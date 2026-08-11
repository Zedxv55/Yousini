"""ทดสอบ Memory ระยะยาว (Phase 1 — เทียบเท่า Hermes memory)"""
import sys, os
os.environ.setdefault("YOUSINI_API_KEY", "dummy-test-key")
os.environ.setdefault("YOUSINI_BASE_URL", "https://api.openai.com/v1")
os.environ.setdefault("YOUSINI_MODEL", "gpt-4o")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yousini_memory
import yousini


def test_memory_add_remove_replace(tmp_path):
    m = yousini_memory.MemoryStore(tmp_path, "user")
    m.add("ผู้ใช้ชอบภาษาไทย")
    assert "ผู้ใช้ชอบภาษาไทย" in m.to_text()
    # add ซ้ำไม่เพิ่มบรรทัดซ้ำ
    m.add("ผู้ใช้ชอบภาษาไทย")
    assert m.to_text().count("ผู้ใช้ชอบภาษาไทย") == 1
    m.replace("ผู้ใช้ชอบภาษาไทย", "ผู้ใช้ชอบภาษาไทยและอังกฤษ")
    assert "และอังกฤษ" in m.to_text()
    m.remove("และอังกฤษ")
    assert "อังกฤษ" not in m.to_text()


def test_memory_persist_across_instances(tmp_path):
    m1 = yousini_memory.MemoryStore(tmp_path, "agent")
    m1.add("เครื่องนี้ใช้ Windows + git-bash")
    m2 = yousini_memory.MemoryStore(tmp_path, "agent")
    assert "git-bash" in m2.to_text()


def test_memory_budget(tmp_path):
    m = yousini_memory.MemoryStore(tmp_path, "user", limit=30)
    m.add("ข้อความยาวเกินงบประมาณที่กำหนดไว้")
    ok, used, limit = m.budget_ok()
    assert ok is False and used > limit


def test_manager_act_and_inject(tmp_path):
    mgr = yousini_memory.MemoryManager(tmp_path)
    mgr.act("add", "user", content="ผู้ใช้สื่อสารภาษาไทย")
    mgr.act("add", "agent", content="shell เป็น git-bash")
    txt = mgr.inject_text()
    assert "[user]" in txt and "ภาษาไทย" in txt
    assert "[agent]" in txt and "git-bash" in txt
    # action/target ผิด → คืนข้อความ error ไม่ crash
    assert "ต้องเป็น" in mgr.act("bogus", "user")
    assert "ต้องเป็น user" in mgr.act("add", "nope", content="x")
    assert "old_text" in mgr.act("remove", "user")
    assert "old_text" in mgr.act("replace", "user", content="x")
    assert "ต้องใส่ content" in mgr.act("add", "user")


def test_system_prompt_includes_memory(tmp_path):
    sp = yousini.build_system_prompt("", [], memory_text="[user] ชอบภาษาไทย")
    assert "=== ความจำระยะยาว" in sp
    assert "ชอบภาษาไทย" in sp
    sp2 = yousini.build_system_prompt("", [], memory_text="")
    assert "=== ความจำระยะยาว" not in sp2