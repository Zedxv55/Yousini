# -*- coding: utf-8 -*-
"""C2 round 9: web server HTTP routes, plan_mode, REPL branches."""
import json
import os
import time
import socket
import sys
import threading
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import urllib.request
import urllib.error

import yousini


def _req(req):
    """Send a request; return the response object (even on HTTP errors)."""
    try:
        return urllib.request.urlopen(req)
    except urllib.error.HTTPError as _e:
        return _e

def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class _Fn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _TC:
    def __init__(self, index, id_, fn):
        self.index = index
        self.id = id_
        self.function = fn


def _chunk(content=None, tool=None, finish=None, tc_index=0):
    fn = _Fn(tool[0], json.dumps(tool[1])) if tool else None
    tc = [_TC(tc_index, "t1", fn)] if tool else None
    delta = mock.Mock(content=content, tool_calls=tc)
    choice = mock.Mock(delta=delta, finish_reason=finish)
    return mock.Mock(choices=[choice], usage=None)


def _stream(*chunks):
    def gen():
        yield from chunks
    return gen()


def test_serve_get_routes_and_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setenv("YOUSINI_DISABLE_NETWORK", "1")
    monkeypatch.setenv("YOUSINI_API_KEY", "fake")
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "MODEL", "test-model")
    monkeypatch.setattr(yousini, "APP_VERSION", "3.10.1")
    monkeypatch.setattr(yousini, "_usage_enabled", lambda: True, raising=False)
    monkeypatch.setattr(yousini, "_sponsor_line", lambda cfg: "", raising=False)
    # prevent hooks run_session_stop atexit noise
    monkeypatch.setattr(yousini, "atexit", mock.MagicMock())
    port = _free_port()
    t = threading.Thread(target=yousini.serve_main,
                         kwargs=dict(host="127.0.0.1", port=port, token="tok123",
                                     safe=True, allow_shell=False), daemon=True)
    t.start()
    time.sleep(0.8)
    try:
        base = f"http://127.0.0.1:{port}"
        # banner + health + html
        r = _req(urllib.request.Request(base + "/health"))
        assert r.read().decode() == "ok", r.read().decode()
        r = _req(urllib.request.Request(base + "/"))
        assert "Yousini" in r.read().decode(), r.read().decode()[:80]
        r = _req(urllib.request.Request(base + "/info"))
        d = json.loads(r.read().decode())
        assert d["model"] == "test-model"
        # master token → role_for_token returns (owner, admin)
        assert d.get("user", "local") == "local" or d.get("role") == "admin"
        assert d["tier"] in ("free", "pro", None)
        # auth required without token
        r = _req(urllib.request.Request(base + "/api/stats"))
        assert r.status == 401
        r = _req(urllib.request.Request(base + "/api/stats", headers={"X-Yousini-Token": "tok123"}))
        assert r.status == 200
        d = json.loads(r.read().decode())
        assert d["ok"] is True
        assert "server" in d
        # bearer auth
        r = _req(urllib.request.Request(base + "/api/queue/status", headers={"Authorization": "Bearer tok123"}))
        assert r.status == 200
        d = json.loads(r.read().decode())
        assert "counts" in d
        # token in query string
        r = _req(urllib.request.Request(base + "/api/queue/get?id=x&token=tok123"))
        assert r.status == 200
        # bad token
        r = _req(urllib.request.Request(base + "/api/stats", headers={"X-Yousini-Token": "bad"}))
        assert r.status == 401
        # lsp summary
        r = _req(urllib.request.Request(base + "/api/lsp/summary"))
        assert r.status == 401
        r = _req(urllib.request.Request(base + "/api/lsp/summary", headers={"X-Yousini-Token": "tok123"}))
        assert r.status == 200
        d = json.loads(r.read().decode())
        assert d["ok"] is True
        assert "result" in d
        # 404 fallback
        r = _req(urllib.request.Request(base + "/nope"))
        assert r.status == 404
    finally:
        try:
            _req(urllib.request.Request(f"http://127.0.0.1:{port}/health"))
        except Exception:
            pass


def test_serve_post_market_webhook_queue(monkeypatch, tmp_path):
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setenv("YOUSINI_DISABLE_NETWORK", "1")
    monkeypatch.setenv("YOUSINI_API_KEY", "fake")
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "atexit", mock.MagicMock())
    monkeypatch.setattr(yousini, "_read_cfg_light", lambda: {"marketplace": True},
                        raising=False)
    with mock.patch("yousini_marketplace.marketplace_enabled", return_value=False):
        with mock.patch("yousini_marketplace.search_catalog", return_value=[]):
            with mock.patch("yousini_marketplace.installed_list", return_value=[]):
                with mock.patch("yousini_marketplace.registry_url", return_value="r"):
                    port = _free_port()
                    t = threading.Thread(target=yousini.serve_main,
                                         kwargs=dict(host="127.0.0.1", port=port,
                                                     token="t2"), daemon=True)
                    t.start()
                    time.sleep(0.8)
                    try:
                        base = f"http://127.0.0.1:{port}"
                        h = {"X-Yousini-Token": "t2"}
                        # marketplace disabled
                        r = _req(urllib.request.Request(base + "/api/market/catalog", data=json.dumps({}).encode(), headers=h, method="POST"))
                        d = json.loads(r.read().decode())
                        assert d["ok"] is False
                        # marketplace install with missing source
                        r = _req(urllib.request.Request(base + "/api/market/install", data=json.dumps({"source": ""}).encode(), headers=h, method="POST"))
                        d = json.loads(r.read().decode())
                        assert d.get("error") or d.get("ok")
                        # unknown market action
                        r = _req(urllib.request.Request(base + "/api/market/foo", data=json.dumps({}).encode(), headers=h, method="POST"))
                        d = json.loads(r.read().decode())
                        assert d["ok"] is False
                        # unknown lsp method
                        r = _req(urllib.request.Request(base + "/api/lsp/unknown", data=json.dumps({}).encode(), headers=h, method="POST"))
                        d = json.loads(r.read().decode())
                        assert d["ok"] is False
                        # bad content-length json fallback
                        r = _req(urllib.request.Request(base + "/api/lsp/summary", data="not-json".encode(), headers=h, method="POST"))
                        d = json.loads(r.read().decode())
                        assert d["ok"] is True  # payload fallback {}
                        # webhook unknown
                        r = _req(urllib.request.Request(base + "/api/webhook/none", data=json.dumps({}).encode(), headers=h, method="POST"))
                        d = json.loads(r.read().decode())
                        assert d["ok"] is False
                        # queue actions
                        r = _req(urllib.request.Request(base + "/api/queue/enqueue", data=json.dumps({"prompt": "do it"}).encode(), headers=h, method="POST"))
                        d = json.loads(r.read().decode())
                        assert d["ok"] is True
                        tsk = d["task"]
                        tid = tsk["id"]
                        r = _req(urllib.request.Request(base + "/api/queue/claim", data=json.dumps({"worker": "default"}).encode(), headers=h, method="POST"))
                        assert json.loads(r.read().decode())["claimed"] is True
                        r = _req(urllib.request.Request(base + "/api/queue/complete", data=json.dumps({"id": tid, "result": "x"}).encode(), headers=h, method="POST"))
                        assert json.loads(r.read().decode())["ok"] is True
                        # get unknown task
                        r = _req(urllib.request.Request(base + "/api/queue/get?id=nope", headers=h))
                        d = json.loads(r.read().decode())
                        assert d["ok"] is True
                        # queue no action
                        r = _req(urllib.request.Request(base + "/api/queue/nope", data=json.dumps({}).encode(), headers=h, method="POST"))
                        d = json.loads(r.read().decode())
                        assert d["ok"] is False
                        # 404 post
                        r = _req(urllib.request.Request(base + "/api/other", data=json.dumps({}).encode(), headers=h, method="POST"))
                        assert r.status == 404
                    finally:
                        pass


def test_serve_chat_sse_flow(monkeypatch, tmp_path):
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setenv("YOUSINI_DISABLE_NETWORK", "1")
    monkeypatch.setenv("YOUSINI_API_KEY", "fake")
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "atexit", mock.MagicMock())
    # mock run_turn_events to emit a couple of events then stop
    events = [{"type": "token", "text": "hi "},
              {"type": "final", "text": "hi there"}]
    gen_it = iter(events)
    monkeypatch.setattr(yousini, "run_turn_events",
                        mock.MagicMock(side_effect=lambda a, m: iter(events)))
    monkeypatch.setattr(yousini, "Agent", mock.MagicMock())
    port = _free_port()
    t = threading.Thread(target=yousini.serve_main,
                         kwargs=dict(host="127.0.0.1", port=port), daemon=True)
    t.start()
    time.sleep(0.8)
    try:
        base = f"http://127.0.0.1:{port}"
        h = {"Content-Type": "application/json"}
        r = _req(urllib.request.Request(base + "/api/chat", data=json.dumps({"message": "สวัสดี", "session": "s1"}).encode(), headers=h, method="POST"))
        assert r.status == 200
        assert "text/event-stream" in r.headers["Content-Type"]
        body = r.read().decode("utf-8")
        assert "hi " in body
        assert "hi there" in body
        # empty message
        r = _req(urllib.request.Request(base + "/api/chat", data=json.dumps({"message": ""}).encode(), headers=h, method="POST"))
        assert r.status == 400
        # bad json → 400
        r = _req(urllib.request.Request(base + "/api/chat", data="xxxxx".encode(), headers={**h, "Content-Length": "5"}, method="POST"))
        assert r.status == 400
    finally:
        pass


def test_serve_chat_sse_stream_error(monkeypatch, tmp_path):
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setenv("YOUSINI_DISABLE_NETWORK", "1")
    monkeypatch.setenv("YOUSINI_API_KEY", "fake")
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "atexit", mock.MagicMock())

    def boom(agent, msg):
        raise RuntimeError("kaboom")
        yield  # make it a generator

    monkeypatch.setattr(yousini, "run_turn_events", boom)
    monkeypatch.setattr(yousini, "Agent", mock.MagicMock())
    port = _free_port()
    t = threading.Thread(target=yousini.serve_main,
                         kwargs=dict(host="127.0.0.1", port=port), daemon=True)
    t.start()
    time.sleep(0.8)
    try:
        r = _req(urllib.request.Request(f"http://127.0.0.1:{port}/api/chat", data=json.dumps({"message": "x"}).encode(), headers={"Content-Type": "application/json"}, method="POST"))
        body = r.read().decode("utf-8")
        assert "kaboom" in body, body[:300]
    finally:
        pass


def test_plan_mode_non_json_plan(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setenv("YOUSINI_DISABLE_NETWORK", "1")
    monkeypatch.setenv("YOUSINI_API_KEY", "fake")
    printed = []
    spy = mock.MagicMock()
    spy.side_effect = lambda *a, **k: printed.append((a, k))
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini.console, "print", spy)
    monkeypatch.setattr(yousini, "client", mock.MagicMock())
    plan_resp = mock.MagicMock()
    plan_resp.choices = [mock.MagicMock(message=mock.MagicMock(content="ทำ 3 ขั้นตอน"))]
    yousini.client.chat.completions.create.return_value = plan_resp
    fake_agent2 = mock.MagicMock()
    fake_agent2.messages = []
    fake_agent2.usage = {"prompt_tokens": 0, "completion_tokens": 0}
    fake_agent2.shell.return_value = "ok"
    monkeypatch.setattr(yousini, "Agent", mock.MagicMock(return_value=fake_agent2))
    it = iter(["วันนี้", "y"])
    monkeypatch.setattr("builtins.input", lambda p="": next(it))
    yousini.plan_mode()
    joined = "".join(str(x) for (a, k) in printed for x in a)
    assert "แผน" in joined


# ---------- Groups K-N: stats / lsp / market / queue fallback branches ----------

def _serve(monkeypatch, tmp_path, extra_patches=None, token="tok"):
    """boot serve_main on a free port; return (port, base_url)"""
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setenv("YOUSINI_DISABLE_NETWORK", "1")
    monkeypatch.setenv("YOUSINI_API_KEY", "fake")
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "atexit", mock.MagicMock())
    if extra_patches:
        for patcher in extra_patches:
            patcher.start()
    port = _free_port()
    t = threading.Thread(target=yousini.serve_main,
                         kwargs=dict(host="127.0.0.1", port=port, token=token),
                         daemon=True)
    t.start()
    time.sleep(0.8)
    return port, f"http://127.0.0.1:{port}", token


def test_serve_stats_module_fallbacks(monkeypatch, tmp_path):
    """Group K: stats_json - every optional module fails/missing, still ok=True."""
    bad = mock.MagicMock()
    bad.stats.side_effect = Exception("usage broken")
    bad.db_path.side_effect = Exception("no db")
    bad.counts.side_effect = Exception("no counts")
    patchers = [
        mock.patch.dict(sys.modules, {"yousini_usage": bad}),
        mock.patch("yousini_team.team_status", side_effect=Exception("team")),
        mock.patch("yousini_sessions_db.SessionSearch",
                   side_effect=Exception("no sessions db")),
        mock.patch("yousini_marketplace.marketplace_enabled",
                   side_effect=Exception("no market")),
        mock.patch("yousini_marketplace.installed_list",
                   side_effect=Exception("no market list")),
        mock.patch("yousini_symbols.SymbolIndex",
                   side_effect=Exception("no symbols")),
        mock.patch("yousini_queue.counts",
                   side_effect=Exception("no queue")),
    ]
    try:
        port, base, token = _serve(monkeypatch, tmp_path, extra_patches=patchers)
        h = {"X-Yousini-Token": token}
        r = _req(urllib.request.Request(base + "/api/stats", headers=h))
        assert r.status == 200
        d = json.loads(r.read().decode())
        assert d["ok"] is True
        # fallback dicts for failed modules
        assert "usage" in d and isinstance(d["usage"], dict)
        assert "error" in d["usage"]
        assert "sessions" in d and isinstance(d["sessions"], dict)
        assert "market" in d and isinstance(d["market"], dict)
        assert "team" in d and isinstance(d["team"], dict)
        assert "symbols" in d and isinstance(d["symbols"], dict)
        assert "queue" in d and isinstance(d["queue"], dict)
    finally:
        for p in patchers:
            p.stop()


def test_serve_lsp_all_methods(monkeypatch, tmp_path):
    """Group L: lsp_json_ok - summary/hover/definition/references/document-symbols/unknown."""
    port, base, token = _serve(monkeypatch, tmp_path)
    try:
        h = {"X-Yousini-Token": token}
        # GET summary
        r = _req(urllib.request.Request(base + "/api/lsp/summary", headers=h))
        assert json.loads(r.read().decode())["ok"] is True
        # workspace-symbols
        r = _req(urllib.request.Request(base + "/api/lsp/workspace-symbols", data=json.dumps({"query": "Agent"}).encode(), headers=h, method="POST"))
        assert json.loads(r.read().decode())["ok"] is True
        body = {"file": "yousini.py", "line": 0, "character": 0}
        for method in ("hover", "definition", "references"):
            r = _req(urllib.request.Request(base + f"/api/lsp/{method}", data=json.dumps(body).encode(), headers=h, method="POST"))
            assert "ok" in json.loads(r.read().decode()), method
        r = _req(urllib.request.Request(base + "/api/lsp/document-symbols", data=json.dumps({"file": "yousini.py"}).encode(), headers=h, method="POST"))
        assert "ok" in json.loads(r.read().decode())
        # unknown method -> ok=False
        r = _req(urllib.request.Request(base + "/api/lsp/nonexistent-method", data=json.dumps({}).encode(), headers=h, method="POST"))
        assert json.loads(r.read().decode())["ok"] is False
    finally:
        pass


def test_serve_market_enabled_branches(monkeypatch, tmp_path):
    """Group M: market_json with marketplace enabled - catalog/installed/install/update/info."""
    patchers = [
        mock.patch("yousini_marketplace.marketplace_enabled", return_value=True),
        mock.patch("yousini_marketplace.search_catalog", return_value=[{"id": "p1"}]),
        mock.patch("yousini_marketplace.installed_list", return_value=[]),
        mock.patch("yousini_marketplace.registry_url", return_value="https://r"),
        mock.patch("yousini_marketplace.install", return_value={"ok": True}),
        mock.patch("yousini_marketplace.update",
                   return_value={"ok": True}),
        mock.patch("yousini_marketplace.uninstall",
                   return_value={"ok": True}),
        mock.patch("yousini_marketplace.pkg_info", return_value={"id": "p1"}),
        mock.patch("yousini_marketplace.format_info", return_value="info p1"),
    ]
    try:
        port, base, token = _serve(monkeypatch, tmp_path, extra_patches=patchers)
        h = {"X-Yousini-Token": token}
        # catalog
        r = _req(urllib.request.Request(base + "/api/market/catalog", data=json.dumps({"query": "x"}).encode(), headers=h, method="POST"))
        assert json.loads(r.read().decode())["ok"] is True
        # installed
        r = _req(urllib.request.Request(base + "/api/market/installed", data=json.dumps({}).encode(), headers=h, method="POST"))
        assert json.loads(r.read().decode())["ok"] is True
        # install missing source
        r = _req(urllib.request.Request(base + "/api/market/install", data=json.dumps({"source": ""}).encode(), headers=h, method="POST"))
        d = json.loads(r.read().decode())
        assert d.get("ok") is False and "source" in d.get("error", "")
        # install with source
        r = _req(urllib.request.Request(base + "/api/market/install", data=json.dumps({"source": "p1"}).encode(), headers=h, method="POST"))
        assert json.loads(r.read().decode())["ok"] is True
        # update
        r = _req(urllib.request.Request(base + "/api/market/update", data=json.dumps({"id": "p1"}).encode(), headers=h, method="POST"))
        assert json.loads(r.read().decode())["ok"] is True
        # uninstall (admin only, master token is admin)
        r = _req(urllib.request.Request(base + "/api/market/uninstall", data=json.dumps({"id": "p1"}).encode(), headers=h, method="POST"))
        assert "ok" in json.loads(r.read().decode())
        # info
        r = _req(urllib.request.Request(base + "/api/market/info", data=json.dumps({"id": "p1"}).encode(), headers=h, method="POST"))
        assert json.loads(r.read().decode())["ok"] is True
    finally:
        for p in patchers:
            p.stop()


def test_serve_queue_notfound_branches(monkeypatch, tmp_path):
    """Group N: queue_json - empty prompt, complete/fail unknown ids, requeue/get."""
    port, base, token = _serve(monkeypatch, tmp_path)
    try:
        h = {"X-Yousini-Token": token}
        # enqueue empty prompt
        r = _req(urllib.request.Request(base + "/api/queue/enqueue", data=json.dumps({"prompt": ""}).encode(), headers=h, method="POST"))
        d = json.loads(r.read().decode())
        assert d["ok"] is False and "prompt" in d.get("error", "")
        # complete unknown id
        r = _req(urllib.request.Request(base + "/api/queue/complete", data=json.dumps({"id": "nonexistent-xyz"}).encode(), headers=h, method="POST"))
        d = json.loads(r.read().decode())
        assert d["ok"] is False and "งาน" in d.get("error", "")
        # fail unknown id
        r = _req(urllib.request.Request(base + "/api/queue/fail", data=json.dumps({"id": "nonexistent-xyz"}).encode(), headers=h, method="POST"))
        d = json.loads(r.read().decode())
        assert d["ok"] is False and "งาน" in d.get("error", "")
        # requeue unknown id -> ok True (returns None task)
        r = _req(urllib.request.Request(base + "/api/queue/requeue", data=json.dumps({"id": "nonexistent-xyz"}).encode(), headers=h, method="POST"))
        d = json.loads(r.read().decode())
        assert d["ok"] is True
        # get unknown id -> ok True, task None
        r = _req(urllib.request.Request(base + "/api/queue/get?id=nonexistent-xyz", headers=h))
        d = json.loads(r.read().decode())
        assert d["ok"] is True
        # status + claim empty
        r = _req(urllib.request.Request(base + "/api/queue/status", headers=h))
        assert json.loads(r.read().decode())["ok"] is True
        r = _req(urllib.request.Request(base + "/api/queue/claim", data=json.dumps({"worker": "w1"}).encode(), headers=h, method="POST"))
        assert "claimed" in json.loads(r.read().decode())
    finally:
        pass

