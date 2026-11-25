"""Registry der fachlichen Op-Handler (T 2.4).

Die Pipeline (Task 1.2) kennt keine Fachlogik. Jede Domäne legt ein Modul in diesem Paket an
(z. B. `tables.py` für 1.3, `documents.py` für 1.4) und registriert ihre Handler:

    from app.ops.handlers import register
    from app.ops.context import OpContext
    from app.schemas.ops import RowInsert

    @register("row.insert")
    async def row_insert(ctx: OpContext, op: RowInsert):
        ...                       # validieren, anwenden, ctx.touch / ctx.set_references / ctx.add_inverse
        return {"ids": [...]}     # optional: landet in BatchResult.results[<op-index>]

Alle Module dieses Pakets werden beim ersten `apply_batch` automatisch importiert (`load_handlers`).
Handler sehen Ops mit bereits aufgelösten Keys (Tabelle, Spalte, Rolle, Workflow in IDs, Zeilenwerte nach
Spalten-IDs). Fehler: `PipelineError(code, message, details)` werfen, die Transaktion wird zurückgerollt.
"""
from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Awaitable, Callable
from typing import Any

Handler = Callable[[Any, Any], Awaitable[Any]]
HANDLERS: dict[str, Handler] = {}
_loaded = False


def register(op_name: str):
    def decorator(handler: Handler) -> Handler:
        HANDLERS[op_name] = handler
        return handler
    return decorator


def load_handlers() -> None:
    """Importiert alle Handler-Module einmalig, damit ihre `@register`-Dekoratoren laufen."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    for module in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{module.name}")


__all__ = ["HANDLERS", "register", "load_handlers", "Handler"]
