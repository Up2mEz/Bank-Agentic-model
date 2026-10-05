# ผล review ก่อนเผยแพร่

5 ตุลาคม 2026 ตรวจ maintained implementation, ผลทดลองและ staged Git snapshot ของโครงการนี้

**คำตัดสินโมเดล:** V3 pooled OOF log loss ดีขึ้น 0.427110 → 0.425785 แต่หนึ่ง fold แย่ลง จึงคง V2 ตาม frozen gate ไม่มีการเปลี่ยน threshold/gate/feature grid เพื่อให้ candidate ได้ promotion

ผลตรวจที่ทำจริง:

- unit tests 20 ข้อผ่าน รวม real small CatBoost save/reload, schema/probability rejection, inner-only refit, group separation, calibration boundary 0/1 และ label-only raw-snapshot change
- Ruff lint/format และ Python compile checks ผ่านสำหรับ `src`, `tests`, `tools`; whitespace review ของ maintained source ผ่าน Historical `scripts/`/`reports/` รักษา bytes เพื่อ provenance ไม่ใช้ formatter เปลี่ยน frozen sources
- Features ใหม่ตรง legacy V2 ทุกเซลล์ 30,000 แถว: behavior37/trajectory68/no-demographics64; batch/single/nonunique-index probes ผ่าน
- clean V2 refit probabilities ตรง historical V2 ทุกแถวทั้ง validation/test: maximum absolute difference 0; selected saved pipeline ตรง gate และ metrics recompute ผ่าน
- ตรวจ cached UCI CSV และ original XLS กับ Kaggle mirror อีกครั้ง: 0 differing cells; `reports/v3/source_audit.json`
- staged publication audit ตรวจ actual local `.env` credential values และ common patterns โดยไม่พิมพ์ค่า ไม่มี key/raw data/model checkpoints/local agent logs ถูก stage; Markdown local links ตรวจแล้วไม่มีลิงก์ไป excluded outputs ที่หายจาก Git
- native agy method review, code-excerpt review และ full-helper follow-up สำเร็จ; ข้อเสนอที่เดาจากโค้ดไม่ครบถูกหักล้างด้วย definitions/tests ไม่แก้โค้ดตามคำอ้างผิด

Failure analysis ที่ไม่ถูกกลบ:

- บน old test V3 AUC 0.788159/log loss 0.426297 เทียบ V2 0.786933/0.426866 แต่ AP ลด 0.548343 → 0.547486
- ที่ top-10% review capacity V2 จับ default ได้ 312 ราย ส่วน V3 ได้ 307 ราย; ไม่เลือก capacity ใหม่เพื่อทำให้ผลดูดีขึ้น
- Quiet group old test: V2 FN@.5 348/349 events; V3 FN 349/349 events แม้ log loss/AUC ภายในกลุ่มดีขึ้นเล็กน้อย threshold .5 จึงต้องแยกจาก ranking/probability quality
- bootstrap differences ของ old test ทั้ง AUC/log loss/Brier คร่อมศูนย์; เป็น conditional descriptive resampling ไม่ใช่ selection-adjusted intervals
- inner-tree median/ขนาด refit/fixed blend เป็นข้อจำกัดเชิงวิธีที่ต้องตรวจต่อบน labeled cohort ใหม่ ไม่ได้พิสูจน์ causal cause ของ fold ที่แย่ลง

CLI preflight มี dispatch error ก่อนเริ่ม fitting; แก้และเพิ่ม regression test โดยรักษา unused protocol/failure record แล้ว freeze ใหม่ก่อนมี model outcomes ไม่มีการ rerun เพื่อเลือกผล test ที่ดีที่สุด

รายงานเชิงวิธี/ตัวเลข: `reports/v3/REPORT_TH.md`, `research/ITERATION_3_RESEARCH_TH.md`, `research/AGY_V3_REVIEW_DISPOSITION_TH.md` GitHub Actions จะแสดงผลหลัง push; ผล CI ต้องตรวจจาก run จริงก่อนอ้างว่า cloud checks ผ่าน
