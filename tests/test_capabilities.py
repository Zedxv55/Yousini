"""ทดสอบ capabilities v3.7: การลงทะเบียน tool (git_pr/scaffold/dev_check) + compact chunked"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import yousini
from yousini import Agent


class _Fake:
    def __init__(self, cwd):
        self.cwd = str(cwd)


def _bind(method_name, cwd):
    """เรียก instance method ที่ใช้แค่ self.cwd โดยไม่ต้องสร้าง Agent จริง"""
    return Agent.__dict__[method_name].__get__(_Fake(cwd))


def test_tools_registered():
    for name in ("git_pr", "scaffold", "dev_check"):
        assert name in yousini.IMPL
        assert any(t.get("function", {}).get("name") == name for t in yousini.TOOLS)


def test_dev_check_compile(tmp_path):
    (tmp_path / "good.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    r = _bind("dev_check_tool", tmp_path)("compile")
    assert "— compile —" in r
    assert "good.py" not in r.split("พบปัญหา")[0] if "พบปัญหา" in r else True
    assert "bad.py" in r


def test_dev_check_status(tmp_path):
    r = _bind("dev_check_tool", tmp_path)("status")
    assert "— git status —" in r


def test_dev_check_invalid_scope(tmp_path):
    r = _bind("dev_check_tool", tmp_path)("bogus")
    assert "(ไม่มีอะไรตรวจ" in r


def test_scaffold_tool(tmp_path):
    r = _bind("scaffold_tool", tmp_path)("web-static", "demo")
    assert not r.startswith("Error"), r
    assert (tmp_path / "demo" / "index.html").is_file()


def test_git_pr_tool_no_gh(tmp_path):
    r = _bind("git_pr_tool", tmp_path)("list")
    assert "gh" in r or "Error" in r


def test_git_pr_tool_create_requires_repo(tmp_path):
    r = _bind("git_pr_tool", tmp_path)("create", title="x")
    assert "repo" in r or "Error" in r


# ---- compact chunked ----
class _Msg:
    def __init__(self, content):
        self.content = content


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _FakeClient:
    def __init__(self, log):
        self.chat = _FakeChat(log)


class _FakeChat:
    def __init__(self, log):
        self.completions = _FakeCompletions(log)


class _FakeCompletions:
    def __init__(self, log):
        self.log = log

    def create(self, **kw):
        self.log.append(kw)
        return _Resp("สรุปส่วนนี้แล้ว")


class _FakeAgent:
    def __init__(self):
        self.model = "test-model"
        self.messages = [{"role": "system", "content": "SYS"}]


def test_compact_chunks_and_merges(monkeypatch):
    log = []
    monkeypatch.setattr(yousini, "client", _FakeClient(log))
    a = _FakeAgent()
    # 28 ข้อความเก่า → chunk ละ 6 → 5 รอบสรุป
    for i in range(28):
        a.messages.append({"role": "user" if i % 2 == 0 else "assistant",
                           "content": f"ข้อความที่ {i}"})
    out = Agent.compact(a, keep_last=2)
    assert "ยุบบริบทเหลือ" in out
    assert len(a.messages) == 5                      # sys + สรุป + ack + recent 2
    assert len(log) == 5                             # สรุปทีละ chunk
    merged = a.messages[1]["content"]
    assert "[ส่วน 1]" in merged and "[ส่วน 5]" in merged


def test_compact_short_context(monkeypatch):
    log = []
    monkeypatch.setattr(yousini, "client", _FakeClient(log))
    a = _FakeAgent()
    a.messages.append({"role": "user", "content": "hi"})
    out = Agent.compact(a, keep_last=6)
    assert "ไม่ต้องยุบ" in out
    assert len(a.messages) == 2


def test_compact_single_chunk(monkeypatch):
    log = []
    monkeypatch.setattr(yousini, "client", _FakeClient(log))
    a = _FakeAgent()
    for i in range(4):
        a.messages.append({"role": "user", "content": f"m{i}"})
    out = Agent.compact(a, keep_last=2)
    assert len(a.messages) == 5                     # sys + สรุป + ack + recent 2
    assert "[ส่วน " not in a.messages[1]["content"]   # 1 chunk → ไม่มี prefix ส่วน


def test_estimate_tokens():
    a = _FakeAgent()
    a.messages.append({"role": "user", "content": "abcd" * 4})   # 16 chars → ~4 tokens
    assert Agent._estimate_tokens(a) >= 4