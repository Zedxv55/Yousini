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
import threading
import subprocess
import difflib
import time
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
    bases = [os.getcwd(), Path(__file__).resolve().parent, Path.home()]
    for base in dict.fromkeys(str(Path(b)) for b in bases):
        try:
            with open(str(Path(base) / path), "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
        except FileNotFoundError:
            continue

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
from rich.table import Table

# ---- Interactive features (yousini_interactive.py) — command palette / typewriter / progress
from yousini_interactive import (
    command_palette as _ui_palette,
    typewriter_md as _ui_typewriter,
    ProgressBars as _ProgressBars,
)
# ---- TUI Design System (yousini_ui.py) — สี/กรอบ/สถานะมาตรฐานวัน 3.8.1 ----
from yousini_ui import (
    welcome_banner as _ui_welcome,
    user_bubble as _ui_user,
    tool_call as _ui_tool_call,
    tool_result as _ui_tool_result,
    status_hud as _ui_status,
    error_box as _ui_error,
    warn_box as _ui_warn,
    cmd_hints as _ui_cmd_hints,
    set_theme as _ui_set_theme,
    get_theme as _ui_theme,
    _width as _ui_width,
    ok_line as _ui_ok,
    cancel_line as _ui_cancel,
)

console = Console()

# ---- Monetization foundation (v3.0) — billing/sponsor/usage — ล้มเหลวได้โดยไม่พังตัวหลัก ----
_HAS_MONET = False
try:
    from yousini_billing import TIERS as BILL_TIERS
    from yousini_billing import activate as _billing_activate
    from yousini_billing import deactivate as _billing_deactivate
    from yousini_billing import tier_info as _billing_tier_info
    from yousini_billing import entitlement as _billing_entitlement
    from yousini_sponsor import sponsor_line as _sponsor_line
    from yousini_sponsor import sponsor_status as _sponsor_status
    from yousini_usage import is_enabled as _usage_enabled
    from yousini_usage import set_enabled as _usage_set_enabled
    from yousini_usage import record_tokens as _usage_record_tokens
    from yousini_usage import record_tool as _usage_record_tool
    from yousini_usage import record_turn as _usage_record_turn
    from yousini_usage import summary as _usage_summary
    from yousini_usage import summary_short as _usage_summary_short
    from yousini_usage import report as _usage_report
    from yousini_usage import reset as _usage_reset
    _HAS_MONET = True
except Exception:
    pass


def _record_usage_tokens(prompt, completion):
    if _HAS_MONET:
        try:
            if _usage_enabled():
                _usage_record_tokens(int(prompt or 0), int(completion or 0))
        except Exception:
            pass


def _record_usage_tool(name):
    if _HAS_MONET:
        try:
            if _usage_enabled():
                _usage_record_tool(name)
        except Exception:
            pass


def _record_usage_turn():
    if _HAS_MONET:
        try:
            if _usage_enabled():
                _usage_record_turn()
        except Exception:
            pass

# ---------------------------------------------------------------------------
# ดีไซน์: ความหมายสีแบบเสมอต้นเสมอปลาย (semantic colors)
# กฎสีตามที่ตกลง: "กำลังคิด/ประมวลผล = เทา (muted) · คำตอบ = เน้นสี"
# ---------------------------------------------------------------------------
C_THINK = "grey58"          # กำลังคิด / เตรียมเครื่องมือ / ผลลัพธ์เครื่องมือ → เทา
C_TOOL = "bold cyan"        # เรียกเครื่องมือ (การกระทำ)
C_TOOL_ARGS = "grey66"      # อาร์กิวเมนต์เครื่องมือ (เน้นน้อยลง)
C_RESULT = "grey66"         # ผลลัพธ์เครื่องมือ
C_ANSWER = "cyan"           # กรอบคำตอบ (เน้น)
C_OK = "green"              # สำเร็จ / ปลอดภัย
C_WARN = "yellow"           # คำเตือน / ต้องยืนยัน
C_ERR = "red"               # อันตราย / ผิดพลาด
C_ACCENT = "magenta"        # หัวข้อหลัก / แบนเนอร์
C_PROMPT = "bold yellow"    # ข้อความขออนุมัติ


def _think(text: str = "กำลังคิด…") -> Text:
    return Text("⠿ " + text, style=C_THINK)


def _answer_panel(md_text: str) -> Panel:
    """คงไว้เพื่อ backward compatibility — ใช้ _ui_answer_panel ใน chat_turn"""
    return Panel(Markdown(md_text), border_style=C_ANSWER,
                 title="คำตอบ Yousini", title_align="left", padding=(0, 1))

def _ui_answer_panel(md_text, model=None):
    """คำตอบ AI แบบ HUD — border cyan + subtitle model (ใช้ theme จาก yousini_ui)"""
    theme = _ui_theme()
    subtitle = Text(f" | {model}", style="dim") if model else None
    return Panel(
        Markdown(md_text),
        border_style=theme["answer"],
        title="[bold cyan]Yousini[/bold cyan]",
        subtitle=subtitle,
        padding=(0, 1),
        width=min(_ui_width(), 118),
    )


def _tool_line(name: str, args_shown) -> Text:
    t = Text()
    t.append("⏺ ", style=C_TOOL)
    t.append(name, style="bold cyan")
    shown = args_shown if isinstance(args_shown, str) else json.dumps(args_shown, ensure_ascii=False)
    t.append(f"({_truncate(shown, 200)})", style=C_TOOL_ARGS)
    return t


def _divider(label: str, style: str = C_ACCENT) -> Rule:
    return Rule(label, style=style)


def _status_footer(agent: "Agent"):
    """แถบสถานะด้านล่าง (สีเทา): โมเดล · รอบการสนทนา · โทเค็นสะสม"""
    msgs = max(0, len(agent.messages) - 1)
    u = agent.usage
    if u["prompt_tokens"] or u["completion_tokens"]:
        tok = f"tok {u['prompt_tokens'] + u['completion_tokens']:,} (in {u['prompt_tokens']:,}/out {u['completion_tokens']:,})"
    else:
        tok = "tok —"
    t = Text()
    t.append(f"  {agent.model}", style=C_THINK)
    t.append(f"   ·   ข้อความ {msgs}   ·   {tok}", style=C_THINK)
    console.print(t)


# ---- Config: รองรับทุก OpenAI-compatible API ----
# อ่าน YOUSINI_* ก่อน ถ้าไม่มีตกไปใช้ ZELAX_* แล้ว GROQ_* (เข้ากันได้กับของเดิม)
API_KEY = (os.getenv("YOUSINI_API_KEY") or os.getenv("ZELAX_API_KEY")
           or os.getenv("GROQ_API_KEY") or os.getenv("MISTRAL_API_KEY", ""))
BASE_URL = (os.getenv("YOUSINI_BASE_URL") or os.getenv("ZELAX_BASE_URL")
            or os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"))
MODEL = (os.getenv("YOUSINI_MODEL") or os.getenv("ZELAX_MODEL")
         or os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"))

AUTO_RUN = os.getenv("AUTO_RUN", "0") == "1"
CONFIRM_FILES = os.getenv("CONFIRM_FILES", "1") == "1"
SHELL_TIMEOUT = int(os.getenv("SHELL_TIMEOUT", "60"))

# version ของแอป — ใช้กับ /info, --version และ web UI (single source of truth)
APP_VERSION = "3.9.0"

# ---- Config ฟีเจอร์ใหม่ ----
# ชื่อไฟล์บริบทโปรเจกต์ (เหมือน CLAUDE.md)
CONTEXT_FILE = os.getenv("YOUSINI_CONTEXT", "YOUSINI.md")
# โฟลเดอร์สกิล (relative ต่อ cwd)
SKILLS_DIR = os.getenv("YOUSINI_SKILLS", "skills")
# สกิลระดับเครื่อง (ติดตั้งผ่าน `yousini skill install`) — โหลดร่วมกับ ./skills ของโปรเจกต์
def _profile_root() -> Path:
    """รากของ data dir — รองรับโพรไฟล์ (YOUSINI_PROFILE env หรือ ~/.yousini/.active_profile)"""
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


GLOBAL_SKILLS_DIR = Path(os.getenv("YOUSINI_GLOBAL_SKILLS", str(_profile_root() / "skills")))
# โฟลเดอร์ hooks: ถ้าไม่ระบุ จะหา ./.yousini/hooks แล้ว ~/.yousini/hooks
HOOKS_DIR = os.getenv("YOUSINI_HOOKS", "")
# เปิด/ปิด auto-checkpoint (git commit ก่อนแก้ไฟล์)
CHECKPOINT = os.getenv("YOUSINI_CHECKPOINT", "1") == "1"
# ที่เก็บ session
SESSION_DIR = Path(os.getenv("YOUSINI_SESSIONS", str(_profile_root() / "sessions")))

# Web search provider (ทางเลือกเสริม: ใช้ API key ของผู้ให้บริการค้นหาจริง แทน scraping)
# ตั้ง YOUSINI_SEARCH_PROVIDER=brave|serpapi|tavily แล้วใส่ key ผ่านตัวแปรที่สอดคล้อง
SEARCH_PROVIDER = (os.getenv("YOUSINI_SEARCH_PROVIDER") or "").lower()
SEARCH_API_KEY = (os.getenv("YOUSINI_SEARCH_API_KEY") or os.getenv("BRAVE_API_KEY")
                  or os.getenv("SERPAPI_KEY") or os.getenv("TAVILY_API_KEY", ""))
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")

if not API_KEY:
    console.print(Text("Error: ไม่พบ API Key โปรดคัดลอก .env.example เป็น .env แล้วใส่ YOUSINI_API_KEY", style="red"))
    sys.exit(1)

# ---- Provider Fallback Chain (Phase 5 — เทียบเท่า credential pool ของ Hermes) ----
# ลำดับ: ตัวหลัก (env) → YOUSINI_FALLBACK_PROVIDERS (JSON) → config.json["providers"]
# เมื่อเจอ auth/rate/network/5xx → สลับไป provider ถัดไปอัตโนมัติ


def _load_providers():
    """รายการ provider ทั้งหมด (base_url, api_key) เรียงตามลำดับการลอง"""
    provs = [{"base_url": BASE_URL, "api_key": API_KEY}]
    raw = os.getenv("YOUSINI_FALLBACK_PROVIDERS", "")
    if raw:
        try:
            for p in json.loads(raw):
                if isinstance(p, dict) and p.get("api_key") and p.get("base_url"):
                    provs.append(p)
        except Exception:
            pass
    cfg_file = globals().get("CONFIG_FILE")  # นิยามทีหลังบรรทัด 2082 — กัน NameError ตอน import
    if cfg_file is not None:
        try:
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            prov_cfg = cfg.get("providers", [])
            if isinstance(prov_cfg, dict):  # รูปแบบ login: {ชื่อ: {base_url, api_key, model}}
                prov_cfg = [_fix_provider(p) for p in prov_cfg.values()]
            for p in prov_cfg:
                if isinstance(p, dict) and p.get("api_key") and p.get("base_url"):
                    provs.append(p)
        except Exception:
            pass
    # ตัดตัวซ้ำ (key+url เดียวกัน)
    seen, out = set(), []
    for p in provs:
        k = (p["base_url"], p["api_key"])
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out


def _fix_provider(p: dict) -> dict:
    """เติมค่าเริ่มต้นให้ provider จาก config.json (ฐาน URL ตามผู้ให้บริการ)"""
    if p.get("base_url"):
        return p
    url_map = {"mistral": "https://api.mistral.ai/v1", "groq": "https://api.groq.com/openai/v1",
               "openrouter": "https://openrouter.ai/api/v1", "deepseek": "https://api.deepseek.com/v1",
               "openai": "https://api.openai.com/v1", "gemini": "https://generativelanguage.googleapis.com/v1beta/openai"}
    name = str(p.get("name", "")).lower()
    for k, v in url_map.items():
        if k in name:
            p["base_url"] = v
            break
    return p


def _retryable(e) -> bool:
    """error ที่ควรลอง provider ถัดไป (auth/โค้ต้า/network/5xx)"""
    from openai import (AuthenticationError, RateLimitError, APIConnectionError,
                        InternalServerError, Timeout)
    if isinstance(e, (AuthenticationError, RateLimitError, APIConnectionError,
                      InternalServerError, Timeout)):
        return True
    try:
        from openai import APIStatusError
        if isinstance(e, APIStatusError) and e.status_code >= 500:
            return True
    except Exception:
        pass
    return False


class _Completions:
    def __init__(self, owner):
        self.owner = owner

    def create(self, *a, **kw):
        return self.owner._create(*a, **kw)


class _Chat:
    def __init__(self, owner):
        self.completions = _Completions(owner)


class _FallbackClient:
    """proxy แทน OpenAI client — ลอง provider ตามลำดับ สลับอัตโนมัติเมื่อ error"""

    def __init__(self, providers=None):
        self.providers = providers if providers is not None else _load_providers()
        self.current = 0
        self.chat = _Chat(self)
        self._client = self._build(0)

    def _build(self, i):
        p = self.providers[i]
        return OpenAI(api_key=p["api_key"], base_url=p["base_url"])

    def _create(self, *args, **kwargs):
        attempts = 0
        last_e = None
        while True:
            try:
                return self._client.chat.completions.create(*args, **kwargs)
            except Exception as e:
                last_e = e
                if not _retryable(e):
                    raise
                attempts += 1
                if attempts >= len(self.providers):
                    break
                self.current = (self.current + 1) % len(self.providers)
                self._client = self._build(self.current)
                console.print(Text(
                    f"⚠️ Provider #{self.current} ({self.providers[self.current]['base_url']}) "
                    f"ล่ม: {e.__class__.__name__} → สลับอัตโนมัติ", style="yellow"))
        raise last_e


client = _FallbackClient()

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
- memory     จัดการความจำระยะยาว (จำข้าม session): action=add/remove/replace/list, target=user/agent — บันทึกความชอบ/ข้อเท็จจริง/บทเรียนที่ควรจำ
- skill_create / skill_patch สร้าง/แก้ไขสกิล (ความรู้/ขั้นตอนที่ใช้ซ้ำ) — หลังจากทำงานยากสำเร็จ
- search_sessions ค้นหาย้อนหลังใน session ก่อนหน้า (เมื่อผู้ใช้ถามว่าเคยทำ/คุยเรื่องอะไรไว้)
- symbols ค้นหาโครงสร้างโค้ดด้วย AST (symbol index): ก่อนแก้โค้ดให้หา def/refs ของฟังก์ชันที่เกี่ยวข้องก่อนเสมอ
- cron          จัดการงานอัตโนมัติตามเวลา (list/add/remove/pause/resume)
- run_python รันโค้ด Python บนเครื่อง (คำนวณ, ประมวลผลข้อมูล, ทดสอบ snippet) คืน stdout/stderr
- spawn_subagent รันเอเจนต์ย่อยแยกบริบทเพื่อทำงานเฉพาะส่วน (วิเคราะห์/ค้นหา/สรุป) คืนสรุปสั้นๆ ไม่ทำให้บริบทหลักบวม
- manage_todos จัดการรายการสิ่งที่ต้องทำ (plan/ความคืบหน้า): action=add/update/complete/start/delete/list — ใช้แสดงแผนงานให้ผู้ใช้เห็นชัดเจนก่อนลงมือ

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
10. เมื่อผู้ใช้บอกความชอบ/ข้อเท็จจริง/ข้อมูลเกี่ยวกับเครื่อง ให้บันทึกความจำระยะยาวด้วย memory(target=user|agent) ทันที — ห้ามบันทึกความคืบหน้างานชั่วคราว
11. เมื่องานยากสำเร็จ (หลายขั้นตอน, แก้บั๊กที่ซับซ้อน, เจอทางลัด) ให้เสนอผู้ใช้ว่าจะบันทึกเป็น skill ไหม และใช้ skill_create ทันทีถ้าผู้ใช้ตกลง; ถ้าพบว่าสกิลล้าสมัย ให้ skill_patch แก้ไขทันที
12. หากรัน shell ที่ใช้เวลานาน ให้ใช้ run_in_background=true แล้ว poll ผลด้วย read_job แทนการรอ
13. ห้ามเรียกใช้ชื่อเครื่องมือที่ไม่ได้ระบุไว้ข้างต้น (โดยเฉพาะ repo_browser, python, web_browser) เพราะไม่มีในระบบ และจะทำให้เกิดข้อผิดพลาดร้ายแรง ให้ใช้เฉพาะเครื่องมือที่ให้มาครั้งละตัว"""


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


def _parse_skill(text: str, fallback_name: str):
    """แยก frontmatter YAML แบบง่าย (name/description/version) ออกจากเนื้อหา
    คืน (name, description, body) — ไม่มี frontmatter → ใช้ fallback_name + บรรทัดแรก"""
    name, desc, body = fallback_name, "", text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            fm = text[3:end]
            body = text[end + 4:].lstrip("\n")
            for ln in fm.splitlines():
                if ":" in ln:
                    k, _, v = ln.partition(":")
                    v = v.strip().strip('"').strip("'")
                    if k.strip() == "name" and v:
                        name = v
                    elif k.strip() == "description" and v:
                        desc = v
    if not desc:
        desc = _skill_desc(body)
    return name, desc, body


def load_skill_index(cwd: str, skills_dir: str = SKILLS_DIR):
    """คืนรายการสกิลแบบย่อ (name, desc, source) จาก ./skills (📁โปรเจกต์) + ~/.yousini/skills (💾เครื่อง)
    โดยไม่โหลดเนื้อหาเต็ม — ป้องกัน context bloat; สกิลโปรเจกต์ชนะสกิลเครื่องถ้าชื่อซ้ำ"""
    seen = set()
    out = []
    for source, d in (("project", Path(cwd) / skills_dir), ("global", GLOBAL_SKILLS_DIR)):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            name, desc, _ = _parse_skill(text, f.stem)
            if name in seen:
                continue
            seen.add(name)
            out.append((name, desc, source))
    return out


def load_skill_full(cwd: str, name: str, skills_dir: str = SKILLS_DIR):
    """โหลดเนื้อหาเต็มของสกิล — หาในโปรเจกต์ก่อน แล้วค่อยหาในเครื่อง"""
    for d in (Path(cwd) / skills_dir, GLOBAL_SKILLS_DIR):
        p = d / f"{name}.md"
        if p.is_file():
            try:
                return p.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                return f"Error: อ่านสกิลไม่ได้: {e}"
    avail = ", ".join(sorted(x.stem for x in (Path(cwd) / skills_dir).glob("*.md"))) if (Path(cwd) / skills_dir).is_dir() else ""
    return f"Error: ไม่พบสกิล '{name}' (มี: {avail})"


def build_system_prompt(context_text: str, skills, memory_text: str = "", git_text: str = "") -> str:
    parts = [BASE_SYSTEM_PROMPT]
    if memory_text.strip():
        parts.append("=== ความจำระยะยาว (จำข้าม session) ===\n"
                     "ข้อมูลด้านล่างคือความจำที่บันทึกไว้ — ใช้เป็นแนวทางเสมอ:\n"
                     f"{memory_text}")
    if git_text.strip():
        parts.append(git_text)
    if context_text.strip():
        parts.append("=== บริบทโปรเจกต์ (YOUSINI.md) ===\n" + context_text)
    if skills:
        rows = []
        for item in skills:
            n, d = item[0], item[1]
            src = item[2] if len(item) > 2 else ""
            rows.append(f"- {n}: {d}" + (" 📁" if src == "project" else " 💾" if src == "global" else ""))
        idx = "\n".join(rows)
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
        # บน Unix ใช้ bash/sh (.sh) — hook ที่เป็น cross-platform (.bat ครอบ dw
        # ที่ exit 0 ได้) ควรตรวจพบและรันได้ทั้งสองฝั่ง ถ้า interpreter ตรงตามไม่ได้
        # จะ fall back ให้ shell ที่มีในเครื่องรันฟายล์นั้น (fail-open)
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
        # Cross-platform fallback: มีฟายล์ hook อยู่จริง แต่ interpreter ใน
        # order (เช่น cmd บน Linux) ไม่มี — ใช้ shell ที่มีจริงรันแทนได้เสมอ
        for ext in (".bat", ".cmd", ".sh"):
            p = self.dir / (base + ext)
            if p.is_file():
                if shutil.which("bash"):
                    return (p, ["bash"])
                if shutil.which("sh"):
                    return (p, ["sh"])
                if shutil.which("cmd"):
                    return (p, ["cmd", "/c"])
                return None
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
        # Phase 3: index ลง SQLite+FTS5 เพื่อค้นหาย้อนหลัง (/search, tool search_sessions)
        try:
            from yousini_sessions_db import SessionSearch
            SessionSearch(self.base / "search.db").index_messages(
                name, messages, data["saved_at"], meta)
        except Exception:
            pass
        return str(self._path(name))

    def search(self, query: str, limit: int = 10):
        """ค้นหาย้อนหลังในทุก session (FTS5 + LIKE fallback ภาษาไทย) — คืน list ของ dict"""
        try:
            from yousini_sessions_db import SessionSearch
            return SessionSearch(self.base / "search.db").search(query, limit=limit)
        except Exception:
            return []

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
        # ความจำระยะยาว (Phase 1 — เทียบเท่า Hermes memory)
        try:
            from yousini_memory import MemoryManager
            self.memory = MemoryManager()
        except Exception:
            self.memory = None
        self._git_block = None   # ประวัติ git (คำนวณครั้งเดียวต่อ session)
        self.hooks = Hooks(hooks_dir, self.cwd)
        self.system_prompt = build_system_prompt(
            self.context_text, self.skills,
            memory_text=self.memory.inject_text() if self.memory else "",
            git_text=self._ensure_git_block())
        self.messages = [{"role": "system", "content": self.system_prompt}]
        # สถิติโทเค็น (best-effort: อ่านจาก usage ของ API ถ้ามี)
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}
        # รายการสิ่งที่ต้องทำ (todo) สำหรับแสดงแผน/ความคืบหน้าให้ผู้ใช้
        self.todos = []
        self._todo_seq = 0
        # Quiet mode: ซ่อน output ของ tool call/result — เหลือแค่คำตอบสุดท้าย
        self.quiet_mode = False

    def refresh_context(self):
        """โหลดบริบท/สกิล/ความจำใหม่ (เรียกหลัง set_cwd หรือ /reload)"""
        self.context_text = load_context_text(self.cwd, self.context_file)
        self.skills = load_skill_index(self.cwd, self.skills_dir)
        self.system_prompt = build_system_prompt(
            self.context_text, self.skills,
            memory_text=self.memory.inject_text() if self.memory else "",
            git_text=self._ensure_git_block())
        # แทนที่ system message แรก
        if self.messages and self.messages[0]["role"] == "system":
            self.messages[0]["content"] = self.system_prompt
        else:
            self.messages.insert(0, {"role": "system", "content": self.system_prompt})

    def begin_turn(self):
        self._did_checkpoint = False

    def _add_usage(self, usage):
        """สะสมโทเค็นจาก usage ของ API (free model บางตัวอาจไม่ส่งมา)"""
        try:
            self.usage["prompt_tokens"] += int(getattr(usage, "prompt_tokens", 0) or 0)
            self.usage["completion_tokens"] += int(getattr(usage, "completion_tokens", 0) or 0)
        except Exception:
            pass
        _record_usage_tokens(getattr(usage, "prompt_tokens", 0) or 0,
                             getattr(usage, "completion_tokens", 0) or 0)

    def compact(self, keep_last: int = 6) -> str:
        """ยุบบริบทเก่าๆ เป็นสรุปสั้นๆ เพื่อลดโทเค็น (ช่วยโมเดลฟรีเมื่อสนทนายาว)
        เก็บ system message + ไม่เกิน keep_last ข้อความล่าสุด แล้วสรุปส่วนที่เหลือ
        แบบ chunked (ทีละกลุ่ม ~6 ข้อความ/2500 ตัวอักษร) — ลดโทเค็นได้มากกว่าแบบรวมก้อนเดียว"""
        if len(self.messages) <= keep_last + 1:
            return "(ไม่ต้องยุบ บริบทยังสั้นอยู่)"
        sys0 = self.messages[0]
        rest = self.messages[1:]
        to_sum = rest[:-keep_last] if keep_last else rest
        recent = rest[-keep_last:] if keep_last else []
        # แบ่งเป็น chunk ตามจำนวนข้อความ/ขนาด เพื่อไม่ให้เกิน context ในรอบเดียว
        chunks, cur, cur_len = [], [], 0
        for m in to_sum:
            c = _truncate(m.get("content") or "", 1500)
            size = len(c)
            if cur and (len(cur) >= 6 or cur_len + size > 2500):
                chunks.append(cur)
                cur, cur_len = [], 0
            cur.append((m.get("role", "?"), c))
            cur_len += size
        if cur:
            chunks.append(cur)
        summaries = []
        for i, chunk in enumerate(chunks, 1):
            blob = "\n\n".join(f"[{role}] {c}" for role, c in chunk)
            prompt = (f"สรุปส่วนที่ {i}/{len(chunks)} ของบทสนทนาด้านล่างให้กระชับที่สุด "
                      "(เก็บเฉพาะข้อมูลสำคัญ: ทำอะไรไปแล้ว ผลลัพธ์ และคำตัดสิน) "
                      "ตอบเป็นภาษาไทย ย่อหน้าเดียว ไม่ต้องไหว้:")
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": prompt},
                              {"role": "user", "content": blob}],
                    temperature=0.2, stream=False)
                s = (resp.choices[0].message.content or "").strip()
                if s:
                    summaries.append(s)
            except Exception as e:
                return f"(ยุบบริบทไม่ได้: {e})"
        if not summaries:
            return "(ไม่สามารถสรุปบริบทได้)"
        merged = ("\n".join(f"[ส่วน {i}] {s}" for i, s in enumerate(summaries, 1))
                  if len(summaries) > 1 else summaries[0])
        self.messages = [
            sys0,
            {"role": "user", "content": "[บริบทสรุปจากการสนทนาก่อนหน้า]\n" + merged},
            {"role": "assistant", "content": "รับทราบสรุปบริบทแล้ว"},
        ] + recent
        return f"ยุบบริบทเหลือ {len(self.messages)} ข้อความ (สรุป {len(summaries)} ส่วน)"

    # ---- รายการสิ่งที่ต้องทำ (todo) — แสดงแผน/ความคืบหน้าให้ผู้ใช้เห็นชัดเจน ----
    def manage_todos(self, action: str, content: str = "", todo_id=None, status: str = "") -> str:
        act = (action or "").lower()
        if act in ("add", "สร้าง", "เพิ่ม"):
            self._todo_seq += 1
            self.todos.append({"id": self._todo_seq, "content": content,
                               "status": "pending"})
            return f"เพิ่ม todo #{self._todo_seq}: {content}"
        if act in ("update", "แก้ไข", "set"):
            for t in self.todos:
                if str(t["id"]) == str(todo_id):
                    t["content"] = content or t["content"]
                    return f"แก้ไข todo #{t['id']}: {t['content']}"
            return f"Error: ไม่พบ todo #{todo_id}"
        if act in ("complete", "done", "เสร็จ", "สำเร็จ"):
            for t in self.todos:
                if str(t["id"]) == str(todo_id):
                    t["status"] = "completed"
                    return f"ทำเครื่องหมายเสร็จสิ้น todo #{t['id']}"
            return f"Error: ไม่พบ todo #{todo_id}"
        if act in ("start", "in_progress", "กำลังทำ", "เริ่ม"):
            for t in self.todos:
                if str(t["id"]) == str(todo_id):
                    t["status"] = "in_progress"
                    return f"เริ่มทำ todo #{t['id']}"
            return f"Error: ไม่พบ todo #{todo_id}"
        if act in ("delete", "ลบ", "remove"):
            before = len(self.todos)
            self.todos = [t for t in self.todos if str(t["id"]) != str(todo_id)]
            return f"ลบ todo #{todo_id}" if len(self.todos) < before else f"Error: ไม่พบ todo #{todo_id}"
        if act in ("list", "แสดง", "ดู"):
            return self._todos_text()
        return ("Error: action ต้องเป็น add/update/complete/start/delete/list")

    def _todos_text(self) -> str:
        if not self.todos:
            return "(ยังไม่มีรายการสิ่งที่ต้องทำ)"
        sym = {"pending": "○", "in_progress": "◐", "completed": "●"}
        return "\n".join(f"{sym.get(t['status'],'○')} #{t['id']} [{t['status']}] {t['content']}"
                         for t in self.todos)

    def _print_todos(self):
        console.print(Panel(self._todos_text(), title="📋 สิ่งที่ต้องทำ",
                            border_style=C_WARN, padding=(0, 1)))

    # ---- trimming: ตัดที่ user-boundary เท่านั้น ไม่ให้เหลือ tool-result ลอยๆ ----
    # ---- Context window management ----
    # Token budget before auto-compact triggers (rough: 1 token ≈ 4 chars)
    MAX_CONTEXT_TOKENS = int(os.getenv("YOUSINI_MAX_TOKENS", "12000"))
    AUTO_COMPACT_RATIO = float(os.getenv("YOUSINI_COMPACT_RATIO", "0.8"))

    def _estimate_tokens(self, messages: list = None) -> int:
        """Best-effort token estimate (4 chars ≈ 1 token).
        Good enough for auto-compact decisions without pulling in tiktoken."""
        msgs = messages or self.messages
        total = 0
        for m in msgs:
            c = m.get("content", "")
            if isinstance(c, list):
                # multimodal — count only text parts
                for part in c:
                    if isinstance(part, dict):
                        total += len(part.get("text", ""))
                    else:
                        total += len(str(part))
            else:
                total += len(str(c))
        return max(1, total // 4)

    def _trim(self, max_msgs=40, max_tokens=None):
        """Token-aware trimming: first try compacting by token budget,
        then fall back to naive max-msgs truncation."""
        if max_tokens is None:
            max_tokens = self.MAX_CONTEXT_TOKENS
        # Check if we already need compacting
        current_tokens = self._estimate_tokens()
        threshold = int(max_tokens * self.AUTO_COMPACT_RATIO)
        if current_tokens > threshold:
            self.compact()
            return
        if len(self.messages) <= max_msgs:
            return
        # Naive fallback: keep system + latest user messages
        sys0 = self.messages[0]
        conv = self.messages[1:]
        cuts = [i for i, m in enumerate(conv) if m["role"] == "user"]
        while len(conv) > max_msgs - 1 and len(cuts) > 1:
            drop = cuts[1]
            conv = conv[drop:]
            cuts = [i - drop for i in cuts[1:]]
        self.messages = [sys0] + conv

    def _auto_compact(self) -> bool:
        """Auto-compact if token usage exceeds threshold. Returns True if compacted."""
        current = self._estimate_tokens()
        threshold = int(self.MAX_CONTEXT_TOKENS * self.AUTO_COMPACT_RATIO)
        if current > threshold and len(self.messages) > 3:
            self.compact()
            console.print(Text(
                f"⚡ ยุบคอนเทกซต์อัตโนมัติ (โทเค็น ~{current} → ต่ำกว่า {threshold})",
                style=C_WARN))
            return True
        return False

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

        # Check if command is in allow-list (no confirmation needed)
        allowed_by_policy = is_shell_allowed(command)

        dangerous = is_dangerous(command)
        if not self.interactive:
            # โหมด headless/server: ห้ามคำสั่งอันตรายเด็ดขาด นอกจาก auto_run
            if dangerous and not self.auto_run and not allowed_by_policy:
                return "Error: คำสั่งอันตรายถูกบล็อกในโหมด headless (ตั้ง AUTO_RUN=1 เพื่ออนุญาต)"
        elif not self.auto_run and not allowed_by_policy or dangerous:
            border = C_ERR if dangerous else C_WARN
            title = "⚠ คำสั่งเสี่ยงสูง — ยืนยันก่อนรัน" if dangerous else "ยืนยันรัน shell"
            # If allowed by policy, show different message
            if allowed_by_policy and not dangerous:
                title = "✓ คำสั่งได้รับอนุญาตจาก policy — ยืนยันการรัน"
                border = C_OK
            console.print(Panel(Text(command, style="bold white"), title=title,
                                border_style=border, padding=(0, 1)))
            ans = _safe_input(f"  [y] รัน   [N] ยกเลิก   [e] แก้ไข  ? ").strip().lower()
            if ans in ("e", "edit"):
                return self.shell(_safe_input("  พิมพ์คำสั่งใหม่: ").strip(), timeout, run_in_background)
            if ans not in ("y", "yes", "1"):
                console.print(Text("↩ ยกเลิกโดยผู้ใช้", style=C_WARN))
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
            ans = _safe_input(f"   เขียนทับไฟล์ {path}?  [y] ใช่   [N] ไม่เขียน  ? ").strip().lower()
            if ans not in ("y", "yes", "1"):
                console.print(Text("↩ ยกเลิกการเขียนโดยผู้ใช้", style=C_WARN))
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
            ans = _safe_input(f"   แก้ไฟล์ {path}?  [y] ใช่   [N] ไม่แก้  ? ").strip().lower()
            if ans not in ("y", "yes", "1"):
                console.print(Text("↩ ยกเลิกการแก้โดยผู้ใช้", style=C_WARN))
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
        """ค้นหาข้อมูลบนอินเทอร์เน็ต
        ลำดับความสำคัญ:
        1. YOUSINI_SEARCH_PROVIDER + YOUSINI_SEARCH_API_KEY (ถ้าตั้งไว้)
        2. Brave API (ถ้ามี BRAVE_API_KEY) — default ที่เชื่อถือได้
        3. Scraping fallback (DuckDuckGo/Bing) — ใช้เมื่อไม่มี API key"""
        if SEARCH_PROVIDER and SEARCH_API_KEY:
            return web_search_api(query, max_results, SEARCH_PROVIDER, SEARCH_API_KEY)
        if BRAVE_API_KEY:
            return web_search_api(query, max_results, "brave", BRAVE_API_KEY)
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

    def memory_tool(self, action: str, target: str, content: str = "", old_text: str = "") -> str:
        """จัดการความจำระยะยาว (Phase 1 — เทียบเท่า Hermes memory)"""
        if not self.memory:
            return "memory ไม่พร้อมใช้งาน (ติดตั้ง yousini_memory.py ไม่สำเร็จ)"
        return self.memory.act(action, target, content=content, old_text=old_text)

    def _skill_target_dir(self) -> Path:
        """ตำแหน่งสร้างสกิล: ./skills ของโปรเจกต์ถ้ามี dir อยู่แล้ว มิฉะนั้น ~/.yousini/skills"""
        proj = Path(self.cwd) / self.skills_dir
        return proj if proj.is_dir() else GLOBAL_SKILLS_DIR

    def skill_create(self, name: str, description: str, content: str) -> str:
        """สร้างสกิลใหม่ (มี frontmatter name/description) — ใช้เมื่อทำงานยากสำเร็จและควรจำวิธี"""
        target_dir = self._skill_target_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        p = target_dir / f"{name}.md"
        if p.exists():
            return f"มีสกิล '{name}' อยู่แล้ว — ใช้ skill_patch เพื่อแก้ไข"
        fm = f"---\nname: {name}\ndescription: {description}\n---\n"
        p.write_text(fm + content.lstrip("\n"), encoding="utf-8")
        self.refresh_context()
        return f"สร้างสกิล '{name}' แล้ว: {p}"

    def skill_patch(self, name: str, old_string: str, new_string: str) -> str:
        """แก้เนื้อหาสกิล (search & replace)"""
        for d in (Path(self.cwd) / self.skills_dir, GLOBAL_SKILLS_DIR):
            p = d / f"{name}.md"
            if p.is_file():
                text = p.read_text(encoding="utf-8")
                if old_string not in text:
                    return f"ไม่พบ '{old_string}' ในสกิล '{name}'"
                p.write_text(text.replace(old_string, new_string, 1), encoding="utf-8")
                self.refresh_context()
                return f"แก้สกิล '{name}' แล้ว"
        return f"ไม่พบสกิล '{name}'"

    def cron_tool(self, action: str, schedule: str = "", prompt: str = "", job_id: int = None) -> str:
        """จัดการงานอัตโนมัติตามเวลา (เทียบเท่า Hermes cronjob): list/add/remove/pause/resume"""
        from yousini_cron import JobStore, parse_schedule
        store = JobStore()
        if action == "list":
            rows = store.list()
            if not rows:
                return "ยังไม่มีงาน cron"
            return "\n".join(
                f"#{j['id']} {'▶' if j['enabled'] else '⏸'} {j['name']} [{j['schedule']}] "
                f"รันล่าสุด {j['last_run'] or '—'} → {j['prompt'][:60]}" for j in rows)
        if action == "add":
            if parse_schedule(schedule)[0] == "invalid":
                return f"schedule ไม่ถูกต้อง: {schedule} (ลอง 30m, 0 9 * * *, 2026-08-11T10:00:00)"
            if not prompt:
                return "ต้องใส่ prompt"
            j = store.add(prompt[:30], schedule, prompt, cwd=self.cwd)
            return f"เพิ่มงาน #{j['id']} '{j['name']}' แล้ว (ทุก {schedule})"
        if action == "remove" and job_id:
            if store.get(job_id):
                store.remove(job_id)
                return f"ลบงาน #{job_id} แล้ว"
            return f"ไม่พบงาน #{job_id}"
        if action in ("pause", "resume") and job_id:
            j = store.set_enabled(job_id, action == "resume")
            if j:
                return f"งาน #{job_id} {'▶ resume แล้ว' if action == 'resume' else '⏸ pause แล้ว'}"
            return f"ไม่พบงาน #{job_id}"
        return "action ต้องเป็น list/add/remove/pause/resume (add ต้องมี schedule + prompt)"

    def symbols_tool(self, action: str = "summary", name: str = "", query: str = "") -> str:
        """ค้นหาโครงสร้างโค้ด — AST symbol index (go-to-definition, refs)"""
        from yousini_symbols import SymbolIndex
        try:
            idx = SymbolIndex(self.cwd)
        except Exception as e:
            return f"ไม่สามารถ index โปรเจกต์ได้: {e}"
        if action == "summary":
            s = idx.summary()
            kinds = " | ".join(f"{k}: {v}" for k, v in s["kinds"].items())
            return f"Symbol index: {s['total']} สัญลักษณ์ ใน {s['files']} ไฟล์\n{kinds}"
        if action in ("find", "def") and name:
            hit = idx.find(name)
            if not hit:
                refs = idx.refs(name, limit=5)
                if refs:
                    rows = [{"kind": "ref", "name": name, "file": r["file"], "line": r["line"], "signature": r["text"]} for r in refs]
                    return f"ไม่พบนิยามของ '{name}' แต่พบการอ้างอิง:\n" + idx.format(rows)
                return f"ไม่พบ '{name}' ในโปรเจกต์"
            return idx.format([hit])
        if action == "refs" and name:
            refs = idx.refs(name)
            rows = [{"kind": "ref", "name": name, "file": r["file"], "line": r["line"], "signature": r["text"]} for r in refs]
            return idx.format(rows) if rows else f"ไม่มี refs ของ '{name}' ในโปรเจกต์"
        if action == "list":
            q = (query or "").strip().lower()
            hits = [e for e in idx.entries if q in e["name"].lower()][:30] if q else idx.entries[:30]
            return idx.format(hits)
        return "ใช้: action=summary|find|refs|list, name=<สัญลักษณ์>, query=<คำค้น>"

    def _ensure_git_block(self):
        """ประวัติ git ล่าสุด (context สำหรับ debug — คำนวณครั้งเดียวต่อ session)"""
        if self._git_block is None:
            try:
                from yousini_git import last_commits_block
                self._git_block = last_commits_block(8, self.cwd)
            except Exception:
                self._git_block = ""
        return self._git_block

    def git_tool(self, action: str = "log", n: int = 10, file: str = "", line: int = 1) -> str:
        """ใช้ประวัติ git เป็น context: log|full|status|diff|blame"""
        from yousini_git import recent_log, full_log, status_short, diff_stat, blame, is_repo
        if not is_repo(self.cwd):
            return "(ไม่อยู่ใน git repo — ข้ามการใช้งาน git)"
        if action == "log":
            return "\n".join(recent_log(n, self.cwd)) or "(ยังไม่มี commit)"
        if action == "full":
            return full_log(n, self.cwd)
        if action == "status":
            return status_short(self.cwd)
        if action == "diff":
            return diff_stat(self.cwd) or "(ไม่มี diff)"
        if action == "blame" and file:
            return blame(file, line, self.cwd)
        return "ใช้: action=log|full|status|diff|blame, n=<จำนวน>, file=<ไฟล์>, line=<บรรทัด>"


    def search_sessions(self, query: str, limit: int = 10) -> str:
        """ค้นหาย้อนหลังใน session ก่อนหน้า (เทียบเท่า Hermes session_search)"""
        try:
            from yousini_sessions_db import SessionSearch
            rows = SessionSearch(SESSION_DIR / "search.db").search(query, limit=limit)
        except Exception:
            rows = []
        if not rows:
            return f"ไม่พบ session ที่เกี่ยวกับ '{query}'"
        parts = [f"พบ {len(rows)} session ที่เกี่ยวข้อง:"]
        for r in rows:
            parts.append(f"• [{r['session']}] ({str(r['saved_at'])[:16]}) {r['role']}: {r['snippet']}")
        return "\n".join(parts)

    def git_pr_tool(self, action: str = "create", title: str = "", body: str = "",
                    branch: str = "", base: str = "main") -> str:
        """สร้าง PR: commit งานค้าง → (สร้าง) branch → push → gh pr create (หรือลิงก์ compare)"""
        from yousini_git import create_pr, pr_list
        if action == "list":
            return pr_list(self.cwd)
        if action == "create":
            return create_pr(title, body, branch, base, self.cwd)
        return "ใช้: action=create|list, title=<ชื่อ PR>, body=<รายละเอียด>, branch=<สาขา>, base=<base>"

    def scaffold_tool(self, kind: str, name: str) -> str:
        """สร้างโครงโปรเจกต์จากเทมเพลต (python-cli|python-pkg|web-static)"""
        from yousini_scaffold import scaffold
        return scaffold(kind, name, self.cwd)

    def dev_check_tool(self, scope: str = "all") -> str:
        """รวมตรวจโปรเจกต์: all|status|compile|test|lint — สถานะ git, ไวยากรณ์ Python, test, lint"""
        scope = (scope or "all").lower()
        from yousini_git import status_short
        from pathlib import Path as _Path
        parts = []
        if scope in ("all", "status"):
            parts.append("— git status —\n" + status_short(self.cwd))
        if scope in ("all", "compile"):
            import py_compile
            py = [str(p) for p in _Path(self.cwd).rglob("*.py")
                  if ".git" not in p.parts and "__pycache__" not in p.parts][:200]
            bad = []
            for f in py:
                try:
                    py_compile.compile(f, doraise=True, quiet=1)
                except Exception:
                    bad.append(f)
            parts.append("— compile — ตรวจ " + str(len(py)) + " ไฟล์ .py → " +
                         ("ไวยากรณ์ OK ทั้งหมด" if not bad else
                          "พบปัญหา " + str(len(bad)) + " ไฟล์:\n" + "\n".join("  " + b for b in bad)))
        if scope in ("all", "test"):
            tests = [p for p in _Path(self.cwd).rglob("test_*.py") if ".git" not in p.parts] + \
                    [p for p in _Path(self.cwd).rglob("*_test.py") if ".git" not in p.parts]
            if tests:
                try:
                    proc = subprocess.run([sys.executable, "-m", "pytest", "-q",
                                           "-p", "no:cacheprovider"],
                                          cwd=self.cwd, capture_output=True,
                                          text=True, timeout=240)
                    lines = (proc.stdout or "").strip().splitlines()
                    tail = lines[-3:] if len(lines) > 3 else lines
                    body = "\n".join(tail)
                    if proc.returncode != 0:
                        body += f"\n(exit {proc.returncode})"
                    parts.append("— test —\n" + (body or "(ไม่มีผลลัพธ์)"))
                except subprocess.TimeoutExpired:
                    parts.append("— test — หมดเวลา (240s)")
                except Exception as e:
                    parts.append(f"— test — error: {e}")
            else:
                parts.append("— test — ไม่พบไฟล์ test_*.py")
        if scope in ("all", "lint"):
            runner = next((x for x in ("ruff", "flake8") if shutil.which(x)), None)
            if runner:
                try:
                    proc = subprocess.run([runner, "check", "."], cwd=self.cwd,
                                          capture_output=True, text=True, timeout=120)
                    out = (proc.stdout or "").strip()
                    parts.append("— " + runner + " — " +
                                 ("ไม่มีปัญหา" if proc.returncode == 0 and not out
                                  else (out[:1500] or f"(exit {proc.returncode})")))
                except Exception as e:
                    parts.append(f"— {runner} — error: {e}")
            else:
                parts.append("— lint — ไม่พบ ruff/flake8 (ข้าม)")
        return "\n\n".join(parts) or "(ไม่มีอะไรตรวจ — ใช้ /dev <all|status|compile|test|lint>)"

    # ---- Export/Import session (v3.8) ----
    def session_export_tool(self, name: str, out: str = "", fmt: str = "json") -> str:
        """ส่งออก session เป็นไฟล์ JSON/MD — สำรองหรือย้ายเครื่อง"""
        from yousini_session_io import export_session
        r = export_session(SessionStore(SESSION_DIR), name, out, fmt)
        if r["ok"]:
            return f"export สำเร็จ: {r['path']} ({r['fmt']}, {r['count']} ข้อความ)"
        return r["error"]

    def session_import_tool(self, path: str, new_name: str = "") -> str:
        """นำเข้า session จากไฟล์ JSON — กลับมาใช้/ค้นหาได้"""
        from yousini_session_io import import_session
        r = import_session(SessionStore(SESSION_DIR), path, new_name)
        if r["ok"]:
            return f"import สำเร็จ: '{r['name']}' ({r['count']} ข้อความ)"
        return r["error"]

    def workflow_run_tool(self, name: str) -> str:
        """รันเทมเพลตงานอัตโนมัติ (release|weekly_report|code_review หรือของผู้ใช้)"""
        from yousini_workflows import run_workflow
        exec_tool = lambda tname, targs: _exec_tool(self, tname, targs, tc_id="workflow")
        return run_workflow(name, exec_tool=exec_tool, chat_turn=None, cwd=self.cwd)

    def config_tool(self, action: str = "list", key: str = "", value: str = "") -> str:
        """ตั้งค่า/ดู config และ feature flags"""
        from yousini_config import config_cmd, flag_cmd
        action = (action or "list").lower()
        if action in ("flag", "flags"):
            return flag_cmd(f"{key} {value}".strip())
        if action == "get" and key:
            return config_cmd(f"get {key}")
        if action == "set" and key:
            return config_cmd(f"set {key} {value}")
        return config_cmd("list")

    def plugin_list_tool(self) -> str:
        """แสดง plugin ที่โหลดอยู่ (เพิ่ม tool/คำสั่ง)"""
        from yousini_plugins import list_plugins
        ps = list_plugins()
        if not ps:
            return "ไม่มี plugin อยู่ — วางโฟลเดอร์ที่มี plugin.py ลงในโฟลเดอร์ plugins/ แล้วรีสตาร์ท"
        return "\n".join(f"• {p['name']} v{p['version']} — {p.get('description', '')}"
                         for p in ps)

    def update_tool(self, action: str = "check") -> str:
        """ตรวจ/อัปเดตเวอร์ชัน Yousini"""
        from yousini_update import update_main
        return update_main(["go" if action == "update" else "check"], APP_VERSION)

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

    def batch_edit_files(self, edits: list) -> str:
        """แก้ไขหลายไฟล์พร้อมกัน + commit อะตอมิก (ใช้ list ของ dict: {path, old_string, new_string})
        ถ้าไม่ระบุ old_string จะเขียนทับไฟล์เลย"""
        if not edits:
            return "Error: ต้องระบุรายการแก้ไขอย่างน้อย 1 ไฟล์"
        if not self.allow_write:
            return "Error: batch_edit ถูกปิดในโหมด read-only"
        changes = []
        for i, edit in enumerate(edits, 1):
            path = edit.get("path")
            if not path:
                changes.append(f"Step {i}: (ข้าม — ไม่ระบุ path)")
                continue
            old_string = edit.get("old_string", "")
            new_string = edit.get("new_string", "")
            full = self._resolve(path)
            try:
                if old_string:
                    r = self.edit_file(path, old_string, new_string)
                    changes.append(f"Step {i}: edit {path}: {r}")
                else:
                    r = self.write_file(path, new_string)
                    changes.append(f"Step {i}: write {path}: {r}")
            except Exception as e:
                changes.append(f"Step {i}: Error {path}: {e}")
        # Atomic git commit
        cp = self.checkpoint("batch_edit_files")
        summary = f"batch_edit_files: {len(changes)} file(s) changed"
        if cp:
            summary += f" — {cp}"
        return summary + "\n" + "\n".join(changes)

    def run_test_loop(self, test_cmd: str = "pytest", max_iterations: int = 3) -> str:
        """รัน test → ถ้ามี error → แก้ไขอัตโนมัติ → loop จนผ่านหรือหมด max_iterations"""
        if not self.allow_shell:
            return "Error: run_test_loop ถูกปิดในโหมด read-only"
        console.print(Text(f"🧪 Test loop: {test_cmd} (max {max_iterations} iterations)", style=C_THINK))
        self.checkpoint(f"before_test_loop:{test_cmd}")
        for i in range(1, max_iterations + 1):
            console.print(Text(f"รอบที่ {i}/{max_iterations}...", style=C_TOOL))
            proc = subprocess.run(test_cmd, shell=True, cwd=self.cwd,
                                  capture_output=True, text=True, timeout=120)
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            combined = stdout + stderr
            if proc.returncode == 0:
                console.print(Text(f"✅ Round {i}: ทุก test ผ่าน!", style=C_OK))
                return f"test loop ผ่านในรอบที่ {i}:\n{combined[:2000]}"
            console.print(Text(f"❌ Round {i}: test ล้มเหลว ({proc.returncode})", style=C_WARN))
            if i < max_iterations:
                self.messages.append({
                    "role": "user",
                    "content": (f"Test ล้มเหลว (round {i}):\n{combined[-1500:]}\n"
                                f"แก้ไขโค้ดให้ test ผ่าน แล้วส่ง tool call ต่อไปได้เลย")
                })
        return f"test loop จบหลัง {max_iterations} รอบ — มีบาง test ที่ยังล้มเหลว"


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
# web_search ผ่าน API provider จริง (Brave / SerpAPI / Tavily) — default คือ Brave API
# โทรก่อน scraping เสมอเมื่อมี BRAVE_API_KEY ตั้งไว้
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
    {"type": "function", "function": {"name": "manage_todos", "description": "จัดการรายการสิ่งที่ต้องทำ (plan/ความคืบหน้า) เพื่อแสดงแผนงานให้ผู้ใช้เห็นชัดเจน: action สามารถเป็น add/update/complete/start/delete/list — add ต้องการ content, complete/start/update/delete ต้องการ todo_id", "parameters": {"type": "object", "properties": {"action": {"type": "string", "description": "add / update / complete / start / delete / list"}, "content": {"type": "string", "description": "ข้อความรายการ (สำหรับ add/update)"}, "todo_id": {"type": "integer", "description": "รหัสรายการ (สำหรับ update/complete/start/delete)"}, "status": {"type": "string", "description": "สถานะใหม่ (ไม่บังคับ)"}}, "required": ["action"]}}},
    {"type": "function", "function": {"name": "batch_edit_files", "description": "แก้ไขหลายไฟล์พร้อมกัน + commit อะตอมิก เหมาะสำหรับ refactor ใหญ่ ใส่รายการ edits = [{path, old_string?, new_string?}]", "parameters": {"type": "object", "properties": {"edits": {"type": "array", "description": "รายการแก้ไฟล์ แต่ละอันมี path + new_string (เรียกใช้ old_string ถ้าต้องการ replace)", "items": {"type": "object", "properties": {"path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}}, "required": ["path", "new_string"]}}}, "required": ["edits"]}}},
    {"type": "function", "function": {"name": "run_test_loop", "description": "รัน test แล้วแก้ไขอัตโนมัติซ้ำ (auto-fix loop) — เหมาะกับ TDD workflow ใส่ test_cmd เช่น pytest -x", "parameters": {"type": "object", "properties": {"test_cmd": {"type": "string", "description": "คำสั่งรัน test (ค่าเริ่มต้น pytest)", "default": "pytest"}, "max_iterations": {"type": "integer", "description": "จำนวนรอบสูงสุด (ค่าเริ่มต้น 3)", "default": 3}}, "required": []}}},
    {"type": "function", "function": {"name": "memory", "description": "จัดการความจำระยะยาว (จำข้าม session เหมือน Hermes memory): action add/remove/replace/list, target user (ข้อมูลผู้ใช้) หรือ agent (บันทึกของ agent) — บันทึกเฉพาะข้อเท็จจริง/ความชอบ/บทเรียนที่ควรจำข้าม session ห้ามบันทึกความคืบหน้างานชั่วคราว", "parameters": {"type": "object", "properties": {"action": {"type": "string", "description": "add / remove / replace / list"}, "target": {"type": "string", "description": "user หรือ agent"}, "content": {"type": "string", "description": "ข้อความ (สำหรับ add/replace)"}, "old_text": {"type": "string", "description": "ข้อความค้นหาในรายการเดิม (สำหรับ remove/replace)"}}, "required": ["action", "target"]}}},
    {"type": "function", "function": {"name": "skill_create", "description": "สร้างสกิลใหม่ (ความรู้/ขั้นตอนที่ควรจำและใช้ซ้ำ): name สั้นๆ, description ขึ้นต้นด้วย 'Use when ...', content คือเนื้อหาเต็ม — ใช้หลังจากทำงานยากสำเร็จเพื่อบันทึกวิธีทำ (self-improvement)", "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "ชื่อสกิล (ตัวเล็ก ขีด- เช่น deploy-flow)"}, "description": {"type": "string", "description": "คำอธิบาย ขึ้นต้นด้วย 'Use when ...'"}, "content": {"type": "string", "description": "เนื้อหาเต็มของสกิล (ขั้นตอน)"}}, "required": ["name", "description", "content"]}}},
    {"type": "function", "function": {"name": "skill_patch", "description": "แก้ไขสกิลที่มีอยู่ (search & replace เนื้อหา) — ใช้เมื่อพบว่าสกิลล้าสมัย/ผิดพลาด", "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "ชื่อสกิล"}, "old_string": {"type": "string", "description": "ข้อความเดิมที่จะแทนที่"}, "new_string": {"type": "string", "description": "ข้อความใหม่"}}, "required": ["name", "old_string", "new_string"]}}},
    {"type": "function", "function": {"name": "cron", "description": "จัดการงานอัตโนมัติตามเวลา (เหมือน Hermes cronjob): action=list/add/remove/pause/resume — add ต้องการ schedule (เช่น '30m', '0 9 * * *', '2026-08-11T10:00:00') + prompt", "parameters": {"type": "object", "properties": {"action": {"type": "string", "description": "list / add / remove / pause / resume"}, "schedule": {"type": "string", "description": "ช่วงเวลา เช่น 30m, every 2h, 0 9 * * *, ISO"}, "prompt": {"type": "string", "description": "งานที่ให้ agent ทำเมื่อถึงเวลา"}, "job_id": {"type": "integer", "description": "id งาน (สำหรับ remove/pause/resume)"}}, "required": ["action"]}}},
    {"type": "function", "function": {"name": "git", "description": "ใช้ประวัติ git เป็น context: log=รายการ commit ล่าสุด, full=log พร้อมผู้แต่ง/วันที่, status=ไฟล์ค้าง, diff=diff ยังไม่ commit, blame=ใครแก้บรรทัดนี้", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["log", "full", "status", "diff", "blame"]}, "n": {"type": "integer"}, "file": {"type": "string"}, "line": {"type": "integer"}}, "required": ["action"]}}},
    {"type": "function", "function": {"name": "symbols", "description": "ค้นหาโครงสร้างโค้ดด้วย symbol index (AST-aware): summary=ภาพรวมโปรเจกต์, find=<ชื่อ>=go-to-definition, refs=<ชื่อ>=ทุกจุดอ้างอิง, list+query=รายการสัญลักษณ์", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["summary", "find", "refs", "list"]}, "name": {"type": "string"}, "query": {"type": "string"}}, "required": ["action"]}}},
    {"type": "function", "function": {"name": "search_sessions", "description": "ค้นหาย้อนหลังใน session ก่อนหน้าทั้งหมด (เหมือน Hermes session_search) — ใช้เมื่อผู้ใช้ถามว่าเคยทำ/คุยเรื่องอะไรไว้ก่อนหน้านี้", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "คำค้น"}, "limit": {"type": "integer", "description": "จำนวนผลสูงสุด (ค่าเริ่มต้น 10)"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "git_pr", "description": "สร้าง Pull Request จากงานที่ทำ: commit งานค้าง → (สร้าง) branch → push → เปิด PR ผ่าน gh (หรือคืนลิงก์ compare). action=create ต้องการ title; action=list แสดง PR ที่เปิดอยู่", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["create", "list"]}, "title": {"type": "string", "description": "ชื่อ PR"}, "body": {"type": "string", "description": "รายละเอียด PR"}, "branch": {"type": "string", "description": "สาขา (ไม่ระบุ = ใช้สาขาปัจจุบัน)"}, "base": {"type": "string", "description": "สาขาปลายทาง (ค่าเริ่มต้น main)"}}, "required": ["action"]}}},
    {"type": "function", "function": {"name": "scaffold", "description": "สร้างโครงโปรเจกต์เริ่มต้นจากเทมเพลต (ไม่ต้องใช้โมเดล): kind=python-cli|python-pkg|web-static, name=ชื่อโปรเจกต์ (ตัวเล็ก)", "parameters": {"type": "object", "properties": {"kind": {"type": "string", "enum": ["python-cli", "python-pkg", "web-static"]}, "name": {"type": "string"}}, "required": ["kind", "name"]}}},
     {"type": "function", "function": {"name": "dev_check", "description": "รวมตรวจโปรเจกต์ (สถานะ git, ไวยากรณ์ Python, รัน test, lint) — scope=all|status|compile|test|lint. ใช้ก่อนสรุปว่างานผ่านหรือหลัง refactor", "parameters": {"type": "object", "properties": {"scope": {"type": "string", "enum": ["all", "status", "compile", "test", "lint"]}}, "required": []}}},
    {"type": "function", "function": {"name": "session_export", "description": "ส่งออก session (บทสนทนาที่บันทึกไว้) เป็นไฟล์ JSON หรือ Markdown เพื่อสำรอง/ย้ายเครื่อง: name=ชื่อ session, out=เส้นทางไฟล์หรือโฟลเดอร์, fmt=json|md. ดูชื่อ session ได้จาก tool search_sessions หรือ /sessions", "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "out": {"type": "string"}, "fmt": {"type": "string", "enum": ["json", "md"]}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "session_import", "description": "นำเข้า session จากไฟล์ JSON (จาก session_export หรือไฟล์ session เดิม) กลับมาใช้/ค้นหาได้: path=ไฟล์, new_name=ชื่อใหม่ (ไม่ระบุใช้ชื่อเดิม)", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "new_name": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "workflow_run", "description": "รันเทมเพลตงานอัตโนมัติ (ชุดขั้นตอนซ้ำ): name=release|weekly_report|code_review หรือเทมเพลตผู้ใช้. เทมเพลตมีขั้นตอน tool/prompt รันตามลำดับ", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "config", "description": "จัดการตั้งค่า/feature flags: action=list|get|set|flag — get/set ค่า config.json (เช่น theme), flag เปิด-ปิดความสามารถ (เช่น plugin_system, usage_report)", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["list", "get", "set", "flag"]}, "key": {"type": "string", "description": "ชื่อคีย์ (สำหรับ get/set/flag)"}, "value": {"type": "string", "description": "ค่าใหม่ (สำหรับ set/flag)"}}, "required": ["action"]}}},
    {"type": "function", "function": {"name": "plugin_list", "description": "แสดง plugin ที่ติดตั้ง/โหลดอยู่ (ส่วนขยายที่เพิ่ม tool/คำสั่ง) — พร้อมเวอร์ชันและคำอธิบาย", "parameters": {"type": "object", "properties": {}}, "required": []}},
    {"type": "function", "function": {"name": "check_update", "description": "ตรวจสอบเวอร์ชัน Yousini ล่าสุดจาก GitHub เทียบกับปัจจุบัน — action=check|update. update จะดึงโค้ดใหม่ลง working tree (ต้องรันจาก repo Yousini)", "parameters": {"type": "object", "properties": {"action": {"type": "string", "enum": ["check", "update"]}}, "required": []}}},
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
    "manage_todos": lambda a, k: k.manage_todos(**a),
    "batch_edit_files": lambda a, k: k.batch_edit_files(**a),
    "run_test_loop": lambda a, k: k.run_test_loop(**a),
    "memory": lambda a, k: k.memory_tool(**a),
    "skill_create": lambda a, k: k.skill_create(**a),
    "skill_patch": lambda a, k: k.skill_patch(**a),
    "search_sessions": lambda a, k: k.search_sessions(**a),
    "symbols": lambda a, k: k.symbols_tool(**a),
    "git": lambda a, k: k.git_tool(**a),
    "git_pr": lambda a, k: k.git_pr_tool(**a),
    "scaffold": lambda a, k: k.scaffold_tool(**a),
    "dev_check": lambda a, k: k.dev_check_tool(**a),
    "cron": lambda a, k: k.cron_tool(**a),
    "session_export": lambda a, k: k.session_export_tool(**a),
    "session_import": lambda a, k: k.session_import_tool(**a),
    "workflow_run": lambda a, k: k.workflow_run_tool(**a),
    "config": lambda a, k: k.config_tool(**a),
    "plugin_list": lambda a, k: k.plugin_list_tool(**a),
    "check_update": lambda a, k: k.update_tool(**a),
}

# ---- MCP client (Phase 6): เครื่องมือจาก MCP server ภายนอก (ชื่อขึ้น mcp__<server>__<tool>) ----
try:
    from yousini_mcp import connect_all as _mcp_connect
    _mcp_schemas, _mcp_impls = _mcp_connect()
    if _mcp_schemas:
        TOOLS = TOOLS + _mcp_schemas
        IMPL.update(dict(_mcp_impls))
except Exception as _mcp_err:
    if str(_mcp_err):
        pass  # ปิดเงียบ — ไม่ให้ MCP ที่พังทำลายการเริ่มต้น

# ปกติ schema tools: Mistral/provider บางราย ไม่ยอมรับ "required": [] (ว่าง) → ลบออก
for _t in TOOLS:
    _fn = _t.get("function", {})
    if _fn.get("required") == []:
        _fn.pop("required", None)

# ข้อความเตือนเมื่อโมเดลเรียก tool ที่ไม่มีในระบบ (เช่น repo_browser ของ gpt-oss)
_TOOL_FIX_HINT = (
    "ข้อผิดพลาด: คุณพยายามเรียกใช้เครื่องมือที่ไม่มีในระบบ (เช่น repo_browser, python, "
    "web_browser) กรุณาใช้เฉพาะเครื่องมือที่กำหนดให้เท่านั้น: shell, read_file, write_file, "
    "edit_file, list_dir, glob, grep, web_fetch, web_search, set_cwd, ask_user, "
    "list_jobs, read_job, manage_todos, batch_edit_files, run_test_loop, git_pr, "
    "scaffold, dev_check, session_export, session_import, workflow_run, config, "
    "plugin_list, check_update"
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

    # แสดงผล tool call ในโหมดปกติ หรือแสดง spinner ในโหมด quiet
    shown = args.get("command", "") if name == "shell" else args
    if not isinstance(shown, str):
        shown = json.dumps(shown, ensure_ascii=False)

    if not agent.quiet_mode:
        console.print(_ui_tool_call(name, shown))

    # เตรียม spinner สำหรับ quiet mode (แสดงว่ากำลังทำงาน)
    spinner_live = None
    spinner_text = Text(f"⏳ {name}…", style=C_THINK)
    if agent.quiet_mode:
        spinner_live = Live(spinner_text, console=console, refresh_per_second=10)
        spinner_live.start()

    try:
        result = IMPL[name](args, agent)
    finally:
        if spinner_live is not None:
            spinner_live.stop()
            # ลบข้อความ spinner ออก (เขียนทับบรรทัดนั้นเมื่อเสร็จ)
            console.print()

    _record_usage_tool(name)
    agent.hooks.run_post(name, args, str(result))

    # แสดงผลลัพธ์ในโหมดปกติ
    if not agent.quiet_mode:
        _ui_tool_result(name, result)

    agent.messages.append({"role": "tool", "tool_call_id": tc_id, "content": str(result)})
    # สำหรับ todo: วาดแผนงานให้ผู้ใช้เห็นชัดเจนด้วย (เฉพาะโหมดปกติ)
    if not agent.quiet_mode and name == "manage_todos":
        agent._print_todos()


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


def _prepare_user_content(user_text: str, agent: "Agent"):
    """แปลงข้อความผู้ใช้ → content blocks (รองรับรูปภาพ [img:...]) — เก็บเป็น str ถ้าไม่มีรูป
    คืน (content, warnings) — warnings มีคำเตือนชัดเจนเมื่อใส่รูปแต่โมเดลไม่รองรับ vision
    หรือไฟล์รูปโหลดไม่ได้ (กัน silent fail ที่ผู้ใช้งงว่าใส่รูปแล้วทำไมไม่ตอบ)"""
    warnings: list[str] = []
    if "[img:" not in user_text:
        return user_text, warnings
    try:
        from yousini_vision import content_with_images
        content = content_with_images(user_text, agent.cwd)
    except Exception as e:
        warnings.append(f"ไม่สามารถแนบรูปภาพได้: {e}")
        return user_text, warnings
    if isinstance(content, str):
        warnings.append(
            "มี [img:...] แต่ไม่พบรูปที่โหลดได้ (ไฟล์ไม่มี, อยู่คนละโฟลเดอร์, หรือใหญ่เกิน 4MB) — "
            "ส่งเป็นข้อความล้วนแทน")
        return content, warnings
    if not _model_supports_vision(agent.model):
        warnings.append(
            f"โมเดล {agent.model} อาจไม่รองรับรูปภาพ (vision) — เปลี่ยนเป็น pixtral-large-latest "
            "หรือโมเดล vision (เช่น /model) เพื่อให้เห็นรูปจริง; ส่งเนื้อหาต่อ โดยภาพอาจถูกละเว้น")
    return content, warnings


def _model_supports_vision(model: str) -> bool:
    """ประเมินว่าโมเดลรองรับ image_url ผ่าน OpenAI-compatible API หรือไม่ (อนุรักษ์นิยม)."""
    m = (model or "").lower()
    return any(k in m for k in (
        "pixtral", "vision", "llava", "moondream", "fuyu", "gemini",
        "claude", "gpt-4o", "gpt-4.1", "gpt-4.5", "gpt-5", "qwen2-vl", "qwen-vl",
    ))


def chat_turn(agent: Agent, user_text: str):
    agent.begin_turn()
    _record_usage_turn()
    if not hasattr(agent, "_typewriter"):
        agent._typewriter = True  # typewriter on by default
    content, warnings = _prepare_user_content(user_text, agent)
    for w in warnings:
        console.print(Text(f"คำเตือน: {w}", style="yellow"))
    agent.messages.append({"role": "user", "content": content})
    agent._trim()
    agent._auto_compact()
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
            _ui_error(str(e)); return

        content = []
        tool_calls = []

        # spinner ธรรมดา (ไม่ใช้ rich.Live — กันเฟรมซ้ำ/จอเลอะบน Windows conhost)
        stop_spin = threading.Event()
        spinner = None
        if sys.stdout.isatty():
            _frames = ["⠿", "⠸", "⠼", "⠴", "⠦", "⠇"]

            def _spin():
                i = 0
                while not stop_spin.is_set():
                    sys.stdout.write("\r" + _frames[i % len(_frames)] + " กำลังคิด…")
                    sys.stdout.flush()
                    i += 1
                    stop_spin.wait(0.1)

            spinner = threading.Thread(target=_spin, daemon=True)
            spinner.start()

        def _stop_spinner():
            if spinner is not None:
                stop_spin.set()
                spinner.join(timeout=0.5)
                sys.stdout.write("\r" + " " * 32 + "\r")
                sys.stdout.flush()

        try:
            for chunk in stream:
                u = getattr(chunk, "usage", None)
                if u is not None:
                    agent._add_usage(u)
                if not chunk.choices:
                    continue
                d = chunk.choices[0].delta
                if d.content:
                    content.append(d.content)
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
            _stop_spinner()
            if _is_tool_validation_err(e) and attempts < MAX_ATTEMPTS:
                attempts += 1
                agent.messages.append({"role": "user", "content": _TOOL_FIX_HINT})
                continue
            return _fallback_turn(agent, e)
        except Exception as e:
            _stop_spinner()
            if _is_tool_validation_err(e) and attempts < MAX_ATTEMPTS:
                attempts += 1
                agent.messages.append({"role": "user", "content": _TOOL_FIX_HINT})
                continue
            _ui_error(f"stream: {e}"); return

        if any(t.get("name") for t in tool_calls):
            tool_seen = True
            _stop_spinner()
            if "".join(content).strip():
                console.print(Markdown("".join(content)))
            if not agent.quiet_mode:
                console.print(_think("เตรียมเครื่องมือ…"))
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

        _stop_spinner()
        ans = "".join(content)
        agent.messages.append({"role": "assistant", "content": ans})
        # คำตอบเน้นสี — typewriter effect (ป้อน Markdown ทีละคำ) ถ้าเปิด typewriter ไว้
        if ans.strip():
            if getattr(agent, "_typewriter", False):
                _ui_typewriter(ans, model=agent.model)
            else:
                console.print(_ui_answer_panel(ans, model=agent.model))
        _ui_status(agent)
        console.print()
        return


# ---------------------------------------------------------------------------
# run_turn_events — เวอร์ชัน generator สำหรับ server/remote (yield เป็น event)
# event: {"type": "token"|"tool"|"tool_result"|"final"|"error", ...}
# ---------------------------------------------------------------------------
def run_turn_events(agent: Agent, user_text: str):
    agent.begin_turn()
    _record_usage_turn()
    content, warnings = _prepare_user_content(user_text, agent)
    for w in warnings:
        yield {"type": "warn", "text": w}
    agent.messages.append({"role": "user", "content": content})
    agent._trim()
    agent._auto_compact()
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
                u = getattr(chunk, "usage", None)
                if u is not None:
                    agent._add_usage(u)
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
                _record_usage_tool(t["name"])
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
    """จอเปิด: delegete ไปยัง yousini_ui.welcome_banner (HUD + คำแนะนำปุ่มลัด)"""
    _ui_welcome(agent)
    return

def _print_help():
    lines = [
        ("/help", "แสดงคำสั่งนี้"),
        ("/clear", "ล้างประวัติการสนทนา"),
        ("/history", "แสดงประวัติข้อความทั้งหมด"),
        ("/model <ชื่อ>", "เปลี่ยนโมเดล เช่น /model openai/gpt-oss-120b"),
        ("/cwd <โฟลเดอร์>", "เปลี่ยนโฟลเดอร์ทำงาน"),
        ("/approve on|off", "รัน shell อัตโนมัติโดยไม่ถาม"),
        ("/login", "เข้าสู่ระบบ/เลือก provider และ API key"),
        ("/theme <ชื่อ>", "เปลี่ยนธีม (dark/notion/nord/tokyo-night)"),
        ("/permission <คำสั่ง>", "จัดการ on/off shell commands (add/list/remove/clear)"),
        ("/plan", "โหมดแผน: วางแผนก่อนทำ (กำลังพัฒนา)"),
        ("/img <ไฟล์|url> [คำถาม]", "แนบรูปภาพให้โมเดลดู (ต้องใช้โมเดล vision เช่น pixtral-large-latest)"),
        ("/reload", "โหลด YOUSINI.md + skills ใหม่"),
        ("/skills", "แสดงสกิลที่โหลดอยู่"),
        ("/hooks", "แสดงสถานะ hooks"),
        ("/save [ชื่อ]", "บันทึกบทสนทนาลงดิสก์"),
        ("/load [ชื่อ]", "โหลดบทสนทนาจากดิสก์"),
        ("/sessions", "แสดงรายการ session ที่บันทึกไว้"),
        ("/search <คำ>", "ค้นหาย้อนหลังในทุก session (รองรับภาษาไทย)"),
        ("/symbols [def|refs|list <คำ>]", "ค้นหาโครงสร้างโค้ด (AST symbol index)"),
        ("/git [log|full|status|diff|blame]", "ดูประวัติ/สถานะ git เป็น context"),
        ("/cron", "ดู/จัดการงานอัตโนมัติ: add <schedule> <prompt> | remove <id> | pause|resume <id>"),
        ("/jobs", "แสดงงาน shell background"),
        ("/todos", "แสดงรายการสิ่งที่ต้องทำ (plan/ความคืบหน้า)"),
        ("/memory", "ดู/จัดการความจำระยะยาว (add|remove|replace|list <user|agent> [ข้อความ])"),
        ("/providers", "แสดง provider ที่ใช้ + ลำดับสำรอง (fallback อัตโนมัติ)"),
        ("/compact", "ยุบบริบทเก่าเป็นสรุปสั้นๆ (ลดโทเค็น เหมาะตอนสนทนายาว)"),
        ("/quiet on|off", "ซ่อนรายละเอียด tool call/result — เหลือเห็นแต่คำตอบสุดท้าย (มี spinner แสดงว่ากำลังทำงาน)"),
        ("/checkpoint", "git commit จุดเก็บชั่วคราวเดี๋ยวนั้น"),
        ("/rollback", "ย้อนกลับไปจุด checkpoint ล่าสุด (git reset)"),
        ("/usage [on|off|reset]", "สถิติการใช้งาน token/tool (เก็บเฉพาะในเครื่อง, opt-in)"),
        ("/ads [on|off|status]", "เปิด/ปิด sponsor line (ปิดได้เสมอ — pro ไม่มีโฆษณา)"),
        ("/tier [activate <key>|off]", "ดู/เปิดสิทธิ์ Pro/Team ด้วย license key"),
        ("/market [search|install|uninstall]", "ค้นหา/ติดตั้ง skills & tool plugins (marketplace)"),
        ("/team", "ดูสถานะ workspace ของทีม (registry/สมาชิก/role)"),
        ("/agent send <worker> <โจทย์>", "ส่งงานให้ agent อื่นผ่านคิว (collaboration)"),
        ("/agent status|result <id>", "ดูสถานะคิว / ผลลัพธ์งาน"),
        ("/work", "ประมวลผลงานที่ค้างในคิวตอนนี้"),
        ("/pr <ชื่อ>|list", "สร้าง Pull Request (commit→branch→push→gh) / ดู PR เปิด"),
        ("/scaffold <kind> <name>", "สร้างโครงโปรเจกต์: python-cli|python-pkg|web-static"),
        ("/dev [all|status|compile|test|lint]", "รวมตรวจโปรเจกต์ (git/ไวยากรณ์/test/lint)"),
        ("/plugins", "แสดง plugin ที่โหลดอยู่ (ส่วนขยาย tool/คำสั่ง)"),
        ("/export <session> [--md] [--out ไฟล์]", "ส่งออก session เป็น JSON/MD (สำรอง/ย้ายเครื่อง)"),
        ("/import <ไฟล์> [--name ชื่อ]", "นำเข้า session จากไฟล์ JSON"),
        ("/update [check]", "ตรวจ/อัปเดตเวอร์ชัน Yousini จาก GitHub"),
        ("/config list|get <key>|set <key> <ค่า>", "ดู/ตั้งค่า config.json"),
        ("/flag [list|<ชื่อ> [on|off]]", "เปิด/ปิด feature flags (plugin_system, usage_report, ...)"),
        ("/workflow list|run <ชื่อ>|show <ชื่อ>", "เทมเพลตงานอัตโนมัติ (release, weekly_report, code_review)"),
        ("/usage report [daily|weekly|monthly]", "สร้างรายงานการใช้งานตามช่วงเวลา"),
        ("/exit, /quit", "ออก"),
    ]
    servers = [
        ("yousini serve", "เปิดเว็บ UI + API (localhost)"),
        ("yousini serve --host 0.0.0.0 --token รหัส", "เปิดออนไลน์ (มี token)"),
        ("yousini serve --safe", "เปิดแบบอ่านอย่างเดียว (ปิด shell/เขียนไฟล์)"),
        ("yousini connect <url> [--token รหัส]", "คุยกับ Yousini อีกเครื่องผ่านเน็ต"),
        ("yousini mcp [--allow-exec]", "เปิดเป็น MCP server (stdio)"),
        ("yousini resume", "โหลด session ล่าสุดแล้วเข้าสู่แชท"),
        ("yousini cron [--interval 60|--once]", "รันงาน cron ตามเวลา (daemon / รอบเดียว)"),
        ("yousini mcp-add <ชื่อ> <คำสั่ง>", "เพิ่ม MCP server (client) — เครื่องมือขึ้น mcp__<ชื่อ>__<tool>"),
        ("yousini plugin list|install <path>|rm <ชื่อ>", "จัดการ plugin (โหลด tool/คำสั่งเพิ่ม)"),
        ("yousini session export|import", "ส่งออก/นำเข้า session (สำรอง, ย้ายเครื่อง)"),
        ("yousini update [check]", "ตรวจ/อัปเดตเวอร์ชัน Yousini"),
        ("yousini config|flag", "ตั้งค่า config.json / feature flags"),
        ("yousini workflow list|run|show", "เทมเพลตงานอัตโนมัติ"),
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
    for item in agent.skills:
        n = item[0]
        src = item[2] if len(item) > 2 else ""
        tag = " 📁" if src == "project" else " 💾" if src == "global" else ""
        t.append(f"• {n}{tag}\n", style="bold cyan")
    console.print(Panel(t, title=f"สกิลที่โหลด ({len(agent.skills)}) — 📁โปรเจกต์ 💾เครื่อง", border_style="magenta"))


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

# ============================================================
# CONFIGURATION & THEMES
# ============================================================
CONFIG_DIR = _profile_root()
CONFIG_FILE = CONFIG_DIR / "config.json"

THEMES = {
    "dark": {"bg": "#05060a", "panel": "rgba(18,20,32,.68)", "ink": "#eef1ff",
             "brand1": "#7c5cff", "brand2": "#18d3ff", "brand3": "#ff5cae",
             "ok": "#3ddc97", "warn": "#ffcf5c", "danger": "#ff6b6b"},
    "notion": {"bg": "#ffffff", "panel": "rgba(240,240,242,.8)", "ink": "#191919",
               "brand1": "#0070ec", "brand2": "#4dccff", "brand3": "#ff6b6b",
               "ok": "#22c55e", "warn": "#f59e0b", "danger": "#ef4444"},
    "nord": {"bg": "#24283b", "panel": "rgba(42,46,66,.7)", "ink": "#d8dee9",
             "brand1": "#8aadf4", "brand2": "#7dcfff", "brand3": "#f5a97f",
             "ok": "#8ccf7e", "warn": "#e2b768", "danger": "#e06e63"},
    "tokyo-night": {"bg": "#1a1b26", "panel": "rgba(36,40,59,.7)", "ink": "#c0caf5",
                    "brand1": "#bb9af7", "brand2": "#7aa2f7", "brand3": "#ff9e6d",
                    "ok": "#9ece6a", "warn": "#e0af68", "danger": "#f7768e"}
}


def _apply_provider_config(cfg: dict) -> bool:
    """Apply provider API key + base_url + model from config to the running process.
    Also recreates the global OpenAI client so the change takes effect immediately.
    Returns True if a provider was activated."""
    global client, API_KEY, BASE_URL, MODEL
    providers = cfg.get("providers", {})
    default_key = cfg.get("default_provider")
    activated = False
    if default_key and default_key in providers:
        p = providers[default_key]
        api_key = p.get("api_key", "")
        base_url = p.get("base_url", "")
        model = p.get("model", "")
        if api_key:
            os.environ["YOUSINI_API_KEY"] = api_key
            API_KEY = api_key; activated = True
        if base_url:
            os.environ["YOUSINI_BASE_URL"] = base_url
            BASE_URL = base_url; activated = True
        if model:
            os.environ["YOUSINI_MODEL"] = model
            MODEL = model; activated = True
    elif default_key == "custom" and "<custom>" in providers:
        p = providers["<custom>"]
        if p.get("api_key"):
            os.environ["YOUSINI_API_KEY"] = p["api_key"]
            API_KEY = p["api_key"]; activated = True
        if p.get("base_url"):
            os.environ["YOUSINI_BASE_URL"] = p["base_url"]
            BASE_URL = p["base_url"]; activated = True
        if p.get("model"):
            os.environ["YOUSINI_MODEL"] = p["model"]
            MODEL = p["model"]; activated = True
    if activated:
        client = _FallbackClient()  # rebuild ทั้ง chain (ตัวหลัก = provider ที่เพิ่ง activate)
    return activated


def load_config() -> dict:
    CONFIG_DIR.mkdir(exist_ok=True)
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        # Auto-apply provider credentials on load (fix: login works without restart)
        _apply_provider_config(cfg)
        return cfg
    except Exception:
        return {"theme": "dark", "allow_shell_prefix": []}


def save_config(cfg: dict) -> None:
    CONFIG_DIR.mkdir(exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_cfg_light() -> dict:
    """อ่าน config.json แบบตรงๆ โดยไม่ trigger _apply_provider_config (กัน rebuild client)"""
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def is_shell_allowed(cmd: str) -> bool:
    """Check if a shell command is in the allow-list (no confirmation needed)"""
    cfg = load_config()
    allow = cfg.get("allow_shell_prefix", [])
    if not allow:
        return False
    return any(cmd.startswith(p) for p in allow)


def permission_cmd(args: str) -> str:
    cfg = load_config()
    allow = cfg.get("allow_shell_prefix", [])
    parts = args.strip().split()
    if not parts:
        return "ใช้: /permission add <prefix> | /permission list | /permission remove <prefix> | /permission clear"
    cmd = parts[0].lower()
    if cmd == "add" and len(parts) > 1:
        prefix = parts[1]
        if prefix not in allow:
            allow.append(prefix)
            cfg["allow_shell_prefix"] = allow
            save_config(cfg)
            return f"เพิ่ม '{prefix}' เข้า allow-list"
        return f"'{prefix}' มีอยู่แล้ว"
    elif cmd == "list":
        if not allow:
            return "allow-list ว่าง - คำสั่ง shell ทุกอย่างถามก่อน"
        return "allow-list:\n" + "\n".join(f"  - {p}" for p in allow)
    elif cmd == "remove" and len(parts) > 1:
        prefix = parts[1]
        if prefix in allow:
            allow.remove(prefix)
            cfg["allow_shell_prefix"] = allow
            save_config(cfg)
            return f"ลบ '{prefix}' ออกแล้ว"
        return f"'{prefix}' ไม่มีใน allow-list"
    elif cmd == "clear":
        cfg["allow_shell_prefix"] = []
        save_config(cfg)
        return "ล้าง allow-list แล้ว"
    return "ใช้: /permission add <prefix> | /permission list | /permission remove <prefix> | /permission clear"


def login_mode():
    console.print(Panel(Text("เข้าสู่ระบบ Yousini - เลือกซัพพโรเวียร์เดอร์", style="bold cyan"),
                   border_style="magenta"))
    cfg = load_config()
    current_provider = cfg.get("default_provider", "groq")

    t = Text()
    t.append("เลือกซัพพโรเวียร์ (หรือพิมพ์ custom เพื่อกำหนดเอง):\n\n", style="dim")
    providers = {
        "openrouter": {"name": "OpenRouter (ฟรี)", "base_url": "https://openrouter.ai/api/v1",
                       "models": ["cohere/north-mini-code:free", "nvidia/nemotron-3-ultra-550b-a12b:free",
                                  "poolside/laguna-m.1:free", "nvidia/nemotron-3-super-120b-a12b:free",
                                  "nousresearch/hermes-3-llama-3.1-405b:free"]},
        "groq": {"name": "Groq", "base_url": "https://api.groq.com/openai/v1",
                 "models": ["openai/gpt-oss-120b", "llama-3.3-70b-versatile"]},
        "openai": {"name": "OpenAI", "base_url": "https://api.openai.com/v1",
                   "models": ["gpt-4o", "gpt-4o-mini"]},
        "deepseek": {"name": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
                     "models": ["deepseek-chat"]},
        "anthropic": {"name": "Anthropic", "base_url": "https://api.anthropic.com/v1",
                      "models": ["claude-3-5-sonnet-20241022"]}
    }
    for key, val in providers.items():
        marker = "✓ " if key == current_provider else "  "
        t.append(f"  {marker}", style="green" if key == current_provider else "dim")
        t.append(f"{key}", style="bold cyan")
        t.append(f" — {val['name']}\n", style="dim")
    t.append("\n  custom — กำหนดเอง (URL/โมเดลอิสระ)\n", style="yellow")
    console.print(t)

    choice = input("\nเลือก (Enter เพื่อยกเลิก): ").strip().lower()
    if not choice:
        console.print(Text("ยกเลิก", style="yellow")); return

    provider_key = choice if choice in providers or choice == "custom" else None
    if not provider_key:
        console.print(Text("ไม่เลือกหรือพิมพ์ผิด - ยกเลิก", style="red")); return

    api_key = input(f"ป้อน API Key สำหรับ {provider_key}: ").strip()
    if not api_key:
        console.print(Text("ต้องใส่ API Key - ยกเลิก", style="red")); return

    if provider_key == "custom":
        base_url = input("ป้อน Base URL (เช่น https://api.example.com/v1): ").strip()
        model = input("ป้อนโมเดล (เช่น model-name): ").strip()
        if not base_url or not model:
            console.print(Text("ต้องใส่ทั้ง URL และโมเดล - ยกเลิก", style="red")); return
    else:
        p = providers[provider_key]
        base_url = p["base_url"]
        t = Text()
        for i, m in enumerate(p["models"]):
            t.append(f"  {i+1}. {m}\n", style="cyan")
        t.append(f"  0. กำหนดเอง (custom)\n", style="yellow")
        console.print(t)
        model_choice = input(f"เลือกโมเดล (1-{len(p['models'])}, 0=กำหนดเอง): ").strip()
        if model_choice == "0":
            model = input("ป้อนโมเดล: ").strip()
            if not model:
                console.print(Text("ต้องใส่โมเดล - ยกเลิก", style="red")); return
        elif model_choice.isdigit() and 1 <= int(model_choice) <= len(p["models"]):
            model = p["models"][int(model_choice) - 1]
        else:
            model = p["models"][0]  # default

    # บันทึก config
    cfg = load_config()
    cfg["default_provider"] = provider_key
    cfg["providers"] = {provider_key: {"api_key": api_key, "base_url": base_url, "model": model}}
    save_config(cfg)
    # Auto-apply so the change takes effect immediately (no restart needed)
    _apply_provider_config(cfg)
    console.print(Text(f"\n✅ บันทึกและเปิดใช้ provider: {provider_key}, โมเดล: {model}", style="green"))


def plan_mode():
    """Plan Mode — agent generates a task plan, user confirms, then executes step-by-step.
    Flow: goal → plan → confirm → execute loop (run → check → fix if needed)."""
    console.print(Panel(Text("📋 แผนโหมด — Agent จะวางแผนและดำเนินการตามลำดับ", style="bold cyan"),
                        border_style="magenta"))

    # Step 1: Get goal from user
    goal = input("\nเป้าหมายของคุณ: ").strip()
    if not goal:
        console.print(Text("ยกเลิก — ไม่ได้ระบุเป้าหมาย", style="red")); return

    # Step 2: Generate plan via LLM
    console.print(Text("\n⏺ กำลังวิเคราะห์เป้าหมายและสร้างแผน...", style=C_THINK))
    plan_prompt = (
        f"คุณเป็น senior developer วางแผนการทำงานให้เสร็จสมบูรณ์ "
        f"เป้าหมาย: {goal}\n\n"
        f"สร้างแผนงานเป็น JSON รายการ step ดังนี้:\n"
        f"[\n"
        f'  {{"id": 1, "action": "อ่าน/เขียน/รันโค้ด", "detail": "..."}},\n'
        f'  {{"id": 2, "action": "edit_file", "detail": "..."}},\n'
        f'  {{"id": 3, "action": "run_test", "detail": "..."}}\n'
        f']\n\n'
        f"ตอบกลับเป็น JSON list เท่านั้น ไม่ต้องอธิบายเพิ่ม"
    )
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": plan_prompt}],
            temperature=0.3, max_tokens=2000
        )
        plan_text = resp.choices[0].message.content.strip()
        # Try to parse as JSON list
        try:
            plan_steps = json.loads(plan_text)
        except json.JSONDecodeError:
            # If not JSON, wrap in a single step
            plan_steps = [{"id": 1, "action": "general", "detail": plan_text}]
    except Exception as e:
        console.print(Text(f"Error สร้างแผน: {e}", style="red"))
        return

    # Step 3: Show plan to user
    t = Text()
    t.append("\n📋 แผนดำเนินการ:\n", style="bold cyan")
    for step in plan_steps if isinstance(plan_steps, list) else [plan_steps]:
        sid = step.get("id", "?")
        action = step.get("action", "general")
        detail = step.get("detail", str(step))
        t.append(f"  {sid}. ", style="bold yellow")
        t.append(f"[{action}] ", style="cyan")
        t.append(f"{_truncate(detail, 120)}\n", style="")
    console.print(Panel(t, title="Plan", border_style="blue"))

    # Step 4: Confirm
    confirm = input("\nเริ่มดำเนินการตามแผน? [y/N] ").strip().lower()
    if confirm not in ("y", "yes", "เอา"):
        console.print(Text("ยกเลิกแผน", style="yellow")); return

    # Step 5: Execute plan step-by-step
    agent = Agent()
    results = []
    for i, step in enumerate(plan_steps if isinstance(plan_steps, list) else [plan_steps]):
        action = step.get("action", "general")
        detail = step.get("detail", "")
        console.print(Text(f"\n⏩ Step {i+1}/{len(plan_steps)}: [{action}]", style=C_TOOL))

        if action in ("run_test", "test"):
            result = agent.shell(f"python -m pytest {detail or '.'} -x -q 2>&1 | tail -20", timeout=60)
        elif action in ("edit_file", "write", "create"):
            result = agent.write_file(
                step.get("path", "file.py"),
                step.get("content", detail)
            ) if "path" in step else agent.edit_file(
                step.get("path", ""),
                step.get("old_string", ""),
                step.get("new_string", detail)
            )
        elif action in ("shell", "command", "run"):
            result = agent.shell(detail, timeout=60)
        elif action in ("read", "inspect"):
            result = agent.read_file(detail or ".", limit=3000)
        else:
            # General: send to LLM with the detail as task
            agent.messages.append({"role": "user", "content": detail})
            result = chat_turn(agent, detail)

        results.append({"step": i+1, "action": action, "result": result})
        console.print(Text(f"   ✅ Step {i+1} เสร็จ", style=C_OK))

    # Step 6: Summary
    success = all(r.get("result") and "Error" not in str(r.get("result", "")) for r in results)
    console.print(Panel(
        Text(f"{'✅ แผนเสร็จสิ้น!' if success else '❌ มีข้อผิดพลาดบางข้อ'}  ({len(results)} steps)",
             style="bold green" if success else "bold red"),
        title="Plan Result"
    ))


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
    from yousini_lsp import LSPEngine, _path_to_uri

    web_ui = _load_webui()
    sessions = {}          # sid -> Agent
    locks = {}             # sid -> Lock (กันรันทับกันในเซสชันเดียว)
    reg_lock = threading.Lock()
    store = SessionStore(SESSION_DIR)
    lsp = LSPEngine(root=str(Path.cwd()))
    serve_started = time.time()

    def stats_json():
        """dashboard — รวมสถิติ server/usage/sessions/market/team/symbols"""
        import sqlite3
        out = {
            "server": {"model": MODEL, "version": APP_VERSION, "cwd": str(Path.cwd()),
                       "safe": safe, "auth": bool(token),
                       "uptime_s": int(time.time() - serve_started)},
        }
        try:
            from yousini_usage import stats as _ustats
            out["usage"] = _ustats()
        except Exception as e:
            out["usage"] = {"error": str(e)}
        try:
            from yousini_sessions_db import SessionSearch
            SessionSearch(SESSION_DIR / "search.db")  # สร้าง schema ถ้ายังไม่มี
            conn = sqlite3.connect(str(SESSION_DIR / "search.db"))
            out["sessions"] = {
                "count": conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
                "recent": [
                    {"name": r[0], "saved_at": r[1], "msgs": r[2]}
                    for r in conn.execute(
                        "SELECT s.name, s.saved_at, "
                        "(SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) "
                        "FROM sessions s ORDER BY s.saved_at DESC LIMIT 8")],
            }
            conn.close()
        except Exception as e:
            out["sessions"] = {"error": str(e)}
        try:
            from yousini_marketplace import installed_list, marketplace_enabled
            cfg = _read_cfg_light()
            out["market"] = {"enabled": marketplace_enabled(cfg),
                             "installed": len(installed_list())}
        except Exception as e:
            out["market"] = {"error": str(e)}
        try:
            from yousini_team import team_status
            ts = team_status(_read_cfg_light())
            out["team"] = {"active": bool(ts.get("active")),
                           "name": ts.get("name"), "workspace": ts.get("workspace"),
                           "users": len(ts.get("users", []))}
        except Exception:
            out["team"] = {"active": False}
        try:
            from yousini_symbols import SymbolIndex
            s = SymbolIndex(str(Path.cwd())).summary()
            out["symbols"] = s
        except Exception:
            out["symbols"] = {"total": 0, "files": 0}
        try:
            from yousini_queue import counts as _qcounts
            out["queue"] = _qcounts()
        except Exception:
            out["queue"] = {"pending": 0, "running": 0, "done": 0, "failed": 0}
        return {"ok": True, **out}


    def resolve_file(file: str):
        p = Path(file or "")
        if not p.is_absolute():
            p = Path.cwd() / p
        return p.resolve()

    def lsp_json_ok(method: str, payload: dict):
        """รัน LSP query ผ่าน HTTP → dict JSON (รับทั้ง stdio editor และ web UI)"""
        try:
            if method == "summary":
                return {"ok": True, "result": lsp.summary()}
            if method == "workspace-symbols":
                return {"ok": True, "symbols": lsp.workspace_symbols(payload.get("query", ""))}
            path = resolve_file(payload.get("file", ""))
            uri = _path_to_uri(path)
            line = int(payload.get("line", 0))
            char = int(payload.get("character", 0))
            if method == "hover":
                return {"ok": True, "result": lsp.hover(uri, line, char)}
            if method == "definition":
                return {"ok": True, "result": lsp.definition(uri, line, char)}
            if method == "references":
                return {"ok": True, "references": lsp.references(uri, line, char)}
            if method == "document-symbols":
                return {"ok": True, "symbols": lsp.document_symbols(uri)}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": False, "error": f"method ไม่รู้จัก: {method}"}

    def market_json(action: str, payload: dict):
        """marketplace ผ่าน HTTP — เรียกโมดูล yousini_marketplace โดยตรง"""
        try:
            from yousini_marketplace import (search_catalog, fetch_catalog, installed_list,
                                             install as _mi, uninstall as _mu,
                                             update as _mup, pkg_info,
                                             marketplace_enabled, format_info,
                                             registry_url)
            cfg = _read_cfg_light()
            if not marketplace_enabled(cfg):
                return {"ok": False, "error": "marketplace ถูกปิดใช้งาน"}
            if action == "catalog":
                return {"ok": True, "packages": search_catalog(payload.get("query", ""), cfg),
                        "registry": registry_url(cfg)}
            if action == "installed":
                return {"ok": True, "packages": installed_list()}
            if action == "install":
                src = payload.get("source", "")
                if not src:
                    return {"ok": False, "error": "ต้องระบุ source"}
                return _mi(src, project=bool(payload.get("project")),
                           force=bool(payload.get("force")), cfg=cfg)
            if action == "uninstall":
                return _mu(payload.get("id", ""))
            if action == "update":
                return _mup(payload.get("id", ""), cfg=cfg)
            if action == "info":
                return {"ok": True, "info": format_info(pkg_info(payload.get("id", ""), cfg))}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": False, "error": f"action ไม่รู้จัก: {action}"}

    def queue_json(action: str, payload: dict):
        """agent collaboration queue ผ่าน HTTP"""
        from yousini_queue import (enqueue, get, claim, complete, fail, requeue,
                                   list_tasks, counts)
        if action == "status":
            return {"ok": True, "counts": counts(),
                    "tasks": list_tasks(limit=20)}
        if action == "enqueue":
            prompt = (payload.get("prompt") or "").strip()
            if not prompt:
                return {"ok": False, "error": "ต้องระบุ prompt"}
            t = enqueue(prompt, worker=payload.get("worker") or "default",
                        from_=payload.get("from") or "api",
                        priority=payload.get("priority") or 0)
            return {"ok": True, "task": t}
        if action == "claim":
            t = claim(payload.get("worker") or "default")
            return {"ok": True, "task": t, "claimed": bool(t)}
        if action == "complete":
            t = complete(payload.get("id", ""), result=payload.get("result", ""))
            if not t:
                return {"ok": False, "error": "ไม่พบงาน"}
            return {"ok": True, "task": t}
        if action == "fail":
            t = fail(payload.get("id", ""), error=payload.get("error", ""))
            if not t:
                return {"ok": False, "error": "ไม่พบงาน"}
            return {"ok": True, "task": t}
        if action == "requeue":
            t = requeue(payload.get("id", ""))
            return {"ok": True, "task": t}
        if action == "get":
            return {"ok": True, "task": get(payload.get("id", ""))}
        return {"ok": False, "error": f"action ไม่รู้จัก: {action}"}

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

        def _client_token(self):
            hdr = self.headers.get("X-Yousini-Token") or ""
            if hdr:
                return hdr
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                return auth[7:]
            q = urllib.parse.urlparse(self.path).query
            return urllib.parse.parse_qs(q).get("token", [""])[0]

        def _auth_user(self):
            """คืน (name, role) หรือ None — multi-user ผ่าน users config (team.json/config.json)"""
            try:
                from yousini_team import role_for_token
                return role_for_token(self._client_token(), _read_cfg_light(), master_token=token)
            except Exception:
                pass
            if not token or self._client_token() == token:
                return ("local", "admin")
            return None

        def _auth_ok(self):
            return self._auth_user() is not None

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
                info = {"model": MODEL, "name": "Yousini",
                        "version": APP_VERSION, "cwd": str(Path.cwd()),
                        "safe": safe, "auth": bool(token)}
                au = self._auth_user()
                if au:
                    info["user"] = au[0]
                    info["role"] = au[1]
                try:
                    from yousini_team import team_status
                    ts = team_status(_read_cfg_light())
                    if ts.get("active"):
                        info["workspace"] = ts.get("name")
                        info["workspace_id"] = ts.get("workspace")
                except Exception:
                    pass
                if _HAS_MONET:
                    try:
                        cfg = _read_cfg_light()
                        info["tier"] = cfg.get("tier", "free")
                        info["ads_enabled"] = not (cfg.get("ads_disabled")
                                                   or cfg.get("tier") == "pro")
                        info["usage_enabled"] = _usage_enabled()
                        info["sponsor"] = _sponsor_line(cfg)
                    except Exception:
                        pass
                self._send(200, json.dumps(info, ensure_ascii=False),
                           "application/json; charset=utf-8")
            elif path == "/health":
                self._send(200, "ok")
            elif path == "/api/lsp/summary":
                if not self._auth_ok():
                    return self._send(401, json.dumps({"error": "unauthorized"}),
                                      "application/json; charset=utf-8")
                self._send(200, json.dumps(lsp_json_ok("summary", {}), ensure_ascii=False),
                           "application/json; charset=utf-8")
            elif path in ("/api/market/catalog", "/api/market/installed"):
                if not self._auth_ok():
                    return self._send(401, json.dumps({"error": "unauthorized"}),
                                      "application/json; charset=utf-8")
                action = path.rsplit("/", 1)[-1]
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("q", [""])[0]
                self._send(200, json.dumps(market_json(action, {"query": query}),
                                           ensure_ascii=False),
                           "application/json; charset=utf-8")
            elif path == "/api/stats":
                if not self._auth_ok():
                    return self._send(401, json.dumps({"error": "unauthorized"}),
                                      "application/json; charset=utf-8")
                self._send(200, json.dumps(stats_json(), ensure_ascii=False),
                           "application/json; charset=utf-8")
            elif path == "/api/queue/status":
                if not self._auth_ok():
                    return self._send(401, json.dumps({"error": "unauthorized"}),
                                      "application/json; charset=utf-8")
                self._send(200, json.dumps(queue_json("status", {}), ensure_ascii=False),
                           "application/json; charset=utf-8")
            elif path.startswith("/api/queue/get"):
                if not self._auth_ok():
                    return self._send(401, json.dumps({"error": "unauthorized"}),
                                      "application/json; charset=utf-8")
                qid = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("id", [""])[0]
                self._send(200, json.dumps(queue_json("get", {"id": qid}), ensure_ascii=False),
                           "application/json; charset=utf-8")
            else:
                self._send(404, "not found")

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            if path.startswith("/api/market/"):
                au = self._auth_user()
                if not au:
                    return self._send(401, json.dumps({"error": "unauthorized"}),
                                      "application/json; charset=utf-8")
                action = path[len("/api/market/"):].strip("/")
                if action in ("install", "uninstall", "update") and au[1] != "admin":
                    return self._send(403, json.dumps({"error": "ต้องมีสิทธิ์ admin ในการจัดการ marketplace"},
                                                      ensure_ascii=False),
                                      "application/json; charset=utf-8")
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    payload = json.loads(self.rfile.read(length) or "{}")
                except Exception:
                    payload = {}
                return self._send(200, json.dumps(market_json(action, payload),
                                                  ensure_ascii=False),
                                  "application/json; charset=utf-8")
            if path.startswith("/api/lsp/"):
                if not self._auth_ok():
                    return self._send(401, json.dumps({"error": "unauthorized"}),
                                      "application/json; charset=utf-8")
                method = path[len("/api/lsp/"):].strip("/")
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    payload = json.loads(self.rfile.read(length) or "{}")
                except Exception:
                    payload = {}
                return self._send(200, json.dumps(lsp_json_ok(method, payload),
                                                  ensure_ascii=False),
                                  "application/json; charset=utf-8")
            if path.startswith("/api/webhook/"):
                name = path[len("/api/webhook/"):].strip("/")
                if not self._auth_ok():
                    return self._send(401, json.dumps({"error": "unauthorized"}),
                                      "application/json; charset=utf-8")
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    payload = json.loads(self.rfile.read(length) or "{}")
                except Exception:
                    payload = {}
                from yousini_webhook import run_webhook
                ok, out = run_webhook(name, payload)
                return self._send(200 if ok else 404,
                                  json.dumps({"ok": ok, "name": name, "result": str(out)[:2000]},
                                             ensure_ascii=False),
                                  "application/json; charset=utf-8")
            if path.startswith("/api/queue/"):
                if not self._auth_ok():
                    return self._send(401, json.dumps({"error": "unauthorized"}),
                                      "application/json; charset=utf-8")
                action = path[len("/api/queue/"):].strip("/")
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    payload = json.loads(self.rfile.read(length) or "{}")
                except Exception:
                    payload = {}
                return self._send(200, json.dumps(queue_json(action, payload),
                                                  ensure_ascii=False),
                                  "application/json; charset=utf-8")
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
            try:
                from yousini_team import users as _tu
                multi = bool(_tu(_read_cfg_light()))
            except Exception:
                multi = False
            au = self._auth_user()
            if multi and au:
                sid = f"{au[0]}:{sid}"

            agent, lock = get_agent(sid)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            def _chunk(data: bytes) -> bytes:
                return ("%x\r\n" % len(data)).encode("ascii") + data + b"\r\n"

            def emit(ev):
                data = ("data: " + json.dumps(ev, ensure_ascii=False)
                        + "\n\n").encode("utf-8")
                self.wfile.write(_chunk(data))
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
            try:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
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


def lsp_main(root: str = "."):
    """LSP server แบบ stdio JSON-RPC 2.0 (Content-Length framing) สำหรับ editor
    สำคัญ: stdout ต้องสะอาดสำหรับ JSON-RPC เท่านั้น จึงเขียน log ไป stderr"""
    from yousini_lsp import lsp_main as _lsp_run
    _lsp_run(root=root)


def marketplace_main(argv=None):
    """CLI: yousini marketplace <list|search|installed|install|uninstall|update|info>"""
    from yousini_marketplace import (fetch_catalog, search_catalog, installed_list,
                                     install as _mkt_install, uninstall as _mkt_uninstall,
                                     update as _mkt_update, update_all as _mkt_update_all,
                                     pkg_info, format_catalog, format_installed,
                                     format_info, marketplace_enabled, registry_url)
    argv = list(argv or [])
    cfg = _read_cfg_light()

    def usage():
        console.print(Text("ใช้: yousini marketplace [list|search <คำ>|installed|install <id|url|path>|"
                           "uninstall <id>|update <id>|update --all|info <id>]", style="yellow"))

    if not marketplace_enabled(cfg):
        console.print(Text("Marketplace ถูกปิดใช้งาน — ตั้ง marketplace_enabled: true ใน config.json", style="red"))
        return
    if not argv or argv[0] in ("help", "--help", "-h"):
        usage()
        return

    cmd = argv[0]
    rest = argv[1:]

    if cmd == "list":
        pkgs = fetch_catalog(cfg)
        console.print(Panel(format_catalog(pkgs), title="Marketplace catalog",
                            border_style="magenta", padding=(1, 2)))
        console.print(Text(f"registry: {registry_url(cfg)}", style="dim"))
    elif cmd == "search":
        q = " ".join(rest).strip()
        pkgs = search_catalog(q, cfg)
        console.print(Panel(format_catalog(pkgs), title=f"ค้นหา: '{q or 'ทั้งหมด'}'",
                            border_style="magenta", padding=(1, 2)))
    elif cmd in ("installed", "local"):
        console.print(Panel(format_installed(), title="Packages ที่ติดตั้ง",
                            border_style="green", padding=(1, 2)))
    elif cmd == "install":
        if not rest:
            console.print(Text("ใช้: yousini marketplace install <id|url|path> [--project] [--force]", style="red"))
            return
        source = rest[0]
        project = "--project" in rest
        force = "--force" in rest
        console.print(Text(f"กำลังติดตั้ง: {source} ...", style="dim"))
        r = _mkt_install(source, project=project, force=force, cfg=cfg)
        if r["ok"]:
            rows = [f"ติดตั้งสำเร็จ: {r['name']} v{r['version']}",
                    f"skills: {', '.join(r['skills']) or '—'}",
                    f"tool plugins (MCP): {', '.join(r['mcp']) or '—'}"]
            console.print(Panel("\n".join(rows), title=f"{r['id']}",
                                border_style="green", padding=(1, 2)))
            console.print(Text("รัน /reload (หรือรีสตาร์ท) เพื่อโหลด skills ใหม่", style="dim"))
        else:
            console.print(Text(f"ติดตั้งไม่สำเร็จ: {r.get('error', '?')}", style="red"))
    elif cmd == "uninstall":
        if not rest:
            console.print(Text("ใช้: yousini marketplace uninstall <id>", style="red"))
            return
        r = _mkt_uninstall(rest[0])
        if r["ok"]:
            console.print(Text(f"ถอนการติดตั้ง '{r['id']}' แล้ว (ลบ {r['removed_skills']} skills, "
                               f"{r['mcp_removed']} MCP servers)", style="green"))
        else:
            console.print(Text(r.get("error", "?"), style="red"))
    elif cmd == "update":
        if "--all" in rest:
            results = _mkt_update_all(cfg)
            for r in results:
                console.print(Text(f"{r['id']}: {'อัปเดตเป็น v'+str(r.get('version','?')) if r['ok'] else r.get('error','?')}",
                                   style="green" if r["ok"] else "red"))
        elif rest:
            r = _mkt_update(rest[0], cfg=cfg)
            console.print(Text(f"{r['id']}: {'อัปเดตเป็น v'+str(r.get('version','?')) if r['ok'] else r.get('error','?')}",
                               style="green" if r["ok"] else "red"))
        else:
            console.print(Text("ใช้: yousini marketplace update <id> หรือ update --all", style="red"))
    elif cmd == "info":
        if not rest:
            console.print(Text("ใช้: yousini marketplace info <id>", style="red"))
            return
        console.print(Panel(format_info(pkg_info(rest[0], cfg)), title="Package info",
                            border_style="cyan", padding=(1, 2)))
    else:
        usage()


def agent_main(argv=None):
    """CLI: yousini agent <send|status|result|requeue|prune|clear> + yousini work [--once]"""
    from yousini_queue import (enqueue, get, counts, list_tasks, requeue, prune_done,
                               clear, reclaim_stale, format_task, format_queue)
    argv = list(argv or [])
    if not argv:
        console.print(Panel(format_queue(list_tasks(), title="Queue") + "\n\n" +
                            "pending {pending} · running {running} · done {done} · failed {failed}".format(**counts()),
                            title="Agent queue", border_style="cyan", padding=(1, 2)))
        console.print(Text("ใช้: yousini agent send <worker> <โจทย์> | status | result <id> | requeue <id> | prune | clear",
                           style="dim"))
        return
    cmd = argv[0].lower()
    if cmd == "send" and len(argv) > 2:
        worker = argv[1]
        prompt = " ".join(argv[2:])
        t = enqueue(prompt, worker=worker, from_="cli")
        console.print(Text(f"ส่งงานแล้ว: #{t['id']} → worker '{worker}' (รอในคิว)", style="green"))
        console.print(Text("worker รัน `yousini work` เพื่อรับงาน (หรือรอให้มันดึงผ่าน API)", style="dim"))
    elif cmd == "status":
        c = counts()
        console.print(Panel(format_queue(list_tasks(), title="Queue") + "\n\n" +
                            "pending {pending} · running {running} · done {done} · failed {failed}".format(**c),
                            title="Agent queue", border_style="cyan", padding=(1, 2)))
    elif cmd == "result" and len(argv) > 1:
        console.print(Panel(format_task(get(argv[1])), title="Task", border_style="cyan",
                            padding=(1, 2)))
    elif cmd == "requeue" and len(argv) > 1:
        t = requeue(argv[1])
        console.print(Text(f"requeue #{argv[1]} → {t.get('status') if t else 'ไม่พบ'}", style="green"))
    elif cmd == "prune":
        n = prune_done()
        console.print(Text(f"ลบงานที่เสร็จแล้วเกินเกณฑ์ {n} งาน", style="green"))
    elif cmd == "clear":
        n = clear()
        console.print(Text(f"ล้างคิว {n} งาน", style="green"))
    elif cmd == "reclaim":
        n = reclaim_stale()
        console.print(Text(f"ย้อนงานที่ค้าง 'running' กลับเป็น pending {n} งาน", style="yellow"))
    else:
        console.print(Text("ใช้: yousini agent send <worker> <โจทย์> | status | result <id> | requeue <id> | prune | clear",
                           style="red"))


def work_main(once=False, interval=5.0, worker="default", max_tasks=50):
    """worker loop: ดึงงานจากคิว → รัน → บันทึกผล. --once = รอบเดียว"""
    from yousini_queue import counts, process_once, reclaim_stale
    if once:
        reclaim_stale()
        done = process_once(worker=worker, max_tasks=max_tasks)
        console.print(Text(f"Worker '{worker}' ทำงานเสร็จ {len(done)} งาน", style="green"))
        return
    console.print(Text(f"Worker '{worker}' เริ่มรอรับงาน (poll ทุก {interval}s) — Ctrl+C หยุด", style="cyan"))
    while True:
        try:
            reclaim_stale()
            c = counts()
            if c["pending"]:
                done = process_once(worker=worker, max_tasks=max_tasks)
                for t in done:
                    tag = f"#{t.get('id')}"
                    if t.get("status") == "done":
                        console.print(Text(f"✅ {tag} เสร็จ ({len(t.get('result') or '')} ตัวอักษร)", style="green"))
                    else:
                        console.print(Text(f"❌ {tag} ล้ม: {t.get('error')}", style="red"))
        except KeyboardInterrupt:
            console.print(Text("\nหยุด worker", style="dim"))
            break
        except Exception as e:
            console.print(Text(f"worker error: {e}", style="red"))
        time.sleep(interval)


def team_main(argv=None):
    """CLI: yousini team <status|init|join|leave|users|set-registry>"""
    from yousini_team import (team_status, init as _init, join as _join, leave as _leave,
                              users as _users, set_registry as _set_reg, format_status,
                              resolve_registry)
    argv = list(argv or [])
    if not argv:
        console.print(Panel(format_status(team_status(load_config())), title="Team workspace",
                            border_style="cyan", padding=(1, 2)))
        console.print(Text("ใช้: yousini team [status|init <ชื่อ>|join <url>|leave|users|set-registry <url>]",
                           style="dim"))
        return
    cmd = argv[0].lower()
    cfg = load_config()
    if cmd == "status":
        console.print(Panel(format_status(team_status(cfg)), title="Team workspace",
                            border_style="cyan", padding=(1, 2)))
    elif cmd == "init" and len(argv) > 1:
        r = _init(" ".join(argv[1:]))
        if r.get("ok"):
            console.print(Text(f"สร้าง workspace แล้ว: {r.get('name')} (id: {r.get('workspace')})", style="green"))
        else:
            console.print(Text(r.get("error", "ผิดพลาด"), style="red"))
    elif cmd == "join" and len(argv) > 1:
        r = _join(argv[1])
        if r.get("ok"):
            console.print(Text(f"เข้าร่วมทีมแล้ว: {r.get('name')} (id: {r.get('workspace')})", style="green"))
        else:
            console.print(Text(r.get("error", "ผิดพลาด"), style="red"))
    elif cmd == "leave":
        r = _leave()
        console.print(Text("ออกจาก workspace แล้ว" if r.get("ok") else "ผิดพลาด",
                           style="green" if r.get("ok") else "red"))
    elif cmd == "users":
        us = _users(cfg)
        if not us:
            console.print(Text("ยังไม่มีผู้ใช้ — เพิ่มใน config.json (users) หรือ team.json", style="dim"))
        else:
            for u in us:
                console.print(Text(f"  {u['name']}  ({u['role']})  token={u['token'][:6]}…" if u.get("token")
                                   else f"  {u['name']}  ({u['role']})  (ไม่มี token)", style="cyan"))
        console.print(Text("registry ที่ใช้: " + (resolve_registry(cfg) or "-"), style="dim"))
    elif cmd == "set-registry" and len(argv) > 1:
        r = _set_reg(argv[1])
        console.print(Text(f"registry ทีม = {r.get('registry') or '(ว่าง → ใช้ค่าเริ่มต้น)'}",
                           style="green" if r.get("ok") else "red"))
    else:
        console.print(Text("ใช้: yousini team [status|init <ชื่อ>|join <url>|leave|users|set-registry <url>]",
                           style="red"))


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
                    "spawn_subagent", "batch_edit_files", "run_test_loop") and not allow_exec:
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


def _providers_cmd():
    """แสดง provider chain + ตัวที่กำลังใช้"""
    provs = _load_providers()
    if not provs:
        console.print(Text("ไม่มี provider กำหนด (ใส่ YOUSINI_API_KEY ใน .env)", style="yellow"))
        return
    t = Text()
    for i, p in enumerate(provs):
        mark = "▶" if i == client.current else " "
        host = str(p["base_url"]).replace("https://", "").replace("/v1", "").rstrip("/")
        key = str(p["api_key"])
        t.append(f"{mark} #{i + 1} {host}  ", style="bold cyan" if i == client.current else "dim")
        t.append(f"key={key[:6]}…{key[-3:]}\n", style="dim")
    console.print(Panel(t, title="Provider chain (fallback อัตโนมัติเมื่อโค้ต้าหมด)", border_style="magenta"))


def _symbols_cmd(agent, args=""):
    """/symbols | /symbols def <ชื่อ> | /symbols refs <ชื่อ> | /symbols list [คำ] — AST symbol index"""
    parts = args.split(None, 1)
    sub = parts[0].lower() if parts else ""
    name = parts[1].strip() if len(parts) > 1 else ""
    try:
        if sub in ("def", "find"):
            out = agent.symbols_tool(action="find", name=name)
        elif sub == "refs":
            out = agent.symbols_tool(action="refs", name=name)
        elif sub == "list":
            out = agent.symbols_tool(action="list", query=name)
        else:
            out = agent.symbols_tool(action="summary")
    except Exception as e:
        out = f"Error: {e}"
    console.print(Panel(Text(out), title="🧭 Symbol Index", border_style="cyan"))


def _git_cmd(agent, args=""):
    """/git | /git log [n] | /git blame <ไฟล์> <บรรทัด> | /git status | /git diff | /git full"""
    parts = args.split()
    sub = parts[0].lower() if parts else "status"
    try:
        if sub == "log" and len(parts) > 1 and parts[1].isdigit():
            out = agent.git_tool(action="log", n=int(parts[1]))
        elif sub == "log":
            out = agent.git_tool(action="log", n=10)
        elif sub == "full":
            out = agent.git_tool(action="full", n=int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 6)
        elif sub == "status":
            out = agent.git_tool(action="status")
        elif sub == "diff":
            out = agent.git_tool(action="diff")
        elif sub == "blame" and len(parts) >= 3:
            out = agent.git_tool(action="blame", file=parts[1], line=int(parts[2]))
        else:
            out = "ใช้: /git | /git log [n] | /git full [n] | /git status | /git diff | /git blame <ไฟล์> <บรรทัด>"
    except Exception as e:
        out = f"Error: {e}"
    console.print(Panel(Text(out), title="🌀 Git", border_style="green"))


def _cron_cmd(agent, args=""):
    """จัดการงาน cron จาก REPL (/cron list|add|remove|pause|resume)"""
    from yousini_cron import JobStore, parse_schedule
    store = JobStore()
    parts = args.split(None, 1)
    sub = parts[0].lower() if parts else ""
    if not sub:
        rows = store.list()
        if not rows:
            console.print(Text("ยังไม่มีงาน cron — ใช้ /cron add <schedule> <prompt> เช่น /cron add 30m สรุปงานวันนี้", style="yellow"))
            return
        t = Text()
        for j in rows:
            st = "▶" if j["enabled"] else "⏸"
            t.append(f"{st} #{j['id']} {j['name']} ", style="bold cyan")
            t.append(f"[{j['schedule']}]  รันล่าสุด: {j['last_run'] or '—'}\n", style="dim")
            t.append(f"   {j['prompt'][:80]}\n", style="white")
        console.print(Panel(t, title=f"Cron jobs ({len(rows)})", border_style="magenta"))
        return
    if sub == "add" and len(parts) > 1:
        sch, _, prompt = parts[1].partition(" ")
        if not prompt:
            console.print(Text("ใช้: /cron add <schedule> <prompt> เช่น /cron add 0 9 * * * สรุปข่าวเช้า", style="yellow"))
            return
        if parse_schedule(sch)[0] == "invalid":
            console.print(Text(f"schedule '{sch}' ไม่ถูกต้อง (ลอง 30m, 0 9 * * *, 2026-08-11T10:00:00)", style="red"))
            return
        j = store.add(prompt[:30], sch, prompt, cwd=agent.cwd)
        console.print(Text(f"เพิ่มงาน #{j['id']} '{j['name']}' แล้ว (ทุก {sch})", style="green"))
        return
    if sub == "remove" and len(parts) > 1:
        try:
            jid = int(parts[1])
        except ValueError:
            console.print(Text("ใส่ id ตัวเลข", style="red")); return
        if store.get(jid):
            store.remove(jid)
            console.print(Text(f"ลบงาน #{jid} แล้ว", style="yellow"))
        else:
            console.print(Text(f"ไม่พบงาน #{jid}", style="red"))
        return
    if sub in ("pause", "resume") and len(parts) > 1:
        try:
            jid = int(parts[1])
        except ValueError:
            console.print(Text("ใส่ id ตัวเลข", style="red")); return
        j = store.set_enabled(jid, sub == "resume")
        if j:
            console.print(Text(f"งาน #{jid} {'▶ resume แล้ว' if sub == 'resume' else '⏸ pause แล้ว'}", style="green"))
        else:
            console.print(Text(f"ไม่พบงาน #{jid}", style="red"))
        return
    console.print(Text("ใช้: /cron | /cron add <schedule> <prompt> | /cron remove <id> | /cron pause|resume <id>", style="yellow"))


def _set_ads(disabled: bool):
    cfg = _read_cfg_light()
    cfg["ads_disabled"] = bool(disabled)
    save_config(cfg)


def _usage_status_text() -> str:
    on = _usage_enabled() if _HAS_MONET else False
    head = ("เปิดใช้งาน (เก็บเฉพาะในเครื่อง, ไม่ส่งออก)" if on
            else "ปิดใช้งาน — สั่ง /usage on เพื่อเริ่มเก็บ")
    return f"สถานะ: {head}\n\n{_usage_summary()}" if _HAS_MONET else "โมดูล usage ยังไม่พร้อม"


def _format_tier(ti: dict) -> str:
    price = f"${ti['price']}/เดือน" if ti["price"] else "ฟรี"
    lines = [f"Tier: {ti['label'].upper()} ({ti['tier']})",
             f"ราคา: {price}",
             f"License: {ti['license_key']}",
             "สิทธิ์ (entitlements):"]
    for k, v in ti["entitlements"].items():
        lines.append(f"  {k:<18}: {'เปิด' if v else 'ปิด'}")
    return "\n".join(lines)


def _repl_market(args: str):
    """/market ... — ติดตั้ง/ค้นหา skills & tool plugins จาก marketplace"""
    from yousini_marketplace import (search_catalog, install as _mkt_install,
                                     uninstall as _mkt_uninstall, installed_list,
                                     format_installed, format_catalog,
                                     marketplace_enabled, registry_url)
    cfg = _read_cfg_light()
    if not marketplace_enabled(cfg):
        console.print(Text("Marketplace ถูกปิดใช้งาน (config.json → marketplace_enabled)", style="red"))
        return
    if not args:
        console.print(Panel(format_installed(), title="Marketplace — ติดตั้งแล้ว",
                            border_style="green", padding=(1, 2)))
        console.print(Text("ใช้: /market search <คำ>  |  /market install <id|url>  |  /market uninstall <id>",
                           style="dim"))
        return
    cmd, _, rest = args.partition(" ")
    rest = rest.strip()
    if cmd in ("search", "list"):
        pkgs = search_catalog(rest, cfg)
        console.print(Panel(format_catalog(pkgs, max_rows=15),
                            title=f"Marketplace — {rest or 'ทั้งหมด'}",
                            border_style="magenta", padding=(1, 2)))
    elif cmd == "install" and rest:
        console.print(Text(f"กำลังติดตั้ง: {rest} ...", style="dim"))
        r = _mkt_install(rest, project="--project" in rest, force="--force" in rest, cfg=cfg)
        if r["ok"]:
            console.print(Text(f"ติดตั้งสำเร็จ: {r['name']} v{r['version']} — "
                               f"skills {len(r['skills'])} · tools {len(r['mcp'])}", style="green"))
            console.print(Text("รัน /reload เพื่อโหลด skills ใหม่", style="dim"))
        else:
            console.print(Text(f"ติดตั้งไม่สำเร็จ: {r.get('error', '?')}", style="red"))
    elif cmd == "uninstall" and rest:
        r = _mkt_uninstall(rest)
        console.print(Text(f"ถอนการติดตั้ง '{r.get('id', rest)}' แล้ว" if r["ok"]
                           else r.get("error", "?"), style="green" if r["ok"] else "red"))
    else:
        console.print(Text("ใช้: /market [search <คำ>|install <id|url>|uninstall <id>]", style="yellow"))


def _print_session_summary():
    if not _HAS_MONET:
        return
    try:
        if _usage_enabled():
            console.print(Panel(_usage_summary(), title="สรุปการใช้งานเซสชันนี้",
                                border_style="cyan", padding=(1, 2)))
        line = _sponsor_line(_read_cfg_light())
        if line:
            console.print(Text(f"┄ {line}", style="dim"))
    except Exception:
        pass


_PLUGINS = None  # cache ของ plugin ที่โหลดแล้ว


def _load_plugins() -> dict:
    """โหลด plugin ถ้า flag plugin_system เปิด — ลงทะเบียน tool schema/impl เพิ่ม"""
    global _PLUGINS
    if _PLUGINS is not None:
        return _PLUGINS
    _PLUGINS = {"schemas": [], "impls": {}, "repl": {}, "cli": {}}
    try:
        from yousini_config import get_flag
        if not get_flag("plugin_system", True):
            return _PLUGINS
        from yousini_plugins import load_plugins
        agg = load_plugins()
        if agg["schemas"]:
            for _t in agg["schemas"]:
                _fn = _t.get("function", {})
                if _fn.get("required") == []:
                    _fn.pop("required", None)
                if _fn.get("name") and not any(
                        x.get("function", {}).get("name") == _fn["name"] for x in TOOLS):
                    TOOLS.append(_t)
            IMPL.update(agg["impls"])
        _PLUGINS["schemas"] = agg["schemas"]
        _PLUGINS["impls"] = agg["impls"]
        _PLUGINS["repl"] = agg["repl"]
        _PLUGINS["cli"] = agg["cli"]
    except Exception:
        pass
    return _PLUGINS


def _REPL_COMMANDS(agent):
    """รายการคำสั่ง REPL สำหรับ command palette"""
    return [
        ("/help", "แสดงทุกคำสั่ง"), ("/clear", "ล้างประวัติแชท"), ("/history", "ดูประวัติ"),
        ("/memory", "ดู/จัดการความจำระยะยาว"), ("/compact", "ยุบบริบท"), ("/quiet", "ซ่อนรายละเอียด tool"),
        ("/providers", "provider + ลำดับสำรอง"), ("/usage", "สถิติ token"), ("/todos", "รายการงาน"),
        ("/jobs", "งาน background"), ("/skills", "skills ที่โหลด"), ("/hooks", "hooks"),
        ("/checkpoint", "git commit จุดชั่วคราว"), ("/rollback", "ย้อน checkpoint"), ("/dev", "รวมตรวจโปรเจกต์"),
        ("/scaffold", "โครงโปรเจกต์"), ("/update", "ตรวจ/อัปเดต"), ("/config", "ดู/ตั้งค่า config"),
        ("/stream", "typewriter mode on|off"), ("/palette", "เปิด command palette"),
        ("/exit", "ออก"), ("/quit", "ออก"), ("/export", "สงออก session"), ("/import", "นำเข้า session"),
    ]
def _run_repl(agent: Agent):
    _setup_readline()
    _print_banner(agent)
    agent.hooks.run_session_start()
    atexit.register(lambda: agent.hooks.run_session_stop())
    store = SessionStore(SESSION_DIR)
    _ui_cmd_hints()
    while True:
        if low in ("/palette", "/p"):
            pick = _ui_palette(_REPL_COMMANDS(agent))
            if pick:
                console.print(Text(f"เลือก: {pick[0]}", style="dim"))
                user_input = pick[0] + " "
                low = user_input.lower().strip()
                continue
        if low.startswith("/stream"):
            mode = low[7:].strip().lower()
            if mode == "on":
                agent._typewriter = True
                console.print(Text("typewriter mode: คำตอบ Markdown จะป้อนทีละคำ", style="green"))
            elif mode == "off":
                agent._typewriter = False
                console.print(Text("typewriter mode: ปิด (แสดงคำตอบในกรอบทันที)", style="yellow"))
            else:
                st = "เปิด" if getattr(agent, "_typewriter", False) else "ปิด"
                console.print(Text(f"typewriter: {st} (ใช้ /stream on|off)", style="dim"))
            continue
        try:
            user_input = input("❯ ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print(Text("\nจบการทำงาน", style="dim"))
            _print_session_summary(); break
        if not user_input:
            continue
        low = user_input.lower()
        if low in ("/exit", "/quit"):
            console.print(Text("จบการทำงาน", style="dim"))
            _print_session_summary(); break
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
        if low == "/todos":
            agent._print_todos(); continue
        if low == "/providers":
            _providers_cmd(); continue
        if low.startswith("/memory"):
            args = user_input[7:].strip()
            if not args:
                t = Text()
                for key in ("user", "agent"):
                    t.append(f"[{key}]\n", style="bold cyan")
                    t.append((agent.memory.stores[key].to_text() if agent.memory else "") or "(ว่าง)\n", style="dim")
                console.print(Panel(t, title="ความจำระยะยาว (ข้าม session)", border_style="magenta")); continue
            parts = args.split(" ", 2)
            if len(parts) < 2 or parts[0].lower() not in ("add", "remove", "replace", "list"):
                console.print(Text("ใช้: /memory add|remove|replace|list <user|agent> [ข้อความ]", style="yellow")); continue
            act, target = parts[0].lower(), parts[1].lower()
            content = parts[2] if len(parts) > 2 else ""
            r = agent.memory_tool(act, target,
                                  content=content,
                                  old_text=content if act in ("remove", "replace") else "")
            console.print(Text(r, style="green" if "ต้อง" not in r else "yellow")); continue
        if low == "/compact":
            console.print(Text(agent.compact(), style=C_OK)); continue
        if low == "/quiet on" or low == "/quiet":
            agent.quiet_mode = True
            console.print(Text("Silent mode: ซ่อนรายละเอียด tool — แสดงแค่คำตอบ (มี spinner แสดงความคืบหน้า)", style="dim")); continue
        if low == "/quiet off":
            agent.quiet_mode = False
            console.print(Text("Normal mode: แสดงรายละเอียด tool call ทั้งหมด", style="green")); continue
        if low == "/usage":
            console.print(Panel(_usage_status_text(), title="Usage telemetry", border_style="magenta")); continue
        if low == "/usage on":
            _usage_set_enabled(True) if _HAS_MONET else None
            console.print(Text("เปิดเก็บสถิติการใช้งานแล้ว (เฉพาะในเครื่อง ไม่ส่งออก)", style="green")); continue
        if low == "/usage off":
            _usage_set_enabled(False) if _HAS_MONET else None
            console.print(Text("ปิดเก็บสถิติการใช้งานแล้ว", style="yellow")); continue
        if low == "/usage reset":
            _usage_reset() if _HAS_MONET else None
            console.print(Text("ล้างสถิติทั้งหมดแล้ว", style="yellow")); continue
        if low == "/usage report" or low.startswith("/usage report "):
            period = user_input[13:].strip().lower() or "weekly"
            r = _usage_report(period) if _HAS_MONET else "(ปิดใช้งาน)"
            console.print(Panel(r, title="Usage report", border_style="cyan", padding=(1, 2)))
            continue
        if low == "/ads on":
            _set_ads(False)
            console.print(Text("เปิด sponsor line แล้ว (ปิดได้ด้วย /ads off หรือ tier pro)", style="dim")); continue
        if low == "/ads off":
            _set_ads(True)
            console.print(Text("ปิด sponsor line แล้ว", style="green")); continue
        if low == "/ads status":
            console.print(Panel(_sponsor_status(_read_cfg_light()), title="Sponsor slot", border_style="magenta")); continue
        if low == "/tier":
            console.print(Panel(_format_tier(_billing_tier_info(_read_cfg_light())), title="สิทธิ์ (Tier)", border_style="magenta")); continue
        if low.startswith("/tier activate "):
            key = user_input[15:].strip()
            cfg = _read_cfg_light()
            ok, msg = _billing_activate(cfg, key)
            if ok:
                save_config(cfg)
            console.print(Text(msg, style="green" if ok else "red")); continue
        if low == "/tier off":
            cfg = _read_cfg_light()
            msg = _billing_deactivate(cfg)
            save_config(cfg)
            console.print(Text(msg, style="yellow")); continue
        if low == "/market" or low.startswith("/market "):
            _repl_market(user_input[8:].strip())
            continue
        if low == "/team" or low.startswith("/team "):
            from yousini_team import team_status, format_status
            console.print(Panel(format_status(team_status(_read_cfg_light())),
                                title="Team workspace", border_style="cyan", padding=(1, 2)))
            continue
        if low == "/agent" or low.startswith("/agent "):
            from yousini_queue import enqueue as _qe, get as _qget, counts as _qcounts, \
                list_tasks as _qlist, format_task, format_queue
            parts = user_input[7:].strip().split(None, 2)
            sub = parts[0].lower() if parts else "status"
            if sub == "send" and len(parts) >= 3:
                t = _qe(parts[2], worker=parts[1], from_="repl")
                console.print(Text(f"ส่งงานแล้ว: #{t['id']} → '{parts[1]}' (รอในคิว)", style="green"))
                console.print(Text("อีกเครื่อง/worker รัน `yousini work` หรือเรียก /api/queue/claim เพื่อรับงาน", style="dim"))
            elif sub == "result" and len(parts) >= 2:
                console.print(Panel(format_task(_qget(parts[1])), title="Task",
                                    border_style="cyan", padding=(1, 2)))
            else:
                c = _qcounts()
                console.print(Panel(format_queue(_qlist(), title="Queue") + "\n\n" +
                                    "pending {pending} · running {running} · done {done} · failed {failed}".format(**c),
                                    title="Agent queue", border_style="cyan", padding=(1, 2)))
                console.print(Text("ใช้: /agent send <worker> <โจทย์> | result <id> | status", style="dim"))
            continue
        if low == "/work":
            from yousini_queue import process_once
            console.print(Text("กำลังประมวลผลงานที่ค้างในคิว...", style="yellow"))
            done = process_once()
            for t in done:
                if t.get("status") == "done":
                    console.print(Text(f"✅ {t.get('id')} เสร็จ ({len(t.get('result') or '')} ตัวอักษร)", style="green"))
                else:
                    console.print(Text(f"❌ {t.get('id')} ล้ม: {t.get('error')}", style="red"))
            console.print(Text(f"ทำงานเสร็จ {len(done)} งาน", style="green"))
            continue
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
        if low.startswith("/search"):
            q = user_input[7:].strip()
            if not q:
                console.print(Text("ใช้: /search <คำค้น>", style="yellow")); continue
            rows = store.search(q)
            if not rows:
                console.print(Text(f"ไม่พบ session เกี่ยวกับ '{q}'", style="yellow")); continue
            t = Text()
            for r in rows:
                t.append(f"• [{r['session']}] ", style="bold cyan")
                t.append(f"({r['saved_at'][:16]}) ", style="dim")
                t.append(f"{r['role']}: {r['snippet']}\n",
                         style="green" if r["role"] == "assistant" else "white")
            console.print(Panel(t, title=f"ผลค้นหา '{q}'", border_style="magenta")); continue
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
        if low == "/login":
            login_mode()
            continue
        if low.startswith("/theme "):
            name = user_input[6:].strip()
            cfg = load_config()
            if name in THEMES:
                cfg["theme"] = name
                save_config(cfg)
                _ui_set_theme(name)
                console.print(Text(f"เปลี่ยนธีมเป็น: {name}", style="green"))
            else:
                # show theme selector
                t = Text()
                for key in THEMES:
                    t.append(f"  - {key}\n", style="cyan")
                console.print(Panel(t, title="ธีมที่มี", border_style="magenta"))
            continue
        if low.startswith("/permission "):
            args = user_input[12:].strip()
            console.print(permission_cmd(args))
            continue
        if low.startswith("/img "):
            # แนบรูปภาพแล้วให้โมเดลดู (ต้องใช้โมเดล vision เช่น pixtral)
            rest = user_input[5:].strip()
            if not rest:
                console.print(Text("ใช้: /img <path.png|url> [คำถาม]", style="yellow"))
                continue
            parts = rest.split(None, 1)
            path, question = parts[0], (parts[1] if len(parts) > 1 else "ดูภาพนี้แล้วอธิบายให้ละเอียด")
            chat_turn(agent, f"[img:{path}] {question}")
            continue
        if low == "/plan":
            plan_mode()
            continue
        if low == "/symbols" or low.startswith("/symbols "):
            _symbols_cmd(agent, user_input[8:].strip()); continue
        if low == "/git" or low.startswith("/git "):
            _git_cmd(agent, user_input[4:].strip()); continue
        if low == "/cron" or low.startswith("/cron "):
            _cron_cmd(agent, user_input[5:].strip()); continue
        if low == "/pr" or low.startswith("/pr "):
            rest = user_input[3:].strip()
            if rest.lower().startswith("list"):
                console.print(Panel(agent.git_pr_tool("list"), title="เปิด PR",
                                    border_style="green", padding=(1, 2)))
            elif rest:
                console.print(Panel(agent.git_pr_tool("create", title=rest),
                                    title="PR flow", border_style="green", padding=(1, 2)))
            else:
                console.print(Text("ใช้: /pr <ชื่อ PR>  |  /pr list", style="yellow"))
            continue
        if low == "/scaffold" or low.startswith("/scaffold "):
            parts = user_input[9:].strip().split(None, 1)
            if len(parts) >= 2:
                r = agent.scaffold_tool(parts[0].lower(), parts[1].strip())
                console.print(Panel(r, title="Scaffold",
                                    border_style="green" if not r.startswith("Error") else "red",
                                    padding=(1, 2)))
            else:
                from yousini_scaffold import kinds_text
                console.print(Text(f"ใช้: /scaffold <kind> <name>  (kind: {kinds_text()})", style="yellow"))
            continue
        if low == "/dev" or low.startswith("/dev "):
            rest = user_input[4:].strip().lower() or "all"
            console.print(Panel(agent.dev_check_tool(rest), title="Dev check",
                                border_style="cyan", padding=(1, 2)))
            continue
        # ---- v3.8: plugins / session io / update / config / workflow ----
        if low == "/plugins":
            console.print(Panel(agent.plugin_list_tool(), title="Plugins",
                                border_style="magenta", padding=(1, 2)))
            continue
        if low == "/export" or low.startswith("/export "):
            rest = user_input[7:].strip()
            parts = rest.split()
            if not parts:
                console.print(Text("ใช้: /export <ชื่อ session> [--md] [--out <ไฟล์>]", style="yellow"))
                continue
            name = parts[0]
            fmt = "md" if "--md" in parts else "json"
            out = ""
            if "--out" in parts:
                i = parts.index("--out")
                if i + 1 < len(parts):
                    out = parts[i + 1]
            console.print(Panel(agent.session_export_tool(name, out, fmt), title="Export",
                                border_style="green", padding=(1, 2)))
            continue
        if low == "/import" or low.startswith("/import "):
            rest = user_input[7:].strip()
            parts = rest.split()
            if not parts:
                console.print(Text("ใช้: /import <ไฟล์ session.json> [--name <ชื่อใหม่>]", style="yellow"))
                continue
            new_name = ""
            if "--name" in parts:
                i = parts.index("--name")
                if i + 1 < len(parts):
                    new_name = parts[i + 1]
            console.print(Panel(agent.session_import_tool(parts[0], new_name), title="Import",
                                border_style="green", padding=(1, 2)))
            continue
        if low == "/update" or low.startswith("/update "):
            rest = user_input[7:].strip().lower()
            r = agent.update_tool("update" if rest in ("go", "update") else "check")
            console.print(Panel(r, title="Self-update", border_style="cyan", padding=(1, 2)))
            continue
        if low == "/config" or low.startswith("/config "):
            from yousini_config import config_cmd
            console.print(Panel(config_cmd(user_input[7:].strip()), title="Config",
                                border_style="magenta", padding=(1, 2)))
            continue
        if low == "/flag" or low.startswith("/flag "):
            from yousini_config import flag_cmd
            console.print(Panel(flag_cmd(user_input[5:].strip()), title="Feature flags",
                                border_style="magenta", padding=(1, 2)))
            continue
        if low == "/workflow" or low.startswith("/workflow "):
            from yousini_workflows import workflow_main
            exec_tool = lambda tname, targs: _exec_tool(agent, tname, targs, tc_id="workflow")
            msg = workflow_main(user_input[9:].strip().split(), exec_tool, chat_turn=None)
            console.print(Panel(msg, title="Workflow", border_style="cyan", padding=(1, 2)))
            continue
        # แสดงข้อความผู้ใช้แบบ bubble ก่อนส่งเข้า agent
        _ui_user(user_input)
        # ---- plugin REPL commands (จาก plugin ที่โหลด) ----
        _plugins = _load_plugins()
        if _plugins["repl"] and low in _plugins["repl"]:
            fn, desc = _plugins["repl"][low]
            try:
                out = fn(user_input[len(low):].strip(), agent)
                if out:
                    console.print(Text(str(out)))
            except Exception as e:
                console.print(Text(f"plugin error: {e}", style="red"))
            continue
        chat_turn(agent, user_input)
        # Phase 3: auto-save session ทุก turn เพื่อให้ค้นหาย้อนหลังได้
        try:
            store.save(_default_session_name(agent.cwd), agent.messages,
                       {"model": agent.model, "cwd": agent.cwd})
        except Exception:
            pass


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
    _apply_startup_theme()
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


def cron_main(interval=60, once=False):
    """รันงาน cron ที่ถึงเวลา — loop (daemon) หรือ --once รอบเดียว"""
    from yousini_cron import JobStore, run_due_jobs

    def run_fn(job):
        agent = Agent(interactive=False, cwd=job.get("cwd") or os.getcwd())
        chat_turn(agent, job["prompt"])
        out = agent.messages[-1].get("content", "") if agent.messages else ""
        try:
            SessionStore(SESSION_DIR).save(f"cron-{job['name']}", agent.messages,
                                           {"model": agent.model, "cwd": agent.cwd, "cron": True})
        except Exception:
            pass
        return out

    store = JobStore()
    if once:
        for r in run_due_jobs(store, run_fn):
            tag = f"[{r['job']}]"
            if r["error"]:
                console.print(Text(f"{tag} ❌ {r['error']}", style="red"))
            else:
                console.print(Text(f"{tag} ✅ ({len(r['output'] or '')} ตัวอักษร)", style="green"))
        return
    console.print(Text(f"Cron daemon เริ่มแล้ว (ตรวจทุก {interval}s) — Ctrl+C เพื่อหยุด", style="cyan"))
    while True:
        try:
            for r in run_due_jobs(store, run_fn):
                tag = f"[{r['job']}]"
                if r["error"]:
                    console.print(Text(f"{tag} ❌ {r['error']}", style="red"))
                else:
                    console.print(Text(f"{tag} ✅ สรุปสั้น: {str(r['output'])[:120]}", style="green"))
        except KeyboardInterrupt:
            console.print(Text("\nหยุด cron daemon", style="dim"))
            break
        time.sleep(interval)


def _apply_startup_theme():
    """apply ธีม TUI จาก config.json ตอน start (fail-open)"""
    try:
        _ui_set_theme(load_config().get("theme", "dark"))
    except Exception:
        pass

def main():
    _apply_startup_theme()
    argv = sys.argv[1:]

    # ---- version ----
    if argv and argv[0] in ("--version", "-v", "version"):
        console.print(Text(f"Yousini {APP_VERSION} (Python {sys.version.split()[0]})", style="cyan"))
        return

    # โหลด plugins (ถ้า flag plugin_system เปิด) — ก่อน dispatch คำสั่ง
    _load_plugins()

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

    # ---- subcommand: lsp ----
    if argv and argv[0] == "lsp":
        o = _parse_flags(argv[1:])
        targets = o.get("_", [])
        lsp_main(root=targets[0] if targets else ".")
        return

    # ---- subcommand: marketplace / market ----
    if argv and argv[0] in ("marketplace", "market"):
        marketplace_main(argv[1:])
        return

    # ---- subcommand: team ----
    if argv and argv[0] == "team":
        team_main(argv[1:])
        return

    # ---- subcommand: agent (collaboration queue) ----
    if argv and argv[0] == "agent":
        agent_main(argv[1:])
        return

    # ---- subcommand: work (worker loop) ----
    if argv and argv[0] == "work":
        o = _parse_flags(argv[1:])
        work_main(once=bool(o.get("once")), interval=float(o.get("interval", 5)),
                  worker=str(o.get("worker", "default")), max_tasks=int(o.get("max", 50)))
        return

    # ---- subcommand: pr ----
    if argv and argv[0] == "pr":
        o = _parse_flags(argv[1:])
        from yousini_git import create_pr, pr_list
        rest = o.get("_", [])
        if rest and rest[0].lower() == "list":
            console.print(Panel(pr_list("."), title="เปิด PR", border_style="green", padding=(1, 2)))
        elif rest:
            console.print(Panel(create_pr(rest[0], body=" ".join(rest[1:])),
                                title="PR flow", border_style="green", padding=(1, 2)))
        else:
            console.print(Text("ใช้: yousini pr <ชื่อ PR> [รายละเอียด]  |  yousini pr list", style="red"))
        return

    # ---- subcommand: scaffold ----
    if argv and argv[0] == "scaffold":
        from yousini_scaffold import scaffold, kinds_text
        if len(argv) >= 3:
            r = scaffold(argv[1], argv[2])
            console.print(Panel(r, title="Scaffold",
                                border_style="green" if not r.startswith("Error") else "red",
                                padding=(1, 2)))
        else:
            console.print(Text(f"ใช้: yousini scaffold <kind> <name>  (kind: {kinds_text()})", style="red"))
        return

    # ---- subcommand: dev ----
    if argv and argv[0] == "dev":
        scope = argv[1] if len(argv) > 1 else "all"
        console.print(Panel(Agent(interactive=False).dev_check_tool(scope),
                            title="Dev check", border_style="cyan", padding=(1, 2)))
        return

    # ---- subcommand: plugin (v3.8) ----
    if argv and argv[0] == "plugin":
        from yousini_plugins import plugin_main
        plugin_main(argv[1:])
        return

    # ---- subcommand: session export/import (v3.8) ----
    if argv and argv[0] == "session":
        from yousini_session_io import session_io_main
        console.print(Panel(session_io_main(SessionStore(SESSION_DIR), argv[1:]),
                            title="Session", border_style="green", padding=(1, 2)))
        return

    # ---- subcommand: update / self-update (v3.8) ----
    if argv and argv[0] == "update":
        from yousini_update import update_main
        console.print(Panel(update_main(argv[1:], APP_VERSION), title="Self-update",
                            border_style="cyan", padding=(1, 2)))
        return

    # ---- subcommand: config / flag (v3.8) ----
    if argv and argv[0] in ("config", "flag"):
        from yousini_config import config_cmd, flag_cmd
        body = (flag_cmd(" ".join(argv[1:])) if argv[0] == "flag"
                else config_cmd(" ".join(argv[1:])))
        console.print(Panel(body, title="Config", border_style="magenta", padding=(1, 2)))
        return

    # ---- subcommand: workflow (v3.8) ----
    if argv and argv[0] == "workflow":
        from yousini_workflows import workflow_main
        exec_tool = lambda tname, targs: _exec_tool(
            Agent(interactive=False), tname, targs, tc_id="workflow")
        body = workflow_main(argv[1:], exec_tool, chat_turn=None)
        console.print(Panel(body, title="Workflow", border_style="cyan", padding=(1, 2)))
        return

    # ---- subcommand: usage (v3.8 report) ----
    if argv and argv[0] == "usage":
        from yousini_usage import summary, report
        rest = argv[1:]
        if rest and rest[0].lower() in ("report", "weekly", "daily", "monthly"):
            period = rest[0].lower()
            if period == "report":
                period = rest[1].lower() if len(rest) > 1 and rest[1].lower() in ("daily", "weekly", "monthly") else "weekly"
            console.print(Panel(report(period), title="Usage report",
                                border_style="cyan", padding=(1, 2)))
        else:
            console.print(Panel(summary(), title="Usage telemetry",
                                border_style="magenta", padding=(1, 2)))
        return

    # ---- subcommand: plugin CLI commands (จาก plugin ที่โหลด) ----
    _plugins = _load_plugins()
    if argv and _plugins["cli"] and argv[0] in _plugins["cli"]:
        fn, desc = _plugins["cli"][argv[0]]
        try:
            msg = fn(argv[1:], _parse_flags(argv[1:]))
            if msg:
                console.print(Text(str(msg)))
        except Exception as e:
            console.print(Text(f"plugin error: {e}", style="red"))
        return

    # ---- subcommand: login ----
    if argv and argv[0] == "login":
        o = _parse_flags(argv[1:])
        login_mode()  # interactive provider selection
        return

    # ---- subcommand: theme ----
    if argv and argv[0] == "theme":
        o = _parse_flags(argv[1:])
        name = o.get("_", ["default"])[0] if o.get("_") else None
        if name and name in THEMES:
            cfg = {"theme": name}
            CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
            _ui_set_theme(name)
            console.print(Text(f"เปลี่ยนธีมเป็น: {name}", style="green"))
        else:
            # show theme selector
            t = Text()
            for key in THEMES:
                t.append(f"  - {key}\n", style="cyan")
            console.print(Panel(t, title="ธีมที่มี", border_style="magenta"))
        return

    # ---- subcommand: permission ----
    if argv and argv[0] == "permission":
        o = _parse_flags(argv[1:])
        subcmd = o.get("_", [])[0] if o.get("_") else ""
        perm_args = " ".join(o.get("_", [])[1:]) if len(o.get("_", [])) > 1 else ""
        permission_cmd(subcmd + " " + perm_args)  # CLI permission command
        return

    # ---- subcommand: webhook-add / webhook-rm / webhook-list ----
    if argv and argv[0] in ("webhook-add", "webhook-rm", "webhook-list"):
        from yousini_webhook import WebhookStore
        ws = WebhookStore()
        if argv[0] == "webhook-list":
            hooks = ws.load()
            if not hooks:
                console.print(Text("ยังไม่มี webhook — ใช้ yousini webhook-add <ชื่อ> <prompt>", style="yellow"))
            else:
                t = Text()
                for h in hooks:
                    t.append(f"• {h['name']}: {str(h['prompt'])[:70]}\n", style="cyan")
                console.print(Panel(t, title="Webhooks", border_style="magenta"))
            return
        if argv[0] == "webhook-add":
            rest = argv[1:]
            if len(rest) < 2:
                console.print(Text("ใช้: yousini webhook-add <ชื่อ> <prompt> [--cwd <dir>] [--callback <url>]", style="red"))
                return
            name = rest[0].lstrip("/")
            prompt = rest[1]
            cwd, cb = None, ""
            if "--cwd" in rest:
                i = rest.index("--cwd")
                if i + 1 < len(rest):
                    cwd = rest[i + 1]
            if "--callback" in rest:
                i = rest.index("--callback")
                if i + 1 < len(rest):
                    cb = rest[i + 1]
            ws.add(name, prompt, cwd=cwd, callback_url=cb)
            console.print(Text(f"เพิ่ม webhook '/{name}' แล้ว (POST /api/webhook/{name} ใน serve)", style="green"))
            return
        if argv[0] == "webhook-rm" and len(argv) > 1:
            ws.remove(argv[1].lstrip("/"))
            console.print(Text(f"ลบ webhook '{argv[1].lstrip('/')}' แล้ว", style="yellow"))
            return

    # ---- subcommand: telegram (gateway) ----
    if argv and argv[0] == "telegram":
        o = _parse_flags(argv[1:])
        token = o.get("token") or os.getenv("YOUSINI_TG_TOKEN", "")
        chat = o.get("chat") or os.getenv("YOUSINI_TG_CHAT_ID", "")
        if not token:
            console.print(Text("ต้องมี token — ตั้ง YOUSINI_TG_TOKEN หรือ --token <bot token> (จาก BotFather)", style="red"))
            return
        from yousini_telegram import TelegramBot

        def reply_fn(text, cid):
            agent = Agent(interactive=False)
            chat_turn(agent, text)
            return agent.messages[-1].get("content", "") if agent.messages else ""

        bot = TelegramBot(token, chat_id=chat)
        console.print(Text("Telegram gateway เริ่มแล้ว — รอข้อความ (Ctrl+C เพื่อหยุด)", style="cyan"))
        bot.run_forever(reply_fn)
        return

    # ---- subcommand: profile ----
    if argv and argv[0] == "profile":
        if len(argv) > 1:
            name = argv[1] if argv[1] != "default" else ""
            act = Path.home() / ".yousini" / ".active_profile"
            if name:
                act.write_text(name, encoding="utf-8")
                console.print(Text(f"สลับโพรไฟล์เป็น '{name}' แล้ว — รีสตาร์ทเพื่อเริ่มใช้ (data อยู่ ~/.yousini/profiles/{name}/)", style="green"))
            else:
                act.unlink(missing_ok=True)
                console.print(Text("กลับสู่โพรไฟล์ default แล้ว", style="yellow"))
        else:
            print("โพรไฟล์ปัจจุบัน:", _profile_root())
        return

    # ---- subcommand: mcp-add / mcp-list / mcp-rm (MCP client config) ----
    if argv and argv[0] in ("mcp-add", "mcp-list", "mcp-rm"):
        from yousini_mcp import MCP_FILE, load_mcp_config
        if argv[0] == "mcp-list":
            cfg = load_mcp_config()
            if not cfg:
                console.print(Text("ยังไม่มี MCP server ตั้งค่า — ใช้ yousini mcp-add <ชื่อ> <คำสั่ง>", style="yellow"))
            else:
                t = Text()
                for n, c in cfg.items():
                    t.append(f"• {n}: {c}\n", style="cyan")
                console.print(Panel(t, title="MCP servers (client)", border_style="magenta"))
            return
        if argv[0] == "mcp-add":
            rest = argv[1:]
            if len(rest) < 2:
                console.print(Text("ใช้: yousini mcp-add <ชื่อ> <คำสั่งรัน server> เช่น yousini mcp-add wiki python wiki_mcp.py", style="red"))
                return
            name, cmd = rest[0], " ".join(rest[1:])
            try:
                cfg = json.loads(MCP_FILE.read_text(encoding="utf-8")) if MCP_FILE.is_file() else []
            except Exception:
                cfg = []
            cfg = [s for s in cfg if not (isinstance(s, dict) and s.get("name") == name)]
            cfg.append({"name": name, "cmd": cmd})
            MCP_FILE.parent.mkdir(parents=True, exist_ok=True)
            MCP_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
            console.print(Text(f"เพิ่ม MCP server '{name}' แล้ว ({cmd}) — รีสตาร์ท yousini เพื่อโหลดเครื่องมือ", style="green"))
            return
        if argv[0] == "mcp-rm":
            if len(argv) < 2:
                console.print(Text("ใช้: yousini mcp-rm <ชื่อ>", style="red"))
                return
            name = argv[1]
            try:
                cfg = json.loads(MCP_FILE.read_text(encoding="utf-8")) if MCP_FILE.is_file() else []
            except Exception:
                cfg = []
            new_cfg = [s for s in cfg if not (isinstance(s, dict) and s.get("name") == name)]
            MCP_FILE.write_text(json.dumps(new_cfg, ensure_ascii=False, indent=1), encoding="utf-8")
            console.print(Text(f"ลบ MCP server '{name}' แล้ว", style="yellow"))
            return

    # ---- subcommand: cron (งานอัตโนมัติตามเวลา) ----
    if argv and argv[0] == "cron":
        o = _parse_flags(argv[1:])
        cron_main(interval=int(o.get("interval", 60)) if str(o.get("interval", "60")).isdigit() else 60,
                  once=bool(o.get("once")))
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
