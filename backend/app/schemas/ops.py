"""Operationen: der einzige Schreibweg (anwendungslogik.md 6.1). Jede Op ist Teil der Union `Op`."""
from typing import Annotated, Any, Literal, Union

from pydantic import Field

from .blocks import BlockIn
from .common import Actor, ApiError, BaseModel, Strict, Value
from .tables import ColumnIn, ColumnPatch, NewRow
from .workflows import Assignee, WorkflowDefinition

# ── Tabellen ─────────────────────────────────────────────────────────────────


class TableCreate(Strict):
    op: Literal["table.create"]
    id: str
    key: str
    name: str
    columns: list[ColumnIn]
    display_column: str | None = None


class TableUpdate(Strict):
    op: Literal["table.update"]
    table: str
    name: str | None = None
    key: str | None = None
    display_column: str | None = None


class TableDelete(Strict):
    op: Literal["table.delete"]
    table: str


class ColumnAdd(Strict):
    op: Literal["column.add"]
    table: str
    column: ColumnIn
    after: str | None = None


class ColumnUpdate(Strict):
    op: Literal["column.update"]
    table: str
    column: str
    patch: ColumnPatch


class ColumnMove(Strict):
    op: Literal["column.move"]
    table: str
    column: str
    after: str | None = None


class ColumnDelete(Strict):
    op: Literal["column.delete"]
    table: str
    column: str


class RowInsert(Strict):
    op: Literal["row.insert"]
    table: str
    rows: list[NewRow]


class RowUpdate(Strict):
    op: Literal["row.update"]
    table: str
    row: str
    values: dict[str, Value | None]  # nur geänderte Spalten


class RowMove(Strict):
    op: Literal["row.move"]
    table: str
    row: str
    after: str | None = None


class RowDelete(Strict):
    op: Literal["row.delete"]
    table: str
    rows: list[str]


# ── Dokumente ────────────────────────────────────────────────────────────────


class DocOwnerIn(Strict):
    workflow: str
    step: str | None = None  # None = Übersichtsdokument des Workflows (Beschreibung + Workflow-Block)


class DocCreate(Strict):
    op: Literal["doc.create"]
    id: str
    title: str
    owner: DocOwnerIn | None = None
    blocks: list[BlockIn] | None = None
    markdown: str | None = None  # Alternative zu `blocks` (8.2)


class DocUpdate(Strict):
    op: Literal["doc.update"]
    doc: str
    title: str


class DocDelete(Strict):
    op: Literal["doc.delete"]
    doc: str


class BlockInsert(Strict):
    op: Literal["block.insert"]
    doc: str
    parent: str | None = None
    after: str | None = None
    block: BlockIn


class BlockUpdate(Strict):
    op: Literal["block.update"]
    block: str
    props: dict[str, Any]  # flaches Merge pro Prop


class BlockMove(Strict):
    op: Literal["block.move"]
    block: str
    parent: str | None = None
    after: str | None = None


class BlockDelete(Strict):
    op: Literal["block.delete"]
    block: str


class TextMark(Strict):
    from_: int = Field(alias="from")
    to: int
    mark: Literal["bold", "italic", "code", "strike"]
    model_config = {"populate_by_name": True, "extra": "forbid"}


class TextEdit(Strict):
    op: Literal["text.edit"]
    block: str
    version: int  # zuletzt gesehene Block-Version (für OT)
    from_: int = Field(alias="from")
    to: int
    insert: str = ""
    marks: list[TextMark] | None = None
    model_config = {"populate_by_name": True, "extra": "forbid"}


# ── Formulare ────────────────────────────────────────────────────────────────


class DraftSet(Strict):
    op: Literal["draft.set"]
    form_block: str
    scope: dict[str, str]  # {"run": "run_42"} | {"user": "usr_1"}
    key: str
    value: Value


class DraftItemInsert(Strict):
    op: Literal["draft.item_insert"]
    form_block: str
    scope: dict[str, str]
    key: str
    item: dict[str, Any]  # {id, values}
    after: str | None = None


class DraftItemUpdate(Strict):
    op: Literal["draft.item_update"]
    form_block: str
    scope: dict[str, str]
    key: str
    item_id: str
    values: dict[str, Value]


class DraftItemDelete(Strict):
    op: Literal["draft.item_delete"]
    form_block: str
    scope: dict[str, str]
    key: str
    item_id: str


class FormSubmit(Strict):
    op: Literal["form.submit"]
    submission_id: str
    form_block: str
    button: str
    run: str | None = None
    values: dict[str, Any] | None = None  # überschreibt den Entwurf (für Agenten)


# ── Workflows, Runs, Aufgaben ────────────────────────────────────────────────


class WorkflowCreate(Strict):
    op: Literal["workflow.create"]
    id: str
    key: str
    name: str
    definition: WorkflowDefinition
    description: str | None = None  # landet im automatisch angelegten Übersichtsdokument


class WorkflowUpdate(Strict):
    op: Literal["workflow.update"]
    workflow: str
    definition: WorkflowDefinition


class WorkflowPublish(Strict):
    op: Literal["workflow.publish"]
    workflow: str


class WorkflowDelete(Strict):
    op: Literal["workflow.delete"]
    workflow: str


class RunStart(Strict):
    op: Literal["run.start"]
    id: str
    workflow: str
    input: dict[str, Value] | None = None


class RunCancel(Strict):
    op: Literal["run.cancel"]
    run: str
    reason: str | None = None


class RunComment(Strict):
    op: Literal["run.comment"]
    run: str
    text: str


class TaskClaim(Strict):
    op: Literal["task.claim"]
    task: str


class TaskRelease(Strict):
    op: Literal["task.release"]
    task: str


class TaskReassign(Strict):
    op: Literal["task.reassign"]
    task: str
    assignees: list[Assignee]


# ── Import, Rollen ───────────────────────────────────────────────────────────


class ImportInclude(Strict):
    op: Literal["import.include"]
    import_id: str  # wird vom Server durch die gespeicherten Ops ersetzt (8.3)


class RoleCreate(Strict):
    op: Literal["role.create"]
    id: str
    key: str
    name: str


class RoleUpdate(Strict):
    op: Literal["role.update"]
    role: str
    key: str | None = None
    name: str | None = None


class RoleDelete(Strict):
    op: Literal["role.delete"]
    role: str


class UserSetRoles(Strict):
    op: Literal["user.set_roles"]
    user: str
    add: list[str] = []
    remove: list[str] = []


class AgentSetRoles(Strict):
    op: Literal["agent.set_roles"]
    agent: str
    add: list[str] = []
    remove: list[str] = []


Op = Annotated[
    Union[
        TableCreate, TableUpdate, TableDelete, ColumnAdd, ColumnUpdate, ColumnMove, ColumnDelete,
        RowInsert, RowUpdate, RowMove, RowDelete,
        DocCreate, DocUpdate, DocDelete, BlockInsert, BlockUpdate, BlockMove, BlockDelete, TextEdit,
        DraftSet, DraftItemInsert, DraftItemUpdate, DraftItemDelete, FormSubmit,
        WorkflowCreate, WorkflowUpdate, WorkflowPublish, WorkflowDelete,
        RunStart, RunCancel, RunComment, TaskClaim, TaskRelease, TaskReassign,
        ImportInclude, RoleCreate, RoleUpdate, RoleDelete, UserSetRoles, AgentSetRoles,
    ],
    Field(discriminator="op"),
]


class OpBatch(Strict):
    """Atomarer Batch. Der Akteur wird NICHT mitgeschickt, sondern serverseitig bestimmt."""

    batch_id: str
    base: dict[str, int] = {}  # erwartete Versionen, z. B. {"blk_x": 4}
    ops: list[Op]


class BatchResult(BaseModel):
    batch_id: str
    seq: dict[str, int] = {}  # Kanal -> seq
    results: dict[str, Any] = {}  # z. B. {"0": {"id": "row_…"}} je Op-Index bzw. Action-Ergebnisse
    # nur bei form.submit
    errors: dict[str, str] | None = None  # "artikel[2].preis" -> Meldung


class BatchError(BaseModel):
    batch_id: str
    error: ApiError
