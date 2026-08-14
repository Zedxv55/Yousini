"""Tests for Database integration (v3.8)."""
import pytest
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from yousini_database import (
    db_query, db_schema, db_export, get_connection, DB_FILE
)
import asyncio


def test_db_simple_query():
    """Test basic SELECT query."""
    result = asyncio.run(db_query("SELECT 1 as test"))
    assert result["success"] is True
    assert len(result["rows"]) == 1
    assert result["rows"][0]["test"] == 1


def test_db_create_table_and_query():
    """Test creating table and querying data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = get_connection(str(db_path))
        conn.execute("CREATE TABLE test (id INTEGER, name TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'hello')")
        conn.commit()
        conn.close()
        
        result = asyncio.run(db_query("SELECT * FROM test", str(db_path)))
        assert result["success"] is True
        assert result["rows"][0]["name"] == "hello"


def test_db_schema_single_table():
    """Test getting table schema."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = get_connection(str(db_path))
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)")
        conn.commit()
        conn.close()
        
        result = asyncio.run(db_schema("users", str(db_path)))
        assert result["success"] is True
        assert result["table"] == "users"
        assert len(result["columns"]) == 3


def test_db_list_all_tables():
    """Test listing all tables in database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = get_connection(str(db_path))
        conn.execute("CREATE TABLE table_a (id INTEGER)")
        conn.execute("CREATE TABLE table_b (id INTEGER)")
        conn.commit()
        conn.close()
        
        result = asyncio.run(db_schema(None, str(db_path)))
        assert result["success"] is True
        assert "table_a" in result["tables"]
        assert "table_b" in result["tables"]


def test_db_export_json():
    """Test exporting table as JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = get_connection(str(db_path))
        conn.execute("CREATE TABLE items (id INTEGER, value TEXT)")
        conn.execute("INSERT INTO items VALUES (1, 'test1'), (2, 'test2')")
        conn.commit()
        conn.close()
        
        result = asyncio.run(db_export("items", str(db_path)))
        assert result["success"] is True
        assert "json" in result
        assert "test1" in result["json"]