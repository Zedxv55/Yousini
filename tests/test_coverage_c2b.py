#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2 (round 2): is_shell_allowed / permission_cmd / _read_cfg_light"""
import json
from pathlib import Path
from unittest import mock

import pytest

import yousini


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(yousini, "CONFIG_FILE", cfg_file)
    cfg_file.write_text(json.dumps({"allow_shell_prefix": ["echo ", "ls"],
                                    "theme": "dark"}),
                        encoding="utf-8")
    return cfg_file


def test_is_shell_allowed_hit(cfg):
    assert yousini.is_shell_allowed("echo hello")
    assert yousini.is_shell_allowed("ls -la")


def test_is_shell_allowed_miss(cfg):
    assert not yousini.is_shell_allowed("rm -rf /")
    assert not yousini.is_shell_allowed("")


def test_is_shell_allowed_no_config(tmp_path, monkeypatch):
    monkeypatch.setattr(yousini, "CONFIG_FILE", tmp_path / "missing.json")
    assert not yousini.is_shell_allowed("echo x")


def test_permission_cmd_add(cfg):
    out = yousini.permission_cmd("add pytest")
    assert "pytest" in out


def test_permission_cmd_list(cfg):
    out = yousini.permission_cmd("list")
    assert "echo" in out


def test_permission_cmd_remove(cfg):
    out = yousini.permission_cmd("remove ls")
    assert "ls" in out


def test_permission_cmd_clear(cfg):
    out = yousini.permission_cmd("clear")
    cfg2 = yousini.load_config()
    assert cfg2.get("allow_shell_prefix") == []


def test_permission_cmd_usage(cfg):
    out = yousini.permission_cmd("")
    assert "permission" in out


def test_read_cfg_light(cfg):
    cfg2 = yousini._read_cfg_light()
    assert cfg2.get("theme") == "dark"
