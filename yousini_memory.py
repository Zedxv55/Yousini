#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yousini Memory — ความจำระยะยาว (เทียบเท่า Hermes memory)

เก็บข้อเท็จจริงผู้ใช้ + บันทึกของ agent ใต้ ~/.yousini/memory/ (หรือ YOUSINI_MEMORY)
- user.md  : ข้อมูลผู้ใช้ (ชื่อ, ความชอบ, สไตล์) — inject เข้า system prompt ทุกครั้ง
- agent.md : บันทึกของ agent (env quirks, บทเรียน, conventions ของเครื่อง)

รูปแบบ: 1 บรรทัด = 1 ข้อเท็จจริง  (add/remove/replace โดยอิงจาก substring)
"""
import os
from pathlib import Path

def _profile_root():
    """ราก data dir ตามโพรไฟล์ (ตรงกับ yousini.py::_profile_root)"""
    base = Path.home() / ".yousini"
    p = os.environ.get("YOUSINI_PROFILE", "").strip()
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


MEMORY_DIR = Path(os.environ.get("YOUSINI_MEMORY", str(_profile_root() / "memory")))
DEFAULT_LIMIT = 2000   # ตัวอักษรสูงสุดต่อไฟล์ (กันบริบทบวม)


class MemoryStore:
    """ไฟล์ความจำไฟล์เดียว (target = user | agent)"""

    def __init__(self, base_dir=None, target="user", limit=DEFAULT_LIMIT):
        self.base_dir = Path(base_dir) if base_dir else MEMORY_DIR
        self.target = target if target in ("user", "agent") else "user"
        self.limit = limit
        self.path = self.base_dir / f"{self.target}.md"

    def load(self):
        if not self.path.exists():
            return []
        text = self.path.read_text(encoding="utf-8")
        return [ln.strip() for ln in text.splitlines() if ln.strip()]

    def save(self, lines):
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def add(self, content):
        lines = self.load()
        if content and content not in lines:
            lines.append(content)
            self.save(lines)
        return f"บันทึกแล้ว ({len(lines)} รายการ)"

    def remove(self, old_text):
        lines = self.load()
        q = old_text.strip()
        kept = [ln for ln in lines if q not in ln]
        self.save(kept)
        return f"ลบ {len(lines) - len(kept)} รายการ (เหลือ {len(kept)})"

    def replace(self, old_text, content):
        lines = self.load()
        q = old_text.strip()
        out = [content if q in ln else ln for ln in lines]
        self.save(out)
        return "แทนที่แล้ว"

    def to_text(self):
        return "\n".join(self.load())

    def budget_ok(self):
        used = sum(len(ln) for ln in self.load())
        return (used <= self.limit, used, self.limit)


class MemoryManager:
    """ครอบทั้ง user + agent — ตัวที่ Agent ใช้"""

    def __init__(self, base_dir=None, limit=DEFAULT_LIMIT):
        self.user = MemoryStore(base_dir, "user", limit)
        self.agent = MemoryStore(base_dir, "agent", limit)
        self.stores = {"user": self.user, "agent": self.agent}

    def act(self, action, target, content="", old_text=""):
        s = self.stores.get(target)
        if s is None:
            return f"target ต้องเป็น user หรือ agent (ได้ '{target}')"
        if action == "add":
            return s.add(content) if content else "ต้องใส่ content"
        if action == "remove":
            return s.remove(old_text) if old_text else "ต้องใส่ old_text"
        if action == "replace":
            if not (old_text and content):
                return "ต้องใส่ old_text + content"
            return s.replace(old_text, content)
        if action == "list":
            return s.to_text() or f"(memory/{target}.md ว่าง)"
        return f"action ต้องเป็น add/remove/replace/list (ได้ '{action}')"

    def inject_text(self):
        """ข้อความสำหรับใส่ใน system prompt — เฉพาะส่วนที่ไม่ว่าง"""
        parts = []
        for key in ("user", "agent"):
            t = self.stores[key].to_text().strip()
            if t:
                parts.append(f"[{key}] {t}")
        return "\n".join(parts)