#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Project scaffolding — สร้างโครงโปรเจกต์เริ่มต้นจากเทมเพลต (ไม่ต้องใช้โมเดล)

- scaffold(kind, name, cwd) — สร้างโฟลเดอร์ name พร้อมไฟล์ตามเทมเพลต
- เทมเพลต: python-cli, python-pkg, web-static
- token แทนที่: [[name]] = ชื่อโปรเจกต์ (ตัวเล็ก), [[Name]] = PascalCase
- คืนรายงานไฟล์ที่สร้าง
"""
import os
import re
import sys
from pathlib import Path

TEMPLATES = {
    "python-cli": {
        "files": {
            "[[name]]/__init__.py": "",
            "[[name]]/main.py": '''"""[[Name]] — CLI tool (main entry)"""
import argparse


def main(argv=None):
    ap = argparse.ArgumentParser(prog="[[name]]", description="[[Name]]")
    ap.add_argument("--hello", action="store_true", help="พิมพ์ Hello")
    args = ap.parse_args(argv)
    if args.hello:
        print("Hello from [[name]]!")


if __name__ == "__main__":
    main()
''',
            "pyproject.toml": '''[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "[[name]]"
version = "0.1.0"
description = "[[Name]]"
requires-python = ">=3.10"
dependencies = []

[project.scripts]
[[name]] = "[[name]].main:main"

[tool.setuptools]
packages = ["[[name]]"]

[tool.pytest.ini_options]
pythonpath = ["."]
''',
            "tests/test_main.py": '''def test_hello(capsys):
    from [[name]].main import main
    main(["--hello"])
    out = capsys.readouterr().out
    assert "Hello from [[name]]" in out
''',
            "README.md": "# [[Name]]\n\nโปรเจกต์ Python CLI.\n\n```bash\npip install -e .\n[[name]] --hello\n```\n",
            ".gitignore": "__pycache__/\n*.pyc\n.venv/\ndist/\nbuild/\n*.egg-info/\n",
        },
    },
    "python-pkg": {
        "files": {
            "[[name]]/__init__.py": '"""[[Name]] — Python package."""\n\n__version__ = "0.1.0"\n',
            "[[name]]/core.py": '''"""ฟังก์ชันหลักของแพ็กเกจ [[name]]."""


def hello(name: str = "world") -> str:
    return f"Hello, {name}!"
''',
            "pyproject.toml": '''[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "[[name]]"
version = "0.1.0"
description = "[[Name]]"
requires-python = ">=3.10"
dependencies = []

[tool.setuptools]
packages = ["[[name]]"]

[tool.pytest.ini_options]
pythonpath = ["."]
''',
            "tests/test_core.py": '''from [[name]].core import hello


def test_hello():
    assert hello("Yousini") == "Hello, Yousini!"
''',
            "README.md": "# [[Name]]\n\nแพ็กเกจ Python.\n\n```python\nfrom [[name]].core import hello\nprint(hello())\n```\n",
            ".gitignore": "__pycache__/\n*.pyc\n.venv/\ndist/\nbuild/\n*.egg-info/\n",
        },
    },
    "web-static": {
        "files": {
            "index.html": '''<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>[[Name]]</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <main>
    <h1>[[Name]]</h1>
    <button id="btn">คลิก</button>
  </main>
  <script src="app.js"></script>
</body>
</html>
''',
            "style.css": '''body {
  font-family: system-ui, sans-serif;
  display: grid;
  place-items: center;
  min-height: 100vh;
  margin: 0;
  background: #0f172a;
  color: #e2e8f0;
}
button {
  padding: .5rem 1rem;
  border-radius: 8px;
  border: none;
  background: #3b82f6;
  color: white;
  cursor: pointer;
}
''',
            "app.js": '''const btn = document.getElementById("btn");
btn.addEventListener("click", () => {
  btn.textContent = "คลิกแล้ว!";
});
''',
            "README.md": "# [[Name]]\n\nเว็บ static (HTML/CSS/JS). เปิด `index.html` หรือเสิร์ฟด้วย `python -m http.server`.\n",
        },
    },
}

KINDS = tuple(TEMPLATES)
KIND_LABEL = ", ".join(KINDS)


def _valid_name(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_\-\.]*", name or ""))


def scaffold(kind: str, name: str, cwd: str = ".") -> str:
    """สร้างโปรเจกต์ 'name' จากเทมเพลต 'kind' ใต้ cwd — คืนรายงาน (ไม่ throw)"""
    kind = (kind or "").lower()
    name = (name or "").strip().lower()
    if kind not in TEMPLATES:
        return f"Error: เทมเพลต '{kind}' ไม่มี (มี: {KIND_LABEL})"
    if not _valid_name(name):
        return (f"Error: ชื่อ '{name}' ไม่ถูกต้อง (ห้ามเว้นวรรค/อักขระพิเศษ, "
                f"เริ่มด้วยตัวอักษรหรือตัวเลข)")
    root = Path(cwd).resolve() / name
    if root.exists():
        return f"Error: {root} มีอยู่แล้ว — เลือกชื่ออื่นหรือลบก่อน"
    Name = name.replace("-", " ").replace("_", " ").title().replace(" ", "")
    created = []
    for rel, content in TEMPLATES[kind]["files"].items():
        rel = rel.replace("[[name]]", name)
        p = root / rel
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            text = content.replace("[[name]]", name).replace("[[Name]]", Name)
            p.write_text(text, encoding="utf-8", newline="\n")
            created.append(str(p.relative_to(root)))
        except Exception as e:
            return f"Error: เขียน {p} ล้มเหลว: {e}"
    return (f"สร้างโปรเจกต์ {kind} '{name}' ที่ {root}\n"
            f"สร้าง {len(created)} ไฟล์:\n" + "\n".join("  " + c for c in created))


def kinds_text() -> str:
    return KIND_LABEL


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        print(scaffold(sys.argv[1], sys.argv[2], os.getcwd()))
    else:
        print(f"ใช้: python yousini_scaffold.py <kind> <name>  (kind: {KIND_LABEL})")