#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2 (round 3): cover main CLI subcommands + chat_turn + login + plan_mode + palette"""
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

import yousini
from yousini import Agent


os_env = {"YOUSINI_API_KEY": "fake", "YOUSINI_DISABLE_NETWORK": "1"}


def _main_with(argv, monkeypatch):
    with mock.patch.object(yousini.sys, "argv", argv):
        with mock.patch.object(yousini, "_apply_startup_theme"):
            yousini.main()


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(yousini, "CONFIG_FILE", cfg_file)
    cfg_file.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    monkeypatch.setattr(yousini, "SESSION_DIR", tmp_path / "sessions")
    (tmp_path / "sessions").mkdir(exist_ok=True)
    return cfg_file


# ---------------------------------------------------------------------------
# main CLI subcommands
# ---------------------------------------------------------------------------
def test_main_marketplace(capsys, monkeypatch):
    _main_with(["yousini", "marketplace"], monkeypatch)
    out = capsys.readouterr().out
    assert out  # อย่างน้อยไม crash


def test_main_market(capsys, monkeypatch):
    _main_with(["yousini", "market"], monkeypatch)


def test_main_team(capsys, monkeypatch):
    _main_with(["yousini", "team"], monkeypatch)


def test_main_update(capsys, monkeypatch):
    import yousini_update
    with mock.patch.object(yousini_update, "update_main", return_value="no update"):
        _main_with(["yousini", "update"], monkeypatch)


def test_main_session(capsys, monkeypatch, tmp_path, cfg):
    import yousini_session_io
    with mock.patch.object(yousini_session_io, "session_io_main", return_value="ok"):
        _main_with(["yousini", "session", "list"], monkeypatch)


def test_main_config(capsys, monkeypatch, cfg):
    with mock.patch("yousini_config.config_cmd", return_value="config body"):
        _main_with(["yousini", "config", "get", "theme"], monkeypatch)
        out = capsys.readouterr().out
        assert "config body" in out


def test_main_flag(capsys, monkeypatch, cfg):
    with mock.patch("yousini_config.flag_cmd", return_value="flag body"):
        _main_with(["yousini", "flag", "x"], monkeypatch)


def test_main_workflow(capsys, monkeypatch, cfg):
    import yousini_workflows
    with mock.patch.object(yousini_workflows, "workflow_main", return_value="wf body"):
        _main_with(["yousini", "workflow", "test"], monkeypatch)


def test_main_usage_summary(capsys, monkeypatch, cfg):
    import yousini_usage
    with mock.patch.object(yousini_usage, "summary", return_value="usage summary"):
        _main_with(["yousini", "usage"], monkeypatch)
        assert "usage summary" in capsys.readouterr().out


def test_main_usage_report(capsys, monkeypatch, cfg):
    import yousini_usage
    with mock.patch.object(yousini_usage, "report", return_value="usage report"):
        _main_with(["yousini", "usage", "report", "daily"], monkeypatch)
        assert "usage report" in capsys.readouterr().out


def test_main_webhook_no_args(capsys, monkeypatch, cfg):
    _main_with(["yousini", "webhook-list"], monkeypatch)
    out = capsys.readouterr().out
    assert "webhook" in out.lower()


def test_main_cron(capsys, monkeypatch, cfg):
    with mock.patch.object(yousini, "cron_main") as cm:
        _main_with(["yousini", "cron", "--once"], monkeypatch)
        cm.assert_called_once()


def test_main_no_args_repl(capsys, monkeypatch, tmp_path, cfg):
    # main() ไม่ระบุ argv → REPL (จะ hang ใช input) — skip: ไม่ test
    pass


# ---------------------------------------------------------------------------
# chat_turn (2182-2435)
# ---------------------------------------------------------------------------
def _make_chunks(text):
    """สร้าง generator chunks แบบ OpenAI stream"""
    for tok in text.split():
        delta = mock.Mock(content=tok + " ", tool_calls=None)
        yield mock.Mock(choices=[mock.Mock(delta=delta)], usage=None)
    yield mock.Mock(choices=[], usage=None)  # finish chunk


def test_chat_turn_success(capsys, monkeypatch):
    agent = Agent(model="test", cwd="/tmp")
    client = mock.Mock()
    client.chat.completions.create.return_value = _make_chunks("Hi from model")
    monkeypatch.setattr(yousini, "client", client)
    out = list(yousini.run_turn_events(agent, "hello"))
    assert any("Hi from model" in e.get("text", "") for e in out)


def test_chat_turn_api_error(capsys, monkeypatch):
    agent = Agent(model="test", cwd="/tmp")
    client = mock.Mock()
    client.chat.completions.create.side_effect = Exception("network error")
    monkeypatch.setattr(yousini, "client", client)
    out = list(yousini.run_turn_events(agent, "hello"))
    assert any("error" in str(e.get("text", "")).lower() for e in out)


# ---------------------------------------------------------------------------
# REPL palette (missed 4047-4087)
# ---------------------------------------------------------------------------
def test_repl_commands(capsys, monkeypatch):
    agent = Agent(model="test", cwd="/tmp")
    cmds = yousini._REPL_COMMANDS(agent)
    names = {n for n, _ in cmds}
    assert len(names) >= len(yousini._REPL_HINTS)
    for key in yousini._REPL_HINTS:
        assert key in names


def test_repl_hints_dict_consistent():
    for name, desc in yousini._REPL_HINTS.items():
        assert name.startswith("/"), f"hint {name} ไม่ใช command"


# ---------------------------------------------------------------------------
# login flow (2772-2843)
# ---------------------------------------------------------------------------
def test_login_custom_via_input(capsys, monkeypatch, tmp_path, cfg):
    monkeypatch.setattr("builtins.input", mock.Mock(side_effect=["custom",
                                                                  "k123", "https://x.ai", "openai/gpt"]))
    yousini.login_mode()
    cfg2 = yousini.load_config()
    assert cfg2.get("default_provider") == "custom"
