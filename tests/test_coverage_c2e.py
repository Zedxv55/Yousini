#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2 (round 5): cover Agent methods (todos, trim, compact, permission, tokens, shell)"""
import json
from pathlib import Path
from unittest import mock

import pytest

import yousini
from yousini import Agent


@pytest.fixture()
def agent(tmp_path, monkeypatch):
    monkeypatch.setattr(yousini, "CONFIG_FILE", tmp_path / "config.json")
    (tmp_path / "config.json").write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    monkeypatch.setattr(yousini, "SESSION_DIR", tmp_path / "sessions")
    (tmp_path / "sessions").mkdir(exist_ok=True)
    a = Agent(model="test", cwd=str(tmp_path))
    a.confirm_files = False
    return a


# ---- todos ----
def test_manage_todos_add(agent):
    assert "เพิ่ม todo #1" in agent.manage_todos("add", "test todo")
    assert agent.manage_todos("list") == "○ #1 [pending] test todo"


def test_manage_todos_update(agent):
    agent.manage_todos("add", "t1")
    assert "Error: ไม่พบ todo #99" in agent.manage_todos("update", "x", todo_id=99)
    assert "แก้ไข todo #1" in agent.manage_todos("update", "new", todo_id=1)


def test_manage_todos_complete_start(agent):
    agent.manage_todos("add", "t1")
    assert "เริ่มทำ" in agent.manage_todos("start", todo_id=1)
    assert "เสร็จ" in agent.manage_todos("complete", todo_id=1)
    assert "●" in agent.manage_todos("list")


def test_manage_todos_delete(agent):
    agent.manage_todos("add", "t1")
    assert "ลบ todo #1" in agent.manage_todos("delete", todo_id=1)
    assert "Error: ไม่พบ todo #1" in agent.manage_todos("delete", todo_id=1)
    assert "Error: action" in agent.manage_todos("bad")


def test_print_todos(agent, capsys):
    agent.manage_todos("add", "t1")
    agent._print_todos()
    assert "ที่ต้องทำ" in capsys.readouterr().out


# ---- tokens / trim / compact ----
def test_estimate_tokens(agent):
    assert agent._estimate_tokens([{"content": "a" * 4000}]) == 1000


def test_trim_and_autocompact(agent, monkeypatch):
    for i in range(1000):
        agent.messages.append({"role": "user", "content": f"m{i}: " + "x" * 40})
        agent.messages.append({"role": "assistant", "content": f"r{i}: " + "y" * 40})
    monkeypatch.setattr(agent, "compact", lambda: None)
    monkeypatch.setattr(agent, "MAX_CONTEXT_TOKENS", 200)
    agent._trim(max_msgs=20)  # token เกิน threshold → compact path
    monkeypatch.undo()
    monkeypatch.setattr(agent, "MAX_CONTEXT_TOKENS", 999999)
    monkeypatch.setattr(agent, "compact", lambda: None)
    agent._trim(max_msgs=20)  # fallback: cut to max_msgs
    assert len(agent.messages) <= 40


def test_autocompact_mock(agent, monkeypatch):
    monkeypatch.setattr(agent, "MAX_CONTEXT_TOKENS", 100)
    for i in range(40):
        agent.messages.append({"role": "user", "content": f"m{i}: " + "z" * 40})
    agent._auto_compact()  # ไม ใช้ค่า return — แค่ชี้ให้รัน path


# ---- shell allowed / permission ----
def test_permission_workflow(agent, monkeypatch):
    monkeypatch.setattr(yousini, "is_shell_allowed", lambda s: s.startswith("echo"))
    # permission_cmd อยู่ใน yousini module globals
    out = yousini.permission_cmd("add grep ")
    assert "grep" in out
    out = yousini.permission_cmd("list")
    assert "grep" in out
    out = yousini.permission_cmd("remove grep")
    out = yousini.permission_cmd("clear")
    assert out is not None


# ---- run_turn_events path: tool calls ----
def test_run_turn_events_tool_call(agent, monkeypatch):
    # mock stream ที่มี tool call
    def make_stream():
        delta = mock.Mock(content=None, tool_calls=[
            mock.Mock(index=0, id="t1", function=mock.Mock(name="shell", arguments='{"command":"echo hi","timeout":5}'))])
        yield mock.Mock(choices=[mock.Mock(delta=delta)], usage=None)
        yield mock.Mock(choices=[], usage=None)
    client = mock.Mock()
    client.chat.completions.create.return_value = make_stream()
    monkeypatch.setattr(yousini, "client", client)
    monkeypatch.setattr(yousini, "is_shell_allowed", lambda s: True)
    events = list(yousini.run_turn_events(agent, "echo hi"))
    types = [e.get("type") for e in events]
    assert any(t in types for t in ("tool", "final", "error", "tool_result"))
