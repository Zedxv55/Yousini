"""ทดสอบ Webhooks — POST ภายนอกสั่ง agent ทำงาน (Phase 7)"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yousini_webhook import WebhookStore, run_webhook


def test_webhook_store_crud(tmp_path):
    ws = WebhookStore(tmp_path / "wh.json")
    ws.add("deploy", "รัน deploy script", cwd="/tmp", callback_url="https://hook.example/x")
    ws.add("daily", "สรุปยอดขาย")
    hooks = ws.load()
    assert len(hooks) == 2
    assert ws.get("deploy")["prompt"] == "รัน deploy script"
    ws.remove("deploy")
    assert ws.get("deploy") is None


def test_webhook_run_with_fake_fn(tmp_path):
    ws = WebhookStore(tmp_path / "wh.json")
    ws.add("hello", "ตอบสวัสดี")
    captured = {}

    def fake_run(prompt, cwd):
        captured["prompt"] = prompt
        captured["cwd"] = cwd
        return "สวัสดีครับ"

    ok, out = run_webhook("hello", payload={"user": "A"}, run_fn=fake_run, store_path=ws.path)
    assert ok and out == "สวัสดีครับ"
    assert "payload จากระบบภายนอก" in captured["prompt"]
    assert '"user": "A"' in captured["prompt"]


def test_webhook_unknown_name(tmp_path):
    ws = WebhookStore(tmp_path / "wh.json")
    ok, out = run_webhook("nope", run_fn=lambda p, c: "", store_path=ws.path)
    assert not ok and "ไม่พบ" in out


def test_webhook_callback_failure_graceful(tmp_path):
    ws = WebhookStore(tmp_path / "wh.json")
    ws.add("cb", "ทำอะไรก็ได้", callback_url="http://127.0.0.1:1/nope")

    def fake_run(p, c):
        return "ผลลัพธ์"

    ok, out = run_webhook("cb", run_fn=fake_run, store_path=ws.path)
    assert ok
    assert "callback ล้ม" in out  # ล้มแบบสุภาพ ไม่ crash