#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for install.py — launcher + PATH (เฉพาะ POSIX paths)"""
import subprocess
from pathlib import Path
from unittest import mock

import pytest
import sys

import install


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(install, "BIN", tmp_path / "bin")
    monkeypatch.setattr(install, "ROOT", Path("/tmp/__yousini_fake_root__"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    yield


@pytest.mark.skipif(sys.platform == "win32",
                    reason="POSIX-only")
def test_write_launcher_posix(tmp_path):
    launcher = install._write_launcher()
    assert launcher.exists()
    assert launcher.stat().st_mode & 0o111
    text = launcher.read_text(encoding="utf-8")
    assert "exec" in text and "$@" in text


@pytest.mark.skipif(sys.platform == "win32",
                    reason="POSIX-only")
def test_add_to_path_creates_rcfile(tmp_path):
    install._add_to_path()
    rc = Path.home() / ".bashrc"
    assert rc.is_file()
    assert "export PATH" in rc.read_text(encoding="utf-8")
    changed, msg = install._add_to_path()
    assert not changed and "มีอยู่แล้ว" in msg


def test_add_to_path_zshrc(tmp_path):
    (Path.home() / ".zshrc").write_text("# zsh\n", encoding="utf-8")
    install._add_to_path()
    assert (Path.home() / ".zshrc").read_text(encoding="utf-8").startswith("# zsh")


@pytest.mark.skipif(sys.platform == "win32",
                    reason="POSIX-only")
def test_remove_from_path_posix():
    changed, msg = install._remove_from_path()
    assert not changed and "เอง" in msg


@pytest.mark.skipif(sys.platform == "win32",
                    reason="POSIX-only")
def test_install_posix(tmp_path, capsys):
    rc = Path.home() / ".bashrc"
    rc.write_text("old\n", encoding="utf-8")
    rc0 = install._add_to_path()
    (install.ROOT / "yousini.py").parent.mkdir(parents=True, exist_ok=True)
    (install.ROOT / "yousini.py").write_text("# fake\n", encoding="utf-8")
    ret = install.install(pip=False)
    assert ret == 0
    assert "launcher" in capsys.readouterr().out
    assert (install.BIN / "yousini").exists()


def test_install_pip_calls_subprocess(tmp_path):
    with mock.patch("subprocess.check_call") as cc:
        ret = install.install(pip=True)
    assert ret == 0
    cc.assert_called_once()
    assert "-e" in cc.call_args[0][0]


def test_install_pip_user(tmp_path):
    with mock.patch("subprocess.check_call") as cc:
        install.install(pip=True, user=True)
    assert "--user" in cc.call_args[0][0]


def test_uninstall_removes_launcher(tmp_path):
    install.BIN.mkdir(parents=True)
    (install.BIN / "yousini").write_text("#!/bin/sh\n", encoding="utf-8")
    ret = install.uninstall()
    assert ret == 0
    assert not (install.BIN / "yousini").exists()


def test_main_uninstall(tmp_path):
    with mock.patch.object(install, "uninstall", return_value=0) as u:
        with mock.patch.object(install.argparse.ArgumentParser, "parse_args",
                               return_value=mock.Mock(uninstall=True, pip=False,
                                                      user=False)):
            assert install.main() == 0
        u.assert_called_once()


def test_main_default(tmp_path):
    install.ROOT.mkdir(parents=True, exist_ok=True)
    (install.ROOT / "yousini.py").write_text("# fake\n", encoding="utf-8")
    with mock.patch.object(install.argparse.ArgumentParser, "parse_args",
                           return_value=mock.Mock(uninstall=False, pip=False,
                                                  user=False)):
        assert install.main() == 0
