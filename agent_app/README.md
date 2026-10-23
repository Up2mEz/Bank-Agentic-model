# Merchant agent application

โฟลเดอร์หลักสำหรับดูแลระบบช่วยเจ้าหน้าที่พิจารณาสินเชื่อร้านค้า ตั้งแต่
onboarding read, OCR, ตรวจ statement, คำนวณตามกฎ, agent เรียก tools และรายงาน
ไปจนถึงเว็บเจ้าหน้าที่ โดยคงชื่อ Python package `merchant_sandbox` เพื่อให้
Go/Android ที่เชื่อมอยู่ใช้ contract เดิมได้

## โครงสร้าง

```text
agent_app/
  pyproject.toml                 dependency และคำสั่งทดสอบของแอป
  run.py                         เปิดเว็บเจ้าหน้าที่
  src/merchant_sandbox/
    core.py, lending.py           controller และเครื่องมือคำนวณเดิม
    agentic_review.py            native-tool review loop ที่มีขอบเขตการทำงาน
    agentic_typhoon.py            Typhoon adapter
    agentic_openai.py             OpenAI adapter และงบ token
    bank.py, review.py            ข้อมูลธนาคารและการตัดสินใจของเจ้าหน้าที่
    ocr.py, statements.py         อ่านเอกสารและตรวจรายการ
    statement_report.py          รายงานหลักฐาน 4 ส่วน
    statement_experiment.py      context และ trace ของการทดลองรายงาน
    server.py, static/           HTTP service และหน้าเจ้าหน้าที่
    paths.py                     ตำแหน่ง resources ใน workspace
  tools/                         ตัวรันทดลองและ evaluator
  tests/                         regression ของแอป รวม browser JS tests
```

แก้ implementation ที่นี่เพียงแห่งเดียว ส่วน `src/creditrisk/` ที่ราก repository
เป็นงานวิจัยโมเดลเครดิต มี dependencies และ tests ของตัวเอง

**ขอบเขตเดิมยังเหมือนเดิม:** server ใช้ `LendingController`;
native agent และรายงาน 4 ส่วนเป็นการทดลองแยก การย้ายโฟลเดอร์ไม่ได้เชื่อมทั้งสอง
เข้าด้วยกันหรือเพิ่ม workflow เพิ่มวงเงิน การตัดสินอนุมัติยังเป็นของเจ้าหน้าที่

## ติดตั้งและรันจาก repository root

ใช้ Python 3.12 ขึ้นไป สำหรับเพื่อนที่ clone ใหม่ รันจาก root ของ repository:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e './agent_app[dev]'
.\.venv\Scripts\python.exe agent_app/run.py --port 8770 --db outputs/agent_app/dev.sqlite3
```

เปิด `http://127.0.0.1:8770/` เพื่อดูเว็บเจ้าหน้าที่ หรือ `/lab` เพื่อสร้างเคสสังเคราะห์
และเลือก **baseline** โดยไม่เรียก API ค่าเริ่มต้นไม่เชื่อม Go และไม่มีข้อมูลลูกค้าเดิม
การยื่นจาก Android ต้องรัน Go/Flutter และตั้งค่าตาม integration contract เพิ่ม

สำหรับ workspace เดิมที่ติดตั้ง Merchant toolchain แล้ว:

```powershell
. .\scripts\project-env.ps1
uv pip install --python .venv\Scripts\python.exe -e './agent_app[dev]'
.\.venv\Scripts\python.exe agent_app/run.py --help
.\.venv\Scripts\python.exe agent_app/run.py --port 8770 --db outputs/agent_app/dev.sqlite3
```

ตัวอย่างนี้ใช้ DB และ port แยกจาก wallet demo ที่กำหนดไว้บน 8768
`scripts/project-env.ps1` ใช้กับเครื่องที่มี Merchant SDK/cache อยู่แล้ว;
Python-only checkout ใหม่ใช้คำสั่งติดตั้งด้านบนได้ สามารถเพิ่ม argument การเชื่อม Go และไฟล์ credential ตาม
[integration contract](../docs/merchant_lending/onboarding-integration-contract.md)
ได้ คำสั่ง `merchant-agent` หลังติดตั้งเรียก server เดียวกัน

บน Linux/macOS เปลี่ยนเป็น `.venv/bin/python` และใช้ environment ของระบบ
ตามปกติ ตัว server นี้ยังเป็น local sandbox ไม่ใช่ production authentication

## ทดสอบ

จาก repository root (workspace ที่มี Merchant tooling ให้ source `scripts/project-env.ps1` ก่อน):

```powershell
# เฉพาะแอป ใช้ configuration ของ agent_app
.\.venv\Scripts\python.exe -m pytest -c agent_app/pyproject.toml agent_app/tests -q
node --test agent_app/tests/wallet_final_ui.test.cjs

# รวมงานวิจัยและแอป ต้องติดตั้ง dependencies งานวิจัยเพิ่มก่อน
.\.venv\Scripts\python.exe -m pip install -r requirements-core.txt -r requirements-dev.txt -e .
.\.venv\Scripts\python.exe -m pytest -q
```

บาง replay tests ต้องใช้ historical baseline ใน `outputs/` ของ workspace นี้
และมี marker `historical_replay` ชุดข้อมูลนี้ไม่รวมใน Git: ถ้าไม่มีทั้ง bundle
tests ส่วนนั้นจะ skip พร้อมเหตุผล; ถ้ามี bundle แต่ไฟล์ไม่ครบ/เสียจะ fail
การตรวจ package/import/CLI และ synthetic tests ใช้แยกจาก live provider ได้
โดยไม่เรียก LLM/OCR ต้องรายงานจำนวน skip แยกจากผลผ่านเสมอ

อ่าน [รายงานสถานะให้ทีม](../docs/merchant_lending/TEAM_AGENTIC_STATUS_20261024_TH.md)
เพื่อแยกผล tests ของโค้ดออกจากผล live model ที่ยังไม่ผ่าน acceptance
เอกสารผลทดลองวันที่ 23 ต.ค. อ้างอิงไฟล์ `outputs/` ในเครื่องผู้ทดลอง;
ไฟล์ดิบเหล่านี้ไม่รวมใน Git และลิงก์ส่วนนั้นจะใช้ไม่ได้ใน fresh clone

## ตัวรันทดลอง

ใช้ `python agent_app/tools/<ชื่อไฟล์>.py --help` เพื่อดูตัวเลือกของ runner เช่น
`run_lending_agentic_experiment.py`, `run_lending_agentic_heldout.py`,
`run_lending_openai_failed.py` และ `run_statement_review_experiment.py`
คำสั่ง live ต้องระบุ provider/budget ตาม runner; การย้ายโฟลเดอร์ไม่เรียก API

ตัวรันที่ผูกกับ frozen V4 ยังตรวจ source เดิมแบบ fail-closed การย้ายทำให้ source
identity เปลี่ยน สำหรับการทดลองรุ่นใหม่ ทั้ง OpenAI และรายงาน 4 ส่วนรับ
`--source-manifest <ไฟล์ใน repository>` รูปแบบ
`{"files":[{"path":"agent_app/…","sha256":"…"}]}` โดยต้องครอบคลุม runtime
ทุกโมดูล, experiment tools 8 ไฟล์, policy และ fixture specifications ทั้งสองไฟล์
ตัวตรวจปฏิเสธไฟล์ขาด/hash เปลี่ยน/path ออกนอก repository/รายการซ้ำ และตรวจซ้ำ
หลังรัน ใช้ `--prepare-only` เพื่อตรวจเตรียมข้อมูลโดยไม่อ่าน credentials/เรียก API

Snapshot ที่ระบุเองบันทึกเป็น `EXPLICIT_SOURCE_SNAPSHOT`, `v4_acceptance: false`
ต้องจัดทำและทบทวน snapshot รุ่นใหม่ก่อนทดลอง ห้ามแก้ hash ในหลักฐานเก่าเพื่อให้
การตรวจผ่าน ผลทดลองเดิมยังอยู่ที่
[เอกสารผลรายงาน 4 ส่วน](../docs/merchant_lending/STATEMENT_FOUR_PART_RESULTS_TH.md)

## Resources และ compatibility

- `docs/merchant_lending/`: contract, policy JSON, design และผลตรวจที่อ้างอิง
- `examples/merchant_sandbox/`: synthetic fixtures และ oracle เดิม
- `outputs/<run>/`: DB ของการทดลอง, snapshots, trace และ receipts
- `.local/merchant-dev/`: tools/cache; `repos/`: Go/Flutter checkouts
- Secrets อยู่ใน environment/ไฟล์เดิม ไม่คัดลอกเข้า `agent_app`

`paths.py` หา repository จากตำแหน่ง package โดยไม่ขึ้นกับ working directory
ถ้าติดตั้ง wheel นอก checkout ให้ตั้ง `AGENT_APP_WORKSPACE` ชี้ repository ที่มี
policy/fixtures ทั้งชุด การติดตั้งแอปไม่ต้องติดตั้ง CatBoost/LightGBM หรือ research
package; การแจกจ่ายเฉพาะ folder นี้ยังไม่รวม shared resources และผลทดลองเก่า

คำสั่ง `scripts/run_merchant_sandbox.py`, runner ใน root `tools/` และ import ผ่าน
`PYTHONPATH=src` เป็น compatibility entry points ที่ส่งต่อมาที่ implementation
นี้ Root package ไม่รวม shim ใน wheel ส่วน junction `src/merchant_sandbox/static`
เป็นของ local เครื่องนี้เพื่อให้ process ที่เปิดก่อนย้ายยังอ่านหน้าเว็บได้ ไม่อยู่
ใน Git และ process ใหม่ไม่ต้องใช้ junction นี้
