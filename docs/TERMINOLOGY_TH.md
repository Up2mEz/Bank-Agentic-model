# คำศัพท์ที่ใช้ในโครงการ

ใช้คำอธิบายภาษาไทยควบคู่ technical terms และคงชื่อ variables/metrics ตาม artifacts เพื่อให้ค้นหาและตรวจผลต่อได้ ชื่อมาตรฐานของโมเดลคือ **TabPFN**

## Task และข้อมูล

| Technical term | ความหมายในโครงการ |
|---|---|
| Credit risk | ความเสี่ยงด้านเครดิต; ครอบคลุมมากกว่า target ที่ทดลองใน dataset นี้ |
| Credit default / default label | การผิดนัดชำระตาม label ของ dataset; exact default threshold ยังไม่ยืนยัน |
| Fraud detection | การตรวจเหตุการณ์ฉ้อโกงตามนิยามและ outcomes ของงานนั้น; default label เพียงอย่างเดียวไม่ยืนยัน fraud |
| Predictor / feature | ตัวแปรที่ใช้ทำนาย; input หลักมี 23 predictors ต้นฉบับ |
| Engineered feature | ตัวแปรที่คำนวณเพิ่มจาก input เช่น payment-to-bill ratio หรือการเปลี่ยนยอดย้อนหลัง |
| Target / label | ผลลัพธ์ที่โมเดลเรียนรู้; ในข้อมูลนี้คือ `default.payment.next.month` |
| Cohort | กลุ่มข้อมูลที่มีประชากร/ช่วงเวลาหรือเงื่อนไขการเก็บข้อมูลร่วมกัน; cohort ไต้หวันไม่ยืนยันผลบนธนาคารไทย |
| Monthly snapshot | ค่าสรุปย้อนหลังรายเดือน; ไม่มีรายละเอียดแต่ละ transaction |
| Exact-vector group | แถวที่มี predictors เหมือนกันทุกค่า ใช้จัด split เพื่อลด overlap; ไม่ได้พิสูจน์ว่าเป็น borrower เดียวกัน |
| Data provenance | ที่มาของข้อมูลและหลักฐานที่ตรวจย้อนกลับได้ เช่น source URL, snapshot และ SHA-256 |

## การทดลองและประเมินผล

| Technical term | ความหมายในโครงการ |
|---|---|
| Model version / experiment iteration | รุ่นโมเดล เช่น TabPFN V2, TabPFN-3.5 / รอบพัฒนาโครงการ เช่น V1, V2, V3; เป็นคนละลำดับ |
| Fit partition | แถวที่ใช้ fit โมเดล; main experiment ใช้ 16,500 แถว |
| Context | Labeled examples ที่ TabPFN ใช้ประกอบ inference; auxiliary trials ใช้ 1,000/4,000 แถว |
| Pretraining / pretrained weights | การฝึกน้ำหนัก foundation model ก่อนนำมาใช้; การ fit context ใน trials นี้ไม่ได้ฝึกน้ำหนักนั้นใหม่ |
| Validation partition | ข้อมูลแยกจาก fit สำหรับเลือก/ตรวจ settings ตาม protocol |
| Calibration partition | ข้อมูลแยกจาก fit สำหรับเลือกและ fit probability calibration |
| Reference test | ชุดทดสอบเดิมที่เคยนำผลมาวิเคราะห์แล้ว; ผลอ้างอิงไม่ใช่ independent test ใหม่ |
| Cross-validation (CV) / fold | แบ่งข้อมูลเป็นหลายส่วน แล้วหมุนส่วนสำหรับ fit/evaluation ตาม procedure |
| OOF (out-of-fold) prediction | Prediction ของแถวที่ไม่ได้อยู่ในข้อมูลฝึกของ fold นั้น; ไม่รับประกัน independent validation หลังมี model selection |
| Nested CV / inner–outer folds | Inner folds เลือก settings ภายใน outer-training data แล้ว outer fold ประเมิน candidate |
| Calibration | การปรับ probability predictions โดยใช้ข้อมูล calibration; identity หมายถึงคง probability เดิม |
| Pipeline | กระบวนการ input validation, feature calculation, model prediction และ calibration ที่บันทึกเป็นรุ่น |
| Baseline / comparator / candidate | โมเดลอ้างอิง, โมเดลที่ใช้เปรียบเทียบ, และโมเดลที่เสนอให้ประเมิน ตามลำดับ |
| Auxiliary experiment | การทดลองเพิ่มเติมที่แยกจากขั้นตอนเลือก main pipeline |
| Promotion gate | เกณฑ์ที่กำหนดก่อนรันว่าจะเปลี่ยนจาก baseline เป็น candidate หรือคงโมเดลเดิม |
| Failure analysis | วิเคราะห์แถว/กลุ่ม/ช่วงเวลาที่ทำนายพลาด และประเด็นที่อาจอธิบายข้อจำกัดโดยยังไม่สรุปสาเหตุ |
| Review capacity | จำนวนหรือสัดส่วนแถวที่เจ้าหน้าที่ตรวจได้; ใช้วัดคุณภาพการจัดอันดับที่ budget กำหนด |
| Independent temporal validation | ประเมินบน cohort ตามเวลาที่ใหม่และแยกจากการพัฒนาโมเดล; random re-split ของ cohort ที่ใช้แล้วไม่สร้างเงื่อนไขนี้ |
| Frozen protocol / artifact | วิธีและไฟล์ผลที่ล็อกไว้เพื่อรักษาประวัติ; การแก้ README ไม่เปลี่ยนผลทดลองเหล่านั้น |

## Metrics และขอบเขตงานธนาคาร

| Technical term | ความหมาย / วิธีอ่าน |
|---|---|
| ROC-AUC | สรุปความสามารถจัดอันดับ positive เทียบ negative ข้าม score thresholds; สูงขึ้นดีกว่า ไม่ใช่เปอร์เซ็นต์ accuracy |
| AP (average precision) | สรุป precision–recall จากการจัดอันดับ scores; สูงขึ้นดีกว่า และขึ้นกับ class prevalence/ข้อมูลที่ประเมิน |
| Log loss | ประเมิน probability ที่ให้กับ outcome จริง; ต่ำลงดีกว่า และลงโทษการทำนายผิดด้วยความมั่นใจสูง |
| Brier score | ค่าเฉลี่ย squared error ระหว่าง probability กับ binary outcome; ต่ำลงดีกว่า ไม่ได้แยกวัด calibration เพียงอย่างเดียว |
| Threshold | จุดตัด score สำหรับจัดกลุ่ม/ส่งตรวจ; ต้องกำหนดตาม validation, capacity และต้นทุนของงานนั้น |
| Association / causal effect | ความสัมพันธ์ที่สังเกตได้ / ผลของการแทรกแซง; association จากข้อมูลนี้ยังไม่พิสูจน์ causal effect |
| PD (probability of default) | ความน่าจะเป็นผิดนัดตาม definition/horizon ที่ระบุ; next-month dataset probability ใช้แทน 12-month regulatory PD ไม่ได้อัตโนมัติ |
| LGD (loss given default) | สัดส่วนความเสียหายเมื่อผิดนัด; ไม่ใช่ target ที่โครงการนี้ประเมิน |
| EAD (exposure at default) | ภาระความเสี่ยง ณ เวลาผิดนัด; BILL_AMT ไม่ได้ยืนยันว่าเป็น regulatory EAD |
| ECL (expected credit loss) | ความเสียหายเครดิตที่คาดว่าจะเกิดตามวิธี/horizon ของงานนั้น; ยังไม่คำนวณจากโมเดลนี้ |
| AML (anti-money laundering) | งานตรวจและป้องกันการฟอกเงิน; suspicious alert หรือ anomaly score ไม่ยืนยัน confirmed laundering |
| Graph / node / edge | ความสัมพันธ์ที่แทนด้วยหน่วยข้อมูลและเส้นเชื่อม เช่น account nodes กับ transfer edges; dataset เดิมไม่มี observed transaction graph |

ดู [README](../README.md), [ผล TabPFN](TABPFN_RESULTS_TH.md) และ [ขอบเขต event ธนาคาร](../research/GRAPH_FRAUD_AND_BANK_EVENT_SCOPE_TH.md) สำหรับตัวอย่างการใช้คำกับหลักฐานจริง
