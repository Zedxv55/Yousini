"""ทดสอบ Profiles — แยก config/session/memory ต่อโพรไฟล์ (Phase 7)"""
import os, sys, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("YOUSINI_")}
# คง YOUSINI_API_KEY (ค่า dummy) ไว้ — yousini.py exit ทันทีถ้าไม่มี API Key
# ทดสอบ Profiles ไม่ได้ต้องการ key จริง ขอเพียง import สำเร็จ
_CLEAN_ENV["YOUSINI_API_KEY"] = os.environ.get("YOUSINI_API_KEY", "dummy")


def test_profile_env_changes_dirs(tmp_path):
    code = (
        "import os\n"
        "os.environ['YOUSINI_PROFILE']='work'\n"
        "import yousini\n"
        "print(yousini.SESSION_DIR)\n"
        "print(yousini.CONFIG_DIR)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", env=_CLEAN_ENV,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    lines = [l for l in out.stdout.strip().splitlines() if l]
    assert len(lines) == 2 and out.returncode == 0
    assert lines[0].replace("\\", "/").endswith(".yousini/profiles/work/sessions")
    assert lines[1].replace("\\", "/").endswith(".yousini/profiles/work")


def test_profile_default_when_unset(tmp_path):
    code = (
        "import os\n"
        "if 'YOUSINI_PROFILE' in os.environ:\n"
        "    del os.environ['YOUSINI_PROFILE']\n"
        "import yousini\n"
        "print(yousini.CONFIG_DIR)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", env=_CLEAN_ENV,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    line = out.stdout.strip().splitlines()[-1]
    assert "profiles" not in line.replace("\\", "/")
    assert line.replace("\\", "/").endswith(".yousini")