# ผลทดสอบ Agent service — 24 ตุลาคม 2026

Service integration กับ model acceptance เป็นคนละผลกัน รอบนี้เชื่อม browser
และ Android/Go เข้า service ที่เก็บงานถาวรแล้ว แต่ Typhoon ยังทำ native tool task
ตัวอย่างไม่จบ จึงยังเรียกว่า workflow พิจารณาสินเชื่อเสร็จสมบูรณ์ไม่ได้

## สิ่งที่ตรวจผ่าน

- Python รวม **677 passed / 15 skipped / 1 known strict XFAIL**; skips เป็น
  historical bundles ที่ไม่อยู่ใน publication checkout ส่วน XFAIL เกี่ยวกับ
  controller เดิมไม่บังคับ balance continuity ข้ามเอกสาร ยังไม่ได้แก้ในงานนี้
- Node UI **42 passed**; Ruff check/format ผ่าน; build Python wheel ผ่าน
- Browser จริง: กรอก synthetic applicant, เพิ่ม PDF ตัวอย่างพร้อม recorded OCR,
  ส่งงาน Offline แล้วดูรายงาน 4 ส่วนพร้อม refs ในพื้นที่เจ้าหน้าที่
- Browser จำลอง server รับงานแล้วแต่ตอบกลับหาย: pending command อยู่หลัง reload,
  กดคำสั่งเดิมแล้วคืนงานเดิม ตรวจ SQLite พบ **1 job** ของเคสนี้ ไม่มีงานซ้ำ
- Regression HTTP: Android internal submit → แยก persisted ReviewService,
  fresh submit/แก้ input/upload/remove ถูกกันไว้เมื่อคำสั่งเดิมยังไม่แน่นอน,
  explicit recovery ใช้ body/key เดิม และ late result ไม่ทับรุ่นใหม่/ผลของคน
- Native Android APK เดิมเปิดและอ่าน onboarding/loan list ผ่าน Go 18082 →
  Case API 8770 ได้ รอบ parent นี้ **ไม่ได้กรอกและยื่น Android เคสใหม่จนครบ**;
  submit/recovery ถูกตรวจผ่าน scoped HTTP tests ต้องแยกจาก native UI acceptance
- ระหว่างคำสั่ง Android ยังไม่แน่นอน ต้องกู้คืนงานเดิมก่อนส่งคำขอข้อมูลเพิ่ม
  เพื่อไม่ให้เคสติด WAIT_CUSTOMER; receipt ของคำตัดสินที่เคยรับแล้ว replay ได้ตามเดิม
- Black-box auth: encoded service route ที่ไม่ส่ง Bearer ได้ HTTP 401

ฐาน SQLite เดิม 11 เคสถูกคัดลอกเข้า demo state แยกพร้อมเอกสาร/receipts;
SHA-256 ฐานต้นทางก่อนและหลังตรงกัน ไม่มีการลบหรือเปลี่ยนฐานต้นฉบับ

## ลอง Typhoon จริงสองรอบ

ใช้ `typhoon-v2.5-30b-a3b-instruct` กับ synthetic case เดียวกัน, recorded OCR
จึงมี **OCR API calls = 0** ทั้งสองรอบ ไม่มี OpenAI API call ในงาน service นี้
ผลไม่ใช่ live OCR acceptance และไม่ใช่การทดสอบครบชุด C/H/S เดิม

| รอบ | Native calls | Total tokens | ผล |
|---|---:|---:|---|
| ก่อนแก้ diagnostics | 4 | 12,232 | TECHNICAL_REVIEW |
| ลองใหม่ตามคำขอ หลังแก้ service | 4 | 12,243 | TECHNICAL_REVIEW |

Token แยกแต่ละ call ของรอบลองใหม่:

| Call | Input | Output | รวม | สิ่งที่เกิดขึ้น |
|---|---:|---:|---:|---|
| 1 | 2,895 | 20 | 2,915 | compare_declarations สำเร็จ |
| 2 | 2,774 | 17 | 2,791 | inspect_cashflow สำเร็จ |
| 3 | 3,151 | 68 | 3,219 | ปฏิเสธ native response: unknown_tool / unknown_name |
| 4 | 3,233 | 85 | 3,318 | หลัง bounded protocol repair ยัง unknown_tool / unknown_name |

ทั้งสี่ครั้งเป็น HTTP 200 จึงไม่ใช่ปัญหาติดต่อ provider ไม่ได้ แต่คำตอบสองครั้งท้าย
อ้างชื่อ function ที่ไม่อยู่ในรายการ tool ที่อนุญาต ณ รอบนั้น Controller ไม่ execute
คำสั่งนั้นและส่งต่องานตรวจไม่ครบ ตัว diagnostics แบบ enum/count ไม่เก็บชื่อ tool
นอก allowlist หรือ raw rejected response จึงยังระบุชื่อ function ที่โมเดลส่งกลับไม่ได้
ไม่ควรสรุปจากหลักฐานเท่านี้ว่าเกิดจากความฉลาดของโมเดลอย่างเดียว

Trace ใหม่มี accepted tool arguments/เหตุผลสั้น ๆ/observations และ `llm_attempt`
ครบทุก provider call รวมรอบสุดท้ายที่ถูกปฏิเสธ ไม่ใช่ private chain-of-thought
รายงานยังแสดงหลักฐานบางส่วนได้ แต่เว็บระบุว่า “ตรวจไม่ครบ/ปัญหาเทคนิค”
ไม่มี financial approval packet และไม่มีคำตัดสินจาก Agent

## ส่วนที่ต้องทำต่อ

1. ปิดปัญหา model/tool adherence ด้วย repro ที่เก็บ input context/tool schema และ
   diagnostics แบบปลอดข้อมูลลับ เปรียบเทียบ prompt/controller/provider โดยใช้
   fixtures และ held-out assertions เดิม ไม่แก้ oracle ให้ผ่านตามคำตอบโมเดล
2. ส่ง trusted onboarding snapshot ที่ผูก KYC session/owner/version เข้า native
   evidence context อย่างชัดเจน ปัจจุบัน staff อ่านสถานะธนาคารผ่าน Go card;
   service ใหม่เน้น statement evidence และยังไม่ได้แทน underwriting controller ทั้งชุด
3. ทดสอบ financial/policy semantics ที่ยังไม่ผ่าน เชื่อมหลักฐานรายได้/หนี้/ภาระจ่าย
   ที่ทีมเครดิตยอมรับ ก่อนให้ผลประเมินกำลังชำระรองรับการตัดสินใจของเจ้าหน้าที่
4. เพิ่ม workflow ขอเพิ่มวงเงินจาก loan/repayment ledger: ค่างวดที่ถึงกำหนด,
   จ่ายจริง, ค้าง/DPD, ปิดก่อนกำหนด และกระแสเงินสดล่าสุด โดยไม่ถือว่าจ่ายเร็ว
   หรือไม่เห็นหนี้ในบัญชีเดียวเป็นเหตุอนุมัติอัตโนมัติ
5. ก่อน production ต้องมี staff identity/roles, storage/queue/reconciliation,
   TLS/secrets/retention และ deployment acceptance ภายใต้เป้าหมาย AWS/งบที่ยืนยัน

อ่าน [คู่มือรัน](../../agent_app/SERVICE_GUIDE_TH.md) และ
[สถานะ workflow ให้ทีม](TEAM_AGENTIC_STATUS_20261024_TH.md)
หลักฐานดิบอยู่ใน `outputs/agent-service-20261024/` ของ workspace ผู้ทดสอบ ไม่รวม Git
Docker engine/Compose ใช้งานไม่ได้บนเครื่องพัฒนารอบนี้ จึงให้ hosted container job
ตรวจ build/start แยก และต้องดูผลที่ PR head จริงก่อนถือว่าผ่าน ไม่มี AWS deploy ในรอบนี้
