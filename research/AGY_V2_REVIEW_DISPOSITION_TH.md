# คัดข้อเสนอ agy รอบสองตามหลักฐาน

agy เรียกผ่าน native CLI สองครั้ง: methodology review และ code review จากข้อความที่ส่งให้ ไม่เปิด raw data/repository เอง ผลอยู่ใน `outputs/agents/agy_v2_method_review.txt` และ `agy_v2_code_review.txt` ไม่มีการเรียก Gemini CLI

| ข้อเสนอ/ข้อกล่าว | ผลตรวจของเรา | การดำเนินการ |
| --- | --- | --- |
| Test เดิมเปิดแล้วและ OOF ใช้เลือก จึงมี optimism | สอดคล้องกับประวัติ/โค้ด และ primary paper ที่อ่าน | ระบุ exposed references และ selected OOF bias; ไม่อ้าง unbiased/generalization |
| ล็อก tuning budget และเทียบ TabPFN/CatBoost ขนาดข้อมูลเท่ากัน | สอดคล้องเป้าหมาย | ล็อก 9 candidates ก่อน CV และ fixed nested 4,000 context พร้อม comparator |
| การหาร NumPy กับ pandas ทำให้ features เป็น NaN เมื่อ index ไม่ต่อเนื่อง | **ไม่เกิดตามที่กล่าวในโค้ดนี้** `features()` คืน copy โดยไม่ reset index การตรวจ batch กับทีละแถวที่เก็บ original indices ตรงกัน | ไม่เปลี่ยน feature definition ระหว่างรัน |
| CatBoost eval_set ไม่ผ่าน input_for จึง dtype mismatch | **ไม่ใช่ปัญหาในโค้ดนี้** input_for แปลงเฉพาะ LightGBM; CatBoost input เป็นค่าชุดเดียวกัน | ไม่แก้ preprocessing จากสมมติฐานที่ตรวจแล้วไม่เกิด |
| LightGBM no-demographics จะ KeyError | เป็นกรณีอนาคตที่ไม่มีในกริดนี้; no-demographics candidate เป็น CatBoost | บันทึกข้อจำกัด ไม่เพิ่ม/เปลี่ยนกริดเพื่อแก้ hypothetical case |
| Cache อาจมี summary ก่อนเขียน OOF | ลำดับโค้ดจริงเขียน OOF ก่อน summary; select ตรวจ IDs และ analysis ตรวจ probability อีกครั้ง | ไม่อ้างว่าพบ cache corruption หรือ rerun training จากข้อเดา |
| ผล reference table ต้องบอก selected pipeline | ข้อเสนอที่มีประโยชน์ต่อการอ่านผล แม้ report เดิมมี gate แล้ว | เพิ่ม `is_selected_pipeline`, selection hash และ evaluation timestamp ก่อน finalize โดยไม่เปลี่ยนเกณฑ์ |
| Scoring ควรรักษา index และหลีกเลี่ยงโมเดล weight 0 | มีประโยชน์ต่อการตรวจลำดับและ compute | รักษา index/เพิ่ม input_row_position; endpoint weight เรียกเฉพาะ active model ไม่เปลี่ยน prediction formula |
| Negative bill คือ overpayment/refund; บิลล่าสุด due October | ไม่มีหลักฐานจาก dictionary ที่อ่านรองรับรายละเอียดนี้ | ไม่ใช้ข้ออธิบายสาเหตุ/settlement timing นั้น |
| Monotonic constraints รับรองเสถียรภาพ/calibration | เป็น hypothesis ที่ไม่มีผลทดสอบในงานนี้; original unknown codes เป็น nominal | ไม่บังคับหรืออ้างประโยชน์ที่ยังไม่พิสูจน์ |
| LightGBM เดี่ยวแพ้จึงห้าม blend | ไม่ใช่เงื่อนไขจำเป็นทางคณิตศาสตร์ เพราะ errors อาจ complementary | คงกริดน้ำหนักที่ล็อกไว้; ใช้ OOF วัดจริง |
| 1-SE/ECE/feature count cutoffs ตามที่ agent เสนอเป็น significance/stop rule | กฎบางข้อเป็น arbitrary และ row-level SE ไม่บัญชี model selection/group/fold dependence | ไม่ใช้เป็นหลักฐาน significance; ใช้ development gate ที่ระบุขอบเขตชัด |

`--mode plan` ใน methodology review ครั้งแรกมี warning ว่าไม่มีผลร่วมกับ disabled slash expansion จึงไม่อ้างว่า mode enforcement ผ่าน คำสั่ง code review ครั้งถัดไปไม่ใส่ flag นั้น ไม่มี auto-approve ทั้งสองครั้ง และไม่รายงานให้ agy เป็นผู้รัน tests หรือฝึกโมเดล

การตรวจ runtime/prediction parity เป็นงานที่รันในโครงการนี้โดยเรา หลักฐานสุดท้ายอยู่ใน `outputs/experiment_v2/analysis.json` การ compile พบวงเล็บตกใน report builder และแก้ก่อนสร้างรายงาน ไม่กระทบข้อมูลหรือการฝึก
