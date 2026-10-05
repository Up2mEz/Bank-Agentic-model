# การวิจัยรอบสาม: แก้จุดอ่อนที่วัดพบ และตรวจวิธีประเมินให้เข้มขึ้น

วันที่ตรวจแหล่งข้อมูลและรัน: 5 ตุลาคม 2026 งานวิจัยที่ไม่ใช่เชิงพาณิชย์

รอบนี้ศึกษาว่า **การเลือกความลึกและจำนวนต้นไม้ภายใน training folds** ช่วยลดปัญหาที่พบใน V2 หรือไม่ ไม่ตั้งข้อสรุปล่วงหน้าว่าจะชนะ V2 และไม่เปลี่ยน test เดิมให้กลายเป็น independent holdout ด้วยการแบ่งใหม่

## หลักฐานจาก literature และสิ่งที่นำมาใช้

| แหล่งต้นทางที่เปิดตรวจ | ข้อค้นพบ/ข้อกำหนดที่แหล่งรองรับ | การตัดสินใจในโครงการ | ขอบเขตการถ่ายทอด |
|---|---|---|---|
| Cawley & Talbot (2010), JMLR 11(70):2079–2107, [บทความ](https://www.jmlr.org/papers/v11/cawley10a.html), [full text](https://www.jmlr.org/papers/volume11/cawley10a/cawley10a.pdf), p.2080 | การเลือกโมเดลสามารถ overfit เกณฑ์ CV; ต้องนับ model selection เป็นส่วนหนึ่งของกระบวนการ fit และทำใหม่เมื่อฝึกบน sample ใหม่ | ประเมินกระบวนการเลือกโมเดลทั้งชุด: inner folds เลือก depth/iterations แล้ว outer fold ประเมิน | ไม่ใช่หลักฐานว่า CatBoost จะชนะ หรือว่าข้อมูลเดิมที่เคยเห็นกลับมาเป็นอิสระได้ |
| [scikit-learn: nested versus non-nested CV](https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html) | การใช้คะแนนชุดเดียวเพื่อเลือก hyperparameters และประเมินทำให้คะแนน optimistic; inner/outer loops แยกหน้าที่ | outer held-out labels ไม่ถูกส่งให้ `nested_fit`; ตรวจ group disjointness ทั้งสองชั้น | ตัวอย่าง Iris เป็นคำอธิบายวิธี ไม่ใช่ benchmark ของข้อมูลสินเชื่อนี้ |
| [CatBoost official parameter-tuning source](https://raw.githubusercontent.com/catboost/catboost/master/catboost/docs/en/concepts/parameter-tuning.md), section Number of trees | ตรวจ underfit/overfit ก่อนจูนอย่างอื่น; overfitting detector และ best model ใช้ validation metric เลือกจำนวนต้นไม้ | inner held-out เท่านั้นใช้ Logloss early stopping; refit outer train โดยไม่มี eval_set | เอกสารไม่ได้กำหนดว่า median inner iterations เหมาะกับขนาด refit ที่ใหญ่กว่า; นี่เป็น heuristic ที่โครงการกำหนดก่อนรัน |
| Kull, Silva Filho & Flach (2017), AISTATS/PMLR 54:623–631, [บทความ](https://proceedings.mlr.press/v54/kull17a.html), [full text](https://proceedings.mlr.press/v54/kull17a/kull17a.pdf) | calibration บางวิธีทำให้ probability แย่ลงได้; paper เสนอ beta calibration และทดลองกับหลาย classifiers | เก็บ identity เป็นทางเลือกเสมอ และเลือก calibrator ด้วย group folds ใน calibration partition | ผล beta เหนือ logistic สำหรับ Naive Bayes/AdaBoost ในบทความไม่พิสูจน์ว่าจะชนะบน CatBoost ของเรา; ยังไม่เพิ่ม beta หลังเห็นผลรอบนี้ |
| Guo et al. (2017), ICML/PMLR 70:1321–1330, [บทความ](https://proceedings.mlr.press/v70/guo17a.html) | modern neural networks ในงานภาพ/เอกสารที่บทความทดลองอาจไม่ calibrated; postprocessing ช่วยได้ในบริบทที่ทดลอง | แยก ranking metrics ออกจาก probability quality | เป็นหลักฐานเฉพาะ neural networks และ datasets ในบทความ ไม่ใช้ยืนยันว่า temperature scaling เป็นวิธีดีที่สุดสำหรับ tree models |
| [UCI dataset documentation](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients) | Taiwan credit-card default, 30,000 rows/23 features; แหล่งข้อมูลให้ความสำคัญกับค่าความน่าจะเป็น | ใช้ log loss เป็นเป้าหมายหลัก พร้อม AUC/AP/Brier และ subgroup counts | นิยาม default แบบ regulatory 12 เดือนยังไม่ทราบ; ข้อสรุป ANN ในงานปี 2009 ไม่ใช่คำสั่งให้เลือก ANN ในปี 2026 |

**สรุปเชิงวิธี:** สิ่งที่ literature รองรับชัดเจนคือการควบคุมการเลือกโมเดลและประเมิน probability อย่างรอบคอบ ส่วนวิธีที่ได้คะแนนดีที่สุดบนข้อมูลนี้ต้องวัดเอง การเพิ่มความซับซ้อนของ agent หรือจำนวนโมเดลไม่ใช่หลักฐานว่าจะลดความเสี่ยงได้

ข้อแตกต่างในการอ่าน Kull et al.: logistic curve บน probability scores ที่บทความกล่าวถึงไม่มี identity map แต่ implementation ของโครงการ fit logistic regression บน **logit(probability)** ซึ่งมี identity เมื่อ coefficient = 1/intercept = 0 จึงไม่ถ่ายทอดคำอ้างว่า family ของเราขาด identity การเก็บตัวเลือก identity แยกยังช่วยเปรียบเทียบกับ calibrator ที่ประมาณจาก sample จริงและอาจเสียจากความแปรปรวนได้

## สำรวจข้อมูลเพิ่มเติมจาก original fit 16,500 แถวจริง

สำรวจเฉพาะ fit partition สำหรับตารางเพิ่มเติมนี้ และคง feature recipe เดิมเพื่อแยกผลของวิธีเลือกโมเดล ดู `reports/exploration_v3/exploration.json` และ CSV รายกลุ่มเพื่อทำซ้ำ

| กลุ่มในชุดพัฒนา | จำนวนแถว | Default labels | อัตรา |
|---|---:|---:|---:|
| ไม่มี PAY code เป็นบวกตลอด 6 snapshots | 11,024 | 1,304 | 11.83% |
| มี PAY code เป็นบวกอย่างน้อยหนึ่ง snapshot | 5,476 | 2,345 | 42.82% |
| ในกลุ่มแรก: ยอดชำระ = 0 อย่างน้อย 3 snapshots | 1,546 | 285 | 18.43% |
| ในกลุ่มแรก: ยอดชำระ = 0 น้อยกว่า 3 snapshots | 9,478 | 1,019 | 10.75% |
| ในกลุ่มแรก: ยอดบิลไม่เป็นบวกอย่างน้อย 3 snapshots | 1,239 | 228 | 18.40% |
| PAY code ทั้งหกเท่ากับ -2 | 1,208 | 159 | 13.16% |
| PAY code ทั้งหกเท่ากับ 0 | 5,383 | 555 | 10.31% |

ข้อเท็จจริงคือกลุ่มที่ไม่มีรหัสเป็นบวกยังมี default labels และมีความต่างภายในกลุ่ม ข้อมูลนี้ไม่ยืนยันว่า code -2/0 หมายถึงอะไร หรือว่าศูนย์ยอดชำระเกิดจากการขาดวินัย/ไม่ใช้งานบัญชี ไม่ตีความยอดบิลติดลบว่าเป็น refund โดยไม่มีหลักฐาน

การวิเคราะห์นี้แนบ Wilson intervals พร้อมจำนวน events; เป็น exploratory intervals ไม่ได้ปรับ multiple comparisons หรือพิสูจน์สาเหตุ Feature 68 ตัวให้ค่าตรงกับ V2 ทุกเซลล์ทั้ง 30,000 แถว รวม index/order และ single-row probes พบหนึ่งคู่ซ้ำ (`recent_bill_utilization` กับ `bill_limit_ratio_1`) และคงไว้เพื่อรักษาการเปรียบเทียบตรงกัน ไม่อ้างว่าเป็นสัญญาณอิสระสองชุด

ใน original fit มี exact-vector groups ที่ outcomes ขัดกัน 9 groups/19 rows; deterministic model บน vectors ที่สังเกตนี้ต้องผิดอย่างน้อย 9 labels ไม่ใช่หลักฐาน label error และไม่ใช่ Bayes-error floor ของประชากร

## การทดลองที่ล็อกก่อนรัน

ใช้ outer group folds เดิม 3 folds เพื่อเปรียบเทียบแบบจับคู่กับ V2 ในแต่ละ outer train:

1. แบ่ง inner group folds 3 folds ลองเพียง depth 4/l2 10 และ depth 6/l2 20; learning rate .03, max 2,000 trees, patience 100
2. เลือก depth จาก mean inner best-model log loss; ใช้ median best tree counts ของ depth นั้น refit outer train ทั้งหมด โดยไม่มี outer eval_set
3. ผสม CatBoost กับ frozen V2 LightGBM OOF ที่ตรวจ SHA/IDs/folds ที่ .75/.25 คงที่ ไม่เลือก blend weights จาก outer scores รอบนี้
4. เปลี่ยนจาก V2 ได้ต่อเมื่อ OOF log-loss gain ≥ .001, log loss ดีขึ้นทุก fold, Brier ไม่แย่ลง และ log loss ในกลุ่มไม่มี PAY code บวกเพิ่มไม่เกิน .001
5. ถ้าไม่ผ่าน เก็บ V2 ไว้และปิดสมมติฐานรอบนี้ ไม่ลองค่าชุดใหม่เพื่อให้ gate ผ่าน

การ fit สุดท้ายทำ inner procedure ใหม่บน original fit ด้วย seed ที่ระบุล่วงหน้า ไม่เลือก depth/iterations ตาม outer minima จาก V2 หรือผล test แล้วเลือก calibrator ใน calibration partition เดิมเท่านั้น ผล old validation/test ใช้ประกอบ failure analysis หลัง gate ล็อกแล้ว

## ข้อจำกัดที่ยังแก้ไม่ได้

Nested procedure แยกการเลือก depth/iterations ของ **รอบปัจจุบัน** ออกจาก outer labels แต่ architecture, features, blend และการตั้งสมมติฐานมาจากการวิจัยก่อนหน้า การใช้กลุ่มย่อยตั้ง gate รอบใหม่ก็เกิดหลังเคยวิเคราะห์ข้อมูลนี้ จึงเป็น predeclared **สำหรับรอบนี้** ไม่ใช่ preregistration ก่อนเห็น dataset

Comparator V2 เคยถูกเลือกจาก outer folds เหล่านี้ จึงมี selection optimism; bootstrap จาก probabilities ที่ตรึงแล้วไม่รวมความแปรปรวนจากการฝึก/เลือกโมเดล และไม่เป็น selection-adjusted confidence interval ไม่ใช้แสดงว่าโมเดลจะชนะบนข้อมูลธนาคารจริง

[Home Credit Model Stability data page](https://www.kaggle.com/competitions/home-credit-credit-risk-model-stability/data) เปิดได้แต่ไม่คืนเนื้อหา data dictionary ผ่าน web reader ในรอบนี้ จึงไม่อ้างว่าตรวจไฟล์หรือได้ independent cohort เพิ่มจากหน้าเว็บนั้น การต่อยอดไปชุดข้อมูลเวลาใหม่ต้องตรวจ raw files, borrower/time overlap, target maturity, label definition และ license ก่อน ข้อมูลคนละ schema/cohort ไม่สามารถใช้เป็น external test ของโมเดล UCI เดิมโดยตรง

## Reference verification

ใช้ workflow ของ `ref-verify` แบบ manual; executable `ref-verify` ไม่พบใน PATH ไม่ได้อ้างว่ารัน CLI สำเร็จ ตรวจ publisher/full-text ตามลิงก์ข้างบน และค้น metadata/retraction เพิ่ม:

- Cawley/Talbot: title/author/year/pages ตรง JMLR และผลค้น DBLP; full text p.2080 รองรับ procedural claim; DOI status ไม่ยกระดับจาก WARN ใน audit เดิม
- Kull et al.: title/authors/year/pages/full text จาก PMLR; [ELLIS author-publication record](https://ellis.eu/publication/2017-beta-calibration-a-well-founded-and-easily-implemented-improvement-on) ยืนยัน title/authors/year อีกแหล่ง; ลิงก์ author manuscript ที่ Bristol คืน 403 จึงไม่อ้างว่าอ่านสำเร็จ ไม่เติม DOI ที่ primary record ไม่ได้ให้
- Guo et al.: citation metadata/abstract จาก PMLR; ใช้เฉพาะ abstract-level finding ไม่ใช้เป็น implementation recommendation ของ CatBoost
- ไม่พบ retraction notice ใน publisher pages ที่อ่าน และการค้นชื่อ Cawley/Kull พร้อม retraction ไม่คืน notice ของ papers เหล่านี้ แต่ไม่ใช่หลักประกันว่าไม่มี retraction/correction ในทุกฐานข้อมูล
- CatBoost/sklearn/UCI เป็น documentation/data sources แยกจาก papers; หน้า Home Credit ไม่คืนเนื้อหาจึงมีข้อจำกัดตามที่ระบุ

ผลการทดลองจริงและ failure analysis อยู่ใน `reports/v3/REPORT_TH.md`; ไม่เติมผลลัพธ์จากข้อเสนอของ agent
