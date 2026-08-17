#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2 (round 4): cover missed main() dispatch paths + core functions"""
import json
import sys
from unittest import mock

import pytest

import yousini
from yousini import Agent


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


# ---- missed 4609-4618: serve ----
def test_main_serve(capsys, monkeypatch, cfg):
    with mock.patch.object(yousini, "serve_main") as rs:
        _main_with(["yousini", "serve"], monkeypatch)
        rs.assert_called_once()


# ---- missed 4622-4629: connect ----
def test_main_connect(capsys, monkeypatch, cfg):
    with mock.patch.object(yousini, "connect_main") as mc:
        _main_with(["yousini", "connect", "x"], monkeypatch)
        mc.assert_called_once()


# ---- missed 4633-4635: mcp ----
def test_main_mcp(capsys, monkeypatch, cfg):
    with mock.patch.object(yousini, "mcp_main") as mm:
        _main_with(["yousini", "mcp", "list"], monkeypatch)
        mm.assert_called_once()


# ---- missed 4639-4642: lsp ----
def test_main_lsp(capsys, monkeypatch, cfg):
    with mock.patch.object(yousini, "lsp_main") as lm:
        _main_with(["yousini", "lsp"], monkeypatch)
        lm.assert_called_once()


# ---- missed 4651-4652: team (main args) ----
def test_main_team_args(capsys, monkeypatch, cfg):
    with mock.patch.object(yousini, "team_main") as tm:
        _main_with(["yousini", "team", "init", "myteam"], monkeypatch)
        tm.assert_called_once()


# ---- missed 4656-4657: agent ----
def test_main_agent(capsys, monkeypatch, cfg):
    with mock.patch.object(yousini, "agent_main") as am:
        _main_with(["yousini", "agent", "spawn"], monkeypatch)
        am.assert_called_once()


# ---- missed 4661-4678: work ----
def test_main_work(capsys, monkeypatch, cfg):
    with mock.patch.object(yousini, "work_main") as wm:
        _main_with(["yousini", "work", "--once"], monkeypatch)
        wm.assert_called_once()


# ---- missed 4682-4690: dev ----
def test_main_dev(capsys, monkeypatch, cfg):
    with mock.patch.object(Agent, "dev_check_tool", return_value="dev ok"):
        _main_with(["yousini", "dev", "all"], monkeypatch)
        assert "dev ok" in capsys.readouterr().out


# ---- missed 4694-4697: pr ----
def test_main_pr_list(capsys, monkeypatch, cfg):
    with mock.patch("yousini_git.pr_list", return_value="pr list"):
        _main_with(["yousini", "pr", "list"], monkeypatch)
        assert "pr list" in capsys.readouterr().out


# ---- missed 4701-4703: plugin ----
def test_main_plugin(capsys, monkeypatch, cfg):
    with mock.patch("yousini_plugins.plugin_main") as pm:
        _main_with(["yousini", "plugin", "list"], monkeypatch)
        pm.assert_called_once()


# ---- missed 4707-4710: session ----
def test_main_session_list(capsys, monkeypatch, cfg):
    with mock.patch("yousini_session_io.session_io_main", return_value="session list"):
        _main_with(["yousini", "session", "list"], monkeypatch)
        assert "session list" in capsys.readouterr().out


# ---- missed 4714-4717: update ----
def test_main_update_args(capsys, monkeypatch, cfg):
    with mock.patch("yousini_update.update_main", return_value="update ok"):
        _main_with(["yousini", "update", "--check"], monkeypatch)
        assert "update ok" in capsys.readouterr().out


# ---- missed 4729-4734: workflow ----
def test_main_workflow_args(capsys, monkeypatch, cfg):
    with mock.patch("yousini_workflows.workflow_main", return_value="wf ok"):
        _main_with(["yousini", "workflow", "run", "test"], monkeypatch)
        assert "wf ok" in capsys.readouterr().out


# ---- missed 4738-4749: usage report ----
def test_main_usage_weekly(capsys, monkeypatch, cfg):
    with mock.patch("yousini_usage.report", return_value="weekly report"):
        _main_with(["yousini", "usage", "weekly"], monkeypatch)
        assert "weekly report" in capsys.readouterr().out


# ---- missed 4796-4830: webhook add/rm ----
def test_main_webhook_add(capsys, monkeypatch, cfg):
    import yousini_webhook
    ws_mock = mock.Mock()
    with mock.patch.object(yousini_webhook, "WebhookStore", return_value=ws_mock):
        _main_with(["yousini", "webhook-add", "myhook", "prompt text"], monkeypatch)
        ws_mock.add.assert_called_once()


def test_main_webhook_rm(capsys, monkeypatch, cfg):
    import yousini_webhook
    ws_mock = mock.Mock()
    with mock.patch.object(yousini_webhook, "WebhookStore", return_value=ws_mock):
        _main_with(["yousini", "webhook-rm", "myhook"], monkeypatch)
        ws_mock.remove.assert_called_once()


# ---- missed 4919-4920: resume ----
def test_main_resume(capsys, monkeypatch, cfg):
    with mock.patch.object(yousini, "resume_main", return_value=None) as rm:
        _main_with(["yousini", "resume"], monkeypatch)
        rm.assert_called_once()
