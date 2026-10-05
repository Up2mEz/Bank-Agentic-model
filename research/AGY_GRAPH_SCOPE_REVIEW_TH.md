# การตรวจข้อเสนอ agy สำหรับ graph fraud / bank-event scope

วันที่ 5 ตุลาคม 2026 — Native `agy --print <prompt> --mode plan` ได้รับ note ก่อนแก้ครบทั้งฉบับและ local raw-audit JSON ใช้คำสั่งผ่าน runner [review_with_agy.py](../tools/review_with_agy.py) โดยห้าม tools/network/file edits และห้ามอ้าง independent measurements ไม่เรียก Gemini CLI

หลักฐาน runtime: exit code 0, stdout 9,680 characters, stderr ว่าง, ไม่พบ denied-tool markers; prompt SHA-256 `1b7929cf89a2f26083013b3ca52d6b78197e122cd8e66325b6c73e728bf68be6`; เริ่ม `2026-10-05T09:41:00.124229+00:00`, เสร็จ `2026-10-05T09:42:23.502869+00:00` Raw prompt/stdout/status อยู่ใน local ignored outputs จึงไม่แนบเป็น public evidence ที่อ้างว่า agent ตรวจแหล่งข้อมูลเอง

| ประเด็นที่ reviewer เสนอ | การพิจารณา / การแก้ใน note |
|---|---|
| แบ่ง cohorts ตาม outcome maturity ทำให้ลำดับเหตุการณ์สลับกัน | **รับแก้ถ้อยคำ**: แบ่งตาม prediction timestamp, แยก label availability สำหรับ training cutoff และติดตาม outcomes ของ evaluation ให้ครบพอ ไม่ใช้ label confirmation date เป็นแกน split |
| k-NN graph ต้องไม่ใช้ holdout เปลี่ยน training representations | **รับสำหรับ inductive experiment ที่เสนอ**: fit transforms/references ใน training fold แล้ว query แถวประเมิน; ไม่รับข้อสรุปว่าการเห็น unlabeled test features คือ leakage ในทุก setting เพราะต้องตัดสินตามข้อมูลที่อนุญาตและเวลาที่พร้อมใช้ |
| grouped vectors ไม่ใช่เครื่องมือป้องกัน leakage; conflicting labels เป็น label noise / irreducible Bayes error | **ปรับคำให้ชัด แต่ไม่รับข้อสรุปเรื่อง noise/Bayes error**: grouped splitting ลด exact-vector overlap ได้ตามกลไกที่ประกาศ ยังไม่พิสูจน์ว่ากลุ่มนั้นเป็น borrower identity; 56 คือ extra rows ไม่ใช่จำนวน duplicate-group rows ทั้งหมด Labels ขัดกันไม่ได้ระบุว่าเกิดจาก annotation error และไม่ให้ Bayes error ของ population |
| แปลง borrower/month แล้วแปะ target รายเดือนเสี่ยงตีความอนาคตผิด | **รับ clarification**: ไม่มี historical monthly outcome labels; whole sequence ทำนายหนึ่ง target ที่จุดตัดได้ ไม่อ้างหก targets หรือหก independent clients การแตก feature representation อย่างเดียวไม่ได้พิสูจน์ว่าเกิด leakage แล้ว |
| ระบบจริงต้องใช้แต่ unseen nodes และห้าม transductive ทั้งหมด | **ไม่รับข้อกำหนดแบบเหมารวม**: บัญชีเดิมอาจมี transaction ใหม่ในอนาคต สิ่งที่ต้องคุมคือ prediction-time information และ label availability; รายงาน existing/unseen entities แยกกัน และจำกัด static transductive results ตาม benchmark setting |
| IEEE-CIS graph ต้องห้าม future links/labels | **รับเจตนาหลัก** และเพิ่ม cutoff ใน candidate table; ไม่รับการห้ามใช้ทุก historical event ที่ยังไม่ยืนยัน label เพราะ unlabeled past events ใช้เป็น context ได้ ส่วน fraud status ใช้ได้เมื่อทราบผลแล้ว ไม่กล่าวหาว่าตัวอย่าง AWS เกิด leakage ที่ตรวจพบจริง |

ผลการพิจารณาอาศัย audit/schema/dictionary ที่โครงการตรวจเองและตรวจความหมายของข้อเสนอกับ task definition ไม่มี GNN training, numerical performance comparison หรือ independent fraud-dataset validation เกิดขึ้นในรีวิวนี้ ไม่ใช้ถ้อยคำรับรองความพร้อมใช้งานของ agent เป็นหลักฐาน
