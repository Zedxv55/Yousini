"""Tests for Multi-agent orchestration (v3.8)."""
import pytest
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from yousini_orchestrate import orchestrate_task, _pick_sub_agents


def test_orchestrate_basic():
    """Test basic orchestration run."""
    result = asyncio.run(orchestrate_task("simple task"))
    assert result["status"] in ("ok", "partial")
    assert "summary" in result
    assert "per_agent" in result


def test_orchestrate_with_sub_agents():
    """Test orchestration with specified sub-agents."""
    result = asyncio.run(
        orchestrate_task(
            "analyze code",
            sub_agents=["code_reviewer", "debugger"]
        )
    )
    assert result["status"] == "ok"
    assert "code_reviewer" in result["per_agent"]
    assert "debugger" in result["per_agent"]
    assert result["per_agent"]["code_reviewer"]["status"] == "ok"


def test_orchestrate_timeout():
    """Test orchestration with timeout."""
    result = asyncio.run(orchestrate_task("test timeout", timeout=1))
    # Should complete quickly since simulate has 0.1s delay
    assert result["status"] in ("ok", "partial")


def test_pick_sub_agents_code_keywords():
    """Test agent selection for code-related tasks."""
    agents = _pick_sub_agents("find bug in python code debug")
    assert "code_reviewer" in agents
    assert "debugger" in agents


def test_pick_sub_agents_design_keywords():
    """Test agent selection for design-related tasks."""
    agents = _pick_sub_agents("design architecture plan")
    assert "architect" in agents


def test_pick_sub_agents_default():
    """Test default agent selection."""
    agents = _pick_sub_agents("random task without keywords")
    assert "general" in agents