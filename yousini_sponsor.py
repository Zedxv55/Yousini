#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sponsor slot แบบ non-intrusive — แสดงเฉพาะตอนว่าง ไม่ขวางงาน

กฎเหล็ก (ตามหลัก trust-first):
- ปิดได้เสมอด้วย /ads off หรือ config ads_disabled=true
- Tier pro/team = ไม่แสดงโฆษณา
- ถ้าไม่มี sponsor ตั้งค่า → ใช้ placeholder บรรทัดเดียวหมุนเวียนรายวัน
- ดึง sponsor ระยะไกลผ่าน YOUSINI_SPONSOR_URL (fail-silent, cache 24h, offline fallback)
"""
import json
import os
import random
import urllib.request
from datetime import datetime
from pathlib import Path

CACHE_TTL = 24 * 60 * 60

_DEFAULT_POOL = [
    "Yousini เป็น open-source (MIT) — สนับสนุนได้ที่ github.com/Zedxv55/Yousini",
    "โฆษณาปิดได้เสมอด้วย /ads off · เปิดรับ sponsor dev-tool: sponsor@yousini.dev",
]


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


def _cache_file() -> Path:
    return _profile_root() / "sponsor_cache.json"


def _load_cache() -> dict:
    try:
        d = json.loads(_cache_file().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_cache(d: dict) -> None:
    try:
        _cache_file().parent.mkdir(parents=True, exist_ok=True)
        _cache_file().write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _fetch_remote(url: str) -> str | None:
    """ดึง sponsor จาก URL — fail-silent เสมอ (network ล่ม = ไม่พัง)"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "yousini/3.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            txt = r.read().decode("utf-8", errors="replace").strip()
        if not txt or len(txt) > 200:
            return None
        return txt.splitlines()[0].strip()
    except Exception:
        return None


def _line_enabled(cfg: dict) -> bool:
    if cfg.get("ads_disabled"):
        return False
    if (cfg.get("tier") or "free") == "pro":
        return False
    return True


def sponsor_line(cfg: dict) -> str | None:
    """คืน sponsor line ที่จะแสดง (None = ไม่แสดง) — ยิงตามสิทธิ์/การตั้งค่า"""
    if not _line_enabled(cfg):
        return None
    url = os.getenv("YOUSINI_SPONSOR_URL", "").strip()
    cache = _load_cache()
    if url:
        if (cache.get("source") == "remote" and cache.get("line")
                and cache.get("fetched")):
            try:
                age = (datetime.now() - datetime.fromisoformat(cache["fetched"])).total_seconds()
                if age < CACHE_TTL:
                    return cache["line"]
            except Exception:
                pass
        line = _fetch_remote(url)
        if line:
            _save_cache({"source": "remote", "line": line,
                         "fetched": datetime.now().isoformat()})
            return line
        if cache.get("line"):
            return cache["line"]
        return None
    # ไม่มี sponsor ระยะไกล → placeholder หมุนเวียนรายวัน
    rng = random.Random(datetime.now().strftime("%Y-%m-%d"))
    return rng.choice(_DEFAULT_POOL)


def sponsor_status(cfg: dict) -> str:
    enabled = _line_enabled(cfg)
    url = os.getenv("YOUSINI_SPONSOR_URL", "").strip()
    cache = _load_cache()
    lines = [
        f"สถานะ: {'เปิด' if enabled else 'ปิด'}",
        f"ปิดด้วย: {'/ads off หรือ tier pro' if enabled else '- (ปิดอยู่แล้ว)'}",
        f"source: {url or 'local placeholder pool'}",
    ]
    if cache.get("line"):
        lines.append(f"line ที่แคชไว้: {cache['line']}")
    return "\n".join(lines)


if __name__ == "__main__":
    line = sponsor_line({})
    print(line or "(no sponsor line)")