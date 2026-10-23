# ผลทดลอง GPT-6 Luna กับเคสที่ V4 ยังไม่ผ่าน

วันที่ 23 ตุลาคม 2026 — ทดลองหนึ่งรอบด้วย OpenAI API จริง `gpt-6-luna`, reasoning `medium`, service tier `default` บนเคสสังเคราะห์ 11 เคสที่เลือกจากข้อผิดพลาดเดิม ได้ **8 PASS / 2 PARTIAL / 1 FAIL** ใช้ **60 requests, 385,356 tokens** ค่าประมาณ **US$0.053378915** รวม cache-write premium ไม่มีค่า usage ที่หายไป และไม่มีการตัดสินอนุมัติหรือปฏิเสธสินเชื่อจริง

PASS หมายถึงผ่านข้อกำหนดของสถานการณ์ทดสอบ ไม่ใช่ลูกค้าได้รับสินเชื่อ ตัวอย่าง H01 ผ่านโดยส่งข้อสงสัยให้เจ้าหน้าที่ และหยุดนำยอดที่ยังไม่ชัดมาคำนวณรายได้

## ขอบเขตที่เปรียบเทียบ

- เดิม 11 เคสนี้มี 10 FAIL และ 1 PARTIAL: 9 FAIL + C06 PARTIAL จาก V4 18 เคส และ H01 FAIL จากชุดเพิ่มเติม เลือกหลังเห็นข้อผิดพลาดแล้ว ไม่ใช่ blind test และไม่ได้ทดลอง 11 เคสที่เหลือซ้ำ
- ใช้ policy, calculator, controller, fixtures และ oracle เดิม ตรวจ frozen source **31/31 ไฟล์ ไม่มี drift**; source/input manifest หลังรันไม่มี drift รวม baseline SQLite
- ใช้ OCR ที่บันทึกไว้ตรงตามเดิม ไม่ได้เรียก OCR ใหม่ ลูกค้าเป็นข้อมูลสังเคราะห์และ KYC/onboarding เป็น mock; ทดสอบเฉพาะ agent review ไม่ใช่ Android → OCR → สินเชื่อครบระบบ
- เปลี่ยนทั้ง provider/API, strict function schema และการจัด context เป็น current snapshot แบบ stateless ดังนั้นยังแยกไม่ได้ว่าผลดีขึ้นจากโมเดลเพียงอย่างเดียว ต้องทำ controlled ablation เพิ่มหากต้องการตอบคำถามนั้น
- Oracle การเงินเดิมไม่เปลี่ยน เปลี่ยนเฉพาะ supplemental checks สองข้อที่ผูกกับชื่อ Typhoon/ตัวนับของ Typhoon ให้ตรวจ OpenAI receipts แทน ตัวนับ `llm_calls` เดิมจึงยังเป็น 0 สำหรับ OpenAI; จำนวนจริงคือ `provider_api_calls` และ receipts
- เป็นโมดูลทดลองแยก ยังไม่ได้เสียบเข้าเว็บเจ้าหน้าที่/production endpoint และยังไม่มีการ deploy AWS

## ผลรายเคส

| เคส | ประเด็น | ก่อน → รอบนี้ | Requests | Total tokens | ค่าประมาณ USD |
|---|---|---|---:|---:|---:|
| H01 | รายรับซ้ำจากขายอุปกรณ์เก่า | FAIL → PASS | 5 | 25,946 | $0.003710 |
| C01 | ข้อมูลครบ รายรับประจำ กำลังชำระเพียงพอ | FAIL → PASS | 4 | 21,695 | $0.003075 |
| C03 | โอนวนสองบัญชี ระบุ own transfer ชัด | FAIL → PASS | 5 | 57,250 | $0.008118 |
| C05 | เงินก้อนครั้งเดียว ไม่ทราบที่มา | FAIL → PARTIAL | 6 | 37,564 | $0.005176 |
| C06 | เงินก้อนขายอุปกรณ์ คำบรรยายมี sales | PARTIAL → PASS | 6 | 40,375 | $0.005608 |
| C08 | แจ้งรายจ่ายต่ำ แต่มีเงินออกประจำไม่ทราบประเภท | FAIL → PARTIAL | 6 | 46,853 | $0.006544 |
| C09 | ตัวเลขที่แจ้งไม่ตรง statement | FAIL → PASS | 6 | 34,190 | $0.004566 |
| C11 | แจ้งใช้สองบัญชี แต่ส่งบัญชีเดียว | FAIL → FAIL | 7 | 43,751 | $0.005699 |
| C12 | ธุรกิจเงินสดบางส่วนไม่ผ่านบัญชี | FAIL → PASS | 6 | 37,525 | $0.005246 |
| C14 | ขาดเดือนพร้อมมีเงินก้อนไม่ทราบที่มา | FAIL → PASS | 6 | 34,150 | $0.004735 |
| C16 | ยอดคงเหลือท้าย statement ไม่สมดุล | FAIL → PASS | 3 | 6,057 | $0.000903 |

**สิ่งที่เห็นจากหลักฐาน:** H01 อ่าน memo เรื่องขายอุปกรณ์เก่า เปิด `AGENT_RAISED` พร้อม refs ครบหกเดือน กันยอดจาก R และส่งคำถามขอหลักฐาน; C03 จับคู่เงินโอนตนเองได้; C12 คงยอดในบัญชีและแยกเงินสดที่ยังไม่พิสูจน์; C16 ส่งความขัดแย้งของยอดให้คนตรวจ ทั้งหมดมี `decision = null`

**C11 ยัง FAIL:** แม้จบที่ `WAIT_CUSTOMER` และบล็อกการคำนวณ แต่ยังไม่สร้างคำขอ statement ของบัญชีที่สองแบบเจาะจงตาม supplemental check มี `compare_declarations` ถูกปฏิเสธสามครั้ง จากนั้นส่งค่าบัญชีรวม `ACC-1 และ OWN-B` เป็น claim เดียว จึงเหลือ `DECLARATION_UNVERIFIED/UNPARSED` แทน `MISSING_ACCOUNT` ห้ามนำการหยุดอย่างระมัดระวังไปนับว่าแก้เคสนี้สำเร็จ

**C05/C08 ยัง PARTIAL ตาม oracle เดิม:** ข้อที่ไม่ผ่านคือ keyword check ว่าคำถามมีคำใดคำหนึ่งใน “ที่มา/ต้นทาง/ค่าเลี้ยงดู/ประเภทค่าใช้จ่าย/ทรัพย์สิน” แต่คำถามจริงใช้ “เป็นเงินประเภทใดและมาจากแหล่งใด” หรือถามวัตถุประสงค์ของเงินโอนประจำ ข้อการเงินและ supplemental checks ผ่าน นี่เป็นข้อจำกัดของตัววัดที่ควรตรวจด้วย rubric เชิงความหมายแยกต่างหาก; ไม่แก้คะแนนเดิมย้อนหลัง

## โทเคนต่อ task และต่อคำถาม

นับ 1 task เป็นการตรวจหนึ่งเคสจนส่งคน และ 1 คำถามเป็นหนึ่ง HTTP generation request ที่ให้โมเดลเลือก tool ถัดไป ไม่ใช่จำนวนประโยคในคำถามถึงลูกค้า

| รายการ | Tokens |
|---|---:|
| Input ทั้งหมด | 367,674 |
| Cached input — รวมอยู่ใน input แล้ว | 10,699 |
| Cache write — รวมอยู่ใน input แล้ว | 349,337 |
| Output ทั้งหมด | 17,682 |
| Reasoning — รวมอยู่ใน output แล้ว | 6,184 |
| รวม input + output | **385,356** |

เฉลี่ย **35,032 tokens/task**, median **37,525**; ช่วง **6,057–57,250** ต่อเคส เฉลี่ย **6,423 tokens/request**, ช่วง **1,811–13,236** ต่อ request จำนวนครั้งต่อเคส 3–7 ไม่มีเคสชนเพดาน 8 ครั้ง

ตัวอย่าง H01 ใช้ 5 requests รวม 25,946 tokens / US$0.003710350:

| รอบ | Tool ที่เลือก | Input | Output | Total |
|---|---|---:|---:|---:|
| 1 | `read_transactions` | 3,119 | 399 | 3,518 |
| 2 | `compare_declarations` | 4,881 | 78 | 4,959 |
| 3 | `flag_transactions` | 4,797 | 580 | 5,377 |
| 4 | `inspect_cashflow` | 5,304 | 41 | 5,345 |
| 5 | `finish_review` | 6,557 | 190 | 6,747 |

มี native response ที่ผ่าน schema 60/60 แต่ **11 actions ถูก validator ของเครื่องมือปฏิเสธ** หลังรับ response: quote ไม่ตรง 3, รูปแบบค่าจำนวนเงิน 3, claim บัญชี 3, ข้อความ finish ไม่ผ่าน neutral filter 2 รวม 68,683 tokens ใน requests เหล่านั้น ไม่ได้ตัดออกจากค่าใช้จ่าย ไม่มี transport/protocol failure ในรอบนี้

รายละเอียดครบ 60 requests: [CSV](../../outputs/lending-openai-luna-20261023/run-01/per-request-usage.csv), [JSON พร้อมผล validator](../../outputs/lending-openai-luna-20261023/analysis.json), [ตารางเปรียบเทียบรายเคส](../../outputs/lending-openai-luna-20261023/per-case-comparison.csv), [เปิดตารางโต้ตอบ](../../outputs/lending-openai-luna-20261023/results.html)

ราคาที่ใช้ต่อหนึ่งล้าน tokens: input $0.10, cached input $0.01, cache write $0.125, output $0.50 ตาม standard tier ณ วันที่ตรวจ สูตรคือ `(input−cached−write)×input rate + cached×cached rate + write×write rate + output×output rate` หารหนึ่งล้าน รอบนี้ไม่มีตัวนับที่ทับซ้อนกันเกิน input และคำนวณซ้ำจาก receipts ได้ตรงกัน [OpenAI model/pricing](https://developers.openai.com/api/docs/models/gpt-6-luna), [API pricing](https://developers.openai.com/api/docs/pricing)

ตัวเลขเงินเป็น **ประมาณการจาก usage ไม่ใช่ invoice หรือยอดเงินคงเหลือในบัญชี** ไม่รวมการใช้งานแชท/เครื่องมือวิจัย/subagents ของผู้พัฒนา หรือ OCR รอบก่อน ไม่มี generation call นอกรอบนี้; preflight เป็น GET metadata ไม่ใช่การสร้างคำตอบ

## การจัด context และสิ่งที่ควรปรับต่อ

แต่ละ request ส่ง current context เพียงชุดเดียว ใช้ JSON compact ไม่พ่วง snapshots เก่าหลายชุด เก็บ source groups, รายเดือน, unknowns, declarations และ observations ปัจจุบันครบ จำกัด output 4,096 tokens รวม reasoning ไม่เก็บ reasoning text และใช้ `store=false` ไม่มีการ retry HTTP หรือสลับโมเดล ปิด automatic truncation และตรวจ refs/schema ก่อนทำ tool

รอบนี้ input คิดเป็น **95.4%** ของ tokens ทั้งหมด และ cache hit เพียง **2.9% ของ input** ยังมีข้อมูลซ้ำระหว่าง source groups กับผล `read_transactions` และ schema รายการ refs การส่ง snapshot เดิมอย่างมีขอบเขตช่วยคุม state แต่ยังไม่ใช่ context ที่เล็กที่สุด

สำหรับเคสเดียวกัน Typhoon V4 เดิมใช้ 51 calls / 384,429 tokens เทียบ Luna 60 calls / 385,356 tokens (**รวมเพิ่ม 0.24%**) จึงห้ามกล่าวว่ารอบนี้ประหยัด tokens โดยรวม ตัวนับของคนละ provider ใช้ tokenizer ต่างกัน และบางเคสเดิมหยุดทางเทคนิคเร็วกว่ารอบนี้ จึงไม่ใช่ benchmark ประสิทธิภาพที่ควบคุมทุกปัจจัย

ลำดับที่แนะนำจากผลจริง:

1. ทำ contract ของ `compare_declarations` ให้ชัด: หนึ่งบัญชีต่อ claim, enum/ชนิดค่าที่เหมาะสม และบอกฟอร์แมตจำนวนเงินใน schema; ทดสอบอิสระกับ quote และ alias ก่อนเปลี่ยน production
2. แยกข้อผิดพลาด native JSON, argument validation, evidence semantics และ oracle ออกจากกัน เก็บ sanitized rejected arguments ที่จำเป็นในงานทดลองรอบถัดไป เพราะ receipts รอบนี้ไม่เก็บ arguments ของ action ที่ถูกปฏิเสธ จึงยังพิสูจน์รูปแบบผิดของแต่ละรอบทั้งหมดไม่ได้
3. ตรวจ neutral filter ด้วยประโยคยืนยัน/ปฏิเสธ และปรับ oracle คำถามเป็น rubric อิง refs/ประเด็น/หลักฐานที่ขอในชุดใหม่ โดยเก็บคะแนนชุดเดิมไว้
4. ลด context โดยเก็บ ledger/refs ที่เครื่องมือเข้าถึงได้ และส่งเฉพาะกลุ่มที่เปลี่ยนหรือยังค้าง ต้องมี regression ว่าไม่ทำข้อมูลสำคัญหาย; ยังไม่ได้ทดลองแนวทางนี้
5. โมเดลเล็กสำหรับจัดหมวดเป็นอีกการทดลองที่ควรทำหลังมี labels และหลักฐานวัตถุประสงค์ ไม่ใช่ตัวแก้ claim/schema หรือหลักฐานที่ไม่มีใน statement ดู [literature review](STATEMENT_CLASSIFICATION_LITERATURE_TH.md)

## การทำซ้ำและหลักฐาน

อ่าน `outputs/lending-openai-luna-20261023/design.md` ก่อนรัน ค่า credential อยู่ root `.env` ตัวแปร `OPENAI`; runner อ่านเฉพาะตัวแปรนี้และไม่ส่ง key ลงรายงาน

```powershell
. .\scripts\project-env.ps1
$env:PYTHONDONTWRITEBYTECODE = '1'
# เตรียม input เท่านั้น ไม่มีการเรียกโมเดล และต้องใช้ output path ใหม่
.\.venv\Scripts\python.exe -X utf8 tools/run_lending_openai_failed.py --output outputs/luna-prepare-new --prepare-only
# บรรทัดนี้คิดค่า API: เรียกเฉพาะเมื่อจะทดลองรอบใหม่
.\.venv\Scripts\python.exe -X utf8 tools/run_lending_openai_failed.py --output outputs/luna-run-new
```

ขอบเขต batch: 88 requests, input 400,000, output 64,000, estimated US$0.10; ต่อเคส 8 requests/240 วินาที ต้องจองงบก่อน dispatch และหยุดเมื่อ usage ไม่ทราบ การจำกัดนี้เป็น local ledger ไม่ใช่การตั้ง spending limit ของบัญชี

Offline integration/regression **138 tests ผ่าน** และ Ruff ผ่านก่อนรันจริง ดู [JUnit](../../outputs/lending-openai-luna-20261023/pytest-combined.xml), [รายงานจริง](../../outputs/lending-openai-luna-20261023/run-01/report.json), [source/input manifest](../../outputs/lending-openai-luna-20261023/run-01/manifest.json), [ตรวจบัญชี usage ซ้ำ](../../outputs/lending-openai-luna-20261023/independent-accounting.json)
