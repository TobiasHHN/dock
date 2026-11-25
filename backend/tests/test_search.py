"""Hybride Suche (Task 5.2): RRF, Filter, Gruppierung, Rechte, API; optional mit echtem Modell.

DB: Standard Host-Port 5433 (DATABASE_URL überschreibbar), Tests werden übersprungen, wenn sie nicht erreichbar ist.
Alle Testdaten tragen den Präfix `zz52` und werden nach jedem Test entfernt.
"""
import json
import os

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth import CurrentUser, current_user
from app.main import app
from app.ops.errors import PipelineError
from app.schemas.common import Actor
from app.search import search as search_mod
from app.search.embeddings import _vec, reembed_source

DB_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://dock:dock@localhost:5433/dock")
ANNA = Actor(type="user", id="usr_zz52anna", name="Anna")

TOPICS = ["bestell", "urlaub", "reise"]


class FakeEmbedder:
    """Deterministisch: je Thema eine Dimension, sonst Dimension 3."""

    model_name = "zz52-fake"

    async def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * 384
            hit = [i for i, k in enumerate(TOPICS) if k in t.lower()]
            for i in hit or [3]:
                v[i] = 1.0
            out.append(v)
        return out


@pytest_asyncio.fixture
async def db(monkeypatch):
    engine = create_async_engine(DB_URL, poolclass=NullPool)
    try:
        async with engine.connect() as c:
            await c.execute(text("SELECT 1"))
    except Exception:
        await engine.dispose()
        pytest.skip("Datenbank nicht erreichbar")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(search_mod, "SessionLocal", Session)
    monkeypatch.setattr(search_mod, "get_embedder", lambda: FakeEmbedder())
    await _cleanup(Session)
    yield Session
    await _cleanup(Session)
    await engine.dispose()


async def _cleanup(Session):
    async with Session() as s:
        await s.execute(text("DELETE FROM embeddings WHERE source_id LIKE 'zz52%'"))
        await s.execute(text("DELETE FROM documents WHERE id LIKE 'zz52%'"))  # blocks per Cascade
        await s.execute(text("DELETE FROM tables WHERE id LIKE 'zz52%'"))
        await s.execute(text("DELETE FROM workflows WHERE id LIKE 'zz52%'"))
        await s.commit()


async def add_doc(Session, id, title):
    async with Session() as s:
        await s.execute(text("INSERT INTO documents (id, workspace_id, title) VALUES (:i, 'ws_demo', :t)"),
                        {"i": id, "t": title})
        await s.commit()


async def add_table(Session, id, name):
    async with Session() as s:
        await s.execute(text("INSERT INTO tables (id, workspace_id, key, name) VALUES (:i, 'ws_demo', :k, :n)"),
                        {"i": id, "k": id, "n": name})
        await s.commit()


async def add_workflow(Session, id, name):
    async with Session() as s:
        await s.execute(
            text("INSERT INTO workflows (id, workspace_id, key, name, draft) VALUES (:i, 'ws_demo', :k, :n, '{}')"),
            {"i": id, "k": id, "n": name})
        await s.commit()


async def add_chunk(Session, kind, source_id, content, block_ids=(), workspace="ws_demo", model="zz52-fake"):
    (vec,) = await FakeEmbedder().embed([content])
    async with Session() as s:
        await s.execute(
            text("INSERT INTO embeddings (workspace_id, source_kind, source_id, block_ids, chunk_hash, content, embedding, model) "
                 "VALUES (:w, :k, :s, :b, :h, :c, CAST(:e AS vector), :m)"),
            {"w": workspace, "k": kind, "s": source_id, "b": list(block_ids), "h": f"{source_id}{hash(content)}",
             "c": content, "e": _vec(vec), "m": model})
        await s.commit()


# ── Logik ────────────────────────────────────────────────────────────────────


def test_snippet_strips_prefix_and_shortens():
    s = search_mod._snippet("Doc > Kapitel\n" + "wort " * 100)
    assert not s.startswith("Doc") and len(s) <= 205 and s.endswith("…")
    assert search_mod._snippet("Tabelle X (x)") == "Tabelle X (x)"


async def test_rrf_ranking_grouping_and_block_ids(db):
    await add_doc(db, "zz52_d1", "Bestellung")
    await add_doc(db, "zz52_d2", "Urlaub")
    # d1: zwei Chunks, der zweite passt zur Anfrage besser (Vektor und Stichwort)
    await add_chunk(db, "document", "zz52_d1", "Bestellung > Allgemein\nSonstiges Blabla", ["zz52_b0"])
    await add_chunk(db, "document", "zz52_d1", "Bestellung > Formular\nBestellung erfassen Formular", ["zz52_b1", "zz52_b2"])
    await add_chunk(db, "document", "zz52_d2", "Urlaub > Antrag\nUrlaub beantragen", ["zz52_b3"])

    res = await search_mod.hybrid_search("Bestellung Formular", ANNA, None, 10)
    assert [h.id for h in res.hits][:1] == ["zz52_d1"]
    ids = [h.id for h in res.hits]
    assert ids.count("zz52_d1") == 1  # ein Treffer pro Quelle
    top = res.hits[0]
    assert top.block_ids == ["zz52_b1", "zz52_b2"] and top.title == "Bestellung"
    assert top.snippet == "Bestellung erfassen Formular"
    # beide Verfahren treffen: Score ist die Summe zweier RRF-Terme (Volltext Rang 1, Vektor Rang 1 oder 2)
    assert 1 / 61 + 1 / 62 - 1e-9 <= top.score <= 2 / 61 + 1e-9
    scores = [h.score for h in res.hits]
    assert scores == sorted(scores, reverse=True)


async def test_kinds_limit_and_empty_query(db):
    await add_doc(db, "zz52_d1", "Bestellung")
    await add_table(db, "zz52_t1", "Bestellungen")
    await add_workflow(db, "zz52_w1", "Bestellprozess")
    await add_chunk(db, "document", "zz52_d1", "Bestellung > A\nBestellung")
    await add_chunk(db, "table", "zz52_t1", "Tabelle Bestellungen (zz52_t1)")
    await add_chunk(db, "workflow", "zz52_w1", "Workflow Bestellprozess (zz52_w1)")

    allhits = await search_mod.hybrid_search("Bestellung", ANNA)
    assert {h.kind for h in allhits.hits} == {"document", "table", "workflow"}
    only = await search_mod.hybrid_search("Bestellung", ANNA, ["table", "workflow"])
    assert {h.kind for h in only.hits} == {"table", "workflow"}
    assert len((await search_mod.hybrid_search("Bestellung", ANNA, None, 2)).hits) == 2
    assert (await search_mod.hybrid_search("   ", ANNA)).hits == []
    assert (await search_mod.hybrid_search("Bestellung", ANNA, ["unbekannt"])).hits == []
    # Sonderzeichen brechen die Volltextsuche nicht
    await search_mod.hybrid_search('"offen & | ! ( : *', ANNA)


async def test_other_model_and_workspace_and_deleted_source_excluded(db):
    await add_doc(db, "zz52_d1", "Bestellung")
    await add_doc(db, "zz52_d2", "Bestellung alt")
    await add_chunk(db, "document", "zz52_d1", "Bestellung > A\nBestellung")
    await add_chunk(db, "document", "zz52_d2", "Bestellung > A\nBestellung", model="altes-modell")
    await add_chunk(db, "document", "zz52_ghost", "Bestellung > A\nBestellung")  # Quelle existiert nicht (mehr)
    res = await search_mod.hybrid_search("Bestellung", ANNA)
    assert [h.id for h in res.hits] == ["zz52_d1"]


async def test_rights_filter(db, monkeypatch):
    await add_doc(db, "zz52_d1", "Bestellung")
    await add_doc(db, "zz52_d2", "Bestellung geheim")
    await add_chunk(db, "document", "zz52_d1", "Bestellung > A\nBestellung")
    await add_chunk(db, "document", "zz52_d2", "Bestellung > A\nBestellung")
    seen = []
    real = search_mod.check_read

    async def fake_check(session, user, channel):
        seen.append((user.id, channel))
        if channel == "doc:zz52_d2":
            raise PipelineError("FORBIDDEN", "nein")
        await real(session, user, channel)

    monkeypatch.setattr(search_mod, "check_read", fake_check)
    agent = Actor(type="agent", id="agt_x", on_behalf_of="usr_zz52anna")
    res = await search_mod.hybrid_search("Bestellung", agent)
    assert [h.id for h in res.hits] == ["zz52_d1"]
    assert ("usr_zz52anna", "doc:zz52_d2") in seen  # Rechte der Person hinter dem Agenten


async def test_limit_applies_after_rights_filter(db, monkeypatch):
    for i in (1, 2, 3):
        await add_doc(db, f"zz52_d{i}", f"Bestellung {i}")
        await add_chunk(db, "document", f"zz52_d{i}", f"Bestellung > A\nBestellung {'x ' * i}")

    async def fake_check(session, user, channel):
        if channel != "doc:zz52_d3":
            raise PipelineError("FORBIDDEN", "nein")

    monkeypatch.setattr(search_mod, "check_read", fake_check)
    res = await search_mod.hybrid_search("Bestellung", ANNA, None, 1)
    assert [h.id for h in res.hits] == ["zz52_d3"]


# ── API ──────────────────────────────────────────────────────────────────────


async def test_api_search(db):
    await add_doc(db, "zz52_d1", "Bestellung")
    await add_chunk(db, "document", "zz52_d1", "Bestellung > A\nBestellung", ["zz52_b1"])
    app.dependency_overrides[current_user] = lambda: CurrentUser(
        id="usr_zz52anna", name="Anna", email="a@example.local", roles=["einkauf"])
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get("/api/search", params={"q": "Bestellung", "kinds": "document,table", "limit": 5})
            assert r.status_code == 200
            body = r.json()
            assert body["query"] == "Bestellung" and body["hits"][0]["id"] == "zz52_d1"
            assert body["hits"][0]["block_ids"] == ["zz52_b1"]
            assert (await c.get("/api/search", params={"q": "x", "kinds": "foo"})).status_code == 422
            assert (await c.get("/api/search", params={"q": "x", "limit": 0})).status_code == 422
            assert (await c.get("/api/search", params={"q": "x", "limit": 51})).status_code == 422
            assert (await c.get("/api/search", params={"q": ""})).json()["hits"] == []
    finally:
        app.dependency_overrides.pop(current_user, None)


# ── Echtes Modell (optional) ────────────────────────────────────────────────


@pytest.mark.skipif(os.environ.get("RUN_MODEL_TESTS") != "1", reason="RUN_MODEL_TESTS=1 setzen (lädt ~220 MB)")
async def test_real_model_finds_order_form(db, monkeypatch, capsys):
    from app.search import embeddings

    emb = embeddings.get_embedder()
    monkeypatch.setattr(search_mod, "get_embedder", lambda: emb)

    def t(s):
        return [{"t": "text", "text": s}]

    docs = {
        "zz52_order": ("Bestellung erfassen", [
            ("h", "heading", {"level": 1, "content": t("Neue Bestellung")}),
            ("n", "field", {"key": "name", "label": "Name"}),
            ("k", "field", {"key": "kostenstelle", "label": "Kostenstelle"}),
            ("a", "field", {"key": "artikel", "label": "Artikel"}),
        ]),
        "zz52_urlaub": ("Urlaubsantrag", [
            ("h", "heading", {"level": 1, "content": t("Urlaub beantragen")}),
            ("p", "paragraph", {"content": t("Wähle Zeitraum und Vertretung für deinen Urlaub aus.")}),
        ]),
        "zz52_reise": ("Reisekosten", [
            ("h", "heading", {"level": 1, "content": t("Reisekosten abrechnen")}),
            ("p", "paragraph", {"content": t("Belege für Bahn und Hotel hochladen und Spesen einreichen.")}),
        ]),
    }
    for did, (title, blocks) in docs.items():
        await add_doc(db, did, title)
        async with db() as s:
            for i, (suffix, typ, props) in enumerate(blocks):
                await s.execute(
                    text("INSERT INTO blocks (id, doc_id, position, type, props) VALUES (:i, :d, :p, :t, CAST(:pr AS jsonb))"),
                    {"i": f"{did}_{suffix}", "d": did, "p": f"a{i}", "t": typ, "pr": json.dumps(props)})
            await s.commit()
        async with db() as s:
            await reembed_source(s, "document", did, emb)

    res = await search_mod.hybrid_search("Formular für Bestellungen", ANNA, ["document"], 5)
    with capsys.disabled():
        print("\nTop-Treffer:", [(h.id, round(h.score, 4)) for h in res.hits])
    assert res.hits[0].id == "zz52_order"
    assert res.hits[0].block_ids
