"""ทดสอบ usage report (v3.8) — yousini_usage.report()"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import yousini_usage as U


@pytest.fixture
def ufile(tmp_path, monkeypatch):
    monkeypatch.setattr(U, "_usage_file", lambda: tmp_path / "usage.json")
    monkeypatch.setattr(U, "_profile_root", lambda: tmp_path)
    U._ENABLED = None
    yield tmp_path
    U._ENABLED = None


def test_report_disabled(ufile):
    r = U.report("weekly")
    assert "ปิดใช้งาน" in r


def test_report_weekly(ufile):
    U.set_enabled(True)
    U.record_tokens(100, 50)
    U.record_tool("shell")
    U.record_turn()
    r = U.report("weekly")
    assert "รายงานรายสัปดาห์" in r
    assert "150" in r and "turns" in r
    assert "shell" in r
    assert (ufile / "reports").is_dir()
    assert list((ufile / "reports").glob("usage-weekly-*.md"))


def test_report_daily(ufile):
    U.set_enabled(True)
    U.record_tokens(10, 5)
    r = U.report("daily")
    assert "รายงานรายวัน" in r


def test_report_monthly(ufile):
    U.set_enabled(True)
    U.record_tokens(10, 5)
    r = U.report("monthly")
    assert "รายงานรายเดือน" in r


def test_report_bad_period(ufile):
    U.set_enabled(True)
    assert "period" in U.report("hourly")