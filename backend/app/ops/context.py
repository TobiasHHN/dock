"""Gemeinsamer Ausführungskontext der Op-Pipeline (T 2.4).

Fachliche Handler (Tasks 1.3, 1.4, 3.3, 4.x) bekommen pro Op `(ctx, op)` und melden ihre Wirkung hier an:

- ``await ctx.touch(kind, id, ...)``: Objekt wurde angelegt, geändert oder gelöscht. Die Pipeline erhöht die
  ``version`` von ``table``, ``row``, ``document`` und ``block`` genau einmal pro Batch (L 6.2 Schritt 6),
  Handler setzen ``version`` also NICHT selbst (neue Objekte starten mit 1, dafür ``created=True``).
- ``ctx.changed(source_kind, source_id)``: Quelle (``document`` | ``table`` | ``workflow``) wurde inhaltlich
  geändert, die Pipeline stößt nach dem Commit ``enqueue_reembed`` an. ``touch`` auf eine solche Quelle meldet
  das automatisch; für Zeilen und Blöcke ruft der Handler ``changed`` für Tabelle bzw. Dokument selbst auf.
- ``ctx.set_references(kind, id, edges)``: vollständige, aktuell gültige Verweise einer Quelle (L 9). Die
  Pipeline ersetzt die alten Kanten dieser Quelle. Leere Liste = alle Kanten der Quelle entfernen.
- ``ctx.add_inverse(op)``: inverse Op für Undo, in Ausführungsreihenfolge; die Pipeline speichert sie umgekehrt.
- ``await ctx.lock_channel(channel)``: zusätzlich betroffener Kanal (Normalfall: die Pipeline leitet die Kanäle
  aus den Ops ab, siehe ``pipeline.channels_for``).
- Rückgabewert des Handlers (nicht ``None``) landet in ``BatchResult.results[<op-index>]``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ops.errors import PipelineError
from app.schemas.common import Actor

DEFAULT_WORKSPACE = "ws_demo"

# Quellen, die der Einbettungs-Worker kennt (search/embeddings.py)
REEMBED_KINDS = {"document", "table", "workflow"}
# kind -> DB-Tabelle mit `version`-Spalte
VERSIONED = {"table": "tables", "row": "rows", "document": "documents", "block": "blocks"}

_PREFIX = {"table": "tbl_", "column": "col_", "role": "rol_", "workflow": "wf_"}
_LOOKUP = {
    "table": "SELECT id FROM tables WHERE workspace_id = :ws AND key = :key",
    "workflow": "SELECT id FROM workflows WHERE workspace_id = :ws AND key = :key",
    "role": "SELECT id FROM roles WHERE workspace_id = :ws AND key = :key",
    "column": "SELECT id FROM columns WHERE table_id = :table AND key = :key",
}
_LABEL = {"table": "Tabelle", "column": "Spalte", "role": "Rolle", "workflow": "Workflow"}


@dataclass
class OpContext:
    session: AsyncSession
    actor: Actor
    workspace_id: str = DEFAULT_WORKSPACE
    results: dict[str, Any] = field(default_factory=dict)
    op_index: int = 0  # Index der gerade ausgeführten Op im (expandierten) Batch
    seq: dict[str, int] = field(default_factory=dict)  # gesperrte Kanäle -> neue seq
    touched: list[tuple[str, str]] = field(default_factory=list)
    created: set[tuple[str, str]] = field(default_factory=set)
    deleted: set[tuple[str, str]] = field(default_factory=set)
    reembed: list[tuple[str, str]] = field(default_factory=list)
    reference_sources: dict[tuple[str, str], list[tuple[str, str, str]]] = field(default_factory=dict)
    inverse_ops: list[dict[str, Any]] = field(default_factory=list)
    pending_refs: dict[tuple[str, str, str | None], str] = field(default_factory=dict)
    _roles: list[str] | None = None

    # ── Meldungen der Handler ────────────────────────────────────────────────

    async def touch(self, kind: str, id_: str, channel: str | None = None, *,
                    created: bool = False, deleted: bool = False) -> None:
        item = (kind, id_)
        if item not in self.touched:
            self.touched.append(item)
        if created:
            self.created.add(item)
        if deleted:
            self.deleted.add(item)
        if channel:
            await self.lock_channel(channel)
        if kind in REEMBED_KINDS:
            self.changed(kind, id_)

    def changed(self, source_kind: str, source_id: str) -> None:
        item = (source_kind, source_id)
        if source_kind in REEMBED_KINDS and item not in self.reembed:
            self.reembed.append(item)

    def set_references(self, source_kind: str, source_id: str,
                       edges: list[tuple[str, str, str]]) -> None:
        """`edges`: Liste von (target_kind, target_id, via), siehe L 9."""
        self.reference_sources[(source_kind, source_id)] = list(dict.fromkeys(edges))

    def add_inverse(self, op: dict[str, Any]) -> None:
        self.inverse_ops.append(op)

    async def lock_channel(self, channel: str) -> int:
        """Sperrt den Kanal und vergibt seine nächste `seq` (T 2.5). Mehrfachaufrufe sind harmlos.
        Die Pipeline sperrt vorab sortiert; spätes Sperren durch Handler ist nur für selten betroffene
        Kanäle gedacht (Deadlock-Gefahr, wenn zwei Batches Kanäle in umgekehrter Reihenfolge sperren)."""
        if channel in self.seq:
            return self.seq[channel]
        await self.session.execute(
            text("INSERT INTO channels (id) VALUES (:id) ON CONFLICT (id) DO NOTHING"), {"id": channel})
        row = await self.session.execute(
            text("UPDATE channels SET seq = seq + 1 WHERE id = :id RETURNING seq"), {"id": channel})
        self.seq[channel] = row.scalar_one()
        return self.seq[channel]

    # ── Keys auflösen (L 1) ──────────────────────────────────────────────────

    def remember_ref(self, kind: str, key: str, id_: str, table_id: str | None = None) -> None:
        """Key eines im selben Batch angelegten Objekts, damit spätere Ops ihn schon nutzen können."""
        self.pending_refs[(kind, key, table_id if kind == "column" else None)] = id_

    async def resolve(self, kind: str, ref: str, table_id: str | None = None) -> str:
        """ID oder Key -> ID (`kind`: table | column | role | workflow). Spalten brauchen die Tabellen-ID."""
        if ref.startswith(_PREFIX[kind]):
            return ref
        pending = self.pending_refs.get((kind, ref, table_id if kind == "column" else None))
        if pending is not None:
            return pending
        if kind == "column" and not table_id:
            raise PipelineError("VALIDATION", f"Spalten-Key '{ref}' braucht eine Tabelle")
        params = {"ws": self.workspace_id, "key": ref}
        if kind == "column":
            params = {"key": ref, "table": table_id}
        found = (await self.session.execute(text(_LOOKUP[kind]), params)).scalar_one_or_none()
        if found is None:
            raise PipelineError("NOT_FOUND", f"{_LABEL[kind]} '{ref}' wurde nicht gefunden")
        return found

    # ── Akteur und Rollen (L 5.8) ────────────────────────────────────────────

    async def actor_roles(self) -> list[str]:
        """Rollen-Keys des wirksamen Akteurs, erst beim Handeln aufgelöst. Ein Agent im Auftrag einer Person
        handelt mit deren Rollen, sonst gelten die eigenen."""
        if self._roles is not None:
            return self._roles
        member_id = self.actor.on_behalf_of or self.actor.id
        rows = await self.session.execute(
            text("""SELECT r.key FROM member_roles mr JOIN roles r ON r.id = mr.role_id
                    WHERE mr.workspace_id = :ws AND mr.member_id = :member"""),
            {"ws": self.workspace_id, "member": member_id})
        roles = list(rows.scalars())
        self._roles = roles
        return roles

