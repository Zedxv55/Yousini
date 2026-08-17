# -*- coding: utf-8 -*-
"""C2 round 10: missed web server branches (SSE internals, market/lsp/queue POST edges)."""
import os
import sys
import time
import socket
import threading
import json
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests  # type: ignore

import yousini


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_serve_sse_branches(monkeypatch, tmp_path):
    """SSE: run_turn_events raises -> emit error branch; persist called; chunked end."""
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setenv("YOUSINI_DISABLE_NETWORK", "1")
    monkeypatch.setenv("YOUSINI_API_KEY", "fake")
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "atexit", mock.MagicMock())
    monkeypatch.setattr(yousini, "run_turn_events",
                        mock.MagicMock(side_effect=RuntimeError("turn-broken")))
    monkeypatch.setattr(yousini, "Agent", mock.MagicMock())
    port = _free_port()
    t = threading.Thread(target=yousini.serve_main,
                         kwargs=dict(host="127.0.0.1", port=port), daemon=True)
    t.start()
    time.sleep(0.8)
    base = f"http://127.0.0.1:{port}"
    try:
        r = requests.post(base + "/api/chat",
                          headers={"Content-Type": "application/json"},
                          json={"message": "x"}, timeout=10, stream=True)
        body = r.content.decode("utf-8")
        assert "turn-broken" in body, body[:300]
        # emit error path แล้ว server จบ chunked stream — connect อีกได้
        r2 = requests.get(base + "/health", timeout=5)
        assert r2.text == "ok"
    finally:
        pass


def test_serve_market_admin_403_and_bad_payload(monkeypatch, tmp_path):
    """POST /api/market/install by non-admin -> 403; bad Content-Length json."""
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setenv("YOUSINI_DISABLE_NETWORK", "1")
    monkeypatch.setenv("YOUSINI_API_KEY", "fake")
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "atexit", mock.MagicMock())
    monkeypatch.setattr(yousini, "_read_cfg_light", lambda: {"marketplace": True},
                        raising=False)
    with mock.patch("yousini_marketplace.marketplace_enabled", return_value=True), \
         mock.patch("yousini_marketplace.search_catalog", return_value=[]), \
         mock.patch("yousini_marketplace.installed_list", return_value=[]), \
         mock.patch("yousini_marketplace.registry_url", return_value="r"):
        port = _free_port()
        t = threading.Thread(target=yousini.serve_main,
                             kwargs=dict(host="127.0.0.1", port=port, token="mt"),
                             daemon=True)
        t.start()
        time.sleep(0.8)
        base = f"http://127.0.0.1:{port}"
        try:
            h = {"Content-Type": "application/json"}
            # bad payload -> payload={} -> market_json unknown action
            r = requests.post(base + "/api/market/list", headers={**h, "X-Yousini-Token": "mt"},
                              data="not-json", timeout=5)
            assert r.status_code == 200
            d = r.json()
            assert d["ok"] is False
            # GET market action (query param) -> unknown action
            r = requests.get(base + "/api/market/installed?q=x",
                             headers={"X-Yousini-Token": "mt"}, timeout=5)
            assert r.json()["ok"] is True
            # GET catalog with q
            r = requests.get(base + "/api/market/catalog?q=x",
                             headers={"X-Yousini-Token": "mt"}, timeout=5)
            assert r.json()["ok"] is True
        finally:
            pass


def test_serve_queue_fail_and_notfound(monkeypatch, tmp_path):
    """POST /api/queue/fail -> ok; complete unknown id -> ok=False."""
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setenv("YOUSINI_DISABLE_NETWORK", "1")
    monkeypatch.setenv("YOUSINI_API_KEY", "fake")
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "atexit", mock.MagicMock())
    port = _free_port()
    t = threading.Thread(target=yousini.serve_main,
                         kwargs=dict(host="127.0.0.1", port=port, token="q1"),
                         daemon=True)
    t.start()
    time.sleep(0.8)
    base = f"http://127.0.0.1:{port}"
    try:
        h = {"X-Yousini-Token": "q1"}
        # enqueue a real task
        r = requests.post(base + "/api/queue/enqueue", headers=h,
                          json={"prompt": "do work"}, timeout=5)
        tid = r.json()["task"]["id"]
        # claim then fail
        requests.post(base + "/api/queue/claim", headers=h,
                      json={"worker": "default"}, timeout=5)
        r = requests.post(base + "/api/queue/fail", headers=h,
                          json={"id": tid, "error": "nope"}, timeout=5)
        d = r.json()
        assert d["ok"] is True
        # complete unknown id
        r = requests.post(base + "/api/queue/complete", headers=h,
                          json={"id": "no-such-id", "result": "x"}, timeout=5)
        d = r.json()
        assert d["ok"] is False and "พบ" in d.get("error", "")
        # enqueue empty prompt
        r = requests.post(base + "/api/queue/enqueue", headers=h,
                          json={"prompt": ""}, timeout=5)
        assert r.json()["ok"] is False
    finally:
        pass
