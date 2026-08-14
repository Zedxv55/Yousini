"""ทดสอบ LSP engine (yousini_lsp) — hover/definition/references/completion/symbols"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from yousini_lsp import LSPEngine, _path_to_uri

try:
    import tree_sitter  # noqa: F401
    HAS_TS = True
except Exception:
    HAS_TS = False

pytestmark = pytest.mark.skipif(not HAS_TS, reason="ไม่มี tree-sitter")


@pytest.fixture(scope="module")
def proj(tmp_path_factory):
    root = tmp_path_factory.mktemp("lsp_proj") / "proj"
    root.mkdir()
    (root / "math_util.py").write_text(
        "def add(a, b):\n    return a + b\n\n\n"
        "def multiply(a, b):\n    return a * b\n\n\n"
        "class Calculator:\n    def __init__(self):\n        self.total = 0\n\n"
        "    def add_to_total(self, n):\n        self.total = self.total + n\n",
        encoding="utf-8")
    src = root / "main.py"
    src.write_text("from math_util import add\n\nresult = add(2, 3)\nprint(result)\n",
                   encoding="utf-8")
    eng = LSPEngine(root=str(root))
    return eng, src


def test_hover(proj):
    eng, src = proj
    h = eng.hover(_path_to_uri(str(src)), 2, 10)
    assert h and h["name"] == "add" and "def add" in h["markdown"]


def test_definition(proj):
    eng, src = proj
    d = eng.definition(_path_to_uri(str(src)), 2, 10)
    assert d and d["uri"].endswith("math_util.py")
    assert d["range"]["start"]["line"] == 0


def test_references(proj):
    eng, src = proj
    refs = eng.references(_path_to_uri(str(src)), 2, 10)
    assert refs and "main.py" in refs[0]["uri"]


def test_document_symbols(proj):
    eng, src = proj
    ds = eng.document_symbols(_path_to_uri(str(src)))
    assert ds == []                                    # main.py ไม่มี def/class
    mds = eng.document_symbols(_path_to_uri(str(src.parent / "math_util.py")))
    names = [x["name"] for x in mds]
    assert {"add", "multiply", "Calculator"} <= set(names)
    calc = next(x for x in mds if x["name"] == "Calculator")
    assert calc["children"] and calc["children"][0]["name"] == "__init__"


def test_workspace_symbols(proj):
    eng, src = proj
    ws = eng.workspace_symbols("calc")
    assert ws and ws[0]["name"] == "Calculator"


def test_completion(proj):
    eng, src = proj
    labels = [x["label"] for x in eng.completion(_path_to_uri(str(src)), 3, 7)]
    assert labels and all(x.lower().startswith("result") for x in labels)
    labels2 = [x["label"] for x in eng.completion(_path_to_uri(str(src)), 2, 12)]
    assert labels2 and all(x.lower().startswith("add") for x in labels2)


def test_summary(proj):
    eng, src = proj
    s = eng.summary()
    assert s["total"] >= 5