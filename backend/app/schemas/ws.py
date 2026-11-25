"""WebSocket-Nachrichten (anwendungslogik.md 7.3). Kanäle: doc:<id>, table:<id>, run:<id>, user:<id>, workspace."""
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field

from .common import Actor, ApiError, Strict
from .ops import Op, OpBatch

# ── Client → Server ──────────────────────────────────────────────────────────


class SubscribeMsg(Strict):
    type: Literal["subscribe"]
    channel: str
    since: int | None = None  # fehlt -> Snapshot


class UnsubscribeMsg(Strict):
    type: Literal["unsubscribe"]
    channel: str


class OpsMsg(Strict):
    type: Literal["ops"]
    batch: OpBatch


class PresenceState(Strict):
    cursor: dict[str, Any] | None = None  # {block, offset}
    editing: str | None = None  # Block-ID; verfällt nach 30 s ohne Eingabe


class PresenceMsg(Strict):
    type: Literal["presence"]
    channel: str
    state: PresenceState


ClientMessage = Annotated[
    Union[SubscribeMsg, UnsubscribeMsg, OpsMsg, PresenceMsg], Field(discriminator="type")
]

# ── Server → Client ──────────────────────────────────────────────────────────


class SnapshotMsg(BaseModel):
    type: Literal["snapshot"] = "snapshot"
    channel: str
    seq: int
    data: dict[str, Any]  # Form je Kanaltyp, siehe SnapshotDoc/Table/Run/User/Workspace


class OpsEventMsg(BaseModel):
    type: Literal["ops"] = "ops"
    channel: str
    seq: int
    batch_id: str
    actor: Actor
    ops: list[Op]


class AckMsg(BaseModel):
    type: Literal["ack"] = "ack"
    batch_id: str
    seq: dict[str, int]
    results: dict[str, Any] = {}


class RejectMsg(BaseModel):
    type: Literal["reject"] = "reject"
    batch_id: str
    error: ApiError


class PresenceActor(BaseModel):
    actor: Actor
    state: PresenceState


class PresenceBroadcastMsg(BaseModel):
    type: Literal["presence"] = "presence"
    channel: str
    actors: list[PresenceActor]


ServerMessage = Annotated[
    Union[SnapshotMsg, OpsEventMsg, AckMsg, RejectMsg, PresenceBroadcastMsg], Field(discriminator="type")
]


# ── Snapshot-Inhalte je Kanaltyp ─────────────────────────────────────────────


class SnapshotDoc(BaseModel):
    """data von `doc:<id>`."""

    document: dict[str, Any]
    blocks: list[dict[str, Any]]


class SnapshotTable(BaseModel):
    """data von `table:<id>`."""

    table: dict[str, Any]
    rows: list[dict[str, Any]]


class SnapshotRun(BaseModel):
    """data von `run:<id>`."""

    run: dict[str, Any]
    task: dict[str, Any] | None = None
    events: list[dict[str, Any]] = []
    drafts: list[dict[str, Any]] = []


class SnapshotUser(BaseModel):
    """data von `user:<id>`."""

    tasks: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    notifications: list[dict[str, Any]] = []


class SnapshotWorkspace(BaseModel):
    """data von `workspace`."""

    documents: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    workflows: list[dict[str, Any]] = []
    roles: list[dict[str, Any]] = []


SnapshotData = Union[SnapshotDoc, SnapshotTable, SnapshotRun, SnapshotUser, SnapshotWorkspace]


class WsMessages(BaseModel):
    """Nur dafür da, die WebSocket-Nachrichten ins OpenAPI-Schema zu bringen (-> TS-Typen, T 5.1)."""

    client: list[ClientMessage] = []
    server: list[ServerMessage] = []
    snapshots: list[SnapshotData] = []  # Inhalt von SnapshotMsg.data je Kanaltyp
