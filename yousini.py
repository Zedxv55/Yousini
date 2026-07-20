#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yousini — Local Coding Agent สไตล์ Claude Code (เชื่อมต่อทั้งในเครื่องและออนไลน์)
รับคำสั่งภาษาธรรมชาติ ทำงานบนเครื่องจริงได้: shell / อ่าน-เขียน-แก้ไฟล์ / ค้นหา
และออนไลน์ได้: web_fetch / web_search ผ่านทุก OpenAI-compatible API

ฟีเจอร์: ความจำข้าม turn · streaming จริง · UI สไตล์ Claude Code (⏺/⎿) ·
diff สีก่อนเขียน · syntax highlight · spinner · คำสั่ง /clear /history /help

รัน:  yousini        (หรือ python3 yousini.py)
"""

import os
import sys
import json
import re
import readline
import atexit
import subprocess
import difflib
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path

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


SYSTEM_PROMPT = """คุณคือ Yousini — Local Coding Agent ที่ทำงานบนเครื่องของผู้ใช้ แบบเดียวกับ Claude Code
คุณสามารถรันคำสั่ง shell, อ่าน/เขียน/แก้ไฟล์, ค้นหาไฟล์บนเครื่อง และเข้าถึงอินเทอร์เน็ต (web_fetch, web_search) ได้

เครื่องมือของคุณ:
- shell      รันคำสั่ง bash บนเครื่อง (ls, python3, pip, git, สร้างโปรเจกต์ ฯลฯ)
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

หลักการทำงาน (Claude Code style):
1. วิเคราะห์คำสั่ง → วางแผนสั้นๆ → ใช้เครื่องมือ → ตรวจสอบผล → สรุป
2. ก่อนแก้ไฟล์ ให้อ่านไฟล์นั้นก่อนเสมอ
3. เปลี่ยนแปลงให้น้อยที่สุด (minimal change) อย่าทำล่วงหน้าเกินจำเป็น
4. ใช้เครื่องมือตรวจสอบผลลัพธ์ อย่าคาดเดา
5. เมื่อต้องการข้อมูลล่าสุดจากโลกภายนอก ให้ใช้ web_search/web_fetch
6. ห้ามรันคำสั่งอันตราย (rm -rf, dd, shutdown ฯลฯ) โดยไม่ได้รับอนุญาต
7. เมื่อเห็นผลจากเครื่องมือแล้ว ให้นำไปใช้ต่อ ห้ามเรียก ask_user ถามผลที่ตนเห็นอยู่แล้ว
8. เมื่องานเสร็จ ให้สรุปสั้นๆ เป็นภาษาไทย พร้อมบอกไฟล์/คำสั่งที่ทำไป
9. ทำงานแบบอัตโนมัติให้ได้มากที่สุด อย่าถามผู้ใช้ยืนยันผลที่ตรวจสอบเองได้"""


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
                 allow_shell=True, allow_write=True):
        self.model = model
        self.cwd = os.path.abspath(cwd)
        self.auto_run = AUTO_RUN
        self.confirm_files = CONFIRM_FILES
        # interactive=False → โหมด server/headless: ไม่ถามผ่าน input()
        self.interactive = interactive
        self.allow_shell = allow_shell   # ปิดได้เพื่อเซิร์ฟเวอร์แบบ read-only
        self.allow_write = allow_write
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

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

    # ---- Shell ----
    def shell(self, command: str, timeout: int = None) -> str:
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
            ans = input("  รัน? [y/N/e=แก้ไข] ").strip().lower()
            if ans in ("e", "edit"):
                return self.shell(input("  พิมพ์คำสั่งใหม่: ").strip(), timeout)
            if ans not in ("y", "yes", "1"):
                return "ปฏิเสธโดยผู้ใช้"
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
        self._show_diff(path, old, content)
        if self.interactive and self.confirm_files and os.path.exists(fp):
            if input("   ยืนยันเขียนทับ? [y/N] ").strip().lower() not in ("y", "yes", "1"):
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
        new = old.replace(old_string, new_string)
        self._show_diff(path, old, new)
        if self.interactive and self.confirm_files:
            if input("   ยืนยันแก้ไฟล์? [y/N] ").strip().lower() not in ("y", "yes", "1"):
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
        try:
            q = urllib.parse.quote(query)
            req = urllib.request.Request(
                f"https://html.duckduckgo.com/html/?q={q}",
                headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                html = r.read().decode("utf-8", errors="replace")
            titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.S)
            links = re.findall(r'class="result__a"[^>]*href="([^"]+)"', html)
            snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S)
            out = []
            for i in range(min(max_results, len(titles))):
                t = _strip_tags(titles[i]).strip()
                l = links[i] if i < len(links) else ""
                s = _strip_tags(snippets[i]).strip() if i < len(snippets) else ""
                out.append(f"{i+1}. {t}\n   {l}\n   {s}")
            res = "\n".join(out) or "ไม่พบผลลัพธ์"
            console.print(Panel(Text(res, style="dim"),
                                title=f"ค้นหา: {query}", border_style="blue"))
            return res
        except Exception as e:
            return f"Error: web_search ไม่ได้: {e}"

    def set_cwd(self, path: str) -> str:
        fp = self._resolve(path)
        if not os.path.isdir(fp):
            return f"Error: ไม่พบโฟลเดอร์: {fp}"
        self.cwd = os.path.abspath(fp)
        return f"เปลี่ยนโฟลเดอร์เป็น: {self.cwd}"

    def ask_user(self, question: str) -> str:
        if not self.interactive:
            return "(โหมดไม่โต้ตอบ: ไม่สามารถถามผู้ใช้ได้ กรุณาตัดสินใจเองจากข้อมูลที่มี)"
        console.print(Text(f"Agent: {question}", style="yellow"))
        try:
            return input("คุณ: ").strip()
        except EOFError:
            return "(ไม่มีคำตอบ — โหมดไม่โต้ตอบ)"


TOOLS = [
    {"type": "function", "function": {"name": "shell", "description": "รันคำสั่ง bash บนเครื่อง (ls, python3, pip install, git, สร้างโปรเจกต์)", "parameters": {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer"}}, "required": ["command"]}}},
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
]

IMPL = {
    "shell": lambda a, k: k.shell(**a), "read_file": lambda a, k: k.read_file(**a),
    "write_file": lambda a, k: k.write_file(**a), "edit_file": lambda a, k: k.edit_file(**a),
    "list_dir": lambda a, k: k.list_dir(**a), "glob": lambda a, k: k.glob(**a),
    "grep": lambda a, k: k.grep(**a), "web_fetch": lambda a, k: k.web_fetch(**a),
    "web_search": lambda a, k: k.web_search(**a), "set_cwd": lambda a, k: k.set_cwd(**a),
    "ask_user": lambda a, k: k.ask_user(**a),
}


def _exec_tool(agent: Agent, name: str, args: dict, tc_id: str):
    shown = args.get("command", "") if name == "shell" else args
    if not isinstance(shown, str):
        shown = json.dumps(shown, ensure_ascii=False)
    console.print(Text(f"⏺ {name}({shown})", style="bold cyan"))
    result = IMPL[name](args, agent)
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


def chat_turn(agent: Agent, user_text: str):
    agent.messages.append({"role": "user", "content": user_text})
    agent._trim()
    tool_seen = False
    while True:
        try:
            stream = client.chat.completions.create(
                model=agent.model, messages=agent.messages, tools=TOOLS,
                tool_choice="auto", temperature=0.5, parallel_tool_calls=False, stream=True)
        except BadRequestError as e:
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
            return _fallback_turn(agent, e)
        except Exception as e:
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
# ใช้ agent.messages ร่วมกัน (ความจำข้าม turn) แต่ไม่พิมพ์คำตอบออกจอ
# event: {"type": "token"|"tool"|"tool_result"|"final"|"error", ...}
# ---------------------------------------------------------------------------
def run_turn_events(agent: Agent, user_text: str):
    agent.messages.append({"role": "user", "content": user_text})
    agent._trim()
    while True:
        try:
            stream = client.chat.completions.create(
                model=agent.model, messages=agent.messages, tools=TOOLS,
                tool_choice="auto", temperature=0.5,
                parallel_tool_calls=False, stream=True)
        except Exception as e:
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
                shown = args.get("command", "") if t["name"] == "shell" else args
                if not isinstance(shown, str):
                    shown = json.dumps(shown, ensure_ascii=False)
                yield {"type": "tool", "name": t["name"], "args": shown}
                result = IMPL[t["name"]](args, agent)
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
    txt.append("\n\n  พิมพ์งานได้เลย  ·  ", style="dim")
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
        ("/exit, /quit", "ออก"),
    ]
    servers = [
        ("yousini serve", "เปิดเว็บ UI + API (localhost)"),
        ("yousini serve --host 0.0.0.0 --token รหัส", "เปิดออนไลน์ (มี token)"),
        ("yousini serve --safe", "เปิดแบบอ่านอย่างเดียว (ปิด shell/เขียนไฟล์)"),
        ("yousini connect <url> [--token รหัส]", "คุยกับ Yousini อีกเครื่องผ่านเน็ต"),
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


# ---------------------------------------------------------------------------
# โหมด SERVER: yousini serve  → เปิดเป็นบริการ (เว็บ UI + API สตรีม SSE)
# เชื่อมต่อได้ทั้งในเครื่อง (localhost) และออนไลน์ (0.0.0.0 + token)
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

    def get_agent(sid):
        with reg_lock:
            if sid not in sessions:
                sessions[sid] = Agent(interactive=False,
                                      allow_shell=(allow_shell and not safe),
                                      allow_write=(allow_write and not safe))
                locks[sid] = threading.Lock()
            return sessions[sid], locks[sid]

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
# ทำให้ CLI สองเครื่อง "คุยกัน" ได้ (ในเครื่อง หรือ ออนไลน์)
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
                            console.print(Text(f"\n⏺ {ev['name']}({ev['args']})",
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

    agent = Agent()
    if argv:
        chat_turn(agent, " ".join(argv))
        return

    _setup_readline()
    _print_banner(agent)
    while True:
        try:
            user_input = input("❯ ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print(Text("\nจบการทำงาน", style="dim")); break
        if not user_input:
            continue
        if user_input.lower() in ("/exit", "/quit"):
            console.print(Text("จบการทำงาน", style="dim")); break
        if user_input.lower() == "/help":
            _print_help(); continue
        if user_input.lower() == "/clear":
            agent.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            console.print(Text("ล้างประวัติแล้ว", style="yellow")); continue
        if user_input.lower() == "/history":
            _print_history(agent); continue
        if user_input.lower().startswith("/model "):
            agent.model = user_input[7:].strip()
            console.print(Text(f"โมเดล: {agent.model}", style="green")); continue
        if user_input.lower().startswith("/cwd "):
            console.print(Text(agent.set_cwd(user_input[5:].strip()), style="yellow")); continue
        if user_input.lower().startswith("/approve "):
            agent.auto_run = user_input[9:].strip().lower() in ("on", "1", "true")
            console.print(Text(f"รันอัตโนมัติ: {'เปิด' if agent.auto_run else 'ปิด (ถามก่อน)'}", style="yellow")); continue
        chat_turn(agent, user_input)


if __name__ == "__main__":
    main()
