#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for C2 coverage — main CLI, REPL handlers, shell/edit/read tools"""
import os
import sys
import subprocess
from pathlib import Path
from unittest import mock

import pytest

import yousini
from yousini import Agent


os.environ["YOUSINI_DISABLE_NETWORK"] = "1"
os.environ["YOUSINI_API_KEY"] = os.environ.get("YOUSINI_API_KEY", "fake-for-tests")
os.environ.setdefault("YOUSINI_BASE_URL", "https://api.mistral.ai/v1")
os.environ.setdefault("YOUSINI_MODEL", "open-mistral-nemo")


@pytest.fixture()
def agent(tmp_path):
    a = Agent(model="test", cwd=str(tmp_path))
    a.confirm_files = False
    a.auto_run = True
    return a


# ---------------------------------------------------------------------------
# main CLI paths
# ---------------------------------------------------------------------------
def test_main_version(capsys):
    with mock.patch.object(yousini.sys, "argv", ["yousini", "--version"]):
        with mock.patch.object(yousini, "_apply_startup_theme"):
            yousini.main()
    assert "Yousini" in capsys.readouterr().out


def test_main_version_short(capsys):
    with mock.patch.object(yousini.sys, "argv", ["yousini", "-v"]):
        with mock.patch.object(yousini, "_apply_startup_theme"):
            yousini.main()
    assert "Yousini" in capsys.readouterr().out


def test_main_help(capsys):
    with mock.patch.object(yousini.sys, "argv", ["yousini", "--help"]):
        with mock.patch.object(yousini, "_apply_startup_theme"):
            yousini.main()
    out = capsys.readouterr().out
    assert "Yousini" in out or "Error" in out


def test_main_init(capsys, tmp_path):
    with mock.patch.object(yousini.sys, "argv", ["yousini", "init", str(tmp_path)]):
        with mock.patch.object(yousini, "_apply_startup_theme"):
            yousini.main()


# ---------------------------------------------------------------------------
# Agent shell / edit_file / read_file
# ---------------------------------------------------------------------------
def test_shell_echo(agent):
    out = agent.shell("echo hello123")
    assert "hello123" in out


def test_shell_readonly(capsys):
    a = Agent(model="test", cwd="/tmp", allow_shell=False)
    out = a.shell("echo x")
    assert "ปิด" in out or "shell" in out.lower()


def test_read_file(agent, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("abc\n", encoding="utf-8")
    out = agent.read_file("a.txt")
    assert "abc" in out


def test_read_file_missing(agent):
    out = agent.read_file("no_such_file_xyz")
    assert "Error" in out


def test_edit_file(agent, tmp_path):
    f = tmp_path / "b.txt"
    f.write_text("old text here", encoding="utf-8")
    out = agent.edit_file("b.txt", "old text", "new text")
    assert f.read_text(encoding="utf-8") == "new text here"


def test_edit_file_no_match(agent, tmp_path):
    f = tmp_path / "c.txt"
    f.write_text("xyz", encoding="utf-8")
    out = agent.edit_file("c.txt", "nope", "x")
    assert "Error" in out


def test_edit_file_readonly(agent, tmp_path):
    a = Agent(model="test", cwd=str(tmp_path), allow_write=False)
    f = tmp_path / "d.txt"
    f.write_text("old", encoding="utf-8")
    out = a.edit_file("d.txt", "old", "new")
    assert "Error" in out


def test_write_file(agent, tmp_path, capsys):
    out = agent.write_file(str(tmp_path / "w.txt"), "hello write")
    assert (tmp_path / "w.txt").read_text(encoding="utf-8") == "hello write"


# ---------------------------------------------------------------------------
# REPL helper functions
# ---------------------------------------------------------------------------
def test_gradient():
    t = yousini._gradient("Hi", ["red", "green"])
    assert t is not None


def test_print_banner(agent, capsys):
    with mock.patch.object(yousini, "_ui_welcome") as uw:
        yousini._print_banner(agent)
        uw.assert_called_once()


def test_repl_completer_hints(capsys):
    yousini._repl_completer_hints("", [("/help", "/help")], 5)


def test_repl_completer_hints_no_matches(capsys):
    yousini._repl_completer_hints("", [], 0)


# ---------------------------------------------------------------------------
# webui loader
# ---------------------------------------------------------------------------
def test_load_webui_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(yousini, "__file__", str(tmp_path / "yousini.py"))
    out = yousini._load_webui()
    assert "<h1>" in out
