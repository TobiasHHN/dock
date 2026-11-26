from pathlib import Path

from app.imports.docx import parse_docx
from app.imports.preview import summarize_ops
from app.imports.xlsx import parse_xlsx

FILES = Path(__file__).resolve().parents[2] / "spec" / "fixtures" / "files"


def _walk(blocks):
    for block in blocks:
        yield block
        yield from _walk(block.get("children", []))


def test_xlsx_preview_shows_schema_and_row_count_without_values():
    result = parse_xlsx((FILES / "uebersicht.xlsx").read_bytes())

    preview = summarize_ops(result.ops)
    table = preview["tables"][0]

    assert table["id"] == result.created["tables"][0]["id"]
    assert table["rows"] == result.created["tables"][0]["rows"]
    assert table["columns"]
    assert all(column.get("id") and column.get("type") for column in table["columns"])
    assert "values" not in table


def test_docx_preview_exposes_nested_form_blocks_and_field_types():
    result = parse_docx((FILES / "formular.docx").read_bytes())

    preview = summarize_ops(result.ops)
    document = preview["documents"][0]
    blocks = list(_walk(document["blocks"]))
    form = next(block for block in blocks if block["type"] == "form")
    fields = [block for block in blocks if block["type"] in ("field", "line_items")]

    assert document["id"] == result.created["documents"][0]["id"]
    assert all(block.get("id") and block.get("type") for block in blocks)
    assert form["id"] == result.created["documents"][0]["form"]["block"]
    assert fields
    assert all("key" in block["props"] for block in fields)
    line_items = next(block for block in fields if block["type"] == "line_items")
    assert all(column.get("key") and column.get("input") for column in line_items["props"]["columns"])
