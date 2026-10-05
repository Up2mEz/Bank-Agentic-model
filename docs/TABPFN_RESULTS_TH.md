# ผลทดลอง TabPFN และขอบเขตการเปรียบเทียบ

สรุปจาก artifacts ที่อยู่ใน Git ตรวจวันที่ 5 ตุลาคม 2026 ตัวเลขปัดเป็นทศนิยม 6 ตำแหน่ง; ผล JSON ต้นทางเก็บ precision เดิม เอกสารนี้จัดการนำเสนอผลที่มีอยู่ ไม่ใช่การฝึกโมเดลรอบใหม่

## รุ่นโมเดลกับรอบทดลอง

**TabPFN V2** และ **TabPFN-3.5** เป็นรุ่นของโมเดล ส่วน **รอบทดลอง V1/V2/V3** เป็นลำดับการพัฒนาโครงการ เช่น `reports/v1/tabpfn_v3_5_results.json` เป็นผล TabPFN-3.5 ในรอบทดลอง V1 ไม่ใช่ TabPFN รุ่น V1

**Context** คือ labeled examples ที่ TabPFN ใช้ประกอบ inference การทดลองตั้ง `fit_mode='fit_preprocessors'`; การ `fit` จัดเตรียม context/preprocessing ไม่มีการฝึกน้ำหนัก foundation model ใหม่

## ผลบน reference test

ทุกแถวประเมินบน test IDs 4,500 แถวชุดเดียวกัน มี default labels 995 แถว ตารางแสดง probabilities หลังเลือก calibration ตาม protocol โดยไม่มีการเลือก calibrator จาก test

| โมเดล | Fit/context (แถว) | ROC-AUC ↑ | AP ↑ | Log loss ↓ | Brier score ↓ |
|---|---:|---:|---:|---:|---:|
| TabPFN V2 | 1,000 | 0.764451 | 0.511527 | 0.441931 | 0.139193 |
| TabPFN-3.5 | 1,000 | 0.772835 | 0.525400 | 0.434855 | 0.136513 |
| CatBoost comparator | 1,000 | 0.755604 | 0.495981 | 0.448645 | 0.141974 |
| TabPFN-3.5 | 4,000 | 0.781629 | 0.536987 | 0.432689 | 0.136405 |
| CatBoost comparator | 4,000 | 0.766467 | 0.517758 | 0.442382 | 0.139899 |

ROC-AUC/AP สรุปคุณภาพการจัดอันดับ ส่วน log loss/Brier ประเมิน probability predictions; ลูกศรระบุทิศทางที่ดีกว่า ROC-AUC 0.781629 ไม่ได้หมายถึง accuracy 78.1629% ดู [คำศัพท์](TERMINOLOGY_TH.md)

ผลของ TabPFN-3.5 ดีกว่า CatBoost comparator ตามทั้งสี่ metrics ในคู่ที่มี fit/context เท่ากัน ข้อนี้เป็นการเปรียบเทียบ **configurations ที่ทดลองจริง** ไม่ได้พิสูจน์ความได้เปรียบทุก dataset หรือทุก tuning budget และยังไม่มี paired uncertainty analysis ที่เพียงพอให้สรุป statistical significance ของ auxiliary comparison นี้

แหล่งผลใน Git:

- [TabPFN V2 และ CatBoost 1,000 แถว](../reports/v1/test_results.json): ใช้ records `aux_tabpfn_v2` และ `aux_catboost_1000` ที่ไม่มี suffix `__raw`
- [TabPFN-3.5 / 1,000 แถว](../reports/v1/tabpfn_v3_5_results.json): ใช้ record `aux_tabpfn_v3.5`; verification ระบุ version `v3.5`, trial status `ok`, test IDs/order ตรงกัน และ probability ทุกค่าอยู่ในช่วง [0, 1]
- [TabPFN-3.5 และ CatBoost 4,000 แถว](../reports/v2/tabpfn_4000_results.json): ใช้ `exposed_test_reference` ของ trials `tabpfn_3_5_4000` และ `catboost_4000` ที่ status `ok`
- [รายงานรอบ V1](../reports/v1/REPORT_TH.md), [รายงานรอบ V2](../reports/v2/REPORT_TH.md), [V1 export manifest](../reports/v1/export_manifest.json), [V2 export manifest](../reports/v2/export_manifest.json)

SHA-256 ของ result files ตรงกับ export manifests และ bytes ตรงกับไฟล์ที่ commit อยู่ใน Git ข้อนี้ยืนยัน provenance ของ artifact ที่อ่าน ไม่ใช่ independent replication ของการฝึกโมเดล

## การควบคุมขนาดข้อมูลและ settings

- ในแต่ละคู่ TabPFN/CatBoost ใช้ fit/context rows เดียวกัน และใช้ validation 400, calibration 600, reference test 4,500 แถวเดิม
- ใช้ 23 predictors ต้นฉบับเหมือนกัน โดยแปลง categorical inputs ตามที่แต่ละ library ต้องการ ไม่ใช้ ID/target เป็น predictor
- TabPFN ใช้ local CPU, 2 ensemble estimators, ระบุ categorical feature indices และเปิด memory-saving mode
- CatBoost comparator ใช้ depth 6, 600 iterations, learning rate 0.05 และ L2 leaf regularization 5 ไม่ทำ hyperparameter search เพิ่มใน auxiliary trials
- เลือก calibration จาก identity, sigmoid-on-logit และ isotonic โดย group CV บน calibration partition ที่แยกจาก fit; TabPFN ที่สรุปเลือก identity ส่วน CatBoost comparator เลือก sigmoid
- Context 4,000 มี context 1,000 เดิมรวมอยู่ภายใน และรักษาการแยก exact-vector groups ระหว่าง partitions; borrower identity และ near-duplicate relations ยังไม่ยืนยัน

Main pipeline ใช้ fit 16,500 แถวและ 68 engineered features พร้อม model-selection history ต่างจาก auxiliary trials จึงไม่ใช้ตารางนี้จัดอันดับ main pipeline กับ TabPFN ว่าเป็นการเปรียบเทียบขนาดข้อมูล/features/tuning budget เท่ากัน

## Runtime และสถานะการรัน

เวลาที่บันทึกสำหรับ 4,000 แถว:

| โมเดล | Fit/preprocessing/calibration (วินาที) | Test batch inference (วินาที) |
|---|---:|---:|
| TabPFN-3.5 | 262.92 | 970.49 |
| CatBoost comparator | 78.25 | 0.07 |

เวลาเป็น wall-clock ของรอบนั้น มี CPU contention และการทำงานคนละช่วง จึงไม่ใช่ controlled speed benchmark เวลา fit ของ TabPFN ในตารางนี้รวม context/preprocessing และ calibration ไม่ใช่ foundation-model pretraining

Historical shell session ของ trial 4,000 คืน PowerShell exit 1 พร้อม CPU-speed warning แต่ trials มี predictions/result artifacts ครบและมีการตรวจ IDs/probabilities/metrics จาก CSV ตาม [รายงาน V2](../reports/v2/REPORT_TH.md) จึงต้องแยก shell status ออกจากผล model trial ที่ตรวจแล้ว เอกสารนี้ตรวจ published JSON/manifests ไม่ได้รัน shell probe หรือ numerical replication ซ้ำ

## ขอบเขตของผล

TabPFN-3.5 / 1,000 แถวเป็น auxiliary addendum ที่ประกาศไว้ก่อน แต่เข้าถึง weights ได้หลังประเมิน main test แล้ว; การทดลอง 4,000 แถวใช้ reference test ที่เปิดดูแล้ว ผลทั้งหมดจึงเป็น **descriptive reference results** บน cohort เดิม ไม่ใช่ independent temporal validation หรือผลยืนยันบนธนาคารไทย

การเพิ่ม context ให้ผล ROC-AUC 0.772835 → 0.781629 และ log loss 0.434855 → 0.432689 เป็นสิ่งที่สังเกตได้จากสอง settings ที่ทดลอง ยังไม่มีหลาย random contexts/seeds หรือ cohorts ใหม่ที่ยืนยันว่าการเพิ่ม context จะช่วยสม่ำเสมอ โมเดลหลักไม่ได้ถูกเปลี่ยนจาก auxiliary test results

## ทำซ้ำการทดลองเดิม

Dependencies ของ historical environment อยู่ใน `requirements.lock.txt`; core environment อย่างเดียวไม่ได้ติดตั้ง TabPFN ต้องมีสิทธิ์เข้าถึง weights และ local token ตาม `.env.example` ก่อนรัน trial ผลโมเดล/weights/raw data/local outputs ไม่รวมใน Git

Frozen experiment sources:

- [TabPFN 1,000 แถว](../scripts/tabpfn_cpu_trial.py): `--version v3.5` สำหรับรุ่น 3.5; ใช้ subset/protocol เดิม
- [ประเมิน addendum 1,000 แถว](../scripts/evaluate_tabpfn_addendum.py)
- [TabPFN/CatBoost 4,000 แถว](../scripts/tabpfn_learning_curve.py): ต้องเตรียม protocol และ subset ของรอบ V2 ก่อน

Scripts เหล่านี้พึ่ง local artifacts ของ historical experiments และปฏิเสธการเขียนทับ completed trials จึงไม่ใช่คำสั่งที่รันได้ทันทีใน fresh clone ที่มีเพียง JSON reports การเปลี่ยน context/settings เพื่อทดลองใหม่ต้องใช้ output directory และ protocol ใหม่ แยกจากผลที่รายงานไว้
