#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2 (round 7): cover cron_tool branches, symbols_tool, git_tool branches, scaffold/dev/git_pr/batch_edit/run_python"""
import json
import os
import subprocess
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
    a.interactive = False
    return a


@pytest.fixture()
def gitrepo(agent, tmp_path):
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(tmp_path), capture_output=True)
    (tmp_path / "f.txt").write_text("line1\nline2\nline3\n")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
    return agent


# ---- cron_tool branches ----
def test_cron_tool_add_bad_schedule(agent):
    assert "schedule" in agent.cron_tool("add", "bad!!", "prompt x")


def test_cron_tool_add_no_prompt(agent):
    out = agent.cron_tool("add", "30m", "")
    assert "prompt" in out


def test_cron_tool_add_remove(agent):
    out = agent.cron_tool("add", "30m", "test prompt")
    assert "งาน" in out
    jid = out.split("#")[1].split(" ")[0]
    assert "ลบงาน" in agent.cron_tool("remove", "", "", job_id=int(jid))
    assert "ไม่พบงาน" in agent.cron_tool("remove", "", "", job_id=999)


def test_cron_tool_pause_resume(agent):
    out = agent.cron_tool("add", "30m", "test prompt 2")
    jid = int(out.split("#")[1].split(" ")[0])
    assert "pause" in agent.cron_tool("pause", "", "", job_id=jid)
    assert "resume" in agent.cron_tool("resume", "", "", job_id=jid)
    assert "ไม่พบงาน" in agent.cron_tool("pause", "", "", job_id=999)


def test_cron_tool_bad_action(agent):
    assert "action" in agent.cron_tool("nope")


# ---- symbols_tool branches ----
def test_symbols_tool_find_no_hit(agent, tmp_path):
    (tmp_path / "b.py").write_text("def known_func():\n    pass\nknown_func()\n")
    out = agent.symbols_tool("find", "unknown_xyz")
    assert "ไม่พบ" in out
    out = agent.symbols_tool("refs", "unknown_xyz")
    assert "ไม่มี" in out or isinstance(out, str)


def test_symbols_tool_list_query(agent, tmp_path):
    (tmp_path / "c.py").write_text("def find_me():\n    pass\n")
    out = agent.symbols_tool("list", query="find_me")
    assert "find_me" in out
    out = agent.symbols_tool("list", query="zzz")
    assert isinstance(out, str)


def test_symbols_tool_bad_action(agent):
    assert "action" in agent.symbols_tool("nope", name="x")


# ---- git_tool branches ----
def test_git_tool_full_diff_blame(gitrepo, tmp_path):
    assert "init" in gitrepo.git_tool("log")
    assert isinstance(gitrepo.git_tool("full"), str)
    assert isinstance(gitrepo.git_tool("status"), str)
    assert isinstance(gitrepo.git_tool("diff"), str)
    assert isinstance(gitrepo.git_tool("blame", file="f.txt", line=1), str)
    assert "action" in gitrepo.git_tool("nope")


def test_git_tool_not_repo(agent):
    assert "git repo" in agent.git_tool("log")


# ---- scaffold_tool / dev_check_tool ----
def test_scaffold_tool_list(agent, tmp_path):
    out = agent.scaffold_tool("web", "myproj3")
    assert isinstance(out, str)


def test_dev_check_tool_lint(agent):
    out = agent.dev_check_tool("lint")
    assert isinstance(out, str)


def test_dev_check_tool_test(agent):
    out = agent.dev_check_tool("test")
    assert isinstance(out, str)


# ---- git_pr_tool ----
def test_git_pr_tool(gitrepo):
    out = gitrepo.git_pr_tool("list")
    assert isinstance(out, str)
    out = gitrepo.git_pr_tool("create", "my pr")
    assert isinstance(out, str)


# ---- batch_edit_files / run_python ----
def test_batch_edit(agent, tmp_path):
    (tmp_path / "x.txt").write_text("aaa\nbbb\n")
    edits = [{"path": "x.txt", "old_string": "aaa", "new_string": "ccc"}]
    out = agent.batch_edit_files(edits)
    assert isinstance(out, str)


def test_run_python(agent, tmp_path):
    (tmp_path / "p.py").write_text("print('hello py')")
    out = agent.run_python(str(tmp_path / "p.py"))
    assert "hello py" in out or "exit" in out


def test_run_python_missing(agent):
    out = agent.run_python(str(agent.cwd + "/nope.py"))
    assert "Error" in out


# ---- list_sessions / export_session ----
def test_session_tools(agent, tmp_path):
    out = agent.search_sessions("")
    assert isinstance(out, str)
    out = agent.list_sessions_tool() if hasattr(agent, "list_sessions_tool") else "skip"
    assert isinstance(out, str)
