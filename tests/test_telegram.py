"""ทดสอบ Telegram gateway — receive/send ผ่าน bot API (Phase 7)"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yousini_telegram import TelegramBot


def test_process_updates_replies(tmp_path, monkeypatch):
    bot = TelegramBot("TOKEN:test", chat_id="123")
    replies = []

    def fake_reply(text, cid):
        replies.append((text, cid))
        return f"ตอบ: {text}"

    updates = [
        {"update_id": 1, "message": {"text": "สวัสดี", "chat": {"id": "123"}}},
        {"update_id": 2, "message": {"text": "ไม่มีการแชท", "chat": None}},
        {"update_id": 3, "message": {"text": "ทำการบ้านหน่อย", "chat": {"id": "456"}}},
    ]
    sent = []
    bot.send = lambda text, cid=None, timeout=None: sent.append((text, cid))

    bot.process_updates(updates, fake_reply)
    assert replies == [("สวัสดี", "123"), ("ทำการบ้านหน่อย", "456")]
    # ไม่มีการแชท (update 2) → ข้าม
    assert sent == [("ตอบ: สวัสดี", "123"), ("ตอบ: ทำการบ้านหน่อย", "456")]
    assert bot.offset == 4  # update_id ล่าสุด + 1


def test_send_truncates_long_text():
    bot = TelegramBot("TOKEN:test", chat_id="1")
    long = "x" * 5000
    result = bot._text_for_send(long)
    assert len(result) <= 4000


def test_api_uses_token_and_params(monkeypatch):
    bot = TelegramBot("TOKEN:abc", chat_id="9")
    calls = []

    class FakeResp:
        def __init__(self):
            self._body = b'{"ok": true, "result": []}'

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        calls.append((req.full_url, req.data, timeout))
        return FakeResp()

    monkeypatch.setattr("yousini_telegram.urllib.request.urlopen", fake_urlopen)
    bot.get_updates()
    url, data, to = calls[0]
    assert "TOKEN:abc/getUpdates" in url
    assert to == bot.timeout + 5