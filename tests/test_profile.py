"""ทดสอบ Profiles — แยก config/session/memory ต่อโพรไฟล์ (Phase 7)"""
import os, sys, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_profile_env_changes_dirs(tmp_path):
    code = (
        "import os\n"
        "os.environ['YOUSINI_PROFILE']='work'\n"
        "import yousini\n"
        "print(yousini.SESSION_DIR)\n"
        "print(yousini.CONFIG_DIR)\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
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
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    line = out.stdout.strip().splitlines()[-1]
    assert "profiles" not in line.replace("\\", "/")
    assert line.replace("\\", "/").endswith(".yousini")