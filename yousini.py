#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yousini — Local Coding Agent สไตล์ Claude Code (เชื่อมต่อทั้งในเครื่องและออนไลน์)
รับคำสั่งภาษาธรรมชาติ ทำงานบนเครื่องจริงได้: shell / อ่าน-เขียน-แก้ไฟล์ / ค้นหา
และออนไลน์ได้: web_fetch / web_search ผ่านทุก OpenAI-compatible API

ฟีเจอร์หลัก:
- ความจำข้าม turn · streaming จริง · UI สไตล์ Claude Code (⏺/⎿) · diff สีก่อนเขียน
- syntax highlight · spinner · คำสั่ง /clear /history /help
- YOUSINI.md — บริบทโปรเจกต์ถาวร (เหมือน CLAUDE.md) โหลดอัตโนมัติ
- skills/ — โหลดสกิลจากโฟลเดอร์ (เหมือน Skills ของ Claude Code)
- Hooks — pre_tool/post_tool script ตัดสินว่าจะรัน tool ไหม (config ได้)
- Session persistence — บันทึก/โหลดบทสนทนาลงดิสก์ (/save /load /sessions)
- Background shell — รันคำสั่งยาวแบบไม่บล็อก (/jobs, read_job)
- Checkpoint/Rollback — auto git commit ก่อนแก้ไฟล์ แล้ว /rollback ได้
- serve — เปิดเว็บ UI + API (SSE) คุยผ่านเบราว์เซอร์/โปรแกรมอื่น
- connect — CLI เครื่องหนึ่งคุยกับ Yousini อีกเครื่องผ่านเน็ต
- mcp — เปิดเป็น MCP server (stdio) ให้ agent ภายนอกเรียก tools ได้

รัน:  yousini        (หรือ python3 yousini.py)
"""

import os
import sys
import io
import json
import re
import shutil
import atexit
import subprocess
import difflib
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from datetime import datetime

# readline มีเฉพาะ Unix; บน Windows ให้ข้ามได้ (ประวัติ arrow-key จะไม่ทำงาน)
try:
    import readline
except ImportError:
    readline = None

# ---- โหลด .env เอง (ไม่พึ่งพา python-dotenv) ----
def _load_env(path=".env"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except FileNotFoundError:
        pass

_load_env()

# Windows: บังคับ console เป็น UTF-8 (codepage 65001) เพื่อแสดงภาษาไทยได้
# แก้ UnicodeEncodeError ตอน rich เรนเดอร์ข้อความไทยบน Windows (cp1252)
if sys.platform == "win32":
    try:
        os.system("chcp 65001 >nul 2>&1")
    except Exception:
        pass
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass

from openai import OpenAI, BadRequestError
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.live import Live
from rich.text import Text
from rich.panel import Panel
from rich.rule import Rule
from rich.spinner import Spinner

console = Console()

# ---- Config: รองรับทุก OpenAI-compatible API ----
# อ่าน YOUSINI_* ก่อน ถ้าไม่มีตกไปใช้ ZELAX_* แล้ว GROQ_* (เข้ากันได้กับของเดิม)
API_KEY = (os.getenv("YOUSINI_API_KEY") or os.getenv("ZELAX_API_KEY")
           or os.getenv("GROQ_API_KEY", ""))
BASE_URL = (os.getenv("YOUSINI_BASE_URL") or os.getenv("ZELAX_BASE_URL")
            or os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"))
MODEL = (os.getenv("YOUSINI_MODEL") or os.getenv("ZELAX_MODEL")
         or os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"))

AUTO_RUN = os.getenv("AUTO_RUN", "0") == "1"
CONFIRM_FILES = os.getenv("CONFIRM_FILES", "1") == "1"
SHELL_TIMEOUT = int(os.getenv("SHELL_TIMEOUT", "60"))

# ---- Config ฟีเจอร์ใหม่ ----
# ชื่อไฟล์บริบทโปรเจกต์ (เหมือน CLAUDE.md)
CONTEXT_FILE = os.getenv("YOUSINI_CONTEXT", "YOUSINI.md")
# โฟลเดอร์สกิล (relative ต่อ cwd)
SKILLS_DIR = os.getenv("YOUSINI_SKILLS", "skills")
# โฟลเดอร์ hooks: ถ้าไม่ระบุ จะหา ./.yousini/hooks แล้ว ~/.yousini/hooks
HOOKS_DIR = os.getenv("YOUSINI_HOOKS", "")
# เปิด/ปิด auto-checkpoint (git commit ก่อนแก้ไฟล์)
CHECKPOINT = os.getenv("YOUSINI_CHECKPOINT", "1") == "1"
# ที่เก็บ session
SESSION_DIR = Path(os.getenv("YOUSINI_SESSIONS",
                              str(Path.home() / ".yousini" / "sessions")))

# Web search provider (ทางเลือกเสริม: ใช้ API key ของผู้ให้บริการค้นหาจริง แทน scraping)
# ตั้ง YOUSINI_SEARCH_PROVIDER=brave|serpapi|tavily แล้วใส่ key ผ่านตัวแปรที่สอดคล้อง
SEARCH_PROVIDER = (os.getenv("YOUSINI_SEARCH_PROVIDER") or "").lower()
SEARCH_API_KEY = (os.getenv("YOUSINI_SEARCH_API_KEY") or os.getenv("BRAVE_API_KEY")
                  or os.getenv("SERPAPI_KEY") or os.getenv("TAVILY_API_KEY", ""))

if not API_KEY:
    console.print(Text("Error: ไม่พบ API Key โปรดคัดลอก .env.example เป็น .env แล้วใส่ YOUSINI_API_KEY", style="red"))
    sys.exit(1)

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# คำสั่งอันตราย → ขออนุมัติเสมอ + เตือน
DANGER_RE = [re.compile(p) for p in [
    r"\brm\s+-rf\b", r"\brm\s+-fr\b", r"\brm\s+-r\b.*\s/\b",
    r"\bdd\b\s+if=", r"\bmkfs", r"\bshutdown\b", r"\bhalt\b", r"\breboot\b",
    r":\(\)\s*\{.*\}\s*;:", r">\s*/dev/sd", r"\bchmod\s+-R\s+0",
    r"\bmv\s+.*\s/dev/null", r"\btruncate\s+-s\s+0",
]]


def is_dangerous(cmd: str) -> bool:
    return any(r.search(cmd) for r in DANGER_RE)


def _safe_input(prompt: str) -> str:
    """อ่าน input อย่างปลอดภัย ถ้า stdin ปิด (ไม่มี TTY / ถูก redirect) จะคืนค่าว่างแทนที่จะ crash (EOFError)"""
    try:
        return input(prompt)
    except EOFError:
        return ""


def _truncate(s: str, n: int = 4000) -> str:
    if len(s) > n:
        return s[:n] + f"\n…(ตัด remaining {len(s) - n} ตัวอักษร)"
    return s


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)


def _html_to_text(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    for a, b in [("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
                 ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")]:
        html = html.replace(a, b)
    html = re.sub(r"\s+", " ", html)
    return html.strip()


BASE_SYSTEM_PROMPT = """คุณคือ Yousini — Local Coding Agent ที่ทำงานบนเครื่องของผู้ใช้ แบบเดียวกับ Claude Code
คุณสามารถรันคำสั่ง shell, อ่าน/เขียน/แก้ไฟล์, ค้นหาไฟล์บนเครื่อง และเข้าถึงอินเทอร์เน็ต (web_fetch, web_search) ได้

เครื่องมือของคุณ:
- shell      รันคำสั่ง bash บนเครื่อง (ls, python3, pip, git, สร้างโปรเจกต์ ฯลฯ) รองรับ run_in_background สำหรับคำสั่งที่รันนาน
- read_file  อ่านไฟล์ข้อความ
- write_file สร้าง/เขียนทับไฟล์
- edit_file  แก้ข้อความในไฟล์ (search & replace)
- list_dir   แสดงไฟล์ในโฟลเดอร์
- glob       หาไฟล์ตามรูปแบบ เช่น '*.py'
- grep       ค้นหาข้อความ (regex) ในไฟล์
- web_fetch  ดึงเนื้อหาเว็บจาก URL (ออนไลน์)
- web_search ค้นหาข้อมูลบนอินเทอร์เน็ต (ออนไลน์)
- set_cwd    เปลี่ยนโฟลเดอร์ทำงาน
- ask_user   ถามผู้ใช้ เฉพาะเมื่อขาดข้อมูลสำคัญจริงๆ เท่านั้น
- list_jobs  แสดงงาน shell แบบ background ที่กำลังรัน/เสร็จแล้ว
- read_job   อ่านผลลัพธ์ของงาน background ตาม job id
- load_skill โหลดเนื้อหาเต็มของสกิลตามชื่อ (จากรายการ Skills ที่โหลดแบบเลือกสรร) — เรียกเมื่องานเกี่ยวข้องกับสกิลนั้น
- run_python รันโค้ด Python บนเครื่อง (คำนวณ, ประมวลผลข้อมูล, ทดสอบ snippet) คืน stdout/stderr
- spawn_subagent รันเอเจนต์ย่อยแยกบริบทเพื่อทำงานเฉพาะส่วน (วิเคราะห์/ค้นหา/สรุป) คืนสรุปสั้นๆ ไม่ทำให้บริบทหลักบวม

หลักการทำงาน (Claude Code style):
1. วิเคราะห์คำสั่ง → วางแผนสั้นๆ → ใช้เครื่องมือ → ตรวจสอบผล → สรุป
2. ก่อนแก้ไฟล์ ให้อ่านไฟล์นั้นก่อนเสมอ
3. เปลี่ยนแปลงให้น้อยที่สุด (minimal change) อย่าทำล่วงหน้าเกินจำเป็น
4. ใช้เครื่องมือตรวจสอบผลลัพธ์ อย่าคาดเดา
5. เมื่อต้องการข้อมูลล่าสุดจากโลกภายนอก ให้ใช้ web_search/web_fetch
6. ห้ามรันคำสั่งอันตราย (rm -rf, dd, shutdown ฯลฯ) โดยไม่ได้รับอนุญาต
7. เมื่อเห็นผลจากเครื่องมือแล้ว ให้นำไปใช้ต่อ ห้ามเรียก ask_user ถามผลที่ตนเห็นอยู่แล้ว
8. เมื่องานเสร็จ ให้สรุปสั้นๆ เป็นภาษาไทย พร้อมบอกไฟล์/คำสั่งที่ทำไป
9. ทำงานแบบอัตโนมัติให้ได้มากที่สุด อย่าถามผู้ใช้ยืนยันผลที่ตรวจสอบเองได้
10. หากรัน shell ที่ใช้เวลานาน ให้ใช้ run_in_background=true แล้ว poll ผลด้วย read_job แทนการรอ
11. ห้ามเรียกใช้ชื่อเครื่องมือที่ไม่ได้ระบุไว้ข้างต้น (โดยเฉพาะ repo_browser, python, web_browser) เพราะไม่มีในระบบ และจะทำให้เกิดข้อผิดพลาดร้ายแรง ให้ใช้เฉพาะเครื่องมือที่ให้มาครั้งละตัว"""


SUBAGENT_SYSTEM_PROMPT = """คุณคือ Yousini Sub-Agent — เอเจนต์ย่อยที่ทำงานแยกบริบทเพื่อทำงานเฉพาะส่วนหนึ่ง
คุณมีเครื่องมือชุดเดียวกับเอเจนต์หลัก (shell อ่านได้, เขียนไฟล์ปิดอยู่, อ่าน/ค้นหา/เว็บ/วิเคราะห์ได้)
กฎการทำงาน:
1. รับคำสั่งงาน → วางแผนสั้นๆ → ใช้เครื่องมือ → ตรวจสอบผล → สรุป
2. คืนคำตอบเป็นภาษาไทยแบบกระชับ (สรุปผลลัพธ์สำคัญ + ไฟล์/คำสั่งที่เกี่ยวข้อง) ห้ามยืดเยื้อ
3. ห้ามเรียก spawn_subagent ซ้ำ (ห้ามสร้างเอเจนต์ย่อยซ้อนกัน)
4. ห้ามคาดเดา ให้ใช้เครื่องมือตรวจสอบเสมอ
5. งานเสร็จให้สรุปสั้นๆ แล้วหยุด (ไม่ต้องถามผู้ใช้)"""


# ---------------------------------------------------------------------------
# Context (YOUSINI.md) + Skills — บริบทโปรเจกต์ถาวร
# ---------------------------------------------------------------------------
def discover_context_files(start_dir: str, filename: str = CONTEXT_FILE):
    """ค้น YOUSINI.md จาก cwd ขึ้นไปจน root + ไฟล์ global ~/.yousini.md"""
    found = []
    try:
        d = Path(start_dir).resolve()
    except Exception:
        d = Path.cwd()
    for _ in range(12):
        p = d / filename
        if p.is_file():
            found.append(p)
        parent = d.parent
        if parent == d:
            break
        d = parent
    g = Path.home() / ".yousini.md"
    if g.is_file():
        found.append(g)
    # ลบซ้ำ (ไฟล์เดียวกันที่เจอจากหลายเส้นทาง)
    seen, uniq = set(), []
    for p in found:
        rp = str(p.resolve())
        if rp not in seen:
            seen.add(rp)
            uniq.append(p)
    return uniq


def load_context_text(start_dir: str, filename: str = CONTEXT_FILE) -> str:
    files = discover_context_files(start_dir, filename)
    chunks = []
    for p in files:
        try:
            chunks.append(f"# บริบทจาก {p}\n{p.read_text(encoding='utf-8', errors='replace')}")
        except Exception:
            pass
    return "\n\n".join(chunks)


def _skill_desc(text: str) -> str:
    """ดึงคำอธิบายสกิลสั้นๆ จากบรรทัดแรกที่มีความหมาย (หัวข้อ # หรือย่อหน้าแรก)"""
    for ln in (l.strip() for l in text.splitlines()):
        if not ln:
            continue
        if ln.startswith("#"):
            return ln.lstrip("#").strip()[:160]
        return ln[:160]
    return ""


def load_skill_index(cwd: str, skills_dir: str = SKILLS_DIR):
    """คืนรายการสกิลแบบย่อ (name, desc) โดยไม่โหลดเนื้อหาเต็ม — ป้องกัน context bloat เมื่อสกิลเยอะ"""
    d = Path(cwd) / skills_dir
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.md")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        out.append((f.stem, _skill_desc(text)))
    return out


def load_skill_full(cwd: str, name: str, skills_dir: str = SKILLS_DIR):
    d = Path(cwd) / skills_dir
    p = d / f"{name}.md"
    if not p.is_file():
        avail = ", ".join(sorted(x.stem for x in d.glob("*.md"))) if d.is_dir() else ""
        return f"Error: ไม่พบสกิล '{name}' (มี: {avail})"
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error: อ่านสกิลไม่ได้: {e}"


def build_system_prompt(context_text: str, skills) -> str:
    parts = [BASE_SYSTEM_PROMPT]
    if context_text.strip():
        parts.append("=== บริบทโปรเจกต์ (YOUSINI.md) ===\n" + context_text)
    if skills:
        idx = "\n".join(f"- {n}: {d}" for n, d in skills)
        parts.append(
            "=== Skills ที่มี (โหลดแบบเลือกสรร) ===\n"
            "รายชื่อสกิลพร้อมคำอธิบายสั้นๆ (เนื้อหาเต็มยังไม่ได้โหลดเข้ามา):\n"
            f"{idx}\n"
            "หากงานเกี่ยวข้องกับสกิลใด ให้เรียก load_skill(name) เพื่อโหลดเนื้อหาเต็มก่อนทำงาน "
            "ห้ามคาดเดอเนื้อหาสกิล")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Hooks — pre_tool / post_tool script ตัดสินว่าจะรัน tool ไหม (config ได้)
# ---------------------------------------------------------------------------
class Hooks:
    def __init__(self, hooks_dir: str = HOOKS_DIR, cwd: str = "."):
        self.cwd = os.path.abspath(cwd)
        self.dir = self._resolve_dir(hooks_dir)

    def _resolve_dir(self, hooks_dir: str):
        candidates = []
        if hooks_dir:
            candidates.append(Path(hooks_dir).expanduser())
        candidates.append(Path(self.cwd) / ".yousini" / "hooks")
        candidates.append(Path.home() / ".yousini" / "hooks")
        for c in candidates:
            if c.is_dir():
                return c
        return None

    def _resolve_script(self, base: str):
        if not self.dir:
            return None
        # เลือก interpreter ตามที่มีจริงใน PATH: บน Windows ใช้ cmd (.bat/.cmd)
        # บน Unix ใช้ bash/sh (.sh) — ถ้า interpreter ไม่มี จะข้าม extension นั้น
        if sys.platform == "win32":
            order = [(".bat", ["cmd", "/c"]), (".cmd", ["cmd", "/c"]),
                     (".sh", ["bash"])]
        else:
            order = [(".sh", ["bash"]), (".bat", ["cmd", "/c"]),
                     (".cmd", ["cmd", "/c"])]
        for ext, runner in order:
            interp = runner[0]
            if interp == "bash" and not (shutil.which("bash") or shutil.which("sh")):
                continue
            if interp == "cmd" and not shutil.which("cmd"):
                continue
            p = self.dir / (base + ext)
            if p.is_file():
                return (p, runner)
        return None

    def has_hooks(self) -> bool:
        return (self._resolve_script("pre_tool") is not None
                or self._resolve_script("post_tool") is not None
                or self._resolve_script("session_start") is not None
                or self._resolve_script("session_stop") is not None)

    def run_session_start(self):
        """เรียก script session_start.{sh,bat,cmd} ตอนเริ่ม session (fail-open)"""
        self._run_event("session_start")

    def run_session_stop(self):
        """เรียก script session_stop.{sh,bat,cmd} ตอนจบ session (fail-open)"""
        self._run_event("session_stop")

    def _run_event(self, event: str):
        h = self._resolve_script(event)
        if not h:
            return
        p, runner = h
        payload = json.dumps({"event": event, "cwd": self.cwd}, ensure_ascii=False)
        try:
            env = dict(os.environ, YOUSINI_EVENT=event, YOUSINI_CWD=self.cwd)
            subprocess.run(runner + [str(p)], input=payload,
                           capture_output=True, text=True, env=env,
                           cwd=self.cwd, timeout=15)
        except Exception:
            pass

    def run_pre(self, name: str, args: dict) -> (bool, str):
        """คืน (allowed, reason). fail-open ถ้า hook พัง เพื่อไม่ให้ agent ค้าง"""
        h = self._resolve_script("pre_tool")
        if not h:
            return (True, "")
        p, runner = h
        payload = json.dumps({"tool": name, "args": args}, ensure_ascii=False)
        try:
            env = dict(os.environ, YOUSINI_TOOL=name, YOUSINI_CWD=self.cwd)
            proc = subprocess.run(runner + [str(p)], input=payload,
                                  capture_output=True, text=True, env=env,
                                  cwd=self.cwd, timeout=15)
            if proc.returncode == 0:
                return (True, "")
            reason = (proc.stdout or proc.stderr or "").strip()
            return (False, reason or f"hook ปฏิเสธ tool '{name}' (exit {proc.returncode})")
        except Exception as e:
            console.print(Text(f"⚠ hook error (pre_tool): {e} — อนุญาตต่อ", style="yellow"))
            return (True, "")

    def run_post(self, name: str, args: dict, result: str):
        h = self._resolve_script("post_tool")
        if not h:
            return
        p, runner = h
        payload = json.dumps({"tool": name, "args": args, "result": result},
                             ensure_ascii=False)
        try:
            env = dict(os.environ, YOUSINI_TOOL=name, YOUSINI_CWD=self.cwd)
            subprocess.run(runner + [str(p)], input=payload,
                           capture_output=True, text=True, env=env,
                           cwd=self.cwd, timeout=15)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Session persistence — บันทึก/โหลดบทสนทนา (JSON)
# ---------------------------------------------------------------------------
class SessionStore:
    def __init__(self, base_dir: Path = SESSION_DIR):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)
        self.index_file = self.base / "_index.json"

    def _path(self, name: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
        return self.base / f"{safe}.json"

    def save(self, name: str, messages: list, meta: dict) -> str:
        data = {"name": name, "saved_at": datetime.now().isoformat(),
                "messages": messages, "meta": meta}
        self._path(name).write_text(json.dumps(data, ensure_ascii=False),
                                    encoding="utf-8")
        self._touch_index(name)
        return str(self._path(name))

    def load(self, name: str):
        p = self._path(name)
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def delete(self, name: str):
        p = self._path(name)
        if p.is_file():
            p.unlink()

    def list(self):
        out = []
        for p in sorted(self.base.glob("*.json")):
            if p.name == "_index.json":
                continue
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                out.append({"name": d.get("name", p.stem),
                            "saved_at": d.get("saved_at", "?"),
                            "turns": len(d.get("messages", []))})
            except Exception:
                pass
        return out

    def _touch_index(self, name: str):
        idx = {}
        try:
            idx = json.loads(self.index_file.read_text(encoding="utf-8"))
        except Exception:
            idx = {}
        idx["last"] = name
        self.index_file.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")

    def last(self):
        try:
            idx = json.loads(self.index_file.read_text(encoding="utf-8"))
            return idx.get("last")
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Background jobs — shell รันนานแบบไม่บล็อก
# ---------------------------------------------------------------------------
class JobManager:
    def __init__(self):
        self.jobs = {}
        self._seq = 0
        self._lock = None  # ใช้ threading.Lock ถ้ามี

    def start(self, command: str, cwd: str, timeout: int):
        import threading
        self._seq += 1
        jid = f"job-{self._seq}"
        buf = io.StringIO()
        try:
            proc = subprocess.Popen(["bash", "-c", command], cwd=cwd,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True)
        except Exception as e:
            return jid, None, f"Error: {e}"
        job = {"id": jid, "cmd": command, "proc": proc, "buf": buf,
               "done": False, "rc": None, "started": datetime.now().isoformat()}
        self.jobs[jid] = job

        def _pump(j):
            try:
                for line in j["proc"].stdout:
                    j["buf"].write(line)
            except Exception:
                pass
            j["proc"].stdout.close()
            j["rc"] = j["proc"].wait()
            j["done"] = True

        t = threading.Thread(target=_pump, args=(job,), daemon=True)
        t.start()
        return jid, job, None

    def read(self, jid: str, tail: int = 4000):
        job = self.jobs.get(jid)
        if not job:
            return None, f"ไม่พบงาน {jid}"
        out = job["buf"].getvalue()
        if len(out) > tail:
            out = out[-tail:]
        status = "เสร็จแล้ว" if job["done"] else "กำลังรัน"
        header = f"[{jid}] {status} (exit={job['rc']})\nคำสั่ง: {job['cmd']}\n--- ผลลัพธ์ ---\n"
        return out, header + out

    def summary(self):
        rows = []
        for jid, job in self.jobs.items():
            status = "เสร็จ" if job["done"] else "รันอยู่"
            nlines = job["buf"].getvalue().count("\n")
            rows.append(f"{jid}  [{status}]  rc={job['rc']}  {nlines} บรรทัด  | {job['cmd'][:60]}")
        return "\n".join(rows) if rows else "(ไม่มีงาน background)"


# ---------------------------------------------------------------------------
# Lexer map สำหรับ syntax highlighting
# ---------------------------------------------------------------------------
LEX = {"py": "python", "js": "javascript", "ts": "typescript", "tsx": "tsx",
       "jsx": "jsx", "json": "json", "md": "markdown", "sh": "bash",
       "yml": "yaml", "yaml": "yaml", "html": "html", "css": "css",
       "java": "java", "go": "go", "rs": "rust", "c": "c", "cpp": "cpp",
       "txt": "text", "toml": "toml", "sql": "sql"}


def _lexer_for(p: str) -> str:
    ext = p.rsplit(".", 1)[-1].lower() if "." in p else "text"
    return LEX.get(ext, "text")


# ---------------------------------------------------------------------------
# Agent — ความจำ (messages) อยู่ใน object คงอยู่ข้าม turn
# ---------------------------------------------------------------------------
class Agent:
    def __init__(self, model=MODEL, cwd=os.getcwd(), interactive=True,
                 allow_shell=True, allow_write=True, checkpoint=CHECKPOINT,
                 hooks_dir=HOOKS_DIR, context_file=CONTEXT_FILE,
                 skills_dir=SKILLS_DIR, jobs=None):
        self.model = model
        self.cwd = os.path.abspath(cwd)
        self.auto_run = AUTO_RUN
        self.confirm_files = CONFIRM_FILES
        # interactive=False → โหมด server/headless: ไม่ถามผ่าน input()
        self.interactive = interactive
        self.allow_shell = allow_shell   # ปิดได้เพื่อเซิร์ฟเวอร์แบบ read-only
        self.allow_write = allow_write
        self.checkpoint_enabled = checkpoint
        self._did_checkpoint = False
        self.jobs = jobs or JobManager()
        # บริบท + สกิล
        self.context_file = context_file
        self.skills_dir = skills_dir
        self.context_text = load_context_text(self.cwd, self.context_file)
        self.skills = load_skill_index(self.cwd, self.skills_dir)
        self.hooks = Hooks(hooks_dir, self.cwd)
        self.system_prompt = build_system_prompt(self.context_text, self.skills)
        self.messages = [{"role": "system", "content": self.system_prompt}]

    def refresh_context(self):
        """โหลดบริบท/สกิลใหม่ (เรียกหลัง set_cwd หรือ /reload)"""
        self.context_text = load_context_text(self.cwd, self.context_file)
        self.skills = load_skill_index(self.cwd, self.skills_dir)
        self.system_prompt = build_system_prompt(self.context_text, self.skills)
        # แทนที่ system message แรก
        if self.messages and self.messages[0]["role"] == "system":
            self.messages[0]["content"] = self.system_prompt
        else:
            self.messages.insert(0, {"role": "system", "content": self.system_prompt})

    def begin_turn(self):
        self._did_checkpoint = False

    # ---- trimming: ตัดที่ user-boundary เท่านั้น ไม่ให้เหลือ tool-result ลอยๆ ----
    def _trim(self, max_msgs=40):
        if len(self.messages) <= max_msgs:
            return
        sys0 = self.messages[0]
        conv = self.messages[1:]
        cuts = [i for i, m in enumerate(conv) if m["role"] == "user"]
        while len(conv) > max_msgs - 1 and len(cuts) > 1:
            drop = cuts[1]
            conv = conv[drop:]
            cuts = [i - drop for i in cuts[1:]]
        self.messages = [sys0] + conv

    # ---- Checkpoint (auto git commit ก่อนแก้ไฟล์) ----
    def checkpoint(self, reason: str = "auto") -> str:
        if not self.checkpoint_enabled:
            return ""
        if self._did_checkpoint:
            return ""
        if not self.allow_write:
            return ""
        git_dir = Path(self.cwd) / ".git"
        if not git_dir.is_dir():
            return ""
        try:
            subprocess.run(["git", "add", "-A"], cwd=self.cwd,
                           capture_output=True, text=True, timeout=20)
            r = subprocess.run(["git", "status", "--porcelain"], cwd=self.cwd,
                               capture_output=True, text=True, timeout=20)
            msg = f"[Yousini checkpoint] {reason} {datetime.now().isoformat(timespec='seconds')}"
            if not r.stdout.strip():
                # ไม่มีอะไรค้าง → commit ว่างเพื่อทำเครื่องหมายจุดเริ่มต้น (tree = สถานะก่อนแก้)
                c = subprocess.run(["git", "commit", "--allow-empty", "-m", msg],
                                   cwd=self.cwd, capture_output=True, text=True, timeout=30)
            else:
                c = subprocess.run(["git", "commit", "-m", msg], cwd=self.cwd,
                                   capture_output=True, text=True, timeout=30)
            if c.returncode == 0:
                self._did_checkpoint = True
                return f"checkpoint: {msg}"
        except Exception as e:
            return f"(checkpoint ล้มเหลว: {e})"
        return ""

    # ---- Shell ----
    def shell(self, command: str, timeout: int = None,
              run_in_background: bool = False) -> str:
        if not self.allow_shell:
            return "Error: shell ถูกปิดในโหมดนี้ (read-only server)"
        dangerous = is_dangerous(command)
        if dangerous:
            console.print(Text(f"คำเตือน: คำสั่งเสี่ยงสูง: {command}", style="yellow"))
        if not self.interactive:
            # โหมด headless/server: ห้ามคำสั่งอันตรายเด็ดขาด นอกจาก auto_run
            if dangerous and not self.auto_run:
                return "Error: คำสั่งอันตรายถูกบล็อกในโหมด headless (ตั้ง AUTO_RUN=1 เพื่ออนุญาต)"
        elif not self.auto_run or dangerous:
            console.print(Text(f"Shell: {command}", style="cyan"))
            ans = _safe_input("  รัน? [y/N/e=แก้ไข] ").strip().lower()
            if ans in ("e", "edit"):
                return self.shell(_safe_input("  พิมพ์คำสั่งใหม่: ").strip(), timeout, run_in_background)
            if ans not in ("y", "yes", "1"):
                return "ปฏิเสธโดยผู้ใช้"
        if run_in_background:
            t = timeout or SHELL_TIMEOUT
            jid, job, err = self.jobs.start(command, self.cwd, t)
            if err:
                return err
            console.print(Text(f"↻ เริ่มงาน background {jid}: {command}", style="cyan"))
            return f"เริ่มงาน background {jid} (รันไม่บล็อก) ใช้ read_job(job_id='{jid}') เพื่อดูผล"
        try:
            t = timeout or SHELL_TIMEOUT
            proc = subprocess.Popen(["bash", "-c", command], cwd=self.cwd,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            out, _ = proc.communicate(timeout=t)
            return _truncate(f"[exit code: {proc.returncode}]\n{out or '(ไม่มีผลลัพธ์)'}")
        except subprocess.TimeoutExpired:
            proc.kill()
            return f"หมดเวลา ({t}s)"
        except Exception as e:
            return f"Error: {e}"

    def _resolve(self, path):
        return path if os.path.isabs(path) else os.path.join(self.cwd, path)

    def _show_diff(self, path, old, new):
        if old is None:
            console.print(Panel(
                Syntax(new, _lexer_for(path), theme="github-dark", word_wrap=True),
                title=f"สร้างไฟล์: {path}", border_style="green"))
            return
        diff = difflib.unified_diff(old.splitlines(), new.splitlines(),
                                    fromfile="เดิม", tofile="ใหม่", lineterm="")
        t = Text()
        for line in diff:
            if line.startswith("+") and not line.startswith("+++"):
                t.append(line + "\n", style="green")
            elif line.startswith("-") and not line.startswith("---"):
                t.append(line + "\n", style="red")
            elif line.startswith(("@@", "+++", "---")):
                t.append(line + "\n", style="bold cyan")
            else:
                t.append(line + "\n", style="dim")
        console.print(Panel(t, title=f"แก้ไฟล์: {path}", border_style="yellow"))

    def read_file(self, path: str, limit: int = 0) -> str:
        fp = self._resolve(path)
        if not os.path.isfile(fp):
            return f"Error: ไม่พบไฟล์: {fp}"
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                data = f.read()
            shown = "\n".join(data.splitlines()[:limit]) if limit and limit > 0 else data
            console.print(Panel(
                Syntax(shown, _lexer_for(fp), theme="github-dark", word_wrap=True),
                title=f"อ่าน: {fp}", border_style="blue"))
            return _truncate(data)
        except Exception as e:
            return f"Error: อ่านไม่ได้: {e}"

    def write_file(self, path: str, content: str) -> str:
        fp = self._resolve(path)
        old = None
        if os.path.isfile(fp):
            try:
                old = open(fp, "r", encoding="utf-8").read()
            except Exception:
                old = ""
        if not self.allow_write:
            return "Error: การเขียนไฟล์ถูกปิดในโหมดนี้ (read-only server)"
        self.checkpoint(f"ก่อนเขียน {os.path.basename(path)}")
        self._show_diff(path, old, content)
        if self.interactive and self.confirm_files and os.path.exists(fp):
            if _safe_input("   ยืนยันเขียนทับ? [y/N] ").strip().lower() not in ("y", "yes", "1"):
                return "ปฏิเสธโดยผู้ใช้"
        try:
            os.makedirs(os.path.dirname(fp) or ".", exist_ok=True)
            with open(fp, "w", encoding="utf-8") as f:
                f.write(content)
            return f"เขียนสำเร็จ: {fp} ({len(content)} ตัวอักษร)"
        except Exception as e:
            return f"Error: เขียนไม่ได้: {e}"

    def edit_file(self, path: str, old_string: str, new_string: str) -> str:
        fp = self._resolve(path)
        if not os.path.isfile(fp):
            return f"Error: ไม่พบไฟล์: {fp}"
        try:
            old = open(fp, "r", encoding="utf-8").read()
        except Exception as e:
            return f"Error: อ่านไม่ได้: {e}"
        if old_string not in old:
            return "Error: ไม่พบ old_string ในไฟล์"
        if not self.allow_write:
            return "Error: การแก้ไฟล์ถูกปิดในโหมดนี้ (read-only server)"
        self.checkpoint(f"ก่อนแก้ {os.path.basename(path)}")
        new = old.replace(old_string, new_string)
        self._show_diff(path, old, new)
        if self.interactive and self.confirm_files:
            if _safe_input("   ยืนยันแก้ไฟล์? [y/N] ").strip().lower() not in ("y", "yes", "1"):
                return "ปฏิเสธโดยผู้ใช้"
        try:
            with open(fp, "w", encoding="utf-8") as f:
                f.write(new)
            return f"แก้สำเร็จ: {fp} ({old.count(old_string)} แห่ง)"
        except Exception as e:
            return f"Error: แก้ไม่ได้: {e}"

    def list_dir(self, path: str = ".") -> str:
        fp = self._resolve(path)
        if not os.path.isdir(fp):
            return f"Error: ไม่พบโฟลเดอร์: {fp}"
        try:
            return "\n".join(
                f"{n}/" if os.path.isdir(os.path.join(fp, n)) else n
                for n in sorted(os.listdir(fp))) or "(ว่าง)"
        except Exception as e:
            return f"Error: {e}"

    def glob(self, pattern: str, path: str = ".") -> str:
        import fnmatch
        base = self._resolve(path)
        if not os.path.isdir(base):
            return f"Error: ไม่พบโฟลเดอร์: {base}"
        try:
            hits = [os.path.join(r, fn) for r, _, fs in os.walk(base)
                    for fn in fs if fnmatch.fnmatch(fn, pattern)]
            return "\n".join(hits[:200]) if hits else "Error: ไม่พบ"
        except Exception as e:
            return f"Error: {e}"

    def grep(self, pattern: str, path: str = ".", glob_pattern: str = "*") -> str:
        import fnmatch
        base = self._resolve(path)
        if not os.path.isdir(base):
            return f"Error: ไม่พบโฟลเดอร์: {base}"
        try:
            rx = re.compile(pattern)
            hits = []
            for root, _, files in os.walk(base):
                for fn in files:
                    if not fnmatch.fnmatch(fn, glob_pattern):
                        continue
                    fp = os.path.join(root, fn)
                    if os.path.getsize(fp) > 5_000_000:
                        continue
                    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                        for i, line in enumerate(f, 1):
                            if rx.search(line):
                                hits.append(f"{fp}:{i}: {line.rstrip()}")
                                if len(hits) >= 200:
                                    break
                if len(hits) >= 200:
                    break
            return "\n".join(hits) if hits else "Error: ไม่พบ"
        except re.error as e:
            return f"Error: regex ผิด: {e}"
        except Exception as e:
            return f"Error: {e}"

    # ---- ออนไลน์ ----
    def web_fetch(self, url: str, max_chars: int = 6000) -> str:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                raw = r.read(800000)
                charset = r.headers.get_content_charset() or "utf-8"
                text = raw.decode(charset, errors="replace")
            content = _html_to_text(text)[:max_chars]
            console.print(Panel(Text(content or "(ว่าง)", style="dim"),
                                title=f"Web: {url}", border_style="blue"))
            return _truncate(text, max_chars)
        except Exception as e:
            return f"Error: web_fetch ไม่ได้: {e}"

    def web_search(self, query: str, max_results: int = 5) -> str:
        if SEARCH_PROVIDER in ("brave", "serpapi", "tavily") and SEARCH_API_KEY:
            return web_search_api(query, max_results, SEARCH_PROVIDER, SEARCH_API_KEY)
        return web_search_robust(query, max_results)

    def set_cwd(self, path: str) -> str:
        fp = self._resolve(path)
        if not os.path.isdir(fp):
            return f"Error: ไม่พบโฟลเดอร์: {fp}"
        self.cwd = os.path.abspath(fp)
        self.hooks.cwd = self.cwd
        self.refresh_context()
        return f"เปลี่ยนโฟลเดอร์เป็น: {self.cwd}"

    def ask_user(self, question: str) -> str:
        if not self.interactive:
            return "(โหมดไม่โต้ตอบ: ไม่สามารถถามผู้ใช้ได้ กรุณาตัดสินใจเองจากข้อมูลที่มี)"
        console.print(Text(f"Agent: {question}", style="yellow"))
        try:
            return input("คุณ: ").strip()
        except EOFError:
            return "(ไม่มีคำตอบ — โหมดไม่โต้ตอบ)"

    def list_jobs(self) -> str:
        return self.jobs.summary()

    def read_job(self, job_id: str, tail: int = 4000) -> str:
        _, text = self.jobs.read(job_id, tail)
        return text

    # ---- โหลดสกิลแบบเลือกสรร (lazy-load): โมเดลขอโหลดเนื้อหาเต็มเมื่อจำเป็น ----
    def load_skill(self, name: str) -> str:
        return load_skill_full(self.cwd, name, self.skills_dir)

    # ---- รัน Python (แขนขาทำงานคำนวณ/ประมวลผลจริง) ----
    def run_python(self, code: str, timeout: int = None) -> str:
        if not self.allow_shell:
            return "Error: การรัน Python ถูกปิดในโหมดนี้ (read-only server)"
        t = timeout or SHELL_TIMEOUT
        import tempfile
        fd = None
        try:
            fd, path = tempfile.mkstemp(suffix=".py", text=True)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(code)
            fd = None
            proc = subprocess.run([sys.executable, path], cwd=self.cwd,
                                  capture_output=True, text=True, timeout=t)
            out = (proc.stdout or "") + (proc.stderr or "")
            if out.strip():
                console.print(Panel(Text(_truncate(out, 4000), style="dim"),
                                    title=f"Python (exit={proc.returncode})", border_style="blue"))
            return _truncate(f"[exit code: {proc.returncode}]\n{out or '(ไม่มีผลลัพธ์)'}")
        except subprocess.TimeoutExpired:
            return f"หมดเวลา ({t}s)"
        except Exception as e:
            return f"Error: {e}"
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except Exception:
                    pass
            try:
                os.unlink(path)
            except Exception:
                pass

    # ---- เอเจนต์ย่อย (subagent) แยกบริบท ไม่ทำให้บริบทหลักบวม ----
    def spawn_subagent(self, task: str, focus: str = "") -> str:
        sub = Agent(model=self.model, cwd=self.cwd, interactive=False,
                    allow_shell=self.allow_shell, allow_write=False,
                    checkpoint=False, context_file=self.context_file,
                    skills_dir=self.skills_dir)
        sub.system_prompt = (SUBAGENT_SYSTEM_PROMPT
                             + (f"\n\nโฟกัสงาน: {focus}" if focus else "")
                             + (f"\n\nบริบทโปรเจกต์:\n{self.context_text}"
                                if self.context_text.strip() else ""))
        sub.messages = [{"role": "system", "content": sub.system_prompt}]
        console.print(Text(f"⚙ เอเจนต์ย่อย: {_truncate(task, 60)}", style="dim"))
        return _run_subagent_loop(sub, task, max_iter=6)


# ---------------------------------------------------------------------------
# web_search แบบทนทาน: ลองหลาย endpoint + fallback
# ---------------------------------------------------------------------------
def web_search_robust(query: str, max_results: int = 5) -> str:
    q = urllib.parse.quote(query)
    agents = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
              "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
              "Mozilla/5.0 (X11; Linux x86_64)"]
    endpoints = [
        ("html", f"https://html.duckduckgo.com/html/?q={q}"),
        ("lite", f"https://lite.duckduckgo.com/lite/?q={q}"),
        ("bing", f"https://www.bing.com/search?q={q}&setlang=th"),
    ]
    last_err = ""
    for kind, url in endpoints:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": agents[0]})
            with urllib.request.urlopen(req, timeout=25) as r:
                html = r.read().decode("utf-8", errors="replace")
            if kind in ("html", "lite"):
                titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.S)
                links = re.findall(r'class="result__a"[^>]*href="([^"]+)"', html)
                snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S)
                if not titles:
                    # fallback pattern สำหรับ lite.ddg
                    titles = re.findall(r'<a[^>]+class="result-link"[^>]*>(.*?)</a>', html, re.S)
                    links = re.findall(r'<a[^>]+class="result-link"[^>]+href="([^"]+)"', html)
            else:  # bing
                titles = re.findall(r'<li class="b_algo"[^>]*>.*?<h2>.*?<a[^>]*>(.*?)</a>',
                                    html, re.S)
                links = re.findall(r'<li class="b_algo"[^>]*>.*?<h2>.*?<a[^>]+href="([^"]+)"',
                                   html, re.S)
                snippets = re.findall(r'<li class="b_algo"[^>]*>.*?<p[^>]*>(.*?)</p>',
                                      html, re.S)
            out = []
            for i in range(min(max_results, len(titles))):
                t = _strip_tags(titles[i]).strip()
                l = links[i] if i < len(links) else ""
                s = _strip_tags(snippets[i]).strip() if i < len(snippets) else ""
                if not t:
                    continue
                # ลิงก์ DDG มักเป็น redirect 302 → พยายามถอด
                if l.startswith("//duckduckgo.com/l/?uddg="):
                    try:
                        l = urllib.parse.unquote(l.split("uddg=", 1)[1].split("&", 1)[0])
                    except Exception:
                        pass
                out.append(f"{i+1}. {t}\n   {l}\n   {s}")
            if out:
                res = "\n".join(out)
                console.print(Panel(Text(res, style="dim"),
                                    title=f"ค้นหา: {query}", border_style="blue"))
                return res
            last_err = f"(parser ไม่เจอผลจาก {kind})"
        except Exception as e:
            last_err = f"{kind}: {e}"
            continue
    return f"Error: web_search ไม่ได้จากทุกแหล่ง ({last_err})"


# ---------------------------------------------------------------------------
# web_search ผ่าน API provider จริง (Brave / SerpAPI / Tavily) — ทางเลือกเสริม
# ใช้เมื่อตั้ง YOUSINI_SEARCH_PROVIDER + key แล้ว ไม่พึ่ง scraping
# ---------------------------------------------------------------------------
def web_search_api(query: str, max_results: int, provider: str, api_key: str) -> str:
    try:
        if provider == "brave":
            url = ("https://api.search.brave.com/res/v1/web/search?"
                   + urllib.parse.urlencode({"q": query, "count": max_results}))
            req = urllib.request.Request(url, headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read().decode("utf-8"))
            rows = (data.get("web", {}) or {}).get("results", [])[:max_results]
            out = [f"{i+1}. {x.get('title','')}\n   {x.get('url','')}\n   "
                   f"{_strip_tags(x.get('description',''))}"
                   for i, x in enumerate(rows)]
        elif provider == "serpapi":
            url = ("https://serpapi.com/search.json?"
                   + urllib.parse.urlencode({"q": query, "num": max_results,
                                             "api_key": api_key}))
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read().decode("utf-8"))
            rows = data.get("organic_results", [])[:max_results]
            out = [f"{i+1}. {x.get('title','')}\n   {x.get('link','')}\n   "
                   f"{_strip_tags(x.get('snippet',''))}"
                   for i, x in enumerate(rows)]
        elif provider == "tavily":
            url = "https://api.tavily.com/search"
            body = json.dumps({"api_key": api_key, "query": query,
                               "max_results": max_results,
                               "search_depth": "basic"}).encode("utf-8")
            req = urllib.request.Request(url, data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read().decode("utf-8"))
            rows = data.get("results", [])[:max_results]
            out = [f"{i+1}. {x.get('title','')}\n   {x.get('url','')}\n   "
                   f"{_strip_tags(str(x.get('content','')))}"
                   for i, x in enumerate(rows)]
        else:
            return f"Error: ไม่รู้จัก provider '{provider}'"
        if not out:
            return "(ไม่พบผลลัพธ์จาก " + provider + ")"
        res = "\n".join(out)
        console.print(Panel(Text(res, style="dim"),
                            title=f"ค้นหา ({provider}): {query}", border_style="blue"))
        return res
    except Exception as e:
        # ถ้า API พัง ตกกลับไป scraping อัตโนมัติ (fail-open)
        return (f"(API {provider} ล้มเหลว: {e} — ลอง scraping)\n"
                + web_search_robust(query, max_results))


TOOLS = [
    {"type": "function", "function": {"name": "shell", "description": "รันคำสั่ง bash บนเครื่อง (ls, python3, pip install, git, สร้างโปรเจกต์). เพิ่ม run_in_background=true สำหรับคำสั่งที่รันนาน แล้วอ่านผลด้วย read_job", "parameters": {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer"}, "run_in_background": {"type": "boolean"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "อ่านไฟล์ข้อความ (มี syntax highlighting)", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "สร้าง/เขียนทับไฟล์", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "edit_file", "description": "แทนที่ old_string ด้วย new_string ในไฟล์", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}}, "required": ["path", "old_string", "new_string"]}}},
    {"type": "function", "function": {"name": "list_dir", "description": "แสดงไฟล์ในโฟลเดอร์", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": []}}},
    {"type": "function", "function": {"name": "glob", "description": "หาไฟล์ตามรูปแบบ เช่น '*.py'", "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "grep", "description": "ค้นหาข้อความ (regex) ในไฟล์", "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}, "glob_pattern": {"type": "string"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "web_fetch", "description": "ดึงเนื้อหาเว็บจาก URL (ออนไลน์) คืนข้อความที่อ่านได้", "parameters": {"type": "object", "properties": {"url": {"type": "string", "description": "URL เต็ม เช่น https://example.com"}, "max_chars": {"type": "integer", "description": "จำกัดตัวอักษร (ค่าเริ่มต้น 6000)"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "web_search", "description": "ค้นหาข้อมูลบนอินเทอร์เน็ต (ออนไลน์) คืนรายการผลลัพธ์", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "คำค้นหา"}, "max_results": {"type": "integer", "description": "จำนวนผลลัพธ์ (ค่าเริ่มต้น 5)"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "set_cwd", "description": "เปลี่ยนโฟลเดอร์ทำงาน", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "ask_user", "description": "ถามผู้ใช้เฉพาะเมื่อขาดข้อมูลสำคัญจริงๆ เท่านั้น", "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}}},
    {"type": "function", "function": {"name": "list_jobs", "description": "แสดงงาน shell แบบ background ที่กำลังรันหรือเสร็จแล้ว", "parameters": {"type": "object", "properties": {}}, "required": []}},
    {"type": "function", "function": {"name": "read_job", "description": "อ่านผลลัพธ์ของงาน background ตาม job id (ได้จาก shell ที่รันแบบ background)", "parameters": {"type": "object", "properties": {"job_id": {"type": "string"}, "tail": {"type": "integer", "description": "จำกัดตัวอักษรท้ายสุด (ค่าเริ่มต้น 4000)"}}, "required": ["job_id"]}}},
    {"type": "function", "function": {"name": "load_skill", "description": "โหลดเนื้อหาเต็มของสกิลตามชื่อ (จากรายการ Skills ที่โหลดแบบเลือกสรร) เพื่อนำมาใช้เป็นแนวทางทำงาน เรียกเฉพาะเมื่องานเกี่ยวข้องกับสกิลนั้น", "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "ชื่อสกิล เช่น 'dep' (ไม่รวม .md)"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "run_python", "description": "รันโค้ด Python บนเครื่อง คืน stdout/stderr (ใช้สำหรับคำนวณ, ประมวลผลข้อมูล, ทดสอบ snippet) ปิดได้ในโหมด read-only", "parameters": {"type": "object", "properties": {"code": {"type": "string", "description": "โค้ด Python เต็ม"}, "timeout": {"type": "integer", "description": "จำกัดวินาที (ค่าเริ่มต้นตาม SHELL_TIMEOUT)"}}, "required": ["code"]}}},
    {"type": "function", "function": {"name": "spawn_subagent", "description": "รันเอเจนต์ย่อยแยกบริบทเพื่อทำงานเฉพาะส่วน (เช่น วิเคราะห์ไฟล์, ค้นหาข้อมูล, สรุป) คืนคำสรุปสั้นๆ ไม่ทำให้บริบทหลักบวม ห้ามเรียกซ้อนกัน", "parameters": {"type": "object", "properties": {"task": {"type": "string", "description": "คำสั่งงานสำหรับเอเจนต์ย่อย"}, "focus": {"type": "string", "description": "โฟกัสเพิ่มเติม (ไม่บังคับ)"}}, "required": ["task"]}}},
]

IMPL = {
    "shell": lambda a, k: k.shell(**a), "read_file": lambda a, k: k.read_file(**a),
    "write_file": lambda a, k: k.write_file(**a), "edit_file": lambda a, k: k.edit_file(**a),
    "list_dir": lambda a, k: k.list_dir(**a), "glob": lambda a, k: k.glob(**a),
    "grep": lambda a, k: k.grep(**a), "web_fetch": lambda a, k: k.web_fetch(**a),
    "web_search": lambda a, k: k.web_search(**a), "set_cwd": lambda a, k: k.set_cwd(**a),
    "ask_user": lambda a, k: k.ask_user(**a), "list_jobs": lambda a, k: k.list_jobs(),
    "read_job": lambda a, k: k.read_job(**a),
    "load_skill": lambda a, k: k.load_skill(**a),
    "run_python": lambda a, k: k.run_python(**a),
    "spawn_subagent": lambda a, k: k.spawn_subagent(**a),
}

# ข้อความเตือนเมื่อโมเดลเรียก tool ที่ไม่มีในระบบ (เช่น repo_browser ของ gpt-oss)
_TOOL_FIX_HINT = (
    "ข้อผิดพลาด: คุณพยายามเรียกใช้เครื่องมือที่ไม่มีในระบบ (เช่น repo_browser, python, "
    "web_browser) กรุณาใช้เฉพาะเครื่องมือที่กำหนดให้เท่านั้น: shell, read_file, write_file, "
    "edit_file, list_dir, glob, grep, web_fetch, web_search, set_cwd, ask_user, "
    "list_jobs, read_job"
)


def _is_tool_validation_err(e) -> bool:
    s = str(e).lower()
    return ("tool call validation" in s or "not in request.tools" in s
            or "unknown tool" in s or "invalid tool" in s)


def _exec_tool(agent: Agent, name: str, args: dict, tc_id: str):
    # ---- Hook: pre_tool ----
    allowed, reason = agent.hooks.run_pre(name, args)
    if not allowed:
        console.print(Text(f"⏹ hook ปฏิเสธ {name}: {reason}", style="red"))
        agent.messages.append({"role": "tool", "tool_call_id": tc_id,
                               "content": f"Blocked by hook: {reason}"})
        return
    if name not in IMPL:
        msg = (f"Error: ไม่มีเครื่องมือ '{name}' ในระบบ "
               f"(มี: {', '.join(sorted(IMPL))})")
        console.print(Text(f"⚠ {msg}", style="red"))
        agent.messages.append({"role": "tool", "tool_call_id": tc_id, "content": msg})
        return
    shown = args.get("command", "") if name == "shell" else args
    if not isinstance(shown, str):
        shown = json.dumps(shown, ensure_ascii=False)
    console.print(Text(f"⏺ {name}({shown})", style="bold cyan"))
    result = IMPL[name](args, agent)
    agent.hooks.run_post(name, args, str(result))
    console.print(Text(f"⎿ {_truncate(str(result), 1500)}", style="dim"))
    agent.messages.append({"role": "tool", "tool_call_id": tc_id, "content": str(result)})


def _fallback_turn(agent: Agent, err):
    console.print(Text("คำเตือน: โมเดลสร้างคำตอบไม่ถูกต้อง กำลังขอคำตอบแบบปกติ…", style="yellow"))
    try:
        resp = client.chat.completions.create(
            model=agent.model, messages=agent.messages, tools=[], temperature=0.5)
        ans = resp.choices[0].message.content or "(โมเดลไม่ตอบ)"
        agent.messages.append({"role": "assistant", "content": ans})
        console.print(Markdown(ans))
    except Exception as e2:
        console.print(Text(f"Error: {e2}", style="red"))


def _run_subagent_loop(agent: Agent, task: str, max_iter: int = 6) -> str:
    """ลูปเอเจนต์ย่อยแบบไม่สตรีมมิง (เก็บคำตอบสุดท้าย) — รันภายใน tool call ของเอเจนต์หลัก"""
    agent.messages.append({"role": "user", "content": task})
    for _ in range(max_iter):
        try:
            resp = client.chat.completions.create(
                model=agent.model, messages=agent.messages, tools=TOOLS,
                tool_choice="auto", temperature=0.3,
                parallel_tool_calls=False)
        except Exception as e:
            return f"[เอเจนต์ย่อย error: {e}]"
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return msg.content or "(ไม่มีคำตอบ)"
        agent.messages.append(msg)
        for tc in msg.tool_calls:
            fn = tc.function.name or ""
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            if not isinstance(args, dict):
                args = {}
            # ห้ามสร้างเอเจนต์ย่อยซ้อนกัน
            if fn == "spawn_subagent":
                agent.messages.append({"role": "tool", "tool_call_id": tc.id,
                    "content": "Error: ไม่สามารถสร้างเอเจนต์ย่อยซ้อนกันได้ (รองรับแค่ 1 ชั้น)"})
                continue
            if fn not in IMPL:
                agent.messages.append({"role": "tool", "tool_call_id": tc.id,
                    "content": f"Error: ไม่มีเครื่องมือ '{fn}'"})
                continue
            try:
                result = IMPL[fn](args, agent)
            except Exception as e:
                result = f"Error: {e}"
            agent.messages.append({"role": "tool", "tool_call_id": tc.id,
                                   "content": str(result)})
    return "(เอเจนต์ย่อยหมดรอบจำกัด — คืนผลลัพธ์ที่ได้)"


def chat_turn(agent: Agent, user_text: str):
    agent.begin_turn()
    agent.messages.append({"role": "user", "content": user_text})
    agent._trim()
    tool_seen = False
    attempts = 0
    MAX_ATTEMPTS = 3
    while True:
        try:
            stream = client.chat.completions.create(
                model=agent.model, messages=agent.messages, tools=TOOLS,
                tool_choice="auto", temperature=0.5, parallel_tool_calls=False, stream=True)
        except BadRequestError as e:
            if _is_tool_validation_err(e) and attempts < MAX_ATTEMPTS:
                attempts += 1
                agent.messages.append({"role": "user", "content": _TOOL_FIX_HINT})
                continue
            return _fallback_turn(agent, e)
        except Exception as e:
            console.print(Text(f"Error: {e}", style="red")); return

        content = []
        tool_calls = []

        def render():
            if not content:
                return Spinner("dots", text="กำลังคิด…", style="dim")
            return Markdown("".join(content))

        try:
            with Live(render(), console=console, refresh_per_second=12) as live:
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    d = chunk.choices[0].delta
                    if d.content:
                        content.append(d.content)
                        live.update(render())
                    if d.tool_calls:
                        for tc in d.tool_calls:
                            i = tc.index or 0
                            while len(tool_calls) <= i:
                                tool_calls.append({"id": "", "name": "", "args": ""})
                            if tc.id:
                                tool_calls[i]["id"] = tc.id
                            if tc.function and tc.function.name:
                                tool_calls[i]["name"] += tc.function.name
                            if tc.function and tc.function.arguments:
                                tool_calls[i]["args"] += tc.function.arguments
        except BadRequestError as e:
            if _is_tool_validation_err(e) and attempts < MAX_ATTEMPTS:
                attempts += 1
                agent.messages.append({"role": "user", "content": _TOOL_FIX_HINT})
                continue
            return _fallback_turn(agent, e)
        except Exception as e:
            if _is_tool_validation_err(e) and attempts < MAX_ATTEMPTS:
                attempts += 1
                agent.messages.append({"role": "user", "content": _TOOL_FIX_HINT})
                continue
            console.print(Text(f"Error: stream {e}", style="red")); return

        if any(t.get("name") for t in tool_calls):
            tool_seen = True
            console.print(Text("กำลังเตรียมเครื่องมือ…", style="dim"))
            asst = {"role": "assistant", "content": "".join(content)}
            asst["tool_calls"] = [
                {"id": t["id"], "type": "function",
                 "function": {"name": t["name"], "arguments": t["args"]}}
                for t in tool_calls if t["name"]]
            agent.messages.append(asst)
            for t in tool_calls:
                if not t["name"]:
                    continue
                try:
                    args = json.loads(t["args"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                _exec_tool(agent, t["name"], args, t["id"])
            continue

        ans = "".join(content)
        agent.messages.append({"role": "assistant", "content": ans})
        if tool_seen:
            console.rule("คำตอบ Yousini", style="magenta")
        console.print()
        return


# ---------------------------------------------------------------------------
# run_turn_events — เวอร์ชัน generator สำหรับ server/remote (yield เป็น event)
# event: {"type": "token"|"tool"|"tool_result"|"final"|"error", ...}
# ---------------------------------------------------------------------------
def run_turn_events(agent: Agent, user_text: str):
    agent.begin_turn()
    agent.messages.append({"role": "user", "content": user_text})
    agent._trim()
    attempts = 0
    MAX_ATTEMPTS = 3
    while True:
        try:
            stream = client.chat.completions.create(
                model=agent.model, messages=agent.messages, tools=TOOLS,
                tool_choice="auto", temperature=0.5,
                parallel_tool_calls=False, stream=True)
        except Exception as e:
            if _is_tool_validation_err(e) and attempts < MAX_ATTEMPTS:
                attempts += 1
                agent.messages.append({"role": "user", "content": _TOOL_FIX_HINT})
                continue
            yield {"type": "error", "text": str(e)}
            return

        content = []
        tool_calls = []
        try:
            for chunk in stream:
                if not chunk.choices:
                    continue
                d = chunk.choices[0].delta
                if d.content:
                    content.append(d.content)
                    yield {"type": "token", "text": d.content}
                if d.tool_calls:
                    for tc in d.tool_calls:
                        i = tc.index or 0
                        while len(tool_calls) <= i:
                            tool_calls.append({"id": "", "name": "", "args": ""})
                        if tc.id:
                            tool_calls[i]["id"] = tc.id
                        if tc.function and tc.function.name:
                            tool_calls[i]["name"] += tc.function.name
                        if tc.function and tc.function.arguments:
                            tool_calls[i]["args"] += tc.function.arguments
        except Exception as e:
            if _is_tool_validation_err(e) and attempts < MAX_ATTEMPTS:
                attempts += 1
                agent.messages.append({"role": "user", "content": _TOOL_FIX_HINT})
                continue
            yield {"type": "error", "text": str(e)}
            return

        if any(t.get("name") for t in tool_calls):
            asst = {"role": "assistant", "content": "".join(content)}
            asst["tool_calls"] = [
                {"id": t["id"], "type": "function",
                 "function": {"name": t["name"], "arguments": t["args"]}}
                for t in tool_calls if t["name"]]
            agent.messages.append(asst)
            for t in tool_calls:
                if not t["name"]:
                    continue
                try:
                    args = json.loads(t["args"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                # ---- Hook: pre_tool (สำหรับ server/remote ด้วย) ----
                allowed, reason = agent.hooks.run_pre(t["name"], args)
                shown = args.get("command", "") if t["name"] == "shell" else args
                if not isinstance(shown, str):
                    shown = json.dumps(shown, ensure_ascii=False)
                if not allowed:
                    yield {"type": "tool", "name": t["name"], "args": shown, "blocked": True}
                    agent.messages.append({"role": "tool",
                                           "tool_call_id": t["id"],
                                           "content": f"Blocked by hook: {reason}"})
                    yield {"type": "tool_result", "name": t["name"],
                           "result": _truncate(f"Blocked by hook: {reason}", 1500)}
                    continue
                yield {"type": "tool", "name": t["name"], "args": shown}
                result = IMPL[t["name"]](args, agent)
                agent.hooks.run_post(t["name"], args, str(result))
                agent.messages.append({"role": "tool",
                                       "tool_call_id": t["id"], "content": str(result)})
                yield {"type": "tool_result", "name": t["name"],
                       "result": _truncate(str(result), 1500)}
            continue

        yield {"type": "final", "text": "".join(content)}
        return


# ---------------------------------------------------------------------------
# REPL + readline history ข้ามเซสชัน
# ---------------------------------------------------------------------------
HIST_FILE = Path.home() / ".yousini_history"


def _setup_readline():
    if readline is None:
        return
    try:
        readline.read_history_file(HIST_FILE)
    except FileNotFoundError:
        pass
    readline.set_history_length(2000)
    atexit.register(lambda: readline.write_history_file(HIST_FILE))


YOUSINI_ART = r"""
 __   __  _______  __   __  _______  ___   __    _  ___
|  | |  ||       ||  | |  ||       ||   | |  |  | ||   |
|  |_|  ||   _   ||  | |  ||  _____||   | |   |_| ||   |
|       ||  | |  ||  |_|  || |_____ |   | |       ||   |
|_     _||  |_|  ||       ||_____  ||   | |  _    ||   |
  |   |  |       ||       | _____| ||   | | | |   ||   |
  |___|  |_______||_______||_______||___| |_|  |__||___|
"""


def _gradient(text: str, colors):
    """ระบายสีไล่เฉดให้ตัวอักษร (ต่อบรรทัด)"""
    out = Text()
    lines = text.split("\n")
    for line in lines:
        n = max(len(line), 1)
        for i, ch in enumerate(line):
            c = colors[int(i / n * (len(colors) - 1))]
            out.append(ch, style=f"bold {c}")
        out.append("\n")
    return out


def _print_banner(agent: Agent):
    palette = ["#18d3ff", "#5ca8ff", "#7c5cff", "#b45cff", "#ff5cae"]
    console.print(_gradient(YOUSINI_ART, palette))
    txt = Text()
    txt.append("ผู้ช่วยเขียนโค้ดอัจฉริยะ", style="bold magenta")
    txt.append("  ·  ทำงานบนเครื่องจริง + ออนไลน์  ·  เชื่อมต่อข้ามเครื่องได้\n\n", style="dim")
    txt.append("  สมอง      ", style="dim"); txt.append(agent.model + "\n", style="bold cyan")
    txt.append("  เชื่อมต่อ   ", style="dim"); txt.append(BASE_URL + "\n", style="dim")
    txt.append("  โฟลเดอร์   ", style="dim"); txt.append(agent.cwd + "\n", style="dim")
    txt.append("  โหมด      ", style="dim")
    txt.append("เครื่อง + ออนไลน์", style="green")
    txt.append("   ·   shell ", style="dim")
    txt.append("ถามก่อน" if not agent.auto_run else "รันทันที", style="yellow")
    ctx = "เปิด" if agent.context_text.strip() else "ปิด"
    sk = len(agent.skills)
    hk = "มี" if agent.hooks.has_hooks() else "ไม่มี"
    txt.append(f"\n  บริบท(YOUSINI.md) ", style="dim"); txt.append(ctx + "\n", style="cyan")
    txt.append("  สกิล      ", style="dim"); txt.append(f"{sk} ตัว\n", style="cyan")
    txt.append("  hooks     ", style="dim"); txt.append(hk + "\n", style="cyan")
    txt.append("\n  พิมพ์งานได้เลย  ·  ", style="dim")
    txt.append("/help", style="bold cyan")
    txt.append(" ดูคำสั่งทั้งหมด  ·  ", style="dim")
    txt.append("yousini serve", style="bold cyan")
    txt.append(" เปิดเว็บ UI  ·  ", style="dim")
    txt.append("yousini connect <url>", style="bold cyan")
    txt.append(" คุยข้ามเครื่อง", style="dim")
    console.print(Panel(txt, border_style="magenta", padding=(1, 2),
                        title="〔 พร้อมทำงาน 〕", subtitle="Yousini AI Agent"))


def _print_help():
    lines = [
        ("/help", "แสดงคำสั่งนี้"),
        ("/clear", "ล้างประวัติการสนทนา"),
        ("/history", "แสดงประวัติข้อความทั้งหมด"),
        ("/model <ชื่อ>", "เปลี่ยนโมเดล เช่น /model openai/gpt-oss-120b"),
        ("/cwd <โฟลเดอร์>", "เปลี่ยนโฟลเดอร์ทำงาน"),
        ("/approve on|off", "รัน shell อัตโนมัติโดยไม่ถาม"),
        ("/reload", "โหลด YOUSINI.md + skills ใหม่"),
        ("/skills", "แสดงสกิลที่โหลดอยู่"),
        ("/hooks", "แสดงสถานะ hooks"),
        ("/save [ชื่อ]", "บันทึกบทสนทนาลงดิสก์"),
        ("/load [ชื่อ]", "โหลดบทสนทนาจากดิสก์"),
        ("/sessions", "แสดงรายการ session ที่บันทึกไว้"),
        ("/jobs", "แสดงงาน shell background"),
        ("/checkpoint", "git commit จุดเก็บชั่วคราวเดี๋ยวนั้น"),
        ("/rollback", "ย้อนกลับไปจุด checkpoint ล่าสุด (git reset)"),
        ("/exit, /quit", "ออก"),
    ]
    servers = [
        ("yousini serve", "เปิดเว็บ UI + API (localhost)"),
        ("yousini serve --host 0.0.0.0 --token รหัส", "เปิดออนไลน์ (มี token)"),
        ("yousini serve --safe", "เปิดแบบอ่านอย่างเดียว (ปิด shell/เขียนไฟล์)"),
        ("yousini connect <url> [--token รหัส]", "คุยกับ Yousini อีกเครื่องผ่านเน็ต"),
        ("yousini mcp [--allow-exec]", "เปิดเป็น MCP server (stdio)"),
        ("yousini resume", "โหลด session ล่าสุดแล้วเข้าสู่แชท"),
    ]
    t = Text()
    t.append("  คำสั่งใน REPL\n", style="bold magenta")
    for cmd, desc in lines:
        t.append("   " + cmd, style="bold cyan")
        t.append("  —  " + desc + "\n", style="dim")
    t.append("\n  โหมดเชื่อมต่อ (รันจาก terminal)\n", style="bold magenta")
    for cmd, desc in servers:
        t.append("   " + cmd + "\n", style="bold cyan")
        t.append("      " + desc + "\n", style="dim")
    console.print(Panel(t, title="คำสั่ง Yousini", border_style="magenta", padding=(1, 2)))


def _print_history(agent: Agent):
    t = Text()
    for m in agent.messages:
        role = m["role"]
        c = m.get("content") or ""
        if role == "system":
            continue
        if role == "tool":
            c = f"[tool-result] {c[:200]}"
            style = "dim"
        elif role == "assistant":
            style = "green"
        else:
            style = "bold"
        t.append(f"[{role}] ", style="bold magenta")
        t.append(_truncate(c, 400) + "\n\n", style=style)
    console.print(Panel(t, title=f"ประวัติ ({len(agent.messages)} ข้อความ)", border_style="magenta"))


def _print_skills(agent: Agent):
    if not agent.skills:
        console.print(Text("ไม่มีสกิล (โฟลเดอร์ skills/ ว่างหรือไม่มี)", style="yellow"))
        return
    t = Text()
    for n, c in agent.skills:
        t.append(f"• {n}", style="bold cyan")
        t.append(f"  ({len(c)} ตัวอักษร)\n", style="dim")
    console.print(Panel(t, title=f"สกิลที่โหลด ({len(agent.skills)})", border_style="magenta"))


def _print_hooks(agent: Agent):
    d = agent.hooks.dir
    if not d:
        console.print(Text("ไม่พบโฟลเดอร์ hooks (วาง pre_tool.sh/post_tool.sh ใน ./.yousini/hooks หรือ ~/.yousini/hooks)", style="yellow"))
        return
    pre = agent.hooks._resolve_script("pre_tool")
    post = agent.hooks._resolve_script("post_tool")
    t = Text()
    t.append(f"โฟลเดอร์: {d}\n", style="dim")
    t.append("pre_tool:  ", style="bold"); t.append(str(pre[0]) if pre else "ไม่มี\n", style="green" if pre else "dim")
    t.append("post_tool: ", style="bold"); t.append(str(post[0]) if post else "ไม่มี\n", style="green" if post else "dim")
    console.print(Panel(t, title="Hooks", border_style="magenta"))


# ---------------------------------------------------------------------------
# โหมด SERVER: yousini serve  → เปิดเป็นบริการ (เว็บ UI + API สตรีม SSE)
# session ถูกบันทึกลงดิสก์ข้าม restart ด้วย
# ---------------------------------------------------------------------------
def _load_webui():
    here = Path(__file__).resolve().parent
    f = here / "webui.html"
    if f.exists():
        return f.read_text(encoding="utf-8")
    return "<h1>Yousini</h1><p>ไม่พบ webui.html ข้างไฟล์ yousini.py</p>"


def serve_main(host="127.0.0.1", port=8787, token="", safe=False,
               allow_shell=True, allow_write=True):
    import http.server
    import socketserver
    import threading

    web_ui = _load_webui()
    sessions = {}          # sid -> Agent
    locks = {}             # sid -> Lock (กันรันทับกันในเซสชันเดียว)
    reg_lock = threading.Lock()
    store = SessionStore(SESSION_DIR)

    def get_agent(sid):
        with reg_lock:
            if sid not in sessions:
                ag = Agent(interactive=False,
                           allow_shell=(allow_shell and not safe),
                           allow_write=(allow_write and not safe))
                # โหลด session เดิมจากดิสก์ (ถ้ามี) → บริบทข้าม restart
                saved = store.load(f"serve-{sid}")
                if saved:
                    try:
                        ag.messages = saved.get("messages", ag.messages)
                    except Exception:
                        pass
                sessions[sid] = ag
                locks[sid] = threading.Lock()
                ag.hooks.run_session_start()
            return sessions[sid], locks[sid]

    def persist(sid, agent):
        try:
            store.save(f"serve-{sid}", agent.messages,
                       {"model": agent.model, "cwd": agent.cwd})
        except Exception:
            pass

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass  # เงียบ (มี panel ของ rich อยู่แล้ว)

        def _auth_ok(self):
            if not token:
                return True
            hdr = self.headers.get("X-Yousini-Token") or ""
            if hdr == token:
                return True
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer ") and auth[7:] == token:
                return True
            q = urllib.parse.urlparse(self.path).query
            return urllib.parse.parse_qs(q).get("token", [""])[0] == token

        def _send(self, code, body, ctype="text/plain; charset=utf-8"):
            data = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._send(200, web_ui, "text/html; charset=utf-8")
            elif path == "/info":
                self._send(200, json.dumps({"model": MODEL, "name": "Yousini",
                           "safe": safe, "auth": bool(token)}),
                           "application/json; charset=utf-8")
            elif path == "/health":
                self._send(200, "ok")
            else:
                self._send(404, "not found")

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            if path != "/api/chat":
                return self._send(404, "not found")
            if not self._auth_ok():
                return self._send(401, json.dumps({"error": "unauthorized"}),
                                  "application/json; charset=utf-8")
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length) or "{}")
            except Exception:
                return self._send(400, "bad request")
            message = (payload.get("message") or "").strip()
            sid = payload.get("session") or "default"
            if not message:
                return self._send(400, "empty message")

            agent, lock = get_agent(sid)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            def emit(ev):
                self.wfile.write(("data: " + json.dumps(ev, ensure_ascii=False)
                                  + "\n\n").encode("utf-8"))
                self.wfile.flush()

            console.print(Text(f"↯ [{sid[:6]}] {message}", style="cyan"))
            with lock:
                try:
                    for ev in run_turn_events(agent, message):
                        emit(ev)
                    persist(sid, agent)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                except Exception as e:
                    try:
                        emit({"type": "error", "text": str(e)})
                    except Exception:
                        pass

    class ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    httpd = ThreadingServer((host, port), Handler)

    atexit.register(lambda: [s.hooks.run_session_stop() for s in sessions.values()])

    # ---- แบนเนอร์เซิร์ฟเวอร์อลังการ ----
    shown_host = "localhost" if host in ("127.0.0.1", "localhost") else host
    online = host == "0.0.0.0"
    t = Text()
    t.append("  Y O U S I N I   S E R V E R  \n\n", style="bold magenta")
    t.append("โหมด: ", style="dim")
    t.append("เครื่อง + ออนไลน์" if online else "ในเครื่อง (localhost)",
             style="cyan" if online else "green")
    t.append("\nเว็บ UI: ", style="dim")
    t.append(f"http://{shown_host}:{port}/\n", style="bold underline bright_cyan")
    t.append("API:    ", style="dim")
    t.append(f"POST http://{shown_host}:{port}/api/chat  (SSE)\n", style="dim")
    t.append("สมอง:   ", style="dim"); t.append(MODEL + "\n", style="bold")
    t.append("ความปลอดภัย: ", style="dim")
    if token:
        t.append("token เปิด ", style="green")
    else:
        t.append("ไม่มี token ", style="yellow")
    t.append("| shell " + ("ปิด" if safe or not allow_shell else "เปิด"), style="dim")
    t.append(" | เขียนไฟล์ " + ("ปิด" if safe or not allow_write else "เปิด"), style="dim")
    t.append(" | session ถาวร (บันทึกลงดิสก์)", style="dim")
    if online and not token:
        t.append("\n\nคำเตือน: เปิดออนไลน์โดยไม่มี token ใครก็สั่งเครื่องคุณได้! ใช้ --token",
                 style="bold red")
    t.append("\n\nกด Ctrl+C เพื่อหยุด", style="dim")
    console.print(Panel(t, border_style="magenta", padding=(1, 3), title="〔 SERVE 〕"))

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        console.print(Text("\nปิดเซิร์ฟเวอร์แล้ว", style="dim"))
        httpd.shutdown()


# ---------------------------------------------------------------------------
# โหมด CLIENT: yousini connect <url>  → คุยกับ Yousini อีกเครื่อง/บริการผ่านเครือข่าย
# ---------------------------------------------------------------------------
def connect_main(url, token=""):
    base = url.rstrip("/")
    if not base.startswith("http"):
        base = "http://" + base
    api = base + "/api/chat"
    sid = f"cli-{os.getpid()}"

    # เช็คการเชื่อมต่อ + ดึงชื่อโมเดล
    remote_model = "?"
    try:
        with urllib.request.urlopen(base + "/info", timeout=8) as r:
            remote_model = json.loads(r.read().decode()).get("model", "?")
    except Exception as e:
        console.print(Text(f"Error: เชื่อมต่อ {base} ไม่ได้: {e}", style="red"))
        return

    t = Text()
    t.append("  Y O U S I N I   —   REMOTE  \n\n", style="bold magenta")
    t.append("เชื่อมต่อไปยัง: ", style="dim"); t.append(base + "\n", style="bold cyan")
    t.append("สมองปลายทาง: ", style="dim"); t.append(remote_model + "\n", style="bold")
    t.append("พิมพ์คุยได้เลย  |  /exit เพื่อออก", style="dim")
    console.print(Panel(t, border_style="magenta", padding=(1, 3), title="〔 CONNECT 〕"))

    _setup_readline()
    while True:
        try:
            msg = input("❯ ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print(Text("\nจบการเชื่อมต่อ", style="dim")); break
        if not msg:
            continue
        if msg.lower() in ("/exit", "/quit"):
            break
        body = json.dumps({"message": msg, "session": sid}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Yousini-Token"] = token
        req = urllib.request.Request(api, data=body, headers=headers)
        acc = []
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                console.print(Text("─" * 3 + " Yousini (remote)", style="magenta"))
                buf = ""
                for raw in r:
                    buf += raw.decode("utf-8", errors="replace")
                    while "\n\n" in buf:
                        block, buf = buf.split("\n\n", 1)
                        line = next((l for l in block.split("\n")
                                     if l.startswith("data:")), None)
                        if not line:
                            continue
                        ev = json.loads(line[5:])
                        if ev["type"] == "token":
                            acc.append(ev["text"])
                            console.print(ev["text"], end="", style="green")
                        elif ev["type"] == "tool":
                            tag = " (hook ปฏิเสธ)" if ev.get("blocked") else ""
                            console.print(Text(f"\n⏺ {ev['name']}({ev['args']}){tag}",
                                          style="bold cyan"))
                        elif ev["type"] == "tool_result":
                            console.print(Text(f"⎿ {ev['result']}", style="dim"))
                        elif ev["type"] == "final":
                            if ev.get("text") and not acc:
                                console.print(Markdown(ev["text"]))
                        elif ev["type"] == "error":
                            console.print(Text(f"\nError: {ev['text']}", style="red"))
                console.print()
        except urllib.error.HTTPError as e:
            if e.code == 401:
                console.print(Text("Error: ต้องใช้ token — รันด้วย --token <TOKEN>",
                              style="red"))
            else:
                console.print(Text(f"Error: {e}", style="red"))
        except Exception as e:
            console.print(Text(f"Error: {e}", style="red"))


# ---------------------------------------------------------------------------
# โหมด MCP SERVER: yousini mcp  → ครอบ tools เป็น MCP server (stdio)
# ให้ agent ภายนอก (Claude Code, อื่นๆ) เรียก tools 9+ ตัวได้ผ่านโปรโตคอลมาตรฐาน
# ---------------------------------------------------------------------------
def _tools_to_mcp():
    out = []
    for t in TOOLS:
        f = t["function"]
        out.append({
            "name": f["name"],
            "description": f["description"],
            "inputSchema": f["parameters"],
        })
    return out


def mcp_main(allow_exec: bool = False):
    """MCP server แบบ stdio JSON-RPC 2.0 (newline-delimited)
    สำคัญ: stdout ต้องสะอาดสำหรับ JSON-RPC เท่านั้น จึงเปลี่ยน console ไปเขียน stderr"""
    global console
    console = Console(file=sys.stderr, force_terminal=False, width=120)
    agent = Agent(interactive=False,
                  allow_shell=allow_exec,
                  allow_write=allow_exec)
    if not allow_exec:
        agent.auto_run = False
    sys.stderr.write("Yousini MCP server started (stdio). allow_exec=%s\n" % allow_exec)
    sys.stderr.flush()

    def send(obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def call_tool(name, arguments):
        if name in ("shell", "write_file", "edit_file", "run_python",
                    "spawn_subagent") and not allow_exec:
            return {"content": [{"type": "text",
                    "text": f"Error: tool '{name}' ถูกปิดในโหมด MCP ปลอดภัย (รันด้วย --allow-exec)"}],
                    "isError": True}
        try:
            args = arguments or {}
            result = IMPL[name](args, agent)
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
        return {"content": [{"type": "text", "text": str(result)}]}

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        method = msg.get("method")
        mid = msg.get("id")
        params = msg.get("params", {}) or {}
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "Yousini", "version": "1.0"}}})
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": _tools_to_mcp()}})
        elif method == "tools/call":
            name = params.get("name")
            args = params.get("arguments", {})
            res = call_tool(name, args)
            send({"jsonrpc": "2.0", "id": mid, "result": res})
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        else:
            if mid is not None:
                send({"jsonrpc": "2.0", "id": mid,
                      "error": {"code": -32601, "message": f"method ไม่รู้จัก: {method}"}})


# ---------------------------------------------------------------------------
# Flags / helpers
# ---------------------------------------------------------------------------
def _parse_flags(argv):
    """แปลง --key value / --flag เป็น dict ง่ายๆ"""
    opts, i = {}, 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            key = a[2:]
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                opts[key] = argv[i + 1]; i += 2
            else:
                opts[key] = True; i += 1
        else:
            opts.setdefault("_", []).append(a); i += 1
    return opts


def _default_session_name(cwd: str) -> str:
    h = abs(hash(os.path.abspath(cwd)))
    return f"cli-{os.path.basename(os.path.abspath(cwd))}-{h % 100000}"


def _run_repl(agent: Agent):
    _setup_readline()
    _print_banner(agent)
    agent.hooks.run_session_start()
    atexit.register(lambda: agent.hooks.run_session_stop())
    store = SessionStore(SESSION_DIR)
    while True:
        try:
            user_input = input("❯ ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print(Text("\nจบการทำงาน", style="dim")); break
        if not user_input:
            continue
        low = user_input.lower()
        if low in ("/exit", "/quit"):
            console.print(Text("จบการทำงาน", style="dim")); break
        if low == "/help":
            _print_help(); continue
        if low == "/clear":
            agent.messages = [{"role": "system", "content": agent.system_prompt}]
            console.print(Text("ล้างประวัติแล้ว", style="yellow")); continue
        if low == "/history":
            _print_history(agent); continue
        if low == "/skills":
            _print_skills(agent); continue
        if low == "/hooks":
            _print_hooks(agent); continue
        if low == "/jobs":
            console.print(Panel(agent.jobs.summary(), title="Background jobs", border_style="magenta")); continue
        if low == "/reload":
            agent.refresh_context()
            console.print(Text(f"โหลดใหม่: บริบท={'เปิด' if agent.context_text.strip() else 'ปิด'} สกิล={len(agent.skills)} ตัว", style="green")); continue
        if low.startswith("/model "):
            agent.model = user_input[7:].strip()
            console.print(Text(f"โมเดล: {agent.model}", style="green")); continue
        if low.startswith("/cwd "):
            console.print(Text(agent.set_cwd(user_input[5:].strip()), style="yellow")); continue
        if low.startswith("/approve "):
            agent.auto_run = user_input[9:].strip().lower() in ("on", "1", "true")
            console.print(Text(f"รันอัตโนมัติ: {'เปิด' if agent.auto_run else 'ปิด (ถามก่อน)'}", style="yellow")); continue
        if low == "/checkpoint":
            r = agent.checkpoint("ด้วยมือ /checkpoint")
            console.print(Text(r or "(ไม่มีอะไรให้เก็บ หรือไม่ได้อยู่ใน git repo)", style="yellow")); continue
        if low == "/rollback":
            r = _rollback_to_last_checkpoint(agent)
            console.print(Text(r, style="yellow")); continue
        if low == "/sessions":
            rows = store.list()
            if not rows:
                console.print(Text("ยังไม่มี session ที่บันทึก", style="yellow")); continue
            t = Text()
            for s in rows:
                t.append(f"• {s['name']}", style="bold cyan")
                t.append(f"   ({s['turns']} ข้อความ, {s['saved_at']})\n", style="dim")
            console.print(Panel(t, title="Sessions ที่บันทึก", border_style="magenta")); continue
        if low.startswith("/save"):
            name = user_input[5:].strip() or _default_session_name(agent.cwd)
            p = store.save(name, agent.messages, {"model": agent.model, "cwd": agent.cwd})
            console.print(Text(f"บันทึก session '{name}' แล้ว:\n{p}", style="green")); continue
        if low.startswith("/load"):
            name = user_input[5:].strip() or store.last() or _default_session_name(agent.cwd)
            d = store.load(name)
            if not d:
                console.print(Text(f"ไม่พบ session '{name}'", style="red")); continue
            agent.messages = d.get("messages", agent.messages)
            if d.get("meta", {}).get("model"):
                agent.model = d["meta"]["model"]
            console.print(Text(f"โหลด session '{name}' ({len(agent.messages)} ข้อความ)", style="green")); continue
        chat_turn(agent, user_input)


def _rollback_to_last_checkpoint(agent: Agent) -> str:
    git_dir = Path(agent.cwd) / ".git"
    if not git_dir.is_dir():
        return "ไม่ได้อยู่ใน git repository"
    try:
        r = subprocess.run(["git", "log", "--oneline", "-F", "--grep",
                           "[Yousini checkpoint]", "-n", "1"],
                          cwd=agent.cwd, capture_output=True, text=True, timeout=20)
        line = r.stdout.strip().split("\n")[0]
        if not line:
            return "ไม่พบ checkpoint ใดๆ (ยังไม่เคย auto-commit)"
        sha = line.split(" ", 1)[0]
        # ย้าย working tree กลับไปยังจุด checkpoint
        res = subprocess.run(["git", "reset", "--hard", sha], cwd=agent.cwd,
                             capture_output=True, text=True, timeout=30)
        if res.returncode == 0:
            return f"rollback สำเร็จ → คืนสถานะที่ checkpoint {sha}"
        return f"rollback ไม่สำเร็จ: {res.stderr}"
    except Exception as e:
        return f"Error: {e}"


def resume_main():
    store = SessionStore(SESSION_DIR)
    name = store.last() or _default_session_name(os.getcwd())
    d = store.load(name)
    agent = Agent()
    if d:
        agent.messages = d.get("messages", agent.messages)
        if d.get("meta", {}).get("model"):
            agent.model = d["meta"]["model"]
        console.print(Text(f"โหลด session ล่าสุด '{name}' ({len(agent.messages)} ข้อความ)", style="green"))
    _run_repl(agent)


def main():
    argv = sys.argv[1:]

    # ---- subcommand: serve ----
    if argv and argv[0] == "serve":
        o = _parse_flags(argv[1:])
        serve_main(
            host=o.get("host", "127.0.0.1"),
            port=int(o.get("port", 8787)),
            token=o.get("token", "") if isinstance(o.get("token"), str) else "",
            safe=bool(o.get("safe")),
            allow_shell=not bool(o.get("no-shell")),
            allow_write=not bool(o.get("no-write")),
        )
        return

    # ---- subcommand: connect ----
    if argv and argv[0] == "connect":
        o = _parse_flags(argv[1:])
        targets = o.get("_", [])
        if not targets:
            console.print(Text("ใช้: yousini connect <url> [--token T]", style="red"))
            return
        connect_main(targets[0],
                     token=o.get("token", "") if isinstance(o.get("token"), str) else "")
        return

    # ---- subcommand: mcp ----
    if argv and argv[0] == "mcp":
        o = _parse_flags(argv[1:])
        mcp_main(allow_exec=bool(o.get("allow-exec")))
        return

    # ---- subcommand: resume ----
    if argv and argv[0] == "resume":
        resume_main()
        return

    agent = Agent()
    if argv:
        chat_turn(agent, " ".join(argv))
        return

    _run_repl(agent)


if __name__ == "__main__":
    main()
