#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yousini installer — ให้รัน `yousini` ได้จากทุกที่

  python install.py                 # ติดตั้ง launcher (Windows .cmd / mac·linux script) + ลง PATH (user)
  python install.py --pip           # ติดตั้งแบบ pip editable (สร้างคำสั่ง yousini จริงใน Python)
  python install.py --pip --user    # pip ลงเฉพาะ user
  python install.py --uninstall     # เอาออก (ลบ launcher + เอาออกจาก PATH)

ทำงานซ้ำได้ (idempotent) ไม่ยุ่งกับไฟล์ของระบบมากกว่า user-level
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BIN = Path.home() / ".yousini" / "bin"
GIT = "https://github.com/Zedxv55/Yousini.git"


def _win() -> bool:
    return sys.platform == "win32"


# ---------------------------------------------------------------------------
# PATH (Windows ใช้ registry ของ user + broadcast; อื่นใช้ ~/.bashrc, ~/.zshrc)
# ---------------------------------------------------------------------------
def _win_path_user() -> str:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment",
                            0, winreg.KEY_READ) as k:
            v, _ = winreg.QueryValueEx(k, "Path")
            return v or ""
    except OSError:
        return ""


def _win_set_path_user(newpath: str) -> None:
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, r"Environment",
                            0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "Path", 0, winreg.REG_EXPAND_SZ, newpath)
    # broadcast เพื่อให้เทอร์มินัลใหม่เห็นทันที
    try:
        import ctypes
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", 0, 2000, None)
    except Exception:
        pass


def _add_to_path() -> tuple:
    """คืน (changed, msg)"""
    if _win():
        cur = _win_path_user()
        entries = [e for e in cur.split(";") if e.strip()]
        if str(BIN) in entries:
            return False, f"PATH มีอยู่แล้ว: {BIN}"
        entries.append(str(BIN))
        _win_set_path_user(";".join(entries))
        return True, f"เพิ่ม {BIN} เข้า PATH (user) แล้ว — เปิดเทอร์มินัลใหม่ก่อนใช้"
    # POSIX
    rcfile = Path.home() / (".zshrc" if Path.home().joinpath(".zshrc").exists() else ".bashrc")
    line = f'export PATH="{BIN}:$PATH"'
    if rcfile.is_file() and line in rcfile.read_text(encoding="utf-8", errors="ignore"):
        return False, f"PATH มีอยู่แล้วใน {rcfile}"
    rcfile.parent.mkdir(parents=True, exist_ok=True)
    with rcfile.open("a", encoding="utf-8") as f:
        f.write("\n# Yousini\n" + line + "\n")
    return True, f"เพิ่ม PATH ใน {rcfile} แล้ว"


def _remove_from_path() -> tuple:
    if _win():
        cur = _win_path_user()
        entries = [e for e in cur.split(";") if e.strip() and e.strip() != str(BIN)]
        _win_set_path_user(";".join(entries))
        return True, f"เอาออกจาก PATH แล้ว (user): {BIN}"
    return False, "PATH ต้องเอาออกจาก .bashrc/.zshrc เอง (บรรทัด # Yousini)"


# ---------------------------------------------------------------------------
# launcher
# ---------------------------------------------------------------------------
def _write_launcher() -> Path:
    BIN.mkdir(parents=True, exist_ok=True)
    py = sys.executable
    target = ROOT / "yousini.py"
    if _win():
        launcher = BIN / "yousini.cmd"
        launcher.write_text(
            f"@echo off\r\n\"{py}\" \"{target}\" %*\r\n",
            encoding="utf-8")
    else:
        launcher = BIN / "yousini"
        launcher.write_text(
            f"#!/bin/sh\nexec \"{py}\" \"{target}\" \"$@\"\n",
            encoding="utf-8")
        launcher.chmod(0o755)
    return launcher


# ---------------------------------------------------------------------------
# install / uninstall
# ---------------------------------------------------------------------------
def install(pip: bool = False, user: bool = False) -> int:
    if pip:
        cmd = [sys.executable, "-m", "pip", "install", "-e", str(ROOT)]
        if user:
            cmd.append("--user")
        print("ติดตั้งแบบ pip editable (คำสั่ง `yousini` จริง) ...")
        subprocess.check_call(cmd)
        print("เสร็จ — ลอง: yousini --version")
        return 0
    launcher = _write_launcher()
    print(f"สร้าง launcher: {launcher}")
    changed, msg = _add_to_path()
    print(msg if changed else f"PATH: {msg}")
    print(f"\nติดตั้งเสร็จ — เปิดเทอร์มินัลใหม่ แล้วลอง: yousini --version")
    return 0


def uninstall() -> int:
    launcher = BIN / ("yousini.cmd" if _win() else "yousini")
    if launcher.exists():
        launcher.unlink()
        print(f"ลบ launcher: {launcher}")
    changed, msg = _remove_from_path()
    print(msg if changed else f"PATH: {msg}")
    try:
        BIN.rmdir()
    except OSError:
        pass
    print("เอาออกเรียบร้อย (ถ้าติดตั้งแบบ --pip ให้ใช้ pip uninstall yousini)")
    return 0


def main():
    ap = argparse.ArgumentParser(description="ติดตั้ง Yousini ให้รันจากทุกที่")
    ap.add_argument("--pip", action="store_true",
                    help="ติดตั้งแบบ pip editable แทน launcher")
    ap.add_argument("--user", action="store_true", help="pip ลงเฉพาะ user")
    ap.add_argument("--uninstall", action="store_true", help="เอาออก")
    a = ap.parse_args()
    try:
        if a.uninstall:
            return uninstall()
        return install(pip=a.pip, user=a.user)
    except subprocess.CalledProcessError as e:
        print(f"ผิดพลาด: {e}", file=sys.stderr)
        return e.returncode
    except Exception as e:
        print(f"ผิดพลาด: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())