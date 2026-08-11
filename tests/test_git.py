"""ทดสอบ Git awareness — รู้ประวัติ commit เป็น context (Phase 10)"""
import os, sys, subprocess, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from yousini_git import recent_log, blame, status_short, diff_stat, last_commits_block


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    """สร้าง git repo จริงใน tmp — commit 2 ครั้ง แล้วแก้ไฟล์ 1 ครั้ง (dirty)"""
    root = tmp_path_factory.mktemp("gitrepo")
    if shutil.which("git") is None:
        pytest.skip("ไม่มี git บนเครื่อง")
    def g(*args):
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
    g("init", "-b", "main", "-q")
    g("config", "user.email", "test@yousini.local")
    g("config", "user.name", "Tester")
    (root / "a.txt").write_text("บรรทัดแรก\nบรรทัดที่สอง\n", encoding="utf-8")
    g("add", ".")
    g("commit", "-m", "feat: เพิ่มไฟล์แรก", "-q")
    (root / "b.txt").write_text("hello\n", encoding="utf-8")
    g("add", ".")
    g("commit", "-m", "fix: แก้บั๊กครั้งแรก", "-q")
    (root / "a.txt").write_text("บรรทัดแรก\nแก้แล้ว\n", encoding="utf-8")  # dirty
    return root


def test_recent_log_order(repo):
    log = recent_log(5, str(repo))
    assert "fix: แก้บั๊กครั้งแรก" in log[0]     # ล่าสุดมาก่อน
    assert "feat: เพิ่มไฟล์แรก" in log[1]


def test_status_shows_dirty(repo):
    st = status_short(str(repo))
    assert "a.txt" in st and "M" in st          # มีไฟล์แก้ค้าง


def test_diff_stat_nonempty(repo):
    ds = diff_stat(str(repo))
    assert "a.txt" in ds


def test_blame_line(repo):
    out = blame("a.txt", 1, str(repo))          # บรรทัด 1 อยู่ใน HEAD แล้ว
    assert "Tester" in out                      # ผู้เขียนบรรทัด


def test_blame_dirty_line(repo):
    out = blame("a.txt", 2, str(repo))          # บรรทัด 2 ถูกแก้แล้ว ยังไม่ commit
    assert "Not Committed Yet" in out


def test_blame_missing_line(repo):
    out = blame("nonexistent.py", 1, str(repo))
    assert "ไม่พบ" in out or "error" in out.lower() or out.strip() == ""


def test_last_commits_block(repo):
    block = last_commits_block(3, str(repo))
    assert "ประวัติ git" in block
    assert "เพิ่มไฟล์แรก" in block


def test_log_outside_repo(tmp_path):
    log = recent_log(3, str(tmp_path))
    assert isinstance(log, list) and log == []