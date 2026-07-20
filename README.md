# 🤖 CodeagentX — Local Coding Agent สไตล์ Claude Code

Agent ที่รับคำสั่งภาษาธรรมชาติ แล้ว **ทำงานบนเครื่องจริงได้เอง** แบบเดียวกับ Claude Code:
รัน shell, อ่าน/เขียน/แก้ไฟล์, ค้นหาไฟล์ — ใช้โมเดล Groq (เลือกโมเดลตัวแรงได้)

พัฒนาต่อยอดจากหนังสือ *ai-agent-book* (bojieli) โดยใช้ความสามารถ Tool Calling

---

## ✨ เปิดใช้งานง่ายๆ — แค่พิมพ์ `codeagentx`

```bash
codeagentx
```
> ไม่ต้อง cd ไปไหน Launcher จะไล่ตาม symlink หาตำแหน่งจริงของ repo เอง (ใช้เครื่องอื่นได้)

หรือเรียกไฟล์โดยตรง:
```bash
python3 /home/it-admin/CodeagentX/codeagentx.py
```

ส่งคำถามหนึ่งรอบ:
```bash
codeagentx "สร้างโฟลเดอร์ demo แล้วเขียนสคริปต์ Python พิมพ์สวัสดี และรันมัน"
```

---

## 🚀 ฟีเจอร์หลัก (รุ่นล่าสุด)
- **ความจำข้าม turn** — Agent จำบริบทสนทนาได้ตลอดเซสชัน (มี trimming กันบริบทยาวเกิน และกัน tool-result ลอยๆ)
- **Streaming จริง** — ตอบสดพร้อมเรนเดอร์ Markdown สดๆ ระหว่างโมเดลพิมพ์ (ไม่รอครบแล้วค่อยแปะ)
- **UI สไตล์ Claude Code** — ใช้ `⏺` (การกระทำ) กับ `⎿` (ผลลัพธ์) แทน emoji เกิน
- **Spinner** — "⏳ กำลังคิด…" ระหว่างรอ → "⏳ กำลังเตรียมเครื่องมือ…" ตอนเรียก tool
- **Diff สี** เขียว/แดง ก่อนยืนยันเขียน/แก้ไฟล์ทุกครั้ง
- **Syntax highlighting** ตามนามสกุลไฟล์ตอนอ่าน
- **Banner** แผงเดียวสะอาด
- **คำสั่งใหม่** `/clear` `/history` `/help` + **arrow-key history ข้ามเซสชัน** (readline)

---

## 🔧 ตั้งค่า (Configuration)

ไฟล์ `.env` (มีให้แล้วในเครื่องนี้ พร้อม Groq key) ถ้าเอาไปเครื่องอื่น ให้คัดลอกจากเทมเพลต:

```bash
cp .env.example .env
# แล้วแก้ GROQ_API_KEY ใน .env (รับฟรีที่ https://console.groq.com/keys)
```

ตัวเลือกใน `.env`:
| ตัวแปร | คำอธิบาย | ค่าแนะนำ |
|---|---|---|
| `GROQ_API_KEY` | Key จาก Groq | — |
| `GROQ_BASE_URL` | Endpoint (ไม่ต้องแก้) | `https://api.groq.com/openai/v1` |
| `GROQ_MODEL` | โมเดลที่ใช้ | `openai/gpt-oss-120b` |
| `AUTO_RUN` | `1`=รัน shell ทันทีไม่ถาม (อันตราย) | `0` |
| `CONFIRM_FILES` | `0`=เขียนไฟล์ไม่ต้องถาม | `1` |
| `SHELL_TIMEOUT` | ตัดคำสั่งค้างที่ (วินาที) | `60` |

### เปลี่ยนโมเดลตัวแรง
แก้ `GROQ_MODEL` ใน `.env` หรือพิมพ์ `/model <ชื่อ>` ในแชท โมเดลที่ใช้ได้บน Groq:
- `openai/gpt-oss-120b` (ค่าเริ่มต้น แนะนำ — llama-3.3-70b-versatile ถูก Groq ประกาศเลิกใช้ 16 ส.ค. 2026)
- `qwen/qwen3.6-27b`
- `groq/compound`

---

## 🛠️ เครื่องมือ (Tools)
| เครื่องมือ | ทำอะไร |
|---|---|
| `shell` | รันคำสั่ง bash บนเครื่อง |
| `read_file` | อ่านไฟล์ (syntax highlight) |
| `write_file` | สร้าง/เขียนทับไฟล์ (แสดง diff ก่อน) |
| `edit_file` | แก้ข้อความในไฟล์ (search & replace, แสดง diff ก่อน) |
| `list_dir` | แสดงไฟล์ในโฟลเดอร์ |
| `glob` | หาไฟล์ตามรูปแบบ `*.py` |
| `grep` | ค้นหาข้อความ (regex) |
| `set_cwd` | เปลี่ยนโฟลเดอร์ทำงาน |
| `ask_user` | ถามผู้ใช้ (เมื่อขาดข้อมูลสำคัญเท่านั้น) |

---

## 🔐 ความปลอดภัย
ตัวนี้รันคำสั่งบนเครื่องคุณได้จริง จึงมีระบบป้องกัน:
- **ขออนุมัติก่อนรัน shell** — แสดงคำสั่ง ถาม `รัน? [y/N/e=แก้ไข]` (พิมพ์ `e` แก้ก่อนรัน)
- **กันคำสั่งอันตราย** — `rm -rf`, `dd`, `shutdown` ฯลฯ เตือน + ขออนุมัติเสมอ
- **ขออนุมัติก่อนเขียน/แก้ไฟล์** (แสดง diff สี)
- หากโมเดล生成 tool call พัง ระบบจะขอคำตอบแบบปกติแทน (ไม่ crash)

---

## ⌨️ คำสั่งในแชท
- `/help` — แสดงคำสั่งทั้งหมด
- `/clear` — ล้างประวัติการสนทนา
- `/history` — แสดงประวัติข้อความทั้งหมด
- `/approve on` — รัน shell ทันทีโดยไม่ถาม (เร็วแต่ระวัง)
- `/approve off` — กลับไปถามก่อนรัน (ค่าเริ่มต้น แนะนำ)
- `/cwd <โฟลเดอร์>` — เปลี่ยนที่ทำงาน
- `/model <ชื่อ>` — เปลี่ยนโมเดล
- `/exit` — ออก

---

## 📦 ติดตั้งบนเครื่องใหม่
```bash
git clone https://github.com/Zedxv55/CodeagentX.git
cd CodeagentX
pip install -r requirements.txt
cp .env.example .env        # แล้วใส่ GROQ_API_KEY
# ติดตั้งคำสั่ง codeagentx ลง PATH ด้วย symlink (แนะนำ เพราะ launcher ตาม symlink ได้):
ln -s "$(pwd)/codeagentx" ~/.local/bin/codeagentx
# หรือถ้าใช้ /usr/local/bin:
# sudo ln -s "$(pwd)/codeagentx" /usr/local/bin/codeagentx
```
> ใช้ `ln -s` ไม่ใช่ `cp` เพื่อให้ launcher ไล่ตาม symlink หาโฟลเดอร์ repo จริงได้ แม้ย้าย/ลิงก์ข้ามที่

---

## 🧠 Skill
ความสามารถสไตล์ Claude Code ถูกเขียนไว้ใน `SKILL.md` (และฝังใน `codeagentx.py`)
สามารถ copy ไปวางเป็น system prompt ของ Agent ตัวอื่นได้ทันที

---

⚠️ **คำเตือน:** ไฟล์ `.env` มี API Key ห้ามแชร์/อัปโหลดสาธารณะ
