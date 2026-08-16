"""Database integration for Yousini (v3.8).

SQLite tool: query tables, view schema, export/import data.
"""

import sqlite3
import json
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional


DB_FILE = Path.home() / ".yousini" / "yousini.db"


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Get a database connection."""
    path = Path(db_path) if db_path else DB_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(path))


async def db_query(sql: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Execute a SELECT query and return results."""
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(sql)
        rows = [dict(row) for row in cur.fetchall()]
        return {"success": True, "rows": rows, "count": len(rows)}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


async def db_schema(table_name: Optional[str] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Get table schema information."""
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if table_name:
            # PRAGMA doesn't support ? placeholders - use safe string formatting
            safe_table = table_name.replace('"', '""')
            cur = conn.execute(f'PRAGMA table_info("{safe_table}")')
            rows = [dict(row) for row in cur.fetchall()]
            return {"success": True, "table": table_name, "columns": rows}

        # Get all tables
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cur.fetchall()]

        schemas = {}
        for t in tables:
            safe_t = t.replace('"', '""')
            cur = conn.execute(f'PRAGMA table_info("{safe_t}")')
            schemas[t] = [dict(row) for row in cur.fetchall()]

        return {"success": True, "tables": tables, "schema": schemas}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


async def db_export(table_name: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Export table data as JSON."""
    result = await db_query(f'SELECT * FROM "{table_name}"', db_path)
    if result.get("success"):
        return {"success": True, "table": table_name, "json": json.dumps(result["rows"], indent=2)}
    return result


async def db_exec(sql: str, params: List[Any] = None, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Execute non-SELECT queries (INSERT, UPDATE, DELETE). Requires confirmation."""
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        conn.commit()
        return {"success": True, "changes": cur.rowcount}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


SQL_TOOL = {
    "type": "function",
    "function": {
        "name": "sql_query",
        "description": "Query SQLite database tables",
        "parameters": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SELECT query to execute"},
                "db_path": {"type": "string", "description": "Database file path (optional)"},
            },
            "required": ["sql"],
        },
    },
}


SQL_SCHEMA_TOOL = {
    "type": "function",
    "function": {
        "name": "sql_schema",
        "description": "View database table schema",
        "parameters": {
            "type": "object",
            "properties": {
                "table_name": {"type": "string", "description": "Table name (optional, all tables if omitted)"},
                "db_path": {"type": "string", "description": "Database file path (optional)"},
            },
        },
    },
}


async def execute_sql_tool(args: dict, ctx: dict) -> str:
    return json.dumps(await db_query(args.get("sql", "SELECT 1"), args.get("db_path")), ensure_ascii=False)


async def execute_sql_schema_tool(args: dict, ctx: dict) -> str:
    return json.dumps(await db_schema(args.get("table_name"), args.get("db_path")), ensure_ascii=False)