#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Usage & cost telemetry (local, opt-in) — นับ token/tool/turn ต่อเซสชันและต่อวัน

- เก็บเฉพาะในเครื่อง (~/.yousini/usage.json) — ไม่มีการส่งข้อมูลออก 100%
- เป็น opt-in: ต้องเปิดก่อน (/usage on) — default ปิด เพื่อความน่าเชื่อถือ (trust-first)
- ใช้เป็นฐานสำหรับโควตา Pro และช่วยให้ผู้ใช้เห็นค่าใช้จ่าย token จริง
"""
import json
import os
import threading
from datetime import datetime
from pathlib import Path

_LOCK = threading.RLock()
_ENABLED = None  # cache หลังอ่านครั้งแรก — กันอ่านไฟล์ทุก chunk ใน streaming


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


def _usage_file() -> Path:
    return _profile_root() / "usage.json"


def _blank() -> dict:
    return {
        "opt_in": False,
        "days": {},
        "session": {"start": datetime.now().isoformat(timespec="seconds"),
                    "prompt": 0, "completion": 0, "turns": 0, "tools": {}},
    }


def _load() -> dict:
    try:
        d = json.loads(_usage_file().read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            d = _blank()
        d.setdefault("opt_in", False)
        d.setdefault("days", {})
        s = d.setdefault("session", {})
        s.setdefault("start", datetime.now().isoformat(timespec="seconds"))
        s.setdefault("prompt", 0); s.setdefault("completion", 0)
        s.setdefault("turns", 0); s.setdefault("tools", {})
        return d
    except Exception:
        return _blank()


def _save(d: dict) -> None:
    try:
        _usage_file().parent.mkdir(parents=True, exist_ok=True)
        _usage_file().write_text(json.dumps(d, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    except Exception:
        pass


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def is_enabled() -> bool:
    global _ENABLED
    if _ENABLED is None:
        with _LOCK:
            if _ENABLED is None:
                _ENABLED = bool(_load().get("opt_in"))
    return _ENABLED


def set_enabled(flag: bool) -> bool:
    global _ENABLED
    with _LOCK:
        d = _load()
        d["opt_in"] = bool(flag)
        _save(d)
        _ENABLED = d["opt_in"]
        return _ENABLED


def _bump(bucket: dict, key: str, val: int) -> None:
    bucket[key] = int(bucket.get(key, 0)) + int(val or 0)


def record_tokens(prompt: int, completion: int) -> None:
    if not is_enabled():
        return
    with _LOCK:
        d = _load()
        dt = d["days"].setdefault(_today(),
                                  {"prompt": 0, "completion": 0, "turns": 0, "tools": {}})
        _bump(dt, "prompt", prompt); _bump(dt, "completion", completion)
        _bump(d["session"], "prompt", prompt); _bump(d["session"], "completion", completion)
        _save(d)


def record_tool(name: str) -> None:
    if not is_enabled():
        return
    with _LOCK:
        d = _load()
        dt = d["days"].setdefault(_today(),
                                  {"prompt": 0, "completion": 0, "turns": 0, "tools": {}})
        dt["tools"][name] = int(dt["tools"].get(name, 0)) + 1
        d["session"]["tools"][name] = int(d["session"]["tools"].get(name, 0)) + 1
        _save(d)


def record_turn() -> None:
    if not is_enabled():
        return
    with _LOCK:
        d = _load()
        dt = d["days"].setdefault(_today(),
                                  {"prompt": 0, "completion": 0, "turns": 0, "tools": {}})
        _bump(dt, "turns", 1)
        _bump(d["session"], "turns", 1)
        _save(d)


def _fmt_tools(tools: dict) -> list[str]:
    out = []
    for name in sorted(tools, key=lambda n: -tools[n]):
        out.append(f"  - {name:<16}: {tools[name]} ครั้ง")
    return out


def summary() -> str:
    """สรุปรวม: วันนี้ + เซสชันปัจจุบัน + ทั้งหมด (เฉพาะเมื่อเปิดใช้งาน)"""
    with _LOCK:
        d = _load()
    if not d.get("opt_in"):
        return "ปิดใช้งาน — สั่ง /usage on เพื่อเริ่มเก็บสถิติ (เก็บเฉพาะในเครื่อง ไม่ส่งออก)"
    days = d.get("days", {})
    today = _today()
    dt = days.get(today, {})
    sess = d.get("session", {})
    all_p = sum(x.get("prompt", 0) for x in days.values())
    all_c = sum(x.get("completion", 0) for x in days.values())
    all_turns = sum(x.get("turns", 0) for x in days.values())
    all_tools = {}
    for x in days.values():
        for k, v in (x.get("tools", {}) or {}).items():
            all_tools[k] = all_tools.get(k, 0) + v

    def tok(p, c):
        return f"{p + c:,} tok (in {p:,} / out {c:,})"

    lines = [f"วันนี้ ({today}): {tok(dt.get('prompt', 0), dt.get('completion', 0))} · "
             f"{dt.get('turns', 0)} turns · {sum((dt.get('tools') or {}).values())} tools"]
    lines += _fmt_tools(dt.get("tools", {}))
    lines.append(f"เซสชันนี้: {tok(sess.get('prompt', 0), sess.get('completion', 0))} · "
                 f"{sess.get('turns', 0)} turns · {sum((sess.get('tools') or {}).values())} tools")
    lines.append(f"รวมทั้งหมด: {tok(all_p, all_c)} · {all_turns} turns · {len(all_tools)} tools")
    return "\n".join(lines)


def summary_short() -> str:
    with _LOCK:
        d = _load()
    if not d.get("opt_in"):
        return "(ปิดสถิติ)"
    sess = d.get("session", {})
    p = sess.get("prompt", 0); c = sess.get("completion", 0)
    return (f"{p + c:,} tok (in {p:,}/out {c:,}) · "
            f"{sess.get('turns', 0)} turns · {sum((sess.get('tools') or {}).values())} tools")


def reset() -> None:
    with _LOCK:
        was = _ENABLED if _ENABLED is not None else bool(_load().get("opt_in"))
        d = _blank()
        d["opt_in"] = was  # ล้างสถิติ แต่คงการตั้งค่าการเก็บไว้
        _save(d)


if __name__ == "__main__":
    print(summary())