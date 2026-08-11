#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Git awareness — ใช้ประวัติ git เป็น context ในการทำงาน (เทียบเท่า Claude Code)

- recent_log / blame / status / diff_stat — wrapper subprocess กัน repo พัง
- last_commits_block() — บล็อกข้อความสำหรับ inject เข้า system prompt
"""
import os
import shutil
import subprocess
from pathlib import Path


def _git(cwd: str, *args: str) -> str:
    """รัน git คืน stdout (ว่างถ้าล้มเหลว) — ไม่ throw"""
    if shutil.which("git") is None:
        return ""
    try:
        r = subprocess.run(["git", "-C", str(cwd), *args],
                           capture_output=True, text=True, timeout=10,
                           encoding="utf-8", errors="replace")
        return r.stdout
    except Exception:
        return ""


def is_repo(cwd: str) -> bool:
    out = _git(cwd, "rev-parse", "--is-inside-work-tree")
    return out.strip() == "true"


def recent_log(n: int = 10, cwd: str = ".") -> list:
    """git log --oneline ใหม่สุดก่อน — คืน list[str] (บรรทัด '<hash> <subject>')"""
    out = _git(cwd, "log", f"--oneline", "-n", str(n))
    return [ln for ln in out.splitlines() if ln.strip()]


def blame(file: str, line: int, cwd: str = ".") -> str:
    """git blame บรรทัดเดียว — คืน 'hash author: ข้อความ' (หรือข้อความเตือน)"""
    out = _git(cwd, "blame", "--line-porcelain", "-L", f"{int(line)},{int(line)}", file)
    author, content = "", ""
    for ln in out.splitlines():
        if ln.startswith("author "):
            author = ln[7:]
        elif ln.startswith("\t"):
            content = ln.strip()
    if not content:
        return f"ไม่พบบรรทัด {line} ของ {file} ใน git"
    return f"{author}: {content}"


def status_short(cwd: str = ".") -> str:
    """git status --short + สาขา (คืนข้อความรวม)"""
    branch = _git(cwd, "branch", "--show-current").strip()
    st = _git(cwd, "status", "--short").strip()
    head = f"สาขา: {branch}" if branch else "(ไม่อยู่ใน git repo)"
    return f"{head}\n{st}" if st else f"{head}\n(ทำงานสะอาด — ไม่มีไฟล์ค้าง)"


def diff_stat(cwd: str = ".") -> str:
    """git diff --stat (ยังไม่ commit) + staged"""
    body = ""
    for args in (["diff", "--stat"], ["diff", "--cached", "--stat"]):
        out = _git(cwd, *args).strip()
        if out:
            body += out + "\n"
    return body.rstrip()


def full_log(n: int = 6, cwd: str = ".") -> str:
    """git log ละเอียด: hash + ผู้แต่ง + วันที่ + subject"""
    out = _git(cwd, "log", "-n", str(n),
               "--pretty=format:%h %an %ad %s", "--date=short")
    return out if out.strip() else "(ยังไม่มี commit)"


def last_commits_block(n: int = 8, cwd: str = ".") -> str:
    """บล็อก '=== ประวัติ git ล่าสุด ===' สำหรับ inject เข้า system prompt"""
    if not is_repo(cwd):
        return ""
    log = recent_log(n, cwd)
    if not log:
        return ""
    body = "\n".join("  " + ln for ln in log)
    return f"=== ประวัติ git ล่าสุด (ใช้แก้บั๊ก/เข้าใจโค้ด) ===\n{body}\n"