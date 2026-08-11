#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Webhooks — ระบบภายนอก POST มาแล้วให้ agent ทำงาน (เทียบเท่า webhook routes ของ Hermes)

- ตั้งค่า: yousini webhook-add <ชื่อ> <prompt> [--cwd ...] [--callback ...]  (เก็บ ~/.yousini/webhooks.json)
- เรียก:  POST /api/webhook/<ชื่อ> ใน serve mode — payload JSON แทรกเข้า prompt
- ผลลัพธ์: ส่งกลับเป็น JSON + (ถ้าตั้ง callback_url) POST ผลไปยัง URL นั้น
"""
import json
import os
import urllib.request
from pathlib import Path

WEBHOOK_FILE = Path(os.getenv("YOUSINI_WEBHOOK_FILE",
                              str(Path.home() / ".yousini" / "webhooks.json")))


def _wh_file():
    # อ่าน env ตอนเรียก — รองรับ test ที่แก้ env หลัง import
    return Path(os.getenv("YOUSINI_WEBHOOK_FILE", str(Path.home() / ".yousini" / "webhooks.json")))


class WebhookStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else _wh_file()

    def load(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def save(self, hooks):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(hooks, ensure_ascii=False, indent=1), encoding="utf-8")

    def add(self, name, prompt, cwd=None, callback_url=""):
        hooks = [h for h in self.load() if h.get("name") != name]
        hooks.append({"name": name, "prompt": prompt, "cwd": cwd, "callback_url": callback_url})
        self.save(hooks)
        return name

    def remove(self, name):
        hooks = [h for h in self.load() if h.get("name") != name]
        self.save(hooks)

    def get(self, name):
        return next((h for h in self.load() if h.get("name") == name), None)


def run_webhook(name, payload=None, run_fn=None, store_path=None):
    """รัน webhook — คืน (ok, result_text)"""
    wh = WebhookStore(store_path).get(name)
    if wh is None:
        return False, f"ไม่พบ webhook '{name}'"
    prompt = (wh.get("prompt") or "").strip()
    if payload:
        prompt += ("\n--- payload จากระบบภายนอก (JSON) ---\n"
                   + json.dumps(payload, ensure_ascii=False))
    if run_fn is None:

        def run_fn(p, cwd):
            from yousini import Agent, chat_turn
            agent = Agent(interactive=False, cwd=cwd or os.getcwd())
            chat_turn(agent, p)
            return agent.messages[-1].get("content", "") if agent.messages else ""

    try:
        out = run_fn(prompt, wh.get("cwd"))
    except Exception as e:
        out = f"Error: {e}"
    cb = (wh.get("callback_url") or "").strip()
    if cb:
        try:
            req = urllib.request.Request(
                cb, data=json.dumps({"name": name, "result": out}, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=15)
        except Exception as e:
            out += f"\n(callback ล้ม: {e})"
    return True, out