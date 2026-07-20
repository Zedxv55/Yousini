# Yousini

Local Coding Agent สไตล์ Claude Code — รับคำสั่งภาษาธรรมชาติ แล้วทำงานบนเครื่องจริงได้เอง:
รัน shell, อ่าน/เขียน/แก้ไฟล์, ค้นหาไฟล์ **และเชื่อมต่อได้ทั้งในเครื่องและออนไลน์** ผ่านทุก OpenAI-compatible API (Groq, OpenAI, OpenRouter, DeepSeek, Mistral ฯลฯ)

- 🖥️ **CLI สวยงาม** — banner ไล่สี, สตรีมสด, diff สี, syntax highlight
- 🌐 **serve** — เปิดเป็นเว็บ UI + API (SSE) คุยผ่านเบราว์เซอร์ได้ + เก็บ session ลงดิสก์ข้าม restart
- 🔗 **connect** — CLI เครื่องหนึ่งคุยกับ Yousini เครื่องอื่น/บริการอื่นผ่านเน็ตได้
- 🛡️ มีระบบกันคำสั่งอันตราย + ขออนุมัติก่อนรัน/เขียนไฟล์
- 📌 **YOUSINI.md** — บริบทโปรเจกต์ถาวร (เหมือน CLAUDE.md) โหลดอัตโนมัติทุกครั้ง
- 🧩 **Skills** — โหลด `skills/*.md` เข้า system prompt อัตโนมัติ
- 🪝 **Hooks** — `pre_tool`/`post_tool` script ตัดสินว่าจะรัน tool ไหม (config ได้)
- 💾 **Session persistence** — `/save` `/load` `/sessions` บันทึกบทสนทนาลงดิสก์
- ⏳ **Background shell** — รันคำสั่งยาวแบบไม่บล็อก (`run_in_background`) + `/jobs`
- 🔖 **Checkpoint/Rollback** — auto `git commit` ก่อนแก้ไฟล์ แล้ว `/rollback` ได้
- 🔌 **MCP server** — `yousini mcp` ครอบ tools เป็น MCP server ให้ agent ภายนอกเรียกได้

พัฒนาต่อยอดจากหนังสือ *ai-agent-book* (bojieli) โดยใช้ความสามารถ Tool Calling

---

## เริ่มต้นใช้งาน

เปิด terminal แล้วพิมพ์:

```bash
yousini
```

หรือส่งคำสั่งหนึ่งรอบโดยตรง:

```bash
yousini "สร้างโฟลเดอร์ demo แล้วเขียนสคริปต์ Python พิมพ์สวัสดี และรันมัน"
```

---

## โหมดเชื่อมต่อ (ใหม่!)

### เปิดเป็นบริการ (เว็บ UI + API)

```bash
yousini serve                       # เปิดที่ http://localhost:8787 (ในเครื่อง)
yousini serve --host 0.0.0.0 --token รหัสลับ   # เปิดออนไลน์พร้อม token ป้องกัน
yousini serve --safe                # แบบอ่านอย่างเดียว (ปิด shell / เขียนไฟล์)
yousini serve --port 9000 --no-shell
```

เปิดเบราว์เซอร์ไปที่ `http://localhost:8787/` จะเจอเว็บแชทสวยงาม แชทได้เลย
โปรแกรมอื่นเรียก API ได้ที่ `POST /api/chat` แบบ Server-Sent Events (ดูตัวอย่างด้านล่าง)

### เชื่อมต่อ CLI ข้ามเครื่อง

```bash
yousini connect http://10.0.0.5:8787          # คุยกับ Yousini เครื่องอื่น
yousini connect https://yousini.example.com --token รหัสลับ
```

ทำให้ CLI สองเครื่อง "คุยกัน" ได้ — ในเครื่องหรือออนไลน์

---

## ความสามารถหลัก

- ความจำข้าม turn — Agent จำบริบทการสนทนาได้ตลอดเซสชัน (มี trimming กันบริบทยาวเกิน และกัน tool-result ลอยๆ)
- Streaming จริง — ตอบสดพร้อมเรนเดอร์ Markdown สดๆ ระหว่างโมเดลพิมพ์
- UI สไตล์ Claude Code — ใช้ `⏺` (การกระทำ) กับ `⎿` (ผลลัพธ์)
- Banner ASCII ไล่สี magenta→cyan อลังการ
- Diff สี เขียว/แดง ก่อนยืนยันเขียน/แก้ไฟล์ทุกครั้ง
- Syntax highlighting ตามนามสกุลไฟล์ตอนอ่าน
- คำสั่ง `/clear` `/history` `/help` + arrow-key history ข้ามเซสชัน (readline)

---

## ตัวอย่างหน้าจอ (UX/UI CLI)

```text
 __   __  _______  __   __  _______  ___   __    _  ___
|  | |  ||       ||  | |  ||       ||   | |  |  | ||   |
|  |_|  ||   _   ||  | |  ||  _____||   | |   |_| ||   |
|       ||  | |  ||  |_|  || |_____ |   | |       ||   |
|_     _||  |_|  ||       ||_____  ||   | |  _    ||   |
  |   |  |       ||       | _____| ||   | | | |   ||   |
  |___|  |_______||_______||_______||___| |_|  |__||___|

  พร้อมทำงาน  ·  ทำงานบนเครื่องจริง + ออนไลน์  ·  เชื่อมต่อข้ามเครื่องได้

❯ สร้างไฟล์ hello.py ที่พิมพ์สวัสดี แล้วรัน
กำลังคิด…
⏺ write_file({"path": "hello.py", "content": "print('สวัสดี')"})
╭───────────────────────── สร้างไฟล์: hello.py ─────────────────────────╮
│ print('สวัสดี')                                                       │
╰──────────────────────────────────────────────────────────────────────╯
⎿ เขียนสำเร็จ: hello.py (15 ตัวอักษร)
⏺ shell(python3 hello.py)
⎿ [exit code: 0]
สวัสดี
```

### ตัวอย่างหน้าจอ (Web UI — `yousini serve`)

เบราว์เซอร์แชทไดนามิก: พื้น aurora เคลื่อนไหว, ฟองแชทแก้ว (glass), ชิปแสดง tool-call สีฟ้า
ขณะ agent ทำงาน จะเห็น `⏺ shell(...)` โผล่ขึ้นทีละอันพร้อมผลลัพธ์สดแบบสตรีม

### เรียก API จากโปรแกรมอื่น (SSE)

```bash
curl -N -X POST http://localhost:8787/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"สร้างเว็บ hello world","session":"demo"}'
# จะได้ stream: data: {"type":"token","text":"..."} ทีละท่อน
```

---

## ตั้งค่า (Configuration)

ไฟล์ `.env` (มีให้แล้วในเครื่องนี้ พร้อม key) ถ้าเอาไปเครื่องอื่น ให้คัดลอกจากเทมเพลต:

```bash
cp .env.example .env
# แล้วใส่ YOUSINI_API_KEY ใน .env
```

ตัวแปรใน `.env`:

| ตัวแปร | คำอธิบาย | ค่าแนะนำ |
|---|---|---|
| `YOUSINI_API_KEY` | API Key จาก provider ที่เลือก | — |
| `YOUSINI_BASE_URL` | Endpoint (OpenAI-compatible) | `https://api.groq.com/openai/v1` |
| `YOUSINI_MODEL` | โมเดลที่ใช้ | `openai/gpt-oss-120b` |
| `AUTO_RUN` | `1`=รัน shell ทันทีไม่ถาม (อันตราย) | `0` |
| `CONFIRM_FILES` | `0`=เขียนไฟล์ไม่ต้องถาม | `1` |
| `SHELL_TIMEOUT` | ตัดคำสั่งค้างที่ (วินาที) | `60` |
| `YOUSINI_SEARCH_PROVIDER` | เสิร์ชผ่าน API จริงแทน scraping: `brave` / `serpapi` / `tavily` (เว้นว่าง=ใช้ scraping หลายชั้น) | _(ว่าง)_ |
| `YOUSINI_SEARCH_API_KEY` (หรือ `BRAVE_API_KEY` / `SERPAPI_KEY` / `TAVILY_API_KEY`) | คีย์สำหรับ provider ค้นหาที่เลือก | — |

> เข้ากันได้กับของเดิม: หากไม่มี `YOUSINI_*` จะตกไปอ่าน `ZELAX_*` หรือ `GROQ_*` เป็น fallback ให้ย้ายมาใช้ `YOUSINI_*` ได้ทันที

### เปลี่ยน Provider / โมเดล

Yousini เปิดรับทุก OpenAI-compatible API ไม่ผูกกับ Groq เพียงแก้ `YOUSINI_BASE_URL` / `YOUSINI_API_KEY` / `YOUSINI_MODEL` (ดูตัวอย่างใน `.env.example`):

```bash
# OpenAI
YOUSINI_BASE_URL=https://api.openai.com/v1
YOUSINI_API_KEY=sk-...
YOUSINI_MODEL=gpt-4o

# OpenRouter (Claude / Gemini / Llama ฯลฯ)
YOUSINI_BASE_URL=https://openrouter.ai/api/v1
YOUSINI_API_KEY=sk-or-...
YOUSINI_MODEL=anthropic/claude-3.5-sonnet

# DeepSeek
YOUSINI_BASE_URL=https://api.deepseek.com/v1
YOUSINI_API_KEY=sk-...
YOUSINI_MODEL=deepseek-chat
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
| `web_fetch` | ดึงเนื้อหาเว็บจาก URL (ออนไลน์) |
| `web_search` | ค้นหาข้อมูลบนอินเทอร์เน็ต (ออนไลน์) |
| `set_cwd` | เปลี่ยนโฟลเดอร์ทำงาน |
| `ask_user` | ถามผู้ใช้ (เมื่อขาดข้อมูลสำคัญเท่านั้น) |
| `load_skill` | โหลดเนื้อหาเต็มของสกิลตามชื่อ (lazy-load — ไม่กิน context ถ้าไม่ได้ใช้) |
| `run_python` | รันโค้ด Python บนเครื่อง (คำนวณ/ประมวลผล/ทดสอบ snippet) |
| `spawn_subagent` | รันเอเจนต์ย่อยแยกบริบท เพื่อทำงานเฉพาะส่วนแล้วคืนสรุป (ไม่ทำให้บริบทหลักบวม) |

---

## ความปลอดภัย

ตัวนี้รันคำสั่งบนเครื่องคุณได้จริง จึงมีระบบป้องกัน:

- ขออนุมัติก่อนรัน shell — แสดงคำสั่ง ถาม `รัน? [y/N/e=แก้ไข]` (พิมพ์ `e` แก้ก่อนรัน)
- กันคำสั่งอันตราย — `rm -rf`, `dd`, `shutdown` ฯลฯ เตือน + ขออนุมัติเสมอ (ในโหมด headless/server จะบล็อกเด็ดขาด)
- ขออนุมัติก่อนเขียน/แก้ไฟล์ (แสดง diff สี)
- หากโมเดลสร้าง tool call พัง ระบบจะขอคำตอบแบบปกติแทน (ไม่ crash)
- โหมด `serve --safe` หรือ `--no-shell`/`--no-write` ปิดความสามารถที่อาจอันตรายได้

---

## คำสั่งในแชท

- `/help` — แสดงคำสั่งทั้งหมด (รวมโหมด serve / connect / mcp)
- `/clear` — ล้างประวัติการสนทนา
- `/history` — แสดงประวัติข้อความทั้งหมด
- `/approve on` — รัน shell ทันทีโดยไม่ถาม (เร็วแต่ระวัง)
- `/approve off` — กลับไปถามก่อนรัน (ค่าเริ่มต้น แนะนำ)
- `/reload` — โหลด `YOUSINI.md` + `skills/` ใหม่ (เมื่อแก้ไฟล์บริบทระหว่างทาง)
- `/skills` — แสดงสกิลที่โหลดอยู่
- `/hooks` — แสดงสถานะ hooks
- `/cwd <โฟลเดอร์>` — เปลี่ยนที่ทำงาน
- `/model <ชื่อ>` — เปลี่ยนโมเดล
- `/save [ชื่อ]` — บันทึกบทสนทนาลงดิสก์
- `/load [ชื่อ]` — โหลดบทสนทนาจากดิสก์
- `/sessions` — แสดงรายการ session ที่บันทึกไว้
- `/jobs` — แสดงงาน shell แบบ background ที่กำลังรัน/เสร็จแล้ว
- `/checkpoint` — `git commit` จุดเก็บชั่วคราวเดี๋ยวนั้น
- `/rollback` — ย้อนกลับไปจุด checkpoint ล่าสุด (git reset --hard)
- `/exit` — ออก

---

## ฟีเจอร์ขั้นสูง

### 📌 บริบทโปรเจกต์ถาวร (YOUSINI.md)

สร้างไฟล์ `YOUSINI.md` ในโฟลเดอร์โปรเจกต์ (ดู `YOUSINI.example.md`) — Agent จะโหลด
อัตโนมัติทุกครั้งที่เริ่มงานในโฟลเดอร์นั้น (และโฟลเดอร์แม่ขึ้นไปจน root) รวมถึง
`~/.yousini.md` ระดับเครื่อง ใช้จดกฎ/stack/convention ของโปรเจกต์

### 🧩 Skills (`skills/*.md`)

ทุกไฟล์ `.md` ในโฟลเดอร์ `skills/` (relative ต่อ cwd) จะถูก**สแกนเฉพาะชื่อ+คำอธิบาย**
โหลดเข้า system prompt (ไม่โหลดเนื้อหาเต็ม) เพื่อไม่ให้ context บวมเมื่อสกิลเยอะ
เมื่องานเกี่ยวข้องกับสกิลใด โมเดลจะเรียก `load_skill(name)` เพื่อโหลดเนื้อหาเต็มเข้ามา
ดูตัวอย่างได้ที่ `skills/example.md` ใช้เพิ่มความรู้/เวิร์กโฟลว์เฉพาะทาง

### 🪝 Hooks (pre_tool / post_tool / session_start / session_stop)

วางสคริปต์ในโฟลเดอร์ `.yousini/hooks` (หรือ `~/.yousini/hooks` หรือระบุผ่าน
`YOUSINI_HOOKS=...`) รันตาม lifecycle ต่างๆ:

- `pre_tool` / `post_tool` — รันก่อน/หลัง**ทุก** tool call
  - `pre_tool` รับ JSON `{"tool","args"}` ทาง stdin + env `YOUSINI_TOOL`/`YOUSINI_CWD`
    - **exit 0** → อนุญาต · **exit != 0** → บล็อก (stdout กลับเป็นเหตุผลให้โมเดล)
  - `post_tool` รับ `{"tool","args","result"}` — best-effort ไม่เปลี่ยนผลลัพธ์
- `session_start` — รันตอนเริ่ม session (audit log / เตรียมสภาพแวดล้อม)
- `session_stop` — รันตอนจบ session (cleanup / flush log) — ผูกกับ `atexit` ด้วย

ดูตัวอย่าง `pre_tool.example.sh` / `post_tool.example.sh` (กันดาวน์โหลดสคริปต์จากเน็ตแล้วรัน, กันแตะไฟล์ระบบ)

### 💾 Session persistence

บทสนทนาถูกบันทึกลงดิสก์ (JSON) ใต้ `~/.yousini/sessions` (หรือ `YOUSINI_SESSIONS=...`):

- `/save [ชื่อ]` บันทึก · `/load [ชื่อ]` โหลด · `/sessions` รายการ
- `yousini resume` โหลด session ล่าสุดแล้วเข้าสู่แชท
- โหมด `serve` เก็บ session ของแต่ละ sid ลงดิสก์ด้วย → restart server บริบทไม่หาย

### ⏳ Background shell

ส่ง `run_in_background: true` ให้ tool `shell` สำหรับคำสั่งที่รันนาน Agent จะคืน job id
ทันทีแล้วคุณสามารถถามผลทีหลังผ่าน `read_job(job_id=...)` หรือดูรายการด้วย `/jobs`

### 🔖 Checkpoint / Rollback

เมื่อเปิด `YOUSINI_CHECKPOINT=1` (ค่าเริ่มต้น) Agent จะ `git commit` จุดเก็บชั่วคราว
**ก่อน**แก้ไฟล์ในแต่ละรอบการสนทนา หากพังกลางทาง พิมพ์ `/rollback` เพื่อคืนสถานะก่อนแก้
(ทำงานได้เฉพาะใน git repository)

### 🔌 MCP server (`yousini mcp`)

รัน Yousini เป็น MCP server แบบ stdio (JSON-RPC 2.0) ครอบ tools ทั้งหมด
ให้ Claude Code หรือ agent อื่นในโลก MCP เรียกใช้ได้:

```bash
yousini mcp                  # โหมดปลอดภัย: บล็อก shell/write/edit
yousini mcp --allow-exec     # อนุญาต shell/write/edit (ระวัง)
```

เชื่อมต่อจาก Claude Code ผ่านไฟล์ตั้งค่า MCP ที่ชี้ไปที่ `yousini mcp` ได้ทันที

---

## ติดตั้งบนเครื่องใหม่

```bash
git clone https://github.com/Zedxv55/Yousini.git
cd Yousini
pip install -r requirements.txt
cp .env.example .env        # แล้วใส่ YOUSINI_API_KEY
# ติดตั้งคำสั่ง yousini ลง PATH ด้วย symlink (launcher ตาม symlink ได้):
ln -s "$(pwd)/yousini" ~/.local/bin/yousini
# หรือถ้าใช้ /usr/local/bin:
# sudo ln -s "$(pwd)/yousini" /usr/local/bin/yousini
```

ใช้ `ln -s` ไม่ใช่ `cp` เพื่อให้ launcher ไล่ตาม symlink หาโฟลเดอร์ repo จริงได้ แม้ย้าย/ลิงก์ข้ามที่

> ติดตั้งแบบแพ็กเกจ (มีคำสั่ง `yousini` จาก console script): `pip install -e .`

---

## Skill

ความสามารถสไตล์ Claude Code ถูกเขียนไว้ใน `SKILL.md` (และฝังใน `yousini.py`)
สามารถ copy ไปวางเป็น system prompt ของ Agent ตัวอื่นได้ทันที
นอกจากนี้ยังสามารถขยายด้วย `skills/*.md` และ `YOUSINI.md` ตามหัวข้อ "ฟีเจอร์ขั้นสูง" ด้านบน

---

คำเตือน: ไฟล์ `.env` มี API Key ห้ามแชร์/อัปโหลดสาธารณะ
