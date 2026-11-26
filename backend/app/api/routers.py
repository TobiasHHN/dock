"""Stub-Router (Task 0.4): liefern Beispieldaten, damit das Frontend ohne Backend-Logik bauen kann.
Phase 1: Jeder Owner ersetzt die Stubs seines Bereichs durch echte Implementierungen (Task-IDs in den Kommentaren)."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ROLE_NAMES, CurrentUser, create_access_token, current_user, hash_password, verify_password
from app.db.session import get_session
from app.domain import forms, queries
from app.domain.ids import new_id
from app.ops.errors import PipelineError
from app.ops.pipeline import apply_batch
from app.schemas import api as A
from app.schemas.blocks import DocumentMarkdown, DocumentOut, DocumentSummary
from app.schemas.ops import BatchError, BatchResult, OpBatch
from app.schemas.tables import RowsPage, Table
from app.schemas.workflows import (
    ButtonInfo, Notification, RunListItem, RunStatusView, TaskDetail, TaskListItem,
    ValidationResult, Workflow, WorkflowSummary,
)
from app.schemas.ws import WsMessages

from . import stub_data as D

User = Annotated[CurrentUser, Depends(current_user)]

# ── Auth, Nutzer, Rollen (1.1) ───────────────────────────────────────────────
auth = APIRouter(prefix="/api", tags=["auth"])


@auth.post("/auth/signup", response_model=A.TokenResponse)
async def signup(body: A.SignupRequest, session: AsyncSession = Depends(get_session)):
    email = body.email.strip().lower()
    name = body.name.strip()
    if "@" not in email or not name:
        raise HTTPException(status_code=422, detail="Name und gültige E-Mail-Adresse sind erforderlich")
    if len(body.password) < 8 or len(body.password) > 1024:
        raise HTTPException(status_code=422, detail="Das Passwort muss zwischen 8 und 1024 Zeichen lang sein")

    user_id = new_id("user")
    try:
        async with session.begin():
            exists = await session.execute(text("SELECT 1 FROM users WHERE email = :email"), {"email": email})
            if exists.first() is not None:
                raise HTTPException(status_code=409, detail="Diese E-Mail-Adresse ist bereits registriert")

            role_key = body.role
            role_id = new_id("role")
            await session.execute(
                text("""INSERT INTO roles (id, workspace_id, key, name)
                        VALUES (:id, 'ws_demo', :key, :name)
                        ON CONFLICT (workspace_id, key) DO NOTHING"""),
                {"id": role_id, "key": role_key, "name": ROLE_NAMES[role_key]},
            )
            role_row = (await session.execute(
                text("SELECT id FROM roles WHERE workspace_id = 'ws_demo' AND key = :key"),
                {"key": role_key},
            )).mappings().first()
            await session.execute(
                text("""INSERT INTO users (id, name, email, password_hash, active)
                        VALUES (:id, :name, :email, :password_hash, true)"""),
                {"id": user_id, "name": name, "email": email, "password_hash": hash_password(body.password)},
            )
            await session.execute(
                text("""INSERT INTO member_roles (workspace_id, member_id, role_id)
                        VALUES ('ws_demo', :user_id, :role_id)"""),
                {"user_id": user_id, "role_id": role_row["id"]},
            )
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Diese E-Mail-Adresse ist bereits registriert") from None

    user = A.UserOut(id=user_id, name=name, email=email, roles=[body.role])
    return A.TokenResponse(access_token=create_access_token(user_id, [body.role]), user=user)


@auth.post("/auth/login", response_model=A.TokenResponse)
async def login(body: A.LoginRequest, session: AsyncSession = Depends(get_session)):
    email = body.email.strip().lower()
    result = await session.execute(
        text("""SELECT id, name, email, password_hash, active FROM users WHERE email = :email"""),
        {"email": email},
    )
    row = result.mappings().first()
    if row is None or not row["active"] or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="E-Mail-Adresse oder Passwort ist falsch",
                            headers={"WWW-Authenticate": "Bearer"})
    role_result = await session.execute(
        text("""SELECT r.key FROM roles AS r
               JOIN member_roles AS mr ON mr.role_id = r.id
               WHERE mr.member_id = :user_id AND mr.workspace_id = 'ws_demo'
               ORDER BY r.key"""),
        {"user_id": row["id"]},
    )
    role_keys = [r["key"] for r in role_result.mappings().all()]
    user = A.UserOut(id=row["id"], name=row["name"], email=row["email"], roles=role_keys)
    return A.TokenResponse(access_token=create_access_token(row["id"], role_keys), user=user)


@auth.get("/me", response_model=A.UserOut)
async def me(user: User):
    return A.UserOut(**user.model_dump())


@auth.get("/roles", response_model=list[A.RoleOut])
async def roles(user: User, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        text("""SELECT r.id, r.key, r.name, count(mr.member_id)::int AS member_count
               FROM roles AS r
               LEFT JOIN member_roles AS mr ON mr.role_id = r.id AND mr.workspace_id = r.workspace_id
               WHERE r.workspace_id = 'ws_demo'
               GROUP BY r.id, r.key, r.name
               ORDER BY r.key""")
    )
    return [A.RoleOut(**dict(row)) for row in result.mappings().all()]


@auth.get("/users", response_model=list[A.UserOut])
async def users(user: User, role: str | None = None, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        text("""SELECT u.id, u.name, u.email,
                      COALESCE(array_agg(r.key) FILTER (WHERE r.key IS NOT NULL), '{}') AS roles
               FROM users AS u
               LEFT JOIN member_roles AS mr ON mr.member_id = u.id AND mr.workspace_id = 'ws_demo'
               LEFT JOIN roles AS r ON r.id = mr.role_id AND r.workspace_id = 'ws_demo'
               WHERE u.active = true
               GROUP BY u.id
               ORDER BY u.name""")
    )
    out = [A.UserOut(**dict(row)) for row in result.mappings().all()]
    return [u for u in out if role is None or role in u.roles]


# ── Ops: der einzige Schreibweg (1.2) ────────────────────────────────────────
ops = APIRouter(prefix="/api", tags=["ops"])


@ops.post("/ops", response_model=BatchResult)
async def apply_ops(batch: OpBatch, user: User):
    """Fehler: HTTP-Status je ErrorCode (`ops/errors.py`), Body `BatchError`."""
    try:
        return await apply_batch(batch, user.actor)
    except PipelineError as exc:
        return JSONResponse(status_code=exc.status_code,
                            content=BatchError(batch_id=batch.batch_id, error=exc.error).model_dump(mode="json"))


# ── Dokumente (1.4) ──────────────────────────────────────────────────────────
documents = APIRouter(prefix="/api", tags=["documents"])


def _http(exc: PipelineError) -> HTTPException:
    return HTTPException(exc.status_code, exc.error.message)


@documents.get("/documents", response_model=list[DocumentSummary])
async def list_documents(user: User, session: AsyncSession = Depends(get_session)):
    return await queries.list_documents(session)


@documents.get("/documents/{doc}", response_model=DocumentOut)
async def get_document_json(doc: str, user: User, run: str | None = None,
                            session: AsyncSession = Depends(get_session)):
    try:
        if run is not None:
            return await queries.fetch_document(session, doc, run=run, user=user)
        return await queries.fetch_document(session, doc)
    except PipelineError as exc:
        raise _http(exc) from exc


@documents.get("/documents/{doc}/markdown", response_model=DocumentMarkdown)
async def get_document_markdown(doc: str, user: User, run: str | None = None,
                                session: AsyncSession = Depends(get_session)):
    """Markdown mit Block-IDs (L 8.2); Actions und Buttons nur im JSON. Mit `run` im Kontext eines Runs ausgewertet."""
    try:
        if run is not None:
            return await queries.fetch_document_markdown(session, doc, run=run, user=user)
        return await queries.fetch_document_markdown(session, doc)
    except PipelineError as exc:
        raise _http(exc) from exc


@documents.post("/documents/{doc}/blocks/{block}/validate", response_model=A.FormValidateResult, tags=["forms"])
async def validate_form(doc: str, block: str, user: User, session: AsyncSession = Depends(get_session)):
    """Prüfung aus L 5.7 (Daten) für ein Formular: Warnungen mit Block und Feld, z. B. Tippfehler in Ausdrücken."""
    try:
        return await forms.validate_form_in_db(session, doc, block)
    except PipelineError as exc:
        raise _http(exc) from exc


# ── Tabellen (1.3, 3.1) ──────────────────────────────────────────────────────
tables = APIRouter(prefix="/api", tags=["tables"])


@tables.get("/tables", response_model=list[A.TableSummary])
async def list_tables(user: User, session: AsyncSession = Depends(get_session)):
    return await queries.list_tables(session)


@tables.get("/tables/{table}", response_model=Table)
async def get_table(table: str, user: User, session: AsyncSession = Depends(get_session)):
    try:
        return await queries.fetch_table(session, table)
    except PipelineError as exc:
        raise _http(exc) from exc


@tables.post("/tables/{table}/rows/query", response_model=RowsPage)
async def query_rows(table: str, body: A.RowsQuery, user: User, session: AsyncSession = Depends(get_session)):
    """Einfache Feldfilter und Sortierung (L 3.4); Ausdrücke `{{ }}` in Filterwerten (`user`, `now`, `today`) werden ausgewertet, Fehler daran sind 422."""
    try:
        return await queries.query_rows(session, table, [f.model_dump() for f in body.filter],
                                        [x.model_dump() for x in body.sort], body.limit, body.offset,
                                        context={"user": {"id": user.id, "name": user.name}})
    except PipelineError as exc:
        raise _http(exc) from exc


# ── Workflows (4.1) ──────────────────────────────────────────────────────────
workflows = APIRouter(prefix="/api", tags=["workflows"])


@workflows.get("/workflows", response_model=list[WorkflowSummary])
async def list_workflows(user: User, session: AsyncSession = Depends(get_session)):
    return await queries.list_workflows(session)


@workflows.get("/workflows/{wf}", response_model=Workflow)
async def get_workflow(wf: str, user: User, session: AsyncSession = Depends(get_session)):
    """Workflow per ID oder Key, mit Entwurf (`draft`) und `latest_version`."""
    try:
        return await queries.fetch_workflow(session, wf)
    except PipelineError as exc:
        raise _http(exc) from exc


@workflows.post("/workflows/validate", response_model=ValidationResult)
async def validate_workflow(body: A.WorkflowValidateRequest, user: User,
                            session: AsyncSession = Depends(get_session)):
    """Prüfung nach L 5.7: genau eines von `workflow` (Entwurf) oder `definition`. Fehler blockieren
    `workflow.publish`, Warnungen nicht."""
    if (body.workflow is None) == (body.definition is None):
        raise HTTPException(422, "Genau eines von 'workflow' oder 'definition' angeben")
    try:
        return await queries.validate_workflow(session, user.actor, body.workflow, body.definition)
    except PipelineError as exc:
        raise _http(exc) from exc


# ── Runs, Aufgaben, Benachrichtigungen (4.2–4.4) ─────────────────────────────
runs = APIRouter(prefix="/api", tags=["runs"])


@runs.get("/runs", response_model=list[RunListItem])
async def list_runs(user: User, workflow: str | None = None,
                    started_by: Literal["me", "any"] = "me", status: str | None = None):
    return D.RUN_LIST


@runs.get("/runs/{run}", response_model=RunStatusView)
async def get_run(run: str, user: User):
    return D.RUN_STATUS


@runs.get("/tasks", response_model=list[TaskListItem])
async def list_tasks(user: User, assigned_to: Literal["me"] = "me", status: str = "open",
                     workflow: str | None = None):
    can = "chef" in user.roles
    return [TaskListItem(task=D.TASK_OPEN, run_title=D.RUN_STATUS.title, step_name="Genehmigung",
                         workflow_name="Bestellprozess", can_act=can)] if can else []


@runs.get("/tasks/{task}", response_model=TaskDetail)
async def get_task(task: str, user: User):
    return TaskDetail(
        task=D.TASK_OPEN, run_title=D.RUN_STATUS.title, document_id="doc_s2",
        document_markdown="# Genehmigung {#blk_s2_h}\n\nBestellung von Ben Mitarbeiter für Kostenstelle 4711.",
        form_block="blk_s2_form",
        buttons=[ButtonInfo(id="approve", label="Genehmigt", style="primary", outcome="approved"),
                 ButtonInfo(id="reject", label="Abgelehnt", style="danger", outcome="rejected", require=["kommentar"])],
        fields=[{"key": "kommentar", "label": "Kommentar", "input": "textarea", "required": False}],
        can_act="chef" in user.roles,
    )


@runs.get("/notifications", response_model=list[Notification])
async def list_notifications(user: User, unread: bool = False):
    if "chef" not in user.roles:
        return []
    return [Notification(id="ntf_1", recipient_id=user.id, run_id="run_42", task_id="tsk_2", type="step_entered",
                         payload={"title": D.RUN_STATUS.title, "step": "Genehmigung"}, created_at=D.T1)]


@runs.post("/notifications/{notification}/read", response_model=Notification)
async def read_notification(notification: str, user: User):
    return Notification(id=notification, recipient_id=user.id, type="step_entered", created_at=D.T1, read_at=D.T1)


# ── Import (3.6–3.8) ─────────────────────────────────────────────────────────
imports = APIRouter(prefix="/api/imports", tags=["imports"])

_UPLOAD_CHUNK = 1024 * 1024


async def _read_upload(file: UploadFile) -> bytes:
    """Liest den Upload mit Größenlimit, ohne eine riesige Datei komplett in den Speicher zu holen."""
    from app.imports.xlsx import MAX_BYTES

    data = bytearray()
    while chunk := await file.read(_UPLOAD_CHUNK):
        data += chunk
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "Die Datei ist zu groß (erlaubt sind 10 MB).")
    return bytes(data)


async def _prepare_import(source: str, result, user: CurrentUser, session: AsyncSession, apply: bool) -> A.ImportPlan:
    from app.imports import store
    from app.ops.context import OpContext

    await session.commit()  # beendet die Transaktion der Anmeldeprüfung (Autobegin), sonst scheitert `begin()`
    async with session.begin():
        plan = await store.save_plan(OpContext(session=session, actor=user.actor), source, result.ops,
                                     result.created, result.warnings)
    if apply:
        batch = OpBatch(batch_id=new_id("batch"), ops=[{"op": "import.include", "import_id": plan.import_id}])
        try:
            plan.result = await apply_batch(batch, user.actor)
        except PipelineError as exc:
            raise HTTPException(exc.status_code, exc.error.message) from exc
    return plan


@imports.post("/xlsx", response_model=A.ImportPlan)
async def import_xlsx(user: User, file: UploadFile = File(...), sheet: str | None = Form(None),
                      apply: bool = Form(False), session: AsyncSession = Depends(get_session)):
    """Bereitet einen Excel-Import vor (schreibt noch nichts). Kaputte oder zu große Dateien: 422 bzw. 413."""
    from app.imports.xlsx import ImportFileError, parse_xlsx

    data = await _read_upload(file)
    try:
        result = await run_in_threadpool(parse_xlsx, data, sheet or None)
    except ImportFileError as exc:
        raise HTTPException(422, str(exc)) from exc
    return await _prepare_import("xlsx", result, user, session, apply)


@imports.post("/docx", response_model=A.ImportPlan)
async def import_docx(user: User, file: UploadFile = File(...), title: str | None = Form(None),
                      owner: str | None = Form(None), bind_table: str | None = Form(None),
                      apply: bool = Form(False), session: AsyncSession = Depends(get_session)):
    """Bereitet einen Word-Import vor (schreibt noch nichts). `owner` = `workflow:schritt` oder JSON
    `{"workflow":…,"step":…}`. Kaputte oder zu große Dateien: 422 bzw. 413."""
    from app.imports.docx import parse_docx
    from app.imports.xlsx import ImportFileError

    data = await _read_upload(file)
    existing = await queries.list_tables(session)  # für bind_table und gegen Key-Kollisionen
    await session.commit()  # beendet die lesende Transaktion, `_prepare_import` öffnet eine eigene
    try:
        result = await run_in_threadpool(parse_docx, data, title or None, owner or None, bind_table or None,
                                         existing, file.filename)
    except ImportFileError as exc:
        raise HTTPException(422, str(exc)) from exc
    return await _prepare_import("docx", result, user, session, apply)


# ── Suche (5.2) ──────────────────────────────────────────────────────────────
search = APIRouter(prefix="/api", tags=["search"])


@search.get("/search", response_model=A.SearchResponse)
async def do_search(q: str, user: User, kinds: str | None = None, limit: int = Query(10, ge=1, le=50)):
    kind_list = None
    if kinds:
        kind_list = [k.strip() for k in kinds.split(",") if k.strip()]
        bad = [k for k in kind_list if k not in ("document", "table", "workflow")]
        if bad:
            raise HTTPException(422, f"Unbekannte kinds: {', '.join(bad)}")
    from app.search.search import hybrid_search

    return await hybrid_search(q, user.actor, kind_list or None, limit)


# ── Schema-Hilfe: bringt WS-Nachrichten und Ops ins OpenAPI (für TS-Typen, 0.8) ──
schema = APIRouter(prefix="/api/schema", tags=["schema"])


@schema.get("/ws-messages", response_model=WsMessages)
async def ws_messages():
    return WsMessages()


all_routers = [auth, ops, documents, tables, workflows, runs, imports, search, schema]
