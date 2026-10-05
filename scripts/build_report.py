"""Render Thai report from measured artifacts; no invented scores."""
import json
import platform
from pathlib import Path
from credit_experiment import OUT,ROOT,read_json

def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |',*['| '+' | '.join(map(str,r))+' |' for r in rows]])

def main():
    audit=read_json(OUT/'data_audit.json');protocol=read_json(OUT/'protocol.json');selection=read_json(OUT/'selection.json');result=read_json(OUT/'test_results.json')
    extra=OUT/'tabpfn_v3_5_results.json'
    if extra.exists():result['results'].extend(read_json(extra)['results'])
    main_rows=[r for r in result['results'] if r['track']=='main' and not r['model'].endswith('__raw')]
    aux_rows=[r for r in result['results'] if r['track']!='main' and not r['model'].endswith('__raw')]
    champion=result['champion_preselected'];chosen=next(r for r in main_rows if r['model']==champion)
    baseline=next(r for r in main_rows if r['model']=='logistic');ci=result['champion_bootstrap_95_intervals']
    main_table=table(['โมเดล','ROC-AUC ↑','Average precision ↑','Log loss ↓','Brier ↓'],[[r['model'],*[f'{r[k]:.5f}' for k in ['roc_auc','average_precision','log_loss','brier']]] for r in main_rows])
    aux_table=table(['โมเดลข้อมูลย่อย','ROC-AUC ↑','AP ↑','Log loss ↓','Brier ↓'],[[r['model'],*[f'{r[k]:.5f}' for k in ['roc_auc','average_precision','log_loss','brier']]] for r in aux_rows])
    split_table=table(['ชุด','แถว','เหตุการณ์','สัดส่วนเหตุการณ์'],[[part,v['rows'],v['events'],f'{v["prevalence"]:.3%}'] for part,v in protocol['splits'].items()])
    train_table=table(['โมเดล','calibrator','เวลา fit/search/calibration (วินาที)','ทำนาย test batch (วินาที)','validation calibrated log loss'],[[r['model'],r['calibration'],f'{r["fit_calibration_seconds"]:.1f}',f'{r["test_batch_prediction_seconds"]:.2f}',f'{r["validation_calibrated"]["log_loss"]:.5f}'] for r in selection['candidates']])
    aux_trials=[]
    for filename in ['tabpfn_trial.json','tabpfn_v3_5_trial.json']:
        p=OUT/filename
        if p.exists():aux_trials.append(read_json(p))
    tab_status='; '.join(f"{trial['actual_version']}: "+', '.join(f"{r['name']}={r['status']}" for r in trial['trials']) for trial in aux_trials)
    aux_time_table=table(['โมเดลข้อมูลย่อย','calibrator','fit/preprocessing/calibration (วินาที)','ทำนาย test batch (วินาที)'],[[f"{r['name']} {r['version']}",r.get('calibration','—'),f"{r['fit_calibration_seconds']:.2f}" if 'fit_calibration_seconds' in r else '—',f"{r['test_batch_prediction_seconds']:.2f}" if 'test_batch_prediction_seconds' in r else '—'] for trial in aux_trials for r in trial['trials']])
    text=f'''# ผลทดลอง credit risk รอบแรก

วันที่ 4 ตุลาคม 2026 — `experiment_v1` — งานวิจัยที่ไม่ใช่เชิงพาณิชย์

## ผลที่ควรเข้าใจก่อน

**โมเดลที่เลือกไว้ก่อนดูผล test คือ `{champion}`** ใช้ validation log loss หลัง calibration เป็นเกณฑ์ ไม่เปลี่ยน champion ตามผล test โมเดลนี้ทำนาย label ของลูกหนี้บัตรเครดิตใน UCI cohort ได้ตามตัวเลขด้านล่าง ยังไม่ใช่โมเดลที่พิสูจน์แล้วสำหรับผู้สมัครใหม่ SME หรือธนาคารไทย

เทียบ Logistic บน test เดียวกัน: AUC ต่าง {chosen['roc_auc']-baseline['roc_auc']:+.5f}; log loss ต่าง {chosen['log_loss']-baseline['log_loss']:+.5f} (ค่าติดลบสำหรับ log loss หมายถึงดีขึ้น) เป็นผลของการทดลองขอบเขตนี้ ไม่ใช่การจัดอันดับโมเดลทั่วโลก

## 1. ตรวจข้อมูลจริงก่อนฝึก

- โหลดต้นฉบับ XLS และ CSV ที่ UCI API ระบุ พร้อม Kaggle CSV และ metadata; เทียบทุกค่าหลังจับคู่ชื่อคอลัมน์ พบต่างกัน **{audit['source_value_mismatches']} เซลล์สำหรับ CSV และ {audit['original_xls_value_mismatches']} เซลล์สำหรับ XLS** ชนิดข้อมูลบางคอลัมน์ต่างกัน แต่ค่าตัวเลขตรงกัน
- {audit['rows']:,} แถว, {audit['predictors']} predictors, ID และ target แยกออก; พบ label 1 จำนวน {audit['labels']['1']:,} ({audit['event_rate']:.2%}) และ null {audit['missing_cells']} เซลล์
- เมื่อเอา ID/target ออก พบแถวซ้ำส่วนเกิน {audit['identical_predictor_extra_rows']} แถว และ {audit['conflicting_label_groups']} กลุ่มมี predictor เหมือนกันแต่ label ต่างกัน เก็บทั้งหมด ไม่เดาว่าคนเดียวกัน ไม่ลบหรือแก้ label
- พบ EDUCATION 0/5/6, MARRIAGE 0 และ repayment -2/0 ที่ dictionary ที่ตรวจอธิบายไม่ครบ เก็บเป็นหมวดหมู่เฉพาะ ไม่ remap ตามความจำ
- ค่า BILL_AMT ติดลบยังเก็บไว้; ไม่สรุปว่าเป็น error จากเครื่องหมายเพียงอย่างเดียว รายละเอียด domains, ranges, negative counts และ SHA-256 อยู่ใน `data_audit.json`
- Kaggle metadata ระบุ CC0 ขณะที่ต้นทาง UCI ระบุ CC BY 4.0 จึงรักษาการอ้างต้นทางและผู้สร้าง ไม่อนุมานว่าผู้ทำ mirror มีสิทธิ์เปลี่ยนเป็น public domain

ที่มาและการอ้างข้อมูล: I-Cheng Yeh (2009), *Default of Credit Card Clients*, UCI, DOI [10.24432/C55S3H](https://doi.org/10.24432/C55S3H), [ต้นทางและ CC BY 4.0](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients), [Kaggle mirror](https://www.kaggle.com/datasets/uciml/default-of-credit-card-clients-dataset).

## 2. แยกข้อมูลตามหน้าที่

{split_table}

จัดกลุ่ม predictor ที่เหมือนกันก่อนแบ่งด้วย StratifiedGroupKFold 20 folds แล้วแบ่ง folds เป็นสี่หน้าที่ตาม protocol ไม่มีกลุ่มดังกล่าวข้าม partition การแบ่งนี้ลดการปนของ exact duplicate vectors แต่ไม่ได้รับรอง borrower identity หรือ near-duplicate independence

- Fit: เรียนรู้พารามิเตอร์ของโมเดล
- Validation: เลือก setting ของโมเดล แล้วเลือก pipeline หลัง calibration
- Calibration: เลือก identity/sigmoid/isotonic จาก out-of-fold log loss ภายในชุดนี้ และ fit calibrator ที่เลือกบนชุด calibration ทั้งชุด; base model คงเดิม
- Test: ประเมินโมเดลที่ล็อกแล้ว; ไม่ใช้เลือก feature, hyperparameter หรือ champion ใหม่

## 3. สิ่งที่ทดลองจริง

Logistic C=0.1/1/10; CatBoost depth=4/6/8, 600 trees; LightGBM leaves=15/31/63, 500 trees; EBM interactions=0/5, max rounds=1500, outer bags=4 ใช้ 4 threads และ seed={protocol['seed']} ไม่เปิด class weighting/SMOTE

มี CatBoost อีก candidate เพิ่ม payment-to-positive-bill ratios 6 เดือน, flags สำหรับบิลที่ไม่เป็นบวก, recent bill utilization และผลต่างบิลเดือน 1 กับ 6 โดย denominator ที่ไม่เป็นบวกให้ ratio เป็น missing พร้อม flag; ใช้ setting ที่เลือกจาก raw CatBoost เป็น ablation ที่ประกาศก่อนดู test

ทุกโมเดลใช้ข้อมูล fit เดียวกันใน main track แต่จำนวน setting และโครงสร้าง computation ต่างกัน นี่เป็น bounded baseline experiment ไม่ใช่การค้นหาเท่ากันด้วย compute budget หรือ exhaustive SOTA benchmark

{train_table}

เวลาที่รายงานรวมการค้นหา/ฝึก/calibration ตาม pipeline มีการรัน CPU jobs พร้อมกัน จึงไม่ใช่ latency benchmark ในสภาวะเครื่องว่าง

## 4. ผลบน test ที่ไม่ใช้เลือกโมเดล

Test {result['n_test']:,} แถว, label 1 {result['test_events']:,}, prevalence {result['test_prevalence']:.3%}

{main_table}

อ่าน metric:

- **ROC-AUC**: จัดอันดับความเสี่ยงได้ดีเพียงใด; 0.5 เป็นระดับสุ่มสำหรับการจัดอันดับ ไม่ใช่ accuracy
- **Average precision**: คุณภาพการจัดอันดับคลาสผิดนัด; ต้องอ่านคู่ prevalence นี้ ไม่เรียกเป็น trapezoidal PR-AUC
- **Log loss**: ลงโทษ probability ที่ผิด โดยเฉพาะมั่นใจผิด; ต่ำดีกว่า
- **Brier**: ค่าเฉลี่ยกำลังสองของความคลาดเคลื่อน probability; ต่ำดีกว่า แต่รวมทั้ง calibration/discrimination จึงไม่ใช้แทน calibration ทั้งหมด

Calibration ของ champion บน test: intercept={chosen['calibration_intercept']:.4f}, slope={chosen['calibration_slope']:.4f} ค่าที่สอดคล้อง ideal model คือ 0 และ 1 ตามลำดับ เป็น descriptive diagnostic ไม่ได้นำกลับไปปรับโมเดลบน test

หากขั้นเลือก calibrator ได้ `identity` หมายถึงคง probability เดิม เพราะตัวเลือกนี้มี out-of-fold log loss ต่ำสุดใน calibration partition ไม่ได้แปลว่าพิสูจน์ perfect calibration แล้ว

95% group-bootstrap intervals (300 replicates) ของ champion:

- AUC [{ci['roc_auc'][0]:.5f}, {ci['roc_auc'][1]:.5f}]
- Log loss [{ci['log_loss'][0]:.5f}, {ci['log_loss'][1]:.5f}]
- AUC ต่างจาก Logistic [{ci['auc_minus_logistic'][0]:+.5f}, {ci['auc_minus_logistic'][1]:+.5f}]
- Log loss ต่างจาก Logistic [{ci['log_loss_minus_logistic'][0]:+.5f}, {ci['log_loss_minus_logistic'][1]:+.5f}]

Intervals เหล่านี้อธิบายความไม่แน่นอนภายใน cohort ภายใต้หน่วย resampling ที่ระบุ ไม่ใช่ temporal stability, multiplicity-adjusted discovery หรือการรับรอง performance ของ cohort อนาคต

![ROC, precision-recall และ calibration](evaluation.png)

## 5. TabPFN: แยกขนาดข้อมูลให้ชัด

สถานะที่วัดจริง: {tab_status}

ใช้ fit 1,000 แถว validation 400 และ calibration 600 แถวจาก subset ที่ล็อกก่อนทดลอง; ทำนาย test 4,500 แถวเดียวกับ main track มี CatBoost fit 1,000 แถวเหมือนกันเป็น comparator ไม่เอาผลนี้ไปอ้างว่า TabPFN แพ้/ชนะโมเดลที่ได้ข้อมูลฝึก 16,500 แถวอย่างเท่าเทียม

{aux_table}

{aux_time_table}

TabPFN ใช้ local CPU inference, 2 ensemble estimators และระบุ categorical features รุ่นจริง เวลาและ calibrator ดู `tabpfn*_trial.json` รุ่น 3.5 เคยติด authentication/license gate ก่อนผู้ใช้มี key ดูประวัติใน diagnostics; ห้ามเรียกผล V2 ว่า V3.5

เวลา fit ของ TabPFN ในตารางรวมการเตรียม context/preprocessing และการเลือก calibration ไม่ใช่การฝึกน้ำหนัก foundation model ใหม่ เวลารันแต่ละ trial เกิดคนละช่วงและอาจมีงาน CPU อื่น จึงไม่ใช้เป็น controlled speed benchmark รุ่น 3.5 เป็น auxiliary addendum ที่ประกาศไว้ก่อน แต่เข้าถึงได้หลังประเมิน main test แล้ว ไม่เปลี่ยน champion หรือตั้งค่าจากผล test นี้

## 6. ขอบเขตและสิ่งที่ยังพิสูจน์ไม่ได้

- Header ยืนยัน next-month target; ยังไม่มีหลักฐาน exact default threshold ให้เรียก 90+ DPD หรือ regulatory 12-month PD
- ข้อมูล Taiwan ปี 2005 เป็น cohort เดียว ไม่มี genuine out-of-time test หรือ Thai portfolio validation
- มี demographic predictors ใน benchmark ไม่ใช่การอนุมัติให้ใช้งานจริง; `subgroups.csv` แสดงจำนวน/events และ performance แยกกลุ่ม แต่กลุ่มเล็กและการเลือก threshold/policy ยังต้องศึกษา
- ไม่ประเมิน rejected applicants, LGD/EAD, expected monetary loss หรือกำไรจาก approval policy เพราะไม่มีข้อมูลและต้นทุนที่รองรับ
- ไม่ได้เพิ่ม calibration จาก test หรือปรับ ensemble หลังเห็นผล
- ขั้นต่อไปที่มีความหมายคือข้อมูลหลาย cohort ของพอร์ตเป้าหมายและ labels ที่ mature แล้ว ไม่ใช่เพิ่มความซับซ้อนเพื่อชดเชยข้อมูลที่ขาด

## 7. ใช้โมเดลทดลองและตรวจย้อนกลับ

`models/` เก็บ model + calibrator + schema ของทุก main candidate; CatBoost มี native `.cbm` เพิ่มเติม โหลดเฉพาะ joblib ที่โครงการสร้างและเชื่อถือ

```powershell
.venv\\Scripts\\python.exe scripts\\score.py outputs\\experiment_v1\\demo_input.csv
```

Input ต้องเป็น 23 predictors ไม่มี ID/target; output ระบุ raw probability, calibrated probability, model version และวัตถุประสงค์ ไม่มีคำสั่งอนุมัติ/ปฏิเสธสินเชื่อ

การตรวจหลังรันอยู่ใน `verification.json`: cross-source equality, split/group separation, artifact reload, probability domain และ demo prediction parity รายละเอียดข้อมูล/วิธี/ผลดิบอยู่ใน `data_audit.json`, `protocol.json`, `splits.csv`, `selection.json`, `metrics.csv`, `test_results.json`, logs และ `requirements.lock.txt` ที่ root

Herdr/agy/Gemini และการคัดข้ออ้างจาก agent อธิบายใน [execution log](../../research/EXECUTION_AND_AGENT_REVIEW_TH.md) agent ไม่ได้เป็นผู้ฝึกหรือคำนวณตัวเลขในตารางนี้
'''
    (OUT/'REPORT_TH.md').write_text(text,encoding='utf-8')
    print('Wrote',OUT/'REPORT_TH.md')

if __name__=='__main__':main()
