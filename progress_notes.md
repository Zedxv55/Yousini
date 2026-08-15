# ความคืบหน้างาน fix Zedxv55/Yousini (15 ส.ค. 2026)

## Repo: /home/ubuntu/Yousini (clone มาแล้ว, main branch)

## Root causes ที่วินิจฉัยแล้ว (บันทึกเต็มใน diagnosis_notes.md)
1. yousini_symbols.py — mtime float precision (false negative stale), tree-sitter JS field access  fragile
2. yousini_git.py — `gh pr create --json url` flag เท็จ (gh 2.97 ไม่มี --json ใน pr create) → fail ทุกครั้ง
3. test_profile.py — ลบ YOUSINI_API_KEY จาก subprocess env → import yousini sys.exit → fail ทุกครั้ง
4. yousini.py Hooks._resolve_script — Linux: ไฟล์ .bat hook พบแต่ skip เพราะ shutil.which("cmd")=None → has_hooks()=False

## สิ่งที่แก้ไปแล้ว (ทำ edit เสร็จ)
- [x] yousini_symbols.py: _is_stale() ใช้ mtime_ns + tolerance 1s + normalize ns; build() fallback regex เมื่อ parse พัง; _parse_js ใหม่ resilient (_field() fallback scan identifier)
- [x] yousini_git.py: remove --json, parse URL from stdout (last http line), fallback compare URL ทั้งกรณี gh สำเร็จ/ล้มเหลว
- [x] yousini.py: Hooks._resolve_script เพิ่ม cross-platform fallback (bat บน Linux รันด้วย bash)

## สถานะ ณ ตอนนี้ (13:01)
- FIX ครบ: pytest เต็ม suite = 201 passed, 0 failed (เดิม 8 failed)
- Commit แล้ว: 56b9556 (changelog 3.8.1 added ใน README, ci.yml, test_profile, yousini.py Hooks, yousini_git.py create_pr, yousini_lsp.py references, yousini_symbols.py fixes)
- หมายเหตุ: version ใน repo เป็น 3.8.0 อยู่ — fix นี้ควร tag เป็น v3.8.1 (เลข minor fix) — ผู้ใช้ขอ Release v3.8.0 แต่โค้ดบน repo คือ 3.8.0 แล้ว (pyproject = 3.8.0) → tag v3.8.1 + update pyproject? ตัดสินใจ: tag v3.8.1 เพราะ 3.8.0 tag ไปแล้ว(ไม่ใช่ — tag สุดท้าย v2.1.0) → อิง pyproject 3.8.0 → tag v3.8.0 ตามที่ผู้ใช้ขอ
- เหลือ: push, tag v3.8.0, gh release create, เขียนแผนงาน release_plan_v3.8.0.md + final summary, ส่งมอบ
- ไฟล์แผนงานต้องสร้าง: /home/ubuntu/release_plan_v3.8.0.md
- รายงานเดิมที่ส่งแล้ว: /home/ubuntu/yousini_report.md

## ยังต้องทำ
1. แก้ tests/test_profile.py — ค้าง YOUSINI_API_KEY ใน _CLEAN_ENV (ใส่ค่าปลอม 'dummy') หรือเพิ่ม env YOUSINI_API_KEY
2. อ่าน test_git_pr.py เต็ม (sed -n 30,70) — ตรวจ assert คาดหวัง: คาด /compare/main...branch?expand=1 → โค้ดใหม่คืน "... — เปิด PR ได้จากลิงก์นี้:\nhttps://..." → assert 'in' น่าจะ pass แต่ต้องตรวจว่า test set GH_TOKEN ไหม
3. รัน pytest เต็ม suite ให้ผ่าน (ตอนนี้ 8 fail → ต้อง 0 fail)
4. แก้ CI workflow .github/workflows/ci.yml:
   - เพิ่ม env: YOUSINI_API_KEY: dummy, GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
   - แยก integration tests ที่ต้องการ GH_TOKEN (test_git_pr) — mark pytest: skip เมื่อไม่มี GH_TOKEN ให้ run ใน CI ภายใต้ token จริง
   - test_hooks_resolution: ตอนนี้ควร pass เมื่อ fix Hooks แล้ว (test สร้าง .bat hook บน linux)
   - อาจลด matrix: รัน windows-latest 3.12 เท่าที่จำเป็น (ค้างไว้ แต่ให้ผ่าน)
5. อ่าน README ส่วน changelog — เพิ่ม heading "## Changelog / บันทึกการเปลี่ยนแปลง" หรือแก้เวอร์ชัน sync: pyproject 3.8.0, README บอก 3.8.0 → tag v3.8.0
6. รัน test อีกครั้ง → commit → push → tag v3.8.0 → gh release create v3.8.0 --title "Yousini v3.8.0 — Fix CI & Symbol Engine" --notes <changelog>
7. พิมพ์แผนงาน Release v3.8.0 + PyPI (docs: /home/ubuntu/release_plan_v3.8.0.md) + รายงานสรุปผลการวิเคราะห์ (update yousini_report.md หรือสร้างไฟล์ใหม่ final_summary.md)
8. ส่งมอบ: attachment รายงาน + ไฟล์แผนงาน + ผลลัพธ์ push/repo

## ข้อมูลสำคัญอื่นๆ
- CI log ที่ดึงมา: /home/ubuntu/ci_log_all.txt (31784780714 = run ล่าสุด fail)
- FAIL เดิม: test_hooks_resolution, test_create_pr_auto_branch, test_create_pr_named_branch, test_profile_env_changes_dirs, test_profile_default_when_unset, test_build_index_python_kinds, test_js_support, test_stale_rebuild
- test suite ตอนนี้: 194 tests (8 failed, 186 passed) — test_symbols 6 tests, test_git_pr 2, test_profile 2
- conftest.py มีแค่ sys.path insert
- gh CLI 2.97.0 login แล้ว, user: Zedxv55
- README บอก version 3.8.0, Python 3.10+, MIT, EN/TH
- Release ล่าสุด GitHub: v2.1.0, v2.0.0 (~4 วันก่อน)
- ไฟล์รายงานเดิม: /home/ubuntu/yousini_report.md, /home/ubuntu/zeetest1_report.md

## หมายเหตุ syntax ภาษาไทยใน code repo
- โค้ด repo ใช้ภาษาไทยใน comment/docstring บ่อยครั้ง — ไม่ต้องตาม แต่ต้องเข้าใจได้
