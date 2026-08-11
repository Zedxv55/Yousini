#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vision/Image input — แทรกรูปภาพเข้าแชทเป็น content block (base64 data URL)

- พิมพ์  IMG:<path>  หรือ  [img:<path>]  ในข้อความ → กลายเป็น {"type": "image_url", ...}
- รองรับไฟล์ท้องถิ่น (.png/.jpg/.jpeg/.webp/.gif) + URL http(s) ส่งตรง
- จำกัด 3 รูป/ข้อความ และ 4MB/รูป (กัน context ระเบิด)
- ต้องใช้โมเดลที่รองรับ vision เช่น YOUSINI_MODEL=pixtral-large-latest
"""
import base64
import os
import re
from pathlib import Path

IMG_TOKEN = "[img:"
MAX_IMAGES = 3
MAX_BYTES = 4 * 1024 * 1024
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

_TOKEN_RE = re.compile(r"\[img:([^\]]+)\]")


def is_image_path(path: str) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTS


def _data_url(path: str) -> str | None:
    """อ่านไฟล์รูป → data URL (None ถ้าไฟล์ไม่มี/ใหญ่เกิน)"""
    try:
        p = Path(path)
        if not p.is_file() or p.stat().st_size > MAX_BYTES:
            return None
        raw = p.read_bytes()
        ext = p.suffix.lower().lstrip(".") or "png"
        if ext == "jpg":
            ext = "jpeg"
        return f"data:image/{ext};base64," + base64.b64encode(raw).decode("ascii")
    except Exception:
        return None


def content_with_images(text: str, cwd: str = ".") -> str | list:
    """คืน content blocks (list) ถ้ามีรูป, มิฉะนั้นข้อความเดิม (str)"""
    found = _TOKEN_RE.findall(text)
    if not found:
        return text
    blocks, count = [], 0
    # ตัด token ทั้งหมดออกจากข้อความก่อน
    rest = _TOKEN_RE.sub("", text).strip()

    def push(txt):
        if txt:
            blocks.append({"type": "text", "text": txt})

    for tok in found:
        tok = tok.strip() or "".join(found)
        if not tok:
            continue
        if count >= MAX_IMAGES:
            break
        if tok.startswith(("http://", "https://")):
            blocks.append({"type": "image_url", "image_url": {"url": tok}})
            count += 1
        else:
            # path สัมพัทธ์ → เทียบกับ cwd
            p = tok if os.path.isabs(tok) else str(Path(cwd) / tok)
            url = _data_url(p)
            if url:
                blocks.append({"type": "image_url", "image_url": {"url": url}})
                count += 1
    if not blocks:
        return rest
    if rest:
        push(rest)
    return blocks or rest