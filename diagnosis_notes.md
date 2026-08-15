# สรุปผลวินิจฉัย (15 ส.ค. 2026)

## สถานะ: บั๊กส่วนใหญ่ reproduce ไม่ได้ใน env นี้ แต่ root cause ชัดเจนจาก CI log

### 1. yousini_symbols — FAIL ใน CI (test_build_index_python_kinds, test_js_support, test_stale_rebuild)
- รันผ่านใน sandbox นี้ (6/6 pass) → ไม่ใช่บั๊กลอจิกหลัก
- สันนิษฐาน root cause: ใน CI (CI run 31784780714) test_symbols fail เพราะ **test รันก่อน install dependencies สำเร็จ?** — ไม่ใช่ (install ทำก่อน)
- จาก CI log: "5 failed, 196 passed" ใน ubuntu 3.12 = fail: hooks_resolution, git_pr x2, profile x2 — symbols ไม่ได้ fail ใน ubuntu 3.12 แต่ fail ใน run อื่น/บาง matrix
- บั๊กที่แท้จริงที่แก้ได้ในโค้ด:
  a) `_is_stale()` เปรียบเทียบ mtime แบบ float — ใน filesystem ที่ความละเอียดต่ำ (Windows FAT/ext3, CI runner) mtime อาจ trunc → false negative → cache เก่าไม่ rebuild → **ต้องใช้ st_mtime_ns หรือเทียบ >= กับ tolerance** — เป็น root cause ของ stale_rebuild ในบางสภาพ
  b) JS `_parse_js` ไม่รองรับ `export const NAME = "yousini"` แบบ deep — จริงๆ walk เดินเข้า export_statement → variable_declarator ได้ (pass ใน sandbox) แต่ `variable_declarator` ที่อยู่ใน `export_statement` child_by_field_name('name') ใช้ได้ — ข้อคิด: grammar ใหม่ js อาจเปลี่ยนชื่อ field 'name' → KeyError 'start' ที่เจอคือ node.name? ไม่ใช่
  c) **KeyError 'start'** ที่ CI แจ้ง: มาจาก `_txt(node)` ไม่ใช่ — มาจาก node["start"]? ไม่มี code แบบนั้น → น่าจะเป็น tree-sitter 0.22 API เก่า (`node.start_point` ใช้ได้เสมอ) → KeyError 'start' มาจาก `node['start']`? ตรวจไม่พบ → เป็นไปได้ว่าเกิดจาก version เก่าของ tree-sitter ที่ `child_by_field_name` fail? ไม่
  - สรุป: แก้ที่ resilience — ห่อ `child_by_field_name` ด้วย try/except, ใช้ children scan fallback, ใช้ mtime ns + tolerance
  - แก้เพิ่ม: ใช้ `os.path.getmtime` พร้อม tolerance 0.1s กัน false negative, ใช้ mtime_ns เมื่อระบบรองรับ

### 2. test_git_pr (2 failed) — รากลึกชัดเจน
- `gh pr create --json url` → **gh ไม่มี flag `--json` สำหรับ pr create** (มีเฉพาะในบางคำสั่งเช่น pr list)
- yousini_git.py บรรทัด ~227 ใช้ `["pr","create",..., "--json","url"]` → fail ทุกครั้งที่ gh มีจริง
- ใน test: mock subprocess → gh fake รับทุก flag? ไม่ — test ใช้ gh จริงใน temp repo
- แก้: เปลี่ยนเป็น parse URL จาก stdout ของ `gh pr create` (สร้าง PR แล้วพิมพ์ URL), หรือ `gh pr view --json url` (หลัง create, ด้วย --state open), หรือ `gh api` — วิธีปลอดภัยสุด: ใช้ `gh pr create` แล้วจับ stdout (URL อยู่บรรทัดสุดท้าย) หรือ `gh pr view <branch> --json url --state open`
- Test คาดหวัง: output มี '/compare/main...<branch>?expand=1' หรือ pr url → ให้สร้าง URL เอง: `https://{remote}/compare/{base}...{branch}?expand=1` เมื่อ gh ล้มเหลว

### 3. test_profile (2 failed) — รากลึก: env
- subprocess.run ใช้ `_CLEAN_ENV = {k:v for k,v in os.environ if not k.startswith("YOUSINI_")}` → ลบ YOUSINI_API_KEY → import yousini → `if not API_KEY: sys.exit('Error: ...')` → **returncode != 0, stdout ว่าง** → len(lines)==1 → fail
- แก้: คง YOUSINI_API_KEY (และ YOUSINI_MODEL ฯลฯ) ไว้ใน env ของ subprocess หรือ ใส่ API key ปลอมเมื่อ run test
- CI: ไม่เคยตั้ง YOUSINI_API_KEY → test profile fail ทุกครั้ง
- แก้ 2 ฝั่ง: (a) ใน test: ค้าง YOUSINI_API_KEY ไว้ (ใส่ค่าปลอม test) + (b) CI workflow: set YOUSINI_API_KEY=dummy ใน env ของ test step + pytest mark skip เมื่อไม่มี

### 4. test_hooks_resolution (1 failed)
- test สร้าง hooks_dir แล้ว `Hooks(str(hooks_dir), str(tmp_path))` → _resolve_dir จะพบ hooks_dir ก่อน → dir ตั้งค่า ok
- `h.has_hooks()` fail → means _resolve_script('pre_tool') ไม่พบ pre_tool.bat ใน Windows? ไม่ — test รันบน ubuntu → order = [('.sh', ['bash'])...] → hooks_dir เป็น Path(str) → `.yousini/hooks` อยู่ใน temp → **จุด.fail: candidate แรก c = Path(hooks_dir).expanduser() ควรเป็น dir → is_dir = True** → ควรผ่าน
- จริงๆ: fail หมายถึง h.has_hooks() == False → _resolve_script ไม่เจอไฟล์? ให้ดู _resolve_script ต่อ: ใช้ glob('pre_tool.*')? ต้องอ่านโค้ดต่อ
- รัน test นี้ที่นี่: fail → ต้องแก้ Hooks resolution ให้ค้นหาไฟล์ hook จาก dir ที่ระบุ + wildcard extensions

### 5. คุณภาพ:
- gh ปัจจุบัน 2.97.0 ไม่มี --json ใน pr create (ยืนยันแล้ว: gh pr create --help ไม่มี json) → โค้ดเก่าผิดชัดเจน

## แผนการแก้ (Phase 2)
1. yousini_symbols.py:
   - _is_stale: ใช้ mtime_ns + tolerance 1s (กัน filesystem precision)
   - ห่อ tree-sitter parsing ด้วย exception handling ที่ละเอียดกว่า (ไม่กลืน exception ทั้งไฟล์แบบเงียบ — log warn เมื่อ debug)
   - variable_declarator fallback: scan children เมื่อ child_by_field_name ให้ None
   - ใช้ `start_point` ตรง (ไม่มี KeyError จริง แต่เพิ่ม safety)
2. yousini_git.py: แก้ create_pr — ไม่ใช้ --json; แก้ parse output; fallback compare URL
3. yousini.py Hooks._resolve_script: ตรวจและแก้ (ต้องอ่านโค้ดเต็มก่อน)
4. tests/test_profile.py: คง YOUSINI_API_KEY ใส่ subprocess env
5. conftest.py: อ่าน — ดูว่ามี setup อะไร
6. CI workflow:
   - set env YOUSINI_API_KEY=dummy, GH_TOKEN=g ${{ secrets.GITHUB_TOKEN }}
   - แยก integration tests (git_pr, telegram, update, web_search) ด้วย mark: skip เมื่อไม่มี GH_TOKEN/net
   - เพิ่ม matrix filter: รัน test_symbols เฉพาะเมื่อ deps พร้อม (pip install -e . อยู่แล้ว — ok)
   - เพิ่ม step: ยืนยัน no API key error ไม่นับ fail (เทคนิค: ใส่ dummy key)
7. README/CHANGELOG + version sync (pyproject 3.8.0 → tag v3.8.0)
