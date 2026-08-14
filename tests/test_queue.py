"""ทดสอบ Agent collaboration queue (yousini_queue) — env แยก per-test กันชนไฟล์จริง"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import yousini_queue as Q


@pytest.fixture()
def qf(tmp_path, monkeypatch):
    """ชี้ YOUSINI_QUEUE_FILE ไป tmp + โหลดโมดูลใหม่ด้วย env นั้น"""
    f = str(tmp_path / "queue.json")
    monkeypatch.setenv("YOUSINI_QUEUE_FILE", f)
    monkeypatch.setenv("YOUSINI_QUEUE_STALE", "1")
    import importlib
    importlib.reload(Q)
    yield f
    importlib.reload(Q)


def test_enqueue_get(qf):
    t = Q.enqueue("ทำความสะอาด repo", worker="dev-1", from_="cli")
    assert t["status"] == "pending" and t["worker"] == "dev-1"
    assert Q.get(t["id"])["id"] == t["id"]
    assert Q.get("task-nope") is None


def test_claim_priority_then_oldest(qf):
    t1 = Q.enqueue("ก้อนแรก", worker="w", from_="t")
    t2 = Q.enqueue("งานสำคัญ", worker="w", from_="t", priority=5)
    t3 = Q.enqueue("ก้อนที่สาม", worker="w", from_="t")
    c1 = Q.claim("w")
    assert c1["id"] == t2["id"]                      # priority สูงสุดก่อน
    assert c1["status"] == "running" and c1["worker"] == "w"
    c2 = Q.claim("w")
    assert c2["id"] == t1["id"]                      # แล้ว oldest
    c3 = Q.claim("w")
    assert c3["id"] == t3["id"]
    assert Q.claim("w") is None                      # คิวว่าง


def test_complete_fail_requeue(qf):
    t = Q.enqueue("วิเคราะห์บั๊ก", worker="dev-2", from_="api")
    Q.claim("dev-2")
    Q.complete(t["id"], result="เจอแล้ว: นิยามซ้ำ")
    got = Q.get(t["id"])
    assert got["status"] == "done" and "นิยามซ้ำ" in got["result"]
    Q.fail(t["id"], error="timeout")
    assert Q.get(t["id"])["status"] == "failed"
    Q.requeue(t["id"])
    assert Q.get(t["id"])["status"] == "pending"


def test_counts(qf):
    a = Q.enqueue("a", worker="w", from_="t")
    b = Q.enqueue("b", worker="w", from_="t")
    Q.claim("w")
    Q.complete(a["id"], result="ok")
    Q.fail(b["id"], error="e")
    c = Q.counts()
    assert c == {"pending": 0, "running": 0, "done": 1, "failed": 1}


def test_list_filters(qf):
    Q.enqueue("a", worker="dev-1", from_="t")
    Q.enqueue("b", worker="dev-2", from_="t")
    assert all(t["worker"] == "dev-1" for t in Q.list_tasks(worker="dev-1"))
    assert all(t["status"] == "pending" for t in Q.list_tasks(status="pending"))


def test_run_task_runner_done_and_fail(qf):
    t = Q.enqueue("งานทดสอบ runner", worker="w", from_="t")
    d = Q.run_task(t, runner=lambda p: f"fake result: {p}")
    assert d["status"] == "done" and "fake result" in d["result"]

    def boom(p):
        raise RuntimeError("boom")

    t2 = Q.enqueue("งานที่จะพัง", worker="w", from_="t")
    d2 = Q.run_task(t2, runner=boom)
    assert d2["status"] == "failed" and "boom" in d2["error"]


def test_process_once(qf):
    for i in range(3):
        Q.enqueue(f"batch-{i}", worker="w", from_="t")
    done = Q.process_once(runner=lambda p: "ok", worker="w")
    assert len(done) == 3 and all(t["status"] == "done" for t in done)
    assert Q.counts()["pending"] == 0


def test_prune_and_clear(qf):
    for i in range(5):
        Q.enqueue(f"x{i}", worker="w", from_="t")
    ts = Q.list_tasks()
    Q.claim("w")
    Q.complete(ts[0]["id"], result="r")
    Q.claim("w")
    Q.complete(ts[1]["id"], result="r")
    n = Q.prune_done(keep=1)
    assert n == 1                                # เก็บ done 1 → ลบที่เกิน 1
    Q.clear()
    assert Q.counts() == {"pending": 0, "running": 0, "done": 0, "failed": 0}


def test_persistence(qf):
    Q.enqueue("persist-check", worker="w", from_="t")
    assert Path(qf).is_file()


def test_reclaim_stale(qf):
    from datetime import datetime, timedelta
    Q._save([{"id": "task-stuck", "status": "running",
              "started_at": (datetime.now() - timedelta(seconds=5)).isoformat(timespec="seconds"),
              "worker": "w", "prompt": "x", "priority": 0,
              "created_at": "2026-08-14T10:00:00", "done_at": "", "result": "",
              "error": "", "from": "t", "meta": {}}])
    n = Q.reclaim_stale()
    assert n == 1 and Q.get("task-stuck")["status"] == "pending"


def test_format_task(qf):
    t = Q.enqueue("โจทย์", worker="w", from_="t")
    s = Q.format_task(t)
    assert "โจทย์" in s and "pending" in s


def test_clear_unclaimed(qf):
    Q.enqueue("a", worker="w", from_="t")
    assert Q.counts()["pending"] == 1