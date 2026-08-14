#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Session Search — ค้นหาย้อนหลังใน session ทั้งหมด (เทียบเท่า session_search ของ Hermes)

- SQLite + FTS5 สำหรับภาษาอังกฤษ/คำเดี่ยว
- LIKE fallback สำหรับภาษาไทย (ไม่มีเว้นวรรค → FTS5 จับเป็น token เดียว ไม่ match)
- ทุกครั้งที่ SessionStore.save() ถูกเรียก จะ re-index ลงฐานข้อมูลนี้โดยอัตโนมัติ
"""
import json
import re
import sqlite3
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE,
  saved_at TEXT,
  meta TEXT
);
CREATE TABLE IF NOT EXISTS messages (
  msg_id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER,
  role TEXT,
  content TEXT,
  seq INTEGER,
  FOREIGN KEY(session_id) REFERENCES sessions(id)
);
"""


class SessionSearch:
    def __init__(self, db_path, fts=True):
        self.db_path = str(db_path)
        self.fts = fts
        conn = self._conn()
        try:
            conn.executescript(SCHEMA)
            if self.fts:
                conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5("
                    "content, content='messages', content_rowid='msg_id')")
        except sqlite3.OperationalError:
            self.fts = False  # SQLite build ไหนไม่มี FTS5 → ใช้ LIKE อย่างเดียว
        conn.commit()
        conn.close()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def index_messages(self, name, messages, saved_at=None, meta=None):
        """บันทึก/แทนที่ทั้ง session ในฐานข้อมูล (re-index ครั้งละทั้ง session)"""
        conn = self._conn()
        try:
            conn.execute(
                "DELETE FROM messages WHERE session_id IN "
                "(SELECT id FROM sessions WHERE name=?)", (name,))
            conn.execute("DELETE FROM sessions WHERE name=?", (name,))
            cur = conn.execute(
                "INSERT INTO sessions (name, saved_at, meta) VALUES (?,?,?)",
                (name, saved_at or datetime.now().isoformat(),
                 json.dumps(meta or {}, ensure_ascii=False)))
            sid = cur.lastrowid
            for i, m in enumerate(messages):
                if not isinstance(m, dict):
                    continue
                content = str(m.get("content", ""))
                role = str(m.get("role", ""))
                cur = conn.execute(
                    "INSERT INTO messages (session_id, role, content, seq) VALUES (?,?,?,?)",
                    (sid, role, content, i))
                if self.fts and content.strip():
                    conn.execute(
                        "INSERT INTO messages_fts (rowid, content) VALUES (?,?)",
                        (cur.lastrowid, content))
            conn.commit()
        finally:
            conn.close()

    def search(self, query, limit=10):
        """ค้นหาข้ามทุก session — คืน [{session, role, snippet, saved_at}] เรียงตามความเกี่ยวข้อง"""
        query = (query or "").strip()
        if not query:
            return []
        rows = []
        seen = set()
        conn = self._conn()
        try:
            if self.fts:
                safe = re.sub(r'["*()]', " ", query)
                try:
                    cur = conn.execute(
                        "SELECT s.name, m.role, m.content, s.saved_at, "
                        "snippet(messages_fts, 0, '…', '…', '…', 10) AS snip "
                        "FROM messages_fts "
                        "JOIN messages m ON m.msg_id = messages_fts.rowid "
                        "JOIN sessions s ON s.id = m.session_id "
                        "WHERE messages_fts MATCH ? ORDER BY m.seq LIMIT ?",
                        (safe, limit * 3))
                    for r in cur:
                        if r["name"] in seen:
                            continue
                        seen.add(r["name"])
                        rows.append({"session": r["name"], "role": r["role"],
                                     "snippet": (r["snip"] or r["content"])[:200],
                                     "saved_at": r["saved_at"]})
                except sqlite3.OperationalError:
                    pass
            # LIKE fallback — ภาษาไทยและข้อความย่อยใดๆ
            cur = conn.execute(
                "SELECT s.name, m.role, m.content, s.saved_at "
                "FROM messages m JOIN sessions s ON s.id = m.session_id "
                "WHERE m.content LIKE ? ORDER BY m.seq LIMIT ?",
                (f"%{query}%", limit * 3))
            for r in cur:
                if r["name"] in seen:
                    continue
                seen.add(r["name"])
                rows.append({"session": r["name"], "role": r["role"],
                             "snippet": r["content"][:200],
                             "saved_at": r["saved_at"]})
        finally:
            conn.close()
        return rows[:limit]

    def count(self):
        """จำนวน session ทั้งหมดในฐาน"""
        conn = self._conn()
        try:
            return conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
        finally:
            conn.close()

    def recent(self, limit=10):
        """session ล่าสุด — [{name, saved_at, msgs}] เรียงตามเวลาบันทึก"""
        conn = self._conn()
        try:
            cur = conn.execute(
                "SELECT s.name, s.saved_at, s.meta, "
                "(SELECT COUNT(*) FROM messages m WHERE m.session_id=s.id) AS msgs "
                "FROM sessions s ORDER BY s.saved_at DESC LIMIT ?", (limit,))
            return [{"name": r["name"], "saved_at": r["saved_at"], "msgs": r["msgs"]}
                    for r in cur]
        finally:
            conn.close()