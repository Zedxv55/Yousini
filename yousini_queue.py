#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yousini Agent Queue — ส่งงานระหว่าง agent (agent-to-agent collaboration)

- คิวแบบ persistent (profile_root()/queue.json) — ใช้ร่วมกันได้หลายโปรเซส
- ล็อกไฟล์ข้ามโปรเซส (msvcrt บน Windows / fcntl บน POSIX) กัน worker แย่งงานกัน
- งาน: {id, from, worker, prompt, priority, status, created_at, started_at, done_at,
        result, error}
  status: pending → running → done | failed
- worker: claim งาน pending ที่ priority สูงสุด (แล้ว created_at เก่าสุด)
"""
import json
import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

_LOCK = threading.RLock()


def profile_root() -> Path:
    base = Path.home() / ".yousini"
    p = os.getenv("YOUSINI_PROFILE", "").strip()
    active = p
    if not active:
        try:
            f = base / ".active_profile"
            if f.is_file():
                active = f.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    if active and active not in ("", "default"):
        return base / "profiles" / active
    return base


QUEUE_FILE = Path(os.getenv("YOUSINI_QUEUE_FILE", str(profile_root() / "queue.json")))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _fmt(ts: str) -> str:
    if not ts:
        return "—"
    return ts.replace("T", " ")[:16]


# ---------------------------------------------------------------------------
# file lock (ข้ามโปรเซส)
# ---------------------------------------------------------------------------
class _FileLock:
    def __init__(self, path: Path, timeout: float = 10.0):
        self.path = path
        self.timeout = timeout
        self._fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(str(self.path) + ".lock", "a+b")
        import sys
        if sys.platform == "win32":
            import msvcrt
            deadline = time.time() + self.timeout
            while True:
                try:
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.time() > deadline:
                        raise
                    time.sleep(0.05)
        else:
            import fcntl
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        try:
            import sys
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            self._fh.close()
        except Exception:
            pass
        return False


# ---------------------------------------------------------------------------
# load / save
# ---------------------------------------------------------------------------
def _load() -> list:
    try:
        data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(tasks: list) -> None:
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text(json.dumps(tasks, ensure_ascii=False, indent=1),
                          encoding="utf-8")


def _next_id(existing: list) -> str:
    return "task-" + uuid.uuid4().hex[:10]


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def enqueue(prompt: str, worker: str = "default", from_: str = "local",
            priority: int = 0, meta: dict = None) -> dict:
    """เพิ่มงานเข้าคิว — คืนงานที่สร้าง"""
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("ต้องระบุ prompt")
    with _LOCK, _FileLock(QUEUE_FILE):
        tasks = _load()
        task = {"id": _next_id(tasks), "from": from_, "worker": worker or "default",
                "prompt": prompt, "priority": int(priority or 0), "status": "pending",
                "created_at": _now(), "started_at": "", "done_at": "",
                "result": "", "error": "", "meta": meta or {}}
        tasks.append(task)
        _save(tasks)
    return task


def get(task_id: str) -> dict:
    for t in _load():
        if t.get("id") == task_id:
            return dict(t)
    return None


def claim(worker: str = "default") -> dict:
    """worker รับงานถัดไป (priority สูงสุด → created_at เก่าสุด) → คืนงาน status=running"""
    worker = worker or "default"
    with _LOCK, _FileLock(QUEUE_FILE):
        reclaim_stale_locked()
        tasks = _load()
        pool = [t for t in tasks if t.get("status") == "pending"]
        if not pool:
            return None
        pool.sort(key=lambda t: (-int(t.get("priority", 0)), t.get("created_at", "")))
        t = pool[0]
        t["status"] = "running"
        t["started_at"] = _now()
        t["worker"] = worker
        _save(tasks)
    return dict(t)


STALE_SECONDS = int(os.getenv("YOUSINI_QUEUE_STALE", "300"))


def _stale(task: dict, now: float) -> bool:
    if task.get("status") != "running" or not task.get("started_at"):
        return False
    try:
        from datetime import datetime as _dt
        return now - _dt.fromisoformat(task["started_at"]).timestamp() > STALE_SECONDS
    except Exception:
        return False


def reclaim_stale_locked() -> int:
    """งาน running ที่ค้างเกิน STALE_SECONDS (worker ตาย/ค้าง) → ย้อนกลับ pending
    เรียกภายใน lock แล้ว — คืนจำนวนที่รีเซ็ต"""
    now = time.time()
    tasks = _load()
    n = 0
    for t in tasks:
        if _stale(t, now):
            t["status"] = "pending"
            t["started_at"] = ""
            n += 1
    if n:
        _save(tasks)
    return n


def reclaim_stale() -> int:
    with _LOCK, _FileLock(QUEUE_FILE):
        return reclaim_stale_locked()


def complete(task_id: str, result: str = "") -> dict:
    with _LOCK, _FileLock(QUEUE_FILE):
        tasks = _load()
        for t in tasks:
            if t.get("id") == task_id:
                t["status"] = "done"
                t["result"] = str(result or "")
                t["done_at"] = _now()
                _save(tasks)
                return dict(t)
    return None


def fail(task_id: str, error: str) -> dict:
    with _LOCK, _FileLock(QUEUE_FILE):
        tasks = _load()
        for t in tasks:
            if t.get("id") == task_id:
                t["status"] = "failed"
                t["error"] = str(error or "")
                t["done_at"] = _now()
                _save(tasks)
                return dict(t)
    return None


def requeue(task_id: str) -> dict:
    with _LOCK, _FileLock(QUEUE_FILE):
        tasks = _load()
        for t in tasks:
            if t.get("id") == task_id:
                t["status"] = "pending"
                t["started_at"] = ""
                t["done_at"] = ""
                t["error"] = ""
                _save(tasks)
                return dict(t)
    return None


def list_tasks(worker: str = None, status: str = None, limit: int = 50) -> list:
    tasks = _load()
    if worker:
        tasks = [t for t in tasks if t.get("worker") == worker]
    if status:
        tasks = [t for t in tasks if t.get("status") == status]
    tasks.sort(key=lambda t: (t.get("status"), -int(t.get("priority", 0)),
                              t.get("created_at", "")))
    return [dict(t) for t in tasks[:limit]]


def counts() -> dict:
    c = {"pending": 0, "running": 0, "done": 0, "failed": 0}
    for t in _load():
        s = t.get("status", "pending")
        if s in c:
            c[s] += 1
    return c


def prune_done(keep: int = 20) -> int:
    """ลบงาน done/failed ที่เกิน keep ตัวล่าสุด — คืนจำนวนที่ลบ"""
    with _LOCK, _FileLock(QUEUE_FILE):
        tasks = _load()
        done = [t for t in tasks if t.get("status") in ("done", "failed")]
        done.sort(key=lambda t: t.get("done_at", ""), reverse=True)
        drop = {t["id"] for t in done[keep:]}
        new = [t for t in tasks if t.get("id") not in drop]
        if len(new) != len(tasks):
            _save(new)
        return len(tasks) - len(new)


def clear() -> int:
    with _LOCK, _FileLock(QUEUE_FILE):
        tasks = _load()
        n = len(tasks)
        if n:
            _save([])
        return n


# ---------------------------------------------------------------------------
# worker / run_task
# ---------------------------------------------------------------------------
def run_task(task: dict, runner=None) -> dict:
    """รันงานด้วย runner(prompt)->str (default ใช้ Agent จริง). กันพัง→mark failed"""
    try:
        result = (runner or _default_runner)(task.get("prompt", ""))
        return complete(task["id"], result=result)
    except Exception as e:
        return fail(task["id"], error=str(e))


def _default_runner(prompt: str) -> str:
    """รัน prompt ด้วย Agent ตัวใหม่ — คืนข้อความ assistant ล่าสุด"""
    from yousini import Agent, chat_turn
    agent = Agent(interactive=False, cwd=os.getcwd())
    chat_turn(agent, prompt)
    for m in reversed(agent.messages):
        if m.get("role") == "assistant" and m.get("content"):
            return str(m["content"])
    return "(ไม่มีคำตอบจาก agent)"


def process_once(runner=None, worker: str = "default", max_tasks: int = 10) -> list:
    """worker รอบเดียว: claim+รัน+complete ไปเรื่อยจนคิวว่าง (หรือครบ max_tasks)"""
    out = []
    for _ in range(max_tasks):
        task = claim(worker)
        if not task:
            break
        done = run_task(task, runner=runner)
        out.append(done)
    return out


# ---------------------------------------------------------------------------
# format
# ---------------------------------------------------------------------------
def format_task(t: dict) -> str:
    if not t:
        return "(ไม่พบงาน)"
    return (f"#{t.get('id')}  [{t.get('status')}]  worker={t.get('worker')}  "
            f"สร้าง {_fmt(t.get('created_at'))}"
            + (f"\n  รับ {_fmt(t.get('started_at'))}  เสร็จ {_fmt(t.get('done_at'))}" if t.get("status") != "pending" else "")
            + f"\n  จาก {t.get('from')}  p{t.get('priority')}"
            + f"\n  โจทย์: {str(t.get('prompt'))[:120]}"
            + (f"\n  ผล: {str(t.get('result'))[:300]}" if t.get("result") else "")
            + (f"\n  error: {str(t.get('error'))[:200]}" if t.get("error") else ""))


def format_queue(tasks: list, title: str = "Queue") -> str:
    if not tasks:
        return f"{title}: ว่าง"
    return f"{title}: {len(tasks)} งาน\n" + "\n".join(
        f"  #{t.get('id')}  [{t.get('status')}]  w={t.get('worker')}  p{t.get('priority')}  "
        f"{_fmt(t.get('created_at'))}  {str(t.get('prompt'))[:60]}" for t in tasks)


if __name__ == "__main__":
    print(format_queue(list_tasks(), title="Queue"))
    print("counts:", counts())