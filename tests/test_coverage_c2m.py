# -*- coding: utf-8 -*-
"""C2 round 11: CLI main() subcommands + REPL command branches (missed 4058-4932)."""
import os
import sys
import time
import socket
import threading
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.console import Console
import yousini
import yousini_scaffold
import yousini_git


def _run_main(argv, inputs=None, env_extra=None):
    """run yousini.main() with argv + mocked input()"""
    env = os.environ.copy()
    env["YOUSINI_API_KEY"] = "fake"
    env["YOUSINI_DISABLE_NETWORK"] = "1"
    tmp = env_extra or {}
    for k, v in tmp.items():
        env[k] = v
    for k, v in env.items():
        os.environ[k] = v
    saved_argv = sys.argv
    sys.argv = ["yousini", *argv]
    fake_console = mock.MagicMock()
    with mock.patch.object(yousini, "console", fake_console), \
         mock.patch.object(yousini, "_usage_enabled", lambda: False, create=True) if not hasattr(yousini, "_usage_enabled") else mock.patch.object(yousini, "_usage_enabled", lambda: False), \
         mock.patch.object(yousini, "_sponsor_line", lambda cfg: "", create=True) if not hasattr(yousini, "_sponsor_line") else mock.patch.object(yousini, "_sponsor_line", lambda cfg: ""):
        if inputs is not None:
            it = iter(inputs)
            with mock.patch("builtins.input", lambda p="": next(it)):
                yousini.main()
        else:
            yousini.main()
    sys.argv = saved_argv
    for k in tmp:
        os.environ.pop(k, None)
    return fake_console


def test_cli_version_serve_banner_and_connect_help(monkeypatch, tmp_path):
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "_usage_enabled", lambda: False, raising=False)
    monkeypatch.setattr(yousini, "_sponsor_line", lambda cfg: "", raising=False)
    monkeypatch.setattr(yousini, "atexit", mock.MagicMock())
    # --version
    sys.argv = ["yousini", "--version"]
    yousini.main()
    # connect with no targets -> usage error
    sys.argv = ["yousini", "connect"]
    yousini.main()
    # serve: boot then KeyboardInterrupt -> banner + shutdown branch
    port = socket.socket()
    port.bind(("127.0.0.1", 0))
    p = port.getsockname()[1]
    port.close()
    monkeypatch.setattr(yousini, "serve_main", mock.MagicMock(side_effect=KeyboardInterrupt))
    sys.argv = ["yousini", "serve", "--port", str(p), "--token", "t1"]
    try:
        yousini.main()
    except KeyboardInterrupt:
        pass


def test_cli_subcommands_scaffold_pr_mcp(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "_usage_enabled", lambda: False, raising=False)
    monkeypatch.setattr(yousini, "_sponsor_line", lambda cfg: "", raising=False)
    monkeypatch.setattr(yousini, "atexit", mock.MagicMock())
    # scaffold with too few args -> usage
    sys.argv = ["yousini", "scaffold", "web"]
    yousini.main()
    # scaffold with enough args
    monkeypatch.setattr(yousini_scaffold, "scaffold",
                        mock.MagicMock(return_value="สร้างโครงแล้ว"))
    sys.argv = ["yousini", "scaffold", "web", "proj1"]
    yousini.main()
    # pr list
    monkeypatch.setattr(yousini_git, "pr_list", mock.MagicMock(return_value="PR list"))
    sys.argv = ["yousini", "pr", "list"]
    yousini.main()
    # pr create
    monkeypatch.setattr(yousini_git, "create_pr", mock.MagicMock(return_value="PR สร้างแล้ว"))
    sys.argv = ["yousini", "pr", "new-feature", "desc"]
    yousini.main()
    # mcp-* subcommands delegate to mcp_main() (mocked to avoid stdin read)
    monkeypatch.setattr(yousini, "mcp_main", mock.MagicMock(), raising=False)
    sys.argv = ["yousini", "mcp", "mcp-list"]
    yousini.main()
    sys.argv = ["yousini", "mcp", "mcp-add", "wiki", "python wiki_mcp.py"]
    yousini.main()
    sys.argv = ["yousini", "mcp", "mcp-rm", "wiki"]
    yousini.main()


def test_cli_marketplace_and_team(monkeypatch, tmp_path):
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "_usage_enabled", lambda: False, raising=False)
    monkeypatch.setattr(yousini, "_sponsor_line", lambda cfg: "", raising=False)
    monkeypatch.setattr(yousini, "atexit", mock.MagicMock())
    with mock.patch("yousini_marketplace.marketplace_enabled", return_value=True), \
         mock.patch("yousini_marketplace.search_catalog", return_value=[]), \
         mock.patch("yousini_marketplace.installed_list", return_value=[]), \
         mock.patch("yousini_marketplace.registry_url", return_value="r"), \
         mock.patch("yousini_marketplace.install", return_value={"ok": True, "id": "p1", "name": "p1", "version": "1.0", "skills": [], "mcp": []}), \
         mock.patch("yousini_marketplace.update", return_value={"ok": True, "id": "p1", "version": "2.0"}), \
         mock.patch("yousini_marketplace.update_all", return_value=[{"ok": True, "id": "p1", "version": "2.0"}]), \
         mock.patch("yousini_marketplace.uninstall", return_value={"ok": True, "id": "p1", "removed_skills": 1, "mcp_removed": 0}), \
         mock.patch("yousini_marketplace.pkg_info", return_value={"id": "p1"}), \
         mock.patch("yousini_marketplace.format_info", return_value="info"):
        # help
        sys.argv = ["yousini", "marketplace"]
        yousini.main()
        # search
        sys.argv = ["yousini", "marketplace", "search", "x"]
        yousini.main()
        # installed
        sys.argv = ["yousini", "marketplace", "installed"]
        yousini.main()
        # install + update + info
        sys.argv = ["yousini", "marketplace", "install", "p1"]
        yousini.main()
        sys.argv = ["yousini", "marketplace", "update", "p1"]
        yousini.main()
        sys.argv = ["yousini", "marketplace", "info", "p1"]
        yousini.main()
        # unknown cmd -> usage
        sys.argv = ["yousini", "marketplace", "nope"]
        yousini.main()
    # team status
    monkeypatch.setattr(yousini, "load_config",
                        mock.MagicMock(return_value={"users": []}), raising=False)
    sys.argv = ["yousini", "team", "status"]
    yousini.main()
    # team without args -> default status
    sys.argv = ["yousini", "team"]
    yousini.main()
    # team else -> usage
    sys.argv = ["yousini", "team", "nope"]
    yousini.main()


def test_cli_agent_queue_and_worker(monkeypatch, tmp_path):
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "_usage_enabled", lambda: False, raising=False)
    monkeypatch.setattr(yousini, "_sponsor_line", lambda cfg: "", raising=False)
    monkeypatch.setattr(yousini, "atexit", mock.MagicMock())
    monkeypatch.setattr(yousini, "_read_cfg_light", lambda: {}, raising=False)
    monkeypatch.setattr(yousini, "save_config", lambda c: None, raising=False)
    with mock.patch("yousini_queue.enqueue", return_value={"id": "t1", "status": "pending"}), \
         mock.patch("yousini_queue.get", return_value={"id": "t1", "status": "done", "result": "ok"}), \
         mock.patch("yousini_queue.counts", return_value={"pending": 0, "running": 0, "done": 1, "failed": 0}), \
         mock.patch("yousini_queue.list_tasks", return_value=[]), \
         mock.patch("yousini_queue.format_task", return_value="task t1"), \
         mock.patch("yousini_queue.format_queue", return_value="queue"), \
         mock.patch("yousini_queue.process_once", return_value=[{"id": "t1", "status": "done", "result": "x"}]), \
         mock.patch("yousini_queue.claim", return_value={"id": "t1"}), \
         mock.patch("yousini_queue.complete", return_value={"id": "t1", "status": "done"}), \
         mock.patch("yousini_queue.fail", return_value={"id": "t1", "status": "failed"}), \
         mock.patch("yousini_queue.requeue", return_value={"id": "t1"}), \
         mock.patch("yousini_queue.reclaim_stale", return_value=None):
        # agent send
        sys.argv = ["yousini", "agent", "send", "w1", "do work"]
        yousini.main()
        # agent result
        sys.argv = ["yousini", "agent", "result", "t1"]
        yousini.main()
        # agent status
        sys.argv = ["yousini", "agent", "status"]
        yousini.main()
        # agent else -> usage
        sys.argv = ["yousini", "agent"]
        yousini.main()
        # work --once
        sys.argv = ["yousini", "work", "--once"]
        yousini.main()
        # work no args -> loop (mock to avoid hanging)
        monkeypatch.setattr(yousini, "work_main", mock.MagicMock(), raising=False)
        sys.argv = ["yousini", "work"]
        yousini.main()


def test_cli_theme_login_permission_webhook_telegram_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "_usage_enabled", lambda: False, raising=False)
    monkeypatch.setattr(yousini, "_sponsor_line", lambda cfg: "", raising=False)
    monkeypatch.setattr(yousini, "atexit", mock.MagicMock())
    monkeypatch.setattr(yousini, "load_config",
                        mock.MagicMock(return_value={"theme": "dark"}), raising=False)
    monkeypatch.setattr(yousini, "save_config", lambda c: None, raising=False)
    # theme show selector (unknown name)
    sys.argv = ["yousini", "theme", "bogus"]
    yousini.main()
    # theme valid
    sys.argv = ["yousini", "theme", "dark"]
    yousini.main()
    # permission (CLI)
    sys.argv = ["yousini", "permission"]
    yousini.main()
    sys.argv = ["yousini", "permission", "status"]
    yousini.main()
    # webhook-list empty
    sys.argv = ["yousini", "webhook-list"]
    yousini.main()
    # webhook-add + rm
    sys.argv = ["yousini", "webhook-add", "hook1", "echo hi", "--cwd", "/tmp", "--callback", "http://x"]
    yousini.main()
    sys.argv = ["yousini", "webhook-list"]
    yousini.main()
    sys.argv = ["yousini", "webhook-rm", "hook1"]
    yousini.main()
    # telegram no token -> usage
    sys.argv = ["yousini", "telegram"]
    yousini.main()
    # profile show
    sys.argv = ["yousini", "profile"]
    yousini.main()
    # profile set + back to default
    sys.argv = ["yousini", "profile", "dev"]
    yousini.main()
    sys.argv = ["yousini", "profile", "default"]
    yousini.main()


def test_cli_cron_resume_and_chat_argv(monkeypatch, tmp_path):
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "_usage_enabled", lambda: False, raising=False)
    monkeypatch.setattr(yousini, "_sponsor_line", lambda cfg: "", raising=False)
    monkeypatch.setattr(yousini, "atexit", mock.MagicMock())
    monkeypatch.setattr(yousini, "_read_cfg_light", lambda: {}, raising=False)
    monkeypatch.setattr(yousini, "save_config", lambda c: None, raising=False)
    with mock.patch("yousini_cron.JobStore") as js_cls, \
         mock.patch("yousini_cron.run_due_jobs", return_value=[]):
        store = mock.MagicMock()
        store.list.return_value = []
        js_cls.return_value = store
        # cron --once
        sys.argv = ["yousini", "cron", "--once"]
        yousini.main()
        # resume: no last session -> default name
        monkeypatch.setattr(yousini, "SessionStore",
                            mock.MagicMock(return_value=store), raising=False)
        monkeypatch.setattr(yousini, "Agent", mock.MagicMock(), raising=False)
        monkeypatch.setattr(yousini, "_run_repl", mock.MagicMock(), raising=False)
        sys.argv = ["yousini", "resume"]
        yousini.main()
    # argv chat -> chat_turn
    agent = mock.MagicMock()
    monkeypatch.setattr(yousini, "Agent", mock.MagicMock(return_value=agent), raising=False)
    monkeypatch.setattr(yousini, "chat_turn", mock.MagicMock(), raising=False)
    sys.argv = ["yousini", "สวัสดีครับ"]
    yousini.main()


def test_repl_commands(monkeypatch, tmp_path):
    """run _run_repl with mocked input + mocked command handlers -> cover REPL branches."""
    monkeypatch.setattr(yousini, "console", mock.MagicMock())
    monkeypatch.setattr(yousini, "_usage_enabled", lambda: False, raising=False)
    monkeypatch.setattr(yousini, "_sponsor_line", lambda cfg: "", raising=False)
    monkeypatch.setattr(yousini, "atexit", mock.MagicMock())
    monkeypatch.setattr(yousini, "load_config",
                        mock.MagicMock(return_value={"theme": "dark"}), raising=False)
    monkeypatch.setattr(yousini, "save_config", lambda c: None, raising=False)
    monkeypatch.setattr(yousini, "_read_cfg_light", lambda: {}, raising=False)
    agent = mock.MagicMock()
    agent.messages = [{"role": "system", "content": "s"}]
    agent.cwd = str(tmp_path)
    agent.set_cwd.return_value = str(tmp_path)
    agent.compact.return_value = "compacted"
    agent.checkpoint.return_value = ""
    agent.refresh_context.return_value = None
    agent.plugin_list_tool.return_value = "plugins"
    agent.session_export_tool.return_value = "export ok"
    agent.session_import_tool.return_value = "import ok"
    agent.update_tool.return_value = "update ok"
    agent.git_pr_tool.return_value = "pr ok"
    agent.scaffold_tool.return_value = "scaffold ok"
    agent.dev_check_tool.return_value = "dev ok"
    agent.jobs.summary.return_value = "jobs"
    agent.skills = []
    agent.context_text = ""
    monkeypatch.setattr(yousini, "_print_banner", lambda a: None)
    monkeypatch.setattr(yousini, "_setup_readline", lambda: None)
    monkeypatch.setattr(yousini, "_ui_cmd_hints", lambda: None)
    monkeypatch.setattr(yousini, "_print_session_summary", lambda: None)
    monkeypatch.setattr(yousini, "_ui_user", lambda x: None)
    monkeypatch.setattr(yousini, "_ui_palette", mock.MagicMock(return_value=("/help", "h")))
    monkeypatch.setattr(yousini, "chat_turn", mock.MagicMock())
    monkeypatch.setattr(yousini, "login_mode", mock.MagicMock())
    monkeypatch.setattr(yousini, "plan_mode", mock.MagicMock())
    monkeypatch.setattr(yousini, "_usage_set_enabled", mock.MagicMock())
    monkeypatch.setattr(yousini, "_usage_reset", mock.MagicMock())
    monkeypatch.setattr(yousini, "_usage_report", mock.MagicMock(return_value="report"))
    monkeypatch.setattr(yousini, "_set_ads", mock.MagicMock())
    monkeypatch.setattr(yousini, "_sponsor_status", mock.MagicMock(return_value="ads"))
    monkeypatch.setattr(yousini, "_format_tier", mock.MagicMock(return_value="tier"))
    monkeypatch.setattr(yousini, "_billing_tier_info", mock.MagicMock(return_value={
        "label": "Pro", "tier": "pro", "price": 10, "license_key": "LK",
        "entitlements": {"marketplace": True}}))
    monkeypatch.setattr(yousini, "_billing_activate", mock.MagicMock(return_value=(True, "ok")))
    monkeypatch.setattr(yousini, "_billing_deactivate", mock.MagicMock(return_value="off"))
    monkeypatch.setattr(yousini, "_repl_market", mock.MagicMock())
    monkeypatch.setattr(yousini, "permission_cmd", mock.MagicMock(return_value="perm"))
    monkeypatch.setattr(yousini, "_print_help", lambda: None)
    monkeypatch.setattr(yousini, "_print_history", lambda a: None)
    monkeypatch.setattr(yousini, "_print_skills", lambda a: None)
    monkeypatch.setattr(yousini, "_print_hooks", lambda a: None)
    monkeypatch.setattr(yousini, "_symbols_cmd", mock.MagicMock())
    monkeypatch.setattr(yousini, "_git_cmd", mock.MagicMock())
    monkeypatch.setattr(yousini, "_cron_cmd", mock.MagicMock())
    monkeypatch.setattr(yousini, "_print_colored_diff", mock.MagicMock())
    monkeypatch.setattr(yousini, "_print_file_diff", mock.MagicMock())
    store = mock.MagicMock()
    store.list.return_value = [{"name": "s1", "turns": 5, "saved_at": "2026-01-01"}]
    store.search.return_value = [{"session": "s1", "saved_at": "2026-01-01T00:00:00",
                                  "role": "assistant", "snippet": "hi"}]
    store.load.return_value = {"messages": [{"role": "user", "content": "x"}], "meta": {"model": "m"}}
    store.save.return_value = str(tmp_path / "s.json")
    monkeypatch.setattr(yousini, "SessionStore",
                        mock.MagicMock(return_value=store), raising=False)
    with mock.patch("yousini_queue.enqueue") as qe, \
         mock.patch("yousini_queue.get") as qg, \
         mock.patch("yousini_queue.counts") as qc, \
         mock.patch("yousini_queue.list_tasks") as ql, \
         mock.patch("yousini_queue.format_task") as qft, \
         mock.patch("yousini_queue.format_queue") as qfq, \
         mock.patch("yousini_queue.process_once") as qpo:
        qe.return_value = {"id": "t1", "status": "pending"}
        qg.return_value = {"id": "t1", "status": "done", "result": "ok"}
        qc.return_value = {"pending": 0, "running": 0, "done": 1, "failed": 0}
        ql.return_value = []
        qft.return_value = "t1"
        qfq.return_value = "q"
        qpo.return_value = [{"id": "t1", "status": "done", "result": "r"}]
        inputs = [
            "",                          # empty -> continue
            "/stream on",                # stream on
            "/stream",                   # stream status
            "/palette",                  # palette
            "/help",                     # help
            "/clear",                    # clear
            "/history",                  # history
            "/skills",                   # skills
            "/hooks",                    # hooks
            "/todos",                    # todos
            "/jobs",                     # jobs
            "/quiet",                    # quiet on
            "/model gemini-pro",         # model
            "/cwd /tmp",                 # cwd
            "/approve on",               # approve
            "/checkpoint",               # checkpoint
            "/compact",                  # compact
            "/usage on",                 # usage on
            "/usage off",                # usage off
            "/usage reset",              # usage reset
            "/usage report",             # usage report
            "/usage report monthly",     # usage report period
            "/ads on",                   # ads on
            "/ads off",                  # ads off
            "/ads status",               # ads status
            "/tier",                     # tier
            "/tier activate K123",       # tier activate
            "/tier off",                 # tier off
            "/market",                   # market
            "/market search ai",         # market search
            "/team",                     # team
            "/agent",                    # agent status
            "/agent send w1 do",         # agent send
            "/agent result t1",          # agent result
            "/work",                     # work
            "/reload",                   # reload
            "/rollback",                 # rollback
            "/diff",                     # diff
            "/diff yousini.py",          # diff path
            "/sessions",                 # sessions
            "/search ข่าว",              # search
            "/save my1",                 # save
            "/load my1",                 # load
            "/symbols",                  # symbols
            "/symbols def foo",          # symbols find
            "/git",                      # git
            "/git log 5",                # git log
            "/git blame f.py 10",        # git blame
            "/cron",                     # cron
            "/pr",                       # pr usage
            "/pr list",                  # pr list
            "/pr feat",                  # pr create
            "/scaffold",                 # scaffold usage
            "/scaffold web proj1",       # scaffold
            "/dev",                      # dev
            "/plugins",                  # plugins
            "/export s1",                # export
            "/export s1 --md --out x.md",# export md
            "/import x.json --name y",   # import
            "/update",                   # update
            "/config",                   # config
            "/flag",                     # flag
            "/workflow",                 # workflow
            "/permission allow *",       # permission
            "/img pic.png What is it?",  # img (chat_turn)
            "/plan",                     # plan
            "Hello agent",               # plain chat -> chat_turn + auto-save
            "/exit",                     # exit
        ]
        it = iter(inputs)
        with mock.patch("builtins.input", lambda p="": next(it)):
            yousini._run_repl(agent)
