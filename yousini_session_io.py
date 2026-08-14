#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Export/Import session (v3.8) — ย้ายบทสนทนา/สำรองข้อมูลข้ามเครื่อง

- export: session → ไฟล์ JSON (เต็ม) หรือ Markdown (อ่านง่าย + รวม summary)
- import: ไฟล์ JSON (จาก export หรือไฟล์ session เดิม) → บันทึกลง session store ใหม่
- ทำงานผ่าน SessionStore ที่ส่งเข้ามา (หลีกเลี่ยง circular import)
"""
import json
from datetime import datetime
from pathlib import Path

_DEFAULT_OUT = str(Path.home() / ".yousini" / "exports")


def export_session(store, name: str, out: str = "", fmt: str = "json") -> dict:
    """export session ตามชื่อ → ไฟล์ (json|md) คืน {ok, path, name, fmt, count}"""
    d = store.load(name)
    if not d:
        return {"ok": False, "error": f"ไม่พบ session '{name}' — ดูรายการด้วย /sessions"}
    fmt = (fmt or "json").lower()
    if fmt not in ("json", "md", "markdown"):
        return {"ok": False, "error": "fmt ต้องเป็น json หรือ md"}
    if fmt == "markdown":
        fmt = "md"
    out_p = Path(out) if out else Path(_DEFAULT_OUT)
    if out_p.is_dir() or str(out_p).endswith("/"):
        safe = _safe(name)
        out_p = out_p / f"{safe}.{fmt}"
    out_p.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        data = d
        data["exported_at"] = datetime.now().isoformat()
        out_p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        out_p.write_text(_to_markdown(d), encoding="utf-8")
    n = len(d.get("messages", []))
    return {"ok": True, "path": str(out_p), "name": name, "fmt": fmt, "count": n}


def import_session(store, path: str, new_name: str = "") -> dict:
    """import ไฟล์ JSON session → บันทึกลง store คืน {ok, name, count}"""
    p = Path(path)
    if not p.is_file():
        return {"ok": False, "error": f"ไม่พบไฟล์ '{path}'"}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"อ่านไฟล์ JSON ไม่ได้: {e}"}
    messages = d.get("messages", []) if isinstance(d, dict) else []
    if not isinstance(messages, list) or not messages:
        return {"ok": False, "error": "ไฟล์ไม่ใช่ session ที่ถูกต้อง (ไม่มี messages)"}
    meta = d.get("meta", {}) if isinstance(d, dict) else {}
    meta.setdefault("imported_from", str(p))
    name = (new_name or d.get("name") or p.stem).strip()
    try:
        store.save(name, messages, meta)
    except Exception as e:
        return {"ok": False, "error": f"บันทึกไม่สำเร็จ: {e}"}
    return {"ok": True, "name": name, "count": len(messages)}


def _safe(name: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


def _to_markdown(d: dict) -> str:
    """แปลง session → Markdown (อ่านง่าย + สรุปย่อหัวท้าย)"""
    name = d.get("name", "session")
    meta = d.get("meta", {}) or {}
    lines = [f"# Session: {name}", ""]
    if meta:
        lines.append("| meta | |")
        lines.append("|---|---|")
        for k, v in list(meta.items())[:12]:
            lines.append(f"| {k} | {v} |")
        lines.append("")
    for m in d.get("messages", []):
        role = m.get("role", "")
        content = str(m.get("content") or "")
        if role == "system":
            lines.append(f"## System\n\n```\n{content[:400]}\n```")
        elif role == "tool":
            lines.append(f"> [tool-result] `{content[:200]}`")
        elif role == "assistant":
            lines.append(f"**Assistant:**\n\n{content}")
        else:
            lines.append(f"**User:**\n\n{content}")
        lines.append("")
    summary = meta.get("summary")
    if summary:
        lines.append("---")
        lines.append(f"**Summary:** {summary}")
    return "\n".join(lines)


def session_io_main(store, argv) -> str:
    """CLI: yousini session export <ชื่อ> [--out ไฟล์] [--md] | session import <ไฟล์> [--name ชื่อ]"""
    sub = argv[0].lower() if argv else "help"
    if sub in ("help", ""):
        return ("ใช้: yousini session export <ชื่อ> [--out <ไฟล์>] [--md]  |  "
                "yousini session import <ไฟล์> [--name <ชื่อใหม่>]")
    if sub == "export":
        rest = argv[1:]
        if not rest:
            return "ใช้: yousini session export <ชื่อ> [--out <ไฟล์>] [--md]"
        name = rest[0]
        out, fmt = "", "json"
        if "--out" in rest:
            i = rest.index("--out")
            if i + 1 < len(rest):
                out = rest[i + 1]
        if "--md" in rest:
            fmt = "md"
        r = export_session(store, name, out, fmt)
        if r["ok"]:
            return f"export สำเร็จ: {r['path']} ({r['fmt']}, {r['count']} ข้อความ)"
        return r["error"]
    if sub == "import":
        rest = argv[1:]
        if not rest:
            return "ใช้: yousini session import <ไฟล์> [--name <ชื่อใหม่>]"
        path = rest[0]
        new_name = ""
        if "--name" in rest:
            i = rest.index("--name")
            if i + 1 < len(rest):
                new_name = rest[i + 1]
        r = import_session(store, path, new_name)
        if r["ok"]:
            return f"import สำเร็จ: '{r['name']}' ({r['count']} ข้อความ) — ดูด้วย /load {r['name']}"
        return r["error"]
    return f"ไม่รู้จักคำสั่ง session '{sub}'"
