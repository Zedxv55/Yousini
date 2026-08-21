from pathlib import Path


WEB_UI = Path(__file__).resolve().parents[1] / "webui.html"


def test_webui_exposes_queue_monitor_controls():
    html = WEB_UI.read_text(encoding="utf-8")

    assert 'id="queueBtn"' in html
    assert 'id="queuePanel"' in html
    assert 'id="queuePrompt"' in html
    assert 'id="queueSendBtn"' in html


def test_webui_queue_monitor_uses_queue_api_and_safe_rendering():
    html = WEB_UI.read_text(encoding="utf-8")

    assert "api/queue/" in html
    assert "queueApi('status')" in html
    assert "queueApi('enqueue'" in html
    assert "queueApi('requeue'" in html
    assert "esc(task.prompt" in html
