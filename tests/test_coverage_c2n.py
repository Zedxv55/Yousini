"""B4: tests for /persona REPL command."""
import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import yousini
from yousini import Agent


@pytest.fixture
def agent():
    a = Agent(model="test", cwd="/tmp")
    a.system_prompt = "คุณคือผู้ช่วย AI"
    a.messages = [{"role": "system", "content": "คุณคือผู้ช่วย AI"}]
    return a


def test_persona_casual(agent, monkeypatch, capsys):
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    with mock.patch("builtins.input", side_effect=["/persona casual", KeyboardInterrupt]):
        with mock.patch.object(yousini, "_print_session_summary"):
            with mock.patch.object(yousini, "_ui_cmd_hints"):
                try:
                    yousini._run_repl(agent)
                except (KeyboardInterrupt, SystemExit):
                    pass
    assert "## PERSONA" in agent.system_prompt
    assert "casual" in agent.system_prompt.lower() or "เป็นกันเอง" in agent.system_prompt
    assert agent.messages[0]["content"] == agent.system_prompt


def test_persona_verbose(agent, monkeypatch):
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    with mock.patch("builtins.input", side_effect=["/persona verbose", KeyboardInterrupt]):
        with mock.patch.object(yousini, "_print_session_summary"):
            with mock.patch.object(yousini, "_ui_cmd_hints"):
                try:
                    yousini._run_repl(agent)
                except (KeyboardInterrupt, SystemExit):
                    pass
    assert agent.system_prompt.count("## PERSONA") == 1
    assert "ละเอียด" in agent.system_prompt or "verbose" in agent.system_prompt.lower()


def test_persona_reset(agent, monkeypatch):
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    with mock.patch("builtins.input", side_effect=["/persona casual", "/persona reset",
                                                   KeyboardInterrupt]):
        with mock.patch.object(yousini, "_print_session_summary"):
            with mock.patch.object(yousini, "_ui_cmd_hints"):
                try:
                    yousini._run_repl(agent)
                except (KeyboardInterrupt, SystemExit):
                    pass
    assert "## PERSONA" not in agent.system_prompt
    assert agent.system_prompt == "คุณคือผู้ช่วย AI"


def test_persona_unknown_and_noargs(agent, monkeypatch):
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    with mock.patch("builtins.input", side_effect=["/persona robot", "/persona",
                                                   KeyboardInterrupt]):
        with mock.patch.object(yousini, "_print_session_summary"):
            with mock.patch.object(yousini, "_ui_cmd_hints"):
                try:
                    yousini._run_repl(agent)
                except (KeyboardInterrupt, SystemExit):
                    pass
    assert "## PERSONA" not in agent.system_prompt
    # console.print ถูกเรียกสำหรับ 2 คำเตือน
    assert yousini.console.print.call_count >= 2
