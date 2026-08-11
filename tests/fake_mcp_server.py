#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fake MCP server สำหรับทดสอบ client (Phase 6) — อ่าน JSON-RPC จาก stdin"""
import json
import sys


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        mid = msg.get("id")
        method = msg.get("method", "")
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "fake-mcp", "version": "1.0"}}
        elif method == "tools/list":
            result = {"tools": [{"name": "calc", "description": "คำนวณ a+b",
                                 "inputSchema": {"type": "object",
                                                 "properties": {"a": {"type": "number"},
                                                                "b": {"type": "number"}},
                                                 "required": ["a", "b"]}}]}
        elif method == "tools/call":
            args = (msg.get("params") or {}).get("arguments", {})
            total = args.get("a", 0) + args.get("b", 0)
            result = {"content": [{"type": "text", "text": str(total)}]}
        else:
            result = {}
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": result}) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()