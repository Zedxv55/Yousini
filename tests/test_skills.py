#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for yousini_skills.py — skill install จาก git repo"""
import subprocess
import zipfile
from pathlib import Path
from unittest import mock

import pytest

import yousini_skills


@pytest.fixture(autouse=True)
def tmp_skills(tmp_path, monkeypatch):
    monkeypatch.setattr(yousini_skills, "SKILLS_DIR", tmp_path / "skills")
    yield


def _make_repo(tmp_path, name="repo"):
    """สร้าง repo ท้องถิ่นพร้อมไฟล skills/*.md"""
    root = tmp_path / name
    root.mkdir()
    skills = root / "skills"
    skills.mkdir()
    (skills / "hello.md").write_text("# hello skill\n")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True,
                   capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    return root


def test_no_args_prints_usage(capsys):
    yousini_skills.skill_install([])
    assert "ใช้: yousini skill install" in capsys.readouterr().out


def test_missing_subcommand_prints_usage(capsys):
    yousini_skills.skill_install(["build"])
    assert "ใช้: yousini skill install" in capsys.readouterr().out


def test_missing_url_prints_error(capsys):
    yousini_skills.skill_install(["install"])
    assert "ต้องให้ URL" in capsys.readouterr().out


def test_install_from_local_git(tmp_path, capsys):
    repo = _make_repo(tmp_path)
    yousini_skills.skill_install(["install", str(repo)])
    out = capsys.readouterr().out
    assert "hello.md" in out
    assert "สำเร็จ 1 skill" in out
    assert (yousini_skills.SKILLS_DIR / "hello.md").exists()


def test_install_skips_existing(tmp_path, capsys):
    repo = _make_repo(tmp_path)
    yousini_skills.SKILLS_DIR.mkdir(parents=True)
    (yousini_skills.SKILLS_DIR / "hello.md").write_text("old")
    yousini_skills.skill_install(["install", str(repo)])
    out = capsys.readouterr().out
    assert "มีอยู่แล้ว: hello.md (ข้าม)" in out


def test_install_no_md_files(tmp_path, capsys):
    root = tmp_path / "empty"
    root.mkdir()
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(tmp_path), capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"],
                   cwd=root, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    yousini_skills.skill_install(["install", str(root)])
    assert "skill (.md)" in capsys.readouterr().out


def test_install_bad_url_prints_error(capsys):
    yousini_skills.skill_install(["install", "git://not-valid-url-xyz"])
    assert "Error" in capsys.readouterr().out
