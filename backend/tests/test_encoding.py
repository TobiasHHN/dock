"""B2: Textdateien immer mit encoding="utf-8" lesen/schreiben (unter Windows ist der Standard cp1252, Umlaute werden kaputt)."""
import ast
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _missing_encoding(path: Path) -> list[str]:
    bad = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        kws = {k.arg for k in node.keywords}
        if name in ("read_text", "write_text") and "encoding" not in kws:
            bad.append(f"{path.name}:{node.lineno} {name}")
        if name == "open" and isinstance(f, ast.Name):  # builtin open()
            mode = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else ""
            for k in node.keywords:
                if k.arg == "mode" and isinstance(k.value, ast.Constant):
                    mode = k.value.value
            if "b" not in str(mode) and "encoding" not in kws and len(node.args) < 4:
                bad.append(f"{path.name}:{node.lineno} open")
    return bad


def test_all_text_io_declares_encoding():
    files = [p for d in ("demo", "backend/app", "backend/tests") for p in (ROOT / d).rglob("*.py")
             if ".venv" not in p.parts and "node_modules" not in p.parts]
    assert files
    bad = [b for p in files for b in _missing_encoding(p)]
    assert not bad, bad


def test_fallback_template_keeps_umlauts():
    spec = importlib.util.spec_from_file_location("demo_fallback_enc", ROOT / "demo" / "fallback.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    text = mod.TEMPLATE.read_text(encoding="utf-8")
    assert "Bestellung auslösen" in text
    assert "auslösen" in json.dumps(json.loads(text), ensure_ascii=False)
