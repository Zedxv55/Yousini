#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests — sponsor (yousini_sponsor) + self-update (yousini_update)"""
import os
import sys

os.environ.setdefault("YOUSINI_API_KEY", "dummy-test-key")
os.environ.setdefault("YOUSINI_BASE_URL", "https://api.example.test/v1")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest.mock as mock

import yousini_sponsor as sponsor
import yousini_update as update


# ============================================================ sponsor
def test_line_enabled_flags():
    assert sponsor._line_enabled({}) is True
    assert sponsor._line_enabled({"ads_disabled": True}) is False
    assert sponsor._line_enabled({"tier": "pro"}) is False
    assert sponsor._line_enabled({"tier": "free"}) is True


def test_profile_root_default(tmp_path, monkeypatch):
    monkeypatch.setattr(sponsor.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("YOUSINI_PROFILE", raising=False)
    p = sponsor._profile_root()
    assert p == tmp_path / ".yousini"


def test_profile_root_env(tmp_path, monkeypatch):
    monkeypatch.setattr(sponsor.Path, "home", lambda: tmp_path)
    monkeypatch.setenv("YOUSINI_PROFILE", "work")
    p = sponsor._profile_root()
    assert p == tmp_path / ".yousini" / "profiles" / "work"


def test_profile_root_default_ignored(tmp_path, monkeypatch):
    """profile "default" ถูกตีความเป็น root ไมใช profiles/default"""
    monkeypatch.setattr(sponsor.Path, "home", lambda: tmp_path)
    monkeypatch.setenv("YOUSINI_PROFILE", "default")
    p = sponsor._profile_root()
    assert p == tmp_path / ".yousini"


def test_load_cache_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(sponsor.Path, "home", lambda: tmp_path)
    assert sponsor._load_cache() == {}


def test_load_cache_non_dict_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(sponsor.Path, "home", lambda: tmp_path)
    (tmp_path / ".yousini").mkdir()
    (tmp_path / ".yousini" / "sponsor_cache.json").write_text("[1,2,3]")
    assert sponsor._load_cache() == {}


def test_save_and_load_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(sponsor.Path, "home", lambda: tmp_path)
    sponsor._save_cache({"line": "hello", "source": "remote", "fetched": "x"})
    assert sponsor._load_cache() == {"line": "hello", "source": "remote", "fetched": "x"}


def test_fetch_remote_too_long_or_empty(monkeypatch):
    fake_resp = mock.MagicMock()
    fake_resp.read.return_value = ("line1\nline2\n" + "a" * 300).encode("utf-8")
    fake_cm = mock.MagicMock()
    fake_cm.__enter__ = mock.MagicMock(return_value=fake_resp)
    fake_cm.__exit__ = mock.MagicMock(return_value=False)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: fake_cm)
    assert sponsor._fetch_remote("https://x.test") is None


def test_fetch_remote_network_fail(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen",
                        mock.MagicMock(side_effect=OSError("no net")))
    assert sponsor._fetch_remote("https://x.test") is None


def test_fetch_remote_ok(monkeypatch):
    fake_resp = mock.MagicMock()
    fake_resp.read.return_value = "  Sponsor จาก Remote  \nsecond\n".encode("utf-8")
    fake_cm = mock.MagicMock()
    fake_cm.__enter__ = mock.MagicMock(return_value=fake_resp)
    fake_cm.__exit__ = mock.MagicMock(return_value=False)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: fake_cm)
    assert sponsor._fetch_remote("https://x.test") == "Sponsor จาก Remote"


def test_sponsor_line_disabled_returns_none(monkeypatch):
    monkeypatch.delenv("YOUSINI_SPONSOR_URL", raising=False)
    assert sponsor.sponsor_line({"ads_disabled": True}) is None


def test_sponsor_line_placeholder_pool(monkeypatch, tmp_path):
    """ไม่มี remote URL → ใช placeholder pool (หมุนตามวัน — determinitic ในวันเดียวกัน)"""
    monkeypatch.delenv("YOUSINI_SPONSOR_URL", raising=False)
    monkeypatch.setattr(sponsor.Path, "home", lambda: tmp_path)
    line = sponsor.sponsor_line({})
    assert line is not None and len(line) > 5
    # วันเดียวกัน → ค่าเดิมเสมอ
    assert sponsor.sponsor_line({}) == line


def test_sponsor_line_remote_with_fresh_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(sponsor.Path, "home", lambda: tmp_path)
    monkeypatch.setenv("YOUSINI_SPONSOR_URL", "https://x.test")
    now_iso = mock.MagicMock()
    now_iso.isoformat.return_value = "2026-08-16T12:00:00"
    monkeypatch.setattr(sponsor, "datetime", mock.MagicMock(
        now=now_iso,
        fromisoformat=mock.MagicMock(
            return_value=mock.MagicMock())), raising=False)
    # age < TTL → คืน cache
    sponsor._save_cache({"source": "remote", "line": "cached-line",
                         "fetched": "2026-08-16T11:55:00"})
    assert sponsor.sponsor_line({}) == "cached-line"


def test_sponsor_line_remote_fallback_to_cache(monkeypatch, tmp_path):
    """remote ล้ม → ใช cached line"""
    monkeypatch.setattr(sponsor.Path, "home", lambda: tmp_path)
    monkeypatch.setenv("YOUSINI_SPONSOR_URL", "https://x.test")
    monkeypatch.setattr(sponsor, "_fetch_remote", lambda url: None)
    monkeypatch.setattr(sponsor, "datetime", mock.MagicMock(
        now=mock.MagicMock(), fromisoformat=mock.MagicMock(
            return_value=mock.MagicMock())), raising=False)
    sponsor._save_cache({"source": "remote", "line": "cached-line",
                         "fetched": "2026-08-10T00:00:00"})
    assert sponsor.sponsor_line({}) == "cached-line"


def test_sponsor_line_remote_miss_and_no_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(sponsor.Path, "home", lambda: tmp_path)
    monkeypatch.setenv("YOUSINI_SPONSOR_URL", "https://x.test")
    monkeypatch.setattr(sponsor, "_fetch_remote", lambda url: None)
    monkeypatch.setattr(sponsor, "datetime", mock.MagicMock(
        now=mock.MagicMock(), fromisoformat=mock.MagicMock(
            return_value=mock.MagicMock())), raising=False)
    assert sponsor.sponsor_line({}) is None


def test_sponsor_status_string(monkeypatch, tmp_path):
    monkeypatch.setattr(sponsor.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("YOUSINI_SPONSOR_URL", raising=False)
    s = sponsor.sponsor_status({})
    assert "สถานะ: " in s
    assert "local placeholder pool" in s


def test_sponsor_status_pro_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(sponsor.Path, "home", lambda: tmp_path)
    monkeypatch.delenv("YOUSINI_SPONSOR_URL", raising=False)
    s = sponsor.sponsor_status({"tier": "pro"})
    assert "สถานะ: " in s and "ปิด" in s


# ============================================================ self-update
def test_parse_tags_includes_semver_sorted_desc():
    out = ("v3.9.0\n"
           "refs/tags/v3.10.0\n"
           "refs/tags/v3.11.0-beta.1\n"
           "refs/tags/not-a-version\n")
    tags = update._parse_tags(out)
    assert tags[0] == "3.11.0-beta.1"  # sorted desc, beta pass filter
    assert "3.10.0" in tags
    assert "not-a-version" not in tags


def test_split_version():
    assert update._split("3.10.0") == (3, 10, 0)
    assert update._split("3.9") == (3, 9)


def test_check_update_available(monkeypatch):
    monkeypatch.setattr(update, "latest_version", lambda: "3.11.0")
    res = update.check("3.10.0")
    assert res.get("latest") == "3.11.0"
    assert res.get("newer") is True
    assert res.get("error") == ""


def test_check_no_update(monkeypatch):
    monkeypatch.setattr(update, "latest_version", lambda: "3.10.0")
    res = update.check("3.10.0")
    assert res.get("newer") is False


def test_check_older_current_still_ok(monkeypatch):
    monkeypatch.setattr(update, "latest_version", lambda: "3.9.0")
    res = update.check("3.10.0")
    assert res.get("newer") is False


def test_check_network_failure(monkeypatch):
    """ทุกทางของ latest_version ล้ม → คืน "" → newer=False, error ไม่เป่า"""
    def _fail():
        return ""
    monkeypatch.setattr(update, "latest_version", _fail)
    res = update.check("3.10.0")
    assert res.get("newer") is False
    assert res.get("error")


def test_self_update_no_git(monkeypatch):
    monkeypatch.setattr(update, "_git_bin", lambda: None)
    msg = update.self_update("/tmp")
    assert "git" in msg.lower()


def test_self_update_wrong_remote(monkeypatch):
    monkeypatch.setattr(update, "_git_bin", lambda: "/usr/bin/git")
    ok = mock.MagicMock()
    ok.stdout = "https://github.com/someone/other.git\n"
    monkeypatch.setattr(update, "_run", lambda *a, **kw: ok)
    msg = update.self_update("/tmp")
    assert "ไม่ใช่" in msg or "repo" in msg.lower()


def test_self_update_success_path(monkeypatch):
    monkeypatch.setattr(update, "_git_bin", lambda: "/usr/bin/git")
    calls = {"n": 0}

    def fake_run(args, cwd=None, timeout=30):
        calls["n"] += 1
        if args[0] == "remote":
            r = mock.MagicMock()
            r.stdout = "https://github.com/Zedxv55/Yousini.git\n"
            return r
        return mock.MagicMock(returncode=0)
    monkeypatch.setattr(update, "_run", fake_run)
    msg = update.self_update("/tmp")
    assert "อัปเดตเสร็จ" in msg
    assert calls["n"] >= 3  # remote, fetch, reset


def test_self_update_fetch_fails(monkeypatch):
    monkeypatch.setattr(update, "_git_bin", lambda: "/usr/bin/git")

    def fake_run(args, cwd=None, timeout=30):
        if args[0] == "remote":
            r = mock.MagicMock()
            r.stdout = "https://github.com/Zedxv55/Yousini.git\n"
            return r
        r = mock.MagicMock()
        r.returncode = 1
        r.stderr = "timeout"
        return r
    monkeypatch.setattr(update, "_run", fake_run)
    msg = update.self_update("/tmp")
    assert "fetch" in msg.lower() or "ล้มเหลว" in msg


def test_update_main_unknown_sub(monkeypatch):
    monkeypatch.setattr(update, "check", lambda cur: {"current": "3.10.0"})
    assert "ใช้:" in update.update_main(["foo"], "3.10.0")


def test_update_main_check(monkeypatch):
    monkeypatch.setattr(update, "check",
                        lambda cur: {"current": "3.10.0", "latest": "3.11.0",
                                     "newer": True, "error": ""})
    line = update.update_main(["check"], "3.10.0")
    assert "3.11.0" in line and "⚠" in line


def test_update_main_up_to_date(monkeypatch):
    monkeypatch.setattr(update, "check",
                        lambda cur: {"current": "3.10.0", "latest": "3.10.0",
                                     "newer": False, "error": ""})
    assert "ล่าสุดแล้ว" in update.update_main(["update"], "3.10.0")


def test_update_main_do_update(monkeypatch):
    monkeypatch.setattr(update, "check",
                        lambda cur: {"current": "3.10.0", "latest": "3.11.0",
                                     "newer": True, "error": ""})
    monkeypatch.setattr(update, "self_update", lambda cwd="": "done")
    assert update.update_main(["go"], "3.10.0") == "done"


def test_fetch_raw_pyproject_fail_silent(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen",
                        mock.MagicMock(side_effect=OSError("no net")))
    assert update._fetch_raw_pyproject() == ""


def test_git_bin_env_override(monkeypatch):
    monkeypatch.setenv("YOUSINI_GIT", "/opt/git/bin/git")
    assert update._git_bin() == "/opt/git/bin/git"
