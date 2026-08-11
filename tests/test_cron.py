"""ทดสอบ Cron Jobs — งานอัตโนมัติตามเวลา (Phase 4 เทียบเท่า Hermes cronjob)"""
import os, sys
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yousini_cron import (parse_schedule, cron_matches, JobStore, run_due_jobs)


def test_parse_schedule():
    k, v = parse_schedule("30m")
    assert k == "interval" and v == 1800
    k, v = parse_schedule("every 2h")
    assert k == "interval" and v == 7200
    k, v = parse_schedule("45s")
    assert k == "interval" and v == 45
    k, v = parse_schedule("0 9 * * *")
    assert k == "daily_cron"
    k, v = parse_schedule("2026-08-11T10:00:00")
    assert k == "oneshot"
    assert parse_schedule("")[0] == "invalid"
    assert parse_schedule("banana")[0] == "invalid"


def test_cron_matches():
    fields = parse_schedule("0 9 * * *")[1]  # รัน 09:00 ทุกวัน
    m9 = datetime(2026, 8, 11, 9, 0, 0)
    m10 = datetime(2026, 8, 11, 10, 0, 0)
    assert cron_matches(fields, m9)
    assert not cron_matches(fields, m10)


def test_jobstore_crud(tmp_path):
    store = JobStore(tmp_path / "cron.json")
    j = store.add("สรุปประจำวัน", "30m", "สรุปงานวันนี้", cwd="/tmp")
    assert j["id"] == 1 and j["enabled"] is True
    assert len(store.list()) == 1
    store.set_enabled(1, False)
    assert store.list()[0]["enabled"] is False
    store.remove(1)
    assert store.list() == []
    # id ถัดไปเริ่มนับใหม่ (max ของที่เหลือ = 0 → 1)
    j2 = store.add("x", "30m", "y")
    assert j2["id"] == 1


def test_due_interval_and_mark_run(tmp_path):
    store = JobStore(tmp_path / "cron.json")
    store.add("tick", "30m", "ทำอะไรสักอย่าง")
    base = datetime(2026, 8, 11, 8, 0, 0)
    # interval job ยังไม่เคยรัน → due ทันที (รันครั้งแรกทันที)
    assert len(store.due(base)) == 1
    store.mark_run(1, base)
    assert store.due(base) == []          # เพิ่งรัน → ยังไม่ครบ 30 นาที
    assert len(store.due(base + timedelta(minutes=31))) == 1


def test_due_oneshot_fires_once(tmp_path):
    store = JobStore(tmp_path / "cron.json")
    store.add("one", "2030-01-01T00:00:00", "ครั้งเดียว")
    now = datetime(2030, 1, 1, 0, 0, 30)
    assert len(store.due(now)) == 1
    store.mark_run(1, now)
    assert store.due(now + timedelta(days=1)) == []  # ไม่รันซ้ำ


def test_run_due_jobs_with_fake_runner(tmp_path):
    store = JobStore(tmp_path / "cron.json")
    store.add("jobA", "30m", "prompt A")
    calls = []

    def run_fn(job):
        calls.append(job["name"])
        return f"ผลลัพธ์ของ {job['name']}"

    base = datetime(2026, 8, 11, 8, 0, 0)
    results = run_due_jobs(store, run_fn, now=base)
    assert calls == ["jobA"]
    assert results[0]["output"] == "ผลลัพธ์ของ jobA"
    assert results[0]["error"] is None
    # หลังรัน → mark_run แล้ว ไม่ due ซ้ำ
    assert store.due(base + timedelta(minutes=29)) == []


def test_run_due_jobs_error_handled(tmp_path):
    store = JobStore(tmp_path / "cron.json")
    store.add("bad", "30m", "x")

    def boom(job):
        raise RuntimeError("crash")

    results = run_due_jobs(store, boom, now=datetime(2026, 8, 11, 8, 0, 0))
    assert results[0]["error"] == "crash"