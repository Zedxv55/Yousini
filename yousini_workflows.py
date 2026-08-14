#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Workflow templates (v3.8) — เทมเพลตงานอัตโนมัติ (ชุดขั้นตอนรันซ้ำ)

ขั้นตอน (step) มี 2 แบบ:
    {"tool": "<ชื่อ tool>", "args": {...}}   → เรียก exec_tool(name, args)
    {"prompt": "..."}                       → เรียก chat_turn(text)

เทมเพลต:
    - built-in: release, weekly_report, code_review (ในโค้ด)
    - ผู้ใช้:   ~/.yousini/workflows/<ชื่อ>.json (struct: {name, description, steps})
CLI: yousini workflow list | show <ชื่อ> | run <ชื่อ> [--tool <k>=<v>...] | save <ชื่อ> <json>
"""
import json
import os
from pathlib import Path

BUILTIN = {
    "release": {
        "description": "ปล่อยเวอร์ชัน: ตรวจโปรเจกต์ → รัน test → bump เวอร์ชัน → PR",
        "steps": [
            {"tool": "dev_check", "args": {"scope": "all"}},
            {"prompt": "รัน pytest ให้ครบ ถ้ามี test ล้มเหลวให้แก้จนผ่าน จากนั้นตรวจว่า "
                       "pyproject.toml กับ APP_VERSION ตรงกัน"},
            {"prompt": "bump เวอร์ชัน (patch) ใน pyproject.toml และ APP_VERSION ให้ตรงกัน "
                       "แล้ว commit พร้อมข้อความ feat(vX.Y.Z) ..."},
            {"prompt": "สร้าง PR: สรุปการเปลี่ยนแปลงในเวอร์ชันนี้ ระบุรายการ feature/fix เป็น bullet"},
        ],
    },
    "weekly_report": {
        "description": "สร้างสรุปการใช้งานประจำสัปดาห์ (tokens/tools/turns)",
        "steps": [
            {"tool": "dev_check", "args": {"scope": "status"}},
            {"prompt": "ดูสถิติการใช้งาน (คำสั่ง /usage) แล้วเขียนสรุปการใช้งานสัปดาห์นี้ "
                       "ว่ามี turn/token/tool กี่ครั้ง มีเครื่องมือไหนใช้บ่อยสุด แนะนำการปรับปรุง 1-2 ข้อ"},
        ],
    },
    "code_review": {
        "description": "รีวิวโค้ดที่ยังไม่ commit: ดู diff → วิเคราะห์ → สรุปข้อเสนอ",
        "steps": [
            {"tool": "git", "args": {"action": "diff"}},
            {"prompt": "รีวิวโค้ดจาก diff ด้านบน: ชี้จุดที่เป็นบั๊ก/ความเสี่ยง/สไตล์ "
                       "พร้อมบรรทัด และแนะนำการแก้ไข กระชับ"},
        ],
    },
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


def workflows_dir() -> Path:
    env = os.getenv("YOUSINI_WORKFLOWS_DIR", "").strip()
    if env:
        return Path(env)
    return _profile_root() / "workflows"


def _user_templates() -> dict:
    d = workflows_dir()
    if not d.is_dir():
        return {}
    out = {}
    for p in sorted(d.glob("*.json")):
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(j, dict) and j.get("name"):
                out[j["name"]] = j
        except Exception:
            continue
    return out


def list_templates() -> list:
    out = []
    for name, t in BUILTIN.items():
        out.append({"name": name, "source": "built-in", "description": t["description"],
                    "steps": len(t["steps"])})
    for name, t in _user_templates().items():
        out.append({"name": name, "source": "user", "description": t.get("description", ""),
                    "steps": len(t.get("steps", []))})
    return sorted(out, key=lambda x: x["name"])


def load_template(name: str) -> dict:
    if name in BUILTIN:
        return {**BUILTIN[name], "name": name, "source": "built-in"}
    user = _user_templates().get(name)
    if user:
        user["source"] = "user"
        return user
    return {}


def save_template(name: str, steps_json: str) -> str:
    try:
        steps = json.loads(steps_json)
    except Exception as e:
        return f"Error: steps ไม่ใช่ JSON: {e}"
    if not isinstance(steps, list) or not steps:
        return "Error: steps ต้องเป็น list ที่ไม่ว่างของ {{tool, args}} หรือ {{prompt}}"
    for s in steps:
        if "tool" not in s and "prompt" not in s:
            return "Error: แต่ละ step ต้องมี tool หรือ prompt"
    t = {"name": name, "description": "", "steps": steps}
    d = workflows_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"บันทึกเทมเพลต '{name}' แล้ว ({len(steps)} steps) → {d / (name + '.json')}"


def run_workflow(name: str, exec_tool, chat_turn=None, cwd: str = "",
                 overrides: dict = None) -> str:
    """รันเทมเพลตตามชื่อ — exec_tool(name, args) ต้องเป็น callable, chat_turn(text) ไม่บังคับ"""
    t = load_template(name)
    if not t:
        return f"ไม่พบเทมเพลต '{name}' — มี: " + ", ".join(x["name"] for x in list_templates())
    log = [f"รันเทมเพลต '{name}' ({len(t.get('steps', []))} steps)"]
    for i, step in enumerate(t.get("steps", []), 1):
        if "tool" in step:
            tname = step["tool"]
            args = dict(step.get("args", {}))
            if overrides and tname in overrides:
                args.update(overrides[tname])
            log.append(f"\n[{i}/{len(t['steps'])}] tool: {tname} args={json.dumps(args, ensure_ascii=False)}")
            try:
                res = exec_tool(tname, args) if exec_tool else "(ไม่มี exec_tool)"
                log.append(str(res)[:600])
            except Exception as e:
                log.append(f"ERROR: {e}")
        elif "prompt" in step:
            text = step["prompt"]
            if overrides and "prompt" in overrides:
                text = overrides["prompt"]
            log.append(f"\n[{i}/{len(t['steps'])}] prompt: {text[:120]}")
            if chat_turn:
                try:
                    chat_turn(text)
                    log.append("(เสร็จสิ้น)")
                except Exception as e:
                    log.append(f"ERROR: {e}")
            else:
                log.append("(ไม่มี chat_turn — ข้าม)")
    return "\n".join(log)


def workflow_main(argv, exec_tool, chat_turn=None) -> str:
    sub = argv[0].lower() if argv else "list"
    if sub in ("list", ""):
        ts = list_templates()
        if not ts:
            return "(ไม่มีเทมเพลต)"
        return "\n".join(f"  • {x['name']:<14} [{x['source']}] {x['description']} ({x['steps']} steps)"
                         for x in ts)
    if sub == "show":
        name = argv[1] if len(argv) > 1 else ""
        t = load_template(name)
        if not t:
            return f"ไม่พบเทมเพลต '{name}'"
        return (f"เทมเพลต '{name}' [{t['source']}]: {t.get('description', '')}\n" +
                "\n".join(f"  {i + 1}. {json.dumps(s, ensure_ascii=False)}"
                          for i, s in enumerate(t.get("steps", []))))
    if sub == "save":
        if len(argv) < 3:
            return "ใช้: workflow save <ชื่อ> '<json steps>'"
        return save_template(argv[1], argv[2])
    if sub == "run":
        name = argv[1] if len(argv) > 1 else ""
        if not name:
            return "ใช้: workflow run <ชื่อ> [--<tool> '<json args>'] [--prompt '<ข้อความ>']"
        overrides = {}
        rest = argv[2:]
        i = 0
        while i < len(rest):
            if rest[i].startswith("--"):
                k = rest[i][2:]
                v = rest[i + 1] if i + 1 < len(rest) else "{}"
                try:
                    parsed = json.loads(v)
                    overrides[k] = parsed if isinstance(parsed, (dict, str)) else parsed
                except Exception:
                    overrides[k] = v
                i += 2
            else:
                i += 1
        return run_workflow(name, exec_tool, chat_turn=chat_turn, overrides=overrides or None)
    return "ใช้: workflow list | show <ชื่อ> | run <ชื่อ> [--<tool> '<json>'] | save <ชื่อ> '<steps>'"