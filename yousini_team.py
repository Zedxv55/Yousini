#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yousini Team — workspace ร่วม + multi-user

- team.json (ใน data dir ของโพรไฟล์) = workspace โลคอล: id, name, registry,
  users [{name, token, role}], rules, url (remote config)
- YOUSINI_TEAM_URL หรือ team.json.url → ดึง config ส่วนกลางของทีมมา merge
  (remote ชนะเรื่อง registry/rules/name) — fail-open + cache 30 นาที
- users/role: ใช้กับ web server แบบ multi-user (admin = จัดการ marketplace,
  member = แชท/LSP ได้)
"""
import json
import os
import time
import urllib.request
from pathlib import Path

CACHE_TTL = 30 * 60

DEFAULT_ROLES = ("admin", "member", "viewer")


def profile_root() -> Path:
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


TEAM_FILE = Path(os.getenv("YOUSINI_TEAM_FILE", str(profile_root() / "team.json")))
CACHE_FILE = Path(os.getenv("YOUSINI_TEAM_CACHE", str(profile_root() / "team_cache.json")))


# ---------------------------------------------------------------------------
# local team.json
# ---------------------------------------------------------------------------
def load_local() -> dict:
    try:
        return json.loads(TEAM_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def save_local(data: dict) -> None:
    TEAM_FILE.parent.mkdir(parents=True, exist_ok=True)
    TEAM_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# remote config (fail-open + cache)
# ---------------------------------------------------------------------------
def _fetch(url: str, timeout: float = 8.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Yousini/3.3"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_remote(url: str, force: bool = False) -> dict:
    """ดึง team config ส่วนกลาง → dict (พัง/ออฟไลน์ → ใช้แคช ไม่งั้น {})"""
    if not url:
        return {}
    try:
        if not force and CACHE_FILE.is_file():
            age = time.time() - CACHE_FILE.stat().st_mtime
            if age < CACHE_TTL:
                return json.loads(CACHE_FILE.read_text(encoding="utf-8-sig"))
        data = json.loads(_fetch(url).decode("utf-8-sig"))
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data if isinstance(data, dict) else {}
    except Exception:
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8-sig"))
        except Exception:
            return {}


def team_url(local: dict = None) -> str:
    local = local or load_local()
    return (local.get("url") or os.getenv("YOUSINI_TEAM_URL", "")).strip()


def effective(cfg: dict = None) -> dict:
    """team หลัง merge: local + remote (remote ชนะ: name/registry/rules/workspace)"""
    local = load_local()
    if not local:
        return {}
    out = dict(local)
    url = team_url(local)
    if url:
        remote = fetch_remote(url)
        for k in ("workspace", "name", "registry", "rules", "updated_at"):
            if remote.get(k) is not None:
                out[k] = remote[k]
        # users: local users ชนะ (ผู้ดูแลทีมตั้งค่าคนในเครื่อง), แล้วเอา remote มาผนวก
        merged = {}
        for u in remote.get("users", []):
            if isinstance(u, dict) and u.get("name"):
                merged[u["name"]] = u
        for u in out.get("users", []):
            if isinstance(u, dict) and u.get("name"):
                merged[u["name"]] = u
        if merged:
            out["users"] = list(merged.values())
    return out


# ---------------------------------------------------------------------------
# registry / rules
# ---------------------------------------------------------------------------
def resolve_registry(cfg: dict = None) -> str:
    """registry ที่ใช้จริง: team.registry > config.registry_url > env > default"""
    cfg = cfg or {}
    team = effective(cfg)
    reg = (team.get("registry") or cfg.get("registry_url")
           or os.getenv("YOUSINI_REGISTRY", ""))
    if not reg:
        try:
            from yousini_marketplace import DEFAULT_REGISTRY
            reg = DEFAULT_REGISTRY
        except Exception:
            reg = ""
    return reg


def apply_rules(cfg: dict) -> dict:
    """นำ rules ของทีมไปทับ config (auto_run / safe / shell_timeout ...)"""
    team = effective(cfg)
    rules = team.get("rules") or {}
    if not isinstance(rules, dict):
        return cfg
    out = dict(cfg)
    for k, v in rules.items():
        if k in ("auto_run", "safe", "allow_shell", "allow_write"):
            out[k] = bool(v)
        elif k in ("shell_timeout",):
            out[k] = int(v) if str(v).isdigit() else v
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# users / roles
# ---------------------------------------------------------------------------
def users(cfg: dict = None) -> list:
    """รายชื่อผู้ใช้ {name, token, role} จาก team.json + config.json (เรียง name)"""
    cfg = cfg or {}
    team = effective(cfg)
    merged = {}
    for u in cfg.get("users", []):
        if isinstance(u, dict) and u.get("name"):
            merged[u["name"]] = u
    for u in team.get("users", []):
        if isinstance(u, dict) and u.get("name"):
            merged[u["name"]] = u
    out = []
    for name, u in merged.items():
        role = u.get("role") or "member"
        if role not in DEFAULT_ROLES:
            role = "member"
        out.append({"name": name, "token": u.get("token", ""), "role": role})
    return sorted(out, key=lambda x: x["name"])


def role_for_token(token: str, cfg: dict = None, master_token: str = "") -> tuple:
    """คืน (name, role) สำหรับ token — master_token (serve --token) = owner/admin
    ไม่มีผู้ใช้/ไม่มี master ตั้งค่า → (local, admin)"""
    token = token or ""
    cfg = cfg or {}
    if master_token and token == master_token:
        return ("owner", "admin")
    for u in users(cfg):
        if u["token"] and token and u["token"] == token:
            return (u["name"], u["role"])
    if not master_token and not users(cfg):
        return ("local", "admin")
    return None


def is_admin(role: str) -> bool:
    return role == "admin"


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------
def init(name: str, ws_id: str = "") -> dict:
    """สร้าง workspace ใหม่ (โลคอล)"""
    import re
    if not name.strip():
        return {"ok": False, "error": "ต้องระบุชื่อ workspace"}
    wid = (ws_id or re.sub(r"[^a-z0-9._-]", "-", name.lower()).strip("-") or "team")
    data = {
        "workspace": wid,
        "name": name.strip(),
        "registry": "",
        "users": [],
        "rules": {},
        "created_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    save_local(data)
    return {"ok": True, "workspace": wid, "name": name.strip()}


def join(url: str) -> dict:
    """เข้าร่วมทีมจาก URL ของ team config"""
    url = (url or "").strip()
    if not url:
        return {"ok": False, "error": "ต้องระบุ URL ของ team config"}
    remote = fetch_remote(url, force=True)
    if not remote:
        return {"ok": False, "error": "ดึง team config ไม่สำเร็จ (ออฟไลน์/URL ผิด)"}
    local = load_local()
    local.update({
        "workspace": remote.get("workspace") or remote.get("name") or "team",
        "name": remote.get("name") or "Team",
        "url": url,
        "registry": remote.get("registry") or local.get("registry", ""),
        "users": local.get("users", []),
        "joined_at": time.strftime("%Y-%m-%d %H:%M"),
    })
    save_local(local)
    return {"ok": True, "workspace": local["workspace"], "name": local["name"]}


def leave() -> dict:
    data = load_local()
    data.pop("url", None)
    data.pop("registry", None)
    data.pop("users", None)
    data.pop("joined_at", None)
    save_local(data)
    return {"ok": True}


def set_registry(url: str) -> dict:
    data = load_local()
    data["registry"] = (url or "").strip()
    save_local(data)
    return {"ok": True, "registry": data["registry"]}


def team_status(cfg: dict = None) -> dict:
    """สถานะรวมสำหรับ /team + /info"""
    cfg = cfg or {}
    local = load_local()
    if not local:
        return {"active": False}
    eff = effective(cfg)
    return {
        "active": True,
        "workspace": eff.get("workspace", ""),
        "name": eff.get("name", ""),
        "registry": eff.get("registry", ""),
        "remote": bool(team_url(local)),
        "users": users(cfg),
        "rules": eff.get("rules") or {},
        "created_at": local.get("created_at", ""),
        "joined_at": local.get("joined_at", ""),
    }


# ---------------------------------------------------------------------------
# format
# ---------------------------------------------------------------------------
def format_status(st: dict) -> str:
    if not st or not st.get("active"):
        return "(ยังไม่ได้เข้าร่วม workspace — ใช้: yousini team init <ชื่อ> หรือ team join <url>)"
    us = st.get("users", [])
    members = ", ".join(f"{u['name']}({u['role']})" for u in us) if us else "ยังไม่มี user"
    lines = [f"Workspace: {st.get('workspace','')} — {st.get('name','')}",
             f"Registry: {st.get('registry') or '(ใช้ค่าเริ่มต้น)'}",
             f"Remote config: {'เปิด' if st.get('remote') else 'ปิด (เฉพาะ local)'}",
             f"สมาชิก ({len(us)}): {members}"]
    rules = st.get("rules") or {}
    if rules:
        lines.append("Rules: " + ", ".join(f"{k}={v}" for k, v in rules.items()))
    if st.get("joined_at"):
        lines.append(f"เข้าร่วมเมื่อ: {st.get('joined_at')}")
    elif st.get("created_at"):
        lines.append(f"สร้างเมื่อ: {st.get('created_at')}")
    return "\n".join(lines)