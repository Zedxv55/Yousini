#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Symbol Index — ดัชนีสัญลักษณ์โค้ด (LSP-style symbol search)

tree-sitter parse AST → function/class/method/constants พร้อมไฟล์+บรรทัด+signature
- find()  = go-to-definition (ชื่อ → ตำแหน่งนิยาม)
- refs()  = หาทุกจุดอ้างอิง
- cache   = JSON ใต้ <root>/.yousini_symbols.json (ตรวจ mtime ว่าล้าสมัย)
Fallback: regex ง่าย ๆ เมื่อไม่มี grammar สำหรับภาษานั้น
"""
import json
import os
import re
from pathlib import Path

DEFAULT_IGNORE = {".git", "node_modules", "venv", ".venv", "dist", "build",
                  "__pycache__", ".yousini", "vendor", "target"}
SUPPORTED_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".c", ".h", ".rs"}
CACHE_NAME = ".yousini_symbols.json"


def _txt(node) -> str:
    """text ของ tree-sitter node (bytes → str) กัน error"""
    try:
        return node.text.decode("utf-8", errors="replace")
    except Exception:
        try:
            return bytes(node.text).decode("utf-8", errors="replace")
        except Exception:
            return str(node)


class SymbolIndex:
    """Index สัญลักษณ์ของโปรเจกต์ + cache ตาม mtime"""

    def __init__(self, root: str = ".", ignore_dirs: set = None, use_cache: bool = True):
        self.root = Path(root).resolve()
        self.ignore = DEFAULT_IGNORE | (ignore_dirs or set())
        self.cache_path = self.root / CACHE_NAME
        self.entries = []          # [{name, kind, file, line, signature}]
        self.by_file = {}          # {str(path): mtime}
        self._cache = None
        self._changed = False
        self._load_cache(use_cache)
        if self._is_stale():
            self.build()

    # ---- cache ----
    def _load_cache(self, use_cache):
        try:
            if use_cache and self.cache_path.is_file():
                self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
                self.entries = self._cache.get("entries", [])
                self.by_file = self._cache.get("by_file", {})
        except Exception:
            self._cache = None

    def _is_stale(self) -> bool:
        if not self._cache:
            return True
        try:
            for raw, mtime in self.by_file.items():
                p = Path(raw)
                if not p.is_file() or p.stat().st_mtime != mtime:
                    return True
        except Exception:
            return True
        return False

    def _save_cache(self):
        try:
            data = {"entries": self.entries, "by_file": self.by_file}
            self.cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self._cache = data
        except Exception:
            pass

    # ---- build ----
    def _walk_files(self):
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in self.ignore]
            for fn in filenames:
                p = Path(dirpath) / fn
                if p.suffix in SUPPORTED_EXT:
                    yield p

    def build(self):
        self.entries, self.by_file = [], {}
        for p in self._walk_files():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            got = self._parse_file(p, text)
            if got:
                self.entries.extend(got)
                self.by_file[str(p)] = p.stat().st_mtime
        if self.entries:
            self._save_cache()
        return len(self.entries)

    # ---- parse per language ----
    def _parse_file(self, path: Path, text: str):
        ext = path.suffix
        called = getattr(self, "_parse_" + ext.lstrip(".").replace("+", "p"), None)
        if called:
            try:
                return called(text, path)
            except Exception:
                pass
        return self._parse_regex(text, path)

    def _ts_parser(self):
        """Parser tree-sitter (lazy import — ไม่บังคับติดตั้ง)"""
        try:
            from tree_sitter import Language, Parser
            import tree_sitter_python, tree_sitter_javascript
            langs = {
                ".py": Language(tree_sitter_python.language()),
                ".js": Language(tree_sitter_javascript.language()),
                ".mjs": Language(tree_sitter_javascript.language()),
                ".cjs": Language(tree_sitter_javascript.language()),
                ".ts": Language(tree_sitter_javascript.language()),
                ".tsx": Language(tree_sitter_javascript.language()),
                ".jsx": Language(tree_sitter_javascript.language()),
            }
            return Parser, langs
        except Exception:
            return None, {}

    # ---- tree-sitter extractors ----
    def _parse_py(self, text: str, path: Path):
        Parser, langs = self._ts_parser()
        if not Parser:
            return self._parse_regex(text, path)
        tree = Parser(langs[".py"]).parse(bytes(text, "utf-8"))
        out, stack = [], []
        class_depth = 0

        def walk(node, in_class):
            nonlocal class_depth
            t = node.type
            if t in ("function_definition", "class_definition"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = _txt(name_node)
                    line = node.start_point[0] + 1
                    seg = _txt(node).splitlines()[0][:110]
                    if t == "class_definition":
                        kind = "class"
                        class_depth += 1
                    else:
                        kind = "method" if in_class or class_depth > 0 else "function"
                    out.append({"name": name, "kind": kind, "file": str(path),
                                "line": line, "signature": seg})
            for child in node.named_children:
                walk(child, in_class or t == "class_definition")
            if t == "class_definition":
                class_depth = max(0, class_depth - 1)

        walk(tree.root_node, False)
        # ค่าคงที่ระดับโมดูล: NAME = value
        re_assign = re.compile(r"^([A-Z][A-Z0-9_]{1,})\s*=\s*(.+)$")
        for i, line in enumerate(text.splitlines(), 1):
            m = re_assign.match(line.strip())
            if m and not line.lstrip().startswith(("#", "class", "def")):
                out.append({"name": m.group(1), "kind": "constant", "file": str(path),
                            "line": i, "signature": line.strip()[:110]})
        return out

    def _parse_js(self, text: str, path: Path):
        Parser, langs = self._ts_parser()
        if not Parser:
            return self._parse_regex(text, path)
        tree = Parser(langs[path.suffix]).parse(bytes(text, "utf-8"))
        out = []
        types = {".js": "function_declaration", ".mjs": "function_declaration",
                 ".cjs": "function_declaration", ".ts": "function_declaration",
                 ".tsx": "function_declaration", ".jsx": "function_declaration"}

        def walk(node, in_class):
            t = node.type
            if t in ("function_declaration", "class_declaration", "method_definition",
                     "generator_function_declaration"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = _txt(name_node)
                    line = node.start_point[0] + 1
                    seg = _txt(node).splitlines()[0][:110]
                    if t == "class_declaration":
                        kind = "class"
                    elif t == "method_definition":
                        kind = "method"
                    else:
                        kind = "function" if not in_class else "method"
                    out.append({"name": name, "kind": kind, "file": str(path),
                                "line": line, "signature": seg})
            if t == "variable_declarator":
                name_node = node.child_by_field_name("name")
                val = node.child_by_field_name("value")
                if name_node and _txt(name_node).isupper():
                    out.append({"name": _txt(name_node), "kind": "constant",
                                "file": str(path), "line": node.start_point[0] + 1,
                                "signature": _txt(node)[:110]})
            for child in node.named_children:
                walk(child, in_class or t == "class_declaration")

        walk(tree.root_node, False)
        return out

    def _parse_regex(self, text: str, path: Path):
        """Fallback สำหรับภาษาที่ไม่มี grammar — ค้น def/class/function แบบ regex"""
        out = []
        pats = [
            (r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(", "function"),
            (r"^\s*(?:async\s+)?function\s+([A-Za-z_$]\w*)\s*\(", "function"),
            (r"^\s*class\s+([A-Za-z_$]\w*)", "class"),
            (r"^\s*(?:pub\s+)?fn\s+([A-Za-z_]\w*)", "function"),
            (r"^\s*func\s+\([^)]*\)\s+([A-Za-z_]\w*)\s*\(", "function"),
            (r"^\s*type\s+([A-Za-z_]\w*)\s*struct", "class"),
        ]
        for i, line in enumerate(text.splitlines(), 1):
            ls = line.strip()
            for pat, kind in pats:
                m = re.match(pat, ls)
                if m:
                    out.append({"name": m.group(1), "kind": kind, "file": str(path),
                                "line": i, "signature": ls[:110]})
                    break
        return out

    # ---- query ----
    def find(self, name: str) -> dict | None:
        """go-to-definition: คืน entry นิยามของชื่อ (exact ก่อน, แล้วค่อย contains)"""
        name = name.strip()
        if not name:
            return None
        for e in self.entries:
            if e["name"] == name:
                return e
        for e in self.entries:
            if e["name"].endswith("." + name) or e["name"].startswith(name + "."):
                return e
        return None

    def refs(self, name: str, limit: int = 30) -> list:
        """ทุกบรรทัดที่อ้างอิงชื่อ (นิยาม + การใช้งาน) — grep ผ่านไฟล์ที่ indexed"""
        name = name.strip()
        out = []
        pat = re.compile(r"\b" + re.escape(name) + r"\b")
        for p in self._walk_files():
            try:
                for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if pat.search(line):
                        out.append({"file": str(p), "line": i, "text": line.strip()[:130]})
                        if len(out) >= limit:
                            return out
            except Exception:
                continue
        return out

    def summary(self) -> list:
        """นับจำนวนตาม kind + ไฟล์"""
        kinds = {}
        for e in self.entries:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        files = sorted({e["file"] for e in self.entries})
        return {"root": str(self.root), "total": len(self.entries),
                "kinds": kinds, "files": len(files)}

    def format(self, entries, max_rows=25) -> str:
        if not entries:
            return "(ไม่พบสัญลักษณ์)"
        rows = []
        for e in entries[:max_rows]:
            rel = os.path.relpath(e["file"], self.root)
            rows.append(f"{e['kind']:9} {e['name']}  @ {rel}:{e['line']}")
            rows.append(f"{'':9}   {e['signature']}")
        if len(entries) > max_rows:
            rows.append(f"... อีก {len(entries) - max_rows} รายการ")
        return "\n".join(rows)