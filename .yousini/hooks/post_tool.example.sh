#!/bin/sh
# post_tool hook ตัวอย่าง — รันหลัง tool ทำงานเสร็จ (best-effort, ไม่影響ผลลัพธ์)
# รับ JSON ทาง stdin: {"tool": "...", "args": {...}, "result": "..."}
# รับ env: YOUSINI_TOOL, YOUSINI_CWD
#
# ตัวอย่าง: ถ้า shell คืน exit code ไม่ใช่ 0 ให้เตือนทาง stderr (เข้าล็อก)

payload=$(cat)
tool="$YOUSINI_TOOL"

if [ "$tool" = "shell" ]; then
  result=$(printf '%s' "$payload" | grep -o '\[exit code: [0-9]*\]' | grep -o '[0-9]*')
  if [ -n "$result" ] && [ "$result" != "0" ]; then
    echo "[post_tool] shell จบด้วย exit code $result — ตรวจสอบผลลัพธ์" >&2
  fi
fi

exit 0
