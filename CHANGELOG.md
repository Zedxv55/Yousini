# CHANGELOG

## v3.11.0 (2026-08-17)

### ใหม่
- `/persona` REPL command — สับสวิตช์บุคลิก prompt preset: `casual`, `formal`, `concise`, `verbose`, `reset` (B4)
- `/compact` REPL command — ปรับปรุง context compaction

### Quality
- Test coverage: 60% → **74%** (ผ่านเกณฑ์ CI 70%)
- เพิ่ม test suites ใหม่: vision, chat_turn, run_turn_events, subagent, completer, print helpers, provider, permission, login, plan, web server routes, CLI subcommands, server HTTP routes, /persona

### CI
- fail-under = 70% ใน quality job
- Trusted Publisher (OIDC) auto-publish ไป PyPI เมื่อ push tag `vX.Y.Z` (publish.yml)
- แก flaky tests บน Windows runner และ runner ที่ไมม git config/global

### Bug fixes
- CI Windows: skip POSIX-specific launcher tests, shell tests บน Windows
- CI Ubuntu: git config user.name/email ใน test repos
- CI quality: replace `requests` dependency with urllib ใน server tests
