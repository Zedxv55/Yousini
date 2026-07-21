#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yousini Skill Marketplace - ติดตั้ง skill จาก git repo
"""
import os
import subprocess
import shutil
from pathlib import Path

SKILLS_DIR = Path.home() / ".yousini" / "skills"

def skill_install(args):
    """yousini skill install <git-url>"""
    if not args or args[0].lower() != "install":
        print("ใช้: yousini skill install <git-url>")
        return

    git_url = args[1] if len(args) > 1 else ""
    if not git_url:
        print("ต้องให้ URL ของ git repo")
        return

    SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    # clone repo ชั่วคราว
    import tempfile
    import urllib.request

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            # พยายาม git clone
            if shutil.which("git"):
                subprocess.run(
                    ["git", "clone", "--depth", "1", git_url, tmpdir + "/repo"],
                    check=True, capture_output=True
                )
                repo_path = Path(tmpdir) / "repo"
            else:
                # fallback: ลองดาวน์โหลด zip ถ้า repo เป็น github
                if "github.com" in git_url:
                    api_url = git_url.replace("github.com", "api.github.com/repos").replace(".git", "")
                    api_url = f"{api_url}/zipball/main"
                    urllib.request.urlretrieve(api_url, tmpdir + "/repo.zip")
                    import zipfile
                    with zipfile.ZipFile(tmpdir + "/repo.zip") as z:
                        z.extractall(tmpdir + "/repo")
                    repo_path = Path(tmpdir + "/repo")
                else:
                    print("ต้องการ git หรือ URL ที่รองรับ")
                    return

            # หาไฟล์ .md ใน skills/ folder
            skill_files = list(repo_path.rglob("skills/*.md")) + list(repo_path.rglob("*.md"))
            if not skill_files:
                print("ไม่พบไฟล์ skill (.md) ใน repo")
                return

            # คัดลอก skill files
            copied = 0
            for sf in skill_files:
                dest = SKILLS_DIR / sf.name
                if dest.exists():
                    print(f"มีอยู่แล้ว: {sf.name} (ข้าม)")
                    continue
                shutil.copy(sf, dest)
                copied += 1
                print(f"ติดตั้ง: {sf.name}")

            print(f"\nติดตั้งสำเร็จ {copied} skill(s)")
            print(f"Skill อยู่ที่: {SKILLS_DIR}")

        except Exception as e:
            print(f"Error: {e}")