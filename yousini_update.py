#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Self-update (v3.8) — ตรวจเวอร์ชันล่าสุดจาก GitHub แล้วอัปเดตตัวเอง

- `check(current)` — เทียบเวอร์ชันปัจจุบันกับ latest tag บน GitHub (Zedxv55/Yousini)
- `self_update()` — ถ้ารันจาก git repo ที่มี remote origin ตรง → fetch + reset --hard origin/main
- CLI: yousini update [check] | /update ใน REPL
"""
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

REPO = "Zedxv55/Yousini"
_REMOTE_RE = re.compile(r"github\.com[/:]([^/\s]+)/([^/\s]+?)(?:\.git)?$")


def _git_bin():
    env = os.getenv("YOUSINI_GIT", "").strip()
    if env:
        return env
    import shutil
    g = shutil.which("git")
    if g:
        return g
    for cand in (
        Path.home() / "Tools" / "git" / "cmd" / "git.exe",
        Path.home() / "tools" / "git" / "cmd" / "git.exe",
        Path.home() / "Apps" / "git" / "cmd" / "git.exe",
        Path.home() / "apps" / "git" / "cmd" / "git.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Git" / "cmd" / "git.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Git" / "cmd" / "git.exe",
    ):
        if cand.is_file():
            return str(cand)
    return None


def _run(args, cwd=None, timeout=30):
    g = _git_bin()
    if not g:
        return None
    try:
        r = subprocess.run([g, *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r
    except Exception:
        return None


def _parse_tags(ls_remote: str) -> list:
    """แยก semver จาก `git ls-remote --tags` output — คืน sorted (desc)"""
    vers = []
    for line in (ls_remote or "").splitlines():
        ref = line.split("refs/tags/")[-1].strip()
        if not ref or ref.endswith("^{}"):
            continue
        v = ref.lstrip("v")
        if re.match(r"^\d+\.\d+\.\d+", v):
            vers.append(v)
    def key(v):
        return tuple(int(x) for x in re.split(r"[.\-+]", v)[:3])
    return sorted(set(vers), key=key, reverse=True)


def _fetch_raw_pyproject() -> str:
    """อ่าน pyproject.toml จาก default branch ของ repo (แม่นที่สุดสำหรับ repo dev ที่ไม่มี tag)"""
    try:
        with urllib.request.urlopen(
                f"https://raw.githubusercontent.com/{REPO}/main/pyproject.toml",
                timeout=15) as resp:
            return resp.read().decode("utf-8")
    except Exception:
        return ""


def latest_version() -> str:
    """เวอร์ชันล่าสุดจาก GitHub — เอา pyproject.toml (main) ก่อน ถ้าไม่ได้ใช้ git tags"""
    for src in ("pyproject", "tags"):
        if src == "pyproject":
            txt = _fetch_raw_pyproject()
            m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', txt, re.M)
            if m and re.match(r"^\d+\.\d+\.\d+", m.group(1)):
                return m.group(1)
        else:
            r = _run(["ls-remote", "--tags", f"https://github.com/{REPO}.git"], timeout=30)
            if r is not None and r.returncode == 0:
                tags = _parse_tags(r.stdout)
                if tags:
                    return tags[0]
    try:
        with urllib.request.urlopen(
                f"https://api.github.com/repos/{REPO}/tags", timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for t in data or []:
            v = str(t.get("name", "")).lstrip("v")
            if re.match(r"^\d+\.\d+\.\d+", v):
                return v
    except Exception:
        pass
    return ""


def _split(v: str):
    return tuple(int(x) for x in re.split(r"[.\-+]", v)[:3])


def check(current: str) -> dict:
    """คืน {current, latest, newer, error} — newer=True ถ้ามีเวอร์ชันใหม่กว่า"""
    latest = latest_version()
    if not latest:
        return {"current": current, "latest": "", "newer": False,
                "error": "ตรวจสอบเวอร์ชันล่าสุดไม่ได้ (ไม่มีการเชื่อมต่อ หรือ repo ไม่เปิดอ่าน)"}
    try:
        newer = _split(latest) > _split(current)
    except Exception:
        newer = latest != current
    return {"current": current, "latest": latest, "newer": newer, "error": ""}


def self_update(cwd: str = "") -> str:
    """git fetch + reset --hard origin/main ถ้า cwd เป็น repo ที่ remote ตรงกับ Yousini"""
    base = Path(cwd or os.getcwd())
    r = _run(["remote", "get-url", "origin"], cwd=str(base), timeout=20)
    if r is None:
        return "ไม่พบ git ทำงานบนเครื่อง (YOUSINI_GIT ยังไม่ได้ตั้ง)"
    url = (r.stdout or "").strip()
    m = _REMOTE_RE.search(url)
    if not m or f"{m.group(1)}/{m.group(2)}".lower() != REPO.lower():
        return f"remote origin ({url or '(ไม่มี)'}) ไม่ใช่ repo Yousini — ข้าม auto-update"
    r = _run(["fetch", "origin"], cwd=str(base), timeout=120)
    if r is None or r.returncode != 0:
        return f"git fetch ล้มเหลว: {(r.stderr if r else '')[:200]}"
    r = _run(["reset", "--hard", "origin/main"], cwd=str(base), timeout=60)
    if r is None or r.returncode != 0:
        return f"git reset ล้มเหลว: {(r.stderr if r else '')[:200]}"
    return "อัปเดตเสร็จ: working tree ตรงกับ origin/main แล้ว — รีสตาร์ทเพื่อใช้เวอร์ชันใหม่"


def update_main(argv, current: str) -> str:
    """CLI/REPL: update [check] | update"""
    sub = argv[0].lower() if argv else "go"
    if sub in ("check", "c"):
        r = check(current)
        line = f"เวอร์ชันปัจจุบัน: {r['current']}"
        if r["latest"]:
            line += f" | ล่าสุด: {r['latest']}"
            line += " | ⚠️ มีเวอร์ชันใหม่!" if r["newer"] else " | อัปเดตล่าสุดแล้ว"
        else:
            line += f" | {r['error']}"
        return line
    if sub in ("go", "update"):
        r = check(current)
        if r["error"]:
            return r["error"]
        if not r["newer"]:
            return f"เวอร์ชันปัจจุบัน ({current}) เป็นล่าสุดแล้ว"
        return self_update()
    return "ใช้: update [check]  |  update (อัปเดต)"
