# Bank Agentic Model — Credit Risk Research

โครงการวิจัยการทำนาย **การผิดนัดชำระหนี้ (credit default)** จากข้อมูลผู้ถือบัตรเครดิต พร้อมการเปรียบเทียบโมเดล วิเคราะห์ข้อผิดพลาด (failure analysis) และตรวจสอบหลักฐานผลทดลอง ใช้ UCI/Kaggle Default of Credit Card Clients ซึ่งเป็นข้อมูลไต้หวันปี 2005; ยังไม่มีผล validation บนข้อมูลธนาคารไทย

**สถานะ 5 ตุลาคม 2026:** มีผล TabPFN-3.5 ทั้ง context 1,000 และ 4,000 แถว ส่วนโมเดลหลักที่เลือกไว้ยังเป็น **V2: CatBoost 75% + LightGBM 25%** เพราะ candidate ในรอบ V3 ไม่ผ่านเกณฑ์เปลี่ยนโมเดล (promotion gate)

รอบทดลอง V1/V2/V3 เป็นลำดับการพัฒนาโครงการ ส่วน TabPFN V2 และ TabPFN-3.5 เป็นรุ่นของโมเดล จึงใช้คำว่า “รอบทดลอง” และ “รุ่นโมเดล” แยกกัน

เริ่มอ่าน: [ผล TabPFN](#ผล-tabpfn) · [ผลโมเดลหลัก](#ผลโมเดลหลัก-v2-และ-v3) · [วิธีรัน](#ติดตั้งและทำซ้ำ) · [คำศัพท์](docs/TERMINOLOGY_TH.md) · [ขอบเขต fraud และงานธนาคาร](research/GRAPH_FRAUD_AND_BANK_EVENT_SCOPE_TH.md)

## ผล TabPFN

**Context** คือแถวที่มี features และ labels ซึ่ง TabPFN ใช้ประกอบการทำนาย การ `fit` ในการทดลองนี้เตรียม context/preprocessing ไม่ได้ฝึกน้ำหนัก foundation model ใหม่

ตารางแสดงผลประเมินบน **ชุดทดสอบอ้างอิง (reference test) 4,500 แถวชุดเดียวกัน** ซึ่งเคยนำผลมาวิเคราะห์แล้ว เลือก calibrator ด้วย group CV ใน calibration partition 600 แถว ไม่ใช้ test เลือก calibrator

ทุกคู่ที่ขนาดข้อมูลเท่ากันใช้แถว fit/context เดียวกัน, validation 400 แถว และ 23 predictors ต้นฉบับ ใช้ CPU; TabPFN มี 2 ensemble estimators ส่วน CatBoost comparator ใช้ parameters ที่กำหนดไว้ล่วงหน้า

| โมเดล | Fit/context (แถว) | ROC-AUC ↑ | AP ↑ | Log loss ↓ | Brier score ↓ |
|---|---:|---:|---:|---:|---:|
| TabPFN V2 | 1,000 | 0.764451 | 0.511527 | 0.441931 | 0.139193 |
| TabPFN-3.5 | 1,000 | 0.772835 | 0.525400 | 0.434855 | 0.136513 |
| CatBoost comparator | 1,000 | 0.755604 | 0.495981 | 0.448645 | 0.141974 |
| TabPFN-3.5 | 4,000 | 0.781629 | 0.536987 | 0.432689 | 0.136405 |
| CatBoost comparator | 4,000 | 0.766467 | 0.517758 | 0.442382 | 0.139899 |

**ผลที่สังเกตได้:** TabPFN-3.5 มี ROC-AUC/AP สูงกว่าและ log loss/Brier ต่ำกว่า CatBoost comparator ในทั้งสองคู่ เมื่อเพิ่ม context เป็น 4,000 แถว ROC-AUC ของ TabPFN-3.5 เพิ่มจาก 0.772835 เป็น 0.781629 ข้อสรุปนี้จำกัดอยู่ที่ configurations และ reference test ที่ใช้ ไม่ใช่การยืนยันว่า TabPFN ดีกว่า CatBoost ทุกกรณี

การทดลอง TabPFN เป็น **การทดลองเพิ่มเติม (auxiliary experiment)** ไม่ใช้เปลี่ยนโมเดลหลักจากผล test การเปรียบเทียบกับ main pipeline มีขนาดข้อมูลและ features ต่างกัน เพราะ main pipeline ใช้ fit 16,500 แถวและ 68 engineered features

Context 4,000 แถวรวม context 1,000 เดิมอยู่ภายใน ผลทั้งสองจึงเกี่ยวข้องกัน ไม่ใช่การทดลองซ้ำแบบอิสระสองชุด (independent replications)

แหล่งตัวเลขใน Git: [TabPFN-3.5 / 1,000 แถว](reports/v1/tabpfn_v3_5_results.json), [TabPFN V2 และ CatBoost / 1,000 แถว](reports/v1/test_results.json), [ทั้งสองโมเดล / 4,000 แถว](reports/v2/tabpfn_4000_results.json) รายละเอียด settings, calibration และ runtime อยู่ใน [รายงาน TabPFN](docs/TABPFN_RESULTS_TH.md)

## ผลโมเดลหลัก V2 และ V3

V2 ใช้ CatBoost trajectory depth 6 ร่วมกับ LightGBM 15 leaves โดยให้น้ำหนัก 75% และ 25% ตามลำดับ รอบ V3 ทดลอง **nested cross-validation** เพื่อเลือก depth และจำนวน iterations ภายใน inner folds แล้วประเมินใน outer folds

ตารางนี้เป็น **OOF (out-of-fold) predictions** ของ fit partition 16,500 แถว บน outer folds เดียวกัน:

| Pipeline | ROC-AUC ↑ | AP ↑ | Log loss ↓ | Brier score ↓ | ผลการเลือก |
|---|---:|---:|---:|---:|---|
| V2 baseline | 0.784847 | 0.553305 | 0.427110 | 0.134286 | คงไว้เป็นโมเดลหลัก |
| V3 candidate | 0.785682 | 0.557387 | 0.425785 | 0.133691 | ไม่ผ่าน promotion gate |

V3 ให้ pooled log loss ดีขึ้น แต่หนึ่ง outer fold มี log loss แย่ลง จึงไม่ผ่านเกณฑ์ที่กำหนดก่อนรัน ไม่มีการเปลี่ยน gate ตามผลที่เห็น V2 และข้อมูลชุดนี้ผ่านการเลือกโมเดลมาแล้ว; nested CV รอบใหม่ไม่ทำให้ผลเป็น independent validation

ผล V2 บน **reference test เดิม**: ROC-AUC 0.786933, AP 0.548343, log loss 0.426866 และ Brier score 0.134399 เป็นผลย้อนหลังบน cohort นี้ ยังไม่ยืนยันประสิทธิภาพบนธนาคารไทย

หลักฐาน: [ผล V3 และ failure analysis](reports/v3/REPORT_TH.md), [protocol](reports/v3/protocol.json), [promotion gate](reports/v3/selection.json), [verification](reports/v3/verification.json), [ผล V2](reports/v2/REPORT_TH.md), [ผล V1](reports/v1/REPORT_TH.md)

## Failure analysis และสิ่งที่ตรวจแล้ว

สำรวจ fit partition เพิ่ม พบว่ากลุ่มไม่มี PAY code เป็นบวกยังมี default labels 11.83% ภายในกลุ่มนี้ ผู้ที่มียอดชำระเป็นศูนย์อย่างน้อย 3 monthly snapshots มี default labels 18.43% เทียบกับ 10.75% เมื่อมีน้อยกว่า 3 snapshots เป็นความสัมพันธ์ที่สังเกตได้ (association); ยังไม่ระบุสาเหตุของ default

บน reference test ที่ review capacity 10% โมเดล V2 จัด default events เข้ากลุ่มตรวจได้ 312 ราย ส่วน V3 ได้ 307 ราย แม้ pooled metrics ของ V3 ดีขึ้นบางตัว จึงต้องตรวจ ranking, probability quality และผลในแต่ละกลุ่มแยกกัน ดู [research/EDA รอบสาม](research/ITERATION_3_RESEARCH_TH.md)

โค้ดที่พัฒนาต่ออยู่ใน `src/creditrisk` แยก schema, features, splits, calibration, model selection และ scoring ตรวจแล้วว่า feature calculation ตรงกับ V2 ทุกเซลล์ของข้อมูล 30,000 แถว และผลทำนายหลัง refit/reload ตรงกับหลักฐานเดิม รักษา historical scripts และ reports ไว้ตาม source hashes

agy ช่วย method/code review ผ่าน native CLI ใน plan mode โดยใช้หลักฐานที่ส่งให้ ข้อเสนอผ่านการตรวจซ้ำกับ source, tests และผลจริง ดู [review disposition](research/AGY_V3_REVIEW_DISPOSITION_TH.md) และ [architecture](docs/ARCHITECTURE.md)

## ติดตั้งและทำซ้ำ

ใช้ Python 3.12 รันจาก repository root ตัวอย่าง Windows PowerShell:

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements-core.txt -r requirements-dev.txt -e .
.venv\Scripts\python.exe scripts/fetch_data.py
.venv\Scripts\python.exe tools/verify_input_sources.py
.venv\Scripts\python.exe tools/verify_feature_migration.py
.venv\Scripts\python.exe -m creditrisk.cli prepare
.venv\Scripts\python.exe -m creditrisk.cli cv
.venv\Scripts\python.exe -m creditrisk.cli select
.venv\Scripts\python.exe -m creditrisk.cli finalize
.venv\Scripts\python.exe tools/analyze_v3.py
.venv\Scripts\python.exe tools/build_v3_report.py
```

ใช้ checkout ที่ยังไม่มี completed artifacts ใน `outputs/experiment_v3` คำสั่งป้องกันการเขียนทับ protocol, selection และผลประเมิน การทำซ้ำบนแถวเดิมยังเป็นการตรวจ cohort เดิม

หลัง `finalize` จะมี selected pipeline สำหรับ scoring:

```powershell
.venv\Scripts\python.exe -m creditrisk.cli score examples/borrower_input.csv --scores outputs/example_scores.csv
```

Input ต้องมี 23 predictors ต้นฉบับโดยไม่มี ID/target; example เป็นข้อมูลสังเคราะห์ Output เป็น probability ของ dataset label พร้อม row reference ไฟล์โมเดลไม่รวมใน Git ต้องสร้าง local artifact ก่อนใช้ scoring และโหลดเฉพาะ joblib ที่เชื่อถือได้

บน Linux/macOS ใช้ `.venv/bin/python` แทน `.venv\Scripts\python.exe` รายละเอียดการทำซ้ำ auxiliary TabPFN อยู่ใน [รายงาน TabPFN](docs/TABPFN_RESULTS_TH.md)

## Tech stack และ quality checks

| ส่วนงาน | เครื่องมือที่ใช้ |
|---|---|
| Data และ feature engineering | Python 3.12, pandas, NumPy |
| Main pipeline | CatBoost, LightGBM บน CPU |
| โมเดลอื่นที่เปรียบเทียบในรอบ V1 | EBM, Logistic Regression บน fit partition หลัก |
| Auxiliary models บนข้อมูลย่อย | TabPFN-3.5, TabPFN V2 |
| Cross-validation / calibration / metrics | scikit-learn; group folds, identity, sigmoid-on-logit, isotonic |
| Artifacts และ plots | joblib, JSON/CSV, SHA-256, Matplotlib |
| Tests / lint / CI | pytest, Ruff, GitHub Actions |
| Agent review | native agy; numerical prediction คำนวณด้วย model pipeline |

```powershell
.venv\Scripts\ruff.exe check src tests tools
.venv\Scripts\ruff.exe format --check src tests tools
.venv\Scripts\python.exe -m pytest -q
```

Core dependencies อยู่ใน `requirements-core.txt`; full environment ของ historical experiments และ TabPFN อยู่ใน `requirements.lock.txt` การทำซ้ำ TabPFN-3.5 ต้องมีสิทธิ์เข้าถึง weights/token ใส่ key เฉพาะ local `.env` ตาม `.env.example` Main CatBoost/LightGBM pipeline ใช้ core environment โดยไม่ต้องมี token ดู [CONTRIBUTING](CONTRIBUTING.md) สำหรับขอบเขต tests และ frozen experiments

## Dataset และขอบเขตการใช้ผล

ข้อมูลต้นทาง: I-Cheng Yeh (2009), [UCI Default of Credit Card Clients](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients), [DOI 10.24432/C55S3H](https://doi.org/10.24432/C55S3H), CC BY 4.0 เทียบ [Kaggle mirror](https://www.kaggle.com/datasets/uciml/default-of-credit-card-clients-dataset) กับ UCI CSV และ XLS แล้วค่าตรงทุกเซลล์ ดู [data audit](reports/v1/data_audit.json) และ [data provenance](data/README.md)

Target ระบุ **next-month default payment** แต่ยังไม่ยืนยัน exact default threshold จึงใช้แทน regulatory 12-month PD ไม่ได้ ข้อมูลไม่มี fraud labels/transaction graph, LGD/EAD outcomes, rejected applicants หรือ independent temporal test ต้องใช้ labeled cohort ใหม่ที่ตรง population, target และ prediction time เพื่อประเมินการใช้งานธนาคาร ผลของโมเดลนี้ยังไม่ใช่ผลตรวจ fraud หรือการตัดสินอนุมัติสินเชื่อ

Raw data, model weights, credentials และ local agent logs ไม่รวมใน Git Public reports มี derived split/group/OOF data พร้อม attribution; exact-vector groups หมายถึงแถวที่มี predictors เหมือนกันทุกค่า ไม่ได้ยืนยัน borrower identity Metadata ของ Kaggle mirror ระบุ CC0 แต่โครงการคง attribution/license ต้นทาง UCI

อ่านต่อ: [literature review และ BOT framework](research/CREDIT_RISK_REVIEW_TH.md), [dataset due diligence](research/DATASET_DUE_DILIGENCE_TH.md), [reference audit](research/REFERENCE_AUDIT.md), [Graph ML และขอบเขต event ธนาคาร](research/GRAPH_FRAUD_AND_BANK_EVENT_SCOPE_TH.md), [คำศัพท์ Thai–technical](docs/TERMINOLOGY_TH.md)
