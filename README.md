# 🤖 CodeagentX — Local Coding Agent สไตล์ Claude Code

Agent ที่รับคำสั่งภาษาธรรมชาติ แล้ว **ทำงานบนเครื่องจริงได้เอง** แบบเดียวกับ Claude Code:
รัน shell, อ่าน/เขียน/แก้ไฟล์, ค้นหาไฟล์ — ใช้โมเดล Groq (เลือกโมเดลตัวแรงได้)

พัฒนาต่อยอดจากหนังสือ *ai-agent-book* (bojieli) โดยใช้ความสามารถ Tool Calling

---

## ✨ เปิดใช้งานง่ายๆ — แค่พิมพ์ `codeagentx`

```bash
codeagentx
```
> ไม่ต้อง cd ไปไหน เพราะ installer ใส่คำสั่ง `codeagentx` ลง PATH ให้แล้ว

หรือเรียกไฟล์โดยตรง:
```bash
python3 /home/it-admin/CodeagentX/codeagentx.py
```

ส่งคำถามหนึ่งรอบ:
```bash
codeagentx "สร้างโฟลเดอร์ demo แล้วเขียนสคริปต์ Python พิมพ์สวัสดี และรันมัน"
```

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
| `GROQ_MODEL` | โมเดลที่ใช้ | `llama-3.3-70b-versatile` |
| `AUTO_RUN` | `1`=รัน shell ทันทีไม่ถาม (อันตราย) | `0` |
| `CONFIRM_FILES` | `0`=เขียนไฟล์ไม่ต้องถาม | `1` |
| `SHELL_TIMEOUT` | ตัดคำสั่งค้างที่ (วินาที) | `60` |

### เปลี่ยนโมเดลตัวแรง
แก้ `GROQ_MODEL` ใน `.env` หรือพิมพ์ `/model <ชื่อ>` ในแชท โมเดลที่ใช้ได้บน Groq:
- `llama-3.3-70b-versatile` (ค่าเริ่มต้น แนะนำ)
- `openai/gpt-oss-120b` (ทรงพลังมาก)
- `qwen/qwen3.6-27b`
- `groq/compound`

---

## 🛠️ เครื่องมือ (Tools)
| เครื่องมือ | ทำอะไร |
|---|---|
| `shell` | รันคำสั่ง bash บนเครื่อง |
| `read_file` | อ่านไฟล์ |
| `write_file` | สร้าง/เขียนทับไฟล์ |
| `edit_file` | แก้ข้อความในไฟล์ (search & replace) |
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
- **ขออนุมัติก่อนเขียน/แก้ไฟล์**
- หากโมเดล生成 tool call พัง ระบบจะขอคำตอบแบบปกติแทน (ไม่ crash)

---

## ⌨️ คำสั่งในแชท
- `/approve on` — รัน shell ทันทีโดยไม่ถาม (เร็วแต่ระวัง)
- `/approve off` — กลับไปถามก่อนรัน (ค่าเริ่มต้น แนะนำ)
- `/cwd <โฟลเดอร์>` — เปลี่ยนที่ทำงาน
- `/model <ชื่อ>` — เปลี่ยนโมเดล
- `/tools` — ดูเครื่องมือ
- `/exit` — ออก

---

## 📦 ติดตั้งบนเครื่องใหม่
```bash
git clone https://github.com/Zedxv55/CodeagentX.git
cd CodeagentX
pip install -r requirements.txt
cp .env.example .env        # แล้วใส่ GROQ_API_KEY
# ติดตั้งคำสั่ง codeagentx ลง PATH:
sudo cp codeagentx /usr/local/bin/codeagentx && sudo chmod +x /usr/local/bin/codeagentx
# หรือคัดลอกไป ~/bin ก็ได้
```

---

## 🧠 Skill
ความสามารถสไตล์ Claude Code ถูกเขียนไว้ใน `SKILL.md` (และฝังใน `codeagentx.py`)
สามารถ copy ไปวางเป็น system prompt ของ Agent ตัวอื่นได้ทันที

---

⚠️ **คำเตือน:** ไฟล์ `.env` มี API Key ห้ามแชร์/อัปโหลดสาธารณะ
