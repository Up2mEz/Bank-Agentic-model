# Bank Agentic Model — credit-default research

งานวิจัยภาษาไทยที่ตรวจย้อนกลับได้: ตรวจ dataset, เปรียบเทียบโมเดล, วิเคราะห์สิ่งที่ทำนายพลาด และใช้ agent ช่วยรีวิวหลักฐาน/โค้ด โครงการนี้ทดลองกับ UCI/Kaggle credit-card cohort ไต้หวันปี 2005 ยังไม่มีข้อมูลธนาคารไทยหรือ independent out-of-time validation

**สถานะ 5 ตุลาคม 2026:** candidate V3 ที่เลือก depth/iterations ภายใน nested group folds ให้ OOF log loss **0.425785** เทียบ V2 **0.427110** และ AUC **0.785682** เทียบ **0.784847** แต่มีหนึ่ง outer fold ที่แย่ลง จึง **คง V2** ตาม gate ที่กำหนดก่อนรัน ไม่เปลี่ยนเกณฑ์ตามผลที่เห็น

- [ผลรอบสามและ failure analysis ภาษาไทย](reports/v3/REPORT_TH.md)
- [Literature review เพิ่มเติมและ data exploration](research/ITERATION_3_RESEARCH_TH.md)
- [Graph ML สำหรับ fraud และขอบเขต event ในธนาคาร](research/GRAPH_FRAUD_AND_BANK_EVENT_SCOPE_TH.md) — audit ข้อมูลเดิมและตรวจนิยาม labels ของ graph benchmarks
- [Protocol](reports/v3/protocol.json), [คำตัดสิน gate](reports/v3/selection.json), [verification](reports/v3/verification.json)
- [ผลรอบสอง](reports/v2/REPORT_TH.md) และ [ผลรอบแรก](reports/v1/REPORT_TH.md)
- [การตรวจข้อเสนอ agy](research/AGY_V3_REVIEW_DISPOSITION_TH.md), [โครงสร้างโค้ด](docs/ARCHITECTURE.md), [data provenance](data/README.md)

โมเดล V2 ที่คงไว้เป็น CatBoost trajectory depth 6 (75%) + LightGBM 15 leaves (25%) ผล **test เดิมที่เคยเปิดแล้ว**: AUC 0.786933, log loss 0.426866, Brier 0.134399 ตัวเลขนี้เป็น descriptive historical reference; ไม่ใช้ยืนยันว่าเหมาะกับธนาคารไทย, เป็นโมเดลที่ดีที่สุดทั่วไป หรือพร้อมตัดสินสินเชื่อจริง

## สิ่งที่เพิ่มและตรวจจริง

สำรวจ original fit 16,500 แถวเพิ่ม พบว่ากลุ่มไม่มี PAY code เป็นบวกยังมี default labels 11.83%; ในกลุ่มนี้ ยอดชำระเป็นศูนย์อย่างน้อย 3 snapshots มีอัตรา 18.43% เทียบ 10.75% เมื่อมีน้อยกว่า 3 snapshots เป็น association ที่วัดได้ ไม่ใช่คำอธิบายสาเหตุหรือความหมายที่เดาของ category codes

แยกโค้ดเป็น `src/creditrisk` พร้อม schema/probability checks, categorical adapters, nested fitting และ scoring ที่รักษา row/index order ตรวจ feature migration ทุกเซลล์ของจริง 30,000 แถวตรงกับ V2 และตรวจ save/reload/batch/single-row parity เก็บ historical scripts เดิมไว้เพราะมี source hashes ใน frozen manifests

agy ช่วย method/code review ผ่าน native CLI ใน plan mode โดยอ่านวัสดุที่ส่งให้เท่านั้น ข้อเสนอถูกตรวจซ้ำกับ source/tests/ผลจริง ไม่อ้างว่า agent ตรวจ raw data อิสระ และไม่มีการเรียก Gemini CLI

## เริ่มใช้งานและทำซ้ำ

ใช้ Python 3.12; ตัวอย่าง Windows PowerShell:

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

Run ใน checkout ที่ `outputs/experiment_v3` ยังไม่มี completed artifacts; commands ป้องกันการเขียนทับ protocol, selection และ reference evaluation การ rerun บนแถวเดิมไม่สร้าง independent test ใหม่

หลัง finalize แล้ว ใช้ pipeline ที่ gate เลือก:

```powershell
.venv\Scripts\python.exe -m creditrisk.cli score examples/borrower_input.csv --scores outputs/example_scores.csv
```

Input ต้องเป็น 23 original predictors ไม่มี ID/target; ตัวอย่างเป็นข้อมูลสังเคราะห์ Output เป็น probability ของ **dataset label** พร้อมแถวต้นทาง ไม่ออกคำสั่งอนุมัติ/ปฏิเสธสินเชื่อ โหลดเฉพาะ joblib ที่สร้างเองหรือเชื่อถือได้

บน Linux/macOS ใช้ `.venv/bin/python` แทน `.venv\Scripts\python.exe`; package ไม่ hardcode host path

## Tech stack และการตรวจโค้ด

| ส่วน | เครื่องมือที่ใช้จริง |
|---|---|
| Data / deterministic features | Python 3.12, pandas, NumPy |
| Main models | CatBoost, LightGBM บน CPU |
| Splits / calibration / metrics | scikit-learn; exact-vector group folds, identity/sigmoid-on-logit/isotonic |
| Artifacts / plots | versioned joblib pipeline, JSON/CSV/SHA-256, Matplotlib |
| Quality / reproducibility | pytest, Ruff, GitHub Actions, core/dev version pins |
| Agent review | native agy; LLM ไม่อยู่ใน numerical prediction path |

```powershell
.venv\Scripts\ruff.exe check src tests tools
.venv\Scripts\ruff.exe format --check src tests tools
.venv\Scripts\python.exe -m pytest -q
```

[CONTRIBUTING](CONTRIBUTING.md) อธิบาย test boundaries และการรักษา frozen experiments ผล TabPFN/EBM/Logistic ในรอบก่อนเก็บไว้ใน reports; full legacy/TabPFN environment อยู่ใน `requirements.lock.txt` การทำซ้ำ TabPFN-3.5 ต้องมีสิทธิ์ใช้ weights/token และใส่ key เฉพาะ local `.env` ตาม `.env.example` main experiment รอบนี้ไม่ใช้ token

## Dataset และขอบเขตหลักฐาน

I-Cheng Yeh (2009), [UCI Default of Credit Card Clients](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients), [DOI 10.24432/C55S3H](https://doi.org/10.24432/C55S3H), CC BY 4.0; [Kaggle mirror](https://www.kaggle.com/datasets/uciml/default-of-credit-card-clients-dataset) เทียบทั้ง UCI CSV และต้นฉบับ XLS แล้วตรงทุกเซลล์ ดู [audit](reports/v1/data_audit.json)

Raw data, model weights, `.env` และ local agent logs ถูก exclude จาก Git Public reports รวม derived split/group/OOF data เพื่อทำซ้ำ paired experiment และรักษาการอ้าง UCI ต้นทาง metadata mirror ระบุ CC0 แต่ไม่ได้ใช้อนุมานสิทธิ์ relicense ต้นฉบับ

Target header ระบุ next month แต่ exact default threshold ยังไม่ยืนยัน จึงไม่เท่ากับ regulatory 12-month PD; ไม่มี LGD/EAD/ECL model, rejected applicants หรือ genuine time holdout ข้อมูลที่มีไม่พออ้างสาเหตุของ default/ความเป็นธรรมของ underwriting ต้องใช้ labeled cohort ใหม่ที่ตรง population/target หลัง freeze pipeline จึงประเมิน independent validation ได้

งานวิจัยเบื้องต้น: [approach/tech stack/BOT framework](research/CREDIT_RISK_REVIEW_TH.md), [dataset due diligence](research/DATASET_DUE_DILIGENCE_TH.md), [reference audit](research/REFERENCE_AUDIT.md)
