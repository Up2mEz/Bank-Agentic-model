"""Thai research/failure report built only from recorded experiment artifacts."""
import numpy as np
import pandas as pd
from credit_experiment import ROOT,OUT as OLD,read_json
from credit_research_v2 import OUT

def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |',*['| '+' | '.join(map(str,r))+' |' for r in rows]])

def main():
    fa=read_json(ROOT/'outputs/failure_analysis_v1/summary.json');sel=read_json(OUT/'selection.json');reference=read_json(OUT/'reference_results.json');analysis=read_json(OUT/'analysis.json');aux=read_json(OUT/'tabpfn_4000_results.json');followup=read_json(OUT/'failure_followup.json')
    old=fa['partitions']['old_test_reference'];a=old['threshold_0.5'];b=old['validation_recall70_threshold'];slices=pd.read_csv(ROOT/'outputs/failure_analysis_v1/slices.csv');no=slices[(slices.partition=='old_test_reference')&(slices['slice']=='no_positive_pay_code')].iloc[0]
    cvtable=table(['Candidate','Features','OOF AUC ↑','OOF AP ↑','OOF log loss ↓','OOF Brier ↓'],[[n,row['feature_count'],*[f"{row['pooled_oof'][k]:.6f}" for k in ['roc_auc','average_precision','log_loss','brier']]] for n,row in sorted(sel['summaries'].items(),key=lambda item:item[1]['pooled_oof']['log_loss'])])
    configtable=table(['Candidate','Setting'],[[c['name'],str(c['params'])] for c in read_json(OUT/'protocol.json')['candidate_grid']])
    oldmetric=analysis['legacy_v1_metrics'];testrows=[['V1 เดิม: CatBoost behavior',*[f"{oldmetric[k]:.6f}" for k in ['roc_auc','average_precision','log_loss','brier']]]]
    testrows.extend([[r['model']+' ('+r['calibration']+')',*[f"{r[k]:.6f}" for k in ['roc_auc','average_precision','log_loss','brier']]] for r in reference['results'] if r['partition']=='exposed_test'])
    reftable=table(['โมเดลบน exposed test','AUC ↑','AP ↑','Log loss ↓','Brier ↓'],testrows)
    thresholdtable=table(['จุดตัด V1','จับผู้ผิดนัด','พลาดผู้ผิดนัด','non-events ที่ถูกส่งตรวจ','Recall','Precision','สัดส่วนส่งตรวจ'],[[label,row['tp'],row['fn'],row['fp'],f"{row['recall']:.2%}",f"{row['precision']:.2%}",f"{row['flagged_rate']:.2%}"] for label,row in [('0.5',a),(f"{b['threshold']:.4f} (เลือกจาก validation)",b)]])
    failures=pd.read_csv(OUT/'failure_slices_comparison.csv');focus=['no_positive_pay_code','PAY_0=0','PAY_0=1','recent_code_ge_2','zero_payments_3plus','utilization_gt_1']
    failuretable=table(['กลุ่มบน exposed test','แถว','events','V1 log loss','Candidate log loss','Δ log loss'],[[r['slice'],r['rows'],r['events'],f"{r['legacy_log_loss']:.6f}",f"{r['candidate_log_loss']:.6f}",f"{r['log_loss_delta']:+.6f}"] for r in failures.to_dict('records') if r['partition']=='exposed_test' and r['slice'] in focus])
    hard_before=next(r for r in followup['slice_comparison'] if r['slice']=='no_positive_pay_code' and r['model']=='legacy_v1')
    hard_after=next(r for r in followup['slice_comparison'] if r['slice']=='no_positive_pay_code' and r['model']=='candidate')
    curve_table=table(['CV fold ของ selected CatBoost','fixed iterations','minimum iteration (posthoc)','minimum heldout loss','final heldout loss','train final loss'],[[r['fold'],r['fixed_iterations'],r['heldout_min_iteration_posthoc'],f"{r['heldout_min_loss']:.6f}",f"{r['heldout_final_loss']:.6f}",f"{r['train_final_loss']:.6f}"] for r in followup['selected_catboost_curve_diagnostics']])
    cap=pd.read_csv(OUT/'capacity_comparison.csv');capacitytable=table(['Capacity บน exposed test','V1 events captured','Candidate events captured','V1 recall','Candidate recall'],[[f'{capacity:.0%}',int(oldcap.events_captured),int(newcap.events_captured),f'{oldcap.recall:.2%}',f'{newcap.recall:.2%}'] for capacity in [.1,.2,.3,.4,.5] for oldcap in [cap[(cap.partition=='exposed_test')&(cap.model=='legacy_v1_champion')&np.isclose(cap.capacity,capacity)].iloc[0]] for newcap in [cap[(cap.partition=='exposed_test')&(cap.model=='candidate')&np.isclose(cap.capacity,capacity)].iloc[0]]])
    auxrows=[]
    oldaux=read_json(OLD/'test_results.json')['results']+read_json(OLD/'tabpfn_v3_5_results.json')['results']
    for r in oldaux:
        if r['model'] in ['aux_tabpfn_v3.5','aux_catboost_1000']:auxrows.append([r['model'],1000,*[f'{r[k]:.6f}' for k in ['roc_auc','average_precision','log_loss','brier']]])
    for r in aux['trials']:
        if r['status']=='ok':auxrows.append([r['model'],4000,*[f"{r['exposed_test_reference'][k]:.6f}" for k in ['roc_auc','average_precision','log_loss','brier']]])
        else:auxrows.append([r['model'],4000,'FAILED: '+r['exception_type'],'—','—','—'])
    auxtable=table(['Auxiliary model','Fit/context','AUC ↑','AP ↑','Log loss ↓','Brier ↓'],auxrows)
    delta=next(r for r in reference['results'] if r['model']=='candidate_blend' and r['partition']=='exposed_test');ci=analysis['paired_bootstrap_95_difference_intervals']['exposed_test_candidate_minus_legacy_v1'];oofci=analysis['paired_bootstrap_95_difference_intervals']['selected_oof_minus_cv_reference']
    timings=table(['Auxiliary model','fit/preprocessing/calibration วินาที','test batch วินาที'],[[r['model'],f"{r['fit_preprocessing_calibration_seconds']:.2f}",f"{r['test_batch_seconds']:.2f}"] for r in aux['trials'] if r['status']=='ok'])
    text=f'''# ผลวิจัยและ failure analysis รอบสอง

วันที่ 4 ตุลาคม 2026 — `experiment_v2` — งานวิจัยที่ไม่ใช่เชิงพาณิชย์

## ผลที่ควรเข้าใจก่อน

เกณฑ์ยอมรับ development pipeline: **{'ผ่าน' if sel['promotion_gate_passed'] else 'ไม่ผ่าน'}**; pipeline ที่บันทึกเพื่อใช้งานวิจัยคือ `{sel['selected_pipeline']}`

เลือก CatBoost `{sel['best_catboost']}` และ LightGBM `{sel['best_lightgbm']}` จาก group OOF แล้วค้นน้ำหนักบนกริด 5 ค่า ได้ CatBoost weight **{sel['blend_catboost_weight']:.2f}** ลด OOF log loss จาก {sel['reference_oof']['log_loss']:.6f} เป็น {sel['candidate_oof']['log_loss']:.6f} ต่าง {-sel['improvement_oof_log_loss']:+.6f}; fold deltas = {', '.join(f'{v:+.6f}' for v in sel['fold_log_loss_deltas'])}

บน test เดิม Candidate AUC ต่างจาก V1 เดิม {delta['roc_auc']-oldmetric['roc_auc']:+.6f}, log loss ต่าง {delta['log_loss']-oldmetric['log_loss']:+.6f} **test ชุดนี้เปิดแล้วและใช้ failure analysis ก่อนออกแบบรอบสอง จึงเป็น retrospective reference ไม่ใช่หลักฐานยืนยันใหม่** คะแนน OOF ของผู้ชนะก็เป็น model-selection score; ไม่เรียก unbiased estimate หรือ SOTA

## 1. โมเดลเดิมพลาดอย่างไร

test เดิมมี 4,500 แถว ผู้ผิดนัดตาม dataset label 995 ราย (22.11%) คำว่า events ในรายงานหมายถึง label นี้ ไม่ใช่การรับรอง 90+ DPD หรือ regulatory 12-month PD

{thresholdtable}

ที่ threshold 0.5 จับผู้ผิดนัดได้ {a['tp']} รายและพลาด {a['fn']} ราย จุดตัดที่เลือกจาก validation ให้ recall อย่างน้อย 70% ช่วยจับได้ {b['tp']} รายใน test แต่ส่ง non-events เพิ่มจาก {a['fp']} เป็น {b['fp']} ราย นี่เป็น **การเปลี่ยนภาระการตรวจ** ไม่ใช่การเพิ่ม AUC หรือเปลี่ยนโมเดล ต้องมี cost/capacity จริงก่อนเลือก policy และคำว่า flagged ไม่ใช่คำสั่งปฏิเสธสินเชื่อ

กลุ่มที่ไม่มี positive repayment code มี {int(no['rows']):,} แถว, events {int(no['events'])}, พลาดที่ threshold 0.5 จำนวน {int(no['fn_at_0.5'])}; mean prediction {no['mean_prediction']:.2%} เทียบ observed rate {no['event_rate']:.2%} ตัวเลขนี้ยังไม่ชี้ systematic underprediction ทั้งกลุ่ม การแบ่งอันดับภายในกลุ่มอาจต้องการ signal เพิ่ม แต่ยังไม่รู้ว่าข้อมูลเดิมมี signal เพียงพอหรือไม่

เคส 10% ที่ individual log loss สูงสุดคิดเป็น {old['top10pct_loss_share']:.2%} ของ loss ทั้งหมด เป็นจุดเน้นการวิเคราะห์ โดยไม่ได้ oversample เคสเหล่านี้ในการฝึก และไม่สมมติว่าความมั่นใจผิดเกิดจาก label error

exact-vector conflicting labels พบ {fa['exact_vector_ambiguity']['conflicting_exact_vector_groups']} กลุ่ม รวม {fa['exact_vector_ambiguity']['rows_in_those_groups']} แถว; predictor เดียวกันจึงแยก label เหล่านี้ไม่ได้ด้วย deterministic model ของ features เดิม แต่เป็นจำนวนน้อย ไม่ใช่คำอธิบายข้อผิดพลาดทั้งหมด ไม่ลบ/แก้ label และไม่ตีความเป็น population Bayes-error floor

หลักฐาน baseline อยู่ใน `../failure_analysis_v1/`: summary, slices, calibration bins, capacity, complementarity และ largest losses รายการ slices ซ้อนทับกัน ห้ามรวม loss shares ข้าม slices

## 2. สมมติฐานที่ทดลองและตัวแปรที่ควบคุม

- เก็บ 23 predictors เดิมและ unknown codes เป็น nominal โดยไม่เดาความหมาย
- Feature group ใหม่: จำนวน/ระดับของ positive delay codes, recent-versus-prior summaries, monthly bill/limit และ payment/limit, zero-payment counts, signed bill/payment variation และ monthly slopes
- ไม่จับคู่บิลกับ payment แล้วเรียก “จ่ายเต็ม/ขั้นต่ำ” เพราะไม่มีหลักฐานพอของ bill settlement alignment; aggregate ratios เป็น numeric summaries
- `trajectory_fixed` เทียบ reference โดยคง settings เดิม จึงตรวจผลรวมของ feature group ได้ ส่วน candidate อื่นเปลี่ยนหลาย settings ไม่ใช้พิสูจน์เหตุของ parameter เดี่ยว
- `trajectory_no_demo` ใช้ settings เดียวกับ `trajectory_d4_long` และตัด SEX/EDUCATION/MARRIAGE/AGE เป็น sensitivity analysis ไม่ใช่ proof of fairness
- ไม่ SMOTE/class-weight หรือปรับ threshold เพื่อแสร้งว่า ranking/probability ดีขึ้น

{configtable}

Original fit 16,500 แถว แบ่ง 3 group folds แต่ละ fold ไม่มีกลุ่ม exact-vector ข้าม fit/holdout ใช้ seed 20261005 ทุก candidates, 2 concurrent jobs และ 2 threads ต่อ base model ไม่มี early stopping บน outer holdout; เก็บ learning curves เพื่อวิเคราะห์หลังจบ ไม่ปรับกริดตาม curves รอบนี้

Reference recipe ใน CV ใช้ settings ของ V1 แต่ seed รอบสอง จึงไม่ใช่น้ำหนักเดิมของ V1 การเทียบ old test แสดงทั้ง legacy V1 artifact และ CV-reference refit แยกกัน

## 3. ผล model selection บน group OOF

{cvtable}

Blend ที่เลือก: AUC {sel['candidate_oof']['roc_auc']:.6f}, AP {sel['candidate_oof']['average_precision']:.6f}, log loss {sel['candidate_oof']['log_loss']:.6f}, Brier {sel['candidate_oof']['brier']:.6f}

เกณฑ์ผ่านที่ล็อกไว้: ลด OOF log loss อย่างน้อย 0.001, ดีขึ้นทุก fold และ Brier ไม่แย่ลง ไม่ใช่นัยสำคัญทางสถิติหรือ business utility เงื่อนไขนี้เป็นของรอบทดลองนี้เท่านั้น เก็บ candidates ทั้งหมด ไม่มีการเพิ่มหลังเห็นผล

## 4. เปรียบเทียบ reference ที่เปิดแล้วหลังล็อก selection

Final fit ใช้ 16,500 แถวเท่าเดิม; เลือก identity/sigmoid/isotonic ด้วย group OOF ภายใน calibration 4,500 แถวที่เคยใช้แล้ว ไม่เรียก partition นี้ independent pipeline-selection holdout

{reftable}

Candidate เทียบ legacy V1: 95% paired group-bootstrap differences (300 replicates) AUC [{ci['roc_auc'][0]:+.6f}, {ci['roc_auc'][1]:+.6f}], log loss [{ci['log_loss'][0]:+.6f}, {ci['log_loss'][1]:+.6f}]

บน selected OOF: log-loss difference interval [{oofci['log_loss'][0]:+.6f}, {oofci['log_loss'][1]:+.6f}]

Intervals เป็น descriptive conditional-on-selection resampling; ไม่ชดเชย adaptive model selection, training dependence ระหว่าง CV folds หรือการเห็น test ก่อน จึงไม่ใช้ประกาศ significance/generalization แม้ interval ไม่คร่อมศูนย์

## 5. ความผิดพลาดกลุ่มเดิมดีขึ้นหรือแย่ลง

{failuretable}

Δ log loss ติดลบหมายถึง probability loss ดีขึ้นใน slice นั้น เป็น exploratory analysis มี slices ซ้อนทับและกลุ่มเล็ก ไม่ใช่ข้อสรุป causal หรือการคัด feature ตาม test รอบใหม่

**สมมติฐานที่ยังไม่สำเร็จ:** กลุ่มไม่มี positive repayment code มี log loss {hard_before['metrics']['log_loss']:.6f} → {hard_after['metrics']['log_loss']:.6f} แทบไม่เปลี่ยน ขณะที่ AUC {hard_before['metrics']['roc_auc']:.6f} → {hard_after['metrics']['roc_auc']:.6f} ลดลง พลาดที่ threshold 0.5 จำนวน {hard_before['threshold_0.5']['fn']} → {hard_after['threshold_0.5']['fn']} ราย การเพิ่ม features/complexity รอบนี้จึงยังไม่แก้การจัดอันดับในกลุ่มปัญหาหลัก ไม่อ้างว่าสาเหตุคือ label noise หรือไม่มี signal โดยไม่มีหลักฐานเพิ่ม

{capacitytable}

Capacity เป็นการจัดอันดับแล้วส่งเคสสูงสุดตามจำนวนที่กำหนด ช่วยเทียบภายใต้ workload เท่ากัน ไม่ fit threshold ใหม่จาก test และไม่ประเมินกำไร/expected monetary loss เพราะขาดต้นทุน, LGD และ EAD

![Development diagnostics](development_diagnostics.png)

{curve_table}

Learning curves ของ selected CatBoost แสดง train loss ลดลงต่อ แต่ heldout loss มีจุดต่ำสุดก่อนครบ fixed iterations การดูจุดต่ำสุดนี้เป็น **posthoc diagnosis เท่านั้น** ไม่ refit ตาม outer fold minima เพราะจะเปลี่ยน heldout labels ให้เป็น tuning data ขั้นต่อไปจึงควรทดสอบ inner-fold early stopping ใน protocol ใหม่ ดู `learning_curve_diagnostics.csv` และ `failure_followup.json`

## 6. เพิ่ม context ของ TabPFN-3.5 ได้ผลหรือไม่

context 4,000 รวม 1,000 แถวเดิมไว้ข้างใน ใช้ validation 400/calibration 600/test 4,500 แถวเดิม, 2 estimators และ local CPU; ทั้ง TabPFN และ matched CatBoost ได้ context เดียวกัน ไม่มีการเลือกจาก test

{auxtable}

{timings}

TabPFN auxiliary shell session คืน exit 1 พร้อม PowerShell `NativeCommandError` แต่ stderr มี CPU-speed UserWarning และทั้งสอง trials จบพร้อม predictions/result files จริง ตรวจซ้ำจาก CSV ว่า IDs/probability/metrics ตรงกันแล้ว ทดสอบพฤติกรรม shell ด้วย warning-only probe พบ child Python exit 0 แต่ direct redirection session exit 1 เช่นกัน หลักฐานอยู่ใน `outputs/diagnostics/powershell_warning_behavior.json` จึงแยก shell warning status ออกจาก model-trial success ไม่ลบ warning หรือ rerun ผลเดิมเพื่อเปลี่ยนสถานะ

ห้ามเทียบอันดับ 1,000/4,000/16,500 แถวเป็นการแข่งขนาดข้อมูลเท่ากัน และเวลามี CPU contention ระหว่าง jobs ไม่ใช่ speed benchmark ที่ควบคุมเครื่องว่าง การ `fit` ของ TabPFN คือ context/preprocessing ไม่ใช่การฝึกน้ำหนัก foundation model ใหม่

## 7. ตรวจอะไรแล้วและใช้ต่ออย่างไร

`analysis.json` บันทึก checks: hashes ของ V1/data/features ไม่เปลี่ยน, OOF ทั้งเก้าใช้ IDs เดียวกัน/probability finite, CV groups disjoint, ID/target ไม่กระทบ engineered features, single-row/batch feature parity, demographic ablation ตัดครบ และ reload/scoring parity ของ pipeline ผ่าน

```powershell
.venv\\Scripts\\python.exe scripts\\score_v2.py outputs\\experiment_v2\\demo_input.csv
```

รับ 23 predictors ไม่มี ID/target ให้ probability ของ dataset label สำหรับการทดลอง ไม่มี lending decision โมเดลเดิม V1 และผลเดิมเก็บครบ; V2 bundle อยู่ใน `models/pipeline.joblib`

Aggregate feature influence อยู่ใน `catboost_feature_importance.csv` เป็น PredictionValuesChange ของ CatBoost component ไม่ใช่ causal importance หรือคำอธิบาย probability ของ ensemble ที่ผ่าน calibration แล้ว

## 8. ขั้นต่อไปที่มีหลักฐานรองรับ

1. ล็อก V2 recipe ก่อนรับข้อมูลใหม่ ประเมินบน cohort ใหม่/ช่วงเวลาถัดไปที่ labels mature แล้ว ต้องนิยาม default/horizon และ feature availability ให้ชัด; random re-split ของข้อมูลเดิมไม่แก้ปัญหา test reuse
2. สำหรับกลุ่มที่ไม่มี positive code ตรวจข้อมูลพอร์ตจริงว่ามี income/cash flow, utilization/exposure history, account tenure หรือ bureau history ณ เวลาตัดสินใจหรือไม่ เป็น hypotheses ที่ต้องทดสอบ ไม่ใช่การรับรองว่าช่วยแน่
3. หากต้องการความเที่ยงของ model-selection procedure ภายใน cohort ใช้ nested group CV ที่เลือกทุก setting ภายใน inner folds และเพิ่ม folds/repeatsตาม compute budget; ยังไม่แทน temporal/Thai-bank validation
4. ทดลองลด engineered feature redundancy และแยก ablation ของ parameter เดี่ยวใน protocol ใหม่ ไม่ย้อนแก้ settings ของรอบนี้ให้เข้ากับ test
5. กำหนด review capacity และ costs ก่อนเลือก threshold; ทดสอบ subgroup/error stability และคำอธิบายของ final calibrated pipeline ก่อนใช้ operationally

แนวทางวิจัย/primary-source audit และข้อเสนอ agy ที่รับหรือไม่รับอยู่ใน [research approach](../../research/ITERATION_2_APPROACH_TH.md) agent รีวิว supplied methodology ไม่ได้คำนวณตารางนี้ ไม่มีการเรียก Gemini CLI
'''
    (OUT/'REPORT_TH.md').write_text(text,encoding='utf-8');print('Wrote',OUT/'REPORT_TH.md')

if __name__=='__main__':main()
