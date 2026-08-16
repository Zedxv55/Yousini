# -*- coding: utf-8 -*-
"""
yousini_interactive — ฟีเจอร์ interactive ของ Terminal Yousini
============================================================
1. Command Palette — กด / แล้วค้นหา/เลือกคำสั่งด้วย arrow keys (fail-open:
   จอที่ไม่เป็น tty หรือ Windows ที่ไม่รับ ANSI มาตรฐาน จะค้างใช้ input() ปกติ)
2. Typewriter markdown — สตรีมคำตอบ Markdown ทีละคำพร้อม highlight แบบ live
3. Progress bars — แบบ fail-open สำหรับงานนาน (download/scaffold/dev/...)
ทั้งหมดเป็น pure rich (ไม่มี dependency ใหม่)
"""
import sys
import time
import threading
from datetime import datetime

try:
    from rich.console import Console
    from rich.text import Text
    from rich.panel import Panel
    _RICH_OK = True
except Exception:  # pragma: no cover
    _RICH_OK = False

try:
    from rich.live import Live
    from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, SpinnerColumn
    _HAS_PROGRESS = True
except Exception:  # pragma: no cover
    _HAS_PROGRESS = False

console = Console()

# ============================================================
# Command palette (fuzzy select)
# ============================================================
def _read_key():
    """อ่าน 1 key จาก tty — คืน key หรือ None ถ้าไม่ใช่ tty (Windows ใช้ msvcrt — fail-open)"""
    try:
        if sys.platform == "win32":  # pragma: no cover
            try:
                import msvcrt
                b = msvcrt.getch()
                if b == b"\xe0" or b == b"\x00":
                    b = msvcrt.getch()
                    return {72: "up", 80: "down", 73: "pageup", 81: "pagedown"}.get(b[0])
                if b == b"\r":
                    return "enter"
                if b == b"\x03":
                    return "ctrlc"
                if b == b"\x08":
                    return "back"
                if b == b"\t":
                    return "tab"
                if b == b"\x1b":
                    return "esc"
                try:
                    return b.decode("utf-8")
                except Exception:
                    return None
            except Exception:
                return None
        if not sys.stdin.isatty():
            return None
        import tty, termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            b = sys.stdin.read(1)
            if b == "\x1b":
                # escape sequence
                try:
                    sys.stdin.read(1)  # [
                    c = sys.stdin.read(1)
                except Exception:
                    return None
                if c == "A":
                    return ("up", False)
                if c == "B":
                    return ("down", False)
                if c in ("5", "6"):
                    try:
                        sys.stdin.read(1)  # ~
                    except Exception:
                        pass
                    return (("pageup" if c == "5" else "pagedown"), False)
                return None
            if b in ("\r", "\n"):
                return ("enter", False)
            if b == "\x03":
                return ("ctrlc", False)
            if b == "\t":
                return ("tab", False)
            if b == "\x7f" or b == "\b":
                return ("back", False)
            if b == "\x16":
                return ("ctrlv", False)
            if b == " ":
                return ("space", False)
            # อักขระป้องที่ (UTF-8 ติดกันใน raw mode)
            try:
                if ord(b) & 0b11100000 == 0b11000000:
                    b += sys.stdin.read(1)
                elif ord(b) & 0b11110000 == 0b11100000:
                    b += sys.stdin.read(2)
                elif ord(b) & 0b11111000 == 0b11110000:
                    b += sys.stdin.read(3)
            except Exception:
                pass
            return (b, False)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except Exception:
        return None


def _fuzzy_score(query, label):
    """คะแนน fuzzy แบบง่าย — ตัวอักษรใน query ปรากฏตามลำดับใน label ได้คะแนนบวก"""
    if not query:
        return 1
    ql = query.lower()
    ll = label.lower()
    # prefix match ได้คะแนนสูง
    if ll.startswith(ql):
        return 100 + len(query)
    score, qi = 0, 0
    for ch in ll:
        if qi < len(ql) and ch == ql[qi]:
            score += 10
            qi += 1
    return score if qi == len(ql) else -1


def command_palette(commands, title="Command Palette", prefill=""):
    """เลือกคำสั่งด้วย arrow keys + fuzzy search
    commands: list of (key, description) เช่น [("/help", "แสดงทุกคำสั่ง")]
    คืน (key, description) หรือ None ถ้าถูกยกเลิก
    """
    if not _RICH_OK or not commands or not sys.stdin.isatty():  # pragma: no cover
        # fallback: แจงรายการแล้วอ่าน input ปกติ
        if not commands:
            return None
        for k, d in commands:
            console.print(Text(f"  {k} — {d}", style="dim"))
        try:
            pick = input("❯ ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        for k, d in commands:
            if k.lower().startswith(pick.lower() if pick else "/"):
                return (k, d)
        return None

    entries = [(k, d) for k, d in commands]
    query = prefill
    sel = 0

    def _render(live):
        scored = [(k, d, _fuzzy_score(query, k)) for k, d in entries]
        scored = [x for x in scored if x[2] >= 0]
        scored.sort(key=lambda x: -x[2])
        if not scored:
            body = Text("  (ไม่พบคำสั่งที่ตรงกับค้นหา)", style="dim")
        else:
            body = Text()
            for i, (k, d, _s) in enumerate(scored[:10]):
                if i == sel % min(10, len(scored)):
                    body.append(" ▸ ", style="bold cyan")
                    body.append(k, style="bold cyan")
                    body.append(f" — {d}", style="white")
                else:
                    body.append("   " + k, style="dim")
                    body.append(f" — {d}", style="dim")
                body.append("\n")
        t = Text()
        t.append(" ⌕ ", style="bold magenta")
        t.append(query or "พิมพ์ค้นหา…", style="bold white" if query else "dim")
        t.append("  (↑↓ เลื่อน · ↵ เลือก · Esc ยกเลิก)", style="dim")
        live.update(Panel(body, title=f"[bold magenta]{title}[/bold magenta]",
                          subtitle=t, border_style="magenta", padding=(1, 2)))

    try:
        from rich.live import Live as _Live
        with _Live(Text(), console=console, refresh_per_second=8) as live:
            _render(live)
            while True:
                r = _read_key()
                if r is None:  # ไม่ใช่ tty → fallback ทันที
                    live.stop()
                    return command_palette.__defaults__[1] and None or _palette_fallback(entries)
                key, _ = r
                if key == "enter":
                    scored = [(k, d, _fuzzy_score(query, k)) for k, d in entries]
                    scored = sorted([x for x in scored if x[2] >= 0], key=lambda x: -x[2])[:10]
                    if not scored:
                        live.stop(); continue
                    sel2 = sel % len(scored)
                    k, d, _ = scored[sel2]
                    console.print()
                    return (k, d)
                if key in ("up",):
                    sel -= 1
                elif key == "down":
                    sel += 1
                elif key in ("tab", "space"):
                    sel += 1
                elif key == "back":
                    query = query[:-1]
                    sel = 0
                elif key == "ctrlc":
                    live.stop(); console.print(); return None
                elif key == "esc":
                    live.stop(); console.print(); return None
                elif isinstance(key, str) and len(key) >= 1 and key not in ("pageup", "pagedown") and not (ord(key[0]) < 32):
                    query = (query + key)[:40]
                    sel = 0
                _render(live)
    except Exception:  # pragma: no cover
        return _palette_fallback(entries)


def _palette_fallback(entries):  # pragma: no cover
    for k, d in entries[:20]:
        console.print(Text(f"  {k} — {d}", style="dim"))
    try:
        pick = input("❯ ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    for k, d in entries:
        if pick and k.lower().startswith(pick.lower()):
            return (k, d)
    return None


# ============================================================
# Typewriter markdown streaming
# ============================================================
def typewriter_md(text, model=None, speed="fast"):
    """แสดง Markdown โดยป้อนเนื้อหาทีละคำ (typewriter effect) ผ่าน rich.Live
    เร็วกว่า typewriter จริง ๆ: ป้อนเป็นชุดคำแล้ว refresh ทันที
    """
    if not _RICH_OK or not sys.stdin.isatty():
        from rich.markdown import Markdown
        console.print(Markdown(text))
        return
    try:
        from rich.markdown import Markdown
        from rich.live import Live as _Live
    except Exception:
        from rich.markdown import Markdown
        console.print(Markdown(text))
        return
    # ชุดคำ (batch) ใหญ่พอให้ stream ดูสมูธ: ~120 อักขระ/เฟรม
    BATCH = 120
    chunks = [text[i:i + BATCH] for i in range(0, max(len(text), 1), BATCH)]
    try:
        with _Live(Text("…"), console=console, refresh_per_second=12) as live:
            cur = []
            for part in chunks:
                cur.append(part)
                live.update(Panel(Markdown("".join(cur)),
                                  border_style="cyan", title="[bold cyan]Yousini[/bold cyan]",
                                  subtitle=Text(f" | {model}", style="dim") if model else None,
                                  padding=(0, 1)))
            # เฟรมสุดท้าย: เต็มความกว้าง
            live.update(Panel(Markdown(text),
                              border_style="cyan", title="[bold cyan]Yousini[/bold cyan]",
                              subtitle=Text(f" | {model}", style="dim") if model else None,
                              padding=(0, 1)))
    except Exception:
        from rich.markdown import Markdown
        console.print(Markdown(text))


class TypewriterStream:
    """Live preview แบบ token-by-token — ให้อาหาร Markdown ทีละ chunk
    ที่ได้จากการ stream ของ API ( latency ต่ำกว่า typewriter_md ที่รอ
    คำตอบครบทั้งข้อความก่อนเริ่มป้อน )"""
    def __init__(self, console=None, model=None):
        self.console = console or Console()
        self.model = model
        self._live = None
        self._started = False
        self._buffer = []

    def start(self):
        if not _RICH_OK or not sys.stdin.isatty():
            self._started = False
            return
        try:
            from rich.live import Live as _Live
            self._live = _Live(Text("…"), console=self.console,
                               refresh_per_second=15, transient=False)
            self._live.start()
            self._started = True
        except Exception:
            self._started = False

    def write(self, token):
        if not self._started or self._live is None or not token:
            return
        try:
            from rich.markdown import Markdown
            self._buffer.append(token)
            self._live.update(Markdown("".join(self._buffer)))
        except Exception:
            pass

    def stop(self):
        if self._live is not None:
            try:
                self._live.stop()
            except Exception:
                pass
        self._live = None
        self._started = False


def typewriter_stream():
    """Context manager ให้อาหาร Live preview แบบ token-by-token

    ใช้งาน:
        with typewriter_stream() as tw:
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    tw.write(chunk.choices[0].delta.content)
    ถ้าสภาพแวดล้อมไม่รองรับ (ไม่ใช่ tty / ไม่มี rich) จะเป็น no-op
    """
    class _Ctx:
        def __init__(self):
            self._tw = TypewriterStream(console=console)

        def __enter__(self):
            self._tw.start()
            return self

        def __exit__(self, *exc):
            self._tw.stop()
            return False

        def write(self, token):
            self._tw.write(token)
    return _Ctx()


# ============================================================
# Progress bars (fail-open, thread-safe)
# ============================================================
class ProgressBars:
    """ตัวจัดการ progress bar แบบไม่ block — ใช้ระหว่างงานนาน ๆ เช่น
    download, scaffold, /dev, symbol reindex"""
    def __init__(self, console=None):
        self.console = console or Console()
        self._bars = {}
        self._lock = threading.Lock()
        self._live = None
        self._started = False

    def start(self):
        if not _HAS_PROGRESS or not sys.stdin.isatty():
            self._started = False
            return
        try:
            self._live = Live(refresh_per_second=8, console=self.console, transient=True)
            self._live.start()
            self._started = True
        except Exception:
            self._started = False

    def stop(self):
        if self._live is not None:
            try:
                self._live.stop()
            except Exception:
                pass
            self._live = None
        self._started = False
        self._bars.clear()

    def new(self, name, total=100):
        """สร้าง progress bar คืน id"""
        if not self._started:
            self.start()
        with self._lock:
            bar_id = len(self._bars)
            self._bars[bar_id] = {
                "name": name, "total": max(total, 1), "done": 0,
                "start": time.time(),
            }
            self._refresh()
            return bar_id

    def advance(self, bar_id, amount=1, note=None):
        with self._lock:
            b = self._bars.get(bar_id)
            if b is None:
                return
            b["done"] = min(b["done"] + amount, b["total"])
            if note:
                b["note"] = note
            self._refresh()

    def finish(self, bar_id, note=None):
        with self._lock:
            b = self._bars.get(bar_id)
            if b is None:
                return
            b["done"] = b["total"]
            if note:
                b["note"] = note
            self._refresh()
            self._bars.pop(bar_id, None)
            if not self._bars:
                self.stop()

    def _refresh(self):
        if self._live is None:
            return
        from rich.table import Table
        t = Table.grid(padding=(0, 2))
        t.add_column(min_width=28)
        t.add_column(min_width=10)
        t.add_column(min_width=2)
        for b in sorted(self._bars.values(), key=lambda x: x["name"]):
            pct = max(0, min(100, int(100 * b["done"] / b["total"])))
            filled = int(pct / 5)
            bar = "█" * filled + "░" * (20 - filled)
            note = b.get("note", "")
            label = Text(f" {b['name']} ", style="bold cyan")
            label.append(bar, style="green" if pct >= 100 else "bright_black")
            label.append(f" {pct:>3}% ", style="bold white")
            label.append(f"({note})" if note else "", style="dim")
            t.add_row(label)
        try:
            self._live.update(t)
        except Exception:
            pass
