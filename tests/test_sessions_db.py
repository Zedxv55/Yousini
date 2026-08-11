"""ทดสอบ Session Search — SQLite + FTS5 + LIKE fallback สำหรับภาษาไทย (Phase 3)"""
import os, sys
os.environ.setdefault("YOUSINI_API_KEY", "dummy-test-key")
os.environ.setdefault("YOUSINI_BASE_URL", "https://api.openai.com/v1")
os.environ.setdefault("YOUSINI_MODEL", "gpt-4o")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yousini_sessions_db import SessionSearch


def _sample_messages():
    return [
        {"role": "user", "content": "ช่วยเขียนเว็บขายของหน่อย"},
        {"role": "assistant", "content": "สร้าง index.html และ app.js แล้ว เปิดดูได้ที่ localhost:8000"},
        {"role": "user", "content": "เพิ่มฟีเจอร์ login ด้วย flask"},
    ]


def test_index_and_search_english(tmp_path):
    s = SessionSearch(tmp_path / "sessions.db")
    s.index_messages("s1", _sample_messages(), "2026-08-11T00:00:00", {"model": "x"})
    res = s.search("login")
    assert any(r["session"] == "s1" for r in res)
    assert res[0]["saved_at"] == "2026-08-11T00:00:00"


def test_search_thai_substring(tmp_path):
    """ภาษาไทยไม่มีเว้นวรรค → FTS5 จับเป็น 1 token ต้องใช้ LIKE fallback"""
    s = SessionSearch(tmp_path / "sessions.db")
    s.index_messages("s2", _sample_messages(), "2026-08-11T00:00:00")
    res = s.search("เว็บขายของ")
    assert any(r["session"] == "s2" for r in res)


def test_no_match(tmp_path):
    s = SessionSearch(tmp_path / "sessions.db")
    s.index_messages("s3", _sample_messages(), "2026-08-11T00:00:00")
    assert s.search("zzzzqqqq") == []


def test_reindex_same_name_replaces(tmp_path):
    s = SessionSearch(tmp_path / "sessions.db")
    s.index_messages("s4", _sample_messages(), "2026-08-11T00:00:00")
    s.index_messages("s4", [{"role": "user", "content": "ข้อความใหม่ล่าสุด"}], "2026-08-11T01:00:00")
    assert len(s.search("ข้อความใหม่")) == 1
    assert s.search("login") == []  # ข้อความเก่าถูกลบ


def test_sessionstore_search_wired(tmp_path):
    import yousini
    store = yousini.SessionStore(tmp_path)
    store.save("s5", _sample_messages(), {"model": "x"})
    res = store.search("flask")
    assert any(r["session"] == "s5" for r in res)
    # API เดิมยังทำงานเหมือนเดิม
    assert store.load("s5") is not None
    assert len(store.list()) == 1