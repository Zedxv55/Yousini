"""ทดสอบ workflow templates (v3.8) — yousini_workflows"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import yousini_workflows as W


def test_list_builtin():
    names = {t["name"] for t in W.list_templates()}
    assert {"release", "weekly_report", "code_review"} <= names


def test_load_builtin():
    t = W.load_template("release")
    assert t["steps"] and t["steps"][0]["tool"] == "dev_check"
    assert t["source"] == "built-in"


def test_run_workflow_steps():
    calls = []

    def exec_tool(name, args):
        calls.append(("tool", name, args))
        return "OK:" + name

    def chat_turn(text):
        calls.append(("prompt", text))

    r = W.run_workflow("release", exec_tool, chat_turn)
    assert "รันเทมเพลต 'release'" in r
    kinds = [c[0] for c in calls]
    assert "tool" in kinds and "prompt" in kinds
    assert ("tool", "dev_check", {"scope": "all"}) in calls


def test_run_workflow_no_chat_turn():
    calls = []
    r = W.run_workflow("release", lambda n, a: calls.append(n) or "ok", chat_turn=None)
    assert "ข้าม" in r
    assert calls  # tool steps รันได้


def test_run_unknown():
    r = W.run_workflow("nope", lambda *a: "")
    assert "ไม่พบเทมเพลต" in r


def test_run_with_overrides():
    calls = []

    def exec_tool(name, args):
        calls.append(args)
        return "ok"

    W.run_workflow("release", exec_tool, overrides={"dev_check": {"scope": "test"}})
    assert calls[0] == {"scope": "test"}


def test_save_and_load_user_template(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUSINI_WORKFLOWS_DIR", str(tmp_path / "wf"))
    r = W.save_template("mytmpl", '[{"tool": "git", "args": {"action": "status"}}]')
    assert "บันทึกเทมเพลต 'mytmpl'" in r
    assert any(t["name"] == "mytmpl" and t["source"] == "user" for t in W.list_templates())
    t = W.load_template("mytmpl")
    assert t["steps"][0]["tool"] == "git" and t["source"] == "user"


def test_save_bad_input(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUSINI_WORKFLOWS_DIR", str(tmp_path / "wf"))
    assert "Error" in W.save_template("x", "not json")
    assert "Error" in W.save_template("x", '[]')
    assert "Error" in W.save_template("x", '[{"foo": "bar"}]')


def test_workflow_main(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUSINI_WORKFLOWS_DIR", str(tmp_path / "wf"))
    calls = []
    r = W.workflow_main(["list"], lambda n, a: calls.append(n) or "ok")
    assert "release" in r and "weekly_report" in r
    r2 = W.workflow_main(["show", "code_review"], None)
    assert "dev_check" in r2 or "diff" in r2
    r3 = W.workflow_main(["run", "release"], lambda n, a: "ok")
    assert "รันเทมเพลต 'release'" in r3
    r4 = W.workflow_main([], None)
    assert "release" in r4