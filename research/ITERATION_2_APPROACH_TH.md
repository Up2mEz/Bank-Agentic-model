# วิจัยเพื่อพัฒนารอบสอง: เริ่มจากความผิดพลาดและวัดการปรับปรุงอย่างจำกัดขอบเขต

วันที่ 4 ตุลาคม 2026 — งานวิจัยที่ไม่ใช่เชิงพาณิชย์

## สิ่งที่งานวิจัยรองรับ และสิ่งที่ต้องทดลองเอง

### 1. คะแนนดีขึ้นจากการเลือกโมเดลอาจเป็น selection bias

Cawley และ Talbot (2010), *On Over-fitting in Model Selection and Subsequent Selection Bias in Performance Evaluation*, JMLR 11, 2079–2107 อธิบายว่าการปรับตามเกณฑ์เลือกโมเดลสามารถ overfit เกณฑ์นั้นเอง และทำให้การประเมินเอนเอียง เอกสารเต็มเสนอให้รวม model selection ในกระบวนการ fit ของแต่ละรอบการประเมิน ข้อความตรวจจากหน้า 2: “model selection must be treated as an integral part of the model fitting process”. [บทความและ metadata](https://www.jmlr.org/papers/v11/cawley10a.html), [เอกสารเต็ม](https://www.jmlr.org/papers/volume11/cawley10a/cawley10a.pdf)

**นำมาใช้:** รักษาผลรอบแรก ล็อก candidate grid และเลือกด้วย group OOF ก่อนสร้างผลใหม่บน test เดิม รายงานว่าคะแนนของผู้ชนะจาก OOF ยังมี optimism เพราะ OOF ถูกใช้เลือก และทุก reference partition เคยใช้แล้ว การสุ่มแบ่งใหม่ไม่ทำให้ข้อมูลเดิมกลับเป็น holdout ใหม่

**ข้อจำกัด:** รอบนี้เป็น development experiment ไม่ใช่ nested CV ของกระบวนการวิจัยทั้งหมด และไม่ใช่หลักฐาน generalization ใหม่ เหตุผลที่ใช้ 3 folds คือขอบเขต compute บน CPU ไม่ใช่ข้ออ้างว่า 3 folds ดีที่สุด; แต่ละ fold train ประมาณ 11,000 แถว ต่างจาก final fit 16,500 แถว

### 2. Features และค่าตั้งของ boosting เป็นสมมติฐานที่ต้องแยกทดสอบ

Prokhorenkova และคณะ, *CatBoost: unbiased boosting with categorical features*, NeurIPS 2018 อธิบาย ordering principle สำหรับ prediction shift และ categorical target statistics ตรวจบทความฉบับตีพิมพ์แล้ว ข้อความจากบทนำ: “ordered boosting, a modification of standard gradient boosting algorithm”. [ฉบับตีพิมพ์](https://proceedings.neurips.cc/paper/2018/hash/14491b756b3a51daac41c24863285549-Abstract.html), [เอกสารเต็ม](https://proceedings.neurips.cc/paper/2018/file/14491b756b3a51daac41c24863285549-Paper.pdf), [arXiv](https://arxiv.org/abs/1706.09516)

**นำมาใช้:** เทียบ reference recipe กับ trajectory features โดยคง hyperparameters เดิมก่อน แล้วทดสอบจำนวนต้นไม้/depth/regularization ในกริดจำกัด มี ordered candidate อีกหนึ่ง config แต่ config นี้เปลี่ยนหลายค่า จึงไม่ใช่ pure ablation ที่พิสูจน์ผลของ ordered boosting อย่างเดียว

เอกสาร CatBoost แนะนำตรวจ underfitting/overfitting และจำนวน iterations จาก validation [เอกสารต้นทาง](https://raw.githubusercontent.com/catboost/catboost/master/catboost/docs/en/concepts/parameter-tuning.md) รอบนี้เก็บ learning curves แต่ไม่เลือก best iteration จาก outer held-out fold ใช้จำนวนต้นไม้ที่ล็อกไว้ เพื่อให้ outer prediction ไม่ผ่าน early-stopping selection จาก label ของ fold นั้น หากจะทดสอบ early stopping รอบหน้า ต้องแยก inner stopping set

### 3. เพิ่ม context ของ TabPFN และรักษาความยุติธรรมของขนาดข้อมูล

Prior Labs อธิบาย estimator count, temperature และ trade-off ของ probability balancing โดยระบุว่าการเปลี่ยน threshold ไม่เพิ่ม ROC-AUC หรือปรับ log loss และการเปลี่ยน class prior อาจแลก ranking กับคุณภาพ probability [Model parameters](https://docs.priorlabs.ai/improving-performance/model-parameters)

**นำมาใช้:** คง 2 estimators และค่าเดิมของ V3.5 เพิ่ม context จาก 1,000 เป็น 4,000 แถวแบบ nested natural-prevalence sampling จึงอ่านเป็น learning curve ที่ควบคุมหลายปัจจัยได้ มี CatBoost 4,000 แถวเดียวกันเป็น comparator ไม่เปิด balancing/SMOTE เพื่อไล่คะแนน AUC จน probability เปลี่ยนความหมาย

เลือก 4,000 เพราะข้อจำกัดการทดลองบน CPU ไม่ใช่เพดานทางสถาปัตยกรรมของ V3.5 ใช้ test chunks และ memory saving ตามแนวทางทรัพยากรของผู้ให้บริการ [Memory optimisation](https://docs.priorlabs.ai/cookbook/memory_optimisation) เวลาที่วัดในรอบนี้มีงาน CPU พร้อมกัน จึงไม่ใช่ controlled speed benchmark

เอกสารผู้ให้บริการเสนอ domain ratios/interactions [Feature engineering](https://docs.priorlabs.ai/improving-performance/feature-engineering) เรานำมาเป็นเหตุผลในการทดลอง ไม่รับรองว่าจะเพิ่มคะแนน และไม่ทำตามข้อเสนอให้ใส่ ID โดยอัตโนมัติ: ID ของ dataset นี้ไม่มีหลักฐานว่าเป็น stable borrower identifier ที่มีประโยชน์สำหรับงานเป้าหมาย จึงยังตัดออก

### 4. Ensemble ต้องมีหลักฐานจาก prediction ที่ไม่ใช้ฝึก base model

เอกสาร scikit-learn อธิบาย soft voting ด้วย weighted probabilities [Voting classifier](https://scikit-learn.org/stable/modules/ensemble.html#voting-classifier) รอบนี้ใช้ OOF ของ CatBoost/LightGBM บนแถวเดียวกัน ค้นน้ำหนักเพียง 0/0.25/0.5/0.75/1 ไม่ fit stacker ที่ซับซ้อนบนชุดเล็ก ผู้ชนะและน้ำหนักถูกล็อกก่อนอ่านผล reference ใหม่ คะแนน OOF ของ blend ยังเป็น selection score ไม่ใช่ independent validation

## แปล failure analysis เป็นการทดลอง

1. **Threshold:** ตรวจ 0.5 เทียบ threshold ที่เลือกจาก validation ให้ recall อย่างน้อย 70% และตรวจ capacity 10/20/30/40/50% การเปลี่ยนจุดตัดคือ trade-off ในการส่งตรวจ ไม่ใช่การเพิ่มความสามารถจัดอันดับของโมเดล
2. **พลาดในกลุ่มที่ไม่มี positive code:** ตรวจ trajectories ของยอดบิลและการชำระ ไม่ตั้งสมมติฐานว่า repayment -2/0 หมายถึงอะไร และไม่คัดแต่ผู้ผิดนัดมาฝึกเพิ่มจน class prior บิดเบือน
3. **ความมั่นใจที่ผิด:** ดู individual log loss, tail losses และ calibration bins กลุ่มที่มี mean prediction ใกล้ event rate อาจยังจัดอันดับภายในกลุ่มไม่ดี จึงไม่สรุปจากค่าเฉลี่ยเพียงค่าเดียว
4. **ข้อมูล/label:** เก็บ conflicting exact-vector groups โดยไม่แก้ label หรือเหมารวมว่า dataset noisy; observed ambiguity ของ 46 แถวไม่อธิบายข้อผิดพลาดจำนวนมากทั้งหมด
5. **Features:** เก็บ signed amounts, original predictors, flags และ safe denominators ไม่ตีความบิลติดลบว่า refund/overpayment หากต้นทางไม่ระบุ ไม่ตั้ง PAY_AMT กับ BILL_AMT ต่างเดือนเป็น “จ่ายเต็ม/ขั้นต่ำ” โดยไม่มีหลักฐานการจับคู่
6. **Demographics:** paired sensitivity ablation กับ setting เดียวกันของ trajectory_d4_long; ไม่ใช้ผลคะแนนเพียงอย่างเดียวเป็น proof of fairness

## เกณฑ์พัฒนาที่ล็อกไว้

ยอมรับ candidate เป็น development pipeline เมื่อ OOF log loss ดีขึ้นอย่างน้อย 0.001 จาก reference recipe, ดีขึ้นทุกสาม folds และ Brier ไม่แย่ลง เกณฑ์นี้เป็นกฎเชิงปฏิบัติสำหรับรอบนี้ ไม่ใช่ statistical significance, optimal business threshold หรือการรับรองโมเดลธนาคาร หากไม่ผ่านให้คง reference และเก็บผลล้มเหลวทั้งหมด ไม่เพิ่ม candidate หลังเห็นผล

รายละเอียด settings, hashes, split และวันที่ล็อกอยู่ใน `outputs/experiment_v2/protocol.json` ผลจริงจะอยู่ใน `outputs/experiment_v2/REPORT_TH.md`

## ตรวจแหล่งอ้างอิงและ agent อย่างไร

- ใช้ `ref-verify` แบบ manual: CLI ไม่พบใน PATH; ไม่อ้างว่า executable engine รันผ่าน
- Cawley: metadata ตรงระหว่าง JMLR กับ DBLP ที่ index ให้ค้นได้; เปิดเอกสารเต็มได้ DOI 10.5555/1756006.1859921 ที่ DBLP ระบุเปิดตรงไม่สำเร็จ จึงไม่รับรอง DOI resolution การค้น retraction พบ paper อื่นที่อ้างงานนี้และถูกถอน ไม่ใช่การถอนงาน Cawley; ไม่มี banner ถอนบน JMLR ที่เปิด
- CatBoost: published 2018 กับ arXiv submitted 2017/revised 2019 เป็นคนละ version timeline เก็บแยก ไม่สลับปี Full text และ authors ตรงกัน; DOI arXiv เปิดตรงไม่สำเร็จ ไม่รับรอง DOI resolution ไม่มีการถอนพบจาก bounded search/primary page
- ไม่เรียกทั้งสองรายการว่า citation-release certification; metadata/content ตรวจได้ แต่ DOI resolution ไม่ครบ ส่วนเอกสาร implementation เป็น official docs ไม่ใช่ peer-reviewed evidence ว่าการปรับของเราจะสำเร็จ
- เรียก agy โดยตรงเพื่อวิจารณ์ **ข้อความที่จัดเตรียมให้** ใน `AGY_V2_REVIEW_PROMPT.txt` ได้คำตอบจริง แต่ไม่ได้อ่านไฟล์หรือคำนวณข้อมูลเอง คำสั่งครั้งแรกมี warning ว่า `--mode plan` ไม่มีผลร่วมกับ disabled slash expansion; ไม่อ้างว่า mode enforcement ผ่าน และไม่ได้เปิด auto-approve
- รับข้อเสนอเรื่อง locked budget, already-opened test และ matched-context comparators ส่วนคำอธิบายสาเหตุบิลติดลบ, universal monotonic constraints และกฎตัด blend เมื่อ weak learner แพ้เดี่ยว ๆ ไม่มีหลักฐานพอ จึงไม่รับมาใช้ เช่นเดียวกับเกณฑ์นัยสำคัญที่ใช้ SE ระดับแถวโดยละเลย model selection/group dependence
- ไม่มีการเรียก Gemini CLI รอบนี้
