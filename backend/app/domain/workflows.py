"""Workflows und Runs: Validierung (L 5.7), Veröffentlichen (L 5.3), Ablauf (L 5.4).
Implementierung: Tasks 4.1 (validate/publish), 4.2 (start_run, enter_step, complete_task, cancel_run).

Aufbau der Prüfung (Task 4.1):
- ``check_definition(definition, env)`` ist reine Logik ohne DB. ``env`` (``WorkflowEnv``) ist ein Schnappschuss
  von allem, was die Definition referenziert: Schritt-Dokumente mit Blöcken, Rollen, Nutzer, Tabellenspalten und
  die Unter-Workflow-Kanten aller Workflows (für die Zyklenerkennung).
- ``check_workflow(ctx, definition, workflow_id)`` (bzw. ``validate_workflow`` für freie Definitionen) lädt den Schnappschuss aus der DB (im Batch: inklusive der
  im selben Batch angelegten Dokumente und Rollen, weil alles in derselben Sitzung läuft) und ruft die Prüfung.
- Fehler blockieren das Veröffentlichen, Warnungen nicht. Jede Meldung nennt Schritt, Block und Feld, damit ein
  Agent sie selbst beheben kann. Codes stehen in ``ValidationIssue.code``.

Ausdrücke: Die Pfade in ``{{ }}`` werden hier mit einem eigenen, schlichten Extraktor gelesen (Strings und
Funktionsnamen werden übersprungen). Die volle Auswertung kommt mit Task 3.2 (``domain/expressions.py``).
"""
from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

from app.schemas.common import Actor
from app.schemas.workflows import ValidationIssue, ValidationResult, WorkflowDefinition

END = "end"
ANY_OUTCOME = "*"

_DURATION = re.compile(r"^P(?!$)(\d+Y)?(\d+M)?(\d+W)?(\d+D)?(T(?=\d)(\d+H)?(\d+M)?(\d+S)?)?$")
_EXPR = re.compile(r"\{\{(.*?)\}\}", re.S)
_STRING = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'')
_PATH = re.compile(r"[A-Za-z_]\w*(?:\.\w+)*")
_LITERALS = {"true", "false", "null", "none", "and", "or", "not"}
ROOTS = {"fields", "item", "results", "run", "user", "now", "today"}
RUN_ATTRS = {"id", "title", "status", "steps", "starter", "input", "children", "started_at", "started_by",
             "current_step", "version", "workflow", "result"}
CREATE_ACTIONS = {"create_row", "create_rows"}
STEP_ATTRS = {"outcome", "label", "values", "results", "completed_by", "completed_at"}


# ── Schnappschuss der referenzierten Objekte ─────────────────────────────────


@dataclass
class WorkflowEnv:
    """Alles, was ``check_definition`` über die Umgebung wissen muss (IDs, keine ORM-Objekte)."""

    documents: dict[str, dict[str, Any]] = field(default_factory=dict)  # doc_id -> {title, owner_workflow, owner_step, blocks}
    roles: dict[str, dict[str, Any]] = field(default_factory=dict)  # rol_id -> {key, name, members}
    users: dict[str, str] = field(default_factory=dict)  # usr_id/agt_id -> Name (nur aktive, L 5.8)
    tables: dict[str, dict[str, Any]] = field(default_factory=dict)  # tbl_id -> {key, columns: {col_id: {key, required, default}}}
    subflows: dict[str, set[str]] = field(default_factory=dict)  # wf_id -> Subflow-Ziele (Entwurf und aktuelle Version)
    workflows: set[str] = field(default_factory=set)  # existierende Workflow-IDs
    workflow_id: str | None = None  # der geprüfte Workflow (None = freie Definition)

    def role_id(self, ref: str) -> str | None:
        if ref in self.roles:
            return ref
        return next((rid for rid, r in self.roles.items() if r["key"] == ref), None)


class _Issues:
    def __init__(self) -> None:
        self.items: list[ValidationIssue] = []

    def error(self, code: str, message: str, **where: Any) -> None:
        self.items.append(ValidationIssue(severity="error", code=code, message=message, **where))

    def warning(self, code: str, message: str, **where: Any) -> None:
        self.items.append(ValidationIssue(severity="warning", code=code, message=message, **where))


# ── Ausdrücke ────────────────────────────────────────────────────────────────


def expression_paths(value: str) -> list[str]:
    """Alle Pfade (``fields.name``, ``run.steps.erfassen.values.x``) in den ``{{ }}`` eines Texts.
    Funktionsnamen, String-Literale und Schlüsselwörter zählen nicht."""
    paths: list[str] = []
    for match in _EXPR.finditer(value):
        body = _STRING.sub('""', match.group(1))
        for found in _PATH.finditer(body):
            rest = body[found.end():].lstrip()
            if rest.startswith("("):
                continue
            before = body[found.start() - 1] if found.start() else " "
            if before.isalnum() or before in "._":
                continue
            if found.group(0).lower() in _LITERALS:
                continue
            paths.append(found.group(0))
    return paths


def _strings(value: Any, path: str = "") -> list[tuple[str, str]]:
    """Alle Strings mit ``{{`` in einer verschachtelten Struktur, mit ihrem Pfad."""
    if isinstance(value, str):
        return [(path, value)] if "{{" in value else []
    if isinstance(value, dict):
        return [hit for k, v in value.items() for hit in _strings(v, f"{path}.{k}" if path else str(k))]
    if isinstance(value, list):
        return [hit for i, v in enumerate(value) for hit in _strings(v, f"{path}[{i}]")]
    return []


def _suggest(name: str, known: set[str]) -> str:
    close = difflib.get_close_matches(name, sorted(known), n=1)
    if close:
        return f" Meinten Sie '{close[0]}'?"
    return f" Bekannt: {', '.join(sorted(known))}." if known else ""


# ── Graph ────────────────────────────────────────────────────────────────────


def _graph(definition: WorkflowDefinition, step_keys: set[str],
           outcomes: dict[str, set[str | None]] | None = None) -> dict[str, set[str]]:
    """Kanten der Übergänge. Mit ``outcomes`` (Schritt -> Outcomes seiner Buttons) nur die auslösbaren; Schritte
    ohne Eintrag (kein Dokument, keine Buttons) behalten alle Kanten, sie haben schon eine eigene Meldung."""
    edges: dict[str, set[str]] = {k: set() for k in step_keys}
    exact: dict[str, set[str]] = {}
    for t in definition.transitions:
        exact.setdefault(t.from_, set()).add(t.on)
    for t in definition.transitions:
        produced = (outcomes or {}).get(t.from_)
        if produced and (not produced - exact[t.from_] if t.on == ANY_OUTCOME else t.on not in produced):
            continue
        if t.from_ in step_keys and (t.to in step_keys or t.to == END):
            edges[t.from_].add(t.to)
    return edges


def _reachable(edges: dict[str, set[str]], start: str) -> set[str]:
    seen, todo = set(), [start]
    while todo:
        node = todo.pop()
        if node in seen:
            continue
        seen.add(node)
        todo.extend(edges.get(node, ()))
    return seen


def _dominators(edges: dict[str, set[str]], start: str, nodes: set[str]) -> dict[str, set[str]]:
    """dom[n] = Schritte, die auf JEDEM Weg von `start` nach `n` liegen (inklusive n)."""
    preds: dict[str, set[str]] = {n: set() for n in nodes}
    for src, targets in edges.items():
        for dst in targets:
            if src in nodes and dst in nodes:
                preds[dst].add(src)
    dom = {n: set(nodes) for n in nodes}
    dom[start] = {start}
    changed = True
    while changed:
        changed = False
        for n in nodes - {start}:
            incoming = [dom[p] for p in preds[n]]
            new = (set.intersection(*incoming) if incoming else set()) | {n}
            if new != dom[n]:
                dom[n], changed = new, True
    return dom


# ── Blöcke eines Schritt-Dokuments ───────────────────────────────────────────


def _children(blocks: list[dict[str, Any]]) -> dict[str | None, list[dict[str, Any]]]:
    out: dict[str | None, list[dict[str, Any]]] = {}
    for block in sorted(blocks, key=lambda b: b.get("position") or ""):
        out.setdefault(block.get("parent_id"), []).append(block)
    return out


def _descendants(block_id: str, tree: dict[str | None, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for child in tree.get(block_id, []):
        out.append(child)
        out.extend(_descendants(child["id"], tree))
    return out


@dataclass
class _Form:
    block: dict[str, Any]
    fields: set[str]
    line_items: dict[str, set[str]]  # key -> Spalten-Keys
    descendants: set[str]

    @property
    def buttons(self) -> list[dict[str, Any]]:
        """Buttons nach L 4.3: explizite, sonst automatisch „Speichern“, wenn das Formular Felder hat."""
        props = self.block["props"]
        if props.get("buttons") is not None:
            return props["buttons"]
        if not self.fields:
            return []
        return [{"id": "save", "label": "Speichern", "actions": [a.get("key") for a in props.get("actions") or []]}]


def _forms(blocks: list[dict[str, Any]]) -> list[_Form]:
    tree = _children(blocks)
    forms = []
    for block in blocks:
        if block["type"] != "form":
            continue
        inner = _descendants(block["id"], tree)
        fields = {b["props"].get("key") for b in inner if b["type"] in ("field", "line_items")} - {None}
        line_items = {b["props"]["key"]: {c.get("key") for c in b["props"].get("columns") or []}
                      for b in inner if b["type"] == "line_items" and b["props"].get("key")}
        forms.append(_Form(block, fields, line_items, {b["id"] for b in inner}))
    return forms


# ── Die Prüfung (L 5.7) ──────────────────────────────────────────────────────


def check_definition(definition: WorkflowDefinition, env: WorkflowEnv) -> ValidationResult:
    issues = _Issues()
    steps = definition.steps
    step_keys = {s.key for s in steps}

    # ── Struktur ──
    seen: set[str] = set()
    for i, step in enumerate(steps):
        if step.key in seen:
            issues.error("STEP_DUPLICATE", f"Schritt-Key '{step.key}' kommt mehrfach vor.", step=step.key,
                         field=f"steps[{i}].key")
        seen.add(step.key)
    if not steps:
        issues.error("NO_STEPS", "Der Workflow hat keine Schritte.", field="steps")
    if definition.start not in step_keys:
        issues.error("START_UNKNOWN", f"'start' zeigt auf '{definition.start}', aber es gibt keinen solchen Schritt."
                     + _suggest(definition.start, step_keys), field="start")

    for i, t in enumerate(definition.transitions):
        if t.from_ not in step_keys:
            issues.error("TRANSITION_UNKNOWN_STEP", f"Übergang {i}: 'from' = '{t.from_}' ist kein Schritt."
                         + _suggest(t.from_, step_keys), field=f"transitions[{i}].from")
        if t.to != END and t.to not in step_keys:
            issues.error("TRANSITION_UNKNOWN_STEP", f"Übergang {i}: 'to' = '{t.to}' ist weder ein Schritt noch 'end'."
                         + _suggest(t.to, step_keys | {END}), field=f"transitions[{i}].to")

    pairs: set[tuple[str, str]] = set()
    for i, t in enumerate(definition.transitions):
        if (t.from_, t.on) in pairs:
            issues.error("TRANSITION_DUPLICATE", f"Übergang {i}: von '{t.from_}' mit on = '{t.on}' gibt es schon einen "
                         "Übergang, das Ziel wäre mehrdeutig. Einen davon entfernen.", step=t.from_,
                         field=f"transitions[{i}]")
        pairs.add((t.from_, t.on))

    step_forms = {s.key: _forms(env.documents[s.document]["blocks"]) for s in steps if s.document in env.documents}
    step_outcomes = {k: {b.get("outcome") for f in forms for b in f.buttons} for k, forms in step_forms.items()}

    edges = _graph(definition, step_keys)
    live = _graph(definition, step_keys, step_outcomes)
    live_reachable = _reachable(live, definition.start) - {END} if definition.start in step_keys else set()
    reachable = _reachable(edges, definition.start) - {END} if definition.start in step_keys else set()
    reverse: dict[str, set[str]] = {}
    for src, targets in live.items():
        for dst in targets:
            reverse.setdefault(dst, set()).add(src)
    leads_to_end = _reachable(reverse, END) - {END}
    if definition.start in step_keys:
        for step in steps:
            if step.key not in live_reachable:
                issues.error("STEP_UNREACHABLE", f"Schritt '{step.key}' ist von start ('{definition.start}') aus "
                             "nicht erreichbar. Einen Übergang dorthin anlegen (den ein Button auslöst) oder den "
                             "Schritt entfernen.",
                             step=step.key)
            elif step.key not in leads_to_end:
                issues.error("NO_PATH_TO_END", f"Von Schritt '{step.key}' führt kein Weg zu 'end'. Einen Übergang "
                             f"mit \"to\": \"end\" oder zu einem Schritt mit Weg zum Ende ergänzen, "
                             "den ein Button auslöst.", step=step.key)

    # Zyklen in sich selbst (Schritt kann erneut besucht werden)
    revisitable = {k for k in step_keys if any(k in _reachable(edges, n) for n in edges.get(k, ()))}
    dom = _dominators(edges, definition.start, reachable) if reachable else {}

    # ── Zuständigkeit ──
    def check_assignees(assignees: list[Any], where: str, step_key: str | None) -> None:
        for j, a in enumerate(assignees):
            path = f"{where}[{j}]"
            if a.kind == "role":
                rid = env.role_id(a.role)
                if rid is None:
                    issues.error("ROLE_UNKNOWN", f"Rolle '{a.role}' existiert nicht ({path}). Mit list_roles prüfen "
                                 "oder vorher role.create im selben Batch."
                                 + _suggest(a.role, {r["key"] for r in env.roles.values()}),
                                 step=step_key, field=path)
                elif env.roles[rid]["members"] == 0:
                    issues.warning("ROLE_EMPTY", f"Rolle '{env.roles[rid]['key']}' hat aktuell keine Mitglieder "
                                   f"({path}). Aufgaben würden niemanden erreichen.", step=step_key, field=path)
            elif a.kind == "user" and a.user not in env.users:
                issues.error("USER_UNKNOWN", f"Nutzer '{a.user}' existiert nicht oder ist deaktiviert ({path}).",
                             step=step_key, field=path)
            elif a.kind == "expr":
                check_expr(a.expr, step_key, None, path, form=None, action=None)

    def check_step_path(p: str, parts: list[str], forms: list[_Form], where: dict[str, Any]) -> None:
        """``run.steps.<schritt>.<attr>[.<key>]`` gegen die Formulare dieses Schritts."""
        if len(parts) > 3 and parts[3] not in STEP_ATTRS:
            issues.error("EXPR_UNKNOWN_RUN_PATH", f"'{p}' ({where['field']}): '{parts[3]}' gibt es in einem "
                         "Schritt-Ergebnis nicht." + _suggest(parts[3], STEP_ATTRS), **where)
        elif len(parts) > 4 and parts[3] == "values":
            known = {k for f in forms for k in f.fields}
            if parts[4] not in known:
                issues.error("EXPR_UNKNOWN_FIELD", f"'{p}' ({where['field']}): Schritt '{parts[2]}' hat kein Feld "
                             f"'{parts[4]}'." + _suggest(parts[4], known), **where)
        elif len(parts) > 4 and parts[3] == "results":
            known = {a.get("key") for f in forms for a in f.block["props"].get("actions") or []}
            if parts[4] not in known:
                issues.error("EXPR_UNKNOWN_RESULT", f"'{p}' ({where['field']}): Schritt '{parts[2]}' hat keine Action "
                             f"'{parts[4]}'." + _suggest(parts[4], known), **where)

    def check_expr(value: str, step_key: str | None, block: str | None, path: str, *,
                   form: _Form | None, action: dict[str, Any] | None, dominance: bool = True) -> None:
        for p in expression_paths(value):
            parts = p.split(".")
            root = parts[0]
            where = dict(step=step_key, block=block, field=path)
            if root not in ROOTS:
                issues.error("EXPR_UNKNOWN_ROOT", f"Ausdruck '{value}' ({path}) verwendet '{root}'. Erlaubt sind "
                             f"{', '.join(sorted(ROOTS))}." + _suggest(root, ROOTS), **where)
            elif root == "fields":
                if form is None:
                    issues.warning("EXPR_CONTEXT", f"'{p}' ({path}) steht außerhalb eines Formulars, 'fields' ist "
                                   "dort leer.", **where)
                elif len(parts) > 1 and parts[1] not in form.fields:
                    issues.error("EXPR_UNKNOWN_FIELD", f"Ausdruck '{{{{{p}}}}}' ({path}) verweist auf das "
                                 f"unbekannte Feld '{parts[1]}'." + _suggest(parts[1], form.fields), **where)
            elif root == "item":
                items = _loop_columns(action, form)
                if items is None:
                    issues.error("EXPR_ITEM_OUTSIDE_LOOP", f"'{p}' ({path}) ist nur in einer create_rows-Action "
                                 "mit for_each über eine Zeilenliste gültig.", **where)
                elif len(parts) > 1 and parts[1] not in items:
                    issues.error("EXPR_UNKNOWN_FIELD", f"'{p}' ({path}): Spalte '{parts[1]}' gibt es in der "
                                 "Zeilenliste nicht." + _suggest(parts[1], items), **where)
            elif root == "results":
                keys = {a.get("key") for a in (form.block["props"].get("actions") or [])} if form else set()
                if len(parts) > 1 and parts[1] not in keys:
                    issues.error("EXPR_UNKNOWN_RESULT", f"'{p}' ({path}) verweist auf die unbekannte Action "
                                 f"'{parts[1]}'." + _suggest(parts[1], keys), **where)
            elif root == "run" and len(parts) > 1:
                if parts[1] not in RUN_ATTRS:
                    issues.warning("EXPR_UNKNOWN_RUN_PATH", f"'{p}' ({path}): 'run.{parts[1]}' ist unbekannt."
                                   + _suggest(parts[1], RUN_ATTRS), **where)
                elif parts[1] == "steps" and len(parts) > 2:
                    ref = parts[2]
                    if ref not in step_keys:
                        issues.error("EXPR_UNKNOWN_STEP", f"'{p}' ({path}) verweist auf den unbekannten Schritt "
                                     f"'{ref}'." + _suggest(ref, step_keys), **where)
                    elif dominance and step_key in dom and ref not in dom[step_key] - {step_key}:
                        issues.error("RUN_STEP_NOT_BEFORE", f"'run.steps.{ref}' wird in Schritt '{step_key}' "
                                     f"verwendet, aber '{ref}' liegt nicht auf jedem Weg davor ({path}).", **where)
                    if ref in step_forms:
                        check_step_path(p, parts, step_forms[ref], where)

    for i, step in enumerate(steps):
        sp = f"steps[{i}]"
        if not step.assignees:
            issues.error("STEP_NO_ASSIGNEES", f"Schritt '{step.key}' hat keine assignees.", step=step.key,
                         field=f"{sp}.assignees")
        check_assignees(step.assignees, f"{sp}.assignees", step.key)
        if step.exclude_starter and step.assignees and all(a.kind == "starter" for a in step.assignees):
            issues.error("EXCLUDE_STARTER_ONLY_STARTER", f"Schritt '{step.key}' hat exclude_starter, aber einziger "
                         "Zuständiger ist 'starter'.", step=step.key, field=f"{sp}.exclude_starter")
        for j, other in enumerate(step.exclude_steps):
            if other not in step_keys:
                issues.error("STEP_UNKNOWN", f"exclude_steps von '{step.key}' nennt den unbekannten Schritt "
                             f"'{other}'." + _suggest(other, step_keys), step=step.key, field=f"{sp}.exclude_steps[{j}]")
        if step.due_in is not None and not _DURATION.match(step.due_in):
            issues.error("DUE_INVALID", f"due_in '{step.due_in}' ist keine ISO-Dauer (z. B. 'P2D', 'PT4H').",
                         step=step.key, field=f"{sp}.due_in")
    for where, items in (("starters", definition.starters), ("managers", definition.managers)):
        check_assignees(items, where, None)
        for j, a in enumerate(items):
            if a.kind == "starter" and where == "starters":
                issues.error("STARTER_INVALID", "'starter' ist in starters nicht sinnvoll (es gibt noch keinen "
                             "Antragsteller).", field=f"starters[{j}]")
    if not definition.managers:
        issues.warning("MANAGERS_EMPTY", "managers ist leer: Aufgaben ohne auflösbare Zuständige hätten niemanden, "
                       "und niemand außer dem Antragsteller kann Runs abbrechen.", field="managers")
    if definition.run_title:
        check_expr(definition.run_title, None, None, "run_title", form=None, action=None, dominance=False)

    # ── Schritt-Dokumente und Daten ──
    used_docs: dict[str, str] = {}
    for i, step in enumerate(steps):
        sp = f"steps[{i}].document"
        doc = env.documents.get(step.document)
        if doc is None:
            issues.error("DOCUMENT_UNKNOWN", f"Schritt '{step.key}' zeigt auf das Dokument '{step.document}', das es "
                         "nicht gibt. Dokument mit doc.create (owner = {workflow, step}) anlegen.",
                         step=step.key, field=sp)
            continue
        if step.document in used_docs:
            issues.warning("DOCUMENT_SHARED", f"Schritt '{step.key}' nutzt dasselbe Dokument wie Schritt "
                           f"'{used_docs[step.document]}'.", step=step.key, field=sp)
        used_docs.setdefault(step.document, step.key)
        if env.workflow_id and (doc.get("owner_workflow"), doc.get("owner_step")) != (env.workflow_id, step.key):
            issues.warning("DOCUMENT_OWNER", f"Dokument '{step.document}' hat nicht owner = {{workflow: "
                           f"'{env.workflow_id}', step: '{step.key}'}}.", step=step.key, field=sp)

        blocks = doc["blocks"]
        forms = _forms(blocks)
        outcomes: list[tuple[str, str | None, str]] = []  # (block, outcome, button id)
        creates = False
        for form in forms:
            bid = form.block["id"]
            props = form.block["props"]
            actions = props.get("actions") or []
            action_keys = {a.get("key") for a in actions}
            for j, action in enumerate(actions):
                ap = f"actions[{j}]"
                table = env.tables.get(action.get("table"))
                if table is None:
                    issues.error("TABLE_UNKNOWN", f"Action '{action.get('key')}' schreibt in die unbekannte Tabelle "
                                 f"'{action.get('table')}'.", step=step.key, block=bid, field=f"{ap}.table")
                else:
                    cols = table["columns"]
                    for col in action.get("values") or {}:
                        if col not in cols:
                            issues.error("COLUMN_UNKNOWN", f"Action '{action.get('key')}' schreibt in Spalte "
                                         f"'{col}', die es in '{table['key']}' nicht gibt.",
                                         step=step.key, block=bid, field=f"{ap}.values.{col}")
                    if action.get("type") in CREATE_ACTIONS:
                        given = set(action.get("values") or {})
                        for cid, col in cols.items():
                            if col["required"] and col.get("default") is None and cid not in given:
                                issues.error("REQUIRED_COLUMN_MISSING", f"Pflichtspalte '{table['key']}."
                                             f"{col['key']}' wird von Action '{action.get('key')}' nicht befüllt.",
                                             step=step.key, block=bid, field=f"{ap}.values")
                for path, value in _strings(action, ap):
                    check_expr(value, step.key, bid, path, form=form, action=action)
            for j, button in enumerate(form.buttons):
                bp = f"buttons[{j}]"
                for k, key in enumerate(button.get("actions") or []):
                    if key not in action_keys:
                        issues.error("ACTION_UNKNOWN", f"Button '{button.get('id')}' nennt die unbekannte Action "
                                     f"'{key}'." + _suggest(key, action_keys), step=step.key, block=bid,
                                     field=f"{bp}.actions[{k}]")
                    elif any(a.get("key") == key and a.get("type") in CREATE_ACTIONS for a in actions):
                        creates = True
                for k, key in enumerate(button.get("require") or []):
                    if key not in form.fields:
                        issues.error("FIELD_UNKNOWN", f"Button '{button.get('id')}' verlangt das unbekannte Feld "
                                     f"'{key}'." + _suggest(key, form.fields), step=step.key, block=bid,
                                     field=f"{bp}.require[{k}]")
                outcomes.append((bid, button.get("outcome"), button.get("id")))

        # Ausdrücke in allen anderen Blöcken (Text, Filter, Feld-Defaults, workflow-Block)
        in_form = {d: f for f in forms for d in f.descendants}
        for block in blocks:
            if block["type"] == "form":
                rest = {k: v for k, v in block["props"].items() if k != "actions"}
                form = next(f for f in forms if f.block["id"] == block["id"])
            else:
                rest, form = block["props"], in_form.get(block["id"])
            for path, value in _strings(rest, "props"):
                check_expr(value, step.key, block["id"], path, form=form, action=None)

        # Buttons ↔ Übergänge
        if not outcomes:
            issues.error("STEP_NO_BUTTONS", f"Schritt '{step.key}' hat kein Formular mit Buttons, also kann der Run "
                         "dort nie weiter.", step=step.key, field=sp)
        own = [t for t in definition.transitions if t.from_ == step.key]
        wildcard = any(t.on == ANY_OUTCOME for t in own)
        for bid, outcome, button_id in outcomes:
            if outcome is None:
                if not wildcard:
                    issues.error("BUTTON_NO_OUTCOME", f"Button '{button_id}' in Schritt '{step.key}' hat kein "
                                 "outcome und es gibt keinen Übergang mit on = \"*\", der Run bliebe stehen. outcome "
                                 "setzen oder einen solchen Übergang ergänzen.", step=step.key, block=bid)
            elif not wildcard and not any(t.on == outcome for t in own):
                issues.error("BUTTON_NO_TRANSITION", f"Button '{button_id}' in Schritt '{step.key}' hat Outcome "
                             f"'{outcome}', aber es gibt keinen passenden Übergang. Übergang "
                             f"{{\"from\": \"{step.key}\", \"on\": \"{outcome}\", \"to\": …}} ergänzen.",
                             step=step.key, block=bid)
        produced = {o for _, o, _ in outcomes}
        for t in own:
            if outcomes and t.on != ANY_OUTCOME and t.on not in produced:
                issues.warning("TRANSITION_UNUSED", f"Übergang von '{step.key}' mit on = '{t.on}' wird nie "
                               "ausgelöst, kein Button hat dieses Outcome.", step=step.key)
        if creates and step.key in revisitable:
            issues.warning("REVISIT_CREATE_ROW", f"Schritt '{step.key}' kann erneut besucht werden und enthält "
                           "create_row. Für wiederholte Besuche besser update_row verwenden.", step=step.key)

    # ── Zyklen über Unter-Workflows (L 5.6) ──
    me = env.workflow_id or "<neu>"
    direct = _subflows_of(definition, env)
    for target, block in sorted(direct.items()):
        if target not in env.workflows and target != env.workflow_id:
            issues.error("WORKFLOW_UNKNOWN", f"workflow-Block '{block}' startet den unbekannten Workflow '{target}'.",
                         block=block)
            continue
        cycle = _find_cycle(me, target, env.subflows)
        if cycle is not None:
            issues.error("CYCLE", f"Zyklus über {' → '.join(cycle)}: ein Workflow startet sich selbst als "
                         "Unter-Workflow.", block=block)

    return ValidationResult(ok=not any(i.severity == "error" for i in issues.items), issues=issues.items)


def _loop_columns(action: dict[str, Any] | None, form: _Form | None) -> set[str] | None:
    if action is None or form is None or action.get("type") != "create_rows":
        return None
    paths = expression_paths(action.get("for_each") or "")
    if len(paths) == 1 and paths[0].startswith("fields."):
        return form.line_items.get(paths[0].split(".")[1], set())
    return set() if paths else None


def _subflows_of(definition: WorkflowDefinition, env: WorkflowEnv) -> dict[str, str]:
    """Workflow-ID -> Block-ID der subflow-Blöcke in den Schritt-Dokumenten dieser Definition."""
    out: dict[str, str] = {}
    for step in definition.steps:
        for block in (env.documents.get(step.document) or {}).get("blocks", []):
            if block["type"] == "workflow" and block["props"].get("mode") == "subflow":
                out.setdefault(block["props"]["workflow"], block["id"])
    return out


def _find_cycle(me: str, start: str, graph: dict[str, set[str]]) -> list[str] | None:
    """Pfad me → start → … → me, falls es ihn gibt (der geprüfte Workflow zählt mit seinem neuen Stand)."""
    stack = [(start, [me, start])]
    seen: set[str] = set()
    while stack:
        node, path = stack.pop()
        if node == me:
            return path
        if node in seen:
            continue
        seen.add(node)
        for nxt in sorted(graph.get(node, ())):
            stack.append((nxt, [*path, nxt]))
    return None


# ── Laden aus der DB ─────────────────────────────────────────────────────────


def _j(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


async def load_env(ctx: Any, definition: WorkflowDefinition, workflow_id: str | None) -> WorkflowEnv:
    session, ws = ctx.session, ctx.workspace_id
    env = WorkflowEnv(workflow_id=workflow_id)

    rows = await session.execute(text(
        """SELECT r.id, r.key, r.name, count(mr.member_id)::int AS members FROM roles r
           LEFT JOIN member_roles mr ON mr.role_id = r.id AND mr.workspace_id = r.workspace_id
           WHERE r.workspace_id = :ws GROUP BY r.id"""), {"ws": ws})
    env.roles = {r["id"]: dict(r) for r in rows.mappings()}

    user_ids = [a.user for a in _all_assignees(definition) if a.kind == "user"]
    if user_ids:
        rows = await session.execute(text(
            """SELECT id, name FROM users WHERE active AND id = ANY(CAST(:ids AS text[]))
               UNION ALL
               SELECT id, name FROM agents
               WHERE active AND workspace_id = :ws AND id = ANY(CAST(:ids AS text[]))"""), {"ids": user_ids, "ws": ws})
        env.users = {r["id"]: r["name"] for r in rows.mappings()}

    # Alle Workflows und ihre Schritt-Dokumente (für Zyklen); die Definition des geprüften gilt mit neuem Stand.
    rows = await session.execute(text("SELECT id, draft FROM workflows WHERE workspace_id = :ws"), {"ws": ws})
    drafts = {r["id"]: _j(r["draft"]) for r in rows.mappings()}
    env.workflows = set(drafts)
    step_docs: dict[str, list[str]] = {wid: [s.get("document") for s in (d or {}).get("steps", [])]
                                       for wid, d in drafts.items() if wid != workflow_id}
    own_docs = [s.document for s in definition.steps]
    all_docs = sorted({d for docs in step_docs.values() for d in docs if d} | set(own_docs))

    if all_docs:
        rows = await session.execute(text(
            """SELECT id, title, owner_workflow, owner_step FROM documents
               WHERE workspace_id = :ws AND id = ANY(CAST(:ids AS text[]))"""), {"ws": ws, "ids": all_docs})
        docs = {r["id"]: {**dict(r), "blocks": []} for r in rows.mappings()}
        rows = await session.execute(text(
            """SELECT id, doc_id, parent_id, position, type, props, version FROM blocks
               WHERE doc_id = ANY(CAST(:ids AS text[])) ORDER BY doc_id, position"""), {"ids": list(docs)})
        for r in rows.mappings():
            docs[r["doc_id"]]["blocks"].append({**dict(r), "props": _j(r["props"])})
        env.documents = {d: docs[d] for d in own_docs if d in docs}
        for wid, doc_ids in step_docs.items():
            env.subflows[wid] = {b["props"]["workflow"] for d in doc_ids if d in docs for b in docs[d]["blocks"]
                                 if b["type"] == "workflow" and b["props"].get("mode") == "subflow"}

    # Auch die aktuell veröffentlichten Stände zählen: die startet ein Subflow zur Laufzeit (L 5.6).
    rows = await session.execute(text(
        """SELECT v.workflow_id, v.documents FROM workflow_versions v
           JOIN workflows w ON w.id = v.workflow_id AND w.latest_version = v.version
           WHERE w.workspace_id = :ws"""), {"ws": ws})
    for r in rows.mappings():
        if r["workflow_id"] != workflow_id:
            env.subflows.setdefault(r["workflow_id"], set()).update(
                b["props"]["workflow"] for blocks in _j(r["documents"]).values() for b in blocks
                if b["type"] == "workflow" and b["props"].get("mode") == "subflow")

    table_ids = sorted({a.get("table") for doc in env.documents.values() for b in doc["blocks"]
                        if b["type"] == "form" for a in b["props"].get("actions") or [] if a.get("table")})
    if table_ids:
        rows = await session.execute(text(
            "SELECT id, key FROM tables WHERE workspace_id = :ws AND id = ANY(CAST(:ids AS text[]))"),
            {"ws": ws, "ids": table_ids})
        env.tables = {r["id"]: {"key": r["key"], "columns": {}} for r in rows.mappings()}
        rows = await session.execute(text(
            """SELECT id, table_id, key, required, CAST("default" AS text) AS "default" FROM columns
               WHERE table_id = ANY(CAST(:ids AS text[]))"""), {"ids": list(env.tables)})
        for r in rows.mappings():
            env.tables[r["table_id"]]["columns"][r["id"]] = {
                "key": r["key"], "required": bool(r["required"]),
                "default": None if r["default"] is None else json.loads(r["default"])}
    return env


def _all_assignees(definition: WorkflowDefinition) -> list[Any]:
    return [a for s in definition.steps for a in s.assignees] + list(definition.starters) + list(definition.managers)


async def validate_workflow(ctx: Any, definition: WorkflowDefinition) -> ValidationResult:
    """Alle Fehler und Warnungen aus L 5.7 (Struktur, Zuständigkeit, Daten) in agentenlesbarer Form.
    Prüft eine freie Definition; für einen bestehenden Workflow ``check_workflow`` (Owner- und Zyklenprüfung)."""
    return await check_workflow(ctx, definition, None)


async def check_workflow(ctx: Any, definition: WorkflowDefinition, workflow_id: str | None) -> ValidationResult:
    """Wie ``validate_workflow``, aber im Namen des Workflows ``workflow_id`` (dessen Entwurf ``definition`` ist)."""
    return check_definition(definition, await load_env(ctx, definition, workflow_id))


def errors_message(result: ValidationResult, limit: int = 5) -> str:
    errors = [i for i in result.issues if i.severity == "error"]
    head = "; ".join(i.message for i in errors[:limit])
    more = f" (und {len(errors) - limit} weitere)" if len(errors) > limit else ""
    return f"Workflow ist nicht veröffentlichbar: {head}{more}"


def issue_path(issue: ValidationIssue) -> str:
    parts = [p for p in (f"steps.{issue.step}" if issue.step else None, issue.block, issue.field) if p]
    return ".".join(parts) or issue.code


async def publish_workflow(ctx: Any, workflow_id: str) -> int:
    """Prüft (nur Fehler blockieren), friert die Schritt-Dokumente ein, legt Version n+1 an. Rückgabe: Versionsnummer."""
    version, _ = await publish_with_issues(ctx, workflow_id)
    return version


async def publish_with_issues(ctx: Any, workflow_id: str) -> tuple[int, list[ValidationIssue]]:
    """``publish_workflow`` plus die Meldungen der Prüfung (nur Warnungen, sonst wäre sie gescheitert).
    Wirft ``PipelineError("VALIDATION")`` mit ``details.issues`` (alle Meldungen) und ``details.errors`` (Pfad →
    Meldung)."""
    from app.ops.errors import PipelineError  # domain bleibt ohne harte Abhängigkeit auf die Pipeline

    row = (await ctx.session.execute(
        text("SELECT draft, latest_version FROM workflows WHERE id = :id AND workspace_id = :ws FOR UPDATE"),
        {"id": workflow_id, "ws": ctx.workspace_id})).mappings().first()
    if row is None:
        raise PipelineError("NOT_FOUND", f"Workflow '{workflow_id}' wurde nicht gefunden")
    definition = WorkflowDefinition.model_validate(_j(row["draft"]))
    env = await load_env(ctx, definition, workflow_id)
    result = check_definition(definition, env)
    if not result.ok:
        errors = {issue_path(i): i.message for i in result.issues if i.severity == "error"}
        raise PipelineError("VALIDATION", errors_message(result), {
            "errors": errors, "issues": [i.model_dump(exclude_none=True) for i in result.issues]})

    frozen = {doc_id: [{k: b[k] for k in ("id", "doc_id", "parent_id", "position", "type", "props", "version")}
                       for b in doc["blocks"]]
              for doc_id, doc in env.documents.items()}
    version = (row["latest_version"] or 0) + 1
    await ctx.session.execute(text(
        """INSERT INTO workflow_versions (workflow_id, version, definition, documents, published_by)
           VALUES (:id, :v, CAST(:d AS jsonb), CAST(:docs AS jsonb), CAST(:by AS jsonb))"""),
        {"id": workflow_id, "v": version, "d": json.dumps(definition.model_dump(mode="json", by_alias=True)),
         "docs": json.dumps(frozen), "by": json.dumps(ctx.actor.model_dump(mode="json", exclude_none=True))})
    await ctx.session.execute(text("UPDATE workflows SET latest_version = :v WHERE id = :id"),
                              {"v": version, "id": workflow_id})
    return version, result.issues


# ── Ablauf (Task 4.2) ────────────────────────────────────────────────────────


def parse_iso_duration(raw: str) -> "timedelta":
    """Parst ISO-8601-Dauer (z. B. `P2D`, `PT4H`, `P1W`, `P1DT12H`) zu `timedelta`."""
    from datetime import timedelta

    m = _DURATION.match(raw)
    if not m:
        raise ValueError(f"Ungültige ISO-Dauer: '{raw}'")

    def num(group: int) -> int:
        val = m.group(group)
        return int(val[:-1]) if val else 0

    days = num(1) * 365 + num(2) * 30 + num(3) * 7 + num(4)
    return timedelta(days=days, hours=num(6), minutes=num(7), seconds=num(8))


async def record_run_event(ctx: Any, run_id: str, event_type: str, actor: Actor, *,
                           step: str | None = None, outcome: str | None = None,
                           label: str | None = None, text_val: str | None = None) -> str:
    """Schreibt ein Ereignis in `run_events` (L 5.10)."""
    from app.domain.ids import new_id

    evt_id = new_id("event")
    await ctx.session.execute(
        text("""INSERT INTO run_events (id, run_id, actor, type, step, outcome, label, text)
                VALUES (:id, :run_id, CAST(:actor AS jsonb), :type, :step, :outcome, :label, :text)"""),
        {
            "id": evt_id,
            "run_id": run_id,
            "actor": json.dumps(actor.model_dump(mode="json", exclude_none=True)),
            "type": event_type,
            "step": step,
            "outcome": outcome,
            "label": label,
            "text": text_val,
        },
    )
    return evt_id


async def load_run_bundle(ctx: Any, run_id: str, *, for_update: bool = False
                          ) -> tuple[dict[str, Any], WorkflowDefinition, str]:
    """Lädt Run, zugehörige Workflow-Definition der Run-Version und Workflow-Namen."""
    from app.ops.errors import PipelineError

    lock = " FOR UPDATE OF r" if for_update else ""
    row = (await ctx.session.execute(
        text(f"""SELECT r.*, w.name AS wf_name, v.definition AS wf_def
                 FROM runs r
                 JOIN workflows w ON w.id = r.workflow_id
                 JOIN workflow_versions v ON v.workflow_id = r.workflow_id AND v.version = r.version
                 WHERE r.id = :id{lock}"""),
        {"id": run_id},
    )).mappings().first()
    if row is None:
        raise PipelineError("NOT_FOUND", f"Run '{run_id}' wurde nicht gefunden")
    run = dict(row)
    for col in ("result", "input", "steps", "started_by"):
        run[col] = _j(run[col])
    definition = WorkflowDefinition.model_validate(_j(run.pop("wf_def")))
    wf_name = str(run.pop("wf_name"))
    return run, definition, wf_name


async def _load_lookup_tables(ctx: Any, table_keys: set[str]) -> dict[str, list[dict[str, Any]]]:
    """Lädt Zeilen für `lookup()`-Ausdrücke (Key -> Zeilen mit Spalten-Keys)."""
    from app.ops.context import DEFAULT_WORKSPACE

    ws = getattr(ctx, "workspace_id", DEFAULT_WORKSPACE)
    data: dict[str, list[dict[str, Any]]] = {}
    for key in sorted(table_keys):
        tbl_id = (await ctx.session.execute(
            text("SELECT id FROM tables WHERE workspace_id = :ws AND key = :k"),
            {"ws": ws, "k": key},
        )).scalar_one_or_none()
        if tbl_id is None:
            continue
        cols = {
            c["id"]: c["key"]
            for c in (await ctx.session.execute(
                text("SELECT id, key FROM columns WHERE table_id = :t"), {"t": tbl_id}
            )).mappings()
        }
        rows = (await ctx.session.execute(
            text('SELECT id, "values" FROM rows WHERE table_id = :t ORDER BY position'), {"t": tbl_id}
        )).mappings()
        data[key] = [
            {"id": r["id"], **{cols[c]: v for c, v in (_j(r["values"]) or {}).items() if c in cols}}
            for r in rows
        ]
    return data


async def build_run_expr_context(ctx: Any, run: dict[str, Any], actor: Actor | None = None,
                                 lookup_exprs: list[str] | tuple[str, ...] = ()) -> dict[str, Any]:
    """Baut den Ausdruckskontext (`run.*`, `user.*`, `tables`) für einen Run."""
    from app.domain import expressions
    from app.domain.tasks import effective_id

    started_by = _j(run.get("started_by")) or {}
    starter_id = run.get("started_by_id") or (effective_id(started_by) if started_by else "")
    if started_by.get("on_behalf_of") and starter_id:
        row_name = (await ctx.session.execute(
            text("SELECT name FROM users WHERE id = :id"), {"id": starter_id}
        )).scalar_one_or_none()
        starter_name = row_name or started_by.get("name") or starter_id
    else:
        starter_name = started_by.get("name") or starter_id
    started_at = run.get("started_at")
    run_ctx = {
        "id": run.get("id"),
        "title": run.get("title") or "",
        "status": run.get("status") or "active",
        "current_step": run.get("current_step"),
        "version": run.get("version"),
        "workflow": run.get("workflow_id"),
        "result": _j(run.get("result")),
        "input": _j(run.get("input")) or {},
        "starter": {"id": starter_id, "name": starter_name},
        "started_by": started_by,
        "started_at": started_at.isoformat() if hasattr(started_at, "isoformat") else started_at,
        "steps": _j(run.get("steps")) or {},
    }
    user_ctx = None
    if actor is not None:
        uid = effective_id(actor)
        user_ctx = {"id": uid, "name": actor.name or uid}
    needed_tables: set[str] = set()
    for expr in lookup_exprs:
        needed_tables |= expressions.lookup_tables(expr)
    tables = await _load_lookup_tables(ctx, needed_tables) if needed_tables else {}
    return {"run": run_ctx, "user": user_ctx, "tables": tables}


async def evaluate_run_title(ctx: Any, definition: WorkflowDefinition, workflow_name: str,
                             run: dict[str, Any], fallback: str | None = None) -> str:
    """Wertet `definition.run_title` aus; Fallback ist `Workflow-Name + Datum` (L 5.2)."""
    from datetime import date

    from app.domain import expressions
    from app.domain.expressions import ExpressionError

    default_title = fallback or f"{workflow_name} {date.today().isoformat()}"
    if not definition.run_title:
        return default_title
    eval_ctx = await build_run_expr_context(ctx, run, lookup_exprs=[definition.run_title])
    try:
        val = expressions.evaluate(definition.run_title, eval_ctx)
    except ExpressionError:
        return default_title
    if isinstance(val, str) and val.strip():
        return val.strip()
    return default_title


async def start_run(ctx: Any, run_id: str, workflow: str, input: dict[str, Any] | None, actor: Actor) -> dict[str, Any]:
    """Handler für `run.start` (L 5.4): Startberechtigung, Run anlegen, Event `started`, `enter_step(start)`."""
    from datetime import datetime, timezone

    from app.domain import tasks as T
    from app.ops.context import DEFAULT_WORKSPACE
    from app.ops.errors import PipelineError

    if not run_id.startswith("run_") or len(run_id) <= 3:
        raise PipelineError("VALIDATION", f"Run-IDs beginnen mit 'run_' (erhalten: '{run_id}')",
                            {"errors": {"id": "Präfix 'run_' erforderlich"}})
    exists = (await ctx.session.execute(text("SELECT 1 FROM runs WHERE id = :id"), {"id": run_id})).first()
    if exists is not None:
        raise PipelineError("VALIDATION", f"Run-ID '{run_id}' existiert bereits",
                            {"errors": {"id": f"Run-ID '{run_id}' bereits vergeben"}})

    ws = getattr(ctx, "workspace_id", DEFAULT_WORKSPACE)
    wf_row = (await ctx.session.execute(
        text("SELECT id, name, latest_version FROM workflows WHERE workspace_id = :ws AND (id = :w OR key = :w)"),
        {"ws": ws, "w": workflow},
    )).mappings().first()
    if wf_row is None:
        raise PipelineError("NOT_FOUND", f"Workflow '{workflow}' wurde nicht gefunden")
    if wf_row["latest_version"] is None:
        raise PipelineError("VALIDATION", f"Workflow '{workflow}' ist noch nicht veröffentlicht",
                            {"errors": {"workflow": "Workflow hat noch keine veröffentlichte Version"}})

    wf_id, wf_name, version = wf_row["id"], wf_row["name"], int(wf_row["latest_version"])
    ver_def = (await ctx.session.execute(
        text("SELECT definition FROM workflow_versions WHERE workflow_id = :w AND version = :v"),
        {"w": wf_id, "v": version},
    )).scalar_one()
    definition = WorkflowDefinition.model_validate(_j(ver_def))

    if actor.type != "system" and definition.starters:
        if not await T.matches_assignees(ctx, definition.starters, {"input": input or {}}, actor):
            raise PipelineError("FORBIDDEN", "Sie sind nicht berechtigt, diesen Workflow zu starten",
                                {"workflow": wf_id})

    started_by = await T.enrich_actor(ctx, actor)
    started_by_id = T.effective_id(started_by)
    now = datetime.now(timezone.utc)
    run_stub = {
        "id": run_id,
        "workflow_id": wf_id,
        "version": version,
        "title": "",
        "status": "active",
        "current_step": None,
        "result": None,
        "input": input or {},
        "steps": {},
        "started_by": started_by.model_dump(mode="json", exclude_none=True),
        "started_by_id": started_by_id,
        "started_at": now,
    }
    title = await evaluate_run_title(ctx, definition, wf_name, run_stub)

    await ctx.session.execute(
        text("""INSERT INTO runs (id, workflow_id, version, title, status, current_step, input, steps,
                                  started_by, started_by_id, started_at, updated_at)
                VALUES (:id, :wf, :v, :title, 'active', NULL, CAST(:input AS jsonb), '{}'::jsonb,
                        CAST(:by AS jsonb), :by_id, :at, :at)"""),
        {
            "id": run_id,
            "wf": wf_id,
            "v": version,
            "title": title,
            "input": json.dumps(input or {}),
            "by": json.dumps(started_by.model_dump(mode="json", exclude_none=True)),
            "by_id": started_by_id,
            "at": now,
        },
    )
    await record_run_event(ctx, run_id, "started", started_by)
    task_id = await enter_step(ctx, run_id, definition.start)
    return {
        "id": run_id,
        "workflow": wf_id,
        "version": version,
        "status": "active",
        "current_step": definition.start,
        "task_id": task_id,
    }


async def enter_step(ctx: Any, run_id: str, step: str) -> str:
    """Run auf Schritt setzen, Aufgabe anlegen (`tasks._resolve_assignees`), Event `step_entered`, Titel neu auswerten."""
    from datetime import datetime, timezone

    from app.domain import tasks as T
    from app.domain.ids import new_id
    from app.ops.errors import PipelineError

    run, definition, wf_name = await load_run_bundle(ctx, run_id, for_update=True)
    step_def = next((s for s in definition.steps if s.key == step), None)
    if step_def is None:
        raise PipelineError("VALIDATION", f"Schritt '{step}' existiert in Workflow '{run['workflow_id']}' nicht",
                            {"errors": {"step": f"unbekannter Schritt '{step}'"}})

    await ctx.session.execute(
        text("UPDATE runs SET current_step = :step, updated_at = now() WHERE id = :id"),
        {"step": step, "id": run_id},
    )
    run["current_step"] = step

    candidates, excluded, unassigned = await T._resolve_assignees(ctx, step_def, {**run, "definition": definition})
    due_at = datetime.now(timezone.utc) + parse_iso_duration(step_def.due_in) if step_def.due_in else None
    task_id = new_id("task")
    await ctx.session.execute(
        text("""INSERT INTO tasks (id, run_id, step, status, candidate_users, candidate_roles, excluded, due_at)
                VALUES (:id, :run_id, :step, 'open', CAST(:u AS text[]), CAST(:r AS text[]),
                        CAST(:ex AS text[]), :due)"""),
        {
            "id": task_id,
            "run_id": run_id,
            "step": step,
            "u": candidates.users,
            "r": candidates.roles,
            "ex": excluded,
            "due": due_at,
        },
    )

    system_actor = Actor(type="system", id="workflow", name="Workflow")
    await record_run_event(ctx, run_id, "step_entered", system_actor, step=step)
    if unassigned:
        await record_run_event(
            ctx, run_id, "unassigned", system_actor, step=step,
            text_val=f"Keine auflösbaren Zuständigen für Schritt '{step}', an Manager übergeben",
        )

    new_title = await evaluate_run_title(ctx, definition, wf_name, run, fallback=run["title"])
    if new_title != run["title"]:
        await ctx.session.execute(text("UPDATE runs SET title = :t WHERE id = :id"), {"t": new_title, "id": run_id})

    channels = [f"run:{run_id}", *await T.user_channels_for_candidates(
        ctx, candidates, excluded, [run["started_by_id"]])]
    for ch in sorted(set(channels)):
        await ctx.lock_channel(ch)
    return task_id


async def complete_task(ctx: Any, task_id: str, button: dict[str, Any], values: dict[str, Any],
                        results: dict[str, Any], actor: Actor) -> dict[str, Any]:
    """Nach `form.submit` im Run: Aufgabe `done`, `run.steps[step]` speichern, Übergang nach Outcome,
    Ende oder `enter_step`. Wird von `forms.submit_form` aufgerufen (Task 4.3)."""
    from datetime import datetime, timezone

    from app.domain import tasks as T
    from app.ops.errors import PipelineError

    row = (await ctx.session.execute(
        text("SELECT * FROM tasks WHERE id = :id FOR UPDATE"), {"id": task_id})).mappings().first()
    if row is None:
        raise PipelineError("NOT_FOUND", f"Aufgabe '{task_id}' wurde nicht gefunden")
    if row["status"] == "done":
        raise PipelineError("TASK_DONE", f"Aufgabe '{task_id}' wurde bereits erledigt",
                            {"completed_by": _j(row["completed_by"]), "outcome": row["outcome"]})
    if row["status"] == "cancelled":
        raise PipelineError("TASK_DONE", f"Aufgabe '{task_id}' wurde abgebrochen", {"status": "cancelled"})

    run, definition, wf_name = await load_run_bundle(ctx, row["run_id"], for_update=True)
    if run["status"] != "active" or run["current_step"] != row["step"]:
        raise PipelineError("TASK_DONE", f"Aufgabe '{task_id}' ist nicht mehr aktiv", {"status": run["status"]})

    task_model = T.task_from_row(dict(row))
    if actor.type != "system":
        roles = await T.actor_role_refs(ctx, actor)
        if not T.can_act(actor, roles, task_model):
            who = T.effective_id(actor)
            if who in task_model.excluded:
                raise PipelineError("FORBIDDEN", "Vier-Augen-Prinzip: Sie sind für diese Aufgabe ausgeschlossen",
                                    {"task": task_id})
            is_cand = who in task_model.candidates.users or bool(set(roles) & set(task_model.candidates.roles))
            if is_cand and task_model.claimed_by is not None:
                raise PipelineError(
                    "TASK_CLAIMED",
                    f"Aufgabe wird bereits von {task_model.claimed_by.name or task_model.claimed_by.id} bearbeitet",
                    {"claimed_by": task_model.claimed_by.model_dump(mode="json", exclude_none=True)},
                )
            raise PipelineError("FORBIDDEN", "Sie sind für diese Aufgabe nicht zuständig", {"task": task_id})

    enriched = await T.enrich_actor(ctx, actor)
    now = datetime.now(timezone.utc)
    outcome = button.get("outcome")
    label = button.get("label") or button.get("id") or (outcome or "")

    await ctx.session.execute(
        text("""UPDATE tasks SET status = 'done', completed_by = CAST(:by AS jsonb), completed_at = :at,
                                 outcome = :outcome WHERE id = :id"""),
        {
            "by": json.dumps(enriched.model_dump(mode="json", exclude_none=True)),
            "at": now,
            "outcome": outcome,
            "id": task_id,
        },
    )

    steps_data = dict(_j(run["steps"]) or {})
    steps_data[row["step"]] = {
        "outcome": outcome or "",
        "label": label,
        "values": values,
        "results": results,
        "completed_by": enriched.model_dump(mode="json", exclude_none=True),
        "completed_at": now.isoformat(),
    }
    run["steps"] = steps_data
    await ctx.session.execute(
        text("UPDATE runs SET steps = CAST(:steps AS jsonb), updated_at = :at WHERE id = :id"),
        {"steps": json.dumps(steps_data), "at": now, "id": run["id"]},
    )
    await record_run_event(ctx, run["id"], "step_completed", enriched, step=row["step"], outcome=outcome, label=label)

    trans = next((t for t in definition.transitions
                  if t.from_ == row["step"] and outcome is not None and t.on == outcome), None)
    if trans is None:
        trans = next((t for t in definition.transitions if t.from_ == row["step"] and t.on == ANY_OUTCOME), None)
    if trans is None:
        raise PipelineError("VALIDATION", f"Kein Übergang von Schritt '{row['step']}' für Outcome '{outcome}'",
                            {"errors": {"outcome": f"kein Übergang für '{outcome}'"}})

    if trans.to == END:
        res = {"outcome": outcome or "", "label": label}
        new_title = await evaluate_run_title(ctx, definition, wf_name, run, fallback=run["title"])
        await ctx.session.execute(
            text("""UPDATE runs SET status = 'completed', current_step = NULL, result = CAST(:res AS jsonb),
                                    title = :title, ended_at = :at, updated_at = :at WHERE id = :id"""),
            {"res": json.dumps(res), "title": new_title, "at": now, "id": run["id"]},
        )
        await record_run_event(ctx, run["id"], "completed", enriched, step=row["step"], outcome=outcome, label=label)
        channels = [f"run:{run['id']}", *await T.user_channels_for_candidates(
            ctx, task_model.candidates, task_model.excluded, [run["started_by_id"]])]
        for ch in sorted(set(channels)):
            await ctx.lock_channel(ch)
        return {"status": "completed", "current_step": None, "result": res}

    for ch in sorted(set(await T.user_channels_for_candidates(
        ctx, task_model.candidates, task_model.excluded, [run["started_by_id"]]))):
        await ctx.lock_channel(ch)

    next_task_id = await enter_step(ctx, run["id"], trans.to)
    return {"status": "active", "current_step": trans.to, "task_id": next_task_id}


async def cancel_run(ctx: Any, run_id: str, reason: str | None, actor: Actor) -> dict[str, Any]:
    """`run.cancel`: bricht einen aktiven Run und dessen offene Aufgaben ab (L 5.4)."""
    from app.domain import tasks as T
    from app.ops.errors import PipelineError

    run, definition, _ = await load_run_bundle(ctx, run_id, for_update=True)
    if run["status"] != "active":
        raise PipelineError("VALIDATION", f"Run '{run_id}' ist bereits {run['status']}",
                            {"errors": {"run": f"Run ist nicht aktiv ({run['status']})"}})

    who = T.effective_id(actor)
    allowed = (
        actor.type == "system"
        or (definition.starter_can_cancel and who == run["started_by_id"])
        or await T.is_manager(ctx, definition, run, actor)
    )
    if not allowed:
        raise PipelineError("FORBIDDEN", "Sie dürfen diesen Run nicht abbrechen", {"run": run_id})

    open_tasks = (await ctx.session.execute(
        text("SELECT candidate_users, candidate_roles, excluded FROM tasks WHERE run_id = :id AND status = 'open'"),
        {"id": run_id},
    )).mappings().all()

    await ctx.session.execute(
        text("UPDATE tasks SET status = 'cancelled' WHERE run_id = :id AND status = 'open'"),
        {"id": run_id},
    )
    await ctx.session.execute(
        text("""UPDATE runs SET status = 'cancelled', current_step = NULL, ended_at = now(), updated_at = now()
                WHERE id = :id"""),
        {"id": run_id},
    )
    enriched = await T.enrich_actor(ctx, actor)
    await record_run_event(ctx, run_id, "cancelled", enriched, step=run["current_step"], text_val=reason)

    user_chs: list[str] = [f"user:{run['started_by_id']}"]
    for t in open_tasks:
        cands = T.TaskCandidates(users=list(t["candidate_users"] or []), roles=list(t["candidate_roles"] or []))
        user_chs.extend(await T.user_channels_for_candidates(ctx, cands, list(t["excluded"] or [])))
    for ch in sorted({f"run:{run_id}", *user_chs}):
        await ctx.lock_channel(ch)

    return {"id": run_id, "status": "cancelled"}
