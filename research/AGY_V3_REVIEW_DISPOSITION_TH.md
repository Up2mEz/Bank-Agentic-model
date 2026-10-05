# การตรวจข้อเสนอจาก agy รอบสาม

เรียก native `agy --print ... --mode plan` ตาม current help ไม่มี Gemini CLI, ไม่ใช้ auto-approve และไม่ควบคุม Herdr pane อื่น รีวิววัสดุที่ให้ใน prompt เท่านั้น ไม่ใช่การอ่านไฟล์/ตรวจข้อมูลอย่างอิสระ

Method review: exit 0, stdout 6,864 characters, nonempty, ไม่ตรวจพบ denied-tool marker; status/prompt hash เก็บใน local `outputs/agents/agy_v3_method.status.json` ไม่เผย raw agent logs บน Git

| ข้อเสนอ/ข้ออ้างจาก agy | ผลตรวจและการจัดการ |
|---|---|
| ข้อมูลเดิมมี historical adaptivity; nested search ไม่ทำให้ holdout กลับมาอิสระ | ยอมรับและระบุทั้ง protocol/report; ข้อมูล/architecture มีประวัติเลือกมาแล้ว |
| median inner best iterations เป็น heuristic และอาจไม่เหมาะกับ refit ที่มีแถวมากขึ้น | ยอมรับเป็นข้อจำกัดที่ประกาศก่อนรัน ไม่แก้ budget ตามผล outer/test |
| fixed blend weight อาจไม่เหมาะกับ probability scale ใหม่ | เป็นสมมติฐานที่สมเหตุสมผล แต่ยังไม่ได้วัด optimum ใหม่ คง .75/.25 ตาม protocol และรายงานการปิด gate ถ้าไม่ผ่าน |
| reused LightGBM OOF ใช้ได้เมื่อ folds/features/seed ตรง | ตรวจ SHA/IDs/order/folds และ exact feature migration; ระบุ selection history ของ V2 ด้วย ไม่เรียกว่ายืนยันอิสระ |
| bootstrap จาก fixed predictions ไม่รวม training/model-selection variance | ยอมรับ ระบุเป็น conditional descriptive intervals |
| quiet-group default มักเกิดจากตกงาน/ภาระหนี้ที่อื่น/วิกฤต | **ไม่รับเป็นผลค้นพบ**: dataset ไม่ได้มีตัวแปรเหล่านี้ และยังไม่วัดสาเหตุ ทำได้เพียงเสนอว่าต้องหาข้อมูลเพิ่มเติม |
| Logloss กด quiet-group probability ต่ำกว่า .5 เสมอ | **ไม่รับข้อความเหมารวม**: ไม่ใช่ theorem ที่ review ให้หลักฐาน และผลเดิมมี quiet-group TP 1 รายที่ .5; อธิบายด้วย base-rate และ score distributions ที่วัดแทน |
| no-positive codes แปลว่าประวัติชำระปกติ | **ไม่รับความหมายที่ยังไม่ทราบ**: ใช้คำอธิบายตามค่ารหัสที่เห็นเท่านั้น |
| ลอง class weights/focal loss หรือ threshold แยกกลุ่ม | ยังไม่ทดลอง; class weighting เปลี่ยนเป้าหมาย probability และ threshold ต้องผูก costs/capacity ที่ทราบ ไม่เพิ่มหลังเห็นผลรอบนี้ |

## Code review: ตรวจข้อทักท้วงกับ helper definitions และ tests

Code-excerpt review สำเร็จจริง: exit 0, stdout 11,133 characters; พบหลายข้ออ้างที่เกิดจาก helper definitions ไม่ได้อยู่ใน excerpt จึงส่ง complete helper modules ให้ agy ตรวจใหม่ผ่าน native CLI เดิม Full-helper review: exit 0, stdout 7,776 characters และกลับมายอมรับว่าข้อกล่าวอ้างหลัก 5 ข้อก่อนหน้าไม่ถูกต้อง ผลนี้ยังเป็น supplied-material review ไม่ใช่การรันโค้ดของ agent

| ข้อทักท้วง | สิ่งที่ตรวจจริงและข้อสรุป |
|---|---|
| logit 1D/ไม่มี clipping | `logit` clip ด้วย 1e-7 และ reshape(-1,1) อยู่แล้ว; test boundary 0/1 ตรวจ 2D/finite ผ่าน |
| `fitted.predict` คืน class labels | `fitted` เป็น Calibrator wrapper; sigmoid เรียก predict_proba[:,1] และ isotonic เป็น regression; test probability parity ผ่าน |
| group_folds เป็น generator หมดหลัง candidate แรก | helper คืน `list`; ทั้งสอง configs ได้ inner results ครบ และทุก outer fold เลือก depth6 ได้จริง; test reusable folds/calibrator scores ผ่าน |
| features อาจรวม target/ID | เริ่มจาก explicit 23 PREDICTORS และทุก summary within-row; actual full-data migration กับ tests ที่เปลี่ยน ID/target/row order ผ่าน |
| inner groups_disjoint=True เป็น hardcoded claim | ก่อนกลับจาก group_folds มี disjoint_groups และ class checks ทุก fold; test duplicate/conflicting-label groups ผ่าน |
| categorical floats ทำให้ CatBoost ใช้ไม่ได้ | feature transform แปลง original categorical predictors เป็น strings; real CatBoost fit/reload และ full experiment รันสำเร็จ |
| LightGBM Component default categories={} ทำให้ current experimentพัง | เป็นกรณีสร้าง adapter ผิดสัญญาจากภายนอก; executed `fit_lightgbm` ส่ง training dictionary ครบ และ clean V2 probabilities ตรงเดิมทุกแถว การเติม validation ของ manual construction เป็น prospective API hardening ไม่ใช่เหตุให้แก้ผลทดลอง |
| unknown code เป็น NaN ใน LightGBM ขัดกับ retain-code policy | raw columns และ CatBoost เก็บค่ารหัส; LightGBM ยึด training category dictionary และ unseen levels มีนโยบาย missing ที่ระบุและทดสอบไว้ ไม่เติมความหมายให้รหัส |
| CSV tolerance1e-12 เข้มเกิน | actual probability blend/reload/recompute ผ่าน; ไม่ขยาย tolerance เพื่อกลบผลไม่ตรงที่ยังไม่มีหลักฐาน |
| Duplicate indexes ควรถูก reject/reset | ไม่รับคำเสนอ: validation รักษาแถว และ test nonunique index + actual probes ผ่าน; input_row_position ช่วยจับคู่ output ตามตำแหน่ง |

ไม่ปรับปรุง score ด้วยการเติม clipping/class weighting/เติมความหมาย category หลังเห็นผล การเปลี่ยน handling ของ missing inputs หรือโครงสร้าง adapter ในอนาคตต้องมี schema/protocol version ของตัวเอง

Primary review เพิ่ม `tools/verify_input_sources.py` ตรวจ downloaded CSV SHA เทียบ historical V1/V2 baseline ก่อนทดลอง เพื่อป้องกันนำ saved OOF ไปใช้กับ snapshot ที่เปลี่ยน labels คำสั่งทำซ้ำระบุ prerequisite นี้ชัดเจน source ของการทดลอง V3 คง frozen hashes เดิม

ผลที่ตรวจจริง: clean V2 refit probability ตรง historical V2 **ทุกแถว** ทั้ง validation/test (maximum absolute difference 0), selected saved pipeline ตรง gate, batch/single/reload/nonunique-index parity ผ่าน ส่วน V3 candidate ไม่ได้ promotion เพราะหนึ่ง outer fold แย่ลงตาม gate เดิม
