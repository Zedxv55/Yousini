"""Tests สำหรับ /undo, /rollback --full, /diff (B2+B3)

ใช git repo จริงใน tmp_path เพื่อให `_rollback_to_last_checkpoint` และ
`_print_file_diff` ทำงานผาน git command เดียวกับ runtime."""
import os
import subprocess
import sys

os.environ.setdefault("YOUSINI_API_KEY", "dummy-test-key")
os.environ.setdefault("YOUSINI_BASE_URL", "https://api.example.test/v1")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import yousini


@pytest.fixture()
def mini_repo(tmp_path):
    """git repo เปล่า มีไฟล a.txt + commit แรก และ checkpoint ของ yousini 2 จุด"""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    a = tmp_path / "a.txt"
    a.write_text("v1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "first"], cwd=tmp_path, check=True)
    # checkpoint 1: แกไขไฟล
    a.write_text("v2\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "[Yousini checkpoint] auto c1"],
                   cwd=tmp_path, check=True)
    # checkpoint 2: แกไขอีกครั้ (working ทิ้งไวที่ v2 เพื่อให้ "/undo" ย้อนค่า c2)
    a.write_text("v3\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "[Yousini checkpoint] auto c2"],
                   cwd=tmp_path, check=True)
    # หมายเหตุ: working ต้องต่างจาก c2 (v3) เพื่อให /undo ย้อน c2 ไดหลายครั้
    # แตสำหรับ test diff ทต้องการ working สะอาด ใช /undo หนึ่งครั้ก่อน
    return tmp_path


def _agent(cwd):
    agent = yousini.Agent()
    agent.cwd = str(cwd)
    return agent


# ── helpers ใชร่วมกับ test เดิม ────────────────────────────────────
import unittest.mock as mock


def _setup_common_patches(monkeypatch, cwd):
    monkeypatch.setattr(yousini, "_print_banner", lambda a: None)
    monkeypatch.setattr(yousini, "_ui_cmd_hints", lambda: None)
    monkeypatch.setattr(yousini, "_print_session_summary", lambda: None)
    monkeypatch.setattr(yousini, "_setup_readline", lambda: None)
    monkeypatch.setattr(yousini, "_print_help", lambda: None)
    monkeypatch.setattr(yousini, "_print_history", lambda a: None)
    monkeypatch.setattr(yousini, "_print_skills", lambda a: None)
    monkeypatch.setattr(yousini, "_print_hooks", lambda a: None)
    monkeypatch.setattr(yousini, "_providers_cmd", lambda: None)
    monkeypatch.setattr(yousini, "_usage_status_text", lambda: "(test)")
    monkeypatch.setattr(yousini, "_repl_market", lambda s: None)
    monkeypatch.setattr(yousini, "atexit", mock.MagicMock())
    monkeypatch.setattr(yousini, "SessionStore", mock.MagicMock())


def _make_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    agent = yousini.Agent.__new__(yousini.Agent)
    agent.cwd = str(tmp_path)
    agent.messages = [{"role": "system", "content": "test"}]
    agent.system_prompt = "test"
    agent.quiet_mode = False
    agent._typewriter = False
    agent.jobs = mock.MagicMock()
    agent.jobs.summary.return_value = "(ไมมงาน)"
    mem = mock.MagicMock()
    mem.stores = {"user": mock.MagicMock(), "agent": mock.MagicMock()}
    mem.stores["user"].to_text.return_value = ""
    mem.stores["agent"].to_text.return_value = ""
    agent.memory = mem
    agent.hooks = yousini.Hooks()
    return agent


def _run_repl_with(monkeypatch, tmp_path, inputs):
    it = iter(inputs)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))
    _setup_common_patches(monkeypatch, tmp_path)
    agent = _make_agent(tmp_path, monkeypatch)
    yousini._run_repl(agent)
    return agent


def test_rollback_no_repo(tmp_path):
    """ไม่อยู่ใน git repo → แจ้งชัด ไม crash"""
    assert yousini._rollback_to_last_checkpoint(_agent(tmp_path)).startswith(
        "ไม")


def test_rollback_success(mini_repo):
    agent = _agent(mini_repo)
    (mini_repo / "a.txt").write_text("v5\n")  # working dirty
    assert yousini._rollback_to_last_checkpoint(agent).startswith("rollback สำเร็จ")
    # working tree กลับไปท checkpoint 2 (c2 = v3)
    assert (mini_repo / "a.txt").read_text().strip() == "v3"


def test_rollback_undo_twice(mini_repo):
    """/undo 2 ครั้: ย้อน checkpoint 2 (v3) → checkpoint 1 (v2)"""
    agent = _agent(mini_repo)
    # working = v3 (ตรงกับ c2) เพื่อให "checkpoint ใกลสุด" ของ log เป็น c2
    yousini._rollback_to_last_checkpoint(agent)  # → c2 (v3)
    yousini._rollback_to_last_checkpoint(agent)  # → c1 (v2)
    assert (mini_repo / "a.txt").read_text().strip() == "v2"


def test_rollback_full_goes_to_oldest(mini_repo):
    """/rollback --full → reset ไปยัง checkpoint เกาสุด (แรกสุด = c1 = v2)"""
    agent = _agent(mini_repo)
    res = yousini._rollback_to_last_checkpoint(agent, full=True)
    assert res.startswith("rollback สำเร็จ")
    assert (mini_repo / "a.txt").read_text().strip() == "v2"


def test_rollback_no_checkpoint(tmp_path):
    """repo แตไมม commit ที่เป็น checkpoint → แจงชัด"""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    (tmp_path / "x.txt").write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "ไมใช checkpoint"], cwd=tmp_path, check=True)
    agent = _agent(tmp_path)
    assert "ไมพบ checkpoint" in yousini._rollback_to_last_checkpoint(agent)


def test_rollback_git_failure(mini_repo):
    """git reset ล้มเหลว → คืนข้อความ error แทน raise"""
    agent = _agent(mini_repo)

    with pytest.MonkeyPatch.context() as mp:
        _orig = subprocess.run

        def bad_run(*a, **kw):
            if a[0][0] == "git" and a[0][1] == "reset":
                return subprocess.CompletedProcess(a[0], 1, "", "reset exploded")
            return _orig(a[0], **kw)

        mp.setattr("yousini.subprocess.run", bad_run)
        assert "ไมสำเร็จ" in yousini._rollback_to_last_checkpoint(agent)


def test_rollback_exception_safety(mini_repo):
    """subprocess raise → ฟังก์ชันคืนข้อความ Error ไม raise"""
    agent = _agent(mini_repo)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("yousini.subprocess.run", lambda *a, **kw: (_ for _ in ()).throw(
            OSError("boom")))
        assert yousini._rollback_to_last_checkpoint(agent).startswith("Error")


# ── _confirm_full_rollback ────────────────────────────────────────
def test_confirm_full_rollback_answers(monkeypatch):
    for answer, expect in (("y", True), ("yes", True), ("n", False), ("", False),
                           ("random", False)):
        monkeypatch.setattr("builtins.input", lambda prompt="": answer)
        assert yousini._confirm_full_rollback() is expect


def test_confirm_full_rollback_eof():
    """EOF/ctrl-c ไมต้องการ confirm → คืน False (fail-safe)"""
    import io
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(EOFError))
        assert yousini._confirm_full_rollback() is False


# ── /undo และ /rollback --full ใน routing REPL ─────────────────────
def test_repl_undo_routes(monkeypatch, capsys, mini_repo):
    """/undo ใน REPL → เรียก _rollback_to_last_checkpoint และแสดงผล"""
    calls = []
    yousini._rollback_to_last_checkpoint = lambda ag, full=False: (
        calls.append(full) or "rollback สำเร็จ → คืนสถานะท abc")
    _run_repl_with(monkeypatch, mini_repo, ["/undo", "/exit"])
    out = capsys.readouterr().out
    assert calls == [False]
    assert "rollback สำเร็จ" in out


def test_repl_rollback_full_denied(monkeypatch, capsys, mini_repo):
    """/rollback --full ที่ตอบ N → ไมได reset"""
    calls = []
    yousini._rollback_to_last_checkpoint = lambda ag, full=False: (
        calls.append(full) or "rollback")
    _inputs = iter(["/rollback --full", "N", "/exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(_inputs))
    _setup_common_patches(monkeypatch, mini_repo)
    agent = _make_agent(mini_repo, monkeypatch)
    yousini._run_repl(agent)
    out = capsys.readouterr().out
    assert "ยกเลิก" in out
    assert calls == []  # ไมไดเรียก reset เพราะ confirm ไมผ่าน





# ── /diff ─────────────────────────────────────────────────────────
def test_diff_no_repo(monkeypatch, capsys, tmp_path):
    agent = _agent(tmp_path)
    yousini._print_file_diff(agent, "a.txt")
    out = capsys.readouterr().out
    assert "git repository" in out


def test_diff_unchanged_file(monkeypatch, capsys, mini_repo):
    agent = _agent(mini_repo)
    yousini._print_file_diff(agent, "a.txt")
    out = capsys.readouterr().out
    assert "ไมมการเปลี่ยนแปลง" in out


def test_diff_modified_file_colored(monkeypatch, capsys, mini_repo):
    agent = _agent(mini_repo)
    (mini_repo / "a.txt").write_text("v3\nv4\n")  # +1 บรรทัด (git worktree)
    yousini._print_file_diff(agent, "a.txt")
    out = capsys.readouterr().out
    assert "v4" in out and "diff:" in out


def test_diff_stat_panel_when_clean(monkeypatch, capsys, mini_repo):
    agent = _agent(mini_repo)
    yousini._print_colored_diff(agent)
    out = capsys.readouterr().out
    assert "สะอาด" in out


def test_diff_stat_panel_when_dirty(monkeypatch, capsys, mini_repo):
    """ไฟลทแก (tracked) → แสดง panel diff --stat"""
    agent = _agent(mini_repo)
    (mini_repo / "a.txt").write_text("v3\nv4\n")
    yousini._print_colored_diff(agent)
    out = capsys.readouterr().out
    assert "a.txt" in out and "diff --stat" in out


def test_diff_staged_file_found_via_cached(monkeypatch, capsys, mini_repo):
    agent = _agent(mini_repo)
    # แก + add → ไมอยู่ใน working-tree diff แต่อยู่ใน --cached
    (mini_repo / "c.txt").write_text("staged\n")
    subprocess.run(["git", "add", "."], cwd=mini_repo, check=True)
    yousini._print_file_diff(agent, "c.txt")
    out = capsys.readouterr().out
    assert "staged" in out
