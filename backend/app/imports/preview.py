"""Kompakte, agentenlesbare Vorschau eines vorbereiteten Imports."""
from typing import Any


def summarize_ops(ops: list[dict[str, Any]]) -> dict[str, Any]:
    tables: dict[str, dict[str, Any]] = {}
    documents: list[dict[str, Any]] = []

    for op in ops:
        if op.get("op") == "table.create":
            table_id = op["id"]
            tables[table_id] = {
                "id": table_id,
                "key": op["key"],
                "name": op["name"],
                "display_column": op.get("display_column"),
                "columns": op.get("columns", []),
                "rows": 0,
            }
        elif op.get("op") == "row.insert":
            table = tables.get(op.get("table"))
            if table is not None:
                table["rows"] += len(op.get("rows", []))
        elif op.get("op") == "doc.create":
            documents.append({
                "id": op["id"],
                "title": op["title"],
                "owner": op.get("owner"),
                "blocks": op.get("blocks", []),
            })

    return {"tables": list(tables.values()), "documents": documents}
