#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram gateway — แชทกับ Yousini ผ่าน Telegram bot (gateway พหุช่องทางแบบ Hermes)

ตั้งค่า:  YOUSINI_TG_TOKEN=<bot token จาก BotFather>  (และ YOUSINI_TG_CHAT_ID ตัวเลือก)
รัน:      yousini telegram [--token ...] [--chat ...]
วิธีทำงาน: long-poll getUpdates → ทุกข้อความ ส่งให้ agent ตอบ → ส่งคำตอบกลับ
"""
import json
import os
import time
import urllib.parse
import urllib.request


class TelegramBot:
    BASE = "https://api.telegram.org/bot"

    def __init__(self, token, chat_id=None, timeout=25):
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout
        self.offset = 0

    def _api(self, method, params=None, timeout=None):
        url = self.BASE + self.token + "/" + method
        data = None
        if params:
            data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def send(self, text, chat_id=None, timeout=None):
        if not text:
            return
        return self._api("sendMessage",
                         {"chat_id": str(chat_id or self.chat_id or ""),
                          "text": self._text_for_send(text)},
                         timeout=timeout)

    def get_updates(self):
        params = {"timeout": self.timeout, "offset": self.offset}
        res = self._api("getUpdates", params, timeout=self.timeout + 5)
        return res.get("result", [])

    def _text_for_send(self, text):
        return text[:4000]  # จำกัดความยาวข้อความ Telegram

    def process_updates(self, updates, reply_fn):
        """ประมวลผล batch ของ update — คืน (replies, sent) สำหรับทดสอบ"""
        sent = []
        for u in updates:
            self.offset = u.get("update_id", 0) + 1
            msg = u.get("message") or {}
            text = (msg.get("text") or "").strip()
            chat = msg.get("chat") or {}
            cid = chat.get("id")
            if not text or cid is None:
                continue
            try:
                answer = reply_fn(text, cid) or ""
                if answer:
                    self.send(answer, cid)
                    sent.append((answer, cid))
            except Exception as e:
                self.send(f"Error: {e}", cid)
                sent.append((f"Error: {e}", cid))
        return sent

    def run_forever(self, reply_fn, poll_interval=0.5):
        while True:
            try:
                updates = self.get_updates()
                if updates:
                    self.process_updates(updates, reply_fn)
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"⚠️ telegram poll error: {e}")
                time.sleep(2)
            time.sleep(poll_interval)