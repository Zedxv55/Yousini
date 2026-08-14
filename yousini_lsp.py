#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yousini LSP — Language Server Protocol (stdio, JSON-RPC 2.0)

Workspace-intelligence server แบบ LSP: hover / go-to-definition / references /
document symbols / workspace symbols / completion สำหรับภาษาใน SymbolIndex
(Python, JS/TS, Go, C, Rust และอื่น ๆ ผ่าน fallback regex)

- ใช้ tree-sitter index (yousini_symbols) เป็นตัวชี้เป้า + AST ของไฟล์ที่เปิดอยู่
- โหมด stdio: อ่าน/เขียน framed JSON-RPC ผ่าน stdin/stdout (สำหรับ editor)
- คลาส LSPEngine ใช้ร่วมกับ HTTP endpoint (/api/lsp/*) ของ web server ได้
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from yousini_symbols import SymbolIndex

LSP_VERSION = "3.0.0"
_WORD_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")


# --- LSP enums ---
class SymbolKind:
    CLASS = 5
    METHOD = 6
    FIELD = 7
    FUNCTION = 12
    VARIABLE = 13
    CONSTANT = 14
    STRUCT = 23
    EVENT = 24


class CompletionKind:
    METHOD = 2
    FUNCTION = 3
    CLASS = 7
    MODULE = 9
    PROPERTY = 10
    VARIABLE = 6
    CONSTANT = 21
    STRUCT = 22
    EVENT = 23
    KEYWORD = 14


_KIND_MAP = {
    "function": SymbolKind.FUNCTION,
    "method": SymbolKind.METHOD,
    "class": SymbolKind.CLASS,
    "struct": SymbolKind.STRUCT,
    "constant": SymbolKind.CONSTANT,
    "variable": SymbolKind.VARIABLE,
    "field": SymbolKind.FIELD,
    "event": SymbolKind.EVENT,
}

_COMPLETION_KIND = {
    "function": CompletionKind.FUNCTION,
    "method": CompletionKind.METHOD,
    "class": CompletionKind.CLASS,
    "struct": CompletionKind.STRUCT,
    "constant": CompletionKind.CONSTANT,
    "variable": CompletionKind.VARIABLE,
    "field": CompletionKind.PROPERTY,
    "event": CompletionKind.EVENT,
}

_DEF_TYPES = {
    "function_definition", "class_definition", "method_definition",
    "function_declaration", "class_declaration",
    "generator_function_declaration", "method_signature",
    "function_signature", "class", "struct", "impl",
}


def _txt(node) -> str:
    try:
        return node.text.decode("utf-8", errors="replace")
    except Exception:
        try:
            return bytes(node.text).decode("utf-8", errors="replace")
        except Exception:
            return str(node)


def _path_to_uri(p) -> str:
    return Path(p).resolve().as_uri()


def _uri_to_path(uri: str) -> Path:
    u = urlparse(uri)
    raw = unquote(u.path)
    if sys.platform == "win32":
        if len(raw) > 2 and raw[0] == "/" and raw[2] == ":":
            raw = raw[1:]
        if u.netloc and u.netloc.lower() != "localhost":
            raw = "//" + u.netloc + raw
    elif u.netloc and u.netloc.lower() != "localhost":
        raw = "//" + u.netloc + raw
    return Path(raw)


def _utf16_to_cp(text: str, char: int) -> int:
    """แปลงตำแหน่ง UTF-16 code units → ดัชนี code point (LSP ใช้ UTF-16)"""
    i, cp = 0, 0
    n = len(text)
    while i < char and cp < n:
        c = ord(text[cp])
        if 0xD800 <= c <= 0xDBFF and cp + 1 < n and 0xDC00 <= ord(text[cp + 1]) <= 0xDFFF:
            i += 2
            cp += 2
        else:
            i += 1
            cp += 1
    return min(cp, n)


def _byte_to_utf16_col(text: str, byte_col: int) -> int:
    """แปลงคอลัมน์แบบ byte (tree-sitter) → UTF-16 code units"""
    prefix = text[:byte_col]
    out = 0
    for ch in prefix:
        o = ord(ch)
        if 0xD800 <= o <= 0xDBFF:
            out += 2
        else:
            out += 1
    return out


def _word_at(text: str, line: int, char: int):
    """คำ (identifier) ที่ตำแหน่ง line/char (0-based, char=UTF-16)"""
    lines = text.split("\n")
    if line < 0 or line >= len(lines):
        return None
    ln = lines[line]
    cp = _utf16_to_cp(ln, char)
    for m in _WORD_RE.finditer(ln):
        if m.start() <= cp <= m.end():
            return {
                "name": m.group(0),
                "start": {"line": line, "character": _byte_to_utf16_col(ln, m.start())},
                "end": {"line": line, "character": _byte_to_utf16_col(ln, m.end())},
            }
    return None


def _ident_kind(kind: str) -> int:
    return _KIND_MAP.get(kind, SymbolKind.FUNCTION)


class LSPEngine:
    """แกนกลาง LSP — ใช้ร่วมกันระหว่าง stdio server และ HTTP endpoints"""

    def __init__(self, root: str = ".", use_cache: bool = True):
        self.root = str(Path(root).resolve())
        self.use_cache = use_cache
        self._idx = None
        self._docs = {}          # uri -> text (ไฟล์ที่ editor เปิดอยู่)

    # ---- index ----
    def _index(self) -> SymbolIndex:
        if self._idx is None or self._idx._is_stale():
            self._idx = SymbolIndex(self.root, use_cache=self.use_cache)
        return self._idx

    # ---- documents ----
    def _text(self, uri: str) -> str:
        if uri in self._docs:
            return self._docs[uri]
        try:
            p = _uri_to_path(uri)
            return p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    def set_text(self, uri: str, text: str):
        self._docs[uri] = text

    def drop_text(self, uri: str):
        self._docs.pop(uri, None)

    # ---- core queries ----
    def _target(self, uri: str, line: int, char: int):
        """หาชื่อเป้าหมาย + ตำแหน่งคำ → ข้อมูลนิยาม (ถ้ามี)"""
        text = self._text(uri)
        w = _word_at(text, line, char)
        if not w:
            return None
        name = w["name"]
        hit = self._index().find(name)
        return {"name": name, "word": w, "hit": hit, "text": text}

    def hover(self, uri: str, line: int, char: int):
        """Markdown hover: kind + signature + บรรทัดนิยาม + ตำแหน่ง"""
        t = self._target(uri, line, char)
        if not t:
            return None
        name, hit = t["name"], t["hit"]
        if not hit:
            return None
        kind = hit["kind"]
        try:
            p = Path(hit["file"])
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            lines = []
        snippet = hit.get("signature", "")
        if hit["line"] and 1 <= hit["line"] <= len(lines):
            snippet = "\n".join(lines[hit["line"] - 1: hit["line"] + 4])
        rel = os_relpath(hit["file"], self.root)
        return {
            "name": name,
            "kind": kind,
            "markdown": (f"```{lang_hint(hit['file'])}\n{snippet}\n```\n"
                         f"**{kind}** · `{rel}:{hit['line']}`"),
            "location": {"uri": _path_to_uri(hit["file"]),
                         "range": _range_for(hit["file"], hit.get("line", 1), name)},
        }

    def definition(self, uri: str, line: int, char: int):
        t = self._target(uri, line, char)
        if not t or not t["hit"]:
            return None
        hit = t["hit"]
        return {"uri": _path_to_uri(hit["file"]),
                "range": _range_for(hit["file"], hit.get("line", 1), hit["name"])}

    def references(self, uri: str, line: int, char: int, limit: int = 50):
        t = self._target(uri, line, char)
        if not t:
            return []
        refs = self._index().refs(t["name"], limit=limit)
        out = []
        for r in refs:
            try:
                text = Path(r["file"]).read_text(encoding="utf-8", errors="replace")
            except Exception:
                text = ""
            out.append({"uri": _path_to_uri(r["file"]),
                        "range": _range_for(r["file"], r["line"], t["name"]),
                        "text": r.get("text", "")})
        return out

    def document_symbols(self, uri: str):
        """DocumentSymbol แบบ hierarchical — tree-sitter ถ้ามี grammar, ไม่งั้น flat"""
        text = self._text(uri)
        p = _uri_to_path(uri)
        if not text.strip():
            return []
        ts = self._document_symbols_ts(p, text)
        if ts is not None:
            return ts
        return self._document_symbols_flat(p, text)

    def _document_symbols_ts(self, p: Path, text: str):
        si = self._index()
        Parser, langs = si._ts_parser()
        lang = langs.get(p.suffix)
        if not lang:
            return None
        try:
            tree = Parser(lang).parse(bytes(text, "utf-8"))
        except Exception:
            return None

        def collect(node, depth=0):
            if depth > 40:
                return []
            out = []
            t = node.type
            if t in _DEF_TYPES:
                name_node = node.child_by_field_name("name")
                if name_node:
                    kind = _kind_for_ts(t, p.suffix)
                    name = _txt(name_node)
                    srow, scol = node.start_point
                    erow, ecol = node.end_point
                    nrow, ncol = name_node.start_point
                    out.append({
                        "name": name,
                        "kind": _ident_kind(kind),
                        "detail": _txt(node).splitlines()[0][:110] if _txt(node) else "",
                        "range": _range_pts(text, srow, scol, erow, ecol),
                        "selectionRange": _range_pts(text, nrow, ncol, nrow, ncol + len(name)),
                        "children": [],
                    })
                    for c in node.named_children:
                        out[-1]["children"].extend(collect(c, depth + 1))
                    return out
            for c in node.named_children:
                out.extend(collect(c, depth + 1))
            return out

        return collect(tree.root_node)

    def _document_symbols_flat(self, p: Path, text: str):
        si = self._index()
        entries = [e for e in si.entries if e["file"] == str(p)]
        out = []
        for e in entries:
            line = max(0, e.get("line", 1) - 1)
            out.append({
                "name": e["name"],
                "kind": _ident_kind(e["kind"]),
                "detail": e.get("signature", "")[:110],
                "range": {"start": {"line": line, "character": 0},
                          "end": {"line": line, "character": 0}},
                "selectionRange": {"start": {"line": line, "character": 0},
                                   "end": {"line": line, "character": 0}},
                "children": [],
            })
        return out

    def workspace_symbols(self, query: str = "", limit: int = 100):
        q = (query or "").strip().lower()
        si = self._index()
        hits = [e for e in si.entries if q in e["name"].lower()] if q else si.entries
        hits = hits[:limit]
        out = []
        for e in hits:
            line = max(0, e.get("line", 1) - 1)
            out.append({
                "name": e["name"],
                "kind": _ident_kind(e["kind"]),
                "location": {"uri": _path_to_uri(e["file"]),
                             "range": {"start": {"line": line, "character": 0},
                                       "end": {"line": line, "character": 0}}},
                "containerName": "",
            })
        return out

    def completion(self, uri: str, line: int, char: int, limit: int = 60):
        """completion แบบง่าย: สัญลักษณ์จาก workspace + identifier ในไฟล์ปัจจุบัน"""
        text = self._text(uri)
        w = _word_at(text, line, char)
        prefix = (w["name"] if w else "") if line < len(text.split("\n")) else ""
        if w and w["start"]["character"] < char:
            # ตัดส่วนที่ยังพิมพ์ไม่จบ (ถ้าคำครอบ cursor กลางคำ)
            pass
        prefix = prefix or ""
        seen, items = set(), []
        si = self._index()
        names = [e["name"] for e in si.entries] + list(
            re.findall(r"\b[A-Za-z_$][A-Za-z0-9_$]*\b", text))
        kinds = {e["name"]: e["kind"] for e in si.entries}
        for name in names:
            if name in seen or (prefix and not name.lower().startswith(prefix.lower())):
                continue
            seen.add(name)
            kind = _COMPLETION_KIND.get(kinds.get(name, ""), CompletionKind.VARIABLE)
            items.append({"label": name, "kind": kind})
            if len(items) >= limit:
                break
        items.sort(key=lambda x: (not x["label"].lower().startswith(prefix.lower()),
                                  x["label"].lower()))
        return items

    def summary(self):
        s = self._index().summary()
        s["root"] = self.root
        return s


def _kind_for_ts(t: str, ext: str) -> str:
    if t in ("class_definition", "class_declaration"):
        return "class"
    if t in ("method_definition", "method_signature"):
        return "method"
    if t in ("function_definition", "function_declaration",
             "generator_function_declaration", "function_signature"):
        return "function"
    if t == "struct":
        return "struct"
    if t == "class":
        return "class"
    if t == "impl":
        return "struct"
    return "function"


def _range_for(file, line_1based, name):
    """range ครอบชื่อที่บรรทัดที่กำหนด (line 1-based → 0-based)"""
    ln = max(0, line_1based - 1)
    try:
        text = Path(file).read_text(encoding="utf-8", errors="replace").splitlines()
        src = text[ln] if ln < len(text) else ""
    except Exception:
        src = ""
    idx = src.find(name)
    if idx < 0:
        idx, end = 0, 0
    else:
        end = idx + len(name)
    return {"start": {"line": ln, "character": _byte_to_utf16_col(src, idx)},
            "end": {"line": ln, "character": _byte_to_utf16_col(src, end)}}


def _range_pts(text, srow, scol, erow, ecol):
    lines = text.split("\n")

    def col(row, c):
        if 0 <= row < len(lines):
            return _byte_to_utf16_col(lines[row], c)
        return 0

    return {"start": {"line": srow, "character": col(srow, scol)},
            "end": {"line": erow, "character": col(erow, ecol)}}


def lang_hint(path: str) -> str:
    ext = Path(path).suffix.lower()
    return {
        ".py": "python", ".js": "javascript", ".mjs": "javascript",
        ".cjs": "javascript", ".ts": "typescript", ".tsx": "typescriptreact",
        ".jsx": "javascript", ".go": "go", ".c": "c", ".h": "c",
        ".rs": "rust",
    }.get(ext, "text")


def os_relpath(path: str, root: str) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except Exception:
        return str(path)


# ---------------------------------------------------------------------------
# stdio JSON-RPC 2.0 (Content-Length framing) — สำหรับ editor
# ---------------------------------------------------------------------------
class StdioServer:
    def __init__(self, engine: LSPEngine, root: str = "."):
        self.engine = engine
        self.root = root
        self._shutdown = False

    def _log(self, msg: str):
        try:
            sys.stderr.write("[yousini-lsp] " + msg + "\n")
            sys.stderr.flush()
        except Exception:
            pass

    # ---- framing ----
    def _read_message(self):
        length = None
        while True:
            line = sys.stdin.buffer.readline()
            if not line:
                raise EOFError
            if line in (b"\r\n", b"\n"):
                break
            parts = line.split(b":", 1)
            if len(parts) == 2 and parts[0].strip().lower() == b"content-length":
                try:
                    length = int(parts[1].strip())
                except Exception:
                    length = None
        if length is None:
            return None
        body = sys.stdin.buffer.read(length)
        if len(body) < length:
            raise EOFError
        try:
            return json.loads(body.decode("utf-8"))
        except Exception:
            return None

    def _send(self, obj: dict):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        sys.stdout.buffer.write(b"Content-Length: %d\r\n\r\n" % len(data))
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()

    # ---- dispatch ----
    def _respond(self, mid, result=None, error=None):
        msg = {"jsonrpc": "2.0", "id": mid}
        if error is not None:
            msg["error"] = error
        else:
            msg["result"] = result
        self._send(msg)

    def _capabilities(self):
        return {
            "capabilities": {
                "textDocumentSync": {"openClose": True, "change": 1,
                                     "save": {"includeText": True}},
                "hoverProvider": True,
                "definitionProvider": True,
                "referencesProvider": True,
                "documentSymbolProvider": True,
                "workspaceSymbolProvider": True,
                "completionProvider": {"triggerCharacters": [".", "_", "$"]},
            },
            "serverInfo": {"name": "Yousini LSP", "version": LSP_VERSION},
        }

    def _dispatch(self, msg: dict):
        if not isinstance(msg, dict):
            return
        method = msg.get("method")
        mid = msg.get("id")
        params = msg.get("params") or {}

        if method == "initialize":
            root = params.get("rootUri") or params.get("workspaceFolders") or None
            if isinstance(root, list) and root:
                root = root[0].get("uri") if isinstance(root[0], dict) else None
            if root:
                try:
                    self.engine.root = str(_uri_to_path(root))
                    self.engine._idx = None
                except Exception:
                    pass
            self._respond(mid, self._capabilities())
            self._log("initialized on root " + self.engine.root)
            return
        if method == "initialized":
            return
        if method == "shutdown":
            self._shutdown = True
            self._respond(mid, None)
            return
        if method == "exit":
            raise SystemExit(0 if self._shutdown else 1)
        if method == "textDocument/didOpen":
            td = params.get("textDocument", {})
            self.engine.set_text(td.get("uri", ""), td.get("text", ""))
            return
        if method == "textDocument/didChange":
            td = params.get("textDocument", {})
            changes = params.get("contentChanges", [])
            if changes:
                self.engine.set_text(td.get("uri", ""), changes[-1].get("text", ""))
            return
        if method == "textDocument/didSave":
            td = params.get("textDocument", {})
            if td.get("text") is not None:
                self.engine.set_text(td.get("uri", ""), td["text"])
            return
        if method == "textDocument/didClose":
            td = params.get("textDocument", {})
            self.engine.drop_text(td.get("uri", ""))
            return
        if method == "textDocument/hover":
            pos = params.get("position", {})
            uri = params.get("textDocument", {}).get("uri", "")
            res = self.engine.hover(uri, pos.get("line", 0), pos.get("character", 0))
            if res:
                contents = {"kind": "markdown", "value": res["markdown"]}
                self._respond(mid, {"contents": contents})
            else:
                self._respond(mid, None)
            return
        if method == "textDocument/definition":
            pos = params.get("position", {})
            uri = params.get("textDocument", {}).get("uri", "")
            self._respond(mid, self.engine.definition(uri, pos.get("line", 0),
                                                      pos.get("character", 0)))
            return
        if method == "textDocument/references":
            pos = params.get("position", {})
            uri = params.get("textDocument", {}).get("uri", "")
            self._respond(mid, self.engine.references(uri, pos.get("line", 0),
                                                      pos.get("character", 0)))
            return
        if method == "textDocument/documentSymbol":
            uri = params.get("textDocument", {}).get("uri", "")
            self._respond(mid, self.engine.document_symbols(uri))
            return
        if method == "workspace/symbol":
            self._respond(mid, self.engine.workspace_symbols(params.get("query", "")))
            return
        if method == "textDocument/completion":
            pos = params.get("position", {})
            uri = params.get("textDocument", {}).get("uri", "")
            items = self.engine.completion(uri, pos.get("line", 0),
                                           pos.get("character", 0))
            self._respond(mid, {"isIncomplete": False, "items": items})
            return
        if mid is not None:
            self._respond(mid, None,
                          {"code": -32601, "message": f"method ไม่รู้จัก: {method}"})

    def serve(self):
        while True:
            try:
                msg = self._read_message()
            except EOFError:
                break
            if msg is None:
                continue
            try:
                self._dispatch(msg)
            except SystemExit as e:
                raise e
            except Exception as e:
                self._log("error: " + str(e))
                if msg.get("id") is not None:
                    self._respond(msg["id"], None,
                                  {"code": -32603, "message": str(e)})


def lsp_main(root: str = ".", log: bool = True):
    """จุดเริ่มต้น `yousini lsp` — เขียน log ไป stderr เพื่อกัน stdout เสีย"""
    if log:
        sys.stderr.write("Yousini LSP server started (stdio). root=%s\n" % root)
        sys.stderr.flush()
    engine = LSPEngine(root=root)
    StdioServer(engine, root=root).serve()


if __name__ == "__main__":
    lsp_main(root=sys.argv[1] if len(sys.argv) > 1 else ".")