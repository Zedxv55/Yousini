#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
yousini_ui — Design System / Theme Engine ของ Terminal Yousini
==========================================
Design Principles
-----------------
1. Semantic colors: สีบอกความหมายเสมอ (C_THINK=เทา, C_TOOL=cyan, C_ANSWER=cyan,
   C_OK=เขียว, C_WARN=เหลือง, C_ERR=แดง) — ห้ามสับสนระหว่างสถานะ
2. Density on demand: ผู้ใช้ทั่วไปเห็นเฉพาะคำตอบ (user bubble vs AI answer panel)
   ข้อมูล tool/result จัดแบบ compact และสีก่อนหลังชัดเจน
3. Terminal-safe: ไม่มี dependency ใหม่ (rich ตัวเดิม) รันบน Windows conhost,
   iTerm, GNOME Terminal ได้ไม่พัง (ไม่ใช่ ANSI ตรง, ไม่ใช่ Live บน REPL spinner)
4. Fail-open: ถ้าทุกอย่างพัง (เช่น console width อ่านไม่ได้) ต้องแสดงเป็น plain text

Components
----------
- _welcome_banner(agent)      จอเปิด (ASCII art + HUD + คำแนะนำปุ่มลัด)
- _user_bubble(text)          ข้อความผู้ใช้ (bubble ขวา-ซ้าย จอใหญ่)
- _answer_panel(md_text)      คำตอบ AI (กรอบ cyan + subtitle model)
- _tool_call(name, args)      เรียกเครื่องมือ (tree connector + args มั้จม)
- _tool_result(name, text)    ผลลัพธ์เครื่องมือ (กรอบ dim)
- _error_box / _warn_box      กรอบข้อความผิดพลาด/คำเตือน
- _status_hud(agent)          แถบสถานะ: model · dir · tok · ข้อความ
- _cmd_hints()                แถวคำแนะนำปุ่มลัด (แทน /help)
- _section(label)             หัวข้อ section แบบ HUD
- _confirm(prompt)            คำถามยืนยันแบบ styled
- _stream_cursor()            cursor สตรีมมิงแบบ "..." ที่ไม่ block
- Theme dict (THEMES) รองรับ dark / nord / tokyo-night / notion
"""
import os
import sys
import json
from pathlib import Path

# ---- Rich imports (fail-open: ถ้า rich หายไป ใช้ fallback แบบ plain) ----
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from rich.table import Table
    from rich.rule import Rule
    _RICH_OK = True
except Exception:  # pragma: no cover
    _RICH_OK = False

# console เดียว (ใช้ร่วมกับ yousini.py)
console = Console() if _RICH_OK else None


# ============================================================
# Theme registry — 1 source of truth ของสีทั้งระบบ
# ============================================================
THEMES = {
    "dark": {
        "think": "grey58",          # กำลังคิด / ประมวลผล
        "tool": "bold cyan",        # การกระทำของ tool
        "tool_args": "grey66",      # อาร์กิวเมนต์ (มั้จม)
        "result": "grey66",         # ผลลัพธ์ tool
        "answer": "cyan",           # กรอบคำตอบ
        "answer_title": "bold white",
        "ok": "green",
        "warn": "yellow",
        "err": "bold red",
        "accent": "magenta",
        "prompt": "bold yellow",
        "dim": "dim",
        "bubble_user_bg": "rgb(30,42,60)",
        "hud_border": "bright_black",
    },
    "nord": {
        "think": "#7c8794",
        "tool": "bold #88c0d0",
        "tool_args": "#81a1c1",
        "result": "#d8dee9",
        "answer": "bold #88c0d0",
        "answer_title": "#eceff4",
        "ok": "#a3be8c",
        "warn": "#ebcb8b",
        "err": "bold #bf616a",
        "accent": "#b48ead",
        "prompt": "bold #ebcb8b",
        "dim": "dim",
        "bubble_user_bg": "rgb(59,66,82)",
        "hud_border": "bright_black",
    },
    "tokyo-night": {
        "think": "#565f89",
        "tool": "bold #7dcfff",
        "tool_args": "#a9b1d6",
        "result": "#a9b1d6",
        "answer": "bold #7dcfff",
        "answer_title": "#c0caf5",
        "ok": "#9ece6a",
        "warn": "#e0af68",
        "err": "bold #f7768e",
        "accent": "#bb9af7",
        "prompt": "bold #e0af68",
        "dim": "dim",
        "bubble_user_bg": "rgb(33,38,57)",
        "hud_border": "bright_black",
    },
    "notion": {
        "think": "grey46",
        "tool": "bold white",
        "tool_args": "grey70",
        "result": "grey70",
        "answer": "bold white",
        "answer_title": "white",
        "ok": "green",
        "warn": "yellow",
        "err": "bold red",
        "accent": "bold magenta",
        "prompt": "bold yellow",
        "dim": "dim",
        "bubble_user_bg": "rgb(55,55,55)",
        "hud_border": "white",
    },
}

# active theme — เดิมใช้ dark
_active_theme = "dark"

def get_theme() -> dict:
    return THEMES.get(_active_theme, THEMES["dark"])

def set_theme(name: str) -> str:
    """เปลี่ยน theme, คืนชื่อที่จริง (ถ้าชื่อไม่มี ค้างไว้ที่ theme เดิม — ไม่ reset ให้ dark)"""
    global _active_theme
    name = (name or "dark").strip().lower()
    if name in THEMES:
        _active_theme = name
    return _active_theme

# convenience constants (อ้างถึงสีใน code ต่อไปด้วย T["name"])
T = get_theme


def _width() -> int:
    try:
        cols = os.get_terminal_size(sys.stdout.fileno()).columns
    except Exception:
        cols = 80
    return max(78, cols)


def _truncate(s, n):
    if not isinstance(s, str):
        s = str(s) if s is not None else ""
    return s if len(s) <= n else s[:n - 1] + "…"


# ============================================================
# Welcome banner (จอเปิด)
# ============================================================
YOUSINI_ART = r"""
 __   __  _______  __   __  _______  ___   __    _  ___
|  | |  ||       ||  | |  ||       ||   | |  |  | ||   |
|  |_|  ||   _   ||  | |  ||  _____||   | |   |_| ||   |
|       ||  | |  ||  |_|  || |_____ |   | |       ||   |
|_     _||  |_|  ||       ||_____  ||   | |  _    ||   |
  |   |  |       ||       | _____| ||   | | | |   ||   |
  |___|  |_______||_______||_______||___| |_|  |__||___|
"""


def _gradient(text, colors):
    """ระบายสีไล่เฉดให้ตัวอักษร (ต่อบรรทัด)"""
    if not _RICH_OK:  # pragma: no cover
        return text
    out = Text()
    for line in text.split("\n"):
        n = max(len(line), 1)
        for i, ch in enumerate(line):
            c = colors[int(i / n * (len(colors) - 1))]
            out.append(ch, style=f"bold {c}")
        out.append("\n")
    return out


def welcome_banner(agent=None, *, extra_rows=None):
    """แสดงจอเปิด: ASCII art + HUD + คำแนะนำปุ่มลัด"""
    if not _RICH_OK:  # pragma: no cover
        print(YOUSINI_ART)
        print("Yousini — Local Coding Agent")
        return
    palette = ["#18d3ff", "#5ca8ff", "#7c5cff", "#b45cff", "#ff5cae"]
    console.print(_gradient(YOUSINI_ART, palette))

    rows = []
    if agent is not None:
        rows.append(("โมเดล", agent.model))
        rows.append(("โฟลเดอร์", agent.cwd))
        try:
            from yousini_git import is_repo, status_short
            if is_repo(agent.cwd):
                br = status_short(agent.cwd).splitlines()[0]
                rows.append(("git", br))
        except Exception:
            pass
    for k, v in (extra_rows or []):
        rows.append((k, v))

    w = _width()
    t = Table.grid(padding=(0, 2))
    t.add_column(style="bold cyan", justify="right", min_width=10)
    t.add_column(style="dim", max_width=w - 24)
    for k, v in rows:
        t.add_row("▸ " + k, v)

    console.print(Panel(
        t,
        border_style="cyan",
        padding=(1, 3),
        width=min(w, 92),
        title="[bold cyan]〔 ◈ CORE ONLINE 〕[/bold cyan]",
        subtitle="[dim]พิมพ์ /help เพื่อดูทุกคำสั่ง · /exit เพื่อออกจากแชท[/dim]",
    ))
    console.print()


# ============================================================
# Chat bubbles
# ============================================================
def user_bubble(text):
    """กล่องข้อความผู้ใช้ (สีจางกว่า AI ชัดเจน)"""
    if not _RICH_OK:  # pragma: no cover
        print(f"คุณ: {text}")
        return
    try:
        stamp = f"{datetime_now()} "
    except Exception:
        stamp = ""
    content = Text(stamp + text, style="default")
    console.print(Panel(
        content,
        border_style="bright_black",
        padding=(0, 1),
        width=min(_width(), 110),
        title="[bold white]คุณ[/bold white]",
        subtitle="[dim]user[/dim]",
    ))


def answer_panel(md_text, model=None):
    """กรอบคำตอบ AI — เน้นสี ตามหลัก semantic colors"""
    if not _RICH_OK:  # pragma: no cover
        print(md_text)
        return
    theme = get_theme()
    subtitle_text = Text(f" | {model}", style="dim") if model else None
    return Panel(
        Markdown(md_text),
        border_style=theme["answer"],
        title="[bold cyan]Yousini[/bold cyan]",
        subtitle=subtitle_text,
        padding=(0, 1),
        width=min(_width(), 118),
    )


# import ภายใน function เพื่อไม่ crash ที่ module load
try:
    from rich.markdown import Markdown  # noqa: E402
except Exception:  # pragma: no cover
    Markdown = None


# ============================================================
# Tool call / result
# ============================================================
def tool_call(name, args_shown):
    """บรรทัดเรียกเครื่องมือ — tree connector + args มั้จม"""
    if not _RICH_OK:  # pragma: no cover
        print(f"⏺ {name} {_truncate(args_shown, 200)}")
        return Text()
    theme = get_theme()
    if isinstance(args_shown, str):
        shown = args_shown
    else:
        shown = json.dumps(args_shown, ensure_ascii=False)
    t = Text()
    t.append("┣━ ", style="bright_black")
    t.append("⏺ ", style=theme["tool"])
    t.append(name, style=theme["tool"])
    t.append(f"({_truncate(shown, 200)})", style=theme["tool_args"])
    return t


def tool_result(name, text):
    """ผลลัพธ์เครื่องมือ — กรอบ dim สั้น"""
    if not _RICH_OK:  # pragma: no cover
        print(f"⎿ {_truncate(str(text), 1500)}")
        return
    theme = get_theme()
    console.print(Panel(
        Text(f"┗━ {_truncate(str(text), 1500)}", style=theme["result"]),
        border_style="bright_black",
        title=f"[dim]{name}[/dim]",
        title_align="left",
        padding=(0, 1),
        width=min(_width(), 110),
    ))


# ============================================================
# Status HUD
# ============================================================
def status_hud(agent):
    """แถบสถานะ HUD: โมเดล · โฟลเดอร์ · ข้อความ · โทเค็น"""
    if not _RICH_OK:  # pragma: no cover
        return
    theme = get_theme()
    msgs = max(0, len(agent.messages) - 1)
    u = agent.usage
    if u["prompt_tokens"] or u["completion_tokens"]:
        tok = f"in {u['prompt_tokens']:,} · out {u['completion_tokens']:,}"
    else:
        tok = "—"
    cwd = Path(agent.cwd).name if agent.cwd else "—"
    t = Text()
    t.append("◈ ", style="bold cyan")
    t.append(f"{agent.model}", style="bold white")
    t.append(f"  │  {cwd}", style=theme["dim"])
    t.append(f"  │  ข้อความ {msgs}", style=theme["dim"])
    t.append(f"  │  tok {tok}", style=theme["dim"])
    console.print(t)


# ============================================================
# Errors / warnings / confirms
# ============================================================
def error_box(message, title="Error"):
    if not _RICH_OK:  # pragma: no cover
        print(f"Error: {message}")
        return
    theme = get_theme()
    console.print(Panel(
        Text(str(message)),
        border_style=theme["err"],
        title=f"[{theme['err']}]✕ {title}[/]",
        title_align="left",
        padding=(0, 1),
        width=min(_width(), 100),
    ))


def warn_box(message, title="Warning"):
    if not _RICH_OK:  # pragma: no cover
        print(f"Warning: {message}")
        return
    theme = get_theme()
    console.print(Panel(
        Text(str(message)),
        border_style=theme["warn"],
        title=f"[{theme['warn']}]⚠ {title}[/]",
        title_align="left",
        padding=(0, 1),
        width=min(_width(), 100),
    ))


def confirm(question, choices="[y] ✓ Yes  [N] ✕ No  [e] ✎ Edit"):
    """คำถามยืนยัน — คงความเข้ากันได้กับ `_safe_input` เดิม"""
    if not _RICH_OK:  # pragma: no cover
        return input(f"{question} {choices} ? ")
    theme = get_theme()
    t = Text()
    t.append(f"  {question}  ", style=theme["prompt"])
    t.append(choices, style="dim")
    t.append("  ? ", style=theme["prompt"])
    console.print(t)
    try:
        return input("").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return "n"


# ============================================================
# Misc HUD elements
# ============================================================
def section(label, style=None):
    """หัวข้อ section แบบ HUD"""
    if not _RICH_OK:  # pragma: no cover
        print(f"\n== {label} ==")
        return
    theme = get_theme()
    return Rule(f"[bold]{label}[/bold]", style=style or theme["accent"])


def cmd_hints():
    """แถวคำแนะนำปุ่มลัด (ใช้ใต้ status HUD ทุก turn)"""
    if not _RICH_OK:  # pragma: no cover
        return
    t = Text()
    t.append("  ❯ ", style="bold cyan")
    t.append("type a message", style="dim")
    t.append("   ·   ", style="bright_black")
    t.append("/help", style="bold cyan")
    t.append(" commands   ·   ", style="dim")
    t.append("/clear", style="bold cyan")
    t.append(" reset   ·   ", style="dim")
    t.append("/exit", style="bold cyan")
    t.append(" quit", style="dim")
    console.print(t)


def thinking_cursor():
    """Cursor สตรีมมิง '...' แบบไม่ block REPL"""
    return Text("  ⠿ ", style="grey58")


def datetime_now(fmt="%H:%M:%S"):
    try:
        from datetime import datetime as _dt
        return _dt.now().strftime(fmt)
    except Exception:
        return ""


def ok_line(message):
    if not _RICH_OK:  # pragma: no cover
        print(f"✓ {message}")
        return
    theme = get_theme()
    console.print(Text(f"  ✓ {message}", style=theme["ok"]))


def cancel_line(message="ยกเลิกโดยผู้ใช้"):
    if not _RICH_OK:  # pragma: no cover
        print(f"↩ {message}")
        return
    theme = get_theme()
    console.print(Text(f"  ↩ {message}", style=theme["warn"]))
