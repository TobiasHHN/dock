"""Request-/Response-Modelle der REST-Endpunkte (technische-umsetzung.md 2.2, 2.9)."""
from typing import Any, Literal

from pydantic import BaseModel

from .common import Actor, Strict
from .ops import BatchResult, Op
from .tables import Column, FilterCondition, SortSpec


class SignupRequest(Strict):
    email: str
    name: str
    password: str
    role: Literal["einkauf", "mitarbeiter", "chef"]


class LoginRequest(Strict):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    roles: list[str]  # Rollen-Keys


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserOut


class RoleOut(BaseModel):
    id: str
    key: str
    name: str
    member_count: int = 0


class TableSummary(BaseModel):
    id: str
    key: str
    name: str
    columns: list[Column]
    version: int


class RowsQuery(Strict):
    filter: list[FilterCondition] = []
    sort: list[SortSpec] = []
    limit: int = 100
    offset: int = 0


class ImportPlan(BaseModel):
    """Ergebnis von `POST /api/imports/xlsx|docx` (8.3)."""

    import_id: str
    created: dict[str, Any]  # IDs/Keys dessen, was angelegt würde (Tabellen, Spalten, Dokument, Formular, Felder)
    warnings: list[str] = []
    preview: dict[str, Any] = {}  # erkannte Tabellen-Schemas und Dokument-Blöcke, ohne importierte Zeilenwerte
    result: BatchResult | None = None  # nur bei apply=true


class SearchHit(BaseModel):
    kind: Literal["document", "table", "workflow"]
    id: str
    title: str
    snippet: str
    block_ids: list[str] = []
    score: float


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]


class WorkflowValidateRequest(Strict):
    workflow: str | None = None  # bestehender Workflow (Entwurf) ...
    definition: dict[str, Any] | None = None  # ... oder eine Definition direkt


class StartRunRequest(Strict):
    workflow: str
    input: dict[str, Any] | None = None


class CommentRequest(Strict):
    text: str


class FormValidateResult(BaseModel):
    ok: bool
    warnings: list[dict[str, Any]] = []  # {block, field, message}


# Exporte für das OpenAPI-Schema: damit Op/Actor als Komponenten auftauchen
__all__ = ["Op", "Actor"]
