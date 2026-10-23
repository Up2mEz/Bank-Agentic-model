# ผลทดลองรายงาน Statement 4 ส่วน — 23 ตุลาคม 2026

ทำรายงาน 4 ส่วนและทดลอง Typhoon ก่อน แล้วจึงเริ่มทดสอบ Luna ทั้ง 7 เคสที่ Typhoon ยังไม่ผ่านเกณฑ์รวม โดย **Luna S04 หยุดตาม budget ก่อนทำงานครบ** ผลนี้ยังไม่ใช่ระบบสินเชื่อที่ผ่าน acceptance ทั้งชุด และไม่ได้พิสูจน์ว่าเปลี่ยนโมเดลแล้วปัญหาทั้งหมดหาย

[เปิดตัวดูรายงานและ trace แบบเลือกเคส](../../outputs/statement-four-part-20261023/results.html) — แสดงคำถามต้นฉบับจาก packet เพิ่มเติม โดยไม่เปลี่ยนไฟล์ผลทดลองหรือคะแนนเดิม

รายงานเป็น module/CLI ใน local: `statement_report.py` ไม่ได้ reload เว็บเจ้าหน้าที่/Android หรือบริการเดโมที่ผู้ใช้กำลังใช้งาน ไม่มีคำตัดสินสินเชื่อจากการทดลอง (`decision=null` ทั้ง 14 ผล) และไม่มีการเรียก OCR ใหม่ ข้อมูล S01–S05 เป็น synthetic normalized OCR; C11/H01 อ่าน input และ OCR replay เดิม

## รายงานที่ได้

มี 4 ส่วน: **เงินรับที่มีหลักฐานว่าเป็นยอดขาย / เงินเข้าที่ไม่ใช่ยอดขาย / ภาระจ่ายที่ระบุได้ / รายการที่ต้องถามเพิ่ม** พร้อม refs, จำนวนเงิน, ระดับหลักฐาน, ข้อจำกัด และข้อมูลรายเดือน

ส่วนยอดขายต้องมี application-owned corroboration ที่ผูกกับรายการและจำนวนตรงกัน ไม่ใช้คำว่า sales, category R หรือความมั่นใจของโมเดลเป็นหลักฐานยืนยัน ดังนั้น S01–S05 ที่ไม่มี corroboration มี supported sales เป็นศูนย์ ซึ่ง **ไม่ได้พิสูจน์ว่ารายได้จริงเป็นศูนย์** มี [ตัวอย่าง offline ที่ครบทั้ง 4 ส่วน](../../outputs/statement-four-part-20261023/report-module/sample-report.md) ด้วยหลักฐานประกอบจำลองที่ระบุชัดเจน

โค้ดตรวจความต่อเนื่องข้ามไฟล์และช่วงวันที่จริงเพิ่มในรายงานแล้ว แต่ controller เดิมยังไม่มีกฎ cross-document continuity; strict XFAIL ที่แสดงช่องว่างนั้นยังคงอยู่ ไม่ได้เปลี่ยนสูตรหรือ policy เดิม

รายงานเงินออกไม่บังคับว่าทุกยอดคือวัตถุดิบ/ส่วนตัว/หนี้ ยอดสุทธิในบัญชีแยกจากเงินเหลือผ่อน ภาระหนี้ทั้งหมดและความแท้จริงของเอกสารยัง UNKNOWN/UNVERIFIED เมื่อหลักฐานไม่พอ

## ผลตามเกณฑ์ที่ตรึงไว้ก่อนรัน

| เคส | Typhoon | Luna | สิ่งที่ตรวจพบจาก trace |
|---|---|---|---|
| S01 เจ้าของ/ช่วงงวด/ยอดข้ามไฟล์ | FAIL | FAIL | Typhoon ถามชื่อบัญชี แต่ไม่ยกยอดข้ามไฟล์ร่วมกัน; Luna ยกยอดต่าง 165,000 และสอง refs ได้ ข้อถามความสัมพันธ์เจ้าของ/วันสิ้นงวดยังอาศัยประเด็นทั่วไปจาก controller |
| S02 เงินกู้/ทุนปน sales | FAIL, technical stop | FAIL | Typhoon ตอบข้อความแทน tool สองครั้ง; Luna กันทุน 80,000 ออกจาก R และถามเงินกู้ 100,000 ได้ ข้อรวมภาระกู้ใหม่นี้ในหนี้เดิมที่แจ้งยังไม่ชัด และรายงานเก็บ memo sales+capital เป็น UNKNOWN แทน CAPITAL ตาม literal oracle |
| S03 รายได้ลดจนเดือนศูนย์ | FAIL | FAIL | Typhoon คำนวณทั้ง 6 เดือนได้ แต่ไม่ได้ตั้งคำถามเรื่องแนวโน้ม/เดือนศูนย์เอง; Luna ตั้งคำถามได้แต่เลือก flag รายรับ ส.ค. ทำให้ tool กันยอด 120,000 ออกจาก R จน cashflow เปลี่ยน |
| S04 รับเงินแล้วออกเร็ว | FAIL ตามเกณฑ์รวม | FAIL, budget stop | Typhoon ตั้งคำถามเชื่อมสองรายการพร้อม refs และคง UNKNOWN ได้จริง; สำนวนต่างจาก expected และรายงานย่อคำถามเฉพาะกลับเป็นข้อความทั่วไป ส่วน Luna เรียกจริง 3 requests แล้วหยุดก่อนคำขอถัดไป จึงยังวัดงานครบเคสไม่ได้ |
| S05 รายจ่ายไม่ชัด/หนี้ไม่ครบ | FAIL | FAIL | ทั้งคู่ไม่ฟันธงรายจ่ายนิรนามเป็นหนี้; ยังขาดคำถามเฉพาะที่เชื่อมยอดผ่อนที่เห็นกับภาระหนี้ทั้งหมด และเกณฑ์ refs/สำนวนบางข้อเข้มเกินรูปแบบ tool ที่อนุญาต; Luna ถูก regex ปฏิเสธข้อความปฏิเสธการอนุมัติหนึ่งครั้ง |
| C11 บัญชีที่ยังไม่ส่ง | FAIL | PASS | Luna แยกหนึ่งบัญชีต่อ claim จึงสร้าง MISSING_ACCOUNT และขอ statement OWN-B ได้ แต่ยังมี DECLARATION_UNPARSED ที่ส่งให้คนตรวจ ไม่ได้แปลว่าคำแจ้งทั้งหมดตรวจครบแล้ว |
| H01 ขายอุปกรณ์เก่าซ้ำทุกเดือน | FAIL, technical stop | PASS | Luna อ่านแล้ว flag รายรับทั้ง 6 รายการ ไม่ใช้เป็นรายได้ประจำ ส่งให้คนพร้อมคำถาม; Typhoon มี schema error และไม่ได้กันรายรับเหล่านี้ก่อนคำนวณ |

**คะแนนดิบ: Typhoon 0 PASS / 7 FAIL; Luna 2 PASS / 5 FAIL** เป็นคะแนนรวมของ controller, โมเดล, รายงาน และ evaluator บนชุดที่เลือก ไม่ใช่ความแม่นยำของโมเดลบนผู้ขอสินเชื่อจริง และไม่ใช่ผลรันครบ 18+4 เคสเดิม

Evaluator ตรวจยอด/จำนวนแถว/refs/decision ด้วยเงื่อนไขโครงสร้าง แต่การรับรองความหมายคำถามใช้ประโยคตัวอย่างที่ตรวจไว้แบบตรงกัน คำถามสำนวนอื่นจึงมี `NEEDS_HUMAN_SEMANTIC_REVIEW` แม้เนื้อหาจะสมเหตุสมผล รายงานนี้ **ไม่ตีความทุก FAIL เป็นโมเดลคิดผิด** และไม่เปลี่ยนคะแนนเดิมย้อนหลัง

## Trace ที่อธิบายสาเหตุได้

### 1. C11: ตัวเลือก tool กับโครงสร้าง claim

Typhoon call 1 ส่ง `compare_declarations({claims: []})` ทั้งที่มีข้อความสองบัญชี ต่อมาขอข้อมูล OWN-B ด้วย flag ของรายการในบัญชีที่มีเอกสาร แต่ไม่เกิด MISSING_ACCOUNT ตาม contract

Luna call 1 ส่ง business_account สอง claims แยก value `ACC-1` และ `OWN-B` พร้อม quote จากข้อความ จากนั้น controller สร้างคำขอ statement OWN-B ครบช่วง และจบ WAIT_CUSTOMER

[Typhoon trace](../../outputs/statement-four-part-20261023/typhoon-01/C11/public-trace.json) · [Luna trace](../../outputs/statement-four-part-20261023/luna-01/C11/public-trace.json)

### 2. S03: tool สำหรับ “ถามเพิ่ม” มีผลต่อการคำนวณด้วย

Luna call 3 ใช้ `flag_transactions` กับรายการรับ ส.ค. row-14 และค่าใช้จ่าย ก.ย. rows17/18 เพื่อถามว่าทำไม ก.ย. ไม่มีเงินเข้า แต่ tool นี้ไม่ได้เพียงเพิ่มคำถาม: มันกักยอดที่เป็น R ออกจากรายได้ด้วย ผล provisional residual ก่อนสำรองเดือน ส.ค. เปลี่ยนจาก **−50,000 เป็น −170,000 บาท** เพราะตัดเครดิต 120,000 ออก ไม่ใช่การบวกลบผิดของ calculator

นี่คือปัญหาขอบเขต tool และการเลือก refs ร่วมกัน ควรแยก `request_evidence` ที่ไม่เปลี่ยน ledger ออกจาก `quarantine_income` ซึ่งต้องมีเหตุผล/หลักฐานเฉพาะ ยังไม่ได้แก้ controller เดิมในรอบนี้

[Luna S03 trace](../../outputs/statement-four-part-20261023/luna-01/S03/public-trace.json) · [cashflow จริง](../../outputs/statement-four-part-20261023/luna-01/S03/case.json)

### 3. S05: ยืนยัน false positive ของ regex ได้แล้ว

Luna call 5 ส่ง reason ที่ลงท้าย **“โดยไม่อนุมัติสินเชื่อ”** แต่ guard ตรวจ substring `อนุมัติสินเชื่อ` จึงปฏิเสธด้วย `use neutral evidence questions, not accusations or an approval` โมเดลปรับข้อความและ call 6 ส่งต่อสำเร็จ

คำขอที่ถูกปฏิเสธนี้ใช้ **10,911 tokens** ซึ่งรวมอยู่ในยอดค่าใช้จ่ายแล้ว รอบนี้มี arguments ของคำขอที่ controller ปฏิเสธเก็บไว้ จึงยืนยันกลไกได้ ต่างจากข้อสงสัยในผลเก่าที่ไม่มี arguments ครบ

[หลักฐาน call 5–6](../../outputs/statement-four-part-20261023/luna-01/S05/public-trace.json)

### 4. S02/H01 ของ Typhoon: เป็น native protocol error ที่ระบุชนิดได้

- S02 calls3/4: `finish_reason=stop`, `content_kind=text`, `tool_count=0` ทั้งสองครั้ง จึงไม่มี tool ให้ execute
- H01 call1: `compare_declarations` ผิด object fields; call5: `finish_review` ผิดข้อจำกัดความยาวข้อความ มี native tool แต่ไม่ผ่าน schema
- ไม่เก็บ response body ของคำตอบผิด schema เหล่านี้ จึงทราบชนิดความผิดจาก metadata แต่ไม่อ้างว่าเห็นค่าฟิลด์ที่ไม่ถูกเก็บ

[S02 provider receipts](../../outputs/statement-four-part-20261023/typhoon-01/S02/provider-calls.json) · [H01 provider receipts](../../outputs/statement-four-part-20261023/typhoon-01/H01/provider-calls.json)

### 5. S04: Agent ถามได้ แต่รายงานและ evaluator ยังทำข้อมูลสูญหาย/ประเมินแคบ

Typhoon call 3 อ้างอิง row20 และ row21 ร่วมกัน ถามว่าเงินรับ 900,000 และเงินจ่าย 890,000 ในวันถัดไปเกี่ยวข้องกันหรือไม่ พร้อมขอที่มา/วัตถุประสงค์ ไม่สรุปว่าเป็นการโอนตนเองหรือทุจริต

คำถามจริงยังอยู่ใน `case.packet.issues` และ `staff-report.json.existing_issues` แต่ renderer แทนคำถามในส่วน follow_up ด้วยข้อความทั่วไปว่าให้ตรวจประเด็นเดิม ทำให้ Markdown ไม่แสดงคำถามเฉพาะอย่างครบถ้วน ต้องเปิด trace/คำถามต้นฉบับประกอบ และควรแก้การส่งต่อคำถามใน renderer ก่อนต่อเข้าหน้าเจ้าหน้าที่

[Typhoon S04 trace](../../outputs/statement-four-part-20261023/typhoon-01/S04/public-trace.json) · [รายงาน JSON](../../outputs/statement-four-part-20261023/typhoon-01/S04/staff-report.json)

Luna S04 หยุดด้วย `openai_budget_exhausted` ก่อน HTTP ครั้งที่4 เนื่องจากการสำรอง input tokens จะเกิน cap 240,000 ทั้ง batch การที่ไฟล์สรุปมี `run_status=COMPLETED` หมายถึง loop รันครบรายการ ไม่ได้หมายความทุกเคส finish review สำเร็จ ต้องดู case state/trace ด้วย

## Token และค่าใช้จ่ายจริงที่บันทึกได้

หนึ่ง task ในตารางคือ **หนึ่งเคสตลอดหลายคำขอ** หนึ่ง request คือหนึ่ง HTTP ไปยัง provider ไม่รวม token ของผู้ช่วยเขียนโค้ดหรือ subagent reviewer และไม่มี OCR calls ในรอบนี้

| เคส | Typhoon calls / tokens | Luna calls / tokens | Luna USD ประมาณ |
|---|---:|---:|---:|
| S01 | 5 / 40,476 | 5 / 28,510 | 0.004070600 |
| S02 | 4 / 22,717 | 6 / 39,822 | 0.005684700 |
| S03 | 5 / 29,675 | 5 / 26,711 | 0.003924100 |
| S04 | 6 / 42,328 | 3 / 18,232 — ไม่ครบงาน | 0.002796800 |
| S05 | 6 / 59,202 | 6 / 59,053 | 0.008350550 |
| C11 | 5 / 46,604 | 4 / 25,558 | 0.003689000 |
| H01 | 5 / 28,837 | 5 / 26,626 | 0.003848600 |
| รวม | **36 / 269,839** | **34 / 224,512** | **0.032364350** |

Typhoon input 264,368 / output 5,471; Luna input 212,756 / output 11,756 โดย reasoning 4,961 เป็นส่วนหนึ่งของ output และ cache-write 208,430 เป็นส่วนหนึ่งของ input ไม่บวกซ้ำ ไม่พบ cached read ใน Luna รอบนี้

เฉลี่ยต่อ task ที่เริ่มทดลอง: Typhoon 38,548.43 / Luna 32,073.14 tokens; เฉลี่ยต่อ HTTP: 7,495.53 / 6,603.29 tokens ตัวเลขเฉลี่ย Luna รวม S04 ที่หยุดก่อนครบ จึงไม่ใช้เป็นหลักฐานว่าประหยัดกว่าเมื่อทำงานเท่ากัน Context/API/history และ tokenizer ก็ต่างกัน

ประมาณค่าใช้จ่าย Luna ตรวจซ้ำจาก input/cache-write/output ทุก receipt แล้วตรงกัน 34/34: input $0.10/M, cache-write $0.125/M, cached input $0.01/M, output $0.50/M ตามฐานราคาที่ใช้ในการทดลอง ไม่ใช่ใบแจ้งหนี้หรือยอดเงินในบัญชี และไม่ได้ประเมินราคา Typhoon รอบนี้

รวมกับ Luna รอบก่อน $0.053378915 เป็น **$0.085743265** สำหรับสองรอบที่บันทึกไว้ (94 API calls / 609,868 tokens) ไม่ใช่ usage ทั้งบัญชี

[Typhoon ทุก request CSV](../../outputs/statement-four-part-20261023/typhoon-01/per-request-usage.csv) · [Luna ทุก request CSV](../../outputs/statement-four-part-20261023/luna-01/per-request-usage.csv) · [รายเคส CSV](../../outputs/statement-four-part-20261023/per-case-usage.csv) · [ตรวจยอดอิสระ](../../outputs/statement-four-part-20261023/analysis.json)

## สิ่งที่ควรแก้จากหลักฐานรอบนี้

1. ส่งคำถามต้นฉบับที่มี refs เข้ารายงานเจ้าหน้าที่ โดยแสดงว่าเป็นข้อเสนอ/คำถามที่ยังไม่ยืนยัน แทนการทำให้เหลือข้อความทั่วไป
2. แยกการขอหลักฐานออกจากการกักรายรับ; เปิด case/document-level follow-up ที่ไม่ต้องใช้ transaction refs ผิดความหมาย
3. ให้ Orchestrator มี checklist ของหกมิติและเกณฑ์ครบก่อนส่งต่อ รวม question coverage ไม่ใช่เพียง tool เรียกครบ พร้อมหยุดตาม budget และส่งคำถามค้าง
4. ใช้ structured decision/handoff boundary แทน substring regex ที่ไม่เข้าใจคำปฏิเสธ และทดสอบประโยคปฏิเสธอย่าง “ไม่อนุมัติ” แยกจากการประกาศอนุมัติ
5. ประเมิน refs/หัวข้อ/หลักฐานที่ต้องขอและความหมายแยกจากประโยคตรงตัว รองรับคำถามแยกหลายข้อ/จำนวน quotes ที่ tool ยอมรับ พร้อมคง manual semantic review สำหรับประเด็นคลุมเครือ
6. ลด context ซ้ำ โดยคงเอกสารครั้งแรกและส่งเฉพาะ observations/state ที่จำเป็น พร้อมบันทึก input/output ต่อคำขอ LangGraph มี [checkpoint/persistence](https://docs.langchain.com/oss/python/langgraph/persistence) และ [interrupt เพื่อหยุดรอคน](https://docs.langchain.com/oss/python/langgraph/interrupts) แต่จาก trace รอบนี้ การนำ framework มาใช้เพียงอย่างเดียวยังไม่แก้ tool side effects หรือสร้างความหมายธุรกรรมที่ statement ไม่มี

ยังไม่ฝึกโมเดลแยกวัตถุดิบ/ส่วนตัว และยังไม่จำเป็นต้องทำก่อนแก้ข้อข้างต้น หลักฐานใน statement ไม่พอให้ยืนยันวัตถุประสงค์จริงทุกยอด; ใช้ UNKNOWN และขอ POS/ใบเสร็จ/สัญญาหรือข้อมูลบัญชีอื่นตามประเด็น

## ผลตรวจอิสระและประเด็นที่ยังเปิดอยู่

Luna reviewer ตรวจ source/fixtures/receipts แบบอ่านอย่างเดียว พบ **P2 สองข้อและ P3 แบบมีเงื่อนไขหนึ่งข้อ**; reviewer ไม่ได้อ่านผล live batch จึงไม่ใช้รายงานนั้นรับรองพฤติกรรมโมเดล คะแนน หรือ usage รอบนี้

| ประเด็นจาก review | สิ่งที่ parent ตรวจหลังรัน | สถานะโค้ด |
|---|---|---|
| P2: Luna selector ยังไม่บังคับให้ Typhoon batch จบ/มีผลครบก่อนเลือก | ผลที่บันทึกมี Typhoon ทั้ง 7 เคส และ Luna เริ่มครบทั้ง 7 เคสที่ไม่ผ่าน ไม่มีเคสตกหล่นในผลสุดท้าย; final artifact เพียงอย่างเดียวไม่ได้ยืนยันลำดับเวลา launch | ยังเปิด ต้องเพิ่ม completion/coverage gate ก่อนรอบถัดไป |
| P2: Typhoon adapter ยังไม่บังคับ total = prompt + completion ก่อนใช้ token cap | ตรวจ receipts จริงทั้ง 36 คำขอแล้วผลบวกตรงกันทั้งหมด; Luna 34 คำขอตรงกันด้วย ไม่มี usage ขาดในรอบนี้ | ยังเปิด ต้องหยุดเมื่อ usage ขาด/ไม่สอดคล้อง |
| P3: evaluator อาจใช้ tool event เดียวรับรองหลาย identical replay actions | ไม่พบ accepted tool+arguments ซ้ำหรือ replay marker ใน contexts ของ 14 ผลรอบนี้ | ยังเปิดแบบมีเงื่อนไข ต้องผูก receipt ต่อ action occurrence |

ไม่แก้ source ที่ตรึงไว้หรือ rescoring ผลเดิมหลังเห็นคำตอบ รายการเหล่านี้ยังเป็นข้อจำกัดสำหรับการใช้ runner รอบถัดไป ข้อมูลเริ่มต้น/เอกสาร/initial context/expected ของสอง provider ตรงกัน 7/7; source และ snapshot ทั้งสองรอบไม่มี hash drift

[Independent review](../../outputs/statement-four-part-20261023/review-luna.md) · [ตรวจผลกระทบจาก saved live artifacts](../../outputs/statement-four-part-20261023/postrun-audit.json)

## ขอบเขตการยืนยัน

Full Python suite **501 PASS / 1 known strict XFAIL**; Ruff ของไฟล์ใหม่ 10 ไฟล์ผ่าน; frozen V4 31 ไฟล์และ manifests ทั้งสองรอบไม่เปลี่ยน ไม่แก้ policy, baseline SQLite, live services, emulator, AWS หรือ PR ของอีก thread

[ผล tests](../../outputs/statement-four-part-20261023/full-suite.txt) · [source verification](../../outputs/statement-four-part-20261023/parent-verification.json) · [วิธีรันซ้ำ](STATEMENT_FOUR_PART_REVIEW_TH.md) · [coverage 6 มิติ](STATEMENT_REVIEW_COVERAGE_TH.md)

ยังไม่ได้ยืนยันกับ statement ไทยจริงที่หลากหลาย, OCR สด, bank/dStatement จริง, ภาระนอกบัญชี/เงินสด, หรือผลิตภัณฑ์สินเชื่อจริง รายงานนี้เป็นข้อมูลเตรียมให้เจ้าหน้าที่ตรวจ ไม่ใช่ผลอนุมัติ/ปฏิเสธสินเชื่อ
