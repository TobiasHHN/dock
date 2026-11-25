"""Referenz-Index und Löschschutz (L 9). Pipeline-Teil: Task 1.2, Fachlogik der Kanten: Handler in 1.3/1.4/4.1."""
from typing import Any

from sqlalchemy import text


async def update(ctx: Any, touched: list[Any]) -> None:
    """Pflegt die Tabelle `references`. `touched` sind die Quellen `(kind, id)`, die Handler per
    `ctx.set_references` gemeldet haben: ihre alten Kanten werden vollständig durch die gemeldeten ersetzt
    (umbenannte oder entfernte Props hinterlassen keine veralteten Verweise, leere Liste löscht die Quelle)."""
    for source_kind, source_id in touched:
        await ctx.session.execute(
            text('DELETE FROM "references" WHERE source_kind = :kind AND source_id = :id'),
            {"kind": source_kind, "id": source_id},
        )
        for target_kind, target_id, via in ctx.reference_sources.get((source_kind, source_id), []):
            await ctx.session.execute(
                text('''INSERT INTO "references" (source_kind, source_id, target_kind, target_id, via)
                        VALUES (:sk, :si, :tk, :ti, :via)'''),
                {"sk": source_kind, "si": source_id, "tk": target_kind, "ti": target_id, "via": via},
            )


async def usages(ctx: Any, kind: str, id_: str) -> list[dict[str, Any]]:
    """Wo wird Tabelle/Spalte/Rolle/Dokument verwendet? Grundlage für `IN_USE`-Fehler.
    Gibt `[{source_kind, source_id, via}]` zurück. Die Pipeline schreibt Kanten erst am Ende des Batchs; deshalb
    überlagert diese Funktion den DB-Stand mit den im Batch bereits gemeldeten Kanten (`ctx.reference_sources`):
    Quellen, die im selben Batch entfernt oder geändert wurden, zählen mit ihrem neuen Stand."""
    result = await ctx.session.execute(
        text('''SELECT source_kind, source_id, via FROM "references"
                WHERE target_kind = :kind AND target_id = :id
                ORDER BY source_kind, source_id, via'''),
        {"kind": kind, "id": id_},
    )
    pending = getattr(ctx, "reference_sources", {})
    found = [dict(row) for row in result.mappings() if (row["source_kind"], row["source_id"]) not in pending]
    for (source_kind, source_id), edges in pending.items():
        found += [{"source_kind": source_kind, "source_id": source_id, "via": via}
                  for target_kind, target_id, via in edges if (target_kind, target_id) == (kind, id_)]
    return sorted(found, key=lambda r: (r["source_kind"], r["source_id"], r["via"]))
