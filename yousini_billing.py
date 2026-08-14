#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tier / License — ระบบสิทธิ์ Pro/Team (ระยะแรก: local format + optional cloud check)

- tier เก็บใน config.json (tier / license_key)
- ตรวจรหัส: รูปแบบ YSN-XXXX-XXXX-XXXX (local) + เช็ค cloud ผ่าน YOUSINI_LICENSE_URL (fail-open ถ้า cloud ล่ม)
- สิทธิ์ที่ขายเป็น "ต้องมี server ถึงทำได้" (cloud sync, priority pool, team share)
  ไม่ใช่การปิดกั้นฟีเจอร์ local — คง spirit open-source ไว้
"""
import json
import os
import re
import urllib.request
from pathlib import Path

KEY_RE = re.compile(r"^YSN-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")

TIERS = {
    "free": {
        "label": "Free", "price": 0,
        "entitlements": {"sponsor_line": True, "cloud_sync": False,
                         "priority_pool": False, "team_share": False,
                         "cloud_symbol_cache": False, "audit_log": False},
    },
    "pro": {
        "label": "Pro", "price": 5,
        "entitlements": {"sponsor_line": False, "cloud_sync": True,
                         "priority_pool": True, "team_share": False,
                         "cloud_symbol_cache": True, "audit_log": False},
    },
    "team": {
        "label": "Team", "price": 15,
        "entitlements": {"sponsor_line": False, "cloud_sync": True,
                         "priority_pool": True, "team_share": True,
                         "cloud_symbol_cache": True, "audit_log": True},
    },
}


def _license_url() -> str:
    return os.getenv("YOUSINI_LICENSE_URL", "").strip()


def _validate_key_format(key: str) -> bool:
    return bool(key and KEY_RE.match(key.strip().upper()))


def validate_key(key: str) -> bool:
    """ตรวจ license: format local + cloud (ถ้าตั้ง YOUSINI_LICENSE_URL) — fail-open ถ้า cloud ล่ม"""
    key = (key or "").strip().upper()
    if not _validate_key_format(key):
        return False
    url = _license_url()
    if not url:
        return True
    try:
        req = urllib.request.Request(
            url, data=json.dumps({"key": key}).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "yousini/3.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return bool(json.loads(r.read().decode("utf-8", "replace")).get("valid"))
    except Exception:
        return True  # fail-open: ไม่ปิดกั้นผู้ใช้เพราะ network ล่ม


def activate(cfg: dict, key: str) -> tuple[bool, str]:
    """เปิดสิทธิ์จาก license key — คืน (ok, message); ต้อง save_config เองที่ผู้เรียก"""
    key = (key or "").strip().upper()
    if not validate_key(key):
        return False, ("รหัสสิทธิ์ไม่ถูกต้อง (รูปแบบ: YSN-XXXX-XXXX-XXXX) "
                       "หรือ cloud ปฏิเสธ — ติดต่อ sponsor@yousini.dev")
    tier = "team" if "TEAM" in key else "pro"
    cfg["tier"] = tier
    cfg["license_key"] = key
    return True, f"เปิดใช้งานสิทธิ์ {TIERS[tier]['label'].upper()} แล้ว (key ...{key[-4:]})"


def deactivate(cfg: dict) -> str:
    cfg["tier"] = "free"
    cfg.pop("license_key", None)
    return "ยกเลิกสิทธิ์แล้ว — กลับสู่ Free"


def _mask(key: str) -> str:
    key = key or ""
    return (key[:4] + "…" + key[-4:]) if len(key) >= 8 else (key or "-")


def tier_info(cfg: dict) -> dict:
    tier = cfg.get("tier", "free")
    t = TIERS.get(tier, TIERS["free"])
    return {
        "tier": tier,
        "label": t["label"],
        "price": t["price"],
        "license_key": _mask(cfg.get("license_key", "")),
        "entitlements": t["entitlements"],
    }


def entitlement(cfg: dict, name: str) -> bool:
    t = TIERS.get(cfg.get("tier", "free"), TIERS["free"])
    return bool(t["entitlements"].get(name, False))


if __name__ == "__main__":
    for k in ("YSN-ABCD-1234-EFGH", "bad", "YSN-TEAM-AAAA-BBBB"):
        print(k, "->", validate_key(k))