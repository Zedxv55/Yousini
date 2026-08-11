#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MCP Client — เรียกใช้เครื่องมือจาก MCP server ภายนอก (Phase 6 เทียบเท่า Hermes MCP)

- stdio server: {"name": "...", "cmd": "python server.py"}  (หรือคำสั่งเต็ม)
- ไฟล์ตั้งค่า: ~/.yousini/mcp.json  หรือ env YOUSINI_MCP_SERVERS (JSON array)
- โหลดตอนเริ่ม agent → เครื่องมือทุกตัวจาก server ขึ้นชื่อนำหน้า mcp__<server>__<tool>
"""
import json
import os
import shlex
import subprocess
from pathlib import Path

MCP_FILE = Path(os.getenv("YOUSINI_MCP_FILE", str(Path.home() / ".yousini" / "mcp.json")))


class McpStdioClient:
    """คุยกับ MCP server ผ่าน stdin/stdout ด้วย JSON-RPC 2.0"""

    def __init__(self, name, cmd, timeout=30):
        self.name = name
        self.timeout = timeout
        if isinstance(cmd, str):
            cmd = shlex.split(cmd, posix=(os.name != "nt"))  # Windows: กัน backslash หาย
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            bufsize=1)
        self._id = 0
        self.server_info = {}
        try:
            self.server_info = self._rpc("initialize", {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "yousini", "version": "2.0"}})
            self._rpc("notifications/initialized")
        except Exception:
            self.close()
            raise

    def _rpc(self, method, params=None):
        self._id += 1
        req = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError(f"MCP '{self.name}': server ปิด connection")
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if msg.get("id") == self._id:
                if "error" in msg:
                    raise RuntimeError(f"MCP '{self.name}': {msg['error']}")
                return msg.get("result", {})

    def list_tools(self):
        res = self._rpc("tools/list")
        return res.get("tools", [])

    def call_tool(self, tool_name, args):
        return self._rpc("tools/call", {"name": tool_name, "arguments": args})

    def close(self):
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
        except Exception:
            pass


def _mcp_file():
    """อ่าน env ตอนเรียก — รองรับการแก้ env หลัง import (เช่นใน test)"""
    return Path(os.getenv("YOUSINI_MCP_FILE", str(Path.home() / ".yousini" / "mcp.json")))


def load_mcp_config():
    """คืน [{name, cmd}] จาก mcp.json + env YOUSINI_MCP_SERVERS"""
    out = {}
    try:
        cfg = json.loads(_mcp_file().read_text(encoding="utf-8"))
        for s in cfg if isinstance(cfg, list) else cfg.get("servers", []):
            if isinstance(s, dict) and s.get("name") and s.get("cmd"):
                out[s["name"]] = s["cmd"]
    except Exception:
        pass
    raw = os.getenv("YOUSINI_MCP_SERVERS", "")
    if raw:
        try:
            for s in json.loads(raw):
                if isinstance(s, dict) and s.get("name") and s.get("cmd"):
                    out[s["name"]] = s["cmd"]
        except Exception:
            pass
    return out


def _format_result(res):
    """แปลงผล tools/call เป็นข้อความสั้นๆ"""
    outs = []
    for c in res.get("content", []):
        if c.get("type") == "text":
            outs.append(c["text"])
        elif c.get("type") == "resource":
            outs.append(json.dumps(c.get("resource", {}), ensure_ascii=False))
    if outs:
        return "\n".join(outs)
    if res.get("isError"):
        return f"Error: {res}"
    return json.dumps(res, ensure_ascii=False)[:2000]


def _make_impl(client, tool_name):
    def impl(a, k):
        try:
            res = client.call_tool(tool_name, a)
            return _format_result(res)
        except Exception as e:
            return f"Error: MCP tool '{tool_name}': {e}"
    return impl


def connect_all():
    """เชื่อมต่อทุก MCP server ที่ตั้งค่า → คืน [(schema_dict, impl_fn)]"""
    schemas, impls = [], []
    for name, cmd in load_mcp_config().items():
        try:
            client = McpStdioClient(name, cmd)
        except Exception as e:
            print(f"⚠️ MCP server '{name}' เชื่อมไม่สำเร็จ: {e}")
            continue
        try:
            for t in client.list_tools():
                tname = t.get("name", "")
                if not tname:
                    continue
                schemas.append({"type": "function", "function": {
                    "name": f"mcp__{name}__{tname}",
                    "description": f"[MCP:{name}] {t.get('description', '')}",
                    "parameters": t.get("inputSchema") or {"type": "object", "properties": {}}}})
                impls.append((f"mcp__{name}__{tname}", _make_impl(client, tname)))
        except Exception as e:
            print(f"⚠️ MCP server '{name}' list_tools ล้ม: {e}")
            try:
                client.close()
            except Exception:
                pass
    return schemas, impls