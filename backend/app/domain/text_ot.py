"""Text-OT für `text.edit` (L 7.5, T 2.6), Stretch F15. Gegenstück im Frontend: `frontend/src/sync/textOt.ts`,
gemeinsame Fälle in `spec/fixtures/text_ot/`.

Festlegungen:
- Ein Textblock ist für Positionen eine Folge von Einheiten: jedes Zeichen (Code Point) aus `text`- und
  `link`-Teilen zählt 1, `mention` und `value` zählen als je 1 Einheit (nicht teilbar).
- `text.edit {from, to, insert, marks?}` ersetzt die Einheiten `[from, to)` durch `insert`.
  `marks` beschreibt die Marks des eingefügten Texts als Bereiche RELATIV zu `insert`
  (`{from: 0, to: 3, mark: "bold"}` = die ersten drei eingefügten Zeichen fett). Fehlt `marks`, erbt der
  eingefügte Text die Marks des Zeichens davor (wie beim Tippen).
- Transformation: Ein Edit wird gegen jeden zwischenzeitlich angewendeten Edit desselben Blocks verschoben.
  Einfügen an derselben Stelle: der früher angewendete Edit steht vorn (`side="after"` für den späteren).
  Positionen innerhalb eines ersetzten Bereichs: `from` rückt hinter den neuen Text, `to` vor ihn, damit
  fremder eingefügter Text nicht mitgelöscht wird. Liegt ein Edit ganz in einem fremd gelöschten Bereich,
  entfällt er (Löschen gewinnt), sonst liefen Server und Clients auseinander.
"""
from __future__ import annotations

from typing import Any, Literal

MARK_ORDER = ["bold", "italic", "code", "strike"]
Side = Literal["before", "after"]


def transform_one(edit: dict[str, Any], prior: dict[str, Any], side: Side = "after") -> dict[str, Any]:
    """Verschiebt `edit` so, dass er nach `prior` angewendet werden kann (beide auf demselben Ausgangsstand)."""
    pf, pt = prior["from"], max(prior["from"], prior["to"])
    length = len(prior.get("insert") or "")
    delta = length - (pt - pf)
    ef, et = edit["from"], max(edit["from"], edit["to"])
    is_insert = ef == et

    if ef < pf:
        nf = ef
    elif pf == pt:  # prior fügt nur ein
        if ef > pf or not is_insert or side == "after":
            nf = ef + length
        else:
            nf = ef
    elif ef == pf:
        nf = ef
    elif ef >= pt:
        nf = ef + delta
    else:
        nf = pf + length

    # Liegt der Edit ganz in einem Bereich, den prior gelöscht hat, entfällt er (Löschen gewinnt). Sonst könnte
    # die Gegenrichtung (prior gegen edit verschoben) den eingefügten Text mitlöschen und die Seiten liefen auseinander.
    # Bei genau gleichem Bereich entfällt nur der am Server spätere Edit (side "after"); die Gegenrichtung
    # (side "before") ersetzt dann den fremden Text, so kommen beide Seiten zum selben Ergebnis.
    same_range = ef == pf and et == pt
    if pt > pf and pf <= ef and et <= pt and not (is_insert and ef in (pf, pt)) and (not same_range or side == "after"):
        return {**edit, "from": nf, "to": nf, "insert": "", "marks": None}

    if is_insert:
        nt = nf
    elif et <= pf:
        nt = et
    elif pf == pt:
        nt = et + length
    elif et >= pt:
        nt = et + delta
    else:
        nt = pf
    return {**edit, "from": nf, "to": max(nf, nt)}


def transform(edit: dict[str, Any], applied_since: list[dict[str, Any]]) -> dict[str, Any]:
    """Verschiebt `edit` gegen alle seit seiner Basis-Version angewendeten Edits desselben Blocks (in Reihenfolge)."""
    for prior in applied_since:
        edit = transform_one(edit, prior, "after")
    return edit


# ── Anwenden auf Inline-Inhalt (L 3.3) ───────────────────────────────────────


def _units(content: list[dict[str, Any]]) -> list[tuple]:
    out: list[tuple] = []
    for part in content or []:
        t = part.get("t")
        if t == "text":
            marks = tuple(m for m in MARK_ORDER if m in (part.get("marks") or []))
            out += [("c", ch, marks) for ch in part.get("text", "")]
        elif t == "link":
            out += [("l", ch, part.get("href", "")) for ch in part.get("text", "")]
        else:
            out.append(("a", part))
    return out


def _parts(units: list[tuple]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for u in units:
        last = out[-1] if out else None
        if u[0] == "c":
            if last and last["t"] == "text" and tuple(last.get("marks", [])) == u[2]:
                last["text"] += u[1]
            else:
                out.append({"t": "text", "text": u[1], "marks": list(u[2])})
        elif u[0] == "l":
            if last and last["t"] == "link" and last["href"] == u[2]:
                last["text"] += u[1]
            else:
                out.append({"t": "link", "text": u[1], "href": u[2]})
        else:
            out.append(dict(u[1]))
    return out


def text_length(content: list[dict[str, Any]]) -> int:
    return len(_units(content))


def apply_edit(content: list[dict[str, Any]], edit: dict[str, Any]) -> list[dict[str, Any]]:
    """Wendet einen (bereits transformierten) Edit an. Positionen werden auf die Textlänge begrenzt."""
    units = _units(content)
    f = min(max(edit["from"], 0), len(units))
    t = min(max(edit["to"], f), len(units))
    insert = edit.get("insert") or ""
    marks_spec = edit.get("marks")
    if marks_spec is None:
        before = units[f - 1] if f > 0 else None
        inherited = before[2] if before and before[0] == "c" else ()
        new = [("c", ch, inherited) for ch in insert]
    else:
        new = []
        for i, ch in enumerate(insert):
            on = {m["mark"] for m in marks_spec if m["from"] <= i < m["to"]}
            new.append(("c", ch, tuple(m for m in MARK_ORDER if m in on)))
    return _parts(units[:f] + new + units[t:])
