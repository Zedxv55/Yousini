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


_GIT_BIN = None


def _git_bin() -> str:
    """หา git executable — env YOUSINI_GIT → which → candidates Windows
    (cache) — คืน '' ถ้าไม่เจอ"""
    global _GIT_BIN
    if _GIT_BIN is not None:
        return _GIT_BIN
    cand = [os.environ.get("YOUSINI_GIT", "")]
    if shutil.which("git"):
        cand.append(shutil.which("git"))
    if os.name == "nt":
        for base in (os.environ.get("LOCALAPPDATA", ""),
                     os.environ.get("PROGRAMFILES", ""),
                     os.environ.get("PROGRAMFILES(X86)", "")):
            if base:
                cand.append(os.path.join(base, "Git", "cmd", "git.exe"))
        for sub in ("Tools", "tools", "Apps", "apps"):
            cand.append(os.path.join(os.path.expanduser("~"), sub, "git", "cmd", "git.exe"))
        cand.append(os.path.join(os.path.expanduser("~"), "scoop", "shims", "git.exe"))
    for c in cand:
        if c and os.path.isfile(c):
            _GIT_BIN = c
            return c
    _GIT_BIN = ""
    return ""


def _git(cwd: str, *args: str) -> str:
    """รัน git คืน stdout (ว่างถ้าล้มเหลว) — ไม่ throw"""
    g = _git_bin()
    if not g:
        return ""
    try:
        r = subprocess.run([g, "-C", str(cwd), *args],
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


def _run(cwd: str, *args: str):
    g = _git_bin()
    if not g:
        return None
    env = dict(os.environ)
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    env.setdefault("GIT_ASKPASS", "echo")
    try:
        return subprocess.run([g, "-C", str(cwd), *args],
                              capture_output=True, text=True, timeout=60,
                              encoding="utf-8", errors="replace", env=env)
    except Exception:
        return None


def current_branch(cwd: str = ".") -> str:
    r = _run(cwd, "branch", "--show-current")
    return (r.stdout.strip() if r else "") or ""


def remote_url(cwd: str = ".") -> str:
    r = _run(cwd, "config", "--get", "remote.origin.url")
    return (r.stdout.strip() if r else "") or ""


def _slug(title: str) -> str:
    out = []
    for ch in (title or "").lower():
        if "a" <= ch <= "z" or "0" <= ch <= "9":
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")[:40] or "pr"


def _gh_available() -> bool:
    return shutil.which("gh") is not None


def _parse_origin(url: str):
    """แปลง remote origin → (owner, repo)  รองรับ https / ssh"""
    url = (url or "").strip()
    if url.startswith("git@"):
        body = url.split(":", 1)[-1]
        owner, _, repo = body.rpartition("/")
        return owner, repo.removesuffix(".git")
    if url.startswith("http"):
        parts = url.rstrip("/").split("/")
        if len(parts) >= 2:
            return parts[-2], parts[-1].removesuffix(".git")
    return "", ""


def create_pr(title: str, body: str = "", branch: str = "", base: str = "main",
              cwd: str = ".") -> str:
    """PR flow: commit งานค้าง → (สร้าง) branch → push → gh pr create (หรือลิงก์ compare)
    คืนข้อความสรุป — ไม่ throw"""
    if not is_repo(cwd):
        return "Error: ไม่ได้อยู่ใน git repo"
    origin = remote_url(cwd)
    if not origin:
        return "Error: ไม่มี remote 'origin' — ตั้ง `git remote add origin <url>` ก่อน"
    title = (title or "").strip()
    if not title:
        return "Error: ต้องระบุ title ของ PR"
    base = base or "main"

    # 1) commit งานค้าง
    r = _run(cwd, "add", "-A")
    if r is None or r.returncode != 0:
        return "Error: git add ล้มเหลว"
    r = _run(cwd, "status", "--porcelain")
    dirty = bool((r.stdout or "").strip()) if r else False
    if dirty:
        c = _run(cwd, "commit", "-m", f"[Yousini PR] {title}")
        if c is None or c.returncode != 0:
            return "Error: commit งานค้างล้มเหลว"

    # 2) เลือก/สร้าง branch (ห้าม PR ลงสาขาเดียวกับ base)
    cur = current_branch(cwd)
    if branch and branch != cur:
        chk = _run(cwd, "rev-parse", "--verify", "--quiet", branch)
        if chk is not None and chk.returncode == 0:
            _run(cwd, "checkout", branch)
        else:
            _run(cwd, "checkout", "-b", branch)
        cur = branch
    elif cur == base:
        branch = "yousini/" + _slug(title)
        _run(cwd, "checkout", "-b", branch)
        cur = branch
    else:
        branch = cur
    if not branch:
        return "Error: ตรวจไม่พบสาขา"

    # 3) push
    p = _run(cwd, "push", "-u", "origin", branch)
    if p is None or p.returncode != 0:
        return (f"Error: push {branch} → origin ล้มเหลว (ตรวจสิทธิ์ / network):\n"
                + ((p.stderr or "") if p else ""))

    # 4) PR — ใช้ gh ถ้ามี ไม่งั้นคืนลิงก์ compare
    owner, repo = _parse_origin(origin)
    _compare_url = (f"https://github.com/{owner}/{repo}/compare/{base}...{branch}?expand=1"
                    if owner and repo else "")
    if _gh_available():
        try:
            # หมายเหตุ (fix): `gh pr create` ไม่มี flag `--json` (มีเฉพาะในคำสั่ง query
            # เช่น pr list/view) — การใช้ --json ทำให้ fail ทุกครั้งบน gh แท้
            # จึงดึง URL จาก stdout ที่ gh พิมพ์ออกมาตอนสร้าง PR สำเร็จแทน
            gh = subprocess.run(
                ["gh", "pr", "create", "--base", base, "--head", branch,
                 "--title", title, "--body", body or title],
                cwd=cwd, capture_output=True, text=True, timeout=90,
                encoding="utf-8", errors="replace")
            if gh.returncode == 0:
                url = ""
                for line in reversed((gh.stdout or "").splitlines()):
                    line = line.strip()
                    if line.startswith("http"):
                        url = line
                        break
                if not url:
                    url = _compare_url
                if url:
                    return f"เปิด PR แล้ว: {url} (branch={branch} → {base})"
            # gh ล้มเหลว (เช่น ไม่มี GH_TOKEN ใน CI) — ใช้ลิงก์ compare แทน
            if _compare_url:
                err1 = (gh.stderr or "").strip().splitlines()[0][:160] if gh.stderr else ""
                return (f"push แล้ว (branch={branch}). gh pr create ล้มเหลว"
                        + (f" ({err1})" if err1 else "")
                        + f" — เปิด PR ได้จากลิงก์นี้:\n{_compare_url}")
            return (f"push แล้ว (branch={branch}). gh pr create ล้มเหลว: "
                    f"{(gh.stderr or '').strip()[:300]}")
        except Exception as e:
            if _compare_url:
                return (f"push แล้ว (branch={branch}). gh error: {e} — "
                        f"เปิด PR ได้จากลิงก์นี้:\n{_compare_url}")
            return f"push แล้ว (branch={branch}). gh error: {e}"
    if _compare_url:
        return (f"push แล้ว (branch={branch}). เปิด PR ผ่านลิงก์นี้:\n{_compare_url}")
    return f"push แล้ว (branch={branch}). เปิด PR ที่หน้า repo ({origin})"


def pr_list(cwd: str = ".") -> str:
    """รายการ PR ที่เปิดอยู่ (gh) — ถ้าไม่มี gh คืนข้อความเตือน"""
    if not _gh_available():
        return "(ติดตั้ง GitHub CLI (gh) เพื่อดู/จัดการ PR — https://cli.github.com)"
    try:
        r = subprocess.run(["gh", "pr", "list", "--limit", "20"],
                           cwd=cwd, capture_output=True, text=True, timeout=60,
                           encoding="utf-8", errors="replace")
        return r.stdout.strip() or "(ไม่มี PR ที่เปิดอยู่)" if r.returncode == 0 \
            else f"gh pr list ล้มเหลว: {(r.stderr or '').strip()[:300]}"
    except Exception as e:
        return f"gh pr list error: {e}"