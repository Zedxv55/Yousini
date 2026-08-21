# -*- coding: utf-8 -*-
"""ทดสอบ UI rendering (yousini_ui) + REPL command routing + interactive components"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ต้องตั้ง env ก่อน import โมดูล (เหมือน test อื่น ๆ)
os.environ.setdefault("YOUSINI_API_KEY", "dummy-test-key")
os.environ.setdefault("YOUSINI_BASE_URL", "https://api.openai.com/v1")
os.environ.setdefault("YOUSINI_MODEL", "gpt-4o")

import pytest
from unittest import mock

import yousini
from yousini_ui import (
    get_theme, set_theme, _truncate, _width,
    welcome_banner, user_bubble, answer_panel, tool_call, tool_result,
    status_hud, error_box, warn_box, section, cmd_hints, ok_line, cancel_line,
)
from yousini_interactive import (
    _fuzzy_score, command_palette, typewriter_md, TypewriterStream, ProgressBars,
)
from io import StringIO
from rich.console import Console as FakeConsole

import yousini_ui as _ui_mod
import yousini_interactive as _ix_mod


# ---------------------------------------------------------------- ui basics


def test_themes_all_loadable():
    """ทุกธีมโหลดได้ + มี key มาตรฐานครบ"""
    required = {"answer", "think", "tool", "tool_args", "result", "warn", "err"}
    for name in ("dark", "nord", "tokyo-night", "notion"):
        set_theme(name)
        t = get_theme()
        assert isinstance(t, dict)
        assert required.issubset(t.keys()), f"theme {name} missing {required - set(t)}"
    set_theme("dark")  # restore default


def test_truncate():
    assert _truncate("abc", 5) == "abc"
    assert _truncate("abcdef", 4) == "abc…"  # ตัดท้าย + …
    assert _truncate(123, 4) == "123"  # non-str passthrough


def test_width_nonnegative():
    assert _width() >= 0


def test_welcome_banner_returns_renderable():
    panel = welcome_banner()
    # จอใหญ → welcome_banner พิมพลง console โดยตรง (ไฟล test ไมใช tty ไมพิมพ)
    assert panel is None or hasattr(panel, "render")


def test_bubble_user_text(monkeypatch):
    """user_bubble ต้องมีข้อความผู้ใชใน console output"""
    buf = StringIO()
    fake = FakeConsole(file=buf, width=60, color_system=None)
    monkeypatch.setattr(_ui_mod, "console", fake)
    user_bubble("สวัสดี")
    assert "สวัสดี" in buf.getvalue()


def test_tool_call_and_result(monkeypatch):
    buf = StringIO()
    fake = FakeConsole(file=buf, width=60, color_system=None)
    monkeypatch.setattr(_ui_mod, "console", fake)
    t = tool_call("shell", {"cmd": "ls"})
    assert hasattr(t, "plain")
    tool_result("shell", "a b c")
    text = buf.getvalue()
    assert "shell" in text and "a b c" in text


def test_status_hud_returns_text():
    class _FakeAgent:
        model = "test-model"
        turns = 5
        tokens = 100
        messages = ["m1", "m2"]
        usage = {"prompt_tokens": 100, "completion_tokens": 50}
        cwd = "/tmp/proj"
    status_hud(_FakeAgent())  # ไม crash = ผ่าน


def test_error_and_warn_boxes(monkeypatch):
    buf = StringIO()
    fake = FakeConsole(file=buf, width=60, color_system=None)
    monkeypatch.setattr(_ui_mod, "console", fake)
    error_box("err-msg")
    warn_box("warn-msg")
    text = buf.getvalue()
    assert "err-msg" in text and "warn-msg" in text


def test_section_and_hints():
    t = section("test")
    assert t is not None  # section คืน Rule (render แล้วทันทีผ่าน console)
    panel = cmd_hints()
    assert panel is None or hasattr(panel, "render")


def test_ok_and_cancel_lines(monkeypatch, capsys):
    ok_line("done")
    cancel_line()
    out = capsys.readouterr().out
    assert "done" in out and "ยกเลิก" in out


# ------------------------------------------------- interactive components


def test_fuzzy_score():
    assert _fuzzy_score("pa", "palette") >= 0
    assert _fuzzy_score("xyz", "palette") < 0
    assert _fuzzy_score("pal", "palette") > _fuzzy_score("xyz", "palette")


def test_command_palette_fallback_non_tty(monkeypatch):
    """ไมใช tty → command_palette แจงรายการแลว fallback อ่าน input ปกติ"""
    monkeypatch.setattr("yousini_interactive.sys.stdin",
                        mock.MagicMock(isatty=mock.MagicMock(return_value=False)),
                        raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt="": "help")
    entries = [("/help", "ช่วยเหลือ"), ("/exit", "ออก")]
    res = command_palette(entries, prefill="help")
    # fallback: ตรง pick → คืน entry; ไมตรง → None
    assert res is None or res == ("/help", "ช่วยเหลือ")


def test_command_palette_enter_selection(monkeypatch):
    """_read_key ส่ง enter → เลือก entry ที่ selection ปัจจุบัน"""
    keys = iter(["enter"])
    monkeypatch.setattr(_ix_mod, "_read_key", lambda: (next(keys), 0))
    monkeypatch.setattr("yousini_interactive.sys.stdin",
                        mock.MagicMock(isatty=mock.MagicMock(return_value=True)),
                        raising=False)
    entries = [("/help", "ช่วยเหลือ"), ("/clear", "ลบ")]
    res = command_palette(entries)
    assert res in entries


def test_typewriter_md_fails_open(monkeypatch, capsys):
    """ไม่มี tty หรือ rich ขาดหาย → ตกไปพิมพ์ Markdown แบบธรรมดา"""
    monkeypatch.setattr("yousini_interactive.sys.stdin",
                        mock.MagicMock(isatty=mock.MagicMock(return_value=False)),
                        raising=False)
    typewriter_md("hello **world**")
    out = capsys.readouterr().out
    assert "world" in out


def test_typewriter_stream_noop_off_tty(monkeypatch):
    ts = TypewriterStream()
    monkeypatch.setattr("yousini_interactive.sys.stdin",
                        mock.MagicMock(isatty=mock.MagicMock(return_value=False)),
                        raising=False)
    ts.start()
    assert ts._started is False


def test_progress_bars_class(monkeypatch):
    pb = ProgressBars()
    monkeypatch.setattr("yousini_interactive.sys.stdin",
                        mock.MagicMock(isatty=mock.MagicMock(return_value=False)),
                        raising=False)
    pb.start()
    assert pb._started is False
    bid = pb.new("compile", total=10)
    pb.advance(bid, 5)
    pb.stop()


# ------------------------------------------------- REPL command routing


def _make_agent(tmp_path, monkeypatch):
    """สร้าง Agent จำลองโดยไม่ต้องต่อ API"""
    monkeypatch.setenv("YOUSINI_CONFIG_FILE", str(tmp_path / "config.json"))
    agent = yousini.Agent.__new__(yousini.Agent)
    agent.cwd = str(tmp_path)
    agent.messages = [{"role": "system", "content": "test"}]
    agent.system_prompt = "test"
    agent.quiet_mode = False
    agent._typewriter = False
    agent.jobs = mock.MagicMock()
    agent.jobs.summary.return_value = "(ไม่มีงาน)"
    mem = mock.MagicMock()
    mem.stores = {"user": mock.MagicMock(), "agent": mock.MagicMock()}
    mem.stores["user"].to_text.return_value = ""
    mem.stores["agent"].to_text.return_value = ""
    agent.memory = mem
    agent.hooks = yousini.Hooks()
    return agent


def _run_repl_with(monkeypatch, tmp_path, inputs, **extra):
    it = iter(inputs)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(it))
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
    for k, v in extra.items():
        monkeypatch.setattr(yousini, k, v)
    agent = _make_agent(tmp_path, monkeypatch)
    yousini._run_repl(agent)
    return agent


def test_repl_empty_input_skips(tmp_path, monkeypatch):
    _run_repl_with(monkeypatch, tmp_path, ["", "/help", "/exit"])


def test_repl_stream_toggle(tmp_path, monkeypatch):
    agent = _run_repl_with(monkeypatch, tmp_path, [
        "/stream on", "/stream off", "/stream", "/exit",
    ])
    assert agent._typewriter is False  # /stream off ปิดท้ายสุด


def test_repl_clear_resets_history(tmp_path, monkeypatch):
    agent = _run_repl_with(monkeypatch, tmp_path, ["/clear", "/exit"])
    assert agent.messages == [{"role": "system", "content": "test"}]


def test_repl_quiet_toggle(tmp_path, monkeypatch):
    agent = _run_repl_with(monkeypatch, tmp_path, ["/quiet", "/quiet off", "/exit"])
    assert agent.quiet_mode is False


def test_repl_memory_no_args_prints(tmp_path, monkeypatch):
    _run_repl_with(monkeypatch, tmp_path, ["/memory", "/exit"])


def test_repl_memory_bad_args_warns(tmp_path, monkeypatch, capsys):
    _run_repl_with(monkeypatch, tmp_path, ["/memory bad", "/exit"])
    out = capsys.readouterr().out
    assert "add|remove" in out


def test_repl_jobs_usage(tmp_path, monkeypatch):
    agent = _run_repl_with(monkeypatch, tmp_path, ["/jobs", "/usage", "/exit"])
    agent.jobs.summary.assert_called()


def test_repl_help_clear_history_skills_hooks(tmp_path, monkeypatch):
    _run_repl_with(monkeypatch, tmp_path, [
        "/help", "/clear", "/history", "/skills", "/hooks", "/exit",
    ])


def test_repl_exit_and_quit(tmp_path, monkeypatch):
    _run_repl_with(monkeypatch, tmp_path, ["/quit"])
    _run_repl_with(monkeypatch, tmp_path, ["/exit"])


def test_repl_palette_fallback_when_no_tty(tmp_path, monkeypatch):
    """/palette เมื่อไม่มี tty → fallback เข้าคำสั่งที่ตรงหรือ skip"""
    monkeypatch.setattr(_ix_mod, "_read_key", lambda: None)
    _run_repl_with(monkeypatch, tmp_path, ["/palette", "/exit"])


def test_repl_eof_stops(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", mock.MagicMock(side_effect=EOFError))
    monkeypatch.setattr(yousini, "_print_banner", lambda a: None)
    monkeypatch.setattr(yousini, "_ui_cmd_hints", lambda: None)
    monkeypatch.setattr(yousini, "_setup_readline", lambda: None)
    monkeypatch.setattr(yousini, "atexit", mock.MagicMock())
    monkeypatch.setattr(yousini, "SessionStore", mock.MagicMock())
    agent = _make_agent(tmp_path, monkeypatch)
    yousini._run_repl(agent)  # ต้องจบโดยไม่ raise


def test_repl_commands_list_complete():
    cmds = yousini._REPL_COMMANDS(mock.MagicMock())
    names = {c[0] for c in cmds}
    for name in ("/help", "/clear", "/history", "/memory", "/palette",
                 "/stream", "/exit", "/usage", "/checkpoint", "/rollback"):
        assert name in names


def test_typewriter_stream_on_tty(monkeypatch):
    """preview จะเริ่มเมื่อมี token แรกเท่านั้น แล้วล้าง Live display หลังจบ"""
    import rich.live
    fake_live = mock.MagicMock()
    monkeypatch.setattr(rich.live, "Live", lambda *a, **kw: fake_live)
    monkeypatch.setattr("yousini_interactive.sys.stdin",
                        mock.MagicMock(isatty=mock.MagicMock(return_value=True)),
                        raising=False)
    ts = TypewriterStream()
    ts.start()
    assert ts._enabled is True
    assert ts._started is False
    fake_live.start.assert_not_called()
    ts.write("hello ")
    ts.write("world")
    ts.write("")  # token ว่าง → ข้าม
    ts.stop()
    assert ts._started is False
    fake_live.start.assert_called_once()
    fake_live.stop.assert_called_once()


def test_typewriter_stream_live_fail_still_works(monkeypatch):
    """สร้าง Live ไม่สำเร็จตอน token แรก → ปิด preview อย่างเงียบ ๆ และไม่ raise"""
    import rich.live
    monkeypatch.setattr(rich.live, "Live",
                        mock.MagicMock(side_effect=RuntimeError("no term")))
    monkeypatch.setattr("yousini_interactive.sys.stdin",
                        mock.MagicMock(isatty=mock.MagicMock(return_value=True)),
                        raising=False)
    ts = TypewriterStream()
    ts.start()
    assert ts._enabled is True
    ts.write("x")  # ไม่ raise
    assert ts._started is False
    assert ts._enabled is False
    ts.stop()


def test_typewriter_stream_ctx_manager(monkeypatch, capsys):
    """typewriter_stream() no-op บน non-tty — ก็เปิด/ปิด context ปลอดภัย"""
    monkeypatch.setattr("yousini_interactive.sys.stdin",
                        mock.MagicMock(isatty=mock.MagicMock(return_value=False)),
                        raising=False)
    with _ix_mod.typewriter_stream() as tw:
        tw.write("chunk")
    out = capsys.readouterr().out
    assert out == ""


def test_progress_bars_full_lifecycle(monkeypatch):
    """new/advance บน non-tty → auto start ไม่เข้า Live (fail-open)"""
    monkeypatch.setattr("yousini_interactive.sys.stdin",
                        mock.MagicMock(isatty=mock.MagicMock(return_value=False)),
                        raising=False)
    pb = ProgressBars()
    bid = pb.new("compile", total=10)
    assert isinstance(bid, int)
    pb.advance(bid, 5)
    pb.advance(bid, 5)
    pb.stop()


def test_read_key_posix_no_crash(monkeypatch):
    """_read_key บน posix ที่ไมใช tty (isatty=False) → ไม raise, ไม hang
    termios import ล่าช้า → mock ทั้ง sys + termios module"""
    monkeypatch.setattr("yousini_interactive.sys.platform", "linux", raising=False)
    fake_stdin = mock.MagicMock()
    fake_stdin.isatty.return_value = False
    monkeypatch.setattr("yousini_interactive.sys.stdin", fake_stdin)
    monkeypatch.setattr("sys.stdin", fake_stdin, raising=False)
    res = _ix_mod._read_key()
    assert res is None


def test_command_palette_navigate_and_esc(monkeypatch):
    """นำทางดวย arrow/esc — esc ยกเลิก"""
    import rich.live
    fake_live = mock.MagicMock()
    fake_live.__enter__ = mock.MagicMock(return_value=fake_live)
    fake_live.__exit__ = mock.MagicMock(return_value=False)
    monkeypatch.setattr(rich.live, "Live", lambda *a, **kw: fake_live)
    keys = iter(["down", "esc"])
    monkeypatch.setattr(_ix_mod, "_read_key", lambda: (next(keys), False))
    monkeypatch.setattr("yousini_interactive.sys.stdin",
                        mock.MagicMock(isatty=mock.MagicMock(return_value=True)),
                        raising=False)
    res = command_palette([("/help", "ช่วยเหลือ"), ("/clear", "ลบ")])
    assert res is None
    fake_live.__exit__.assert_called()  # context manager พิมพครบทุก step
    # down เลื่อน → esc ยกเลิก (ไมมการ print ผลลัพธ์)


def test_command_palette_enter_empty_query(monkeypatch):
    """query เปล่า แลว enter → ไมมรายการถูก filter → loop ตอ"""
    import rich.live
    fake_live = mock.MagicMock()
    monkeypatch.setattr(rich.live, "Live", lambda *a, **kw: fake_live)
    keys = iter(["enter", "back", "enter"])
    monkeypatch.setattr(_ix_mod, "_read_key", lambda: (next(keys), False))
    monkeypatch.setattr("yousini_interactive.sys.stdin",
                        mock.MagicMock(isatty=mock.MagicMock(return_value=True)),
                        raising=False)
    res = command_palette([("/help", "ช่วยเหลือ"), ("/clear", "ลบ")])
    assert res == ("/help", "ช่วยเหลือ")


def test_command_palette_ctrlc(monkeypatch):
    keys = iter(["ctrlc"])
    monkeypatch.setattr(_ix_mod, "_read_key", lambda: (next(keys), False))
    monkeypatch.setattr("yousini_interactive.sys.stdin",
                        mock.MagicMock(isatty=mock.MagicMock(return_value=True)),
                        raising=False)
    import rich.live
    fake_live = mock.MagicMock()
    monkeypatch.setattr(rich.live, "Live", lambda *a, **kw: fake_live)
    assert command_palette([("/help", "ช่วยเหลือ")]) is None


def test_typewriter_md_on_tty(monkeypatch):
    """isatty=True → ใช Live (context manager); เนื้อหา Markdown ถูกป้อน Live"""
    import rich.live
    fake_live = mock.MagicMock()
    fake_live.__enter__ = mock.MagicMock(return_value=fake_live)
    fake_live.__exit__ = mock.MagicMock(return_value=False)
    monkeypatch.setattr(rich.live, "Live", lambda *a, **kw: fake_live)
    monkeypatch.setattr("yousini_interactive.sys.stdin",
                        mock.MagicMock(isatty=mock.MagicMock(return_value=True)),
                        raising=False)
    typewriter_md("hello **world**")
    fake_live.__enter__.assert_called()
    fake_live.__exit__.assert_called()
    # ตรวจว่า Panel ที่ update มี Markdown renderable ต้นฉบับ "hello **world**"
    call_args = [c.args for c in fake_live.update.call_args_list]
    assert call_args, "expected live.update calls"
    panels = [a[0] for a in call_args if hasattr(a[0], "renderable")]
    assert panels, "expected Panel renderable"
    contents = [p.renderable.markup for p in panels if hasattr(p.renderable, "markup")]
    assert any("hello **world**" in c for c in contents)


def test_progress_bars_finish_auto_stops(monkeypatch):
    """finish(bar) → remove bar และ stop เมื่อไมเหลือ bar"""
    fake_live = mock.MagicMock()
    monkeypatch.setattr(_ix_mod, "Live", lambda *a, **kw: fake_live)
    monkeypatch.setattr("yousini_interactive.sys.stdin",
                        mock.MagicMock(isatty=mock.MagicMock(return_value=True)),
                        raising=False)
    pb = ProgressBars()
    bid = pb.new("compile", total=5)
    pb.advance(bid, 3, note="ok")
    pb.finish(bid, note="done")
    assert not pb._bars
    fake_live.stop.assert_called()


def test_progress_bars_advance_unknown_bar(monkeypatch):
    """advance/finish id ที่ไมมี → ไม raise"""
    monkeypatch.setattr("yousini_interactive.sys.stdin",
                        mock.MagicMock(isatty=mock.MagicMock(return_value=False)),
                        raising=False)
    pb = ProgressBars()
    pb.start()
    pb.advance(999, 1)
    pb.finish(999)
    pb.stop()

# ─────────────────────────── REPL completers (B1: auto-suggestion)
def test_repl_completer_typing_u_returns_usage_update():
    assert yousini._repl_completer("/u", 0) == "/usage"
    assert yousini._repl_completer("/u", 1) == "/undo"
    assert yousini._repl_completer("/u", 2) == "/update"
    assert yousini._repl_completer("/u", 3) is None


def test_repl_completer_exact_match_returns_single():
    assert yousini._repl_completer("/palette", 0) == "/palette"
    assert yousini._repl_completer("/palette", 1) is None


def test_repl_completer_no_match_returns_none():
    assert yousini._repl_completer("/zzz", 0) is None


def test_repl_completer_empty_prefix_lists_all_commands():
    """prompt เปล่า (กด Tab) → เสนอทุกคำสั่งที่เริ่มต้นด้วย /"""
    first = yousini._repl_completer("", 0)
    assert first.startswith("/")
    # ทุกค่าใน hints ต้องถูกเสนออย่างน้อยหนึ่ง state
    for cmd in yousini._REPL_HINTS:
        offered = any(yousini._repl_completer("", n) == cmd for n in range(40))
        assert offered, f"{cmd} ถูกเสนอเมื่อกด Tab ที่ prompt เปล่า"


def test_repl_completer_case_sensitive():
    """input /U ไมตรง — เป็นไปตามหลัก REPL (ตัวพิมพ์เล็ก)"""
    assert yousini._repl_completer("/U", 0) is None


def test_repl_hints_dict_covers_all_commands():
    cmds = {c[0] for c in yousini._REPL_COMMANDS(None)}
    assert set(yousini._REPL_HINTS) == cmds


def test_repl_completer_hints_fail_safe():
    """แสดง hints ไมควร raise แม้ console จะ error"""
    with mock.patch.object(yousini, "console") as fake_console:
        fake_console.print.side_effect = RuntimeError("boom")
        # ไม raise — wrapped in try/except
        yousini._repl_completer_hints("", ["/help"], 5)
