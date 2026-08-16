"""ทดสอบ Symbol Index — tree-sitter AST, go-to-definition, refs (Phase 9)"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yousini_symbols import SymbolIndex


PY_SAMPLE = '''\
"""โมดูลตัวอย่าง"""
import os
from typing import Optional

MAX_RETRIES = 3          # ค่าคงที่
DEFAULT_NAME = "yousini"


class Worker:
    """Worker class พร้อม method"""

    def __init__(self, name: str = DEFAULT_NAME):
        self.name = name

    def greet(self, loud: bool = False) -> str:
        msg = f"สวัสดี {self.name}"
        return msg.upper() if loud else msg


def helper(value: int) -> Optional[int]:
    if value <= 0:
        return None
    return value * 2


class Worker2(Worker):
    pass
'''

JS_SAMPLE = '''\
// ตัวอย่าง JavaScript
const PORT = 3000;

function add(a, b) {
  return a + b;
}

class Server {
  constructor(port = PORT) {
    this.port = port;
  }
  start() {
    return this.port;
  }
}

export const NAME = "yousini";
'''


def _make_tree(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "worker.py").write_text(PY_SAMPLE, encoding="utf-8")
    (tmp_path / "app" / "server.js").write_text(JS_SAMPLE, encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "from app.worker import Worker\nw = Worker()\nw.greet()\nhelper(2)\n",
        encoding="utf-8",
    )
    # ไฟล์ควรถูกข้าม
    (tmp_path / "app" / "bundle.min.js").write_text("var x=1;", encoding="utf-8")
    return tmp_path


def test_build_index_python_kinds(tmp_path):
    root = _make_tree(tmp_path)
    idx = SymbolIndex(str(root))
    names = {e["name"]: e for e in idx.entries}
    # class + method + function + ค่าคงที่
    assert names["Worker"]["kind"] == "class"
    assert names["Worker"]["file"].endswith("worker.py")
    assert names["greet"]["kind"] == "method"
    assert "MAX_RETRIES" in names
    assert names["helper"]["kind"] == "function"
    # class ที่สืบทอด (Worker2)
    assert names["Worker2"]["kind"] == "class"


def test_find_def_go_to_definition(tmp_path):
    root = _make_tree(tmp_path)
    idx = SymbolIndex(str(root))
    hit = idx.find("greet")
    assert hit is not None
    assert hit["file"].endswith("worker.py")
    assert hit["line"] >= 1
    assert "greet" in hit["signature"]


def test_js_support(tmp_path):
    root = _make_tree(tmp_path)
    idx = SymbolIndex(str(root))
    names = {e["name"]: e for e in idx.entries}
    assert names["add"]["kind"] == "function"
    assert names["Server"]["kind"] == "class"
    assert names["start"]["kind"] == "method"
    assert "PORT" in names  # ค่าคงที่ JS


def test_refs_across_files(tmp_path):
    root = _make_tree(tmp_path)
    idx = SymbolIndex(str(root))
    refs = idx.refs("greet")
    files = {r["file"] for r in refs}
    assert any(f.endswith("main.py") for f in files)   # การใช้งานใน main.py
    assert any(f.endswith("worker.py") for f in files)  # นิยามใน worker.py


def test_ignore_dirs_and_cache(tmp_path):
    root = _make_tree(tmp_path)
    (root / "node_modules").mkdir()
    (root / "node_modules" / "x.js").write_text("function zzz(){}", encoding="utf-8")
    idx = SymbolIndex(str(root))
    names = {e["name"] for e in idx.entries}
    assert "zzz" not in names       # node_modules ถูกข้าม
    # cache ถูกสร้าง
    assert idx.cache_path.exists() or idx._cache is not None


def test_stale_rebuild(tmp_path):
    root = _make_tree(tmp_path)
    idx = SymbolIndex(str(root))
    first = len(idx.entries)
    # แก้ไฟล์ให้มีฟังก์ชันใหม่
    (root / "app" / "worker.py").write_text(
        PY_SAMPLE + "\n\ndef brand_new_fn():\n    return 1\n", encoding="utf-8"
    )
    idx2 = SymbolIndex(str(root))
    assert len(idx2.entries) == first + 1
    assert idx2.find("brand_new_fn") is not None


# ---- regex fallback (เมื่อไมม tree-sitter) — regression tests
# (bug: requirements.txt ไมม tree-sitter → คนใช pip install -r requirements.txt
# จะตกไป regex fallback ที่แยก method/function ไมถูก — แกแล้วใน yousini_symbols.py)


def _force_regex_index(tmp_path):
    """SymbolIndex ที่บังคับใช regex fallback (จำลองระบบไมม tree-sitter)"""
    from unittest import mock
    with mock.patch.object(SymbolIndex, "_ts_parser", return_value=(None, {})):
        return SymbolIndex(str(tmp_path), use_cache=False)


def test_regex_fallback_python_kinds(tmp_path):
    """regex fallback ต้องแยก method vs function ไดเหมือน tree-sitter"""
    root = _make_tree(tmp_path)
    idx = _force_regex_index(root)
    names = {e["name"]: e for e in idx.entries}
    assert names["Worker"]["kind"] == "class"
    assert names["greet"]["kind"] == "method", "def ใน class ต้องเป็น method"
    assert names["helper"]["kind"] == "function", "def ระดับโมดูลต้องเป็น function"
    assert "MAX_RETRIES" in names and names["MAX_RETRIES"]["kind"] == "constant"


def test_regex_fallback_js_support(tmp_path):
    """regex fallback ต้องแยก JS function/method/class/constant"""
    root = _make_tree(tmp_path)
    idx = _force_regex_index(root)
    names = {e["name"]: e for e in idx.entries}
    assert names["add"]["kind"] == "function", "function นอก class ต้องเป็น function"
    assert names["Server"]["kind"] == "class"
    assert names["start"]["kind"] == "method", "function ใน class ต้องเป็น method"
    assert "PORT" in names and names["PORT"]["kind"] == "constant"


def test_requirements_txt_has_tree_sitter():
    """requirements.txt ต้องม dep เดียวกับ pyproject.toml (กันตกไป regex fallback)"""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    req = open(os.path.join(repo, "requirements.txt"), encoding="utf-8").read()
    try:
        import tomllib  # Python 3.11+
        toml = tomllib
    except ImportError:
        import tomli as toml  # type: ignore
    with open(os.path.join(repo, "pyproject.toml"), "rb") as f:
        py = toml.load(f)
    want = {d.split(">=")[0].split("==")[0] for d in py["project"]["dependencies"]}
    have = {l.strip().split(">=")[0].split("==")[0]
            for l in req.splitlines() if l.strip() and not l.startswith("#")}
    missing = want - have
    assert not missing, f"requirements.txt ขาด dependencies: {missing}"
