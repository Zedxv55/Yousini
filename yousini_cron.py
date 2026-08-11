#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cron Jobs — งานอัตโนมัติตามเวลา (เทียบเท่า Hermes cronjob)

ไฟล์เก็บงาน: ~/.yousini/cron.json (หรือ YOUSINI_CRON_FILE)
schedule รองรับ 3 แบบ:
  - "30m" / "every 2h" / "45s"   → วนทุกช่วงเวลา (s/m/h/d)
  - "0 9 * * *"                  → cron 5 ฟิลด์ (นาที ชั่วโมง วัน เดือน วันในสัปดาห์)
  - "2026-08-11T10:00:00"        → รันครั้งเดียวตอนนั้น
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path

def _profile_root():
    """ราก data dir ตามโพรไฟล์ (ตรงกับ yousini.py::_profile_root)"""
    base = Path.home() / ".yousini"
    p = os.getenv("YOUSINI_PROFILE", "").strip()
    if not p:
        try:
            f = base / ".active_profile"
            if f.is_file():
                p = f.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    if p and p not in ("", "default"):
        return base / "profiles" / p
    return base


CRON_FILE = Path(os.getenv("YOUSINI_CRON_FILE", str(_profile_root() / "cron.json")))


def _parse_interval(s):
    """'30m'/'every 2h'/'45s' → วินาที หรือ None ถ้าไม่ใช่"""
    s = (s or "").strip().lower().replace("every ", "")
    m = re.fullmatch(r"(\d+)(s|m|h|d)?", s)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2) or "m"
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def _parse_cron_fields(s):
    """'0 9 * * *' → (minute, hour, dom, month, dow) โดย * = None"""
    parts = (s or "").split()
    if len(parts) != 5:
        return None
    try:
        return tuple(None if x == "*" else int(x) for x in parts)
    except ValueError:
        return None


def parse_schedule(s):
    """คืน (kind, payload): interval->วินาที, daily_cron->5 fields, oneshot->datetime, invalid->None"""
    s = (s or "").strip()
    if not s:
        return ("invalid", None)
    secs = _parse_interval(s)
    if secs:
        return ("interval", secs)
    if s.startswith("iso:"):
        try:
            return ("oneshot", datetime.fromisoformat(s[4:]))
        except ValueError:
            return ("invalid", None)
    try:
        return ("oneshot", datetime.fromisoformat(s))
    except ValueError:
        pass
    fields = _parse_cron_fields(s)
    if fields:
        return ("daily_cron", fields)
    return ("invalid", None)


def cron_matches(fields, now):
    """เช็คว่าเวลาปัจจุบันตรงกับ cron 5 ฟิลด์หรือไม่"""
    minute, hour, dom, month, dow = fields
    if month is not None and now.month != month:
        return False
    if dom is not None and now.day != dom:
        return False
    if dow is not None and now.weekday() != dow:
        return False
    if hour is not None and now.hour != hour:
        return False
    if minute is not None and now.minute != minute:
        return False
    return True


class JobStore:
    """เก็บงาน cron ในไฟล์ JSON (CRUD + ค้นงานที่ถึงเวลา)"""

    def __init__(self, path=CRON_FILE):
        self.path = Path(path)

    def _load(self):
        if not self.path.is_file():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save(self, jobs):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(jobs, ensure_ascii=False, indent=1),
                             encoding="utf-8")

    def add(self, name, schedule, prompt, cwd=None, enabled=True):
        jobs = self._load()
        job = {"id": max([j["id"] for j in jobs], default=0) + 1,
               "name": name, "schedule": schedule, "prompt": prompt,
               "cwd": cwd, "enabled": enabled, "last_run": None,
               "created": datetime.now().isoformat()}
        jobs.append(job)
        self._save(jobs)
        return job

    def get(self, job_id):
        for j in self._load():
            if j["id"] == job_id:
                return j
        return None

    def remove(self, job_id):
        jobs = [j for j in self._load() if j["id"] != job_id]
        self._save(jobs)

    def set_enabled(self, job_id, enabled):
        jobs = self._load()
        for j in jobs:
            if j["id"] == job_id:
                j["enabled"] = bool(enabled)
        self._save(jobs)
        return self.get(job_id)

    def list(self):
        return self._load()

    def mark_run(self, job_id, now=None):
        jobs = self._load()
        for j in jobs:
            if j["id"] == job_id:
                j["last_run"] = (now or datetime.now()).isoformat()
        self._save(jobs)

    def due(self, now=None):
        """งานที่ถึงเวลา (ตาม schedule + last_run)"""
        now = now or datetime.now()
        out = []
        for j in self._load():
            if not j.get("enabled", True):
                continue
            kind, payload = parse_schedule(j.get("schedule", ""))
            last = None
            if j.get("last_run"):
                try:
                    last = datetime.fromisoformat(j["last_run"])
                except Exception:
                    last = None
            if kind == "interval":
                if last is None or (now - last).total_seconds() >= payload:
                    out.append(j)
            elif kind == "daily_cron":
                if cron_matches(payload, now) and (last is None or last.date() < now.date()):
                    out.append(j)
            elif kind == "oneshot":
                if now >= payload and last is None:
                    out.append(j)
        return out


def run_due_jobs(store, run_fn, now=None):
    """รันงานที่ถึงเวลาทั้งหมด — run_fn(job) → str ผลลัพธ์ (หรือ raise)
    คืน [{job, output|error}] และ mark_run ให้อัตโนมัติ"""
    results = []
    for job in store.due(now):
        try:
            out = run_fn(job)
        except Exception as e:
            results.append({"job": job.get("name", f"#{job['id']}"),
                            "output": None, "error": str(e)})
            continue
        store.mark_run(job["id"], now)
        results.append({"job": job.get("name", f"#{job['id']}"),
                        "output": out, "error": None})
    return results