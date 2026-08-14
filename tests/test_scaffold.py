"""ทดสอบ project scaffolding (yousini_scaffold)"""
import os
import subprocess
import sys
import textwrap

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import yousini_scaffold as S


@pytest.mark.parametrize("kind,expect_files", [
    ("python-cli", {"pyproject.toml", "README.md", ".gitignore"}),
    ("python-pkg", {"pyproject.toml", "README.md", ".gitignore"}),
    ("web-static", {"index.html", "style.css", "app.js", "README.md"}),
])
def test_scaffold_creates_files(tmp_path, kind, expect_files):
    r = S.scaffold(kind, "demo", str(tmp_path))
    assert not r.startswith("Error"), r
    root = tmp_path / "demo"
    assert root.is_dir()
    made = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
    assert expect_files <= made


def test_scaffold_tokens_replaced(tmp_path):
    S.scaffold("python-cli", "mycli", str(tmp_path))
    main = (tmp_path / "mycli" / "mycli" / "main.py").read_text(encoding="utf-8")
    assert "mycli" in main and "[[name]]" not in main and "[[Name]]" not in main
    py = (tmp_path / "mycli" / "pyproject.toml").read_text(encoding="utf-8")
    assert "pythonpath" in py  # pytest ini พร้อมรันได้ทันที


def test_web_static_braces_kept(tmp_path):
    """CSS/JS มี literal {} ต้องไม่ถูก format หัก"""
    r = S.scaffold("web-static", "site", str(tmp_path))
    assert not r.startswith("Error"), r
    css = (tmp_path / "site" / "style.css").read_text(encoding="utf-8")
    assert "body {" in css and "}" in css


def test_generated_python_projects_test_ok(tmp_path):
    for kind in ("python-cli", "python-pkg"):
        name = "gen" + kind.replace("python-", "")
        S.scaffold(kind, name, str(tmp_path))
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                              cwd=str(tmp_path / name), capture_output=True, text=True, timeout=120)
        assert proc.returncode == 0, proc.stdout + proc.stderr


def test_invalid_kind(tmp_path):
    r = S.scaffold("nope", "x", str(tmp_path))
    assert r.startswith("Error") and "nope" in r


def test_invalid_name(tmp_path):
    r = S.scaffold("web-static", "a b!", str(tmp_path))
    assert r.startswith("Error")


def test_existing_dir_rejected(tmp_path):
    (tmp_path / "dup").mkdir()
    r = S.scaffold("web-static", "dup", str(tmp_path))
    assert r.startswith("Error") and "มีอยู่แล้ว" in r


def test_kinds_label():
    assert "python-cli" in S.kinds_text() and "web-static" in S.kinds_text()