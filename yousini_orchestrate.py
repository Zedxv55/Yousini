"""Multi-agent orchestration for Yousini (v3.8).

Allows the main agent to delegate tasks to sub‑agents and aggregate results.

Typical use from chat or CLI:
    result = orchestrate_task(
        "Analyse this codebase and report bugs",
        sub_agents=["code_reviewer", "debugger"]
    )
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("yousini.orchestrate")


# ---------------------------------------------------------------------------
# Helper: pick sub‑agent names from task keywords (Thai + English)


def _pick_sub_agents(task: str) -> List[str]:
    """Heuristically pick sub‑agent names from task keywords."""
    task_lower = task.lower()
    if any(k in task_lower for k in {"code", "python", "function", "debug", "bug", "โค้ด", "บั๊ก"}):
        return ["code_reviewer", "debugger"]
    if any(k in task_lower for k in {"design", "architecture", "แผน", "โครงสร้าง"}):
        return ["architect", "planner"]
    if any(k in task_lower for k in {"write", "create", "generate", "ดิ่ง", "สร้าง"}):
        return ["writer", "editor"]
    # default fallback (Thai)
    return ["general"]


# ---------------------------------------------------------------------------
# Core orchestration


async def orchestrate_task(
    task: str,
    sub_agents: Optional[List[str]] = None,
    timeout: int = 300,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Dispatch *task* to one or more sub‑agents and aggregate results.

    Parameters
    ----------
    task: str
        Natural‑language description of the work to do.
    sub_agents: list[str] | None
        Names of sub‑agents to involve. If ``None`` the orchestrator
        picks a reasonable default based on *task* keywords.
    timeout: int
        Seconds before the whole operation is cancelled.
    **kwargs:
        Pass‑through options (e.g. ``model``, ``temperature``).

    Returns
    -------
    dict with keys ``summary``, ``details``, ``per_agent``, ``status``.
    """
    start = time.time()
    chosen: List[str] = sub_agents or _pick_sub_agents(task)
    per_agent: Dict[str, Dict[str, Any]] = {}
    results: List[Dict[str, Any]] = []

    # Launch each sub‑agent concurrently (but respect timeout)
    async def run_one(name: str) -> Dict[str, Any]:
        agent = _resolve_sub_agent(name)
        log.info("Orchestrating sub‑agent %s", name)
        try:
            # --- simulate a sub‑agent call --------------------------------
            # In the real system this would invoke a sub‑process or a
            # separate Yousini instance with a narrowed prompt.
            # Here we just run a lightweight inline "tool" for demo.
            result = await _simulate_sub_agent(agent, task, **kwargs)
            # ----------------------------------------------------------------
            per_agent[name] = {"status": "ok", "result": result}
            return {"agent": name, "result": result}
        except Exception as exc:  # pylint: disable=broad-except
            per_agent[name] = {"status": "error", "message": str(exc)}
            return {"agent": name, "error": str(exc)}

    # Gather coroutines and wait with a hard timeout
    coros = [run_one(name) for name in chosen]
    try:
        gathered = await asyncio.wait_for(
            asyncio.gather(*coros, return_exceptions=False),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return {
            "summary": "Orchestration timed out",
            "details": f"Timeout after {timeout}s for task: {task[:60]}…",
            "per_agent": {name: {"status": "timeout"} for name in chosen},
            "status": "timeout",
        }

    # Aggregate
    per_agent_summaries: Dict[str, Dict[str, Any]] = {}
    for entry in gathered:
        if "error" in entry:
            agent_name = entry.get("agent", "unknown")
            per_agent_summaries[agent_name] = {"status": "error", "message": entry.get("error", "unknown error")}
            results.append({"agent": agent_name, "error": entry.get("error", "unknown error")})
        else:
            agent_name = entry.get("agent", "unknown")
            r = entry.get("result", "no result")
            per_agent_summaries[agent_name] = {"status": "ok", "result": str(r)[:120]}
            results.append({"agent": agent_name, "result": str(r)})

    # Build a simple summary from per‑agent outputs
    summary_parts: List[str] = []
    for agent_name, info in per_agent_summaries.items():
        r = info.get("result", "no result")
        s = info.get("status", "?")
        summary_parts.append(f"[{agent_name}]: {str(r)[:120]} (status: {s})")

    summary = " | ".join(summary_parts) if summary_parts else "no output"

    elapsed = time.time() - start
    return {
        "summary": summary,
        "details": "\n".join(
            f"{agent_name}: {info.get('status', '?')}" for agent_name, info in per_agent_summaries.items()
        ),
        "per_agent": per_agent_summaries,
        "status": "ok" if all(info.get("status") == "ok" for info in per_agent_summaries.values()) else "partial",
        "elapsed_seconds": round(elapsed, 2),
    }


# ---------------------------------------------------------------------------
# Internal: resolve a sub‑agent spec (placeholder – real impl loads skills)


def _resolve_sub_agent(name: str) -> Dict[str, Any]:
    """Return a minimal sub‑agent spec.

    In a full implementation this would load a skill or plugin profile.
    """
    return {"name": name, "role": name, "tools": []}


async def _simulate_sub_agent(agent: Dict[str, Any], task: str, **kwargs: Any) -> str:
    """Placeholder: in production this would invoke a real sub‑agent.

    For now we just echo a canned response so the orchestrator works
    end‑to‑end without needing separate processes.
    """
    await asyncio.sleep(0.1)
    return f"[sub‑agent {agent['name']}] handled: {task[:80]}…"


# ---------------------------------------------------------------------------
# Tool schema constant – used by yousini.py to register in TOOLS

ORCHESTRATE_TOOL = {
    "type": "function",
    "function": {
        "name": "orchestrate",
        "description": "มอบหมายงานไปยังตัวแจนต์ย่อยหลายตัวและรวมผลลัพธ์",
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "รายละเอียดงานที่ต้องการให้ตัวแจนต์ย่อยรัน",
                },
                "sub_agents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "ชื่อตัวแจนต์ย่อย (เว้นแต่ให้ระบบจัดอัตโนมัติ)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "เวลาที่ใช้สูงสุด (วินาที)",
                },
            },
            "required": ["task"],
        },
    },
}


# ---------------------------------------------------------------------------
# REPL / CLI helpers (wired in yousini.py)


def _repl_orchestrate(user_input: str, agent) -> Optional[str]:
    """Handle ``/orchestrate <task>`` in REPL."""
    parts = user_input[len("/orchestrate"):].strip().split(" ", 1)
    if not parts[0]:
        return "ใช้: /orchestrate <รายละเอียดงาน> [--agents agent1 agent2] [--timeout N]"
    task = parts[0]
    agents_arg = parts[1] if len(parts) > 1 else ""
    agents: List[str] = []
    timeout = 300
    if agents_arg:
        agents = [a.strip() for a in agents_arg.split() if a.strip()]
    import anyio

    try:
        result = anyio.run(
            lambda: orchestrate_task(task, sub_agents=agents, timeout=timeout)
        )
        summary = result.get("summary", "no output")
        status = result.get("status", "?")
        return f"สรุป: {summary[:200]}… (สถานะ: {status})"
    except Exception as e:
        return f"orchestrate error: {e}"


def _cli_orchestrate(argv: List[str], opts: Dict[str, Any]) -> str:
    """Handle ``yousini orchestrate <task> [options]`` from CLI."""
    if not argv:
        return "usage: yousini orchestrate <task> [--agents agent1 agent2] [--timeout N]"
    task = argv[0]
    agents: List[str] = []
    timeout = 300
    i = 1
    while i < len(argv):
        if argv[i] == "--agents":
            i += 1
            while i < len(argv) and not argv[i].startswith("--"):
                agents.append(argv[i])
                i += 1
        elif argv[i] == "--timeout":
            i += 1
            if i < len(argv):
                timeout = int(argv[i])
        i += 1
    import anyio

    result = anyio.run(
        lambda: orchestrate_task(task, sub_agents=agents, timeout=timeout)
    )
    return str(result)