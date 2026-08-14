#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Feature flags & config (v3.8) — จัดการตั้งค่า/เปิด-ปิดความสามารถผ่านไฟล์ config.json เดียว

- `features` dict ใน config.json: เปิด/ปิดความสามารถแต่ละอย่าง (default เปิดทั้งหมด)
- get/set ค่าทั่วไป (top-level keys) เช่น theme, marketplace_enabled, quiet_mode
- ใช้ร่วมกับ /config, /flag ใน REPL และ `yousini config` / `yousini flag` ใน CLI
"""
import json
import os
from pathlib import Path

DEFAULT_FEATURES = {
    "plugin_system": True,      # โหลด plugin จากโฟลเดอร์ plugins/
    "usage_report": True,       # สรุปการใช้งานอัตโนมัติ (/usage report)
    "workflow_templates": True, # เทมเพลตงานอัตโนมัติ (/workflow)
    "session_io": True,         # export/import session (/export /import)
    "self_update": True,        # อัปเดตตัวเอง (/update, yousini update)
    "marketplace": True,        # marketplace skills/tools
    "team": True,               # collaboration workspace
}


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


def config_file() -> Path:
    env = os.getenv("YOUSINI_CONFIG_FILE", "").strip()
    if env:
        return Path(env)
    return _profile_root() / "config.json"


def load() -> dict:
    try:
        d = json.loads(config_file().read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            return {}
        return d
    except Exception:
        return {}


def save(cfg: dict) -> None:
    config_file().parent.mkdir(parents=True, exist_ok=True)
    config_file().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def all_flags() -> dict:
    """คืน flags ทั้งหมด = default + ที่ผู้ใช้ปรับ"""
    out = dict(DEFAULT_FEATURES)
    out.update(load().get("features", {}) or {})
    return out


def get_flag(name: str, default: bool = True) -> bool:
    saved = load().get("features", {}) or {}
    if name in saved:
        return bool(saved[name])
    return bool(DEFAULT_FEATURES.get(name, default))


def set_flag(name: str, value: bool) -> str:
    cfg = load()
    features = cfg.setdefault("features", {})
    features[name] = bool(value)
    save(cfg)
    state = "เปิด" if value else "ปิด"
    return f"flag '{name}' = {state} แล้ว (มีผลครั้งถัดไป/รีสตาร์ท)"

def flag_cmd(args: str) -> str:
    """CLI/REPL: flag list | flag <ชื่อ> [on|off]"""
    parts = (args or "").strip().split()
    if not parts or parts[0].lower() in ("list", ""):
        lines = []
        for name, val in all_flags().items():
            lines.append(f"  {'✓' if val else '○'} {name}  {'(เปิด)' if val else '(ปิด)'}")
        return "Feature flags:\n" + "\n".join(lines) if lines else "ไม่มี flags"
    name = parts[0].lower()
    if name not in DEFAULT_FEATURES:
        return f"ไม่รู้จัก flag '{name}' — มี: " + ", ".join(sorted(DEFAULT_FEATURES))
    if len(parts) >= 2:
        v = parts[1].lower() in ("on", "1", "true", "yes", "เปิด")
        return set_flag(name, v)
    cur = get_flag(name)
    return f"flag '{name}' = {'เปิด' if cur else 'ปิด'} (ตั้งด้วย: flag {name} on|off)"


def get_value(key: str):
    """อ่านค่าทั่วไป (top-level) จาก config.json — รองรับ a.b สำหรับ dict"""
    d = load()
    cur = d
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def set_value(key: str, value) -> str:
    """เขียนค่าทั่วไป (top-level) — แยก . สำหรับลง dict ซ้อน เช่น features.plugin_system"""
    cfg = load()
    parts = key.split(".")
    cur = cfg
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    if isinstance(value, str):
        low = value.lower()
        if low in ("true", "false"):
            value = low == "true"
        elif low in ("null", "none"):
            value = None
        elif value.isdigit():
            value = int(value)
    cur[parts[-1]] = value
    save(cfg)
    return f"config '{key}' = {json.dumps(value, ensure_ascii=False)} แล้ว"


def config_cmd(args: str) -> str:
    """CLI/REPL: config list | config get <key> | config set <key> <value>"""
    parts = (args or "").strip().split(None, 2)
    sub = parts[0].lower() if parts else "list"
    if sub == "flags" or sub == "flag":
        return flag_cmd(" ".join(parts[1:]))
    if sub == "list":
        cfg = load()
        if not cfg:
            return "(config.json ว่าง — ยังไม่มีค่าที่บันทึก)"
        lines = []
        for k, v in sorted(cfg.items()):
            lines.append(f"  {k} = {json.dumps(v, ensure_ascii=False)[:80]}")
        return "config.json:\n" + "\n".join(lines)
    if sub == "get" and len(parts) > 1:
        v = get_value(parts[1])
        return f"config '{parts[1]}' = {json.dumps(v, ensure_ascii=False) if v is not None else '(ไม่มีค่า)'}"
    if sub == "set" and len(parts) > 2:
        return set_value(parts[1], parts[2])
    return ("ใช้: config list | config get <key> | config set <key> <value> "
            "| config flag [<name> [on|off]]")


if __name__ == "__main__":
    print(config_cmd("list"))
