from pathlib import Path

import pytest

from yousini_sandbox import Sandbox


def test_unavailable_backend_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr("yousini_sandbox.shutil.which", lambda _: None)
    result = Sandbox(workspace=tmp_path).run("printf unsafe")

    assert result["unavailable"] is True
    assert result["isolated"] is False
    assert result["exit_code"] == -1
    assert "จะไม่รันคำสั่งบน host" in result["stderr"]


def test_rejects_cwd_outside_workspace(tmp_path):
    result = Sandbox(workspace=tmp_path, backend="missing").run("pwd", cwd="..")

    assert result["exit_code"] == -1
    assert "ต้องอยู่ภายใน workspace" in result["stderr"]


def test_read_only_workspace_rejects_new_cwd(tmp_path):
    result = Sandbox(workspace=tmp_path, backend="missing").run("pwd", cwd="new-dir")

    assert result["exit_code"] == -1
    assert "read-only" in result["stderr"]


@pytest.mark.skipif(not Sandbox.available_backends()["bwrap"], reason="Bubblewrap is not installed")
def test_bwrap_isolates_workspace_and_allows_explicit_write(tmp_path):
    source = tmp_path / "input.txt"
    source.write_text("safe input", encoding="utf-8")

    readonly = Sandbox(workspace=tmp_path, timeout=10)
    read_result = readonly.run("cat input.txt && printf '\\n' && test ! -e /home/ubuntu")
    denied_write = readonly.run("printf blocked > blocked.txt")

    assert read_result["isolated"] is True
    assert read_result["exit_code"] == 0
    assert "safe input" in read_result["stdout"]
    assert denied_write["exit_code"] != 0
    assert not (tmp_path / "blocked.txt").exists()

    writable = Sandbox(workspace=tmp_path, timeout=10, writable=True)
    write_result = writable.run("printf allowed > created.txt")

    assert write_result["isolated"] is True
    assert write_result["exit_code"] == 0
    assert (tmp_path / "created.txt").read_text(encoding="utf-8") == "allowed"
