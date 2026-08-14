# Yousini

**Yousini** is a local, terminal-based coding agent inspired by Claude Code. It runs entirely on your machine and connects to any OpenAI-compatible API (Groq, OpenAI, OpenRouter, DeepSeek, Mistral and more). It can run shell commands, read and write files, search the web, manage memory and sessions, expose a web UI, and integrate with other agents through MCP.

Yousini is a terminal coding agent ที่รันในเครื่องของคุณเอง ทำงานร่วมกับ API ที่รองรับรูปแบบ OpenAI (Groq, OpenAI, OpenRouter, DeepSeek, Mistral และอื่น ๆ) มีความสามารถในการรันคำสั่ง shell, อ่าน/เขียน/แก้ไขไฟล์, ค้นหาเว็บ, จัดการความจำและ session, มี Web UI และเชื่อมต่อกับ agent อื่นผ่าน MCP

| Version | License | Language | Python |
| --- | --- | --- | --- |
| 3.7.0 | MIT | Python 3.10+ | English / Thai |

[![CI](https://github.com/Zedxv55/Yousini/actions/workflows/ci.yml/badge.svg)](https://github.com/Zedxv55/Yousini/actions/workflows/ci.yml)

---

## Table of Contents / สารบัญ

- [Overview / ภาพรวม](#overview--ภาพรวม)
- [Features / คุณสมบัติ](#features--คุณสมบัติ)
- [Installation / การติดตั้ง](#installation--การติดตั้ง)
- [Configuration / การตั้งค่า](#configuration--การตั้งค่า)
- [Quick Start / เริ่มต้นใช้งาน](#quick-start--เริ่มต้นใช้งาน)
- [CLI Commands / คำสั่ง](#cli-commands--คำสั่ง)
- [Slash Commands / คำสั่งในแชท](#slash-commands--คำสั่งในแชท)
- [Tools / เครื่องมือ](#tools--เครื่องมือ)
- [Customization / การปรับแต่ง](#customization--การปรับแต่ง)
- [Advanced Features / ฟีเจอร์ขั้นสูง](#advanced-features--ฟีเจอร์ขั้นสูง)
- [LSP Server / Code Intelligence](#lsp-server--code-intelligence)
- [Dashboard / สถิติ](#dashboard)
- [Marketplace / Skills & Plugins](#marketplace--skills--plugins)
- [Team / Multi-User Workspace](#team--multi-user-workspace)
- [Agent Collaboration / คิวงาน](#agent-collaboration--คิวงาน)
- [Capabilities / ความสามารถขั้นสูง](#capabilities--ความสามารถขั้นสูง)
- [Monetization / โมเดลธุรกิจ](#monetization--โมเดลธุรกิจ)
- [Security / ความปลอดภัย](#security--ความปลอดภัย)
- [Troubleshooting / การแก้ไขปัญหา](#troubleshooting--การแก้ไขปัญหา)
- [License / สัญญาอนุญาต](#license--สัญญาอนุญาต)

---

## Overview / ภาพรวม

Yousini gives you a Claude Code-style assistant inside your own terminal. It is a single-file Python agent with rich terminal UI (Rich), streaming responses, tool calling, session persistence and provider fallback.

Yousini ให้คุณมีผู้ช่วยสไตล์ Claude Code ในเทอร์มินัลของคุณเอง เป็น Python agent ไฟล์เดียวพร้อม UI หรูหรา (Rich), การตอบสนองแบบ streaming, tool calling, การบันทึก session และการสลับ provider อัตโนมัติ

Key capabilities / ความสามารถหลัก:

- Interactive CLI with streaming Markdown, syntax highlighting and colored diffs
- Web UI + SSE API via `yousini serve`
- Remote control from another machine via `yousini connect`
- MCP server and MCP client support
- Persistent memory, searchable session history (SQLite + FTS5)
- Auto git checkpoint / rollback
- Background jobs, cron jobs, webhooks and a Telegram gateway
- Code intelligence with tree-sitter (go-to-definition, symbol index) and git awareness

---

## Features / คุณสมบัติ

| Area | Description / รายละเอียด |
| --- | --- |
| Terminal UI | Rich CLI with banner, streaming output, colored diff and syntax highlight |
| Web UI | `yousini serve` launches a Codex-style web interface and SSE API on `http://localhost:8787` |
| Remote connect | `yousini connect <url>` controls a running Yousini from the CLI |
| Context file | `YOUSINI.md` acts like `CLAUDE.md` for persistent project instructions |
| Skills | Markdown files in `skills/` are auto-loaded into the system prompt |
| Hooks | `pre_tool` / `post_tool` / `session_start` / `session_stop` lifecycle scripts |
| Sessions | `/save`, `/load`, `/sessions`, `yousini resume`, SQLite search with `/search` |
| Memory | Long-term memory via the `memory` tool and `/memory` command |
| Self-improvement | `skill_create` / `skill_patch` lets the agent create and update skills |
| Background shell | Long-running commands with `run_in_background` and `/jobs` |
| Checkpoint / Rollback | Auto `git commit` before edits, `/rollback` to restore |
| MCP server | `yousini mcp` exposes Yousini tools to Claude Code and other MCP clients |
| MCP client | `yousini mcp-add <name> <cmd>` connects to external MCP servers |
| Provider fallback | Multiple API keys and automatic failover |
| Cron jobs | Scheduled tasks with `yousini cron` and `/cron` |
| Webhooks | `POST /api/webhook/<name>` triggers agent tasks |
| Telegram gateway | Chat with Yousini from Telegram |
| Profiles | Separate config, sessions and skills per profile |
| Code intelligence | tree-sitter symbol index, go-to-definition and references |
| Git awareness | `git` tool and `/git` command with recent commit context injection |
| Vision | Image input via `[img:path.png]` or `/img` |

---

## Installation / การติดตั้ง

### Prerequisites / สิ่งที่ต้องเตรียม

- **Python 3.10 or newer** (ทดสอบบน Python 3.12)
- An API key from any OpenAI-compatible provider
- Git (recommended, for checkpoints and cloning)

### Step 1 — Install Python

**Windows**

Download Python from [python.org](https://www.python.org/downloads/) and run the installer. In the first screen, check **"Add python.exe to PATH"** before installing.

> Note: If you installed Python from the Microsoft Store, the `python` command may only open the Store page. Install from python.org instead and disable the "App execution alias" for Python in Windows Settings to avoid conflicts.

> หมายเหตุ: หากติดตั้ง Python จาก Microsoft Store คำสั่ง `python` อาจเปิดหน้า Store เท่านั้น ให้ติดตั้งจาก python.org และปิด "App execution alias" สำหรับ Python ในการตั้งค่า Windows

**macOS / Linux**

```bash
# macOS (Homebrew)
brew install python git

# Debian / Ubuntu
sudo apt update && sudo apt install -y python3 python3-venv python3-pip git

# Arch Linux
sudo pacman -S python python-pip git
```

Verify / ตรวจสอบ:

```bash
python --version
git --version
```

### Step 2 — Clone the repository

```bash
git clone https://github.com/Zedxv55/Yousini.git
cd Yousini
```

### Step 3 — Install dependencies

**Option A — venv (recommended / แนะนำ)**

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -e .
```

**Option B — install globally**

```bash
pip install -r requirements.txt
pip install -e .
```

The `pip install -e .` command installs the `yousini` console command and all required packages (`openai`, `rich`, `tree-sitter`, ...).

**Option C — quick launcher (ไม่ต้อง pip install)**

```bash
# Windows
python install.py

# macOS / Linux
python3 install.py
```

`install.py` สร้าง launcher ที่ `~/.yousini/bin` (`yousini.cmd` บน Windows / `yousini` script บน macOS·Linux) แล้วลง `~/.yousini/bin` เข้า PATH (user-level) ให้เรียก `yousini` ได้จากทุกที่. ตัวเลือก: `--pip` (ลงแบบ editable เหมือน Option A), `--uninstall` (เอาออก). ทดสอบได้ด้วย `yousini --version` หลังเปิดเทอร์มินัลใหม่. โฟลเดอร์ `.env` จะถูกหาอัตโนมัติจาก cwd → โฟลเดอร์ของโปรเจกต์ → home.

### Step 4 — Configure your API key

```bash
cp .env.example .env
```

Then edit `.env` and set `YOUSINI_API_KEY`, `YOUSINI_BASE_URL` and `YOUSINI_MODEL` (see [Configuration](#configuration--การตั้งค่า)).

### Step 5 — Launch

```bash
yousini
```

On Windows you can also double-click `yousini.cmd`, which auto-detects a working Python interpreter.

---

## Configuration / การตั้งค่า

Copy `.env.example` to `.env` and fill in your provider details:

| Variable | Description / รายละเอียด | Default |
| --- | --- | --- |
| `YOUSINI_API_KEY` | API key of your provider (required). Aliases: `MISTRAL_API_KEY`, `GROQ_API_KEY`, `ZELAX_API_KEY` | - |
| `YOUSINI_BASE_URL` | OpenAI-compatible endpoint | `https://api.groq.com/openai/v1` |
| `YOUSINI_MODEL` | Model name | `openai/gpt-oss-120b` |
| `AUTO_RUN` | `1` = run shell commands without confirmation | `0` |
| `CONFIRM_FILES` | `0` = edit files without confirmation | `1` |
| `SHELL_TIMEOUT` | Default shell timeout in seconds | `60` |
| `YOUSINI_CONTEXT` | Context file loaded into the system prompt | `YOUSINI.md` |
| `YOUSINI_SKILLS` | Skills directory | `skills` |
| `YOUSINI_CHECKPOINT` | `1` = auto git checkpoint before edits | `1` |
| `YOUSINI_HOOKS` | Hooks directory | `./.yousini/hooks` |
| `YOUSINI_SESSIONS` | Session storage directory | `~/.yousini/sessions` |
| `YOUSINI_SEARCH_PROVIDER` | Web search provider: `brave`, `serpapi`, `tavily` | _(empty)_ |
| `BRAVE_API_KEY` | Brave Search API key (default web search provider) | - |
| `YOUSINI_FALLBACK_PROVIDERS` | JSON array of `{"base_url","api_key"}` for failover | `[]` |
| `YOUSINI_TG_TOKEN` | Telegram bot token (for the gateway) | - |
| `YOUSINI_TG_CHAT_ID` | Allowed Telegram chat id | - |
| `YOUSINI_PROFILE` | Active profile name | `default` |
| `YOUSINI_MAX_TOKENS` | Context window budget | `12000` |
| `YOUSINI_COMPACT_RATIO` | Auto-compact trigger ratio | `0.8` |

### Example providers / ตัวอย่าง provider

```bash
# OpenAI
YOUSINI_BASE_URL=https://api.openai.com/v1
YOUSINI_API_KEY=sk-...
YOUSINI_MODEL=gpt-4o

# OpenRouter (Claude, Gemini, Llama and more)
YOUSINI_BASE_URL=https://openrouter.ai/api/v1
YOUSINI_API_KEY=sk-or-...
YOUSINI_MODEL=anthropic/claude-3.5-sonnet

# DeepSeek
YOUSINI_BASE_URL=https://api.deepseek.com/v1
YOUSINI_API_KEY=sk-...
YOUSINI_MODEL=deepseek-chat

# Mistral
YOUSINI_BASE_URL=https://api.mistral.ai/v1
YOUSINI_API_KEY=...
YOUSINI_MODEL=mistral-large-latest

# Groq (default)
YOUSINI_BASE_URL=https://api.groq.com/openai/v1
YOUSINI_API_KEY=gsk_...
YOUSINI_MODEL=openai/gpt-oss-120b
```

You can also switch the model inside a session with `/model <name>`.

---

## Quick Start / เริ่มต้นใช้งาน

Start the interactive REPL / เริ่มโหมดสนทนา:

```bash
yousini
```

Run a single task / รันงานเดียว:

```bash
yousini "สร้าง demo โปรเจกต์ Python พร้อมไฟล์ hello.py และ README"
```

Web UI / เว็บอินเทอร์เฟซ:

```bash
yousini serve                       # http://localhost:8787
yousini serve --host 0.0.0.0 --token secret
yousini serve --safe                # no shell / no file writes
yousini serve --port 9000 --no-shell
```

Control a remote instance / ควบคุมเครื่องระยะไกล:

```bash
yousini connect http://10.0.0.5:8787
yousini connect https://yousini.example.com --token secret
```

---

## CLI Commands / คำสั่ง

| Command / คำสั่ง | Description / รายละเอียด |
| --- | --- |
| `yousini` | Start interactive session |
| `yousini "<prompt>"` | Run a one-shot task |
| `yousini serve` | Start web UI + SSE API |
| `yousini connect <url>` | Connect to a remote instance |
| `yousini mcp` | Expose Yousini as an MCP server (`--allow-exec` to enable shell/write) |
| `yousini lsp` | Start the LSP server over stdio (`yousini lsp [root]`) |
| `yousini marketplace <cmd>` | Browse / install / update skills & tool plugins (see [Marketplace](#marketplace--skills--plugins)) |
| `yousini agent <cmd>` | Agent collaboration queue: send / status / result / requeue / prune / clear / reclaim |
| `yousini work [--once]` | Run as a worker: pull queued tasks, run them, save results |
| `yousini pr <title> [body]` / `pr list` | Open a Pull Request (commit → branch → push → `gh` or compare link) |
| `yousini scaffold <kind> <name>` | Generate a starter project (`python-cli` / `python-pkg` / `web-static`) |
| `yousini dev [scope]` | Combined project check: `all` / `status` / `compile` / `test` / `lint` |
| `yousini team <cmd>` | Team workspace: status / init / join / leave / users / set-registry (see [Team](#team--multi-user-workspace)) |
| `yousini mcp-add <name> <cmd>` | Add an external MCP server |
| `yousini mcp-list` / `yousini mcp-rm <name>` | Manage MCP client servers |
| `yousini login` | Interactive provider selection |
| `yousini theme [name]` | Set / list terminal themes |
| `yousini profile [name]` | Switch or show the active profile |
| `yousini cron` | Run scheduled jobs (`--once` for a single pass) |
| `yousini resume` | Resume the most recent session |
| `yousini webhook-add <name> <prompt>` | Register a webhook |
| `yousini webhook-list` / `yousini webhook-rm <name>` | Manage webhooks |
| `yousini telegram` | Start the Telegram gateway |

SSE API example / ตัวอย่างการเรียก API แบบ SSE:

```bash
curl -N -X POST http://localhost:8787/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"write a hello world app","session":"demo"}'
# streams: data: {"type":"token","text":"..."}
```

---

## Slash Commands / คำสั่งในแชท

| Command / คำสั่ง | Description / รายละเอียด |
| --- | --- |
| `/help` | Show all commands |
| `/clear` | Clear the conversation |
| `/history` | Show message history |
| `/approve on` / `/approve off` | Toggle shell auto-approval |
| `/reload` | Reload `YOUSINI.md` and `skills/` |
| `/skills` | List available skills |
| `/hooks` | Show active hooks |
| `/cwd <path>` | Change the working directory |
| `/model <name>` | Switch the model |
| `/save [name]` | Save the current session |
| `/load [name]` | Load a saved session |
| `/sessions` | List saved sessions |
| `/search <query>` | Search session history |
| `/jobs` | Show background jobs |
| `/checkpoint` | Create a git checkpoint |
| `/rollback` | Restore the last checkpoint |
| `/compact` | Compact the context window |
| `/todos` | Show the task plan |
| `/plan` | Enter plan mode |
| `/img` | Attach an image |
| `/memory` | Manage long-term memory |
| `/git` | Git status / log / diff |
| `/symbols` | Symbol index and navigation |
| `/providers` | Show provider fallback status |
| `/cron` | Manage scheduled jobs |
| `/usage [on\|off\|reset]` | Usage telemetry (local only, opt-in) — token/tool statistics |
| `/ads [on\|off\|status]` | Toggle the sponsor line (always disable-able; Pro = no ads) |
| `/tier [activate <key>\|off]` | View / activate Pro & Team via license key |
| `/exit` | Quit |

---

## Tools / เครื่องมือ

| Tool | Description / รายละเอียด |
| --- | --- |
| `shell` | Run shell commands |
| `read_file` | Read a file with syntax highlighting |
| `write_file` | Create or overwrite a file |
| `edit_file` | Search-and-replace edit with diff preview |
| `list_dir` | List a directory |
| `glob` | Find files by pattern (`**/*.py`) |
| `grep` | Regex search across files |
| `web_fetch` | Fetch a URL and convert to Markdown |
| `web_search` | Search the web (Brave / SerpAPI / Tavily / fallback scrape) |
| `set_cwd` | Change the working directory |
| `ask_user` | Ask the user a question |
| `load_skill` | Lazy-load a skill to save context |
| `run_python` | Execute Python snippets |
| `spawn_subagent` | Spawn a subagent for parallel work |
| `manage_todos` | Manage the task plan |
| `batch_edit_files` | Multi-file edits with a single commit |
| `run_test_loop` | Automated TDD fix loop |
| `memory` | Store and recall long-term memories |
| `skill_create` / `skill_patch` | Create and update skills |
| `git` | Git log / status / diff / blame |
| `symbols` | Symbol definitions and references (tree-sitter) |

---

## Customization / การปรับแต่ง

### Context file — `YOUSINI.md`

Create `YOUSINI.md` at the project root (start from `YOUSINI.example.md`) with persistent instructions about your project, stack and conventions. The agent reads it at every session start.

### Skills — `skills/*.md`

Markdown files in `skills/` (relative to the working directory) and `~/.yousini/skills` are indexed by name and description and injected into the system prompt. Use `load_skill(name)` to load full content on demand. See `skills/example.md`.

### Hooks — `pre_tool` / `post_tool`

Place scripts in `.yousini/hooks` (or `~/.yousini/hooks`) to run around tool calls:

- `pre_tool` receives `{"tool","args"}` on stdin plus `YOUSINI_TOOL` / `YOUSINI_CWD` env vars. Exit 0 allows the call, non-zero blocks it.
- `post_tool` receives `{"tool","args","result"}` for logging and side effects.
- `session_start` / `session_stop` run at session boundaries.

---

## Advanced Features / ฟีเจอร์ขั้นสูง

- **Auto-compact** — the context is trimmed and summarized when token usage passes the threshold, preventing context overflow.
- **Provider fallback** — configure multiple providers in `YOUSINI_FALLBACK_PROVIDERS`; Yousini fails over automatically.
- **Session persistence** — sessions survive restarts, on disk and searchable via `/search`.
- **Checkpoint / rollback** — every tool batch is committed with git so `/rollback` restores a safe state.
- **Plan mode** — `/plan` produces a step-by-step task plan before executing.
- **Webhooks** — `yousini webhook-add <name> <prompt>` then `POST /api/webhook/<name>`.
- **Telegram gateway** — run `yousini telegram` and chat from Telegram (set `YOUSINI_TG_TOKEN`).

---

## LSP Server / Code Intelligence

Yousini ships a **Language Server Protocol** server (`yousini lsp`, stdio JSON-RPC 2.0) that editors can attach to for workspace code intelligence, backed by the tree-sitter symbol index:

| Capability | What it does |
| --- | --- |
| `textDocument/hover` | Signature + source snippet of the symbol under the cursor |
| `textDocument/definition` | Go-to-definition across the workspace |
| `textDocument/references` | All usages of a symbol (definition + calls) |
| `textDocument/documentSymbol` | Hierarchical outline of a file (classes / methods / functions) |
| `workspace/symbol` | Search symbols by name across the project |
| `textDocument/completion` | Identifier completion from workspace + current file |

Supported languages match the symbol index: Python, JavaScript/TS, Go, C, Rust (regex fallback for others).

```bash
# เริ่ม LSP server ผ่าน stdio (editor/neovim/VS Code ตั้งให้ใช้เป็น language server ได้)
yousini lsp              # root = โฟลเดอร์ปัจจุบัน
yousini lsp /path/to/project
```

Neovim example (`init.lua`):

```lua
vim.api.nvim_create_autocmd('BufReadPost', {
  pattern = { '*.py', '*.js', '*.ts' },
  callback = function()
    vim.lsp.start({
      name = 'yousini',
      cmd = { 'yousini', 'lsp' },
      root_dir = vim.fn.getcwd(),
    })
  end,
})
```

The same engine is exposed over HTTP in the web UI — open the **CODE · LSP** panel (icon `{ }` in the top bar) to run definition / references / hover / document symbols on any file:

| Endpoint | Body |
| --- | --- |
| `POST /api/lsp/hover` | `{"file","line","character"}` |
| `POST /api/lsp/definition` | `{"file","line","character"}` |
| `POST /api/lsp/references` | `{"file","line","character"}` |
| `POST /api/lsp/document-symbols` | `{"file"}` |
| `POST /api/lsp/workspace-symbols` | `{"query"}` |
| `GET /api/lsp/summary` | — |

### Dashboard

Web UI มี panel **DASHBOARD** (icon กราฟแท่งในแถบบน) — สรุปภาพรวมของเซิร์ฟเวอร์:

| หัวข้อ | ข้อมูล |
| --- | --- |
| SERVER | model, version, uptime, cwd, โหมด safe |
| USAGE | token วันนี้/เซสชัน/รวม + กราฟ 7 วัน + tool ที่ใช้บ่อย (จาก `/usage`, opt-in) |
| SESSIONS | จำนวน session + session ล่าสุด (ชื่อ/เวลา/จำนวนข้อความ) |
| MARKETPLACE | จำนวน package ที่ติดตั้ง (และว่าเปิด/ปิด) |
| TEAM | workspace ที่ใช้งาน + จำนวนสมาชิก |
| SYMBOLS (LSP) | จำนวน symbol / ไฟล์ที่ index |

HTTP: `GET /api/stats` (ต้องมี token ถ้าเซิร์ฟเวอร์เปิด token) คืน JSON ชุดเดียวกัน.

---

## Marketplace / Skills & Plugins

Install skills and tool plugins from a registry — `yousini marketplace`:

```bash
yousini marketplace list                  # ดู catalog ทั้งหมด (cache 30 นาที)
yousini marketplace search seo            # ค้นตาม id/name/description/tags
yousini marketplace install <id|git-url|path> [--project] [--force]
yousini marketplace installed             # รายการที่ติดตั้งแล้ว
yousini marketplace uninstall <id>
yousini marketplace update <id>           # อัปเดต (หรือ update --all)
yousini marketplace info <id>
```

ใน session ใช้ `/market [search|install|uninstall <id>]` ได้เช่นกัน และ web UI มี panel **MARKETPLACE** (icon ถุงในแถบบน).

**Package format** — โฟลเดอร์/zip/git repo พร้อม `manifest.json` (หรือ `marketplace.yaml`):

```json
{
  "id": "web-tools",
  "name": "Web Tools",
  "version": "1.2.0",
  "description": "ชุดสกิลสำหรับงานเว็บ",
  "author": "Zedxv55",
  "license": "MIT",
  "price": 0,
  "currency": "USD",
  "tags": ["web", "seo"],
  "skills": ["skills/web_audit.md", "skills/seo_check.md"],
  "mcp_servers": [{"name": "wiki", "cmd": "python wiki_mcp.py"}]
}
```

- `skills` — ไฟล์ `.md` ติดตั้งเข้าคลัง skills (`~/.yousini/skills` หรือ `--project` → `./skills`); ระบุรายการ หรือปล่อยให้ auto-detect จาก `skills/*.md`.
- `mcp_servers` — tool plugins: ติดตั้งแล้วลงทะเบียนเป็น MCP client servers อัตโนมัติ (เครื่องมือขึ้นชื่อ `mcp__<server>__<tool>`).
- `price` / `currency` — เตรียมโครงสร้างสำหรับการขาย package ในอนาคต (ฟรี = `0`).

Registry: ตั้ง `YOUSINI_REGISTRY` (env) หรือ `registry_url` ใน config.json — ค่าเริ่มต้นชี้ที่รายการ registry ของ Yousini. Catalog โหลดแบบ fail-open (ออฟไลน์ → ใช้แคช), ตั้ง `marketplace_enabled: false` ใน config.json เพื่อปิดทั้งระบบ.

---

## Team / Multi-User Workspace

รัน Yousini ร่วมกันเป็นทีม — workspace แชร์ registry/skills ของทีม และ web server รองรับผู้ใช้หลายคนแบบมีสิทธิ์ (role):

```bash
yousini team init "DevOps Lab"          # สร้าง workspace โลคอล
yousini team join <url>                 # เข้าร่วมทีมจาก URL ของ team config ส่วนกลาง
yousini team set-registry <url>         # ชี้ registry ของทีม
yousini team users                      # ดูสมาชิก + registry ที่ใช้
yousini team status                     # ดูสถานะ workspace
yousini team leave                      # ออกจากทีม (เก็บ config โลคอลไว้)
```

ในแชทใช้ `/team` และแถบบน (banner) จะแสดง workspace ตอนเปิด session.

**Team config** — `~/.yousini/team.json` (หรือ `YOUSINI_TEAM_FILE`):

```json
{
  "workspace": "devops-lab",
  "name": "DevOps Lab",
  "url": "https://team.example/team-config.json",
  "registry": "https://team.example/reg.json",
  "users": [
    {"name": "alice", "token": "รหัส", "role": "admin"},
    {"name": "bob", "token": "รหัส", "role": "member"}
  ],
  "rules": {"auto_run": true, "safe": false}
}
```

- `url` (หรือ env `YOUSINI_TEAM_URL`) — team config ส่วนกลาง (JSON) ดึงมา merge ทุกครั้ง: ค่า remote ชนะเรื่อง `name`/`registry`/`rules` แต่ `users` ฝั่ง local ชนะ (ผู้ดูแลเครื่องตั้งเองได้). โหลดแบบ fail-open + cache 30 นาที.
- `users` — multi-user สำหรับ web server: แต่ละคนมี token + role. Role `admin` จัดการ marketplace (install/uninstall/update) ได้, `member` ใช้แชท/LSP/ดู catalog ได้ (ยิงคำสั่งแก้ marketplace จะได้ 403). ไม่มี `users` ตั้งไว้ = โหมด user เดียว (ทุกคนเท่ากับ admin).
- เปิด server: `yousini serve --token <รหัสหลัก>` — token หลักคือ `owner` (admin). Session ถูกแยกต่อผู้ใช้ (`<user>:<session>`).

---

## Agent Collaboration / คิวงาน

ส่งงานระหว่าง agent (agent-to-agent) ผ่าน **task queue** — persistent ใช้ร่วมกันได้หลายเครื่อง/หลายโปรเซส:

```bash
yousini agent send <worker> <โจทย์>     # ส่งงานเข้ารอคิว (จาก="cli")
yousini agent status                     # ดูคิว + สถานะ (pending/running/done/failed)
yousini agent result <id>                # ดูผลลัพธ์งาน
yousini agent requeue <id>               # ย้อนกลับเป็น pending
yousini agent reclaim                    # งาน running ที่ค้างเกิน 5 นาที → pending
yousini agent prune                      # ลบงานที่เสร็จแล้วเกินเกณฑ์
yousini agent clear                      # ล้างคิว

yousini work --once                      # worker: ประมวลผลงานค้างตอนนี้
yousini work --worker qa-1 --interval 5  # worker loop: poll ทุก 5s
```

ในแชท: `/agent send <worker> <โจทย์>`, `/agent status`, `/agent result <id>`, และ `/work` (ประมวลผลคิวทันที).

**ทำงานข้ามเครื่อง** — ทุกอย่างในคิวเป็น HTTP ได้ (`/api/queue/*`, ต้องมี token ถ้าตั้งไว้):

| Method/Path | การทำงาน |
| --- | --- |
| `POST /api/queue/enqueue` | `{"prompt","worker","priority"}` → เพิ่มงาน |
| `POST /api/queue/claim` | `{"worker"}` → รับงานถัดไป (priority สูงสุดก่อน) → `running` |
| `POST /api/queue/complete` | `{"id","result"}` → เสร็จ |
| `POST /api/queue/fail` | `{"id","error"}` → ล้มเหลว |
| `POST /api/queue/requeue` | `{"id"}` → กลับเป็น pending |
| `GET /api/queue/status` | สถานะ + งานล่าสุด |
| `GET /api/queue/get?id=<id>` | ดูงาน |

โครงงาน: `{id, from, worker, prompt, priority, status, created_at, started_at, done_at, result, error}` — งาน `running` ที่ค้างเกิน `YOUSINI_QUEUE_STALE` (ค่าเริ่มต้น 300s, worker ตายกลางทาง) ถูกย้อนกลับเป็น pending อัตโนมัติ. สถานะคิวแสดงใน DASHBOARD ด้วย. คิวเก็บที่ `~/.yousini/queue.json` (หรือ `YOUSINI_QUEUE_FILE`).

---

## Capabilities / ความสามารถขั้นสูง

### Git PR flow — เปิด Pull Request

สร้าง PR จากงานที่ทำได้ในคำสั่งเดียว: **commit งานค้าง → สร้าง/ใช้ branch → push → เปิด PR** (ใช้ `gh` ถ้ามี ไม่งั้นคืนลิงก์ compare ที่เปิดเบราว์เซอร์ได้):

```bash
yousini pr "เพิ่มโมดูลเว็บhooks"          # commit งานค้าง + สร้าง branch yousini/<slug> + push + PR
yousini pr list                            # รายการ PR ที่เปิด (ต้องมี gh)
```

ในแชท: `/pr <ชื่อ PR>` หรือ `/pr list`. Agent ใช้ได้ผ่าน tool `git_pr` (action=create|list) — เหมาะสำหรับเปิด PR หลังจบงาน. หา git อัตโนมัติ (env `YOUSINI_GIT` → PATH → ตำแหน่ง Windows ทั่วไป), push ใช้ `GIT_TERMINAL_PROMPT=0` ป้องกันค้าง.

### Project scaffolding — สร้างโปรเจกต์ทันที

เทมเพลตสำเร็จรูป (ไม่ใช้โมเดล — สร้างได้เลย):

```bash
yousini scaffold python-cli mycli        # CLI: pyproject + entry script + test
yousini scaffold python-pkg mylib        # แพ็กเกจ: __init__ + core + test
yousini scaffold web-static portfolio    # เว็บ static: index.html + style.css + app.js
```

ในแชท: `/scaffold <kind> <name>` (มี `[tool.pytest.ini_options] pythonpath=["."]` ใน pyproject — รัน test ได้ทันทีโดยไม่ต้องติดตั้ง). Agent ใช้ tool `scaffold`.

### Context ฉลาดขึ้น — compact แบบ chunked

`/compact` (และ auto-compact ตอน context เกิน `YOUSINI_MAX_TOKENS`) เปลี่ยนเป็นการสรุป **แบบแบ่งส่วน** — ตัดข้อความเก่าเป็น chunk (~6 ข้อความ/2500 ตัวอักษร) สรุปทีละ chunk ก่อนรวม — ลดโทเค็นได้มากกว่าแบบเดิมมาก และไม่เกิน context ของโมเดลในรอบเดียว.

### Dev tools — รวมตรวจโปรเจกต์

```bash
yousini dev all          # git status + ไวยากรณ์ Python + pytest + lint (ruff/flake8 ถ้ามี)
yousini dev compile      # ตรวจ .py ทั้งหมด
yousini dev test         # รัน pytest
yousini dev status       # สถานะ git
yousini dev lint         # ruff/flake8
```

ในแชท: `/dev [all|status|compile|test|lint]`. Agent ใช้ tool `dev_check` เพื่อยืนยันว่างานผ่านก่อนสรุป (เหมาะกับ TDD/หลัง refactor).

---

## Monetization / โมเดลธุรกิจ

Yousini is **open-source (MIT) and free to use**. Optional monetization features are opt-in, local-first and never intrusive:

| Feature | What it does | Privacy |
| --- | --- | --- |
| **Usage telemetry** | `/usage on` collects local token/tool statistics, shown via `/usage` and at session exit. `~/.yousini/usage.json` | Stays on your machine — nothing is sent out |
| **Sponsor line** | A subtle line under the banner / in the web UI status bar. `/ads off` hides it anytime | No tracking, no ad network |
| **Tiers & license** | Free is unlimited. `Pro`/`Team` keys unlock extra entitlements via `/tier activate <key>` (`YSN-XXXX-XXXX-XXXX`). Keys validate locally (`YOUSINI_LICENSE_URL` optional, fail-open) | Key never leaves your machine unless you self-host a license server |

Principles / หลักการออกแบบ:

- Opt-in only — nothing is enabled without your explicit choice.
- Non-intrusive — the sponsor line never blocks or interrupts your work.
- No ads, no selling telemetry, no mandatory subscription for basic tools.
- All config lives in `config.json` (`ads_disabled`, `tier`, `license_key`).

Free tier always works. Paying is only ever about optional extras.

---

## Security / ความปลอดภัย

- Shell commands require confirmation by default (`AUTO_RUN=0`); use the `e` key to edit a command before running.
- Dangerous patterns (`rm -rf`, `dd`, `shutdown`, ...) are blocked with a stronger warning.
- File edits show diffs before applying.
- Tool calls are wrapped in `try/except` so a failing tool never crashes the agent.
- For untrusted environments use `serve --safe` or `--no-shell` / `--no-write`.
- Never share your `.env` file; it is ignored by git.

---

## Troubleshooting / การแก้ไขปัญหา

### `Error: Python not found. Install Python from python.org and disable the Store app-execution alias.`

You only have the Microsoft Store stub for Python. Install Python from python.org and ensure "Add python.exe to PATH" is enabled.

> คุณติดตั้ง Python เป็นแค่ Store stub เท่านั้น ให้ติดตั้งจาก python.org และเปิด "Add python.exe to PATH"

### `ModuleNotFoundError: No module named 'openai'`

Dependencies are missing. Run `pip install -r requirements.txt` (or `pip install -e .`) inside the project.

> ไลบรารีไม่ถูกติดตั้ง ให้รัน `pip install -r requirements.txt` หรือ `pip install -e .` ในโฟลเดอร์โปรเจกต์

### `git: command not found`

Install Git. On Windows you can use the official installer or a portable MinGit build added to PATH.

### The agent answers but never calls tools

The API key may lack permissions or the model does not support tool calling. Try `mistral-large-latest` or another tool-capable model, and verify `YOUSINI_API_KEY` in `.env`.

### Yousini is not working after an update

Clear the cache and reinstall:

```bash
rm -rf __pycache__ yousini.egg-info .venv
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -e .
```

---

## License / สัญญาอนุญาต

Released under the MIT License. See `LICENSE`.

---

<p align="center">
Yousini — a local coding agent for the terminal.<br>
Yousini — coding agent สำหรับเทอร์มินัลของคุณ
</p>