"""ทดสอบ MCP Client — เรียกเครื่องมือจาก MCP server ภายนอก (Phase 6)"""
import os, sys, subprocess, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yousini_mcp import McpStdioClient, connect_all, load_mcp_config

SERVER = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake_mcp_server.py")]


def test_mcp_stdio_roundtrip():
    client = McpStdioClient("fake", SERVER)
    try:
        tools = client.list_tools()
        assert any(t["name"] == "calc" for t in tools)
        res = client.call_tool("calc", {"a": 3, "b": 4})
        assert res["content"][0]["text"] == "7"
    finally:
        client.close()


def test_mcp_tools_prefix_and_impl(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUSINI_MCP_FILE", str(tmp_path / "mcp.json"))
    (tmp_path / "mcp.json").write_text(
        json.dumps([{"name": "calc-server", "cmd": SERVER}]), encoding="utf-8")
    schemas, impls = connect_all()
    names = [s["function"]["name"] for s in schemas]
    assert "mcp__calc-server__calc" in names
    impl = dict(impls).get("mcp__calc-server__calc")
    assert impl is not None
    out = impl({"a": 10, "b": 5}, None)
    assert out == "15"


def test_mcp_load_config_env(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUSINI_MCP_FILE", str(tmp_path / "mcp.json"))
    (tmp_path / "mcp.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("YOUSINI_MCP_SERVERS", json.dumps([{"name": "a", "cmd": "python x.py"}]))
    cfg = load_mcp_config()
    assert cfg == {"a": "python x.py"}