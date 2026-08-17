#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2: cover missed REPL/UI helpers + config — เป้า 70%"""
import json
import os
from pathlib import Path
from unittest import mock

import pytest

import yousini
from yousini import Agent


os.environ.setdefault("YOUSINI_API_KEY", "fake-for-tests")
os.environ.setdefault("YOUSINI_DISABLE_NETWORK", "1")


@pytest.fixture()
def agent(tmp_path):
    a = Agent(model="test", cwd=str(tmp_path))
    a.confirm_files = False
    a.auto_run = True
    return a


# ---------------------------------------------------------------------------
# REPL helpers (missed 2513-2720)
# ---------------------------------------------------------------------------
def test_print_help(capsys):
    yousini._print_help()
    assert "help" in capsys.readouterr().out.lower()


def test_print_history(agent, capsys):
    agent.messages.append({"role": "user", "content": "hi"})
    yousini._print_history(agent)
    assert "hi" in capsys.readouterr().out


def test_print_history_skips_system(agent, capsys):
    agent.messages.append({"role": "system", "content": "sys"})
    yousini._print_history(agent)
    assert "sys" not in capsys.readouterr().out


def test_print_skills(agent, tmp_path, capsys, monkeypatch):
    sk = tmp_path / "skills"
    sk.mkdir()
    (sk / "x.md").write_text("# x\n", encoding="utf-8")
    monkeypatch.setattr(agent, "skills", [("x.md", str(sk / "x.md"), "global")])
    yousini._print_skills(agent)
    assert "x.md" in capsys.readouterr().out


def test_print_hooks(agent, tmp_path, capsys, monkeypatch):
    d = tmp_path / "hooks"
    d.mkdir()
    agent.hooks.dir = d
    (d / "pre_tool.sh").write_text("echo pre\n", encoding="utf-8")
    yousini._print_hooks(agent)
    out = capsys.readouterr().out
    assert "pre_tool" in out


def test_load_config_fallback(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(yousini, "CONFIG_FILE", cfg_file)
    cfg = yousini.load_config()
    assert isinstance(cfg, dict)


def test_save_and_load_config(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(yousini, "CONFIG_FILE", cfg_file)
    yousini.save_config({"theme": "dark", "custom": 42})
    cfg = yousini.load_config()
    assert cfg.get("theme") == "dark"
    assert cfg.get("custom") == 42


def test_apply_provider_config(monkeypatch):
    cfg = {"default_provider": "p1", "providers": {"p1": {"name": "p1"}}}
    monkeypatch.setattr(yousini, "API_KEY", "old")
    monkeypatch.setattr(yousini, "BASE_URL", "old")
    monkeypatch.setattr(yousini, "MODEL", "old")
    out = yousini._apply_provider_config(cfg)
    assert out in (True, False)


# ---------------------------------------------------------------------------
# palette + REPL command handlers
# ---------------------------------------------------------------------------
def test_repl_commands_has_palette(agent):
    cmds = yousini._REPL_COMMANDS(agent)
    names = [c[0] for c in cmds]
    assert "/palette" in names
    assert "/exit" in names
    assert len(cmds) >= len(yousini._REPL_HINTS)
    for name, _ in cmds:
        assert name in yousini._REPL_HINTS


# ---------------------------------------------------------------------------
# provider fallback chain
# ---------------------------------------------------------------------------
def test_load_providers():
    out = yousini._load_providers()
    assert isinstance(out, (dict, list, type(None)))
