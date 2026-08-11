"""ทดสอบ Provider Fallback Chain — สลับ API สำรองเมื่อโค้ต้าหมด/l่ม (Phase 5)"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yousini
from yousini import _retryable, _load_providers, _FallbackClient


class FakeCompletions:
    def __init__(self, owner):
        self.owner = owner

    def create(self, *a, **kw):
        return self.owner._create(*a, **kw)


class FakeChat:
    def __init__(self, owner):
        self.completions = FakeCompletions(owner)


def _err_cls(name):
    import openai
    return getattr(openai, name)


def test_load_providers_from_env(monkeypatch):
    monkeypatch.setenv("YOUSINI_FALLBACK_PROVIDERS", json.dumps([
        {"base_url": "https://api.groq.com/openai/v1", "api_key": "k1"},
        {"base_url": "https://api.deepseek.com/v1", "api_key": "k2"},
    ]))
    provs = _load_providers()
    base = [x for x in provs if x.get("api_key") != "k1" and x.get("api_key") != "k2"]
    assert any(p["base_url"].startswith("groq") for p in provs)
    assert any(p["base_url"].startswith("deepseek") for p in provs)


def test_retryable_classification():
    import openai
    assert _retryable(openai.AuthenticationError("x", response=None, body=None))
    assert _retryable(openai.RateLimitError("x", response=None, body=None))
    assert _retryable(openai.APIConnectionError(request=None))
    assert not _retryable(openai.BadRequestError("x", response=None, body=None))


def test_fallback_switches_on_error():
    import openai
    fb = _FallbackClient()
    calls = []

    class Boom:
        def __init__(self, exc):
            self.exc = exc

        chat = None  # จะถูกแทนที่ด้านล่าง

    # สร้าง fake 2 ตัว: ตัวแรก error เสมอ ตัวสองสำเร็จ
    ok = object()

    class FakeOk:
        def __init__(self):
            self.chat = FakeChat(self)

        def _create(self, *a, **kw):
            calls.append("ok")
            return ok

    class FakeBoom:
        def __init__(self):
            self.chat = FakeChat(self)

        def _create(self, *a, **kw):
            calls.append("boom")
            raise openai.RateLimitError("quota", response=None, body=None)

    fb._client = FakeBoom()
    fb.providers = [{"base_url": "a"}, {"base_url": "b"}]
    fb._clients = [FakeBoom(), FakeOk()]

    # แก้ _build ให้คืนจาก _clients
    orig_build = fb._build
    fb._build = lambda i: fb._clients[i]
    try:
        r = fb.completions_create(model="x", messages=[])
        assert r is ok
        assert calls == ["boom", "ok"]
    finally:
        fb._build = orig_build


def test_fallback_exhausts_raises_last():
    import openai
    fb = _FallbackClient()

    class FakeBoom:
        def __init__(self):
            self.chat = FakeChat(self)

        def _create(self, *a, **kw):
            raise openai.RateLimitError("quota", response=None, body=None)

    fb._client = FakeBoom()
    fb.providers = [{"base_url": "a"}, {"base_url": "b"}]
    fb._clients = [FakeBoom(), FakeBoom()]
    fb._build = lambda i: fb._clients[i]
    try:
        try:
            fb.completions_create(model="x", messages=[])
            assert False, "ควร raise"
        except openai.RateLimitError:
            pass
    finally:
        pass


def test_non_retryable_no_switch():
    import openai
    fb = _FallbackClient()
    calls = []

    class FakeBad:
        def __init__(self):
            self.chat = FakeChat(self)

        def _create(self, *a, **kw):
            calls.append("bad")
            raise openai.BadRequestError("validation", response=None, body=None)

    fb._client = FakeBad()
    fb.providers = [{"base_url": "a"}, {"base_url": "b"}]
    fb._clients = [FakeBad(), FakeBad()]
    fb._build = lambda i: fb._clients[i]
    try:
        try:
            fb.completions_create(model="x", messages=[])
            assert False
        except openai.BadRequestError:
            pass
        assert calls == ["bad"]  # ไม่ลองตัวถัดไป
    finally:
        pass