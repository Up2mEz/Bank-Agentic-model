# การทดลองและการเรียก agent โดยตรง

วันที่ 4 ตุลาคม 2026; บันทึกสำหรับรอบทดลอง `experiment_v1`

**หมายเหตุสถานะ:** ส่วนด้านล่างเก็บประวัติรอบแรก การเรียก Gemini เป็นเหตุการณ์ก่อนผู้ใช้สั่งให้ใช้ agy เท่านั้น รอบลองใหม่ไม่มีการเรียก Gemini CLI และ TabPFN-3.5 ผ่าน access smoke แล้ว ดูภาคผนวกท้ายเอกสารสำหรับสถานะล่าสุด

## ขอบเขตที่ผู้ใช้อนุญาต

ผู้ใช้ให้เริ่มทดลองโมเดลตามแผน เรียก agy/Gemini CLI โดยตรง และยืนยันว่า TabPFN ใช้ในงานที่ไม่ใช่เชิงพาณิชย์ รอบนี้จึงดาวน์โหลดข้อมูลสาธารณะ ติดตั้ง dependencies ใน `.venv` ของโครงการ และฝึกโมเดล ไม่ได้ deploy หรือเปลี่ยนระบบอนุมัติสินเชื่อใด

## Herdr: พิสูจน์สาเหตุจากโค้ด

- `herdr status` ในรอบนี้สำเร็จ: client/server protocol 22, private protocol compatible, endpoint compatible และไม่ต้อง restart
- `C:\Users\acer\AppData\Local\herdr-a2a-src\src\herdr\types.ts:10` ประกาศ `REQUIRED_PROTOCOL = 20`
- `src\spawn\preflight.ts:81` ตรวจ `pong.protocol === REQUIRED_PROTOCOL` และบรรทัด 87 สร้างข้อความ mismatch ที่พบ
- build ที่ CLI ใช้ (`dist\herdr\types.js`, `dist\spawn\preflight.js`) มีเงื่อนไขเดียวกัน
- จึงยืนยันได้ว่าตัวเชื่อมล็อก protocol เก่า และ server 22 ถูกปฏิเสธจาก exact-equality check นี้ ไม่ใช่หลักฐานว่า Herdr server หยุดทำงาน
- รอบนี้ A2A discovery ยังพบว่า gateway localhost:59949 ไม่พร้อม เป็นสถานะปัจจุบันอีกเรื่องหนึ่ง ไม่ลบหลักฐานของ error ในรอบก่อน
- ไม่แก้ constant เป็น 22 แล้วอ้างว่ารองรับสำเร็จ เพราะ API/schema/semantics ยังต้องทดสอบ ไม่ restart/upgrade หรือแก้ shared tooling นอกงานนี้
- inherited pane IDs ไม่ตรงกับ live IDs (`pane_not_found`) จึงไม่ใช้ focused pane ของงานอื่น

## agy โดยตรง

1. อ่าน `agy --help` และเรียก print mode + plan mode ด้วยงาน read-only
2. งานที่ให้เปิดไฟล์ไม่ผลิตผล เพราะ headless mode auto-denied tool permission `command`; exit code 0 จึงไม่ได้ถูกตีความเป็นผลสำเร็จ
3. ส่งงานใหม่ที่ต่างจากเดิม โดยป้อน design และโค้ด protocol ที่ตรวจแล้วใน prompt และกำหนด no tools ผลตอบกลับสำเร็จ เก็บใน `outputs/agents/agy_inline_review.txt`

ผลรีวิวนี้เป็น **การวิจารณ์จากข้อมูลที่ป้อนให้** ไม่ใช่การเปิดไฟล์หรือคำนวณ raw dataset โดย agy เอง สิ่งที่นำมาใช้:

- เลือก champion จาก pipeline หลัง calibration แทนการเลือกจาก raw probability อย่างเดียว
- ตรวจจำนวน/สัดส่วน events หลัง group stratification จริง
- แยก TabPFN ที่ใช้ข้อมูลย่อย พร้อม CatBoost บนข้อมูลย่อยเดียวกัน
- กันข้ออ้าง temporal/Thai-bank deployment และระบุ uncertainty

สิ่งที่ไม่รับรองตามรีวิว:

- คำอธิบาย repayment code `0` ที่ agent เสนอไม่มีหลักฐานจาก dictionary ที่ตรวจ จึงไม่ใช้
- ความเข้ากันได้ย้อนหลังของ protocol 22 กับ 20 ไม่ได้พิสูจน์จาก `herdr status`; compatibility ที่รายงานเป็นระหว่าง client/server รุ่นปัจจุบัน
- ตัวเลข prevalence/จำนวน events ที่ agentประมาณเองไม่ใช้แทนค่าที่คำนวณจากไฟล์
- ข้อกล่าวว่าหมวดหมู่ใหม่จะ error ทุกโมเดลไม่เป็นจริงทั่วไป; pipeline ระบุ handling ของ unknown และตรวจ output จริง

## Gemini CLI โดยตรง

อ่าน help และเรียก `gemini --approval-mode plan --prompt ...` โดยตรงแล้ว แต่ไม่เริ่ม review:

```text
IneligibleTierError
reasonCode: UNSUPPORTED_CLIENT
This client is no longer supported for Gemini Code Assist for individuals.
```

ยังมี warning ว่า workspace ไม่ trusted และ approval mode ถูกเปลี่ยนเป็น default ไม่ปรับ trust หรือ auto-approve เพื่อข้ามข้อจำกัด ไม่อ้างว่ามีผลจาก Gemini หรือใช้โมเดลอื่นแล้วเรียกชื่อว่า Gemini

## TabPFN

ติดตั้ง `tabpfn==9.1.0` แล้วลอง V3.5 บนข้อมูลสังเคราะห์ขนาดเล็กเพื่อทดสอบโหลด/ทำนายโดยไม่แตะ final test พบ `TabPFNLicenseError`: ต้องมี login/license acceptance และ token ของบัญชีจากผู้ให้บริการ จึงยังไม่มีผล credit benchmark ของรุ่น 3.5

ขอให้ผู้ใช้ทำ authentication โดยไม่ส่ง secret ในแชต และดำเนินงานที่ไม่ขึ้นกับ token ต่อ มีการทดลอง V2 ที่เข้าถึงได้เป็น auxiliary CPU trial ตาม subset ที่ล็อกไว้ก่อนฝึก ไม่เปลี่ยนชื่อเป็น 3.5 และไม่ใช้ผลข้อมูลย่อยแทนอันดับบนข้อมูลฝึกเต็ม [official access guide](https://docs.priorlabs.ai/models/accessing-model-weights), [official repository: version and license distinctions](https://github.com/PriorLabs/TabPFN)

ผลจริงและเวลาที่วัดได้ให้ดู `outputs/experiment_v1/tabpfn_trial.json` เมื่อ trial จบ ส่วนสถานะ V3.5 อยู่ใน `outputs/diagnostics/tabpfn_3_5_smoke.json`

## ภาคผนวก: รอบผู้ใช้ใส่ key และสั่งลองใหม่

- ตรวจ authentication โดยเก็บเพียงสถานะ ไม่บันทึกหรือแสดง token; key อยู่ใน `.env` ที่ `.gitignore` ป้องกันไว้ และ `.env.example` กลับเป็น template ว่าง
- ก่อนลองใหม่ token ใช้ได้แต่บัญชียังไม่ยอมรับ license; เมื่อผู้ใช้สั่งลองใหม่ `scripts/tabpfn_access_check.py` สำเร็จจริง: V3.5 บน CPU ฝึกข้อมูลสังเคราะห์และทำนาย 8 แถว ได้ shape `[8, 2]` ใช้เวลา 57.33 วินาที
- ใช้ `scripts/tabpfn_cpu_trial.py --version v3.5` กับ subset เดิมที่ล็อกไว้ ไม่ rerun main training หรือเปลี่ยน main champion การประเมินเพิ่มเติมแยกใน `tabpfn_v3_5_results.json`; ผลสุดท้ายรวมใน `REPORT_TH.md`
- ปรับ skills ต้นทางทั้งสามและซิงก์โดยไม่เรียก Gemini CLI; รายละเอียดและข้อจำกัดของ bridge อยู่ใน [รายงานปรับ Herdr skills](HERDR_SKILLS_UPDATE_TH.md)
- agy ตรวจคำสั่ง skills จากข้อความที่ให้ พร้อมสี่สถานการณ์จำลอง; ผลอยู่ใน `outputs/agents/agy_herdr_skill_forward_test.txt` ไม่อ้างว่า agy ทดลอง transport หรือคำนวณ metrics เอง
- V3.5 auxiliary trial จบสำเร็จ: fit/preprocessing/calibration 40.08 วินาที และทำนาย test batch 159.85 วินาที; AUC 0.772835, AP 0.525400, log loss 0.434855, Brier 0.136513 เลือก identity จาก calibration OOF ตามเกณฑ์เดิม ไม่ปรับ probability จาก test
- Addendum ตรวจ actual version, trial success, 4,500 test IDs/order, uniqueness และ finite probability ในช่วง [0, 1] ผ่าน พร้อม SHA-256 ของ protocol/subset/predictions/selection/main results เพื่อเชื่อมหลักฐาน รุ่น 3.5 เป็นผลเพิ่มเติมที่กำหนดไว้ก่อนแต่เข้าถึงได้ภายหลัง ไม่ใช้เลือกโมเดลหลักซ้ำ
