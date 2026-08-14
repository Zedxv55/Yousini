"""ทดสอบ team workspace (yousini_team) — init/registry/join/roles"""
import json
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="ys_team_")
os.environ["YOUSINI_TEAM_FILE"] = os.path.join(TMP, "team.json")
os.environ["YOUSINI_TEAM_CACHE"] = os.path.join(TMP, "team_cache.json")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import yousini_team as T  # noqa: E402


@pytest.fixture(autouse=True)
def clean_team():
    yield
    T.TEAM_FILE.unlink(missing_ok=True)
    T.CACHE_FILE.unlink(missing_ok=True)


def test_init_and_load():
    r = T.init("DevOps ทีม")
    assert r.get("ok") and r["workspace"] == "devops"
    assert T.load_local().get("name") == "DevOps ทีม"


def test_set_registry():
    T.set_registry("https://reg.example.com/x.json")
    assert T.load_local()["registry"] == "https://reg.example.com/x.json"


def test_resolve_registry_precedence():
    T.set_registry("https://reg.example.com/x.json")
    assert T.resolve_registry({"registry_url": "cfg-url"}) == "https://reg.example.com/x.json"
    T.set_registry("")
    os.environ["YOUSINI_REGISTRY"] = "env-url"
    assert T.resolve_registry({"registry_url": "cfg-url"}) == "cfg-url"
    assert T.resolve_registry({}) == "env-url"
    del os.environ["YOUSINI_REGISTRY"]


def test_join_via_file_remote(tmp_path):
    remote = tmp_path / "remote_team.json"
    remote.write_text(json.dumps({
        "workspace": "core-team", "name": "Core Team", "registry": "https://core/reg.json",
        "rules": {"auto_run": True, "safe": True},
        "users": [{"name": "remote-admin", "token": "rtok", "role": "admin"}],
    }, ensure_ascii=False), encoding="utf-8")
    r = T.join("file:///" + str(remote).replace("\\", "/"))
    assert r.get("ok") and r["workspace"] == "core-team"
    eff = T.effective()
    assert eff["name"] == "Core Team"
    assert eff["registry"] == "https://core/reg.json"
    assert eff["rules"] == {"auto_run": True, "safe": True}
    # local users รวมกับ remote
    T.save_local({**T.load_local(), "users": [{"name": "localadmin", "token": "lok", "role": "admin"}]})
    eff = T.effective()
    names = [u["name"] for u in eff.get("users", [])]
    assert "remote-admin" in names and "localadmin" in names


def test_roles():
    T.save_local({"workspace": "t", "name": "T", "registry": "",
                  "users": [{"name": "bob", "token": "b", "role": "member"},
                            {"name": "ann", "token": "a", "role": "admin"}]})
    assert T.role_for_token("b") == ("bob", "member")
    assert T.role_for_token("a") == ("ann", "admin")
    assert T.role_for_token("nope") is None


def test_leave():
    T.save_local({"workspace": "t", "name": "T", "registry": "", "users": []})
    r = T.leave()
    assert r.get("ok") or T.load_local() is None or T.load_local().get("workspace") != "t"


def test_team_status_format():
    T.save_local({"workspace": "t", "name": "T", "registry": "https://r/x.json",
                  "users": [{"name": "ann", "token": "a", "role": "admin"}]})
    st = T.team_status({"team_token": "a"})
    assert st.get("active") or st.get("workspace") == "t"
    s = T.format_status(st)
    assert "t" in s