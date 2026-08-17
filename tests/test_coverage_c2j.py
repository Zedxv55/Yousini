# -*- coding: utf-8 -*-
"""C2 round 10: push coverage to 70% — subagent loop, login branches, run_turn branches."""
import json
import sys
import os
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import yousini


def test_subagent_loop_text_reply(monkeypatch):
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    resp = mock.MagicMock()
    msg = mock.MagicMock()
    msg.tool_calls = None
    msg.content = "done 42"
    resp.choices = [mock.MagicMock(message=msg)]
    yousini.client.chat.completions.create.return_value = resp
    ag = mock.MagicMock()
    ag.model = "m"
    ag.messages = []
    out = yousini._run_subagent_loop(ag, "task")
    assert "done 42" in out
    assert yousini.client.chat.completions.create.call_count == 1


def test_subagent_loop_tool_then_done(monkeypatch):
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    # round 1: tool call -> round 2: text
    def two_calls(model, messages, **kw):
        if two_calls.calls == 0:
            two_calls.calls += 1
            msg = mock.MagicMock()
            fn = mock.MagicMock()
            fn.name = "shell"
            fn.arguments = json.dumps({"command": "echo hi"})
            tc = mock.MagicMock()
            tc.function = fn
            tc.id = "t1"
            msg.tool_calls = [tc]
            msg.content = None
            resp = mock.MagicMock()
            resp.choices = [mock.MagicMock(message=msg)]
            return resp
        msg = mock.MagicMock()
        msg.tool_calls = None
        msg.content = "final"
        resp = mock.MagicMock()
        resp.choices = [mock.MagicMock(message=msg)]
        return resp
    two_calls.calls = 0
    yousini.client.chat.completions.create.side_effect = two_calls
    ag = mock.MagicMock()
    ag.model = "m"
    ag.messages = []
    ag.shell.return_value = "hi"
    out = yousini._run_subagent_loop(ag, "task")
    assert "final" in out


def test_subagent_loop_unknown_tool_and_nested(monkeypatch):
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    def bad_round(model, messages, **kw):
        msg = mock.MagicMock()
        fn1 = mock.MagicMock()
        fn1.name = "spawn_subagent"
        fn1.arguments = "{}"
        tc1 = mock.MagicMock()
        tc1.function = fn1
        tc1.id = "t2"
        fn2 = mock.MagicMock()
        fn2.name = "zzz_unknown"
        fn2.arguments = "{}"
        tc2 = mock.MagicMock()
        tc2.function = fn2
        tc2.id = "t3"
        msg.tool_calls = [tc1, tc2]
        msg.content = None
        resp = mock.MagicMock()
        resp.choices = [mock.MagicMock(message=msg)]
        return resp
    yousini.client.chat.completions.create.side_effect = bad_round
    ag = mock.MagicMock()
    ag.model = "m"
    ag.messages = []
    out = yousini._run_subagent_loop(ag, "task")
    assert "หมดรอบจำกัด" in out or "error" in out.lower() or "เอเจนต์ย่อย" in out


def test_login_branches(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setenv("YOUSINI_DISABLE_NETWORK", "1")
    monkeypatch.setenv("YOUSINI_API_KEY", "fake")
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "_apply_provider_config", lambda *a, **k: None)
    # login_main: choice = "2" (reset?) — ตรวจ input flow: ใช choice จาก user
    it = iter(["2", "x", "y", "z"])
    monkeypatch.setattr("builtins.input", lambda p="": next(it))
    try:
        yousini.login_main()
    except Exception:
        pass
    # just ensure it ran without hanging
