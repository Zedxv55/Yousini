"""ทดสอบ self-update (v3.8) — yousini_update"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import yousini_update as U


def test_parse_tags():
    out = ("xxx\trefs/tags/v3.7.0\n"
           "xxx\trefs/tags/3.8.0^{}\n"
           "xxx\trefs/tags/v3.9.0\n"
           "xxx\trefs/tags/note-version\n")
    assert U._parse_tags(out) == ["3.9.0", "3.7.0"]


def test_parse_tags_prerelease_sorted():
    out = "x\trefs/tags/v3.10.0\nx\trefs/tags/v3.9.0\nx\trefs/tags/v3.8.0\n"
    assert U._parse_tags(out) == ["3.10.0", "3.9.0", "3.8.0"]


def test_split():
    assert U._split("3.8.1") == (3, 8, 1)
    assert U._split("3.10.0") > U._split("3.9.9")


def test_check_newer(monkeypatch):
    monkeypatch.setattr(U, "latest_version", lambda: "3.9.0")
    r = U.check("3.8.0")
    assert r["newer"] is True and r["latest"] == "3.9.0" and not r["error"]


def test_check_up_to_date(monkeypatch):
    monkeypatch.setattr(U, "latest_version", lambda: "3.8.0")
    r = U.check("3.8.0")
    assert r["newer"] is False


def test_check_cannot_reach(monkeypatch):
    monkeypatch.setattr(U, "latest_version", lambda: "")
    r = U.check("3.8.0")
    assert r["error"] and r["newer"] is False


def test_self_update_no_git(monkeypatch):
    monkeypatch.setattr(U, "_git_bin", lambda: None)
    assert "ไม่พบ git" in U.self_update(".")


def test_self_update_wrong_remote(monkeypatch):
    monkeypatch.setattr(U, "_git_bin", lambda: "git")
    monkeypatch.setattr(U, "_run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout="https://github.com/other/Repo.git\n", stderr=""))
    assert "ไม่ใช่ repo Yousini" in U.self_update(".")


def test_self_update_no_remote(monkeypatch):
    monkeypatch.setattr(U, "_git_bin", lambda: "git")
    monkeypatch.setattr(U, "_run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout="", stderr=""))
    assert "ไม่ใช่ repo Yousini" in U.self_update(".")


def test_self_update_flow(monkeypatch):
    monkeypatch.setattr(U, "_git_bin", lambda: "git")
    calls = []

    def fake_run(args, cwd=None, timeout=30):
        calls.append(list(args))
        if args[0] == "remote":
            return SimpleNamespace(returncode=0,
                                   stdout="https://github.com/Zedxv55/Yousini.git\n",
                                   stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(U, "_run", fake_run)
    msg = U.self_update(".")
    assert "อัปเดตเสร็จ" in msg
    assert ["fetch", "origin"] in calls
    assert ["reset", "--hard", "origin/main"] in calls


def test_update_main_check(monkeypatch):
    monkeypatch.setattr(U, "latest_version", lambda: "4.0.0")
    r = U.update_main(["check"], "3.8.0")
    assert "4.0.0" in r and "ใหม่" in r
    monkeypatch.setattr(U, "latest_version", lambda: "3.8.0")
    r2 = U.update_main(["check"], "3.8.0")
    assert "ล่าสุด" in r2


def test_update_main_go_up_to_date(monkeypatch):
    monkeypatch.setattr(U, "latest_version", lambda: "3.8.0")
    assert "ล่าสุด" in U.update_main(["go"], "3.8.0")


def test_remote_regex():
    m = U._REMOTE_RE.search("https://github.com/Zedxv55/Yousini.git")
    assert m and m.group(1) == "Zedxv55" and m.group(2) == "Yousini"
    m2 = U._REMOTE_RE.search("git@github.com:Zedxv55/Yousini.git")
    assert m2 and m2.group(1) == "Zedxv55"