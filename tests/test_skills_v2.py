"""ทดสอบ Skills v2 — frontmatter + สร้าง/แก้ไขสกิลเองได้ (Phase 2)"""
import os, sys
os.environ.setdefault("YOUSINI_API_KEY", "dummy-test-key")
os.environ.setdefault("YOUSINI_BASE_URL", "https://api.openai.com/v1")
os.environ.setdefault("YOUSINI_MODEL", "gpt-4o")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yousini


SKILL_FM = """---
name: deploy
description: Use when deploying to production. Deploy steps.
version: 1
---
# Deploy
รัน deploy ด้วยคำสั่งเหล่านี้...
"""


def test_parse_skill_frontmatter():
    name, desc, body = yousini._parse_skill(SKILL_FM, "fallback")
    assert name == "deploy"
    assert desc.startswith("Use when deploying")
    assert "รัน deploy" in body
    # ไม่มี frontmatter → ใช้ชื่อ fallback + บรรทัดแรกเป็น desc
    name2, desc2, body2 = yousini._parse_skill("# Foo bar\nเนื้อหา", "foo")
    assert name2 == "foo"
    assert body2 == "# Foo bar\nเนื้อหา"


def test_skill_index_with_frontmatter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "deploy.md").write_text(SKILL_FM, encoding="utf-8")
    (tmp_path / "skills" / "plain.md").write_text("# Plain\nโหลดแบบธรรมดา\n", encoding="utf-8")
    idx = yousini.load_skill_index(str(tmp_path))
    # รูปแบบใหม่: (name, desc, source) — รองรับทั้ง 2 แบบ tuple
    by_name = {}
    for item in idx:
        name = item[0] if isinstance(item, (tuple, list)) else item
        by_name[name] = item
    assert "deploy" in by_name
    assert "plain" in by_name
    full = yousini.load_skill_full(str(tmp_path), "deploy")
    assert "รัน deploy" in full


def test_skill_create_and_patch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "skills").mkdir()
    ag = yousini.Agent(interactive=False, cwd=str(tmp_path))
    r1 = ag.skill_create("mytool", "Use when using mytool", "ขั้นตอนใช้ mytool\n")
    assert "สร้าง" in r1
    # index เห็นสกิลใหม่
    assert any("mytool" == (i[0] if isinstance(i, (tuple, list)) else i) for i in ag.skills)
    r2 = ag.skill_patch("mytool", "ขั้นตอน", "ขั้นตอนใหม่")
    assert "แก้" in r2
    full = yousini.load_skill_full(str(tmp_path), "mytool")
    assert "ขั้นตอนใหม่" in full and "ขั้นตอนใช้" not in full
    # patch สกิลที่ไม่มี → error ไม่ crash
    r3 = ag.skill_patch("nope", "x", "y")
    assert "ไม่พบ" in r3


def test_skill_create_global_dir(tmp_path, monkeypatch):
    # ไม่มี ./skills → ไปที่ GLOBAL_SKILLS_DIR (จำลองด้วย env)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("YOUSINI_GLOBAL_SKILLS", str(tmp_path / "global_skills"))
    import importlib
    import yousini as y
    importlib.reload(y)  # โหลดค่า GLOBAL_SKILLS_DIR ใหม่จาก env
    try:
        ag = y.Agent(interactive=False, cwd=str(tmp_path), skills_dir="skills")
        r = ag.skill_create("gskill", "Use when x", "เนื้อหา gskill")
        assert y.GLOBAL_SKILLS_DIR.joinpath("gskill.md").exists()
    finally:
        monkeypatch.delenv("YOUSINI_GLOBAL_SKILLS", raising=False)
        importlib.reload(y)  # คืนค่า default ให้ test อื่น