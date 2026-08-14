"""ทดสอบ export/import session (v3.8) — yousini_session_io"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import yousini_session_io as IO


class _FakeStore:
    def __init__(self):
        self.d = {}

    def load(self, name):
        return self.d.get(name)

    def save(self, name, messages, meta):
        self.d[name] = {"name": name, "saved_at": "now", "messages": messages, "meta": meta}


@pytest.fixture
def store():
    s = _FakeStore()
    s.d["s1"] = {"name": "s1", "saved_at": "2026-08-14T00:00:00",
                 "messages": [{"role": "system", "content": "sys"},
                              {"role": "user", "content": "สวัสดี"},
                              {"role": "assistant", "content": "มีอะไรให้ช่วยไหม"}],
                 "meta": {"model": "m", "cwd": "/x"}}
    return s


def test_export_json(store, tmp_path):
    r = IO.export_session(store, "s1", str(tmp_path / "out.json"), "json")
    assert r["ok"] and r["count"] == 3
    assert os.path.isfile(r["path"])
    d = json.loads(Path(r["path"]).read_text(encoding="utf-8"))
    assert d["messages"][1]["content"] == "สวัสดี"
    assert d.get("exported_at")


def test_export_md(store, tmp_path):
    r = IO.export_session(store, "s1", str(tmp_path / "out.md"), "md")
    assert r["ok"] and r["fmt"] == "md"
    text = Path(r["path"]).read_text(encoding="utf-8")
    assert "# Session: s1" in text
    assert "**User:**" in text and "สวัสดี" in text
    assert "**Assistant:**" in text


def test_export_missing(store, tmp_path):
    r = IO.export_session(store, "nope", str(tmp_path / "x.json"))
    assert not r["ok"] and "ไม่พบ session" in r["error"]


def test_export_bad_fmt(store, tmp_path):
    r = IO.export_session(store, "s1", str(tmp_path / "x.txt"), "txt")
    assert not r["ok"] and "fmt" in r["error"]


def test_import_json(store, tmp_path):
    p = tmp_path / "exp.json"
    p.write_text(json.dumps({"name": "orig",
                             "messages": [{"role": "user", "content": "x"}],
                             "meta": {"model": "m"}}), encoding="utf-8")
    r = IO.import_session(store, str(p))
    assert r["ok"] and r["name"] == "orig" and r["count"] == 1
    assert store.d["orig"]["meta"].get("imported_from")


def test_import_with_new_name(store, tmp_path):
    p = tmp_path / "exp.json"
    p.write_text(json.dumps({"name": "orig",
                             "messages": [{"role": "user", "content": "x"}]}), encoding="utf-8")
    r = IO.import_session(store, str(p), new_name="renamed")
    assert r["ok"] and r["name"] == "renamed"
    assert "renamed" in store.d


def test_import_errors(store, tmp_path):
    r = IO.import_session(store, str(tmp_path / "nope.json"))
    assert not r["ok"] and "ไม่พบไฟล์" in r["error"]
    bad = tmp_path / "bad.json"
    bad.write_text("not json{{{", encoding="utf-8")
    r2 = IO.import_session(store, str(bad))
    assert not r2["ok"]
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"name": "e"}), encoding="utf-8")
    r3 = IO.import_session(store, str(empty))
    assert not r3["ok"] and "messages" in r3["error"]


def test_export_import_roundtrip(store, tmp_path):
    out = tmp_path / "sess"
    r1 = IO.export_session(store, "s1", str(out), "json")
    assert r1["ok"]
    st2 = _FakeStore()
    r2 = IO.import_session(st2, r1["path"])
    assert r2["ok"]
    assert st2.d["s1"]["messages"] == store.d["s1"]["messages"]