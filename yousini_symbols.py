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
        self._cache_size = {}
        try:
            if use_cache and self.cache_path.is_file():
                self._cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
                self.entries = self._cache.get("entries", [])
                self.by_file = self._cache.get("by_file", {})
                self._cache_size = self._cache.get("size", {})
        except Exception:
            self._cache = None

    def _is_stale(self) -> bool:
        """ตรวจว่า cache ล้าสมัยหรือไม่ — เทียบ mtime ns และขนาดไฟล์
        เกณฑ์: ไฟล์เปลี่ยนจริงเมื่อ mtime ใหม่กว่าเก่า > 50ms หรือขนาดต่างกัน
        (กัน false-negative บน filesystem ความละเอียดต่ำอย่าง FAT/ext3 ที่ตัดเศษ mtime)
        และไม่กลบการเปลี่ยนที่เกิดขึ้นเร็วในหนึ่งวินาที)"""
        if not self._cache:
            return True
        try:
            for raw, mtime in self.by_file.items():
                p = Path(raw)
                if not p.is_file():
                    return True
                st = p.stat()
                try:
                    real = st.st_mtime_ns
                except AttributeError:
                    real = int(st.st_mtime * 1e9)
                # normalize cache ที่อาจเก็บเป็น float วินาทีหรือ ns
                cached_ns = int(float(mtime) * 1e9) if float(mtime) < 1e15 else int(mtime)
                # ขนาดต่าง = เปลี่ยนแน่นอน
                if getattr(st, 'st_size', 0) != self._cache_size.get(raw, 0):
                    return True
                if real > cached_ns + 50_000_000:   # ใหม่กว่า > 50 ms
                    return True
        except Exception:
            return True
        return False

    def _save_cache(self):
        try:
            data = {"entries": self.entries, "by_file": self.by_file,
                    "size": self._cache_size}
            self.cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self._cache = data
        except Exception:
            pass

    def _file_meta(self, p: Path):
        """อ่าน (mtime_ns, size) อย่างปลอดภัย"""
        try:
            st = p.stat()
            try:
                return st.st_mtime_ns, st.st_size
            except AttributeError:
                return int(st.st_mtime * 1e9), st.st_size
        except Exception:
            return 0, 0

    # ---- build ----
    def _walk_files(self):
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in self.ignore]
            for fn in filenames:
                p = Path(dirpath) / fn
                if p.suffix in SUPPORTED_EXT:
                    yield p

    def build(self):
        self.entries, self.by_file, self._cache_size = [], {}, {}
        for p in self._walk_files():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            try:
                got = self._parse_file(p, text)
            except Exception:
                # ไฟล์ parse ไม่ได้ — ใช้ regex fallback แทนการข้ามทั้งไฟล์
                got = self._parse_regex(text, p)
            if got:
                self.entries.extend(got)
                mtime_ns, size = self._file_meta(p)
                self.by_file[str(p)] = mtime_ns
                self._cache_size[str(p)] = size
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
        out = []
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
        try:
            parser = Parser(langs[path.suffix])
            tree = parser.parse(bytes(text, "utf-8"))
        except Exception:
            return self._parse_regex(text, path)
        out = []

        def _field(node, field: str):
            """เข้าถึง field อย่างปลอดภัย — grammar ใหม่/เก่าอาจเปลี่ยนชื่อ field
            ถ้า child_by_field_name ให้ None จะ scan children เองแทน (ไม่ throw KeyError)"""
            try:
                n = node.child_by_field_name(field)
                if n is not None:
                    return n
            except Exception:
                pass
            # fallback: field 'name' อยู่ใน identifier / property_identifier / binding_identifier
            for c in node.children:
                if c.type in ("identifier", "property_identifier",
                              "binding_identifier", "shorthand_property_identifier"):
                    if c.start_byte >= node.start_byte:
                        return c
            return None

        def walk(node, in_class):
            t = node.type
            try:
                if t in ("function_declaration", "class_declaration", "method_definition",
                         "generator_function_declaration"):
                    name_node = _field(node, "name")
                    if name_node is not None:
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
                    name_node = _field(node, "name")
                    if name_node is not None:
                        txt = _txt(name_node)
                        if txt.isupper():
                            out.append({"name": txt, "kind": "constant",
                                        "file": str(path), "line": node.start_point[0] + 1,
                                        "signature": _txt(node)[:110]})
                for child in node.named_children:
                    walk(child, in_class or t == "class_declaration")
            except Exception:
                # node เดียวไม่ควรทำให้ทั้งไฟล์อินเด็กซ์ไม่สำเร็จ
                pass

        walk(tree.root_node, False)
        return out

    def _parse_regex(self, text: str, path: Path):
        """Fallback สำหรับภาษาที่ไม่มี grammar — ค้น def/class/function/constant แบบ regex
        แยก method (ใน Python: def ที่มี indent) vs function (ระดับโมดูล) ได้ —
        และ JS method ที่ตามหลัง class { (track class depth)"""
        out = []
        pats = [
            # (regex, kind, ใช้ indentation จับ method/constant)
            (r"^(async\s+)?def\s+([A-Za-z_]\w*)\s*\(", "function"),
            (r"^(async\s+)?function\s+([A-Za-z_$]\w*)\s*\(", "function"),
            (r"^([A-Za-z_$]\w*)\s*\(", "function"),
            (r"^class\s+([A-Za-z_$]\w*)", "class"),
            (r"^(?:pub\s+)?fn\s+([A-Za-z_]\w*)", "function"),
            (r"^func\s+\([^)]*\)\s+([A-Za-z_]\w*)\s*\(", "function"),
            (r"^type\s+([A-Za-z_]\w*)\s*struct", "class"),
            (r"^([A-Z][A-Z0-9_]{1,})\s*=", "constant"),
            (r"^(?:const|let|var)\s+([A-Z][A-Z0-9_]{1,})\s*=", "constant"),
        ]
        ext = path.suffix
        # JS/TS: class depth — เพิ่มเฉพาะตอนเข้า class declaration block,
        # ลดเมื่อ braces ภายใน class สมดุล (ไม่นับ function block ปกติ)
        class_depth = 0
        for i, line in enumerate(text.splitlines(), 1):
            ls = line.strip()
            if ext in (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"):
                if class_depth == 0 and re.match(r"^class\s+[A-Za-z_$]\w*", ls):
                    class_depth = 1 if "{" in ls else -1   # -1 = รอ { บรรทังถัดไป
                elif class_depth > 0:
                    class_depth += ls.count("{") - ls.count("}")
                    if class_depth <= 0:
                        class_depth = 0
                elif class_depth == -1 and "{" in ls:
                    class_depth = 1
            for pat, kind in pats:
                m = re.match(pat, ls)
                if not m:
                    continue
                name = m.group(1) if kind != "function" else (
                    m.group(2) if m.lastindex == 2 else m.group(1))
                if kind == "function" and m.lastindex == 2:
                    name = m.group(2)
                # Python: def ที่มี indentation = method (อยู่ใน class block)
                if kind == "function" and ext == ".py":
                    indented = len(line) - len(line.lstrip()) > 0
                    if indented:
                        out.append({"name": name, "kind": "method", "file": str(path),
                                    "line": i, "signature": ls[:110]})
                        break
                # JS/TS: function/method ที่อยู่ภายใน class depth > 0 = method
                if kind == "function" and ext in (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"):
                    if class_depth > 0:
                        out.append({"name": name, "kind": "method", "file": str(path),
                                    "line": i, "signature": ls[:110]})
                        break
                out.append({"name": name, "kind": kind, "file": str(path),
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

    def refs(self, name: str, limit: int = 30, focus_file: str = None) -> list:
        """ทุกบรรทัดที่อ้างอิงชื่อ (นิยาม + การใช้งาน) — grep ผ่านไฟล์ที่ indexed
        เรียง: (1) ไฟล์ focus (ไฟล์ที่ user query) ก่อนเสมอ → ติดตา result แรด
        (2) บรรทัดนิยาม แล้วตามด้วยการใช้งาน — ทำให้ go-to-ref เป็น deterministic"""
        name = name.strip()
        focus_file = focus_file or None
        defs, focus_refs, other_refs = [], [], []
        pat = re.compile(r"\b" + re.escape(name) + r"\b")
        defined_files = {e["file"] for e in self.entries if e["name"] == name}
        for p in self._walk_files():
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue
            for i, line in enumerate(lines, 1):
                if pat.search(line):
                    rec = {"file": str(p), "line": i, "text": line.strip()[:130]}
                    is_def = (str(p) in defined_files
                              and i == self._def_line(name, str(p)))
                    if focus_file and str(p) == str(focus_file):
                        (defs if is_def else focus_refs).append(rec)
                    else:
                        (defs if is_def else other_refs).append(rec)
        out = focus_refs + defs + other_refs
        return out[:limit]

    def _def_line(self, name: str, file: str):
        """บรรทัดที่นิยามในไฟล์นั้น (0 = ไม่มี)"""
        for e in self.entries:
            if e["name"] == name and e["file"] == file:
                return e["line"]
        return 0

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