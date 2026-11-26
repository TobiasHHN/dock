"""`validate_form` (Task 3.5): Warnungen mit Block und Feld, rein (aus Blöcken) und gegen die Datenbank (Endpunkt)."""
import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth import CurrentUser, current_user
from app.db.session import get_session
from app.domain import forms as F
from app.main import app

from .test_forms import ANNA, engine, make_world, run  # noqa: F401  (engine ist eine Fixture)


def blk(id_, type_, props, parent=None, pos="a0"):
    return {"id": id_, "type": type_, "props": props, "parent_id": parent, "position": pos}


def form_blocks(actions, buttons=None, extra=()):
    props = {"actions": actions}
    if buttons is not None:
        props["buttons"] = buttons
    return [blk("f", "form", props),
            blk("n", "field", {"key": "name", "label": "Name", "input": "text"}, "f", "a0"),
            blk("l", "line_items", {"key": "artikel", "label": "Artikel", "columns": [
                {"key": "artikelname", "input": "text"}, {"key": "preis", "input": "currency"}]}, "f", "a1"), *extra]


def messages(warnings):
    return [(w["block"], w["field"], w["message"]) for w in warnings]


def test_clean_form_has_no_warnings():
    actions = [{"key": "order", "type": "create_row", "table": "t", "values": {"c": "{{fields.name}}"}},
               {"key": "items", "type": "create_rows", "table": "t", "for_each": "{{fields.artikel}}",
                "values": {"c": "{{item.artikelname}}", "d": "{{results.order.id}}",
                           "e": "{{coalesce(item.preis, 0)}} {{today}} {{user.name}}"}}]
    assert F.validate_form(form_blocks(actions), "f") == []
    assert F.validate_form(form_blocks(actions), "n") == [] and F.validate_form([], "x") == []


def test_finds_expression_typos_with_block_and_field():
    actions = [{"key": "order", "type": "create_row", "table": "t", "values": {"c": "{{fields.nmae}}"}},
               {"key": "items", "type": "create_rows", "table": "t", "for_each": "{{fields.artikel}}",
                "values": {"c": "{{item.artikelnam}}", "d": "{{results.ordr.id}}", "e": "{{summe(1)}}",
                           "g": "{{fields.name", "h": "{{eval.x}}"}},
               {"key": "single", "type": "create_row", "table": "t", "values": {"c": "{{item.x}}"}}]
    out = F.validate_form(form_blocks(actions, extra=[
        blk("p", "paragraph", {"content": [{"t": "value", "expr": "{{fields.zz}}"}]}, "f", "a2")]), "f")
    text_ = "\n".join(m for _, _, m in messages(out))
    assert "unbekannte Feld „nmae“" in text_ and "Meinten Sie „name“" in text_
    assert "Spalte „artikelnam“" in text_ and "„artikelname“" in text_
    assert "unbekannte Action „ordr“" in text_ and "Meinten Sie „order“" in text_
    assert "Unbekannte Funktion 'summe'" in text_ and "passen nicht zusammen" in text_ and "beginnt mit „eval“" in text_
    assert "„{{item.x}}“" in text_ and "unbekannte Feld „zz“" in text_  # item ohne Schleife, Fehler im Absatz
    fields = {(b, f) for b, f, _ in messages(out)}
    assert ("f", "actions[0].values.c") in fields and ("f", "actions[1].values.c") in fields
    assert ("p", "props.content[0].expr") in fields  # Block des Fundorts


def test_checks_buttons_actions_and_order():
    actions = [{"key": "a", "type": "create_row", "table": "t", "values": {"c": "{{results.b.id}}"}},
               {"key": "b", "type": "create_row", "table": "t", "values": {}},
               {"key": "unused", "type": "create_row", "table": "t", "values": {}},
               {"key": "b", "type": "create_row", "table": "t", "values": {}}]
    buttons = [{"id": "go", "label": "Go", "actions": ["a", "b", "gibtsnicht"], "require": ["nmae"]}]
    out = "\n".join(m for _, _, m in messages(F.validate_form(form_blocks(actions, buttons), "f")))
    assert "nicht davor" in out and "unbekannte Action „gibtsnicht“" in out and "unbekannte Feld „nmae“" in out
    assert "„unused“ wird von keinem Button" in out and "„b“ kommt mehrfach vor" in out
    nothing = F.validate_form(form_blocks([], buttons=[]), "f")
    assert "keinen Button" in nothing[0]["message"]


def test_against_tables_unknown_columns_and_required():
    tables = {"best": {"id": "tbl_1", "key": "best", "columns": {
        "col_name": {"key": "name", "name": "Name", "required": True, "default": None},
        "col_status": {"key": "status", "name": "Status", "required": True, "default": "neu"},
        "col_ks": {"key": "kostenstelle", "name": "KS", "required": False, "default": None}}}}
    ok = [{"key": "o", "type": "create_row", "table": "tbl_1", "values": {"col_name": "{{fields.name}}"}}]
    assert F.check_form(form_blocks(ok), "f", tables) == []
    bad = [{"key": "o", "type": "create_row", "table": "best", "values": {"kostenstele": "x"}},
           {"key": "u", "type": "update_row", "table": "best", "row": "x", "values": {}},
           {"key": "z", "type": "create_row", "table": "nix", "values": {}}]
    out = "\n".join(m for _, _, m in messages(F.check_form(form_blocks(bad), "f", tables)))
    assert "Spalte „kostenstele“" in out and "Meinten Sie „kostenstelle“" in out
    assert "Pflichtspalte „best.name“" in out and "status" not in out.replace("Meinten", "")
    assert "unbekannte Tabelle „nix“" in out
    assert out.count("Pflichtspalte") == 1  # nur die create_row-Action mit Tabelle, Standardwerte zählen nicht


async def test_endpoint_reads_blocks_and_tables(engine):  # noqa: F811
    w = await make_world(engine)
    await run({"op": "block.update", "block": w.form, "props": {"actions": [
        {"key": "order", "type": "create_row", "table": w.bkey, "values": {"kostenstelle": "{{fields.kostenstele}}"}}],
        "buttons": [{"id": "go", "label": "Go", "actions": ["order"]}]}}, actor=ANNA)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def session():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[current_user] = lambda: CurrentUser(
        id=ANNA.id, name="Anna", email="a@example.local", roles=["einkauf"])
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as api:
            res = await api.post(f"/api/documents/{w.doc}/blocks/{w.form}/validate")
            assert res.status_code == 200, res.text
            body = res.json()
            assert body["ok"] is False and all(set(x) == {"block", "field", "message"} for x in body["warnings"])
            text_ = " ".join(x["message"] for x in body["warnings"])
            assert "unbekannte Feld „kostenstele“" in text_ and "Pflichtspalte" in text_  # `name` ist Pflicht
            assert (await api.post(f"/api/documents/{w.doc}/blocks/{w.f_name}/validate")).status_code == 422
            assert (await api.post(f"/api/documents/{w.doc}/blocks/blk_gibtsnicht/validate")).status_code == 404
            await run({"op": "block.update", "block": w.form, "props": {"actions": [
                {"key": "order", "type": "create_row", "table": w.bkey, "values": {"name": "{{fields.name}}"}}]}},
                actor=ANNA)
            assert (await api.post(f"/api/documents/{w.doc}/blocks/{w.form}/validate")).json() == {
                "ok": True, "warnings": []}
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(current_user, None)
