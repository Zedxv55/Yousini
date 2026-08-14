#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yousini Marketplace — ระบบ registry สำหรับ skills / tool plugins

- ติดตั้ง package (skills .md + manifest) จาก catalog ระยะไกล / git repo / zip / โฟลเดอร์
- catalog JSON (YOUSINI_REGISTRY / config.registry_url) — fail-open + cache 30 นาที
- package manifest: manifest.json หรือ marketplace.yaml (ย่อยง่าย ๆ ไม่พึ่ง pyyaml)
- manifest รองรับโครงสร้างราคา (price/currency) สำหรับการขายในอนาคต (commission 20-30%)
- tool plugins: manifest ประกาศ mcp_servers → ติดตั้งแล้วลงทะเบียนเป็น MCP client tool ทันที
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

DEFAULT_REGISTRY = "https://raw.githubusercontent.com/Zedxv55/yousini-marketplace/main/registry.json"
CACHE_TTL = 30 * 60          # วินาที — อายุแคช catalog
SUPPORTED_MANIFEST = ("manifest.json", "marketplace.yaml")


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


MP_DIR = Path(os.getenv("YOUSINI_MARKETPLACE_DIR", str(profile_root() / "marketplace")))
SKILLS_DIR = Path(os.getenv("YOUSINI_GLOBAL_SKILLS", str(profile_root() / "skills")))
INSTALLED_FILE = MP_DIR / "installed.json"
CATALOG_FILE = MP_DIR / "catalog.json"
SRC_DIR = MP_DIR / "src"

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------
def _parse_yaml_simple(text: str) -> dict:
    """แยก YAML แบบง่าย (indentation-based) — mapping + sequence ของ scalar/dict
    ไม่พึ่ง pyyaml — รองรับ manifest ของ marketplace"""
    lines = [(len(l) - len(l.lstrip(" ")), l.strip())
             for l in text.splitlines()
             if l.strip() and not l.lstrip().startswith("#")]
    pos = 0
    n = len(lines)

    def parse_value(indent):
        nonlocal pos
        if pos >= n:
            return None
        ind, content = lines[pos]
        if ind != indent:
            return None
        if content.startswith("- "):
            seq = []
            while pos < n and lines[pos][0] == indent and lines[pos][1].startswith("- "):
                item = lines[pos][1][2:].strip()
                pos += 1
                if ":" in item:
                    k, _, v = item.partition(":")
                    d = {}
                    d[k.strip()] = _scalar(v.strip()) if v.strip() else None
                    while pos < n and lines[pos][0] > indent:
                        d.update(parse_map(lines[pos][0]))
                    seq.append(d)
                else:
                    seq.append(_scalar(item))
            return seq
        return parse_map(indent)

    def parse_map(indent):
        nonlocal pos
        d = {}
        while pos < n and lines[pos][0] == indent and not lines[pos][1].startswith("- "):
            line = lines[pos][1]
            if ":" not in line:
                pos += 1
                continue
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            pos += 1
            if not v:
                if pos < n and lines[pos][0] > indent:
                    d[k] = parse_value(lines[pos][0])
                else:
                    d[k] = None
            else:
                d[k] = _scalar(v)
        return d

    return parse_map(0)


def _scalar(v: str):
    v = v.strip().strip('"').strip("'")
    if v.lower() in ("true", "yes"):
        return True
    if v.lower() in ("false", "no"):
        return False
    if re.fullmatch(r"-?\d+(\.\d+)?", v):
        try:
            return int(v)
        except ValueError:
            return float(v)
    return v


def parse_manifest(root: Path) -> dict:
    """อ่าน manifest.json หรือ marketplace.yaml จากโฟลเดอร์ package → dict (ว่างถ้าไม่พบ)"""
    for name in SUPPORTED_MANIFEST:
        p = root / name
        if p.is_file():
            try:
                if name.endswith(".json"):
                    m = _load_json_file(p)
                    return m if isinstance(m, dict) else {}
                return _parse_yaml_simple(p.read_text(encoding="utf-8-sig"))
            except Exception:
                return {}
    return {}


def _manifest_kv(m: dict, key: str, default=""):
    v = m.get(key, default)
    return v if v is not None else default


def find_package_root(dirpath) -> Path:
    """หาโฟลเดอร์ที่มี manifest อยู่ (walk ลงไป 2 ระดับ)"""
    dirpath = Path(dirpath)
    for cand in (dirpath, *list(dirpath.glob("*"))):
        if cand.is_dir() and any((cand / n).is_file() for n in SUPPORTED_MANIFEST):
            return cand
    return dirpath


# ---------------------------------------------------------------------------
# catalog (remote registry)
# ---------------------------------------------------------------------------
def registry_url(cfg: dict = None) -> str:
    cfg = cfg or {}
    return (cfg.get("registry_url") or os.getenv("YOUSINI_REGISTRY", "") or DEFAULT_REGISTRY).strip()


def marketplace_enabled(cfg: dict = None) -> bool:
    cfg = cfg or {}
    return cfg.get("marketplace_enabled", True) is not False


def _fetch(url: str, timeout: float = 8.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Yousini/3.2"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _load_json_bytes(data: bytes):
    """json.loads ที่ทน BOM + ภาษาไทย"""
    text = data.decode("utf-8-sig", errors="replace")
    return json.loads(text)


def _load_json_file(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))


def fetch_catalog(cfg: dict = None, force: bool = False) -> list:
    """ดึง catalog จาก registry — fail-open: พัง/ออฟไลน์ → ใช้แคช (ถ้ามี) ไม่งั้น []
    เก็บแคชที่ MP_DIR/catalog.json (หมดอายุตาม CACHE_TTL)"""
    cfg = cfg or {}
    url = registry_url(cfg)
    try:
        if not force and CATALOG_FILE.is_file():
            age = time.time() - CATALOG_FILE.stat().st_mtime
            if age < CACHE_TTL:
                data = _load_json_file(CATALOG_FILE)
                return _catalog_pkgs(data)
        raw = _fetch(url)
        data = _load_json_bytes(raw)
        CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CATALOG_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return _catalog_pkgs(data)
    except Exception:
        if CATALOG_FILE.is_file():
            try:
                return _catalog_pkgs(_load_json_file(CATALOG_FILE))
            except Exception:
                pass
        return []


def _catalog_pkgs(data) -> list:
    if isinstance(data, list):
        return [p for p in data if isinstance(p, dict)]
    pkgs = data.get("packages", []) if isinstance(data, dict) else []
    return [p for p in pkgs if isinstance(p, dict)]


def search_catalog(query: str = "", cfg: dict = None) -> list:
    """ค้น package ใน catalog ตาม id/name/description/tags"""
    q = (query or "").strip().lower()
    pkgs = fetch_catalog(cfg)
    if not q:
        return pkgs
    out = []
    for p in pkgs:
        blob = " ".join([
            str(p.get(k, "")) for k in ("id", "name", "description", "author", "tags")
        ]).lower()
        if q in blob:
            out.append(p)
    return out


def catalog_package(pkg_id: str, cfg: dict = None):
    for p in fetch_catalog(cfg):
        if p.get("id") == pkg_id:
            return p
    return None


# ---------------------------------------------------------------------------
# installed registry
# ---------------------------------------------------------------------------
def load_installed() -> dict:
    try:
        return _load_json_file(INSTALLED_FILE)
    except Exception:
        return {}


def _save_installed(data: dict):
    INSTALLED_FILE.parent.mkdir(parents=True, exist_ok=True)
    INSTALLED_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------
# fetching a package source (id / git url / zip url / local path)
# ---------------------------------------------------------------------------
def _download_to_tmp(source: str, cfg: dict = None):
    """ดึง package มาไว้ใน temp dir → คืน Path ของโฟลเดอร์ package root"""
    cfg = cfg or {}
    if os.path.isdir(source):
        return Path(source)
    tmp = Path(tempfile.mkdtemp(prefix="yousini_market_"))
    if "github.com" in source and source.endswith(".git"):
        if shutil.which("git"):
            subprocess.run(["git", "clone", "--depth", "1", source, str(tmp / "repo")],
                           check=True, capture_output=True)
            return find_package_root(tmp / "repo")
        api = source.replace("github.com", "api.github.com/repos").removesuffix(".git")
        return _zipball(api, tmp)
    if source.startswith(("http://", "https://")):
        if source.rstrip("/").endswith(".zip") or "/zipball/" in source:
            return _zipball(source, tmp)
        # URL เปล่า ๆ → คิดว่าเป็น git repo
        if shutil.which("git"):
            subprocess.run(["git", "clone", "--depth", "1", source, str(tmp / "repo")],
                           check=True, capture_output=True)
            return find_package_root(tmp / "repo")
    raise ValueError(f"ไม่รู้จัก source: {source}")


def _zipball(url, tmp: Path) -> Path:
    zpath = tmp / "pkg.zip"
    urllib.request.urlretrieve(url, zpath)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(tmp / "pkg")
    sub = list((tmp / "pkg").iterdir())
    return find_package_root(sub[0]) if sub else (tmp / "pkg")


# ---------------------------------------------------------------------------
# install / uninstall / update
# ---------------------------------------------------------------------------
def _mcp_register(servers: list, remove: bool = False):
    """ลงทะเบียน/ยกเลิก MCP client servers (tool plugins) — lazy import คุณสini_mcp"""
    if not servers:
        return
    try:
        from yousini_mcp import MCP_FILE
    except Exception:
        return
    try:
        cfg = json.loads(MCP_FILE.read_text(encoding="utf-8")) if MCP_FILE.is_file() else []
    except Exception:
        cfg = []
    names = {s.get("name") for s in servers if isinstance(s, dict)}
    cfg = [s for s in cfg if not (isinstance(s, dict) and s.get("name") in names)]
    if not remove:
        cfg.extend({"name": s.get("name"), "cmd": s.get("cmd")} for s in servers
                   if isinstance(s, dict) and s.get("name") and s.get("cmd"))
    MCP_FILE.parent.mkdir(parents=True, exist_ok=True)
    MCP_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")


def _discover_skills(pkg_root: Path, manifest: dict) -> list:
    """ไฟล์ skill ที่ package นำมา: ระบุใน manifest.skills หรือ auto-detect จาก skills/*.md + *.md ที่มี frontmatter"""
    wanted = manifest.get("skills") or []
    files = []
    if wanted:
        for rel in wanted:
            p = pkg_root / str(rel)
            if p.is_file():
                files.append(p)
    if not files:
        if (pkg_root / "skills").is_dir():
            files.extend(sorted((pkg_root / "skills").glob("*.md")))
        for p in sorted(pkg_root.glob("*.md")):
            if p not in files:
                text = p.read_text(encoding="utf-8", errors="replace")
                if text.lstrip().startswith("---") and re.search(r"(?m)^name\s*:", text[:400]):
                    files.append(p)
    return files


def _copy_skills(files: list, skill_dir: Path, pkg_id: str) -> list:
    skill_dir.mkdir(parents=True, exist_ok=True)
    installed = []
    for f in files:
        dest = skill_dir / f.name
        shutil.copy(f, dest)
        installed.append(str(dest))
    return installed


def install(source: str, project: bool = False, force: bool = False, cfg: dict = None) -> dict:
    """ติดตั้ง package จาก id/URL/path → ลง skills (+ mcp servers) + บันทึก installed.json
    คืน dict สรุป เช่น {"ok": True, "id":..., "skills":[...], "mcp":[...]}"""
    cfg = cfg or {}
    installed = load_installed()
    pkg_meta = catalog_package(source, cfg) if not os.path.isdir(source) else None
    source_url = source
    if pkg_meta:
        source_url = pkg_meta.get("source") or pkg_meta.get("url") or source

    tmp_owner = None
    try:
        if os.path.isdir(source):
            pkg_root = Path(source)
        else:
            tmp_owner = Path(tempfile.mkdtemp(prefix="yousini_market_"))
            pkg_root = _download_to_tmp(source_url, cfg)

        manifest = parse_manifest(pkg_root)
        pkg_id = _manifest_kv(manifest, "id", pkg_root.name)
        if not _ID_RE.match(pkg_id):
            pkg_id = re.sub(r"[^a-z0-9._-]", "-", pkg_id.lower()).strip("-") or "pkg"
        version = _manifest_kv(manifest, "version", "0.0.0")
        name = _manifest_kv(manifest, "name", pkg_id)

        if pkg_id in installed and not force:
            return {"ok": False, "error": f"'{pkg_id}' ติดตั้งอยู่แล้ว (v{installed[pkg_id].get('version')}) — ใช้ force เพื่อติดตั้งซ้ำ"}

        skill_dir = Path.cwd() / "skills" if project else SKILLS_DIR
        skill_files = _discover_skills(pkg_root, manifest)
        skill_dest = _copy_skills(skill_files, skill_dir, pkg_id)

        servers = manifest.get("mcp_servers") or []
        _mcp_register(servers, remove=False)

        # คัดลอก package ทั้งก้อนเก็บไว้สำหรับ update/uninstall
        dest = SRC_DIR / pkg_id
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(pkg_root, dest, ignore=shutil.ignore_patterns(".git"))

        installed[pkg_id] = {
            "id": pkg_id, "name": name, "version": version,
            "author": _manifest_kv(manifest, "author"),
            "license": _manifest_kv(manifest, "license"),
            "price": _manifest_kv(manifest, "price", 0),
            "currency": _manifest_kv(manifest, "currency", "USD"),
            "description": _manifest_kv(manifest, "description"),
            "source": source_url, "project": bool(project),
            "installed_at": time.strftime("%Y-%m-%d %H:%M"),
            "skills": [str(s) for s in skill_dest],
            "mcp_servers": [s.get("name") for s in servers if isinstance(s, dict) and s.get("name")],
        }
        _save_installed(installed)
        return {"ok": True, "id": pkg_id, "name": name, "version": version,
                "skills": [Path(s).name for s in skill_dest],
                "mcp": installed[pkg_id]["mcp_servers"]}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        if tmp_owner:
            shutil.rmtree(tmp_owner, ignore_errors=True)


def uninstall(pkg_id: str) -> dict:
    """ถอนการติดตั้ง: ลบ skills ที่บันทึกไว้ + mcp servers + โฟลเดอร์ src"""
    installed = load_installed()
    rec = installed.get(pkg_id)
    if not rec:
        return {"ok": False, "error": f"ไม่พบ package '{pkg_id}' (ใช้ marketplace installed ดูรายการ)"}
    removed = 0
    for skill_path in rec.get("skills", []):
        try:
            Path(skill_path).unlink(missing_ok=True)
            removed += 1
        except Exception:
            pass
    _mcp_register([{"name": n, "cmd": ""} for n in (rec.get("mcp_servers") or [])],
                  remove=True)
    shutil.rmtree(SRC_DIR / pkg_id, ignore_errors=True)
    installed.pop(pkg_id, None)
    _save_installed(installed)
    return {"ok": True, "id": pkg_id, "removed_skills": removed,
            "mcp_removed": len(rec.get("mcp_servers") or [])}


def update(pkg_id: str, cfg: dict = None) -> dict:
    rec = load_installed().get(pkg_id)
    if not rec:
        return {"ok": False, "error": f"ไม่พบ package '{pkg_id}'"}
    return install(rec.get("source") or pkg_id, project=bool(rec.get("project")),
                   force=True, cfg=cfg)


def update_all(cfg: dict = None) -> list:
    out = []
    for pkg_id in list(load_installed().keys()):
        out.append({"id": pkg_id, **update(pkg_id, cfg)})
    return out


def installed_list() -> list:
    return sorted(load_installed().values(), key=lambda r: r.get("name", ""))


def pkg_info(pkg_id: str, cfg: dict = None) -> dict:
    rec = load_installed().get(pkg_id)
    if rec:
        return {"installed": True, **rec}
    meta = catalog_package(pkg_id, cfg)
    if meta:
        return {"installed": False, **meta}
    return {"installed": False, "id": pkg_id, "name": pkg_id, "version": "?"}


# ---------------------------------------------------------------------------
# formatters (ใช้กับ CLI + REPL + web)
# ---------------------------------------------------------------------------
def _price(p: dict) -> str:
    try:
        price = float(p.get("price", 0) or 0)
    except (TypeError, ValueError):
        price = 0
    if price <= 0:
        return "ฟรี"
    return f"${price:g} {p.get('currency', 'USD')}"


def format_catalog(pkgs: list, max_rows: int = 40) -> str:
    if not pkgs:
        return "(catalog ว่าง — ตรวจ registry_url / ลองออนไลน์ใหม่)"
    rows = []
    for p in pkgs[:max_rows]:
        tags = " ".join(p.get("tags") or [])
        rows.append(f"{p.get('id','?'):<28} {p.get('version','?'):<8} {_price(p):<8} "
                    f"{str(p.get('name',''))[:28]}")
        rows.append(f"{'':28} {str(p.get('description',''))[:72]}")
        if tags:
            rows.append(f"{'':28} tags: {tags}")
    if len(pkgs) > max_rows:
        rows.append(f"... อีก {len(pkgs) - max_rows} รายการ")
    return "\n".join(rows)


def format_installed() -> str:
    items = installed_list()
    if not items:
        return "(ยังไม่มี package — ใช้ marketplace search/install ก่อน)"
    rows = []
    for r in items:
        skills = len(r.get("skills", []))
        mcp = len(r.get("mcp_servers", []))
        extra = []
        if skills:
            extra.append(f"{skills} skills")
        if mcp:
            extra.append(f"{mcp} tools(MCP)")
        rows.append(f"{r.get('id','?'):<28} v{r.get('version','?'):<6} {_price(r):<8} "
                    f"{', '.join(extra) or '—'}")
        rows.append(f"{'':28} {r.get('name','')[:64]}")
    return "\n".join(rows)


def format_info(pkg: dict) -> str:
    if not pkg:
        return "(ไม่พบ package)"
    lines = [f"Package: {pkg.get('id')} — {pkg.get('name','')}",
             f"เวอร์ชัน: {pkg.get('version','?')}    ราคา: {_price(pkg)}",
             f"ผู้เขียน: {pkg.get('author','-')}    ไลเซนส์: {pkg.get('license','-')}",
             f"คำอธิบาย: {pkg.get('description','-')}"]
    if pkg.get("skills"):
        lines.append("Skills:")
        for s in pkg["skills"]:
            lines.append(f"  - {Path(s).name}")
    if pkg.get("mcp_servers"):
        lines.append("Tool plugins (MCP servers): " + ", ".join(pkg["mcp_servers"]))
    if pkg.get("installed"):
        lines.append(f"ติดตั้งเมื่อ: {pkg.get('installed_at','?')}  จาก {pkg.get('source','-')}")
    return "\n".join(lines)