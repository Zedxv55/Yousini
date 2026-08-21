import os
import shutil

os.environ.setdefault("YOUSINI_API_KEY", "test-key")
from yousini import Agent


def test_agent_uses_isolated_shell_when_enabled(tmp_path):
    agent = Agent(cwd=str(tmp_path), interactive=False, sandbox=True)
    output = agent.shell("printf agent-sandbox")

    if shutil.which("bwrap"):
        assert "[sandbox: bwrap | isolated: yes | exit code: 0]" in output
        assert "agent-sandbox" in output
    else:
        assert "Sandbox unavailable:" in output
        assert "จะไม่รันคำสั่งบน host" in output


def test_agent_sandbox_refuses_background_shell(tmp_path):
    agent = Agent(cwd=str(tmp_path), interactive=False, sandbox=True)
    output = agent.shell("sleep 1", run_in_background=True)

    assert "ยังไม่รองรับ background job" in output


def test_agent_sandbox_write_is_explicit_opt_in(tmp_path):
    agent = Agent(cwd=str(tmp_path), interactive=False, sandbox=True, sandbox_writable=True)
    output = agent.shell("printf ready > result.txt")

    if shutil.which("bwrap"):
        assert "exit code: 0" in output
        assert (tmp_path / "result.txt").read_text(encoding="utf-8") == "ready"
    else:
        assert "Sandbox unavailable:" in output
