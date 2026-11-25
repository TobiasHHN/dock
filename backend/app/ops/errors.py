"""Fehler, die REST, WebSocket und MCP in ihren jeweiligen Vertrag übersetzen."""
from __future__ import annotations

from typing import Any

from app.schemas.common import ApiError

# ErrorCode -> HTTP-Status der REST-Schnittstelle (Body: `BatchError`)
HTTP_STATUS = {
    "CONFLICT": 409, "IN_USE": 409, "BLOCK_IN_USE": 409, "TASK_DONE": 409, "TASK_CLAIMED": 409,
    "IMPORT_USED": 409,
    "NOT_FOUND": 404, "FORBIDDEN": 403,
    "VALIDATION": 422, "IMPORT_INVALID": 422,
}


class PipelineError(Exception):
    """Ablehnung eines Batches. `code` ist ein `ErrorCode` aus `schemas/common.py`; `details` nach Vertrag
    (z. B. `errors: {pfad: meldung}` bei VALIDATION, `versions` bei CONFLICT, Verwendungen bei IN_USE)."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        self.error = ApiError(code=code, message=message, details=details)
        super().__init__(message)

    @property
    def status_code(self) -> int:
        return HTTP_STATUS.get(self.error.code, 400)
