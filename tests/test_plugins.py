"""ทดสอบ plugin system (v3.8) — โหลด/ติดตั้ง/ลบ plugin + ลงทะเบียน tool/repl/cli"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import yousini_plugins as P

PLUG_CODE = '''
NAME = "hello"
VERSION = "1.0"
DESCRIPTION = "plugin ทดสอบ"
TOOLS = [{"type": "function", "function": {"name": "hello_greet", "description": "ทักทาย",
          "parameters": {"type": "object", "properties": {"name": {"type": "string"}},
                         "required": ["name"]}}}]
def impl_hello_greet(args, ctx):
    return f"สวัสดี {args.get('name')} จาก {ctx['cwd']}"
REPL_COMMANDS = {"/hello": "ทักทาย"}
def repl_hello(args, agent):
    return "repl:" + (args or "โลก")
CLI_COMMANDS = {"hello-cli": "คำสั่ง cli"}
def cli_hello_cli(argv, opts):
    return "cli:" + str(opts)
'''


def _make_plugin(root, name, code=PLUG_CODE, manifest=None):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.py").write_text(code, encoding="utf-8")
    if manifest:
        (d / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return d


@pytest.fixture
def pdir(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUSINI_PLUGINS_DIR", str(tmp_path / "plugins"))
    return tmp_path


def test_load_plugins_registers_all(pdir):
    _make_plugin(pdir / "plugins", "hello", manifest={"name": "hello", "version": "2.0"})
    agg = P.load_plugins()
    assert len(agg["schemas"]) == 1
    assert agg["schemas"][0]["function"]["name"] == "hello_greet"
    assert "hello_greet" in agg["impls"]
    r = agg["impls"]["hello_greet"]({"name": "บี"}, {"cwd": "/work"})
    assert "สวัสดี บี" in r and "/work" in r
    assert "/hello" in agg["repl"]
    assert agg["repl"]["/hello"][0]("", None) == "repl:โลก"
    assert "hello-cli" in agg["cli"]
    assert agg["cli"]["hello-cli"][0]([], {}) == "cli:{}"
    assert agg["plugins"][0]["version"] == "2.0"   # meta มาจาก plugin.json
    assert agg["plugins"][0]["name"] == "hello"


def test_disabled_plugin_skipped(pdir):
    _make_plugin(pdir / "plugins", "hello", manifest={"name": "hello", "enabled": False})
    agg = P.load_plugins()
    assert agg["plugins"] == []
    assert agg["schemas"] == []


def test_broken_plugin_skipped(pdir):
    (pdir / "plugins" / "bad").mkdir(parents=True)
    (pdir / "plugins" / "bad" / "plugin.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    agg = P.load_plugins()
    assert agg["plugins"] == []
    assert agg["schemas"] == []


def test_install_and_remove(pdir):
    src = _make_plugin(pdir.parent, "hello")
    msg = P.install(str(src), "hello")
    assert "ติดตั้ง plugin 'hello'" in msg
    assert P.list_plugins()[0]["name"] == "hello"
    msg2 = P.remove("hello")
    assert "ลบ plugin 'hello'" in msg2
    assert P.list_plugins() == []


def test_install_errors(pdir):
    assert "Error" in P.install(str(pdir / "nope"), "x")
    (pdir / "plain").mkdir()
    (pdir / "plain" / "readme.txt").write_text("x", encoding="utf-8")
    assert "Error" in P.install(str(pdir / "plain"), "plain")   # ไม่มี plugin.py
    assert "Error" in P.install(str(pdir / "hello"), "bad-name!")  # ชื่อผิด
    assert "ไม่พบ plugin" in P.remove("nonexistent")


def test_list_empty(pdir):
    assert P.list_plugins() == []