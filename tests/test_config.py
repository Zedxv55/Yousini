"""ทดสอบ feature flags & config (v3.8) — yousini_config"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import yousini_config as C


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    return tmp_path


def test_default_flags_all_on(cfg):
    f = C.all_flags()
    assert f["plugin_system"] is True
    assert f["usage_report"] is True


def test_get_flag_default_when_unset(cfg):
    assert C.get_flag("plugin_system") is True
    assert C.get_flag("unknown_flag", True) is True


def test_set_flag_and_read(cfg):
    r = C.set_flag("usage_report", False)
    assert "ปิด" in r
    assert C.get_flag("usage_report") is False
    assert C.all_flags()["usage_report"] is False
    C.set_flag("usage_report", True)
    assert C.get_flag("usage_report") is True


def test_flag_cmd_list_and_set(cfg):
    r = C.flag_cmd("list")
    assert "plugin_system" in r and "usage_report" in r
    r2 = C.flag_cmd("plugin_system off")
    assert "ปิด" in r2
    assert C.get_flag("plugin_system") is False
    r3 = C.flag_cmd("plugin_system")
    assert "ปิด" in r3


def test_flag_cmd_unknown(cfg):
    assert "ไม่รู้จัก" in C.flag_cmd("bogus")


def test_config_get_set(cfg):
    r = C.set_value("theme", "nord")
    assert "config 'theme'" in r
    assert C.get_value("theme") == "nord"
    assert C.get_value("nope") is None


def test_set_value_type_coerce(cfg):
    C.set_value("quiet_mode", "true")
    assert C.get_value("quiet_mode") is True
    C.set_value("port", "8787")
    assert C.get_value("port") == 8787


def test_config_cmd(cfg):
    C.set_value("theme", "dark")
    r = C.config_cmd("list")
    assert "theme" in r
    assert "config 'theme'" in C.config_cmd("get theme")
    assert "config 'theme'" in C.config_cmd("set theme nord")
    assert C.get_value("theme") == "nord"
    assert "config.json" in C.config_cmd("")   # ว่าง → แสดง list