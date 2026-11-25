"""Stub-Router (Task 0.4): liefern Beispieldaten, damit das Frontend ohne Backend-Logik bauen kann.
Phase 1: Jeder Owner ersetzt die Stubs seines Bereichs durch echte Implementierungen (Task-IDs in den Kommentaren)."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ROLE_NAMES, CurrentUser, create_access_token, current_user, hash_password, verify_password
from app.db.session import get_session
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


@documents.get("/documents", response_model=list[DocumentSummary])
async def list_documents(user: User):
    return [DocumentSummary(**d.model_dump()) for d, _ in D.DOCS.values()]


@documents.get("/documents/{doc}", response_model=DocumentOut)
async def get_document_json(doc: str, user: User, run: str | None = None):
    if doc not in D.DOCS:
        raise HTTPException(404, f"Dokument {doc} nicht gefunden")
    d, blocks = D.DOCS[doc]
    return DocumentOut(document=d, blocks=blocks)


@documents.get("/documents/{doc}/markdown", response_model=DocumentMarkdown)
async def get_document_markdown(doc: str, user: User, run: str | None = None):
    if doc not in D.DOCS:
        raise HTTPException(404, f"Dokument {doc} nicht gefunden")
    d, _ = D.DOCS[doc]
    return DocumentMarkdown(document=d, markdown=f"# {d.title} {{#blk_h1}}\n\n(Stub)")


@documents.post("/documents/{doc}/blocks/{block}/validate", response_model=A.FormValidateResult, tags=["forms"])
async def validate_form(doc: str, block: str, user: User):  # 3.5
    return A.FormValidateResult(ok=True, warnings=[])


# ── Tabellen (1.3, 3.1) ──────────────────────────────────────────────────────
tables = APIRouter(prefix="/api", tags=["tables"])


@tables.get("/tables", response_model=list[A.TableSummary])
async def list_tables(user: User):
    return [A.TableSummary(**t.model_dump()) for t in D.TABLES]


@tables.get("/tables/{table}", response_model=Table)
async def get_table(table: str, user: User):
    for t in D.TABLES:
        if table in (t.id, t.key):
            return t
    raise HTTPException(404, f"Tabelle {table} nicht gefunden")


@tables.post("/tables/{table}/rows/query", response_model=RowsPage)
async def query_rows(table: str, body: A.RowsQuery, user: User):
    t = next((t for t in D.TABLES if table in (t.id, t.key)), None)
    if t is None:
        raise HTTPException(404, f"Tabelle {table} nicht gefunden")
    rows = D.ROWS.get(t.id, [])
    return RowsPage(table=t.id, rows=rows, total=len(rows))


# ── Workflows (4.1) ──────────────────────────────────────────────────────────
workflows = APIRouter(prefix="/api", tags=["workflows"])


@workflows.get("/workflows", response_model=list[WorkflowSummary])
async def list_workflows(user: User):
    w = D.WORKFLOW
    return [WorkflowSummary(id=w.id, key=w.key, name=w.name, latest_version=w.latest_version)]


@workflows.get("/workflows/{wf}", response_model=Workflow)
async def get_workflow(wf: str, user: User):
    if wf not in (D.WORKFLOW.id, D.WORKFLOW.key):
        raise HTTPException(404, f"Workflow {wf} nicht gefunden")
    return D.WORKFLOW


@workflows.post("/workflows/validate", response_model=ValidationResult)
async def validate_workflow(body: A.WorkflowValidateRequest, user: User):
    return ValidationResult(ok=True, issues=[])


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

_STUB_PLAN = A.ImportPlan(
    import_id="imp_stub",
    created={"tables": [{"id": "tbl_best", "key": "bestellungen", "columns": ["name", "kostenstelle"]}]},
    warnings=["Stub: Import ist noch nicht implementiert"],
)


@imports.post("/xlsx", response_model=A.ImportPlan)
async def import_xlsx(user: User, file: UploadFile = File(...), sheet: str | None = Form(None),
                      apply: bool = Form(False)):
    return _STUB_PLAN


@imports.post("/docx", response_model=A.ImportPlan)
async def import_docx(user: User, file: UploadFile = File(...), title: str | None = Form(None),
                      owner: str | None = Form(None), bind_table: str | None = Form(None),
                      apply: bool = Form(False)):
    return _STUB_PLAN


# ── Suche (5.2) ──────────────────────────────────────────────────────────────
search = APIRouter(prefix="/api", tags=["search"])


@search.get("/search", response_model=A.SearchResponse)
async def do_search(q: str, user: User, kinds: str | None = None, limit: int = 10):
    return A.SearchResponse(query=q, hits=[
        A.SearchHit(kind="workflow", id="wf_best", title="Bestellprozess", snippet="Bestellung erfassen, genehmigen …",
                    score=0.9),
        A.SearchHit(kind="document", id="doc_einkauf", title="Einkauf", snippet="Hier neue Bestellungen starten …",
                    block_ids=["blk_e_p"], score=0.7),
    ])


# ── Schema-Hilfe: bringt WS-Nachrichten und Ops ins OpenAPI (für TS-Typen, 0.8) ──
schema = APIRouter(prefix="/api/schema", tags=["schema"])


@schema.get("/ws-messages", response_model=WsMessages)
async def ws_messages():
    return WsMessages()


all_routers = [auth, ops, documents, tables, workflows, runs, imports, search, schema]
