"""MCP-Server (L 8.1, T 2.8), als ASGI-App unter /mcp. Task 5.3 (P5).

Dünne Schicht über der REST-API: Jedes Tool ruft die FastAPI-App im selben Prozess auf (httpx + ASGITransport)
und reicht die Identität des Aufrufers weiter (`Authorization`). Wenn die Stubs später durch echte
Implementierungen ersetzt werden, nutzt der MCP-Server sie automatisch. Schreibzugriffe laufen ausschließlich über
`POST /api/ops` (ein `OpBatch`).

Stdio-Betrieb: `python -m app.mcp.server` (Identität über die Umgebungsvariablen DOCK_TOKEN).
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Literal

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from ulid import ULID

from app.schemas.blocks import BlockIn
from app.schemas.ops import Op, OpBatch
from app.schemas.tables import ColumnIn, ColumnPatch, FilterCondition, SortSpec
from app.schemas.workflows import Assignee, WorkflowDefinition

# host 0.0.0.0: kein DNS-Rebinding-Schutz auf localhost-Hosts (Zugriff aus Docker/LAN); Pfad "/" wegen Mount unter /mcp.
mcp = FastMCP("dock", host="0.0.0.0", streamable_http_path="/")


class ColumnSpec(ColumnIn):
    """Spalte beim Anlegen. `id` ist optional, der MCP-Server erzeugt sie dann selbst."""

    id: str | None = None  # type: ignore[assignment]


# ── Hilfen ───────────────────────────────────────────────────────────────────

def new_id(prefix: str) -> str:
    return f"{prefix}_{str(ULID()).lower()}"


def _identity_headers(ctx: Context | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    req = None
    if ctx is not None:
        try:
            req = ctx.request_context.request
        except Exception:  # außerhalb einer Anfrage
            req = None
    if req is not None and getattr(req, "headers", None) is not None:
        if req.headers.get("authorization"):
            headers["authorization"] = req.headers["authorization"]
    if "authorization" not in headers and os.environ.get("DOCK_TOKEN"):
        headers["authorization"] = f"Bearer {os.environ['DOCK_TOKEN']}"
    return headers


def _error_text(status: int, body: Any) -> str:
    """REST-Fehler als lesbarer Text mit Code und Pfad (z. B. 'CONFLICT at ops[2].base_version: …')."""
    if isinstance(body, dict):
        err = body["error"] if isinstance(body.get("error"), dict) else body
        if "code" in err:  # ApiError
            details = err.get("details") or {}
            errs = details.get("errors") if isinstance(details, dict) else None
            if isinstance(errs, dict) and errs:
                return "\n".join(f"{err['code']} at {path}: {msg}" for path, msg in errs.items())
            text = f"{err['code']}: {err.get('message', '')}"
            return f"{text}\ndetails: {details}" if details else text
        detail = body.get("detail")
        if isinstance(detail, list):  # FastAPI 422
            lines = []
            for d in detail:
                loc = [str(p) for p in d.get("loc", []) if p != "body"]
                lines.append(f"VALIDATION at {'.'.join(loc) or '-'}: {d.get('msg', d)}")
            return "\n".join(lines)
        if detail is not None:
            code = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "CONFLICT"}.get(status, f"HTTP_{status}")
            return f"{code}: {detail}"
    return f"HTTP_{status}: {body}"


async def _request(ctx: Context | None, method: str, path: str, *, params: dict[str, Any] | None = None,
                   json: Any = None, data: dict[str, str] | None = None,
                   files: dict[str, Any] | None = None) -> Any:
    from app.main import app  # lazy: main.py importiert dieses Modul

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://dock",
                                 headers=_identity_headers(ctx), timeout=60) as client:
        resp = await client.request(method, path, params={k: v for k, v in (params or {}).items() if v is not None},
                                    json=json, data=data, files=files)
    try:
        body = resp.json()
    except ValueError:
        body = resp.text
    if resp.status_code >= 400:
        raise ToolError(_error_text(resp.status_code, body))
    return body


def _check_result(body: Any) -> Any:
    """BatchResult-Ablehnungen (Fehler im 2xx-Body) in Tool-Fehler umwandeln."""
    if isinstance(body, dict):
        if isinstance(body.get("error"), dict):
            raise ToolError(_error_text(400, body))
        if body.get("errors"):
            raise ToolError("\n".join(f"VALIDATION at {p}: {m}" for p, m in body["errors"].items()))
    return body


async def _ops(ctx: Context | None, ops: list[dict[str, Any]], base: dict[str, int] | None = None) -> Any:
    batch: dict[str, Any] = {"batch_id": new_id("bat"), "ops": ops}
    if base:
        batch["base"] = base
    return await _post_batch(ctx, batch)


async def _post_batch(ctx: Context | None, batch: Any) -> Any:
    if isinstance(batch, OpBatch):
        batch = _dump(batch)
    return _check_result(await _request(ctx, "POST", "/api/ops", json=batch))


def _dump(model: Any) -> Any:
    return model.model_dump(mode="json", by_alias=True, exclude_none=True)


def _column(c: ColumnSpec | ColumnIn) -> dict[str, Any]:
    d = _dump(c)
    if not d.get("id"):
        d["id"] = new_id("col")
    return d


# ── Finden ───────────────────────────────────────────────────────────────────

@mcp.tool()
async def search(query: str, kinds: list[Literal["document", "table", "workflow"]] | None = None,
                 limit: int = 10, ctx: Context | None = None) -> Any:
    """Volltext- und Vektorsuche über Dokumente, Tabellen und Workflows. Liefert Treffer mit IDs und Snippets."""
    return await _request(ctx, "GET", "/api/search",
                          params={"q": query, "kinds": ",".join(kinds) if kinds else None, "limit": limit})


# ── Tabellen ─────────────────────────────────────────────────────────────────

@mcp.tool()
async def list_tables(ctx: Context | None = None) -> Any:
    """Listet alle Tabellen mit Spalten (Schema). Tabellen und Spalten lassen sich per ID oder Key ansprechen."""
    return await _request(ctx, "GET", "/api/tables")


@mcp.tool()
async def get_table(table: str, ctx: Context | None = None) -> Any:
    """Schema einer Tabelle (ID oder Key): Spalten, Typen, display_column, Version."""
    return await _request(ctx, "GET", f"/api/tables/{table}")


@mcp.tool()
async def query_rows(table: str, filter: list[FilterCondition] | None = None, sort: list[SortSpec] | None = None,
                     limit: int = 100, offset: int = 0, ctx: Context | None = None) -> Any:
    """Liest Zeilen einer Tabelle mit optionalem Filter und Sortierung."""
    body = {"filter": [_dump(f) for f in filter or []], "sort": [_dump(s) for s in sort or []],
            "limit": limit, "offset": offset}
    return await _request(ctx, "POST", f"/api/tables/{table}/rows/query", json=body)


@mcp.tool()
async def create_table(key: str, name: str, columns: list[ColumnSpec], display_column: str | None = None,
                       ctx: Context | None = None) -> Any:
    """Legt eine Tabelle an (op `table.create`). Spalten brauchen key, name, type; `id` wird sonst erzeugt.
    Mehrere zusammenhängende Änderungen besser in EINEM `apply_ops`-Batch senden."""
    table_id = new_id("tbl")
    op: dict[str, Any] = {"op": "table.create", "id": table_id, "key": key, "name": name,
                          "columns": [_column(c) for c in columns]}
    if display_column:
        op["display_column"] = display_column
    return {"id": table_id, "result": await _ops(ctx, [op])}


@mcp.tool()
async def update_table(table: str, name: str | None = None, key: str | None = None,
                       display_column: str | None = None, ctx: Context | None = None) -> Any:
    """Benennt eine Tabelle um bzw. ändert Key oder display_column (op `table.update`)."""
    op: dict[str, Any] = {"op": "table.update", "table": table}
    op.update({k: v for k, v in {"name": name, "key": key, "display_column": display_column}.items() if v is not None})
    return await _ops(ctx, [op])


@mcp.tool()
async def add_column(table: str, column: ColumnSpec, after: str | None = None, ctx: Context | None = None) -> Any:
    """Fügt eine Spalte hinzu (op `column.add`)."""
    op: dict[str, Any] = {"op": "column.add", "table": table, "column": _column(column)}
    if after:
        op["after"] = after
    return await _ops(ctx, [op])


@mcp.tool()
async def update_column(table: str, column: str, patch: ColumnPatch, ctx: Context | None = None) -> Any:
    """Ändert Name, Key, Typ oder Eigenschaften einer Spalte (op `column.update`). Fehler IN_USE: Spalte wird verwendet."""
    return await _ops(ctx, [{"op": "column.update", "table": table, "column": column, "patch": _dump(patch)}])


@mcp.tool()
async def delete_column(table: str, column: str, ctx: Context | None = None) -> Any:
    """Löscht eine Spalte (op `column.delete`). Fehler IN_USE nennt die Verwendungen (Formulare, Workflows)."""
    return await _ops(ctx, [{"op": "column.delete", "table": table, "column": column}])


@mcp.tool()
async def insert_rows(table: str, rows: list[dict[str, Any]], ctx: Context | None = None) -> Any:
    """Fügt Zeilen ein (op `row.insert`). `rows` = Liste von {Spalten-Key: Wert}."""
    new_rows = [{"id": new_id("row"), "values": r} for r in rows]
    result = await _ops(ctx, [{"op": "row.insert", "table": table, "rows": new_rows}])
    return {"ids": [r["id"] for r in new_rows], "result": result}


@mcp.tool()
async def update_row(table: str, row: str, values: dict[str, Any], ctx: Context | None = None) -> Any:
    """Ändert Werte einer Zeile (op `row.update`); nur geänderte Spalten angeben."""
    return await _ops(ctx, [{"op": "row.update", "table": table, "row": row, "values": values}])


@mcp.tool()
async def delete_rows(table: str, rows: list[str], ctx: Context | None = None) -> Any:
    """Löscht Zeilen anhand ihrer IDs (op `row.delete`)."""
    return await _ops(ctx, [{"op": "row.delete", "table": table, "rows": rows}])


# ── Dokumente ────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_document(doc: str, format: Literal["md", "json"] = "md", run: str | None = None,
                       ctx: Context | None = None) -> Any:
    """Liest ein Dokument. `md`: Markdown mit Block-IDs (`{#blk_…}`), `json`: Blockliste mit Versionen und
    Actions/Buttons der Formulare. Mit `run` im Kontext eines Runs ausgewertet."""
    if format == "md":
        body = await _request(ctx, "GET", f"/api/documents/{doc}/markdown", params={"run": run})
        return body.get("markdown", body) if isinstance(body, dict) else body
    return await _request(ctx, "GET", f"/api/documents/{doc}", params={"run": run})


@mcp.tool()
async def create_document(title: str, markdown: str | None = None, blocks: list[BlockIn] | None = None,
                          owner: dict[str, str] | None = None, ctx: Context | None = None) -> Any:
    """Legt ein Dokument an (op `doc.create`) aus Markdown (Syntax wie `get_document`, Server parst in Blöcke) ODER
    aus `blocks`. Actions und Buttons von Formularen stehen nicht im Markdown, sondern werden mit `block.update`
    (edit_document / apply_ops) gesetzt. `owner` = {"workflow": …, "step": …} macht es zum Schritt-Dokument."""
    if (markdown is None) == (blocks is None):
        raise ToolError("VALIDATION at markdown|blocks: genau eines von beiden angeben")
    doc_id = new_id("doc")
    op: dict[str, Any] = {"op": "doc.create", "id": doc_id, "title": title}
    if markdown is not None:
        op["markdown"] = markdown
    else:
        op["blocks"] = [_dump(b) for b in blocks or []]
    if owner:
        op["owner"] = owner
    return {"id": doc_id, "result": await _ops(ctx, [op])}


@mcp.tool()
async def edit_document(doc: str, ops: list[Op], base_version: dict[str, int] | None = None,
                        ctx: Context | None = None) -> Any:
    """Bearbeitet ein Dokument mit `block.insert|update|move|delete`, `text.edit` und `doc.update`.
    `base_version` = {block_id: zuletzt gelesene Version}; bei veraltetem Stand kommt CONFLICT, dann neu lesen
    (get_document format=json). BLOCK_IN_USE: ein Mensch tippt gerade im Block, später erneut versuchen."""
    allowed = ("block.", "text.edit", "doc.update")
    raw = [_dump(o) for o in ops]
    for i, o in enumerate(raw):
        if not o["op"].startswith(allowed):
            raise ToolError(f"VALIDATION at ops[{i}].op: '{o['op']}' ist in edit_document nicht erlaubt (apply_ops nutzen)")
        if o["op"] == "block.insert" and o.get("doc") != doc:
            raise ToolError(f"VALIDATION at ops[{i}].doc: muss '{doc}' sein")
    return await _ops(ctx, raw, base_version)


# ── Import ───────────────────────────────────────────────────────────────────

def _read_upload(file_path: str | None, content_base64: str | None, filename: str | None) -> tuple[str, bytes]:
    if bool(file_path) == bool(content_base64):
        raise ToolError("VALIDATION at file_path|content_base64: genau eines von beiden angeben")
    if file_path:
        p = Path(file_path).expanduser()
        if not p.is_file():
            raise ToolError(f"NOT_FOUND at file_path: Datei '{file_path}' nicht gefunden")
        return filename or p.name, p.read_bytes()
    try:
        return filename or "upload", base64.b64decode(content_base64 or "", validate=True)
    except ValueError as e:
        raise ToolError(f"VALIDATION at content_base64: kein gültiges Base64 ({e})") from e


@mcp.tool()
async def import_xlsx(file_path: str | None = None, content_base64: str | None = None, filename: str | None = None,
                      sheet: str | None = None, apply: bool = False, ctx: Context | None = None) -> Any:
    """Importiert eine Excel-Datei (.xlsx) als Tabelle(n). ZUERST Dateien importieren, dann den Rest planen.
    `file_path` (lokale Datei, stdio) ODER `content_base64` (HTTP). Antwort: {import_id, created, warnings}; es wird
    noch nichts geschrieben. Danach EIN `apply_ops`-Batch mit {"op":"import.include","import_id":…} plus Ergänzungen
    (Spalten, Rollen via list_roles, Aktionen, Buttons, Workflow, publish). `apply=true` führt den Import sofort aus.
    Warnungen lesen und selbst beheben."""
    name, content = _read_upload(file_path, content_base64, filename)
    data = {"apply": "true" if apply else "false", **({"sheet": sheet} if sheet else {})}
    return await _request(ctx, "POST", "/api/imports/xlsx", data=data, files={"file": (name, content)})


@mcp.tool()
async def import_docx(file_path: str | None = None, content_base64: str | None = None, filename: str | None = None,
                      title: str | None = None, owner: str | None = None, bind_table: str | None = None,
                      apply: bool = False, ctx: Context | None = None) -> Any:
    """Importiert ein Word-Dokument (.docx) als Dokument mit Formular. ZUERST Dateien importieren (auch Excel, damit
    `bind_table` auf die importierte Tabelle zeigen kann). `file_path` (lokal) ODER `content_base64`. Antwort:
    {import_id, created, warnings}. Das Formular hat keine Actions/Buttons (Warnung beachten): diese in EINEM
    `apply_ops`-Batch zusammen mit {"op":"import.include","import_id":…}, Workflow und publish ergänzen.
    `bind_table` erzeugt Action create_row + Button „Speichern“."""
    name, content = _read_upload(file_path, content_base64, filename)
    data = {"apply": "true" if apply else "false"}
    data.update({k: v for k, v in {"title": title, "owner": owner, "bind_table": bind_table}.items() if v})
    return await _request(ctx, "POST", "/api/imports/docx", data=data, files={"file": (name, content)})


# ── Formulare, Workflows ─────────────────────────────────────────────────────

@mcp.tool()
async def validate_form(doc: str, block: str, ctx: Context | None = None) -> Any:
    """Prüft ein Formular (form-Block) auf Fehler und Warnungen (z. B. Formular schreibt nirgends hin). Vor dem
    Veröffentlichen eines Workflows aufrufen."""
    return await _request(ctx, "POST", f"/api/documents/{doc}/blocks/{block}/validate")


@mcp.tool()
async def list_workflows(ctx: Context | None = None) -> Any:
    """Listet alle Workflows."""
    return await _request(ctx, "GET", "/api/workflows")


@mcp.tool()
async def get_workflow(workflow: str, ctx: Context | None = None) -> Any:
    """Liest die Definition eines Workflows (ID oder Key)."""
    return await _request(ctx, "GET", f"/api/workflows/{workflow}")


@mcp.tool()
async def create_workflow(key: str, name: str, definition: WorkflowDefinition, ctx: Context | None = None) -> Any:
    """Legt einen Workflow-Entwurf an (op `workflow.create`). Erst `list_roles` aufrufen, um gültige Rollen für die
    Zuständigen zu kennen. Besser: zusammen mit Dokumenten in EINEM `apply_ops`-Batch anlegen, dann
    `validate_workflow`, dann `publish_workflow`."""
    wf_id = new_id("wf")
    op = {"op": "workflow.create", "id": wf_id, "key": key, "name": name, "definition": _dump(definition)}
    return {"id": wf_id, "result": await _ops(ctx, [op])}


@mcp.tool()
async def update_workflow(workflow: str, definition: WorkflowDefinition, ctx: Context | None = None) -> Any:
    """Ersetzt die Definition des Workflow-Entwurfs (op `workflow.update`)."""
    return await _ops(ctx, [{"op": "workflow.update", "workflow": workflow, "definition": _dump(definition)}])


@mcp.tool()
async def validate_workflow(workflow: str | None = None, definition: dict[str, Any] | None = None,
                            ctx: Context | None = None) -> Any:
    """Prüft einen Workflow (ID/Key) oder eine Definition auf Fehler und Warnungen (L 5.7). Meldungen lesen,
    korrigieren, erneut prüfen, erst dann `publish_workflow`."""
    if (workflow is None) == (definition is None):
        raise ToolError("VALIDATION at workflow|definition: genau eines von beiden angeben")
    body = {"workflow": workflow} if workflow else {"definition": definition}
    return await _request(ctx, "POST", "/api/workflows/validate", json=body)


@mcp.tool()
async def publish_workflow(workflow: str, ctx: Context | None = None) -> Any:
    """Veröffentlicht den Workflow als neue Version (op `workflow.publish`). Vorher `validate_workflow`."""
    return await _ops(ctx, [{"op": "workflow.publish", "workflow": workflow}])


# ── Runs ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def start_run(workflow: str, input: dict[str, Any] | None = None, ctx: Context | None = None) -> Any:
    """Startet einen Run (op `run.start`)."""
    run_id = new_id("run")
    op: dict[str, Any] = {"op": "run.start", "id": run_id, "workflow": workflow}
    if input:
        op["input"] = input
    return {"id": run_id, "result": await _ops(ctx, [op])}


@mcp.tool()
async def list_runs(workflow: str | None = None, started_by: Literal["me", "any"] = "me", status: str | None = None,
                    ctx: Context | None = None) -> Any:
    """Listet Runs („Meine Anträge“ mit started_by=me, sonst any)."""
    return await _request(ctx, "GET", "/api/runs",
                          params={"workflow": workflow, "started_by": started_by, "status": status})


@mcp.tool()
async def get_run(run: str, ctx: Context | None = None) -> Any:
    """Statusansicht eines Runs inkl. Events (wer ist gerade zuständig, seit wann, Verlauf)."""
    return await _request(ctx, "GET", f"/api/runs/{run}")


@mcp.tool()
async def cancel_run(run: str, reason: str | None = None, ctx: Context | None = None) -> Any:
    """Bricht einen Run ab (op `run.cancel`)."""
    op = {"op": "run.cancel", "run": run, **({"reason": reason} if reason else {})}
    return await _ops(ctx, [op])


@mcp.tool()
async def comment_run(run: str, text: str, ctx: Context | None = None) -> Any:
    """Schreibt einen Kommentar in den Verlauf eines Runs (op `run.comment`)."""
    return await _ops(ctx, [{"op": "run.comment", "run": run, "text": text}])


# ── Aufgaben ─────────────────────────────────────────────────────────────────

@mcp.tool()
async def list_tasks(assigned_to: Literal["me"] = "me", status: str = "open", workflow: str | None = None,
                     ctx: Context | None = None) -> Any:
    """Aufgabenliste des Aufrufers (bzw. der Person, in deren Auftrag der Agent handelt)."""
    return await _request(ctx, "GET", "/api/tasks",
                          params={"assigned_to": assigned_to, "status": status, "workflow": workflow})


@mcp.tool()
async def get_task(task: str, ctx: Context | None = None) -> Any:
    """Aufgabe mit Schritt-Dokument (Markdown, im Run-Kontext ausgewertet), verfügbaren Buttons (inkl. `require`),
    Feldern und `can_act`. IMMER vor `complete_task` aufrufen, um gültige Button-IDs und Pflichtfelder zu kennen."""
    return await _request(ctx, "GET", f"/api/tasks/{task}")


@mcp.tool()
async def claim_task(task: str, ctx: Context | None = None) -> Any:
    """Übernimmt eine Aufgabe (op `task.claim`)."""
    return await _ops(ctx, [{"op": "task.claim", "task": task}])


@mcp.tool()
async def release_task(task: str, ctx: Context | None = None) -> Any:
    """Gibt eine übernommene Aufgabe wieder frei (op `task.release`)."""
    return await _ops(ctx, [{"op": "task.release", "task": task}])


@mcp.tool()
async def reassign_task(task: str, assignees: list[Assignee], ctx: Context | None = None) -> Any:
    """Weist eine Aufgabe neu zu (op `task.reassign`)."""
    return await _ops(ctx, [{"op": "task.reassign", "task": task, "assignees": [_dump(a) for a in assignees]}])


@mcp.tool()
async def complete_task(task: str, button: str, values: dict[str, Any] | None = None,
                        ctx: Context | None = None) -> Any:
    """Erledigt eine Aufgabe: sendet das Formular des Schritts mit Button und Werten (op `form.submit`).
    Vorher `get_task` aufrufen (Button-IDs, Pflichtfelder, `require`). Prüffehler stehen pro Feld im Fehlertext."""
    detail = await _request(ctx, "GET", f"/api/tasks/{task}")
    if not detail.get("form_block"):
        raise ToolError(f"VALIDATION at task: Aufgabe {task} hat kein Formular")
    if not detail.get("can_act", True):
        raise ToolError(f"FORBIDDEN at task: Aufrufer darf Aufgabe {task} nicht bearbeiten")
    ids = [b["id"] for b in detail.get("buttons", [])]
    if ids and button not in ids:
        raise ToolError(f"VALIDATION at button: '{button}' unbekannt, verfügbar: {', '.join(ids)}")
    op: dict[str, Any] = {"op": "form.submit", "submission_id": new_id("sub"), "form_block": detail["form_block"],
                          "button": button, "run": detail["task"]["run_id"]}
    if values:
        op["values"] = values
    return await _ops(ctx, [op])


# ── Rollen, Nutzer ───────────────────────────────────────────────────────────

@mcp.tool()
async def list_roles(ctx: Context | None = None) -> Any:
    """Listet Rollen (IDs, Keys, Mitgliederzahl). Vor dem Anlegen von Workflows aufrufen, damit Zuständige
    existierende Rollen verwenden."""
    return await _request(ctx, "GET", "/api/roles")


@mcp.tool()
async def list_users(role: str | None = None, ctx: Context | None = None) -> Any:
    """Listet Nutzer, optional gefiltert nach Rolle."""
    return await _request(ctx, "GET", "/api/users", params={"role": role})


@mcp.tool()
async def create_role(key: str, name: str, ctx: Context | None = None) -> Any:
    """Legt eine Rolle an (op `role.create`)."""
    role_id = new_id("rol")
    return {"id": role_id, "result": await _ops(ctx, [{"op": "role.create", "id": role_id, "key": key, "name": name}])}


@mcp.tool()
async def set_user_roles(user: str, add: list[str] | None = None, remove: list[str] | None = None,
                         ctx: Context | None = None) -> Any:
    """Fügt Rollen hinzu bzw. entfernt sie bei einem Nutzer (op `user.set_roles`)."""
    return await _ops(ctx, [{"op": "user.set_roles", "user": user, "add": add or [], "remove": remove or []}])


@mcp.tool()
async def set_agent_roles(agent: str, add: list[str] | None = None, remove: list[str] | None = None,
                          ctx: Context | None = None) -> Any:
    """Fügt Rollen hinzu bzw. entfernt sie bei einem Agenten (op `agent.set_roles`)."""
    return await _ops(ctx, [{"op": "agent.set_roles", "agent": agent, "add": add or [], "remove": remove or []}])


# ── Allgemein ────────────────────────────────────────────────────────────────

@mcp.tool()
async def apply_ops(batch: OpBatch, ctx: Context | None = None) -> Any:
    """Führt einen atomaren Batch von Operationen aus: entweder klappt alles oder nichts. Typischer Ablauf für
    ganze Prozesse: 1. Dateien importieren (import_xlsx/import_docx), 2. list_roles, 3. EIN Batch mit
    {"op":"import.include","import_id":…} plus Ergänzungen (Rollen, Spalten, Actions/Buttons per block.update,
    workflow.create, workflow.publish). Fehler (CONFLICT, IN_USE, BLOCK_IN_USE, VALIDATION mit Pfad) lesen und den
    Batch korrigiert erneut senden. `batch_id` und alle IDs (Präfix + ULID) erzeugt der Aufrufer."""
    return await _post_batch(ctx, batch)


if __name__ == "__main__":
    mcp.run("stdio")
