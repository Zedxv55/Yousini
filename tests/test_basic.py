"""ทดสอบโครงสร้างและลอจิกพื้นฐานของ Yousini (ไม่ต้องมี API Key จริง)
รันได้ด้วย:  pytest  (หรือ python -m pytest)
"""
import os
import sys
import json
import tempfile

# ต้องตั้งค่า env ก่อน import โมดูล (โมดูลอ่าน API key ตอน import)
os.environ.setdefault("YOUSINI_API_KEY", "dummy-test-key")
os.environ.setdefault("YOUSINI_BASE_URL", "https://api.openai.com/v1")
os.environ.setdefault("YOUSINI_MODEL", "gpt-4o")

import yousini


def test_is_dangerous():
    assert yousini.is_dangerous("rm -rf /")
    assert yousini.is_dangerous("dd if=/dev/zero of=/dev/sda")
    assert not yousini.is_dangerous("ls -la")
    assert not yousini.is_dangerous("echo hello")


def test_context_and_skills(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "YOUSINI.md").write_text("# โปรเจกต์ X\nกฎ: ใช้ภาษาไทย\n", encoding="utf-8")
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "dep.md").write_text("# Skill dep\nรัน pip install\n", encoding="utf-8")
    ctx = yousini.load_context_text(str(tmp_path))
    skills = yousini.load_skills(str(tmp_path))
    sp = yousini.build_system_prompt(ctx, skills)
    assert "โปรเจกต์ X" in ctx
    assert len(skills) == 1
    assert "Skill: dep" in sp
    assert "บริบทโปรเจกต์" in sp


def test_session_store(tmp_path):
    store = yousini.SessionStore(tmp_path / "sessions")
    store.save("demo", [{"role": "user", "content": "hi"}], {"model": "x"})
    loaded = store.load("demo")
    assert loaded["messages"][0]["content"] == "hi"
    names = [s["name"] for s in store.list()]
    assert "demo" in names


def test_mcp_tool_schema():
    tools = yousini._tools_to_mcp()
    names = [t["name"] for t in tools]
    for required in ("shell", "read_file", "web_search", "read_job"):
        assert required in names
    for t in tools:
        assert "inputSchema" in t
        assert t["inputSchema"]["type"] == "object"


def test_web_search_no_crash():
    # ไม่มีเน็ตหรือ parser พัง ต้องคืน string ไม่ crash
    result = yousini.web_search_robust("query that will fail offline", 3)
    assert isinstance(result, str)


def test_hooks_resolution(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    hooks_dir = tmp_path / ".yousini" / "hooks"
    hooks_dir.mkdir(parents=True)
    # ใช้ .bat (cmd) เพื่อรันได้บนทุกแพลตฟอร์มในเทสต์
    (hooks_dir / "pre_tool.bat").write_text("@echo off\nexit 0\n", encoding="utf-8")
    h = yousini.Hooks(str(hooks_dir), str(tmp_path))
    assert h.has_hooks() is True
    # ไม่มี hooks → อนุญาตเสมอ (fail-open)
    clean = tmp_path / "clean"
    clean.mkdir()
    h2 = yousini.Hooks(None, str(clean))
    allowed, _ = h2.run_pre("shell", {"command": "ls"})
    assert allowed is True


def test_jobs_manager(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ag = yousini.Agent(interactive=False, cwd=str(tmp_path))
    # ไม่รันจริง (ไม่มี bash ในบางสภาพแวดล้อม) แค่เช็คว่ามี manager
    assert ag.jobs is not None
    assert "ไม่มีงาน" in ag.jobs.summary()
