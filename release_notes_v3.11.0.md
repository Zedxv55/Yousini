# Yousini v3.11.0 — Free AI Agent CLI

Yousini v3.11.0 ยกระดับการทำงานร่วมกับ AI ในรูปแบบ **Free AI Agent CLI** ที่เลือกใช้งานได้ทั้ง Terminal และ Web App พร้อมเครื่องมือสำหรับงานเบื้องหน้า งานเบื้องหลัง และการติดตามผลลัพธ์เป็นรายงาน

## ไฮไลต์ของรุ่นนี้

### ใช้งานง่ายผ่าน Terminal หรือ Web App

- เปิดโหมดสนทนาด้วย `yousini`
- สั่งงานครั้งเดียวด้วย `yousini "<prompt>"`
- เปิด Web App ในเครื่องด้วย `yousini serve`
- เชื่อมต่อ instance ระยะไกลด้วย `yousini connect <url>`
- มีโหมดปลอดภัย `yousini serve --safe` สำหรับปิด shell และการเขียนไฟล์

### ทำงานเบื้องหน้าได้อย่างมีประสิทธิภาพ

- รองรับการอ่านและเขียนไฟล์ การแก้ไขแบบมี diff การรัน shell และการตรวจสอบโปรเจกต์
- มี `/plan`, `/todos`, `/checkpoint`, `/rollback` และ `/compact` เพื่อควบคุม workflow ให้ตรวจสอบได้
- มี `/approve on` และ `/approve off` สำหรับควบคุมการอนุมัติคำสั่งที่มีผลต่อเครื่อง
- ใช้ `/persona casual`, `/persona formal`, `/persona concise`, `/persona verbose` หรือ `/persona reset` เพื่อเปลี่ยนรูปแบบการตอบ

### ทำงานเบื้องหลังและจัดการคิวงาน

- ส่งงานเข้า queue ด้วย `yousini agent send <worker> <prompt>`
- เปิด worker ด้วย `yousini work --worker <name>`
- ตรวจงานด้วย `yousini agent status` และ `yousini agent result <id>`
- รองรับ `requeue`, `reclaim`, `prune` และ `clear` เพื่อจัดการงานที่ล้มเหลว ค้าง หรือเสร็จแล้ว
- รองรับโหมดรันรอบเดียวด้วย `yousini work --once` สำหรับการประมวลผลแบบ batch หรือ cron

> เป้าหมายของ queue workflow คือทำให้ทุกงานที่ส่งเข้าไปมีสถานะและผลลัพธ์ตรวจสอบได้อย่างชัดเจน ไม่ใช่เพียงสั่งงานแล้วหวังว่าจะเสร็จเอง หากงานใดล้มเหลวหรือค้าง ผู้ใช้สามารถตรวจสอบและ requeue ได้เป็นรายงาน

## ตัวอย่างการใช้งาน

```bash
# งานเบื้องหน้า
yousini "ตรวจ test และ lint ทั้งโปรเจกต์ พร้อมสรุปปัญหา"

# งานผ่าน Web App
yousini serve

# งานเบื้องหลัง
yousini agent send worker-1 "ตรวจ test ใน src/ และสรุปผล"
yousini work --worker worker-1
yousini agent status
```

## คุณภาพและความเสถียร

- มีการทดสอบทั้งหมด 548 tests ผ่าน
- Test coverage อยู่ที่ 74% สูงกว่าเป้าหมาย 70%
- เพิ่มชุดทดสอบสำหรับเส้นทางการทำงานของ Agent, context, session, tools และคำสั่ง `/persona`
- ปรับปรุงการเผยแพร่แพ็กเกจ Python บน PyPI

## การติดตั้ง

```bash
pip install yousini==3.11.0
yousini --version
```

## หมายเหตุด้านความปลอดภัย

Yousini ทำงานบนเครื่องของผู้ใช้และอาจเรียกใช้ shell หรือแก้ไขไฟล์ตามสิทธิ์ที่กำหนด ควรตรวจ prompt และเปิดใช้ `--safe`, `--no-shell`, `--no-write` หรือ approval controls เมื่อทำงานกับโค้ดหรือข้อมูลที่ไม่คุ้นเคย

## ลิงก์

- [README และ Usage Examples](https://github.com/Zedxv55/Yousini#usage-examples--ตัวอย่างคำสั่งการใช้งาน)
- [PyPI: yousini 3.11.0](https://pypi.org/project/yousini/3.11.0/)
- [รายงานการเปลี่ยนแปลง](https://github.com/Zedxv55/Yousini/blob/main/CHANGELOG.md)

ขอบคุณทุกคนที่ทดลองใช้และช่วยผลักดัน Yousini ให้เป็น AI Agent CLI ที่ใช้งานได้จริงในทุกวัน
### หมายเหตุการเผยแพร่

- รุ่นนี้ใช้ tag `v3.11.0`
- แพ็กเกจพร้อมติดตั้งจาก PyPI ด้วย `pip install yousini==3.11.0`
- ไฟล์ release ถูกสร้างจาก source distribution และ wheel ของรุ่นเดียวกัน

## การตรวจสอบงานแบบ 100/100

สำหรับ workflow ที่มีงานจำนวนมาก ให้ใช้ queue และตรวจสถานะรายงานทุก task แทนการยิงคำสั่งซ้ำโดยไม่มี tracking:

```bash
for i in $(seq 1 100); do
  yousini agent send worker-1 "ทำงานรายการที่ $i และบันทึกผลลัพธ์"
done

yousini work --worker worker-1 --once --max 100
yousini agent status
```

รูปแบบนี้ช่วยให้ผู้ใช้เห็นจำนวนงาน pending, running, done และ failed พร้อม requeue เฉพาะรายการที่ยังไม่สำเร็จได้ จึงเหมาะกับเป้าหมายการทำงานให้ครบทุกงานและตรวจสอบได้จริง

> หมายเหตุ: ความสำเร็จของแต่ละงานยังขึ้นกับ prompt, provider, สิทธิ์ของระบบ, เครือข่าย และทรัพยากรเครื่อง Yousini จึงออกแบบให้มีสถานะและ recovery tools เพื่อให้จัดการงานที่ไม่สำเร็จได้อย่างโปร่งใส

## Full Changelog

ดูรายละเอียดเชิงเทคนิคทั้งหมดได้ใน [CHANGELOG.md](https://github.com/Zedxv55/Yousini/blob/main/CHANGELOG.md)

**Full Changelog**: https://github.com/Zedxv55/Yousini/compare/v3.10.0...v3.11.0
