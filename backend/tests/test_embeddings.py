"""Einbetten (Task 5.1): Chunking, Hash-Abgleich, Integration gegen Postgres, optional echtes Modell."""
import os

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.search import chunking
from app.search.embeddings import reembed_source

DB_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://dock:dock@localhost:5433/dock_test")


# ── Hilfen ───────────────────────────────────────────────────────────────────


def blk(id, type, props=None, parent=None, pos="a"):
    return {"id": id, "type": type, "props": props or {}, "parent_id": parent, "position": pos}


def txt(s):
    return [{"t": "text", "text": s}]


def h(id, level, s, pos):
    return blk(id, "heading", {"level": level, "content": txt(s)}, pos=pos)


def p(id, s, pos, parent=None):
    return blk(id, "paragraph", {"content": txt(s)}, parent=parent, pos=pos)


class FakeEmbedder:
    model_name = "fake"

    def __init__(self):
        self.calls: list[list[str]] = []

    async def embed(self, texts):
        self.calls.append(list(texts))
        return [[float(len(t) % 7)] + [0.0] * 383 for t in texts]


# ── Chunking ─────────────────────────────────────────────────────────────────


def test_sections_by_heading_levels():
    blocks = [
        p("b0", "Vorwort", "a"),
        h("h1", 1, "Bestellung", "b"),
        p("p1", "Erster Absatz", "c"),
        h("h2", 2, "Details", "d"),
        p("p2", "Zweiter Absatz", "e"),
        h("h3", 2, "Weiteres", "f"),
        p("p3", "Dritter Absatz", "g"),
        h("h4", 1, "Ende", "h"),
        p("p4", "Letzter Absatz", "i"),
    ]
    chunks = chunking.chunk_document("Doc", blocks)
    assert [c.block_ids for c in chunks] == [
        ["b0"],
        ["h1", "p1"],
        ["h2", "p2"],
        ["h3", "p3"],
        ["h4", "p4"],
    ]
    assert chunks[0].content == "Doc\nVorwort"
    assert chunks[2].content.startswith("Doc > Bestellung > Details\n")
    assert "Zweiter Absatz" in chunks[2].content
    # H2 "Weiteres" ist Geschwister von "Details", nicht Kind
    assert chunks[3].content.startswith("Doc > Bestellung > Weiteres\n")


def test_nested_blocks_in_tree_order():
    blocks = [
        h("h", 1, "Liste", "a"),
        blk("l", "list", pos="b"),
        blk("i2", "list_item", {"content": txt("zweitens")}, parent="l", pos="b"),
        blk("i1", "list_item", {"content": txt("erstens")}, parent="l", pos="a"),
        blk("q", "quote", pos="c"),
        p("qp", "Zitat", "a", parent="q"),
    ]
    (c,) = chunking.chunk_document("Doc", blocks)
    assert c.block_ids == ["h", "i1", "i2", "qp"]
    assert c.content.index("erstens") < c.content.index("zweitens") < c.content.index("Zitat")


def test_form_fields_code_table_view_labels():
    blocks = [
        h("h", 1, "Formular", "a"),
        blk("f", "form", {"buttons": [{"id": "x", "label": "Absenden"}]}, pos="b"),
        blk("fld", "field", {"key": "lieferant", "label": "Lieferant"}, parent="f", pos="a"),
        blk("li", "line_items", {"key": "pos", "label": "Positionen", "columns": [{"key": "m", "label": "Menge"}]}, parent="f", pos="b"),
        blk("c", "code", {"text": "print(1)"}, pos="c"),
        blk("tv", "table_view", {"table": "bestellungen"}, pos="d"),
        blk("div", "divider", pos="e"),
    ]
    (c,) = chunking.chunk_document("Doc", blocks)
    for s in ("Absenden", "Lieferant", "Positionen Menge", "print(1)", "Tabelle bestellungen"):
        assert s in c.content
    assert c.block_ids == ["h", "f", "fld", "li", "c", "tv"]


def test_inline_ignores_mentions_and_values():
    content = [{"t": "text", "text": "Hallo "}, {"t": "mention", "target": "usr_1"}, {"t": "link", "text": "Link", "href": "x"}]
    assert chunking.inline_text(content) == "Hallo Link"


def test_split_at_token_limit():
    blocks = [h("h", 1, "Lang", "a")] + [p(f"p{i}", " ".join(["wort"] * 200), f"b{i:02d}") for i in range(6)]
    chunks = chunking.chunk_document("Doc", blocks)
    assert len(chunks) > 1
    for c in chunks:
        assert chunking.count_tokens(c.content) <= chunking.MAX_TOKENS
        assert c.content.startswith("Doc > Lang\n")
        assert c.block_ids[0] == "h"
    covered = {b for c in chunks for b in c.block_ids}
    assert covered == {"h"} | {f"p{i}" for i in range(6)}


def test_single_huge_block_is_split():
    blocks = [p("p", " ".join(["w"] * 1200), "a")]
    chunks = chunking.chunk_document("D", blocks)
    assert len(chunks) == 3 and all(c.block_ids == ["p"] for c in chunks)


def test_empty_doc_and_empty_heading_only():
    assert chunking.chunk_document("D", []) == []
    (c,) = chunking.chunk_document("D", [h("h", 1, "Nur Titel", "a")])
    assert c.content == "D > Nur Titel" and c.block_ids == ["h"]


def test_hash_is_content_hash():
    a, b = chunking.Chunk("x", ["1"]), chunking.Chunk("x", ["2"])
    assert a.chunk_hash == b.chunk_hash and len(a.chunk_hash) == 64
    assert chunking.Chunk("y").chunk_hash != a.chunk_hash


def test_table_chunk():
    cols = [{"key": "name", "name": "Name", "type": {"kind": "text"}}, {"key": "preis", "name": "Preis", "type": {"kind": "currency"}}]
    (c,) = chunking.chunk_table("Bestellungen", "bestellungen", cols)
    assert "Tabelle Bestellungen (bestellungen)" in c.content
    assert "Name (name, text)" in c.content and "Preis (preis, currency)" in c.content


def test_workflow_chunk():
    steps = [{"key": "erfassen", "name": "Erfassen", "document": "doc_1"}, {"key": "freigabe", "name": "Freigabe", "document": "doc_2"}]
    (c,) = chunking.chunk_workflow("Bestellprozess", "bestellprozess", steps, {"doc_1": "Bestellung erfassen"})
    assert "Workflow Bestellprozess" in c.content
    assert "Erfassen (erfassen), Freigabe (freigabe)" in c.content
    assert "Schritt Erfassen: Bestellung erfassen" in c.content
    assert "Schritt Freigabe" not in c.content


# ── Integration gegen Postgres ──────────────────────────────────────────────


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(DB_URL)
    try:
        async with engine.connect() as c:
            await c.execute(text("SELECT 1 FROM embeddings LIMIT 1"))
            ok = (await c.execute(text("SELECT count(*) FROM workspaces WHERE id = 'ws_demo'"))).scalar()
    except Exception as e:  # DB nicht erreichbar oder ohne Schema
        await engine.dispose()
        pytest.skip(f"Postgres nicht verfügbar: {e}")
    if not ok:
        await engine.dispose()
        pytest.skip("Workspace ws_demo fehlt")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    yield Session
    async with Session() as s:
        await s.execute(text("DELETE FROM embeddings WHERE source_id LIKE 'zz51_%'"))
        await s.execute(text("DELETE FROM documents WHERE id LIKE 'zz51_%'"))  # Blöcke per CASCADE
        await s.execute(text("DELETE FROM tables WHERE id LIKE 'zz51_%'"))
        await s.commit()
    await engine.dispose()


async def _rows(Session, source_id):
    async with Session() as s:
        r = await s.execute(
            text("SELECT chunk_hash, block_ids, content, model, id FROM embeddings WHERE source_id = :i ORDER BY id"),
            {"i": source_id},
        )
        return [dict(x) for x in r.mappings().all()]


async def test_reembed_document_diff(db):
    import json

    Session = db
    doc = "zz51_doc"
    async with Session() as s:
        await s.execute(text("INSERT INTO documents (id, workspace_id, title) VALUES (:i, 'ws_demo', 'Testdoc')"), {"i": doc})
        for bid, typ, props, pos in [
            ("zz51_h1", "heading", {"level": 1, "content": txt("Eins")}, "a"),
            ("zz51_p1", "paragraph", {"content": txt("Text eins")}, "b"),
            ("zz51_h2", "heading", {"level": 1, "content": txt("Zwei")}, "c"),
            ("zz51_p2", "paragraph", {"content": txt("Text zwei")}, "d"),
        ]:
            await s.execute(
                text("INSERT INTO blocks (id, doc_id, position, type, props) VALUES (:i, :d, :p, :t, CAST(:pr AS jsonb))"),
                {"i": bid, "d": doc, "p": pos, "t": typ, "pr": json.dumps(props)},
            )
        await s.commit()

    emb = FakeEmbedder()
    async with Session() as s:
        stats = await reembed_source(s, "document", doc, emb)
    assert stats["inserted"] == 2 and stats["deleted"] == 0
    first = await _rows(Session, doc)
    assert len(first) == 2 and all(r["model"] == "fake" for r in first)
    assert first[0]["block_ids"] == ["zz51_h1", "zz51_p1"]

    # unverändert: nichts neu eingebettet
    emb.calls.clear()
    async with Session() as s:
        stats = await reembed_source(s, "document", doc, emb)
    assert stats == {"inserted": 0, "deleted": 0, "updated": 0, "kept": 2} and emb.calls == []

    # ein Block ändern: nur dieser Abschnitt wird neu eingebettet
    async with Session() as s:
        await s.execute(
            text("UPDATE blocks SET props = CAST(:pr AS jsonb) WHERE id = 'zz51_p2'"),
            {"pr": json.dumps({"content": txt("Text zwei geändert")})},
        )
        await s.commit()
    emb.calls.clear()
    async with Session() as s:
        stats = await reembed_source(s, "document", doc, emb)
    assert stats["inserted"] == 1 and stats["deleted"] == 1 and stats["kept"] == 1
    assert len(emb.calls) == 1 and len(emb.calls[0]) == 1
    second = await _rows(Session, doc)
    assert len(second) == 2
    assert second[0]["id"] == first[0]["id"]  # erster Abschnitt unberührt
    assert "geändert" in second[1]["content"]

    # Dokument gelöscht: alle Einträge weg
    async with Session() as s:
        await s.execute(text("DELETE FROM documents WHERE id = :i"), {"i": doc})
        await s.commit()
    async with Session() as s:
        stats = await reembed_source(s, "document", doc, emb)
    assert stats["deleted"] == 2
    assert await _rows(Session, doc) == []


async def test_reembed_table_and_block_ids_update(db):
    Session = db
    async with Session() as s:
        await s.execute(
            text("INSERT INTO tables (id, workspace_id, key, name) VALUES ('zz51_tbl', 'ws_demo', 'zz51_tbl', 'Testtabelle')")
        )
        await s.execute(
            text("""INSERT INTO columns (id, table_id, key, name, type, position)
                    VALUES ('zz51_c1', 'zz51_tbl', 'name', 'Name', '{"kind":"text"}', 'a')""")
        )
        await s.commit()
    emb = FakeEmbedder()
    async with Session() as s:
        assert (await reembed_source(s, "table", "zz51_tbl", emb))["inserted"] == 1
    rows = await _rows(Session, "zz51_tbl")
    assert "Testtabelle" in rows[0]["content"] and "Name (name, text)" in rows[0]["content"]

    # block_ids-Update bei gleichem Hash
    async with Session() as s:
        await s.execute(text("UPDATE embeddings SET block_ids = '{x}' WHERE source_id = 'zz51_tbl'"))
        await s.commit()
    async with Session() as s:
        stats = await reembed_source(s, "table", "zz51_tbl", emb)
    assert stats["updated"] == 1 and stats["inserted"] == 0
    assert (await _rows(Session, "zz51_tbl"))[0]["block_ids"] == []


# ── Echtes Modell (optional) ────────────────────────────────────────────────


@pytest.mark.skipif(os.environ.get("RUN_MODEL_TESTS") != "1", reason="RUN_MODEL_TESTS=1 setzen (lädt ~220 MB)")
async def test_real_model_dimension():
    from app.search.embeddings import FastEmbedder

    (v,) = await FastEmbedder().embed(["Formular für Bestellungen"])
    assert len(v) == 384
