# ความครอบคลุมการตรวจ statement และ synthetic probes เพิ่มเติม

> **อัปเดตหลังการทดลอง:** เอกสารด้านล่างเป็น coverage snapshot ก่อนรันชุดใหม่ ผลปัจจุบันของ S01–S05 และ C11/H01 อยู่ใน [ผลทดลองรายงาน 4 ส่วน](STATEMENT_FOUR_PART_RESULTS_TH.md): Typhoon 36 requests แล้ว Luna 34 requests; Luna S04 หยุดตาม budget ก่อนครบงาน ตารางประวัติด้านล่างยังคงผลเดิมไว้ ไม่ใช่คะแนนรอบล่าสุด

วันที่หลักฐาน 2026-10-23 — ขอบเขตนี้เป็นงาน fixture/test และอ่าน saved runs เท่านั้น ไม่มี API call, OCR ใหม่, การเข้าถึง PostgreSQL/ฐานข้อมูลใช้งานจริง, การอนุมัติ หรือการเปลี่ยนสูตร/นโยบาย Tests เดิมที่ใช้ SQLite ทำงานเฉพาะ temporary fixtures ใต้ outputs งาน live runner และงบเป็นของ parent agent

## แยกสิ่งที่ตรวจแล้วออกจากสิ่งที่ยังไม่ตรวจ

- **Offline/controller**: C01–C18 ใช้ผลเดิม `offline-final` ตาม oracle เดิม ส่วน S01–S05 ทดสอบการสร้างข้อมูล การ parse จริง ยอดและ refs พร้อม scripted tool observations ไม่มี model เลือก tools
- **Actual Typhoon**: C01–C18 ใน `agentic-v4-final` และ H01–H04 ใน `heldout-v4-final` มี saved provider attempts และ tool traces จริง แต่ OCR เป็น replay และ onboarding เป็น mock
- **Actual Luna**: เลือก 11 เคสที่เคย FAIL/PARTIAL รวม H01 ตาม run เดิม ผล **8 PASS / 2 PARTIAL / 1 FAIL**, 60 API calls, 385,356 tokens, estimated USD 0.053378915 คงคะแนนเดิม ไม่ใช่ whole-suite accuracy หรือ blind holdout
- **ณ เวลา freeze ของ coverage นี้ยังไม่รัน**: S01–S05 และ four-part report acceptance รอ parent รัน Typhoon ก่อนแล้วเลือกเคสไม่ผ่านไป Luna; งานนี้เสร็จเป็นผลรอบใหม่แล้วตามลิงก์อัปเดตด้านบน โดยคง expected ชุดเดิม

คำว่า PASS ในตารางเป็นคะแนน scenario oracle เดิม ไม่ใช่หลักฐานว่ารายงานรูปแบบใหม่ครบ 4 ส่วน หรือพิสูจน์ยอดขาย/ความแท้จริงได้แล้ว

## Matrix ของ fixtures เดิมและ provider traces

`—` = ไม่มีผลรัน provider นั้นใน slice ที่ตรวจ ไม่ใช่ PASS/FAIL และไม่อ้างถึงการรันในอดีตทุกเวอร์ชัน

| ID | ประเด็นเดิมที่ใช้ซ้ำ | Offline เดิม | Typhoon V4 จริง | Luna selected จริง |
|---|---|---|---|---|
| C01 | รายรับประจำ/คำนวณฐาน | PASS | FAIL | PASS |
| C02 | เงินเหลือไม่พอ | PASS | PASS | — |
| C03 | โอนตนเองสองขา | PASS | FAIL | PASS |
| C04 | คู่โอนมี memo sales | FAIL | PASS | — |
| C05 | เงินก้อนไม่ทราบที่มา | PARTIAL | FAIL | PARTIAL |
| C06 | ขายทรัพย์สินมี memo sales | FAIL | PARTIAL | PASS |
| C07 | volatility/เดือนขาดมือ | FAIL | PASS | — |
| C08 | เงินออกประจำไม่ทราบประเภท | PARTIAL | FAIL | PARTIAL |
| C09 | คำแจ้งยอดขาย/ต้นทุนไม่ตรง | FAIL | FAIL | PASS |
| C10 | ขาดทั้งเดือนกรกฎาคม | PASS | PASS | — |
| C11 | ส่งไม่ครบสองบัญชี | FAIL | FAIL | FAIL |
| C12 | เงินสดนอกบัญชียังไม่มีหลักฐาน | FAIL | FAIL | PASS |
| C13 | ไม่ทราบภาระหนี้ | PASS | PASS | — |
| C14 | ขาดเดือนร่วมกับเงินก้อนไม่ทราบที่มา | PARTIAL | FAIL | PASS |
| C15 | เอกสาร/รายการซ้ำ | PASS | PASS | — |
| C16 | ยอดปิดภายในไฟล์ไม่สมดุล | PASS | FAIL | PASS |
| C17 | ลูกค้าแจ้งหนี้ศูนย์ยังเป็น provisional | PASS | PASS | — |
| C18 | กำลังชำระได้เพียงวงเงินเล็ก | PASS | PASS | — |
| H01 | memo ขายอุปกรณ์ซ้ำ 6 เดือนหลบ detector | unit checks; ไม่มี whole-case offline score ใน slice นี้ | FAIL | PASS |
| H02 | เงินรับจากบัญชีที่ไม่เห็นอีกขา | unit checks; ไม่มี whole-case offline score ใน slice นี้ | PASS | — |
| H03 | คำแจ้งรูปแบบ comma ใหม่ | unit checks; ไม่มี whole-case offline score ใน slice นี้ | PASS | — |
| H04 | เงินเหลือบวกแต่หลัง reserve/ค่างวดขาดมือ | unit checks; ไม่มี whole-case offline score ใน slice นี้ | PASS | — |

ผลรวมเดิม offline C = 9 PASS / 3 PARTIAL / 6 FAIL; actual Typhoon C = 8 PASS / 1 PARTIAL / 9 FAIL; actual Typhoon H = 3 PASS / 1 FAIL ค่าทั้งหมดอ่านจาก saved report ไม่ rescoring

หลักฐานรายเคสและ SHA-256 ของ reports/events/cases อยู่ที่ [saved-run-coverage.json](../../outputs/statement-four-part-20261023/coverage/saved-run-coverage.json) โดยระบุ provider attempt count, accepted tools และ validator rejections แยกกัน ลำดับการรัน/model/token ของเก่าไม่ใช่ผลรันใหม่

ข้อสังเกต Luna เดิมคงตาม [review-luna.md](../../outputs/lending-openai-luna-20261023/review-luna.md): C11 ยัง FAIL; C05/C08 มี targeted questions แต่ keyword oracle เดิมให้ PARTIAL จึงไม่แก้คะแนน ส่วน C11 rejected payload เดิมเก็บ arguments ไม่ครบ ไม่สรุปสาเหตุของทั้งสาม rejections เกินหลักฐาน

## Matrix ของ 6 มิติที่ต้องมีในรายงาน

| มิติ | หลักฐานเดิมที่ใช้ซ้ำ | ช่องว่างที่เพิ่ม | สิ่งที่ยังไม่พิสูจน์ |
|---|---|---|---|
| เอกสาร/บัญชี/ช่วงเวลา/continuity | parser unit: owner mismatch; C10/C11/C15/C16 | S01 ชื่อเจ้าของช่วงหลังไม่ตรง, ขาดวันสุดท้าย, ยอดข้ามไฟล์ไม่ต่อ | ความแท้จริงเอกสาร, verification กับธนาคาร; tool ยังไม่มี cross-document continuity validator |
| ที่มาของเงินเข้า | C03–C06/C12, H01/H02 | S02 loan+owner capital ปน memo sales | ไม่มี matched POS/invoice/settlement contract; R และ memo ไม่พิสูจน์ยอดขาย |
| variability/trend ตาม window ของผลิตภัณฑ์ | C07, H03/H04 บางส่วน | S03 ลดต่อเนื่องและศูนย์ในเดือนสุดท้าย | ยังไม่ทดสอบ product window อื่น, ข้อมูลข้ามปี, seasonality หลายรอบ; demo นี้ใช้ 6 เดือนเดิม |
| เงินออก/ภาระหนี้/unknown | C08/C13/C17 | S05 ผู้รับไม่ระบุชื่อและมี labelled repayment ที่ระบุได้บางส่วน | ไม่ทราบภาระหนี้ทั้งหมด/นอกบัญชี; ห้ามถือเงินออกประจำทั้งหมดเป็นหนี้ |
| เงินเหลือและสภาพคล่องรายเดือน | C02/C07/C18, H04 | S03 เดือนศูนย์, S04 เงินเข้าออกเร็ว, S05 net ติดลบแต่ debt unknown | ไม่ใช่กำไรบัญชีหรือความสามารถชำระสุดท้าย; ห้ามแทน unknown ด้วยศูนย์/หักซ้ำ |
| pattern ชวนถามอย่างเป็นกลาง | C04/C05/C08 และ guard tests | S04 เงินเข้าปลายงวดแล้วออกเกือบหมดวันถัดมา | ไม่พิสูจน์ความสัมพันธ์ของคู่รายการ วัตถุประสงค์ หรือ fraud; ห้าม reject อัตโนมัติ |

## สัญญา fixture ใหม่

เรียก `tools.statement_report_fixtures.build_cases()` ได้ dict ที่มี keys S01–S05 แต่ละค่าเป็น `{case, documents, corroboration, expected}` เท่านั้น ใช้รูป case/onboarding เดียวกับ heldout H01 และ reuse `MockBank`/`make_document` แบบไม่เรียกฐานข้อมูล/เครือข่าย

- ส่ง **เฉพาะ `case`, `documents`** เข้า `ReviewSession` และส่ง corroboration ให้ report builder เมื่อมี schema ที่ตกลงแล้วเท่านั้น
- `expected` เป็น evaluation-only literal จาก [statement_review_additional_v1.json](../../examples/merchant_sandbox/statement_review_additional_v1.json) ไม่ได้คำนวณจาก parser/model และห้ามใส่ใน model context, prompt หรือ tool response
- `corroboration=None` ทุกเคส เนื่องจาก report owner ยังไม่ส่ง versioned schema; ทุกเคสมี `confirmed_total_thb=null`, `receipts=[]` ใน supported sales ส่วน candidate totals คือ synthetic oracle/statement memos ที่ต้องตรวจต่อ ไม่มี positive proof-of-sales case ในชุดนี้ การเพิ่ม positive corroboration ต้องประสาน schema ก่อน
- เอกสารเป็น **synthetic normalized OCR text** ใช้ parser จริง SHA-256 ระบุ basis `UTF8_OCR_TEXT_NOT_SOURCE_PDF` ไม่ใช่ hash ของ PDF ที่อ้างว่าได้รับจากธนาคาร ไม่มี OCR/provider call ใหม่หรือ PDF เขียนทับของเก่า
- ทุกแถว reconcile ภายในเอกสาร ยอดเปิด 1,000,000 บาท ห้ามสร้างแถว debit=credit=0; เดือนรายได้ศูนย์ยังมี debits และ period header ครบ
- bank net คิดจาก credits−debits ที่เห็น ส่วน provisional residual ใช้สูตรเดิมกับ synthetic sale candidates และค่าที่ลูกค้าแจ้ง ไม่เปลี่ยนสูตร/threshold และไม่เรียกผลนั้นว่ายอดขายพิสูจน์แล้ว

## Case specs ใหม่ ไม่เกิน 5 เคส

| ID | ตัวเลขที่ตรวจด้วยมือ | สิ่งที่รายงานต้องแสดง/ถาม | Typhoon/Luna |
|---|---|---|---|
| S01 | 2 ไฟล์ ไฟล์ละ 9 แถว: เปิด 1,000,000 + รับ 600,000 − จ่าย 435,000 = ปิด 1,165,000; ไฟล์ถัดไปกลับเปิด 1,000,000 ต่าง −165,000 | ขอความสัมพันธ์ชื่อ Other Person, ขอถึง 30 ก.ย. แทน 29 ก.ย., ขอ reconcile ข้ามงวดทั้ง 3 ประเด็น ห้ามใช้สมดุลในไฟล์เป็น proof of authenticity | NOT RUN / NOT RUN |
| S02 | 20 แถว: รับ 1,380,000 จ่าย 870,000 ปิด 1,510,000; candidate sales 1,200,000; เงินกู้ 100,000 + ทุน 80,000 = 180,000 | แยกสองรายการออกจาก sales; ขอทุนต้นทาง/สัญญาและตารางผ่อนเงินกู้; ไม่อนุมานค่างวดจากเงินต้น | NOT RUN / NOT RUN |
| S03 | 17 แถว: รับ 900,000 จ่าย 870,000 ปิด 1,030,000; candidates [240k,210k,180k,150k,120k,0]; mean 150k, first3 210k, last3 90k | แสดง trend ลดลงและ Sep=0; residual เดิม [70k,40k,10k,−20k,−50k,−170k] พร้อมเดือนขาดมือ Jul/Aug/Sep; Sep ไม่ใช่เดือน statement ขาด | NOT RUN / NOT RUN |
| S04 | 20 แถว: รับ 2,100,000 จ่าย 1,760,000 ปิด 1,340,000; 29 ก.ย. รับ 900,000 → 30 ก.ย. จ่าย 890,000 เหลือส่วนต่าง 10,000 | อ้างสอง refs และถามที่มา/การใช้/เกี่ยวข้องกันหรือไม่; purpose/relationship unknown; ยังจัดเป็น non-sales ชนิดแน่นอนไม่ได้ และไม่ใช่ liquidity คงเหลือ 900k | NOT RUN / NOT RUN |
| S05 | 36 แถว: รับ 1,200,000 จ่าย 1,212,000 ปิด 988,000; net −2,000 ทุกเดือน; anonymous 47k/เดือนรวม282k; repayment 10k/เดือนรวม60k | แยก labelled repayment ที่เห็นจาก total debt unknown; ขอผู้รับและ purpose 35k/12k ว่าเป็นวัตถุดิบ/ส่วนตัว/อื่นและซ้ำกับต้นทุนเดิมหรือไม่; residual สุดท้ายยัง unknown | NOT RUN / NOT RUN |

ตัวอย่าง refs ที่กำหนดไว้ล่วงหน้า:

- S01 cross-file: `DOC-S01-A:page-1:table-1:row-10` กับ `DOC-S01-B:page-1:table-1:row-2`
- S02 loan `DOC-S02-A:page-1:table-1:row-3`, capital `DOC-S02-A:page-1:table-1:row-7`
- S04 inbound `DOC-S04-A:page-1:table-1:row-20`, outbound `DOC-S04-A:page-1:table-1:row-21`
- S05 anonymous Apr rows5/6; repayments rows7/13/19/25/31/37 ของ `DOC-S05-A`

Expected ของทุกเคสมีครบ 4 ส่วน: supported sales receipts, non-sales inflows, identifiable payment obligations, unresolved items/questions แต่ส่วนที่ไม่มีหลักฐานให้คง empty/unknown อย่างมีเหตุผล ไม่เติมรายการเพื่อให้ดูครบ และ observed payment ไม่เท่ากับ contract/debt completeness verification

## Expected failure ที่ต้องคงไว้

S01 diagnostic ablation แก้เฉพาะชื่อเจ้าของและวันสิ้นงวดให้ถูก โดยคงยอดเปิดข้ามไฟล์ที่ต่าง 165,000 บาท ผล parser/controller เดิมเป็น `OK` และไม่มี issue ทั้งที่ expectation คือ `NEEDS_REVIEW` รายละเอียดอยู่ใน [continuity-only-diagnostic.json](../../outputs/statement-four-part-20261023/coverage/S01/continuity-only-diagnostic.json)

Test `test_s01_continuity_alone_must_require_review_even_if_each_file_balances` เก็บ expectation นี้เป็น **strict xfail** เพื่อไม่ให้ owner/period issue ที่ตรวจพบแล้วกลบ validator ที่ขาด ไม่แก้ oracle/เครื่องมือเดิมเพื่อทำคะแนนผ่าน ชุด S01 จริงยังมีทั้งสามประเด็นครบ การที่ model อาจยกคำถามจาก transaction balances ได้ต้องพิสูจน์ใน live trace เพิ่ม ไม่ถือว่ามี validator แล้ว

## หลักฐาน offline และขอบเขตการทดสอบ

- [pytest-red-contract.txt](../../outputs/statement-four-part-20261023/coverage/pytest-red-contract.txt): ก่อนสร้าง builder, contract test fail เพราะ builder ไม่มี; arithmetic dependent tests ถูก skip ชั่วคราว
- [pytest-green.txt](../../outputs/statement-four-part-20261023/coverage/pytest-green.txt): 11 tests แรกผ่านหลังสร้าง fixtures
- [pytest-related-final.txt](../../outputs/statement-four-part-20261023/coverage/pytest-related-final.txt): ผลสุดท้ายของ tests ใหม่ร่วมกับ `test_local_agentic_review`, `test_agentic_evidence_scope`, `test_lending_documents` — 106 PASS / 1 XFAIL ที่ระบุไว้ข้างบน
- [new-case-offline-evidence.json](../../outputs/statement-four-part-20261023/coverage/new-case-offline-evidence.json): initial issue codes, observed bank net, cashflow status, 7-tool allowlist, model/OCR calls = 0
- แต่ละ `coverage/S0x/` มี input-case, replayed-documents, normalized-rows, initial-context, offline-tool-trace, offline-cashflow และ expected-evaluation-only แยกไฟล์กัน `offline-tool-trace` เป็น scripted `read_transactions → compare_declarations → inspect_cashflow` ไม่ใช่ model plan/complete report
- [protected-after.json](../../outputs/statement-four-part-20261023/coverage/protected-after.json): frozen V4 ทั้ง 31 ไฟล์ และ old fixture/oracle/evaluator/report ที่เก็บไว้ก่อนเริ่ม ไม่มี drift

ไม่รัน full repository suite เพราะงานนี้กำหนดให้ bounded/offline และ parent คุม testing budget; tests บางส่วนของ repo เปิด HTTP listener จึงไม่ได้ถือว่าถูกตรวจในงานนี้ ไม่มีผล device/live server/OCR ใหม่, external bank verification, หรือ production policy validation

## Handoff ให้ runner/report owner

ให้ parent freeze new spec/builder/tests ก่อนเรียก provider; ใช้ 7 tools เดิมและ budgets ที่ parent กำหนด เก็บ initial-context, accepted/rejected tool arguments ที่ scrub แล้ว, events, provider usage, report และ expected แยกกัน ประเมินทั้ง 4 ส่วน/6 มิติจาก literal oracle โดยไม่ส่ง oracle ให้ model รัน Typhoon ทั้ง 5 ก่อน และส่งไป Luna เฉพาะ failures/partials ตามเกณฑ์ที่ประกาศ ไม่สรุป model uplift จาก selection นี้

ช่องว่างที่ต้องประสานคือ versioned corroboration schema และ positive matched-sales evidence fixture นอกเหนือจากนั้นยังไม่มีการทดสอบ OCR recognition ใหม่, owner/account verification กับธนาคาร, multi-product window, ต้นทุน/ภาระนอกบัญชี และ report postprocessing ใหม่ ครบ fixture tests ไม่ได้แปลว่า four-part report ผ่านแล้ว
