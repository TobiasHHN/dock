"""Stub-Router (Task 0.4): liefern Beispieldaten, damit das Frontend ohne Backend-Logik bauen kann.
Phase 1: Jeder Owner ersetzt die Stubs seines Bereichs durch echte Implementierungen (Task-IDs in den Kommentaren)."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.auth import CurrentUser, current_user
from app.schemas import api as A
from app.schemas.blocks import DocumentMarkdown, DocumentOut, DocumentSummary
from app.schemas.ops import BatchResult, OpBatch
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
async def signup(body: A.SignupRequest):
    u = A.UserOut(id="usr_new", name=body.name, email=body.email, roles=[body.role])
    return A.TokenResponse(access_token="stub-token", user=u)


@auth.post("/auth/login", response_model=A.TokenResponse)
async def login(body: A.LoginRequest):
    from app.auth import DEMO_USERS

    u = DEMO_USERS.get(body.email.split("@")[0], DEMO_USERS["anna"])
    return A.TokenResponse(access_token="stub-token", user=A.UserOut(**u.model_dump()))


@auth.get("/me", response_model=A.UserOut)
async def me(user: User):
    return A.UserOut(**user.model_dump())


@auth.get("/roles", response_model=list[A.RoleOut])
async def roles(user: User):
    return D.ROLES


@auth.get("/users", response_model=list[A.UserOut])
async def users(user: User, role: str | None = None):
    from app.auth import DEMO_USERS

    out = [A.UserOut(**u.model_dump()) for u in DEMO_USERS.values()]
    return [u for u in out if role is None or role in u.roles]


# ── Ops: der einzige Schreibweg (1.2) ────────────────────────────────────────
ops = APIRouter(prefix="/api", tags=["ops"])


@ops.post("/ops", response_model=BatchResult)
async def apply_ops(batch: OpBatch, user: User):
    return BatchResult(batch_id=batch.batch_id, seq={"workspace": 1}, results={})


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
