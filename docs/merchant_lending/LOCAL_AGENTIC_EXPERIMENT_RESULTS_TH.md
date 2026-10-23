# ผลทดลอง Local Agentic Lending — 23 ตุลาคม 2026

**ทดลองครบแล้ว แต่ยังไม่ผ่านเกณฑ์นำไปใช้กับเจ้าหน้าที่หรือการให้สินเชื่อจริง** รุ่นสุดท้าย V4 ได้ 8 PASS / 1 PARTIAL / 9 FAIL ใน 18 เคสเดิม เทียบกับ baseline 9 / 3 / 6 จึงยังอ้างไม่ได้ว่า agentic รุ่นนี้ดีกว่า baseline โดยรวม แม้แก้พฤติกรรมสำคัญบางเคสได้แล้ว

ข้อผิดพลาดที่สำคัญที่สุดคือ **H01: เงินขายทรัพย์สินเข้าซ้ำทุกเดือน โมเดลไม่เปิดประเด็น และ sandbox packet ยังมี `RECOMMEND_APPROVE`** ไม่มีการอนุมัติหรือจ่ายเงินจริง (`decision=None`) แต่คำแนะนำนี้ยังไม่ปลอดภัยพอสำหรับใช้งานจริง จึงบันทึก [promotion gate: BLOCKED](../../outputs/lending-agentic-local-20261023/promotion-gate.json) และไม่เชื่อมรุ่นทดลองนี้เข้ากับ reviewer endpoint

## สิ่งที่รันจริงและวิธีเทียบ

โมเดลทุกรอบใช้ `typhoon-v2.5-30b-a3b-instruct` ผ่าน Typhoon API จริง ใช้เอกสาร/ข้อมูลจำลองและ OCR ที่เก็บไว้จาก baseline ไม่มีการเรียก OCR ใหม่ในรอบนี้ และ onboarding/KYC เป็น mock ไม่ใช่การยืนยันตัวบุคคลจริง สูตรการเงิน นโยบายเครดิต และ oracle เดิมไม่ถูกเปลี่ยน

| ชุด | ผล | ขอบเขต |
|---|---|---|
| Baseline เดิม | PASS 9 / PARTIAL 3 / FAIL 6 | 18 เคส; deterministic routing + fixture OCR |
| Context-only | PASS 0 / FAIL 2 | เฉพาะ C04/C06; เพิ่ม context แต่คง legacy prompt/tools/controller/settings |
| V4 smoke | PASS 2 / PARTIAL 1 | C01/C04/C06; ทั้งสามผ่านเกณฑ์หลักฐานเพิ่ม แต่ C06 ไม่ผ่านคำถามใน oracle เดิม |
| **V4 final** | **PASS 8 / PARTIAL 1 / FAIL 9** | 18 เคสทั้งหมด รันใหม่จาก source ที่ตรึงไว้ ไม่หยิบเฉพาะผล smoke ที่ดี |
| เกณฑ์หลักฐานเพิ่ม | PASS 10 / FAIL 8 | ใช้ร่วมกับ oracle เดิม ไม่แทนที่; ผลรวมยัง 8 / 1 / 9 |
| เคสเสริมก่อนรัน | PASS 3 / FAIL 1 | H01–H04; ผู้พัฒนาสร้าง ไม่ใช่ชุดตรวจรับภายนอก |

[ตารางทุกเคส](../../outputs/lending-agentic-local-20261023/case-table.md) · [ข้อมูลเปรียบเทียบ](../../outputs/lending-agentic-local-20261023/comparison.json) · [หน้าดู tool trace](../../outputs/lending-agentic-local-20261023/comparison.html)

V4 final ใช้ 81 model calls, 645,544 tokens ตาม usage ที่ provider ส่งกลับ และเวลารวม 151.4 วินาทีใน runner; เคสเสริมใช้ 19 calls / 128,419 tokens รวมสองชุด 100 calls / 773,963 tokens ตัวเลขนี้ไม่รวมรอบพัฒนาและรอบล้มเหลวก่อนหน้า และไม่ใช่ใบแจ้งค่าบริการ

## ตอนนี้เป็น agentic อย่างไร

Runtime ใช้ **Typhoon Case Agent หนึ่งตัวต่อเคส** กับ orchestrator ที่เป็นโค้ด โมเดลเลือกชื่อเครื่องมือและ arguments จากสถานะ/หลักฐานที่เห็น รับผลจริงกลับเป็น native assistant/tool conversation แล้วเลือกขั้นต่อไป ไม่ใช่เพียงเขียนเหตุผลต่อท้าย pipeline เดิม

Sol, Luna และ AGY เป็นผู้ช่วยพัฒนา/ตรวจโค้ด ไม่ใช่ agent ที่ตัดสินสินเชื่อให้ลูกค้าใน runtime นี้

| เครื่องมือภายในส่วนทดลอง | หน้าที่และขอบเขต |
|---|---|
| `read_transactions` | อ่านรายการ/จำนวนเงิน/บัญชี/refs เฉพาะเคส |
| `match_transfers` | โค้ดตรวจสองขา วัน จำนวน เจ้าของและบัญชี; ไม่อาศัยยอดเท่ากันอย่างเดียว |
| `compare_declarations` | รับคำแจ้งพร้อม quote จากข้อความลูกค้า ตรวจ coverage และเทียบยอด/บัญชี; ไม่เพิ่มรายได้จากคำแจ้ง |
| `propose_findings` | โมเดลเสนอความหมายของรายการที่เป็น issue พร้อม quote/refs/คำถาม; ไม่ยืนยัน UNKNOWN เป็นรายรับ |
| `flag_transactions` | เปิดข้อสงสัยใหม่จากแถวที่อ่านแล้วและพักรายรับที่เกี่ยวข้อง; ยังพบการใช้กว้างเกินเหตุใน C11/C12 |
| `inspect_cashflow` | โค้ดคำนวณรายเดือน หลังสำรองและค่างวดตามสูตรเดิม; ไม่ให้ LLM คิดเงินเอง |
| `finish_review` | ส่ง snapshot และข้อค้างให้คน ไม่มี tool อนุมัติหรือโอนเงิน |

โค้ดคุม schema, refs, quote, case version, consent, idempotent replay และการรวมประเด็นก่อนส่งต่อ จำกัดไม่เกิน 8 model calls / 240 วินาทีต่อเคส โดย HTTP timeout ไม่เกินเวลาที่เหลือและ 45 วินาที ปฏิเสธผลที่มาช้า; การหยุดเครือข่ายระดับ OS ไม่ได้พิสูจน์ว่า preempt ได้ทันที

หลัง audit คำแจ้งและตรวจ source issue ที่จำเป็นแล้วจึงเปิดคำนวณ เมื่อกระแสเงินสดเป็นปัจจุบันและไม่มีงานบังคับค้าง จะเปิดเฉพาะ `finish_review` คำถามที่ยังตอบไม่ได้ยังอยู่ใน packet ไม่ถือว่าปิดประเด็น การแก้ malformed native response อนุญาตเพียงหนึ่งครั้งในงบแปดครั้งเดิม ไม่มีการเดา tool/arguments หรือ parse prose มา execute แทนโมเดล

## แก้อะไรได้ และยังผิดที่ไหน

| เคส | หลักฐานจากรอบสุดท้าย | ข้อสรุป |
|---|---|---|
| C04 โอนวนมีคำว่า sales | โมเดลเรียกจับคู่ 24 refs ได้ 12 คู่; R คง 200,000 ต่อเดือน ไม่ใช่ 280,000 | ผ่าน; ความถูกต้องของคู่โอนมาจากโค้ดและหลักฐานสองขา |
| C06 ขายอุปกรณ์ 900,000 | โมเดลเสนอ `ASSET_SALE` อ้าง `sales of old equipment`; พักจาก R และขอหลักฐาน | การตีความและ gate ถูก; oracle เดิมให้ PARTIAL เพราะคำถามไม่ตรงเงื่อนไขคำที่กำหนดไว้ จึงไม่เลื่อนเป็น PASS เอง |
| C07 รายรับแกว่ง | แสดงเงินขาดมือเดือนพฤษภาคมและกรกฎาคม และส่ง EXCEPTION_REVIEW | ผ่าน; การคำนวณรายเดือนเป็นโค้ด ไม่ใช่ความสามารถคำนวณของ LLM |
| C01/C05/C08/C09/C14/C16 | จบ TECHNICAL_REVIEW หลัง native output ไม่ผ่าน validator เช่น prose ไม่มี tool, enum/fields/text length ผิด หรือ tool ไม่เปิดอยู่ | ไม่ได้กลายเป็นเครดิตไม่ดีหรืออนุมัติ แต่ workflow ยังไม่น่าเชื่อถือพอ |
| C03 โอนตนเอง | โมเดลส่ง refs เพียง 12 จาก issue 24 รายการ; ยังมีคู่ที่ตรวจไม่ครบ | handoff พร้อมข้อค้างปลอดภัยกว่าฝืนสรุป แต่ไม่ผ่านงานที่ควรตรวจครบได้ |
| C11 หลายบัญชี / C12 เงินสด | พบข้อมูลขาด แต่เปิด flag เพิ่มและพักยอดรายรับใน statement ที่ไม่ควรถูกตัดด้วยเหตุผลเรื่อง coverage อย่างเดียว | ต้องแยก “ที่มารายการไม่ชัด” จาก “บัญชี/เงินสดที่ยังขาด” ให้ชัดขึ้น |
| H01 ขายทรัพย์สินซ้ำทุกเดือน | กฎเริ่มต้นไม่เตือน; โมเดลอ่านแล้วไปคำนวณโดยไม่ flag | **พลาดความหมายและได้คำแนะนำผ่านใน sandbox — เป็นเหตุหลักที่ห้าม promote** |
| H02/H03/H04 | ไม่ยืนยันโอนภายนอกเป็นรายได้, เทียบยอดใหม่ 275,000/25,000 ได้, พบเงินเหลือ 8,000 ที่ไม่พอหลังสำรอง/ค่างวด | ผ่าน assertions ที่กำหนด แต่ไม่ได้พิสูจน์ว่าปราศจาก false positive ทุกชนิด |

C01 ผ่าน smoke แต่ไม่ผ่าน final ทั้งที่ใช้ source/model/settings เดียวกัน จึงยังอ้างความทำซ้ำได้จาก `temperature=0` ไม่ได้ ผลข้างต้นเป็นหนึ่งรอบต่อชุด ไม่มีช่วงความเชื่อมั่นหรือคำอ้างความแม่นยำสินเชื่อจริง

รีวิวอิสระยืนยัน P1 เรื่อง recurring income ที่ไม่มี source disposition ก่อนคำนวณยังค้างอยู่ และพบ P2 ในตัว evaluator ที่อาจสรุปจำนวน PASS จากรายงานที่ยังไม่ครบได้ รอบนี้ parent ตรวจจำนวน/ID/สถานะจบ/ไฟล์/manifest ครบ 18+4 แยกใน [acceptance envelope](../../outputs/lending-agentic-local-20261023/acceptance-envelope.json) จึงไม่ได้รับรองชุดย่อยเป็นชุดเต็ม แต่ข้อจำกัดของ runner/evaluator สำหรับรอบอนาคตยังไม่ถูกแก้ใน source ที่ตรึงไว้

V4 เป็น **การประเมินหลังปรับจากผลทดลองก่อนหน้า (post-tuning)** ไม่ใช่การทดลองที่ preregister design V4 ครบถ้วน: มี V1 pre-run pin และมี V4 source freeze ก่อนรัน แต่ design เพิ่ม protocol repair/handoff ภายหลัง V1 ส่วน assertions ของ evaluator ไม่เปลี่ยน และ held-out runner เปลี่ยนการ import module เท่านั้น เคส H01–H04 กำหนดไว้ก่อนเรียกโมเดลกับชุดนั้น แต่ไม่ใช่ชุด blind ภายนอก

## Pipeline หรือ LLM และ LangGraph ช่วยตรงไหน

**มีทั้งสองส่วน** ปัญหาเดิมคือ context ตัดหลักฐานออก, tool รับเพียง reason, keyword `sales` จัดหมวดผิด และ route ทำคำถามหลุด การให้โค้ดจัดการคู่โอน/กระแสเงินสด/issue แก้บางส่วนได้จริง แต่เมื่อมีข้อมูลและเครื่องมือครบขึ้น ยังพบการส่ง native response ไม่ถูกสัญญา, เลือกหลักฐานไม่ครบ, flag เกินเหตุ และพลาดธุรกรรมที่ไม่ใช่รายได้ประจำ จึงไม่ควรสรุปว่าเป็น pipeline อย่างเดียว หรือเปลี่ยนโมเดลอย่างเดียวแล้วจบ

การส่ง observation กลับด้วย matching native tool IDs เป็นรูปแบบที่ [Typhoon tool calling](https://docs.opentyphoon.ai/en/tool/) อธิบายไว้ แต่ผลทดลองจริงยังแสดงว่าต้องตรวจและจำกัดความผิดพลาดของ output ทุกครั้ง

รอบนี้ **ยังไม่เพิ่ม LangGraph** การเปลี่ยน framework ไม่ใช่หลักฐานว่าจะแก้ H01 หรือทำให้ tool arguments ถูกต้อง สิ่งที่ LangGraph ช่วยโดยตรงคือ checkpoint/state recovery และรอข้อมูลจากคนผ่าน [persistence](https://docs.langchain.com/oss/python/langgraph/persistence) / [interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) ซึ่งควรเพิ่มเมื่อทดลอง restart/resume งานหลาย worker ไม่ใช่ใช้แทน semantic validation

การแก้รอบถัดไปควรเป็นการเปลี่ยนบทบาทที่วัดได้: ให้โค้ดทำงานพื้นฐานที่จำเป็นและขยายคู่โอนให้ครบ; ใช้ LLM ที่เห็น context เฉพาะงานเพื่อตรวจความหมายของทุกกลุ่มเงินเข้า พร้อมผล review ที่ครบกลุ่มก่อนเปิดคำนวณ; แยก missing coverage ออกจากรายการที่ต้อง quarantine และให้ handoff เป็นข้อมูลมีชนิดชัดเจนโดยไม่พึ่ง freeform reason ที่ไม่ได้ใช้เป็นคำตัดสิน ต้องกำหนดชุดประเมินใหม่ที่ยังไม่ใช้ปรับระบบ และเปรียบเทียบโมเดลบน tools/input เดียวกันหากยังพลาด

## ความพร้อมสำหรับ AWS และแอป

ส่วนทดลองเป็น Python modules/CLI แยกจาก HTTP/Android contract จึงเตรียมห่อเป็น worker ได้ แต่ **ยังไม่ได้พิสูจน์ deployment, Linux container, durable restart, หลาย worker หรือ workflow เพิ่มวงเงินตามประวัติชำระ** ไม่มีการ deploy, เรียก AWS เพิ่ม, restart บริการ, เปลี่ยน DB หรือใช้ emulator ระหว่างงานนี้

เส้นทางที่เสนอใน [แผน AWS เดิม](REMEDIATION_TECHNIQUES_AWS_TH.md) ยังคงใช้ได้: Case API เป็นเจ้าของสถานะธุรกิจ, เอกสารเก็บเป็น private object, worker ใช้ Typhoon adapter เดิม; งานรอคนใช้ workflow ที่รองรับ callback เช่น [Step Functions Standard](https://docs.aws.amazon.com/step-functions/latest/dg/connect-to-resource.html) การเลือก compute/DB/ค่าใช้จ่ายจริงต้องตรวจแยกอีกครั้ง ไม่ถือว่างบหรือสิทธิ์ Bedrock ทำให้รุ่นทดลองนี้พร้อมใช้งาน

## หลักฐานและการรันซ้ำ

- [รายงาน final 18 เคส](../../outputs/lending-agentic-local-20261023/agentic-v4-final/report.json) และ [เกณฑ์เพิ่มเติม](../../outputs/lending-agentic-local-20261023/agentic-v4-final/additional-evaluation.json)
- [รายงานเคสเสริม](../../outputs/lending-agentic-local-20261023/heldout-v4-final/report.json)
- [Freeze V4 manifest](../../outputs/lending-agentic-local-20261023/source-v4-manifest.json) และ [ตรวจความคงเดิมหลังรัน](../../outputs/lending-agentic-local-20261023/final-verification.json): original 22 + V4 31 files, drift 0; input manifests ไม่เปลี่ยน
- [Full offline verification](../../outputs/lending-agentic-local-20261023/pytest-final-v4.xml): 273 passed; Ruff ผ่าน 8 ไฟล์ที่เกี่ยวข้อง ผล offline นี้ไม่ใช้แทนผลโมเดลจริง
- [Independent review](../../outputs/lending-agentic-local-20261023/review-luna-r3-final.md): อ่าน findings และขอบเขตแยกจากผล live ของ parent

```powershell
. .\scripts\project-env.ps1
$env:PYTHONDONTWRITEBYTECODE = '1'
# ต้องใช้ output ใหม่ทุกครั้ง; อ่าน credential จากไฟล์ที่ได้รับอนุญาต ไม่ใส่ key ในคำสั่ง
.\.venv\Scripts\python.exe -X utf8 tools/run_lending_agentic_experiment.py `
  --mode agentic --cases C04,C06 --output outputs/my-agentic-replay `
  --credential-file <authorized-env-file> --max-total-calls 16
```

เก็บรอบ V1 ที่ abort, V2/V3 ที่ไม่ผ่าน, V4 smoke และ V4 final ไว้แยกกันทั้งหมด ไม่แก้ผลเก่าให้เป็นผลรุ่นใหม่ ไม่แก้ oracle ตามคำตอบของโมเดล และไม่มี commit ในงานนี้
