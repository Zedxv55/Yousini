#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CodeagentX — Local Coding Agent สไตล์ Claude Code
รันคำสั่งบนเครื่องจริงได้: shell, อ่าน/เขียน/แก้ไฟล์, ค้นหาไฟล์ เหมือน Claude Code
รองรับ Groq (OpenAI-compatible) + เลือกโมเดลตัวแรงได้

รัน:  codeagentx        (หรือ python3 codeagentx.py)
"""

import os
import sys
import json
import re
import subprocess

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

from openai import OpenAI
from openai import BadRequestError

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

AUTO_RUN = os.getenv("AUTO_RUN", "0") == "1"
CONFIRM_FILES = os.getenv("CONFIRM_FILES", "1") == "1"
SHELL_TIMEOUT = int(os.getenv("SHELL_TIMEOUT", "60"))

if not GROQ_API_KEY:
    print("❌ ไม่พบ GROQ_API_KEY โปรดคัดลอก .env.example เป็น .env แล้วใส่ key")
    sys.exit(1)

client = OpenAI(api_key=GROQ_API_KEY, base_url=GROQ_BASE_URL)

# คำสั่งอันตราย → ขออนุมัติเสมอ + เตือน
DANGER_RE = [re.compile(p) for p in [
    r"\brm\s+-rf\b", r"\brm\s+-fr\b", r"\brm\s+-r\b.*\s/\b",
    r"\bdd\b\s+if=", r"\bmkfs", r"\bshutdown\b", r"\bhalt\b", r"\breboot\b",
    r":\(\)\s*\{.*\}\s*;:", r">\s*/dev/sd", r"\bchmod\s+-R\s+0",
    r"\bmv\s+.*\s/dev/null", r"\btruncate\s+-s\s+0",
]]


def is_dangerous(cmd: str) -> bool:
    return any(r.search(cmd) for r in DANGER_RE)


def _truncate(s: str, n: int = 8000) -> str:
    if len(s) > n:
        return s[:n] + f"\n…(ตัด remaining {len(s) - n} ตัวอักษร)"
    return s


# ===========================================================================
# SKILL — ความสามารถสไตล์ Claude Code (บันทึกใน SKILL.md ด้วย สำหรับ copy/วาง)
# ===========================================================================
SYSTEM_PROMPT = """คุณคือ CodeagentX — Local Coding Agent ที่ทำงานบนเครื่องของผู้ใช้ แบบเดียวกับ Claude Code
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
8. ทำงานแบบอัตโนมัติให้ได้มากที่สุด อย่าถามผู้ใช้ยืนยันผลที่คุณตรวจสอบเองได้"""


class Agent:
    def __init__(self, model=GROQ_MODEL, cwd=os.getcwd()):
        self.model = model
        self.cwd = os.path.abspath(cwd)
        self.auto_run = AUTO_RUN
        self.confirm_files = CONFIRM_FILES

    # ---- Shell ----
    def shell(self, command: str, timeout: int = None) -> str:
        dangerous = is_dangerous(command)
        if dangerous:
            print(f"  ⚠️  คำสั่งเสี่ยงสูง: {command}")
        if not self.auto_run or dangerous:
            print(f"  🖥️  คำสั่ง: {command}")
            ans = input("     รัน? [y/N/e=แก้ไข] ").strip().lower()
            if ans in ("e", "edit"):
                return self.shell(input("     พิมพ์คำสั่งใหม่: ").strip(), timeout)
            if ans not in ("y", "yes", "1"):
                return "❌ ผู้ใช้ไม่อนุญาต"
        try:
            t = timeout or SHELL_TIMEOUT
            proc = subprocess.Popen(["bash", "-c", command], cwd=self.cwd,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            out, _ = proc.communicate(timeout=t)
            return _truncate(f"[exit code: {proc.returncode}]\n{out or '(ไม่มีผลลัพธ์)'}")
        except subprocess.TimeoutExpired:
            proc.kill()
            return f"⏱️  หมดเวลา ({t}s)"
        except Exception as e:
            return f"❌: {e}"

    def _resolve(self, path):
        return path if os.path.isabs(path) else os.path.join(self.cwd, path)

    def read_file(self, path: str, limit: int = 0) -> str:
        fp = self._resolve(path)
        if not os.path.isfile(fp):
            return f"❌ ไม่พบไฟล์: {fp}"
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                data = f.read()
            if limit and limit > 0:
                data = "\n".join(data.splitlines()[:limit])
            return _truncate(data)
        except Exception as e:
            return f"❌ อ่านไม่ได้: {e}"

    def write_file(self, path: str, content: str) -> str:
        fp = self._resolve(path)
        if os.path.exists(fp) and self.confirm_files:
            print(f"  ✏️  จะเขียนทับ: {fp}")
            if input("     ยืนยัน? [y/N] ").strip().lower() not in ("y", "yes", "1"):
                return "❌ ไม่อนุญาต"
        try:
            os.makedirs(os.path.dirname(fp) or ".", exist_ok=True)
            with open(fp, "w", encoding="utf-8") as f:
                f.write(content)
            return f"✅ เขียนสำเร็จ: {fp} ({len(content)} ตัวอักษร)"
        except Exception as e:
            return f"❌ เขียนไม่ได้: {e}"

    def edit_file(self, path: str, old_string: str, new_string: str) -> str:
        fp = self._resolve(path)
        if not os.path.isfile(fp):
            return f"❌ ไม่พบไฟล์: {fp}"
        if self.confirm_files:
            print(f"  ✏️  จะแก้ไฟล์: {fp}")
            if input("     ยืนยัน? [y/N] ").strip().lower() not in ("y", "yes", "1"):
                return "❌ ไม่อนุญาต"
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = f.read()
            if old_string not in data:
                return "❌ ไม่พบ old_string ในไฟล์"
            cnt = data.count(old_string)
            data = data.replace(old_string, new_string)
            with open(fp, "w", encoding="utf-8") as f:
                f.write(data)
            return f"✅ แก้สำเร็จ: {fp} ({cnt} แห่ง)"
        except Exception as e:
            return f"❌ แก้ไม่ได้: {e}"

    def list_dir(self, path: str = ".") -> str:
        fp = self._resolve(path)
        if not os.path.isdir(fp):
            return f"❌ ไม่พบโฟลเดอร์: {fp}"
        try:
            return "\n".join(
                f"{n}/" if os.path.isdir(os.path.join(fp, n)) else n
                for n in sorted(os.listdir(fp))) or "(ว่าง)"
        except Exception as e:
            return f"❌: {e}"

    def glob(self, pattern: str, path: str = ".") -> str:
        import fnmatch
        base = self._resolve(path)
        if not os.path.isdir(base):
            return f"❌ ไม่พบโฟลเดอร์: {base}"
        try:
            hits = [os.path.join(r, fn) for r, _, fs in os.walk(base) for fn in fs
                    if fnmatch.fnmatch(fn, pattern)]
            return "\n".join(hits[:200]) if hits else "❌ ไม่พบ"
        except Exception as e:
            return f"❌: {e}"

    def grep(self, pattern: str, path: str = ".", glob_pattern: str = "*") -> str:
        import fnmatch
        base = self._resolve(path)
        if not os.path.isdir(base):
            return f"❌ ไม่พบโฟลเดอร์: {base}"
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
            return "\n".join(hits) if hits else "❌ ไม่พบ"
        except re.error as e:
            return f"❌ regex ผิด: {e}"
        except Exception as e:
            return f"❌: {e}"

    def set_cwd(self, path: str) -> str:
        fp = self._resolve(path)
        if not os.path.isdir(fp):
            return f"❌ ไม่พบโฟลเดอร์: {fp}"
        self.cwd = os.path.abspath(fp)
        return f"📂 เปลี่ยนโฟลเดอร์เป็น: {self.cwd}"

    def ask_user(self, question: str) -> str:
        try:
            return input(f"  ❓ Agent ถาม: {question} ").strip()
        except EOFError:
            return "(ไม่มีคำตอบ — โหมดไม่โต้ตอบ)"


TOOLS = [
    {"type": "function", "function": {"name": "shell", "description": "รันคำสั่ง bash บนเครื่อง (ls, python3, pip install, git, สร้างโปรเจกต์)", "parameters": {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "อ่านไฟล์ข้อความ", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["path"]}}},
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


def run_agent(agent: Agent, user_input: str) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_input}]
    for _ in range(20):
        try:
            resp = client.chat.completions.create(
                model=agent.model, messages=messages, tools=TOOLS,
                tool_choice="auto", temperature=0.5, parallel_tool_calls=False)
        except BadRequestError as e:
            # โมเดล生成 tool call พัง (เช่น รูปแบบผิด) → ขอคำตอบแบบปกติไม่ใช้ tools
            err = str(e)
            if "tool_use_failed" in err or "Failed to call a function" in err:
                print("  ⚠️ โมเดลสร้าง tool call ไม่ถูกต้อง กำลังขอคำตอบแบบปกติ...")
                try:
                    resp = client.chat.completions.create(
                        model=agent.model, messages=messages, tools=[], temperature=0.5)
                    return resp.choices[0].message.content or "(โมเดลไม่ตอบ)"
                except Exception:
                    return "❌ ไม่สามารถประมวลผลคำสั่งนี้ได้ โปรดลองพิมพ์ใหม่"
            return f"❌ คำขอไม่ถูกต้อง: {e}"
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return msg.content or ""
        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [{"id": tc.id, "type": "function",
                                         "function": {"name": tc.function.name,
                                                      "arguments": tc.function.arguments}}
                                        for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            shown = args.get("command", "") if name == "shell" else args
            print(f"  🔧 {name}({shown})")
            result = IMPL[name](args, agent)
            print(f"  👀 {result[:600]}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})
    return "⚠️ วนลูปเกินจำกัด กรุณาลองใหม่"


def main():
    agent = Agent()
    if len(sys.argv) > 1:
        user_input = " ".join(sys.argv[1:])
        print(f"\n🧑 คุณ: {user_input}")
        print(f"🤖 CodeagentX ({agent.model}):")
        print(run_agent(agent, user_input))
        return

    print("=" * 64)
    print(f"🤖 CodeagentX  (Claude Code-style)  โมเดล: {agent.model}")
    print(f"📂 โฟลเดอร์: {agent.cwd}")
    print(f"🔐 ขออนุมัติ shell: {'ปิด (รันทันที)' if agent.auto_run else 'เปิด (ถามก่อน)'}")
    print("   พิมพ์งาน  |  /model <ชื่อ>  /cwd <โฟลเดอร์>  /approve on|off  /tools  /exit")
    print("=" * 64)
    while True:
        try:
            user_input = input("\n🧑 คุณ > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 ลาก่อน!"); break
        if not user_input:
            continue
        if user_input.lower() in ("/exit", "/quit", "exit", "quit"):
            print("👋 ลาก่อน!"); break
        if user_input.lower() == "/tools":
            print("   ", ", ".join(IMPL.keys())); continue
        if user_input.lower().startswith("/model "):
            agent.model = user_input[7:].strip(); print(f"   ✅ โมเดล: {agent.model}"); continue
        if user_input.lower().startswith("/cwd "):
            print("   " + agent.set_cwd(user_input[5:].strip())); continue
        if user_input.lower().startswith("/approve "):
            agent.auto_run = user_input[9:].strip().lower() in ("on", "1", "true")
            print(f"   🔐 รันอัตโนมัติ: {'เปิด' if agent.auto_run else 'ปิด (ถามก่อน)'}"); continue
        print(f"🤖 CodeagentX ({agent.model}):")
        try:
            print(run_agent(agent, user_input))
        except Exception as e:
            print(f"❌: {e}")


if __name__ == "__main__":
    main()
