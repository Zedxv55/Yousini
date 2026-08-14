"""ทดสอบ marketplace (yousini_marketplace) — manifest/install/catalog/uninstall"""
import json
import os
import sys
import tempfile

BASE = tempfile.mkdtemp(prefix="ys_market_")
os.environ["YOUSINI_MARKETPLACE_DIR"] = os.path.join(BASE, "mp")
os.environ["YOUSINI_GLOBAL_SKILLS"] = os.path.join(BASE, "skills")
os.environ["YOUSINI_MCP_FILE"] = os.path.join(BASE, "mcp.json")
os.environ["YOUSINI_REGISTRY"] = "file:///" + os.path.join(BASE, "registry.json").replace("\\", "/")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import yousini_marketplace as M  # noqa: E402
from yousini_mcp import load_mcp_config  # noqa: E402


@pytest.fixture(autouse=True)
def patch_mcp_file(monkeypatch):
    """_mcp_register lazy import MCP_FILE จาก yousini_mcp — patch ที่ต้นทางไป tmp
    กันเขียนทับ mcp.json จริง"""
    import yousini_mcp as mcp
    from pathlib import Path
    monkeypatch.setattr(mcp, "MCP_FILE", Path(os.environ["YOUSINI_MCP_FILE"]))


@pytest.fixture(scope="module")
def web_pkg():
    pkg = os.path.join(BASE, "web-tools")
    os.makedirs(os.path.join(pkg, "skills"))
    with open(os.path.join(pkg, "manifest.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps({
            "id": "web-tools", "name": "Web Tools", "version": "1.2.0",
            "description": "เครื่องมือเว็บ", "author": "Zedxv55", "license": "MIT",
            "price": 0, "tags": ["web", "seo"],
            "mcp_servers": [{"name": "wiki", "cmd": "python wiki_mcp.py"}],
        }))
    for name, body in [("web_audit.md", "ตรวจเว็บ"), ("seo_check.md", "ตรวจ SEO")]:
        with open(os.path.join(pkg, "skills", name), "w", encoding="utf-8") as f:
            f.write(f"---\nname: {name[:-3]}\ndescription: {body}\n---\n{body}...\n")
    return pkg


@pytest.fixture(scope="module")
def yaml_pkg():
    pkg = os.path.join(BASE, "yaml-pkg")
    os.makedirs(os.path.join(pkg, "skills"))
    with open(os.path.join(pkg, "marketplace.yaml"), "w", encoding="utf-8") as f:
        f.write("id: yaml-pkg\nname: YAML Pkg\nversion: 0.9.0\nauthor: test\n"
                "price: 4.99\ncurrency: USD\nskills:\n  - skills/a.md\n"
                "mcp_servers:\n  - name: db\n    cmd: python db_mcp.py\n")
    with open(os.path.join(pkg, "skills", "a.md"), "w", encoding="utf-8") as f:
        f.write("---\nname: a\n---\nbody")
    return pkg


def test_parse_manifests(web_pkg, yaml_pkg):
    man = M.parse_manifest(M.find_package_root(web_pkg))
    assert man["id"] == "web-tools" and man["version"] == "1.2.0"
    man2 = M.parse_manifest(M.find_package_root(yaml_pkg))
    assert man2["id"] == "yaml-pkg" and man2["price"] == 4.99
    assert man2["mcp_servers"][0]["cmd"] == "python db_mcp.py"


def test_install_and_dup_block(web_pkg, yaml_pkg):
    r = M.install(web_pkg)
    assert r["ok"] and r["id"] == "web-tools" and len(r["skills"]) == 2
    assert os.path.isfile(os.path.join(os.environ["YOUSINI_GLOBAL_SKILLS"], "web_audit.md"))
    rec = M.load_installed()["web-tools"]
    assert rec["version"] == "1.2.0" and rec["mcp_servers"] == ["wiki"]
    r2 = M.install(web_pkg)
    assert not r2["ok"] and "ติดตั้งอยู่แล้ว" in r2["error"]
    r3 = M.install(yaml_pkg)
    assert r3["ok"] and r3["id"] == "yaml-pkg"
    names = sorted(load_mcp_config().keys())
    assert "wiki" in names and "db" in names


def test_catalog_and_search(web_pkg):
    reg = {"packages": [
        {"id": "web-tools", "name": "Web Tools", "version": "1.2.0", "price": 0,
         "description": "เครื่องมือเว็บ", "tags": ["web", "seo"], "source": web_pkg},
        {"id": "other", "name": "Something Else", "version": "2.0.0", "price": 5.0}]}
    with open(os.path.join(BASE, "registry.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(reg))
    pkgs = M.fetch_catalog(force=True)
    assert len(pkgs) == 2
    assert M.search_catalog("seo")[0]["id"] == "web-tools"
    assert len(M.search_catalog("web")) == 1
    assert len(M.fetch_catalog()) == 2               # ใช้ cache


def test_info(web_pkg):
    i = M.pkg_info("web-tools")
    assert i["installed"] and i["version"] == "1.2.0"
    assert not M.pkg_info("other")["installed"]


def test_uninstall(web_pkg):
    u = M.uninstall("web-tools")
    assert u["ok"] and u["removed_skills"] == 2
    assert not os.path.isfile(os.path.join(os.environ["YOUSINI_GLOBAL_SKILLS"], "web_audit.md"))
    assert "web-tools" not in M.load_installed()
    assert all(k != "wiki" for k in load_mcp_config())
    assert not M.uninstall("nope")["ok"]


def test_update_and_price(web_pkg, yaml_pkg):
    r = M.update("yaml-pkg")
    assert r["ok"] and r["id"] == "yaml-pkg"
    assert M._price({"price": 0}) == "ฟรี"
    assert M._price({"price": 4.99}) == "$4.99 USD"