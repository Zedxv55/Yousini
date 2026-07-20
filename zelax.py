#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zelax — Local Coding Agent สไตล์ Claude Code
รับคำสั่งภาษาธรรมชาติ ทำงานบนเครื่องจริงได้: shell / อ่าน-เขียน-แก้ไฟล์ / ค้นหา
รองรับทุก OpenAI-compatible API (Groq, OpenAI, OpenRouter, DeepSeek, Mistral ฯลฯ)
ฟีเจอร์: ความจำข้าม turn · streaming จริง · UI สไตล์ Claude Code (⏺/⎿) ·
diff สีก่อนเขียน · syntax highlight · spinner · คำสั่ง /clear /history /help

รัน:  zelax        (หรือ python3 zelax.py)
"""

import os
import sys
import json
import re
import readline
import atexit
import subprocess
import difflib
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
from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.live import Live
from rich.text import Text
from rich.panel import Panel
from rich.spinner import Spinner

console = Console()

# ---- Config: รองรับทุก OpenAI-compatible API ----
# อ่าน ZELAX_* ก่อน ถ้าไม่มีตกไปใช้ GROQ_* (เข้ากันได้กับของเดิม)
API_KEY = os.getenv("ZELAX_API_KEY") or os.getenv("GROQ_API_KEY", "")
BASE_URL = os.getenv("ZELAX_BASE_URL") or os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
MODEL = os.getenv("ZELAX_MODEL") or os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

AUTO_RUN = os.getenv("AUTO_RUN", "0") == "1"
CONFIRM_FILES = os.getenv("CONFIRM_FILES", "1") == "1"
SHELL_TIMEOUT = int(os.getenv("SHELL_TIMEOUT", "60"))

if not API_KEY:
    console.print(Text("Error: ไม่พบ API Key โปรดคัดลอก .env.example เป็น .env แล้วใส่ ZELAX_API_KEY", style="red"))
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


SYSTEM_PROMPT = """คุณคือ Zelax — Local Coding Agent ที่ทำงานบนเครื่องของผู้ใช้ แบบเดียวกับ Claude Code
คุณสามารถรันคำสั่ง shell, อ่าน/เขียน/แก้ไฟล์ และค้นหาไฟล์ได้ด้วยตนเอง

เครื่องมือของคุณ:
- shell      รันคำสั่ง bash บนเครื่อง (ls, python3, pip, git, สร้างโปรเจกต์ ฯลฯ)
- read_file  อ่านไฟล์ข้อความ
- write_file สร้าง/เขียนทับไฟล์
- edit_file  แก้ข้อความในไฟล์ (search & replace)
- list_dir   แสดงไฟล์ในโฟลเดอร์
- glob       หาไฟล์ตามรูปแบบ เช่น '*.py'
- grep       ค้นหาข้อความ (regex) ในไฟล์
- set_cwd    เปลี่ยนโฟลเดอร์ทำงาน
- ask_user   ถามผู้ใช้ เฉพาะเมื่อขาดข้อมูลสำคัญจริงๆ เท่านั้น

หลักการทำงาน (Claude Code style):
1. วิเคราะห์คำสั่ง → วางแผนสั้นๆ → ใช้เครื่องมือ → ตรวจสอบผล → สรุป
2. ก่อนแก้ไฟล์ ให้อ่านไฟล์นั้นก่อนเสมอ
3. เปลี่ยนแปลงให้น้อยที่สุด (minimal change) อย่าทำล่วงหน้าเกินจำเป็น
4. ใช้เครื่องมือตรวจสอบผลลัพธ์ อย่าคาดเดา
5. ห้ามรันคำสั่งอันตราย (rm -rf, dd, shutdown ฯลฯ) โดยไม่ได้รับอนุญาต
6. เมื่อเห็นผลจากเครื่องมือแล้ว ให้นำไปใช้ต่อ ห้ามเรียก ask_user ถามผลที่ตนเห็นอยู่แล้ว
7. เมื่องานเสร็จ ให้สรุปสั้นๆ เป็นภาษาไทย พร้อมบอกไฟล์/คำสั่งที่ทำไป
8. ทำงานแบบอัตโนมัติให้ได้มากที่สุด อย่าถามผู้ใช้ยืนยันผลที่ตรวจสอบเองได้"""


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
    def __init__(self, model=MODEL, cwd=os.getcwd()):
        self.model = model
        self.cwd = os.path.abspath(cwd)
        self.auto_run = AUTO_RUN
        self.confirm_files = CONFIRM_FILES
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # ---- trimming: ตัดที่ user-boundary เท่านั้น ไม่ให้เหลือ tool-result ลอยๆ ----
    def _trim(self, max_msgs=40):
        if len(self.messages) <= max_msgs:
            return
        sys0 = self.messages[0]
        conv = self.messages[1:]
        cuts = [i for i, m in enumerate(conv) if m["role"] == "user"]
        while len(conv) > max_msgs - 1 and len(cuts) > 1:
            drop = cuts[1]            # ตัด segment แรก [0 .. cuts[1])
            conv = conv[drop:]
            cuts = [i - drop for i in cuts[1:]]
        self.messages = [sys0] + conv

    # ---- Shell ----
    def shell(self, command: str, timeout: int = None) -> str:
        dangerous = is_dangerous(command)
        if dangerous:
            console.print(Text(f"คำเตือน: คำสั่งเสี่ยงสูง: {command}", style="yellow"))
        if not self.auto_run or dangerous:
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
        self._show_diff(path, old, content)
        if self.confirm_files and os.path.exists(fp):
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
        new = old.replace(old_string, new_string)
        self._show_diff(path, old, new)
        if self.confirm_files:
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

    def set_cwd(self, path: str) -> str:
        fp = self._resolve(path)
        if not os.path.isdir(fp):
            return f"Error: ไม่พบโฟลเดอร์: {fp}"
        self.cwd = os.path.abspath(fp)
        return f"เปลี่ยนโฟลเดอร์เป็น: {self.cwd}"

    def ask_user(self, question: str) -> str:
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
    {"type": "function", "function": {"name": "set_cwd", "description": "เปลี่ยนโฟลเดอร์ทำงาน", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "ask_user", "description": "ถามผู้ใช้เฉพาะเมื่อขาดข้อมูลสำคัญจริงๆ เท่านั้น", "parameters": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}}},
]

IMPL = {
    "shell": lambda a, k: k.shell(**a), "read_file": lambda a, k: k.read_file(**a),
    "write_file": lambda a, k: k.write_file(**a), "edit_file": lambda a, k: k.edit_file(**a),
    "list_dir": lambda a, k: k.list_dir(**a), "glob": lambda a, k: k.glob(**a),
    "grep": lambda a, k: k.grep(**a), "set_cwd": lambda a, k: k.set_cwd(**a),
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
    """จับเหตุการณ์โมเดล生成พัง → ขอคำตอบแบบปกติไม่ใช้ tools"""
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
    """หนึ่งรอบสนทนา: ต่อความจำเดิม + streaming + tool loop"""
    agent.messages.append({"role": "user", "content": user_text})
    agent._trim()
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

        # มีการเรียกเครื่องมือ → รันแล้ววนลูปต่อ
        if any(t.get("name") for t in tool_calls):
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

        # ไม่มีเครื่องมือ → จบรอบนี้
        ans = "".join(content)
        agent.messages.append({"role": "assistant", "content": ans})
        console.print()
        return


# ---------------------------------------------------------------------------
# REPL + readline history ข้ามเซสชัน
# ---------------------------------------------------------------------------
HIST_FILE = Path.home() / ".zelax_history"


def _setup_readline():
    try:
        readline.read_history_file(HIST_FILE)
    except FileNotFoundError:
        pass
    readline.set_history_length(2000)
    atexit.register(lambda: readline.write_history_file(HIST_FILE))


def _print_banner(agent: Agent):
    txt = Text()
    txt.append("Zelax", style="bold cyan")
    txt.append("  —  ผู้ช่วยเขียนโค้ดบนเครื่อง (สไตล์ Claude Code)\n\n", style="dim")
    txt.append("โมเดล: ", style="dim"); txt.append(agent.model + "\n", style="bold")
    txt.append("Endpoint: ", style="dim"); txt.append(BASE_URL + "\n", style="dim")
    txt.append("โฟลเดอร์: ", style="dim"); txt.append(agent.cwd + "\n", style="dim")
    txt.append("ขออนุมัติ shell: ", style="dim")
    txt.append("เปิด (ถามก่อน)" if not agent.auto_run else "ปิด (รันทันที)", style="yellow")
    txt.append("\nพิมพ์งาน  |  /help /clear /history /model /cwd /approve /exit", style="dim")
    console.print(Panel(txt, border_style="cyan", padding=(1, 2)))


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
    t = Text()
    for cmd, desc in lines:
        t.append("  " + cmd + "\n", style="bold cyan")
        t.append("     " + desc + "\n", style="dim")
    console.print(Panel(t, title="คำสั่ง", border_style="cyan"))


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
    console.print(Panel(t, title=f"ประวัติ ({len(agent.messages)} ข้อความ)", border_style="cyan"))


def main():
    agent = Agent()
    if len(sys.argv) > 1:
        chat_turn(agent, " ".join(sys.argv[1:]))
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
