#!/bin/sh
# pre_tool hook ตัวอย่าง — รันก่อนทุกครั้งที่ Agent จะเรียก tool
# รับ JSON ทาง stdin: {"tool": "...", "args": {...}}
# รับ env: YOUSINI_TOOL, YOUSINI_CWD
# - exit 0  → อนุญาตให้รัน tool นี้
# - exit != 0 → บล็อก (stdout จะถูกส่งกลับเป็นเหตุผลให้โมเดลทราบ)
#
# ตัวอย่าง: สั่งห้าม tool 'shell' ที่คำสั่งมีคำว่า 'curl ... | bash' (ดาวน์โหลดแล้วรัน)

payload=$(cat)
tool="$YOUSINI_TOOL"

if [ "$tool" = "shell" ]; then
  cmd=$(printf '%s' "$payload" | grep -o '"command"[ ]*:[ ]*"[^"]*"' | sed 's/.*:[ ]*"//; s/"$//')
  case "$cmd" in
    *"| bash"*|*"| sh"*|*"curl "*"|"*|*"wget "*"|"*)
      echo "ปฏิเสธ: ห้ามดาวน์โหลดสคริปต์จากเน็ตแล้วรันโดยไม่ตรวจสอบ"
      exit 3
      ;;
  esac
fi

# ไม่อนุญาตให้ shell เขียนทับไฟล์ระบบ
if [ "$tool" = "shell" ]; then
  cmd=$(printf '%s' "$payload" | grep -o '"command"[ ]*:[ ]*"[^"]*"' | sed 's/.*:[ ]*"//; s/"$//')
  case "$cmd" in
    *"/etc/"*|*"/usr/"*|*"sudo "*)
      echo "ปฏิเสธ: ห้ามแตะไฟล์ระบบหรือใช้ sudo"
      exit 4
      ;;
  esac
fi

exit 0
