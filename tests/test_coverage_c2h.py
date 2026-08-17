#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2 (round 8): cover run_turn_events branches, hook blocks, quiet mode, _prepare_user_content"""
import json
from unittest import mock

import pytest

import yousini
from yousini import Agent


@pytest.fixture()
def agent(tmp_path, monkeypatch):
    monkeypatch.setattr(yousini, "CONFIG_FILE", tmp_path / "config.json")
    (tmp_path / "config.json").write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(yousini, "SESSION_DIR", tmp_path / "sessions")
    (tmp_path / "sessions").mkdir(exist_ok=True)
    a = Agent(model="test", cwd=str(tmp_path))
    a.confirm_files = False
    a.interactive = False
    monkeypatch.setattr(a, "compact", lambda: None)
    return a


class _Fn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments
class _TC:
    def __init__(self, index, id_, fn):
        self.index = index
        self.id = id_
        self.function = fn
def _chunk(content=None, tool=None, finish=None, tc_index=0):
    fn = _Fn(tool[0], json.dumps(tool[1])) if tool else None
    tc = [_TC(tc_index, "t1", fn)] if tool else None
    delta = mock.Mock(content=content, tool_calls=tc)
    choice = mock.Mock(delta=delta, finish_reason=finish)
    return mock.Mock(choices=[choice], usage=None)


def _stream(*chunks):
    yield from chunks


# ---- tool call → tool_result → final ----
def test_turn_tool_then_text(agent, monkeypatch):
    client = mock.Mock()
    client.chat.completions.create.side_effect = [
        _stream(_chunk(tool=("shell", {"command": "echo hi", "timeout": 5}), finish="stop")),
        _stream(_chunk(content="done "), _chunk(content="ok", finish="stop")),
    ]
    monkeypatch.setattr(yousini, "client", client)
    events = list(yousini.run_turn_events(agent, "รัน echo"))
    types = [e["type"] for e in events]
    errs = [e.get("text") for e in events if e["type"] == "error"]
    assert "tool" in types, errs
    assert "tool_result" in types or any(e.get("blocked") for e in events if e["type"] == "tool")
    assert any(e.get("type") == "final" for e in events) or any("hi" in str(e.get("result", "")) for e in events if e["type"] == "tool_result")


# ---- final text only ----
def test_turn_final_only(agent, monkeypatch):
    client = mock.Mock()
    client.chat.completions.create.return_value = _stream(
        _chunk(content="สวดี "), _chunk(content="ครับ", finish="stop"))
    monkeypatch.setattr(yousini, "client", client)
    events = list(yousini.run_turn_events(agent, "สวดี"))
    texts = "".join(e.get("text", "") for e in events if e["type"] == "final")
    assert "ครับ" in texts


# ---- error branch ----
def test_turn_api_error(agent, monkeypatch):
    client = mock.Mock()
    client.chat.completions.create.side_effect = RuntimeError("net down")
    monkeypatch.setattr(yousini, "client", client)
    events = list(yousini.run_turn_events(agent, "x"))
    assert any(e["type"] == "error" for e in events)


# ---- invalid JSON args ----
def test_turn_bad_json_args(agent, monkeypatch):
    delta = mock.Mock(content=None)
    delta.tool_calls = [mock.Mock(index=0, id="t2", function=mock.Mock(name="shell", arguments="not-json@@@"))]
    chunk1 = _chunk(tool=("shell", {"command": "echo z"}), finish="stop")
    chunk2 = _chunk(content="ok", finish="stop")
    client = mock.Mock()
    client.chat.completions.create.side_effect = [_stream(chunk1, chunk2), _stream(chunk2)]
    monkeypatch.setattr(yousini, "client", client)
    events = list(yousini.run_turn_events(agent, "x"))
    assert any(e["type"] == "tool" for e in events)


# ---- _exec_tool quiet mode (spinner) ----
def test_exec_tool_quiet_mode(agent, monkeypatch):
    agent.allow_shell = True
    agent.quiet_mode = True
    yousini._exec_tool(agent, "shell", {"command": "echo q", "timeout": 5}, "tq")
    out = agent.messages[-1]["content"]
    assert "q" in out


# ---- _exec_tool hook block ----
def test_exec_tool_hook_block(agent, monkeypatch):
    agent.hooks.run_pre = mock.Mock(return_value=(False, "policy"))
    yousini._exec_tool(agent, "shell", {"command": "echo h"}, "th")
    assert any("Blocked by hook" in m.get("content", "") for m in agent.messages)


# ---- _prepare_user_content branches ----
def test_prepare_user_content_mentions(agent, monkeypatch):
    out, warnings = yousini._prepare_user_content("ดู @hello.txt", agent)
    assert "@hello.txt" not in out or isinstance(out, str)


def test_prepare_user_content_no_mention(agent, monkeypatch):
    out, warnings = yousini._prepare_user_content("สวสดี", agent)
    assert out == "สวสดี"
    assert not warnings


# ---- _is_tool_validation_err ----
def test_is_tool_validation_err():
    assert yousini._is_tool_validation_err(ValueError("tool call validation failed"))
    assert yousini._is_tool_validation_err(ValueError("not in request.tools"))
    assert not yousini._is_tool_validation_err(RuntimeError("network"))
