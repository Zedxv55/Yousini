"""ทดสอบ Git PR flow (yousini_git.create_pr) — ใช้ local bare repo เป็น origin (ออฟไลน์)"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import yousini_git as G

GIT = G._git_bin()
pytestmark = pytest.mark.skipif(not GIT, reason="ไม่มี git บนเครื่อง")


def git(cwd, *args, check=True):
    return subprocess.run([GIT, "-C", str(cwd), *args], capture_output=True, text=True, check=check)


@pytest.fixture()
def repo(tmp_path):
    """work repo + bare origin — push ชี้ local bare, fetch ชี้ github (สร้าง URL ได้)"""
    work = tmp_path / "work"
    work.mkdir()
    bare = tmp_path / "origin.git"
    git(work, "init", "-b", "main", "-q")
    git(work, "config", "user.email", "test@yousini.local")
    git(work, "config", "user.name", "Tester")
    (work / "a.txt").write_text("hi\n", encoding="utf-8")
    git(work, "add", ".")
    git(work, "commit", "-m", "init", "-q")
    git(work, "clone", "--bare", str(work), str(bare))
    git(work, "remote", "add", "origin", "https://github.com/acme/widget.git")
    git(work, "remote", "set-url", "--push", "origin", str(bare))
    git(work, "push", "-u", "origin", "main")
    return work, bare


def test_parse_origin():
    assert G._parse_origin("git@github.com:acme/widget.git") == ("acme", "widget")
    assert G._parse_origin("https://github.com/acme/widget.git") == ("acme", "widget")
    assert G._parse_origin("") == ("", "")


def test_create_pr_auto_branch(repo):
    work, bare = repo
    (work / "b.txt").write_text("work\n", encoding="utf-8")          # dirty
    r = G.create_pr("เพิ่ม feature สุดยอด", branch="", base="main", cwd=str(work))
    assert "/compare/main...yousini/feature?expand=1" in r, r
    cur = git(work, "branch", "--show-current").stdout.strip()
    assert cur == "yousini/feature"
    heads = git(work, "ls-remote", "--heads", str(bare)).stdout
    assert "refs/heads/" + cur in heads                               # push สำเร็จจริง


def test_create_pr_named_branch(repo):
    work, bare = repo
    r = G.create_pr("งานที่สอง", branch="feat/x", base="main", cwd=str(work))
    assert "/compare/main...feat/x" in r, r
    heads = git(work, "ls-remote", "--heads", str(bare)).stdout
    assert "refs/heads/feat/x" in heads


def test_create_pr_reuses_current_feature_branch(repo):
    work, bare = repo
    G.create_pr("งานแรก", branch="feat/a", base="main", cwd=str(work))
    r = G.create_pr("งานที่สอง", branch="", base="main", cwd=str(work))
    assert "feat/a" in r                                             # ใช้สาขาปัจจุบัน (ไม่เท่ากับ main)


def test_create_pr_needs_title(repo):
    work, _ = repo
    r = G.create_pr("", cwd=str(work))
    assert "title" in r


def test_create_pr_not_a_repo(tmp_path):
    r = G.create_pr("งาน", cwd=str(tmp_path))
    assert "Error" in r


def test_create_pr_no_origin(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    git(work, "init", "-b", "main", "-q")
    git(work, "config", "user.email", "t@t.t")
    git(work, "config", "user.name", "T")
    (work / "a").write_text("x", encoding="utf-8")
    git(work, "add", ".")
    git(work, "commit", "-m", "init", "-q")
    r = G.create_pr("งาน", cwd=str(work))
    assert "origin" in r


def test_slug_ascii():
    assert G._slug("เพิ่ม feature สุดยอด") == "feature"
    assert G._slug("fix!!") == "fix"
    assert G._slug("###") == "pr"