# Zelax

Local Coding Agent สไตล์ Claude Code — รับคำสั่งภาษาธรรมชาติ แล้วทำงานบนเครื่องจริงได้เอง:
รัน shell, อ่าน/เขียน/แก้ไฟล์, ค้นหาไฟล์ ผ่านทุก OpenAI-compatible API (Groq, OpenAI, OpenRouter, DeepSeek, Mistral ฯลฯ)

พัฒนาต่อยอดจากหนังสือ *ai-agent-book* (bojieli) โดยใช้ความสามารถ Tool Calling

---

## เริ่มต้นใช้งาน

เปิด terminal แล้วพิมพ์:

```bash
zelax
```

หรือส่งคำสั่งหนึ่งรอบโดยตรง:

```bash
zelax "สร้างโฟลเดอร์ demo แล้วเขียนสคริปต์ Python พิมพ์สวัสดี และรันมัน"
```

---

## ความสามารถหลัก

- ความจำข้าม turn — Agent จำบริบทการสนทนาได้ตลอดเซสชัน (มี trimming กันบริบทยาวเกิน และกัน tool-result ลอยๆ)
- Streaming จริง — ตอบสดพร้อมเรนเดอร์ Markdown สดๆ ระหว่างโมเดลพิมพ์
- UI สไตล์ Claude Code — ใช้ `⏺` (การกระทำ) กับ `⎿` (ผลลัพธ์)
- Spinner — "กำลังคิด…" ระหว่างรอ → "กำลังเตรียมเครื่องมือ…" ตอนเรียก tool
- Diff สี เขียว/แดง ก่อนยืนยันเขียน/แก้ไฟล์ทุกครั้ง
- Syntax highlighting ตามนามสกุลไฟล์ตอนอ่าน
- Banner แผงเดียวสะอาด
- คำสั่ง `/clear` `/history` `/help` + arrow-key history ข้ามเซสชัน (readline)

---

## ตัวอย่างหน้าจอ (UX/UI CLI)

```text
┌──────────────────────────────────────────────────────────┐
│ Zelax  —  ผู้ช่วยเขียนโค้ดบนเครื่อง (สไตล์ Claude Code)      │
│                                                          │
│ โมเดล: openai/gpt-oss-120b                               │
│ Endpoint: https://api.groq.com/openai/v1                 │
│ โฟลเดอร์: /home/it-admin/project                         │
│ ขออนุมัติ shell: เปิด (ถามก่อน)                           │
│ พิมพ์งาน  |  /help /clear /history /model /cwd /approve /exit │
└──────────────────────────────────────────────────────────┘

❯ สร้างไฟล์ hello.py ที่พิมพ์สวัสดี แล้วรัน
กำลังคิด…
⏺ write_file({"path": "hello.py", "content": "print('สวัสดี')"})
╭───────────────────────── สร้างไฟล์: hello.py ─────────────────────────╮
│ print('สวัสดี')                                                       │
╰──────────────────────────────────────────────────────────────────────╯
⎿ เขียนสำเร็จ: hello.py (15 ตัวอักษร)
กำลังเตรียมเครื่องมือ…
⏺ shell(python3 hello.py)
⎿ [exit code: 0]
สวัสดี
```

---

## ตั้งค่า (Configuration)

ไฟล์ `.env` (มีให้แล้วในเครื่องนี้ พร้อม key) ถ้าเอาไปเครื่องอื่น ให้คัดลอกจากเทมเพลต:

```bash
cp .env.example .env
# แล้วแก้ ZELAX_API_KEY ใน .env
```

ตัวแปรใน `.env`:

| ตัวแปร | คำอธิบาย | ค่าแนะนำ |
|---|---|---|
| `ZELAX_API_KEY` | API Key จาก provider ที่เลือก | — |
| `ZELAX_BASE_URL` | Endpoint (OpenAI-compatible) | `https://api.groq.com/openai/v1` |
| `ZELAX_MODEL` | โมเดลที่ใช้ | `openai/gpt-oss-120b` |
| `AUTO_RUN` | `1`=รัน shell ทันทีไม่ถาม (อันตราย) | `0` |
| `CONFIRM_FILES` | `0`=เขียนไฟล์ไม่ต้องถาม | `1` |
| `SHELL_TIMEOUT` | ตัดคำสั่งค้างที่ (วินาที) | `60` |

### เปลี่ยน Provider / โมเดล

Zelax เปิดรับทุก OpenAI-compatible API ไม่ผูกกับ Groq เพียงแก้ `ZELAX_BASE_URL` / `ZELAX_API_KEY` / `ZELAX_MODEL` (ดูตัวอย่างใน `.env.example`):

```bash
# OpenAI
ZELAX_BASE_URL=https://api.openai.com/v1
ZELAX_API_KEY=sk-...
ZELAX_MODEL=gpt-4o

# OpenRouter (Claude / Gemini / Llama ฯลฯ)
ZELAX_BASE_URL=https://openrouter.ai/api/v1
ZELAX_API_KEY=sk-or-...
ZELAX_MODEL=anthropic/claude-3.5-sonnet

# DeepSeek
ZELAX_BASE_URL=https://api.deepseek.com/v1
ZELAX_API_KEY=sk-...
ZELAX_MODEL=deepseek-chat
```

หรือเปลี่ยนโมเดลทันทีในแชทด้วย `/model <ชื่อ>`

---

## เครื่องมือ (Tools)

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

## ความปลอดภัย

ตัวนี้รันคำสั่งบนเครื่องคุณได้จริง จึงมีระบบป้องกัน:

- ขออนุมัติก่อนรัน shell — แสดงคำสั่ง ถาม `รัน? [y/N/e=แก้ไข]` (พิมพ์ `e` แก้ก่อนรัน)
- กันคำสั่งอันตราย — `rm -rf`, `dd`, `shutdown` ฯลฯ เตือน + ขออนุมัติเสมอ
- ขออนุมัติก่อนเขียน/แก้ไฟล์ (แสดง diff สี)
- หากโมเดล生成 tool call พัง ระบบจะขอคำตอบแบบปกติแทน (ไม่ crash)

---

## คำสั่งในแชท

- `/help` — แสดงคำสั่งทั้งหมด
- `/clear` — ล้างประวัติการสนทนา
- `/history` — แสดงประวัติข้อความทั้งหมด
- `/approve on` — รัน shell ทันทีโดยไม่ถาม (เร็วแต่ระวัง)
- `/approve off` — กลับไปถามก่อนรัน (ค่าเริ่มต้น แนะนำ)
- `/cwd <โฟลเดอร์>` — เปลี่ยนที่ทำงาน
- `/model <ชื่อ>` — เปลี่ยนโมเดล
- `/exit` — ออก

---

## ติดตั้งบนเครื่องใหม่

```bash
git clone https://github.com/Zedxv55/Zelax.git
cd Zelax
pip install -r requirements.txt
cp .env.example .env        # แล้วใส่ ZELAX_API_KEY
# ติดตั้งคำสั่ง zelax ลง PATH ด้วย symlink (launcher ตาม symlink ได้):
ln -s "$(pwd)/zelax" ~/.local/bin/zelax
# หรือถ้าใช้ /usr/local/bin:
# sudo ln -s "$(pwd)/zelax" /usr/local/bin/zelax
```

ใช้ `ln -s` ไม่ใช่ `cp` เพื่อให้ launcher ไล่ตาม symlink หาโฟลเดอร์ repo จริงได้ แม้ย้าย/ลิงก์ข้ามที่

---

## Skill

ความสามารถสไตล์ Claude Code ถูกเขียนไว้ใน `SKILL.md` (และฝังใน `zelax.py`)
สามารถ copy ไปวางเป็น system prompt ของ Agent ตัวอื่นได้ทันที

---

คำเตือน: ไฟล์ `.env` มี API Key ห้ามแชร์/อัปโหลดสาธารณะ
