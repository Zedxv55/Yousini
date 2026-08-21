#!/usr/bin/env python3
"""Stress test แบบควบคุมสำหรับ Yousini queue จำนวน 100 งาน

ทดสอบ lifecycle ที่ CLI ใช้งานจริง: enqueue -> claim -> run -> complete โดยใช้
runner แบบ deterministic เพื่อวัดความเสถียรของ orchestration โดยไม่ปะปนกับความ
พร้อมของผู้ให้บริการ AI, เครือข่าย หรือ API key.

ตัวอย่าง:
    YOUSINI_API_KEY=test-key python3 scripts/stress_queue_100.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yousini
import yousini_queue as queue

TOTAL_TASKS = 100


def deterministic_runner(prompt: str) -> str:
    """Runner ที่สำเร็จแบบกำหนดผลได้ เพื่อ isolate ความเสถียรของ CLI queue."""
    return f"completed: {prompt}"


def main() -> int:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="yousini-stress-") as temp_dir:
        queue_file = Path(temp_dir) / "queue.json"
        previous_queue_file = queue.QUEUE_FILE
        previous_runner = queue._default_runner
        try:
            queue.QUEUE_FILE = queue_file
            queue._default_runner = deterministic_runner

            # เรียก command handler เดียวกับ `yousini agent send` จำนวน 100 ครั้ง.
            for index in range(1, TOTAL_TASKS + 1):
                yousini.agent_main([
                    "send", "stress", f"controlled task {index:03d}",
                ])

            # เรียก worker entry point เดียวกับ `yousini work --once`.
            yousini.work_main(once=True, worker="stress", max_tasks=TOTAL_TASKS)

            tasks = queue.list_tasks(worker="stress", limit=TOTAL_TASKS)
            counts = queue.counts()
            succeeded = [task for task in tasks if task.get("status") == "done"]
            valid_results = [
                task for task in succeeded
                if task.get("result") == f"completed: {task.get('prompt')}"
            ]
            elapsed_seconds = time.perf_counter() - started
            report = {
                "test": "controlled_queue_worker_100",
                "total": TOTAL_TASKS,
                "succeeded": len(succeeded),
                "failed": counts["failed"],
                "pending": counts["pending"],
                "running": counts["running"],
                "result_integrity": len(valid_results),
                "elapsed_seconds": round(elapsed_seconds, 3),
                "tasks_per_second": round(TOTAL_TASKS / elapsed_seconds, 2),
                "success_rate_percent": round(len(succeeded) / TOTAL_TASKS * 100, 2),
                "passed": (
                    len(succeeded) == TOTAL_TASKS
                    and len(valid_results) == TOTAL_TASKS
                    and counts["failed"] == 0
                    and counts["pending"] == 0
                    and counts["running"] == 0
                ),
            }
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["passed"] else 1
        finally:
            queue.QUEUE_FILE = previous_queue_file
            queue._default_runner = previous_runner


if __name__ == "__main__":
    raise SystemExit(main())
