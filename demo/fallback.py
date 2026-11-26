"""Fallback für die Demo (Task 5.6): legt den kompletten Bestellprozess ohne Agent an.

Ablauf wie beim Agenten (L 8.3, L 10.1, `demo/prompts.md` Schritt 1): Demo-Dateien importieren (Import vorbereiten),
den fertigen Batch `demo/fallback_batch.json` mit den IDs aus `created` füllen, als **ein** Batch (zwei
`import.include` + Ergänzungen + `workflow.publish`) ausführen und den Workflow mit `validate_workflow` prüfen.

Aufruf im Repo-Root (Backend läuft, `demo/seed.py` ist gelaufen):

    backend/.venv/bin/python demo/fallback.py            # über die REST-API als Anna (Login anna@demo.local / demo)
    backend/.venv/bin/python demo/fallback.py --direct   # ohne Backend direkt gegen die Datenbank (DATABASE_URL)
    backend/.venv/bin/python demo/fallback.py --dry-run  # nur den gefüllten Batch ausgeben

Die eigenen IDs im Batch sind fest (`wf_best`, `tbl_art`, `doc_s2` …). Ein zweiter Lauf auf derselben Datenbank wird
deshalb abgelehnt. Neu anfangen: `docker compose down -v && docker compose up -d`, dann Seed und dieses Skript.

Platzhalter in `fallback_batch.json` (als Wert oder Schlüssel, immer der ganze String):
`$xlsx`/`$docx` (import_id), `$tbl.bestellungen`, `$col.<spalte>` (Spalten aus der Excel-Datei), `$doc.s1`, `$form.s1`,
`$field.<feld>`, `$items.<zeilenliste>` (aus dem Word-Import).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo"
sys.path.insert(0, str(ROOT / "backend"))

TEMPLATE = DEMO / "fallback_batch.json"
XLSX = DEMO / "Bestelluebersicht.xlsx"
DOCX = DEMO / "Bestellformular.docx"
API = os.environ.get("DOCK_API", "http://localhost:8000")
DEFAULT_DB_URL = "postgresql+asyncpg://dock:dock@localhost:5433/dock"
EMAIL, PASSWORD = "anna@demo.local", "demo"
WORKFLOW = "bestellprozess"
DOCX_OWNER = {"workflow": "wf_best", "step": "erfassen"}


class FallbackError(Exception):
    pass


# ── Batch füllen ─────────────────────────────────────────────────────────────


def placeholders(xlsx: dict[str, Any], docx: dict[str, Any]) -> dict[str, str]:
    """Platzhalter -> ID aus den beiden Import-Plänen (`{import_id, created, warnings}`)."""
    tables = xlsx["created"]["tables"]
    table = next((t for t in tables if t["key"] == "bestellungen"), None) or tables[0]
    doc = docx["created"]["documents"][0]
    form = doc.get("form") or {}
    if not form:
        raise FallbackError("Der Word-Import enthält kein Formular")
    values = {"$xlsx": xlsx["import_id"], "$docx": docx["import_id"], "$tbl.bestellungen": table["id"],
              "$doc.s1": doc["id"], "$form.s1": form["block"]}
    values.update({f"$col.{k}": v for k, v in table["column_ids"].items()})
    values.update({f"$field.{k}": v for k, v in form["fields"].items()})
    values.update({f"$items.{k}": v["block"] for k, v in form["line_items"].items()})
    # Der Import nennt die Artikelliste nach ihrer ersten Spalte (`artikelname`), der Batch nennt sie `artikel`.
    if "$items.artikel" not in values and form["line_items"]:
        values["$items.artikel"] = next(iter(form["line_items"].values()))["block"]
    return values


def fill(node: Any, values: dict[str, str]) -> Any:
    """Ersetzt Platzhalter in Werten und Schlüsseln. Unbekannte Platzhalter sind ein Fehler."""
    def one(s: str) -> str:
        if s.startswith("$"):
            if s not in values:
                raise FallbackError(f"Platzhalter {s} ist nicht belegt (Importe geändert?). Bekannt: "
                                    + ", ".join(sorted(values)))
            return values[s]
        return s

    if isinstance(node, dict):
        return {one(k): fill(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [fill(v, values) for v in node]
    if isinstance(node, str):
        return one(node)
    return node


def build_batch(xlsx: dict[str, Any], docx: dict[str, Any], template: dict[str, Any] | None = None) -> dict[str, Any]:
    template = template or json.loads(TEMPLATE.read_text())
    batch = fill(template, placeholders(xlsx, docx))
    batch["batch_id"] = f"{template['batch_id']}_{uuid.uuid4().hex[:8]}"
    return batch


def errors_of(validation: dict[str, Any]) -> list[dict[str, Any]]:
    return [i for i in validation.get("issues", []) if i.get("severity") == "error"]


# ── über die REST-API ────────────────────────────────────────────────────────


def _request(method: str, path: str, token: str | None = None, body: bytes | None = None,
             content_type: str = "application/json") -> Any:
    req = urllib.request.Request(API + path, data=body, method=method)
    req.add_header("Content-Type", content_type)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            return json.loads(res.read() or b"null")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise FallbackError(f"{method} {path}: HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise FallbackError(f"Backend unter {API} nicht erreichbar ({exc.reason}). Läuft `docker compose up`?") from exc


def _post_json(path: str, data: Any, token: str | None = None) -> Any:
    return _request("POST", path, token, json.dumps(data).encode())


def _upload(path: str, token: str, file: Path, fields: dict[str, str]) -> Any:
    boundary = f"----dock{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{file.name}"\r\n'
                 "Content-Type: application/octet-stream\r\n\r\n".encode() + file.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return _request("POST", path, token, b"".join(parts), f"multipart/form-data; boundary={boundary}")


def run_http(dry_run: bool) -> dict[str, Any]:
    token = _post_json("/api/auth/login", {"email": EMAIL, "password": PASSWORD})["access_token"]
    if any(w.get("key") == WORKFLOW for w in _request("GET", "/api/workflows", token) or []):
        raise FallbackError(f"Workflow '{WORKFLOW}' existiert schon. Frische Datenbank: docker compose down -v")
    xlsx = _upload("/api/imports/xlsx", token, XLSX, {})
    docx = _upload("/api/imports/docx", token, DOCX, {"owner": json.dumps(DOCX_OWNER)})
    batch = build_batch(xlsx, docx)
    if dry_run:
        return {"batch": batch, "warnings": xlsx["warnings"] + docx["warnings"]}
    result = _post_json("/api/ops", batch, token)
    validation = _post_json("/api/workflows/validate", {"workflow": WORKFLOW}, token)
    return {"batch": batch, "result": result, "validation": validation,
            "warnings": xlsx["warnings"] + docx["warnings"]}


# ── direkt gegen die Datenbank (ohne laufendes Backend) ──────────────────────


async def run_direct(dry_run: bool, url: str | None = None, actor: Any = None,
                     template: dict[str, Any] | None = None, retag: Any = None) -> dict[str, Any]:
    """`retag(ops, created)` darf die Import-Ops vor dem Speichern ändern (Tests: eindeutige Keys)."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.domain import queries
    from app.imports import store
    from app.imports.docx import parse_docx
    from app.imports.xlsx import parse_xlsx
    from app.ops import pipeline
    from app.ops.context import OpContext
    from app.schemas.common import Actor
    from app.schemas.ops import OpBatch

    engine = create_async_engine(url or os.environ.get("DATABASE_URL", DEFAULT_DB_URL), poolclass=NullPool)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    old_session = pipeline.SessionLocal
    pipeline.SessionLocal = sm
    try:
        async with sm() as s:
            if actor is None:
                row = (await s.execute(text("SELECT id, name FROM users WHERE email = :e"), {"e": EMAIL})).first()
                if row is None:
                    raise FallbackError(f"{EMAIL} fehlt. Zuerst `backend/.venv/bin/python demo/seed.py` ausführen")
                actor = Actor(type="user", id=row[0], name=row[1])
            if template is None:
                exists = (await s.execute(text("SELECT 1 FROM workflows WHERE key = :k"), {"k": WORKFLOW})).first()
                if exists:
                    raise FallbackError(f"Workflow '{WORKFLOW}' existiert schon. Frische Datenbank: docker compose down -v")
            tables = await queries.list_tables(s)
        plans = []
        for source, parsed in (("xlsx", parse_xlsx(XLSX.read_bytes())),
                               ("docx", parse_docx(DOCX.read_bytes(), owner=DOCX_OWNER, tables=tables,
                                                   filename=DOCX.name))):
            if retag:
                retag(parsed.ops, parsed.created)
            async with sm() as s, s.begin():
                plan = await store.save_plan(OpContext(session=s, actor=actor), source, parsed.ops, parsed.created,
                                             parsed.warnings)
            plans.append(plan.model_dump())
        xlsx, docx = plans
        batch = build_batch(xlsx, docx, template)
        out: dict[str, Any] = {"batch": batch, "warnings": xlsx["warnings"] + docx["warnings"]}
        if dry_run:
            return out
        from app.ops.errors import PipelineError
        try:
            result = await pipeline.apply_batch(OpBatch.model_validate(batch), actor)
        except PipelineError as exc:
            raise FallbackError(f"Batch abgelehnt: {exc.error.model_dump(exclude_none=True)}") from exc
        wf_key = next(o["key"] for o in batch["ops"] if o["op"] == "workflow.create")
        async with sm() as s:
            validation = await queries.validate_workflow(s, actor, wf_key, None)
        out.update(result=result.model_dump(), validation=validation)
        return out
    finally:
        pipeline.SessionLocal = old_session
        await engine.dispose()


# ── Ausgabe ──────────────────────────────────────────────────────────────────


def report(out: dict[str, Any], dry_run: bool) -> int:
    for w in out["warnings"]:
        print(f"  Import-Warnung: {w}")
    if dry_run:
        print(json.dumps(out["batch"], indent=2, ensure_ascii=False))
        return 0
    ops = out["batch"]["ops"]
    published = out["result"]["results"].get(str(len(ops) - 1)) or {}
    print(f"Batch {out['batch']['batch_id']}: {len(ops)} Ops ausgeführt, Workflow '{WORKFLOW}' "
          f"veröffentlicht als v{published.get('version', '?')}")
    for w in published.get("warnings", []):
        print(f"  Warnung beim Veröffentlichen: {w.get('code')}: {w.get('message')}")
    errors = errors_of(out["validation"])
    for e in errors:
        print(f"  FEHLER validate_workflow: {e.get('code')}: {e.get('message')}")
    if errors:
        return 1
    print("validate_workflow: ohne Fehler. Angelegt: Tabellen bestellungen + artikel, Workflow bestellprozess, "
          "Dokumente Bestellformular (Schritt erfassen), Genehmigung, Bestellung auslösen, Einkauf")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--direct", action="store_true", help="ohne Backend direkt gegen die Datenbank")
    ap.add_argument("--dry-run", action="store_true", help="Importe vorbereiten, Batch nur ausgeben")
    args = ap.parse_args(argv)
    try:
        out = asyncio.run(run_direct(args.dry_run)) if args.direct else run_http(args.dry_run)
    except FallbackError as exc:
        print(f"Abbruch: {exc}", file=sys.stderr)
        return 2
    return report(out, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
