"""Workflows, Runs, Aufgaben, Status, Benachrichtigungen (anwendungslogik.md 5)."""
from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field

from .common import Actor, Strict, Value

# ── Definition (5.2) ─────────────────────────────────────────────────────────


class AssigneeStarter(Strict):
    kind: Literal["starter"]


class AssigneeUser(Strict):
    kind: Literal["user"]
    user: str


class AssigneeRole(Strict):
    kind: Literal["role"]
    role: str  # ID oder Key


class AssigneeExpr(Strict):
    kind: Literal["expr"]
    expr: str


Assignee = Annotated[
    Union[AssigneeStarter, AssigneeUser, AssigneeRole, AssigneeExpr], Field(discriminator="kind")
]


class Step(Strict):
    key: str
    name: str
    status_label: str | None = None
    document: str
    assignees: list[Assignee]
    exclude_starter: bool = False
    exclude_steps: list[str] = []
    due_in: str | None = None  # ISO-Dauer, z. B. "P2D"


class Transition(Strict):
    from_: str = Field(alias="from")
    on: str  # Outcome oder "*"
    to: str  # Step-Key oder "end"

    model_config = {"populate_by_name": True, "extra": "forbid"}


class WorkflowDefinition(Strict):
    start: str
    steps: list[Step]
    transitions: list[Transition]
    starters: list[Assignee] = []
    managers: list[Assignee] = []
    run_title: str | None = None
    starter_can_cancel: bool = True
    layout: dict[str, dict[str, float]] | None = None  # nur Anzeige


class Workflow(BaseModel):
    id: str
    key: str
    name: str
    draft: WorkflowDefinition
    latest_version: int | None = None


class WorkflowSummary(BaseModel):
    id: str
    key: str
    name: str
    latest_version: int | None = None


class WorkflowVersion(BaseModel):
    workflow_id: str
    version: int
    definition: WorkflowDefinition
    documents: dict[str, list[dict[str, Any]]]  # doc_id -> eingefrorene Blöcke
    published_at: datetime
    published_by: Actor | None = None


# ── Validierung (5.7) ────────────────────────────────────────────────────────


class ValidationIssue(BaseModel):
    severity: Literal["error", "warning"]
    code: str  # z. B. "STEP_UNREACHABLE", "ROLE_UNKNOWN", "EXPR_UNKNOWN_FIELD"
    message: str  # agentenlesbar, deutsch
    step: str | None = None
    block: str | None = None  # Block-ID, falls zutreffend
    field: str | None = None  # Feld/Prop, falls zutreffend


class ValidationResult(BaseModel):
    ok: bool  # True, wenn keine Fehler (Warnungen erlaubt)
    issues: list[ValidationIssue] = []


# ── Run, Aufgabe, Ergebnis (5.2, 5.9) ────────────────────────────────────────


class StepResult(BaseModel):
    outcome: str
    label: str
    values: dict[str, Any] = {}
    results: dict[str, Any] = {}
    completed_by: Actor
    completed_at: datetime


class Run(BaseModel):
    id: str
    workflow_id: str
    version: int
    title: str
    status: Literal["active", "completed", "cancelled"]
    current_step: str | None = None
    result: dict[str, str] | None = None  # {outcome, label}
    parent: dict[str, str] | None = None  # {run, step, block}
    started_by: Actor
    started_at: datetime
    ended_at: datetime | None = None
    input: dict[str, Value] = {}
    steps: dict[str, StepResult] = {}


class TaskCandidates(BaseModel):
    users: list[str] = []
    roles: list[str] = []


class Task(BaseModel):
    id: str
    run_id: str
    step: str
    status: Literal["open", "done", "cancelled"]
    candidates: TaskCandidates
    excluded: list[str] = []
    claimed_by: Actor | None = None
    created_at: datetime
    due_at: datetime | None = None
    completed_by: Actor | None = None
    completed_at: datetime | None = None
    outcome: str | None = None


class TaskListItem(BaseModel):
    """Eintrag in „Meine Aufgaben“ (L 5.9, T 5.7)."""

    task: Task
    run_title: str
    step_name: str
    workflow_name: str
    can_act: bool
    claimed_by_name: str | None = None


class ButtonInfo(BaseModel):
    id: str
    label: str
    style: str = "secondary"
    outcome: str | None = None
    require: list[str] = []
    confirm: str | None = None


class TaskDetail(BaseModel):
    """`get_task` (L 8.1): alles, was ein Agent zum Erledigen braucht."""

    task: Task
    run_title: str
    document_id: str
    document_markdown: str  # im Run-Kontext ausgewertet
    form_block: str | None = None
    buttons: list[ButtonInfo] = []
    fields: list[dict[str, Any]] = []  # key, label, input, required
    can_act: bool


# ── Events und Status (5.10) ─────────────────────────────────────────────────

RunEventType = Literal[
    "started", "step_entered", "task_claimed", "task_released", "reassigned", "step_completed",
    "overdue", "unassigned", "comment", "subflow_started", "subflow_completed", "completed", "cancelled",
]


class RunEvent(BaseModel):
    id: str
    run_id: str
    at: datetime
    actor: Actor
    type: RunEventType
    step: str | None = None
    outcome: str | None = None
    label: str | None = None
    text: str | None = None


class StatusCandidates(BaseModel):
    users: list[dict[str, str]] = []  # {id, name}
    roles: list[dict[str, str]] = []  # {key, name}


class StatusCurrent(BaseModel):
    step: str
    label: str | None = None
    since: datetime
    candidates: StatusCandidates
    claimed_by: Actor | None = None
    due_at: datetime | None = None


class StatusStep(BaseModel):
    step: str
    name: str
    state: Literal["done", "active", "pending"]
    label: str | None = None
    by: str | None = None
    at: datetime | None = None


class RunStatusView(BaseModel):
    """Statusansicht eines Runs, gleich für Browser und `get_run` (L 5.10)."""

    id: str
    title: str
    workflow: dict[str, Any]  # {id, name, version}
    status: Literal["active", "completed", "cancelled"]
    result: dict[str, str] | None = None
    started_by: Actor
    started_at: datetime
    current: StatusCurrent | None = None
    steps: list[StatusStep]
    events: list[RunEvent]


class RunListItem(BaseModel):
    """„Meine Anträge“."""

    id: str
    title: str
    workflow_name: str
    status: Literal["active", "completed", "cancelled"]
    status_label: str | None = None
    candidates: StatusCandidates | None = None
    result: dict[str, str] | None = None
    started_at: datetime


class Notification(BaseModel):
    id: str
    recipient_id: str
    run_id: str | None = None
    task_id: str | None = None
    type: str  # step_entered | step_completed | completed | cancelled | comment | overdue | unassigned
    payload: dict[str, Any] = {}
    created_at: datetime
    read_at: datetime | None = None
