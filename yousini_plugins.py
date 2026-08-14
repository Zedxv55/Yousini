#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Plugin system (v3.8) — โหลดส่วนขยายจากโฟลเดอร์ plugins/ โดยไม่ต้องแก้แกน

โครงสร้าง plugin (แต่ละโฟลเดอร์):
    plugins/
      <name>/
        plugin.json        # meta: name, version, description, enabled (ไม่บังคับ)
        plugin.py          # โค้ด plugin (บังคับ)

plugin.py ใช้ convention:
    NAME / VERSION / DESCRIPTION        # meta (ถ้าไม่มี plugin.json)
    TOOLS = [ {...OpenAI schema...} ]   # ลงทะเบียน tool schema เพิ่ม
    def impl_<tool_name>(args: dict, ctx: dict) -> str   # ตัวทำงานของ tool
    REPL_COMMANDS = {"/cmd": "คำอธิบาย"}                  # เพิ่มคำสั่ง REPL
    def repl_<cmd>(args: str, agent) -> str               # ตัวทำงาน REPL (ชื่อแทน / → _)
    CLI_COMMANDS = {"cmd": "คำอธิบาย"}                     # เพิ่มคำสั่ง CLI
    def cli_<cmd>(argv: list, opts: dict) -> str          # ตัวทำงาน CLI

ctx = {"agent": agent_instance หรือ None, "cwd": โฟลเดอร์ทำงาน}
"""
import importlib.util
import json
import os
import re
import shutil
from pathlib import Path


def _profile_root() -> Path:
    base = Path.home() / ".yousini"
    p = os.getenv("YOUSINI_PROFILE", "").strip()
    active = p
    if not active:
        try:
            f = base / ".active_profile"
            if f.is_file():
                active = f.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    if active and active not in ("", "default"):
        return base / "profiles" / active
    return base


def plugins_dir() -> Path:
    env = os.getenv("YOUSINI_PLUGINS_DIR", "").strip()
    if env:
        return Path(env)
    return _profile_root() / "plugins"


def _iter_dirs() -> list:
    d = plugins_dir()
    if not d.is_dir():
        return []
    return sorted([p for p in d.iterdir() if p.is_dir() and (p / "plugin.py").is_file()],
                  key=lambda p: p.name.lower())


def _load_module(path: Path):
    try:
        spec = importlib.util.spec_from_file_location(f"yousini_plugin_{path.parent.name}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def _meta(dirp: Path, mod=None) -> dict:
    m = {"name": dirp.name, "version": "0.1", "description": "", "enabled": True}
    from_json = set()
    try:
        jf = dirp / "plugin.json"
        if jf.is_file():
            j = json.loads(jf.read_text(encoding="utf-8"))
            if isinstance(j, dict):
                for k in ("name", "version", "description", "enabled"):
                    if k in j:
                        m[k] = j[k]
                        from_json.add(k)
    except Exception:
        pass
    # module attrs เติมเฉพาะที่ plugin.json ไม่ได้ระบุ
    if mod is not None:
        if "name" not in from_json:
            m["name"] = getattr(mod, "NAME", m["name"])
        if "version" not in from_json:
            m["version"] = str(getattr(mod, "VERSION", m["version"]))
        if "description" not in from_json:
            m["description"] = getattr(mod, "DESCRIPTION", m["description"])
    return m


def list_plugins() -> list:
    out = []
    for dirp in _iter_dirs():
        mod = _load_module(dirp / "plugin.py")
        out.append(_meta(dirp, mod))
    return out


def _tool_impls(mod, schemas: list) -> dict:
    """map ชื่อ tool → ฟังก์ชัน impl_<tool> ของ plugin"""
    impls = {}
    for s in schemas:
        name = s.get("function", s).get("name", "")
        fn = getattr(mod, f"impl_{name}", None)
        if callable(fn):
            impls[name] = fn
    return impls


def _collect(mod) -> dict:
    """รวบรวม schemas/impls/repl/cli จากโมดูล plugin"""
    schemas = list(getattr(mod, "TOOLS", []) or [])
    impls = _tool_impls(mod, schemas)

    repl = {}
    for cmd, desc in (getattr(mod, "REPL_COMMANDS", {}) or {}).items():
        key = cmd if cmd.startswith("/") else f"/{cmd}"
        fname = "repl_" + key.lstrip("/").replace("/", "_").replace("-", "_").replace(".", "_")
        fn = getattr(mod, fname, None)
        if callable(fn):
            repl[key] = (fn, desc)

    cli = {}
    for cmd, desc in (getattr(mod, "CLI_COMMANDS", {}) or {}).items():
        fn = getattr(mod, f"cli_{cmd.replace('-', '_').replace('.', '_')}", None)
        if callable(fn):
            cli[cmd] = (fn, desc)
    return {"schemas": schemas, "impls": impls, "repl": repl, "cli": cli}


def load_plugins() -> dict:
    """โหลด plugin ที่ enabled ทั้งหมด → {schemas, impls, repl, cli, plugins}"""
    agg = {"schemas": [], "impls": {}, "repl": {}, "cli": {}, "plugins": []}
    for dirp in _iter_dirs():
        mod = _load_module(dirp / "plugin.py")
        if mod is None:
            continue
        meta = _meta(dirp, mod)
        if not meta.get("enabled", True):
            continue
        c = _collect(mod)
        agg["schemas"].extend(c["schemas"])
        agg["impls"].update(c["impls"])
        agg["repl"].update(c["repl"])
        agg["cli"].update(c["cli"])
        agg["plugins"].append(meta)
    return agg


def install(path: str, name: str = "") -> str:
    """คัดลอกโฟลเดอร์ plugin จาก path (local) ไปไว้ plugins/"""
    src = Path(path)
    if not src.is_dir():
        return f"Error: ไม่พบโฟลเดอร์ '{path}'"
    if not (src / "plugin.py").is_file():
        return f"Error: '{path}' ไม่ใช่ plugin (ไม่มี plugin.py)"
    meta_name = name or src.name
    if not re.match(r"^[a-zA-Z0-9._-]+$", meta_name):
        return f"Error: ชื่อ plugin '{meta_name}' ไม่ถูกต้อง"
    dst = plugins_dir() / meta_name
    if dst.exists():
        return f"Error: plugin '{meta_name}' มีอยู่แล้ว — ลบก่อน (plugin rm {meta_name})"
    plugins_dir().mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return f"ติดตั้ง plugin '{meta_name}' แล้ว → {dst}"


def remove(name: str) -> str:
    p = plugins_dir() / name
    if not p.is_dir():
        return f"ไม่พบ plugin '{name}'"
    shutil.rmtree(p, ignore_errors=True)
    return f"ลบ plugin '{name}' แล้ว"


def plugin_main(argv) -> None:
    """CLI: yousini plugin list | plugin install <path> | plugin rm <name>"""
    from rich.console import Console
    from rich.panel import Panel
    console = Console()
    sub = argv[0].lower() if argv else "list"
    if sub == "list":
        ps = list_plugins()
        if not ps:
            console.print("[yellow]ไม่มี plugin — วางโฟลเดอร์ที่มี plugin.py ลงใน "
                          f"{plugins_dir()}[/yellow]")
            return
        lines = []
        for p in ps:
            mark = "✓" if p.get("enabled", True) else "○"
            lines.append(f"  {mark} {p['name']} v{p['version']} — {p.get('description', '')}")
        console.print(Panel("\n".join(lines), title=f"Plugins ({len(ps)})", border_style="magenta"))
        return
    if sub == "install":
        if len(argv) < 2:
            console.print("[red]ใช้: yousini plugin install <path/to/plugin-folder>[/red]")
            return
        msg = install(argv[1])
        console.print(Panel(msg, title="Plugin install",
                            border_style="green" if not msg.startswith("Error") else "red"))
        return
    if sub == "rm" and len(argv) > 1:
        console.print(Panel(remove(argv[1]), title="Plugin",
                            border_style="green" if not remove(argv[1]).startswith("Error") else "red"))
        return
    console.print("[yellow]ใช้: yousini plugin list | plugin install <path> | plugin rm <name>[/yellow]")


if __name__ == "__main__":
    import sys
    plugin_main(sys.argv[1:])
