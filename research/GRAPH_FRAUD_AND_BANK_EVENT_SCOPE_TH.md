# ข้อมูลปัจจุบันเหมาะกับ Graph ML สำหรับ fraud หรือไม่ และครอบคลุมงานธนาคารอะไรได้

ตรวจวันที่ 5 ตุลาคม 2026 — เป็นการตรวจ raw snapshot ที่มีอยู่และทบทวนหลักฐานเฉพาะโจทย์ ไม่ใช่ systematic review หรือผลทดลอง GNN ใหม่

**ข้อสรุป:** UCI/Kaggle Default of Credit Card Clients ที่ใช้ในโครงการเหมาะกับการทดลองทำนาย **next-month credit-default label ของผู้ถือบัตรเดิม** แต่ยังไม่เหมาะเป็นชุดหลักสำหรับ Graph ML เพื่อวัดความสามารถตรวจ fraud ในธนาคาร มีข้อขาดสองด้าน: ไม่มีความสัมพันธ์ระหว่างหน่วยข้อมูลที่สังเกตจริง และไม่มี fraud outcome ที่ใช้ตรวจผล โมเดลปัจจุบันยังไม่มี bank event ใดที่ผ่านการยืนยันประสิทธิภาพบนข้อมูลธนาคารไทย

## 1. สิ่งที่ตรวจจากไฟล์จริง

รัน [audit_graph_readiness.py](../tools/audit_graph_readiness.py) กับ CSV ที่ดาวน์โหลดไว้ และบันทึก [data_readiness.json](../reports/graph_scope/data_readiness.json) ตรวจครบทุกคอลัมน์ร่วมกับ [UCI data dictionary](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients) ไม่ใช้การหา keyword ของชื่อคอลัมน์อย่างเดียว

| รายการ | หลักฐาน / ความหมาย |
|---|---|
| ขนาด | 30,000 แถว, 23 predictors + ID + target |
| Target | `default.payment.next.month`: 6,636 แถวเป็น 1, 23,364 แถวเป็น 0; อัตรา default label 22.12% เป็นอัตราใน cohort นี้ ไม่ใช่อัตรา fraud |
| ระดับข้อมูล | หนึ่งแถวต่อ ID; จำนวนแถวต่อ ID สูงสุด = 1 |
| ข้อมูลที่มี | วงเงิน, อายุ/ข้อมูลประชากร และ PAY/BILL_AMT/PAY_AMT อย่างละ 6 เดือน |
| เวลา | ประวัติเมษายน–กันยายน 2005 ตาม dictionary; มี historical summaries ในแถวเดียว ไม่ได้มีหลาย prediction cohorts สำหรับทดสอบคนละช่วงเวลา |
| ประเทศ/ผลิตภัณฑ์ | ผู้ถือบัตรเครดิตในไต้หวัน; ไม่ใช่ประชากรผู้สมัครสินเชื่อใหม่หรือธนาคารไทย |
| Missing | ไม่มี missing cells; ไม่ได้แปลว่ามีปัจจัยสำคัญครบหรือ category codes ทุกตัวมีนิยามชัด |
| แถวซ้ำ | 29,944 distinct predictor vectors; 56 extra rows; 21 vector groups รวม 46 แถวมี labels ขัดกัน เป็นสิ่งที่สังเกตได้ ไม่ใช่หลักฐานว่าคนเดียวกันหรือเครือข่าย fraud |
| Provenance | SHA-256 `a0f0ab49d6326671d6cd83be5c88dcf18007025fe9a53ecd699119c871176ca1`; [source audit เดิม](../reports/v3/source_audit.json) เปรียบเทียบกับ UCI CSV/XLS แล้วค่าตรงกัน |

ไฟล์และ dictionary ไม่มี sender/recipient, merchant identifier, device/IP/session identifier, transaction timestamp, ความสัมพันธ์ลูกค้า–บัญชี, fraud investigation outcome หรือ label availability date `ID` มีบทบาทเป็น row identifier โดยไม่มี documented link ไปยัง counterparty จึงสร้างความสัมพันธ์ระหว่างลูกค้าจาก ID นี้ไม่ได้

**ขอบเขต label:** ยังไม่ได้ยืนยัน exact default threshold จึงไม่ตีความว่าเป็น 90+ DPD, NPL, fraud หรือ 12-month regulatory PD อัตโนมัติ ประวัติ PAY ที่ระบุความล่าช้าเป็น input ย้อนหลัง ไม่ใช่ label ว่าลูกค้าจะเข้าแต่ละ DPD bucket ในอนาคต

## 2. ทำกราฟได้ทางเทคนิค แต่กราฟต้องตอบคำถามที่ข้อมูลรองรับ

กราฟสำหรับเครือข่ายเงินโอนอาจกำหนดบัญชีเป็น **node** และรายการโอน `sender → recipient` เป็น **directed edge** พร้อมเวลา ยอดเงิน สกุลเงินและช่องทาง หากคู่บัญชีโอนกันหลายครั้งต้องเก็บหลาย edges หรือ representation ที่รักษาข้อมูลเหล่านั้นไว้ กราฟสำหรับ payment fraud อาจเชื่อม transaction กับบัญชี/อุปกรณ์/merchant ที่มี identifiers เชื่อถือได้ กราฟหลายชนิดของ entity/edge เรียกว่า heterogeneous graph ทั้งสองกรณีต้องตรวจว่า link สื่อถึงอะไรจริง และรู้ link นั้นแล้วหรือยัง ณ เวลาตัดสินใจ

ตัวอย่าง `A → B → C → A` ช่วยให้เห็นเงินเคลื่อนผ่านหลายบัญชี แต่การพบวงจรเป็นเพียงรูปแบบที่ต้องตรวจสอบ ไม่ได้ยืนยันการฟอกเงิน ลูกค้าปกติก็อาจมีความสัมพันธ์หรือพฤติกรรมที่คล้ายกัน ข้อมูล UCI ของเราเห็นเพียงยอดรวมและสถานะรายเดือน จึงมองไม่เห็นเส้นทางนี้

สำหรับ **supervised fraud detector** ต้องมี fraud labels ที่นิยามตรงเหตุการณ์ ส่วน unsupervised graph anomaly detection ฝึกได้โดยไม่มี fraud labels แต่ anomaly score ยังไม่ใช่ความน่าจะเป็น fraud และการวัดว่าจับ fraud ได้จริงต้องมี outcomes/การตรวจสอบที่เชื่อถือได้ การนำ default label มาเป็น fraud label ไม่แก้ข้อจำกัดนี้

ทางเลือกที่ทำได้กับข้อมูลเดิมมีขอบเขตดังนี้:

- สร้าง k-nearest-neighbor graph จากความคล้ายของ predictors แล้วทดลอง **credit-default node classification** ได้ แต่เป็น similarity graph ที่เราสร้างเอง ไม่มีหลักฐานว่าเป็นเครือข่ายบัญชี ผู้ร่วมขบวนการหรือการโอนเงินจริง ต้องวัดประโยชน์เพิ่มจาก baseline ก่อน สำหรับ inductive exploratory protocol ให้ fit scaling/encoding และ neighbor reference เฉพาะ training fold แล้ว query แถวที่ประเมินเข้าหา training references; ไม่ใช้ holdout labels, holdout-wide preprocessing หรือ future holdout rows เปลี่ยน training representation
- แปลงประวัติหกเดือนเป็น node ตาม borrower/month หรือ sequence ได้ แต่เป็นการจัดรูปข้อมูลเดิม ไม่มี borrower-to-borrower relation เพิ่ม และไม่สร้าง transaction/fraud labels ใหม่ ใช้ทั้ง sequence ทำนาย label ที่จุดตัดเดียวได้; อย่าคัดลอก target เดิมไปอ้างว่าเป็น outcome ของแต่ละเดือน เพราะไม่มี historical monthly targets และอย่านับหก nodes เป็นหก independent labeled clients
- การเชื่อมคนเพราะอายุ เพศ การศึกษาเหมือนกัน หรือรวมทุกคนเข้ากับหก calendar-month nodes เดียวกัน ไม่ได้ยืนยันว่าคนเหล่านั้นเกี่ยวข้องกันในเหตุการณ์ fraud; graph messages อาจส่งเพียงข้อมูลกลุ่มกว้างและทำให้ตีความผิด
- จัดแถวที่มี predictor vectors ซ้ำไว้ใน split เดียวกันเพื่อลดความเสี่ยงจาก exact-vector overlap แต่ไม่ได้พิสูจน์ entity resolution ว่าคนเดียวกัน และไม่แก้ temporal/entity leakage ชนิดอื่น Labels ที่ขัดกันอาจเกี่ยวกับปัจจัยที่ไม่ได้บันทึก ความสุ่มของ outcome หรือปัญหา labels; ยังไม่พิสูจน์ noise หรือ irreducible Bayes error การแบ่ง train/test ใหม่บน 30,000 แถวที่ใช้วิจัยไปแล้วไม่ทำให้เกิด independent validation ใหม่

**การตัดสินใจสำหรับโครงการนี้:** คงงาน credit-default เป็นงานที่ทดสอบกับข้อมูลเดิมได้ ถ้าศึกษา similarity GNN ให้ประกาศ target ตามเดิมและทำ exploratory comparison หากต้องการ fraud graph ให้เริ่มจากข้อมูลเหตุการณ์และความสัมพันธ์ที่ตรงโจทย์นั้น

## 3. Literature review ที่เปลี่ยนการตัดสินใจได้

| หลักฐานที่อ่าน | สิ่งที่แหล่งข้อมูลรองรับ | ผลต่อโครงการ |
|---|---|---|
| [Weber et al., 2019: Elliptic](https://arxiv.org/html/1908.02591), §2 และ abstract | Bitcoin transactions เป็น nodes; BTC flows เป็น edges; ทดลองจำแนก illicit transactions และรายงาน RF ดีกว่าโมเดลที่เปรียบเทียบในงานนั้น | ความสัมพันธ์ต้องมาจากธุรกรรมจริง; มีกราฟไม่ได้รับประกันว่า GNN ชนะ tree models และผลบน Bitcoin ไม่ใช่ผลบนบัญชีธนาคารไทย |
| [Dou et al., 2020: CARE-GNN](https://arxiv.org/pdf/2008.08692), §4.1 | ศึกษา feature/relation camouflage; experiments ใช้ Yelp/Amazon reviews ซึ่งมี proxy definitions เช่น helpful votes | เป็นหลักฐานเรื่องการเลือก neighbor/ความหมายของ relation; ไม่ใช่การยืนยันประสิทธิภาพตรวจ fraud ธนาคาร |
| [Huang et al., 2022: DGraph](https://yangy.org/works/dgraph/dgraph_2022.pdf), §3.2 | User nodes และ emergency-contact edges; operational anomaly/fraud label อิงไม่ชำระหนี้เป็นเวลานานและไม่ตอบ reminders | อ่าน label definition ให้ละเอียด แม้ผู้สร้างเรียกว่า fraud ก็ไม่ใช้แทน confirmed transaction fraud หรือพิสูจน์เจตนาฉ้อโกง |
| [Altman et al., 2023: AMLworld](https://proceedings.neurips.cc/paper_files/paper/2023/file/5f38404edff6f3f642d6fa5892479c42-Paper-Datasets_and_Benchmarks.pdf), §3 และ Fig. 1–2 | สร้าง synthetic financial transactions และ laundering labels; มีหลายรูปแบบการเคลื่อนเงิน เช่น fan-in/fan-out/cycles | เหมาะตรวจ pipeline และความสามารถจับรูปแบบที่จำลองไว้ ต้องแยกผล synthetic ออกจากผล fraud/AML จริง |
| [Egressy et al., 2024: directed multigraph GNN](https://ojs.aaai.org/index.php/AAAI/article/download/29069/30025), หน้า 11838–11840 | วิเคราะห์ direction, parallel edges และ adaptations ของ GNN; reverse message passing แยกการรับข้อมูลจาก incoming/outgoing edges | อย่ารวม repeated transfers เป็นเส้นเดียวหรือทำทุก edge เป็น undirected โดยไม่มี ablation; ความสามารถเชิงโครงสร้างไม่ใช่การรับประกันความแม่นยำทุกธนาคาร |

[Amazon Science / AWS implementation](https://www.amazon.science/code-and-datasets/amazon-sagemaker-and-deep-graph-library-for-fraud-detection-in-heterogeneous-graphs) แสดงการสร้าง heterogeneous graph จาก IEEE-CIS tabular transactions จึงไม่จำเป็นต้องได้ข้อมูลเป็น graph file ตั้งแต่ต้น แต่ต้องมี relational attributes ที่ใช้สร้าง edges ได้ ตัวอย่างนี้เป็น implementation reference ไม่ใช่งานพิสูจน์ว่า approach นี้ดีที่สุดทั่วไป

นี่เป็นการเลือกอ่านงานที่ช่วยตัดสินใจเรื่อง **task, graph, label และ validation** ไม่ได้จัดอันดับ SOTA ปี 2026 และไม่ได้ replicate ตัวเลขใน papers

## 4. Event ในธนาคารที่ข้อมูล/โมเดลปัจจุบันครอบคลุมได้แค่ไหน

คำว่า “ทดลองได้” ในตารางหมายถึง target/input ของ dataset สอดคล้องกับ prototype ไม่ใช่ผ่านการยืนยันใช้งานจริง ทุก use case ยังต้องประเมินข้อมูลและ outcomes ของธนาคารเป้าหมาย

| เหตุการณ์ / งาน | ข้อมูลเดิมรองรับอะไร | สิ่งที่ต้องเพิ่มเพื่อประเมินงานจริง |
|---|---|---|
| ผู้ถือบัตรเดิมผิดนัดในเดือนถัดไป | **ทดลองทำนาย dataset label ได้โดยตรง**; เป็นงานหลักของ V2 | นิยาม default/จุดตัดเวลาให้ตรงกัน, cohort ธนาคารไทยหลายเดือน, independent temporal test และ calibration |
| รายชื่อเฝ้าระวังรายเดือน / จัดลำดับเจ้าหน้าที่ตรวจลูกหนี้ | **ศึกษาการจัดอันดับ default risk ได้**; ยังไม่ได้ทดสอบผลลัพธ์ของ workflow | Outcomes และ capacity/cost ของการตรวจ; ข้อมูล ณ จุดตัดรายเดือน; threshold ที่เลือกบน validation |
| เข้าค้างชำระ 30/60/90 วัน, กลับมาชำระปกติ, re-default | มี historical PAY inputs แต่ **ไม่มี future labels แยกเหตุการณ์เหล่านี้** | Due date, actual payment dates, outstanding history และ repeated longitudinal cohorts พร้อม labels แต่ละ horizon |
| เลือกมาตรการติดตามหนี้ / ปรับโครงสร้าง / เพิ่มลดวงเงิน | มีวงเงินและประวัติชำระ แต่ **ไม่ได้เรียนรู้ผลของมาตรการ** | Action history, recoveries และ outcome/cost; การประเมินผลของ action ที่เหมาะสม ไม่ตีความ default association เป็น causal effect |
| อนุมัติผู้สมัครใหม่ / สินเชื่อบ้าน / สินเชื่อธุรกิจ | **ไม่ครอบคลุม population/product เหล่านี้**; ประวัติบัตรเดิมอาจยังไม่เกิด ณ เวลาสมัคร | Application-time features, income/liabilities/affordability/product/collateral และ outcomes ของประชากรเป้าหมาย รวมข้อจำกัดเรื่อง rejected applicants |
| Fraud บัตร/ซื้อสินค้าออนไลน์ รายธุรกรรม | **ไม่มี transaction-fraud target หรือ event-level inputs** | Transaction, account/card token, merchant, timestamp/channel, device/session และ fraud/chargeback outcomes ที่นิยามและตรวจสอบแหล่ง label |
| หลอกโอนเงิน / บัญชีม้า / เครือข่ายโอนหลายทอด | **ไม่มี sender–recipient graph หรือ case labels** | Account-transfer network พร้อมเวลา, linkage ที่เชื่อถือได้ และ labels เฉพาะ scam/mule event; laundering label ไม่เท่ากับ mule label ทุกกรณี |
| Account takeover / สมัครด้วยตัวตนปลอม | **ไม่มี authentication/KYC/application events หรือ labels** | Login/device/IP/session changes, authentication outcomes หรือ KYC/application/linkage records และ case disposition ตามโจทย์ |
| AML suspicious-transaction prioritization | **ไม่มี transaction network หรือ AML outcomes** | Transfer graph, investigation dispositions และเวลาที่ทราบผล; suspicious alert ไม่ใช่ confirmed laundering และยังมี unknown cases |
| LGD / EAD / expected credit loss / stress testing | **ไม่ใช่ targets ที่โมเดลนี้ทำนาย**; BILL_AMT ไม่ได้เป็น regulatory EAD โดยนิยาม | Default exposure, recoveries/cost/collateral, horizon-consistent PD, macroeconomic/scenario inputs และวิธีคำนวณตามงานนั้น |

[BOT Credit Risk Framework](https://www.bot.or.th/content/dam/bot/documents/th/our-services/Member-corner/manual-of-supervision/Credit-risk-framwork-2567-attachment.PDF) กล่าวถึง PD ใน 12 เดือนข้างหน้าใน borrower rating และแยก LGD/EAD/องค์ประกอบความเสี่ยงอื่น (PDF หน้า 18 และ 20) จึงไม่เอา probability ของ next-month dataset label มาใช้แทนทั้งระบบเครดิต งานส่วนนี้เป็นการตรวจขอบเขตความสอดคล้อง ไม่ใช่การรับรองผ่านข้อกำกับ

## 5. Dataset ที่ควรพิจารณาสำหรับ graph fraud ต่อ

สถานะของชุดใหม่ด้านล่างคือ **ตรวจเอกสารผู้สร้าง/paper แล้ว ยังไม่ได้ดาวน์โหลดและ audit raw files ในรอบนี้** จึงยังไม่รับรอง missingness, exact file sizes, joins, splits, leakage หรือ license compatibility ของไฟล์ที่เลือก ไม่รวมข้อมูลใหม่เหล่านี้เข้ากับ UCI แล้วถือว่าเป็นบุคคลเดียวกัน

| เป้าหมาย | Candidate และข้อมูลที่เอกสารรองรับ | ข้อจำกัด / คำตัดสิน |
|---|---|---|
| การโอนระหว่างบัญชี / รูปแบบ AML | [IBM AML-Data บน Kaggle](https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml), [เอกสารผู้สร้าง](https://github.com/IBM/AML-Data) | **ตัวเลือกแรกสำหรับ prototype กราฟโอนเงินตามข้อเสนอของเรา** มี transaction/laundering tags แต่ทั้งหมดเป็น synthetic; ผลวัดเฉพาะรูปแบบจำลอง ไม่ใช่การยืนยันจับบัญชีม้าจริง ข้อมูลใช้ CDLA-Sharing-1.0 ตามผู้สร้าง; license repo Apache-2.0 ไม่ใช่ license data |
| Payment/e-commerce transaction fraud | [IEEE-CIS](https://www.kaggle.com/competitions/ieee-fraud-detection/data), [AWS graph example](https://aws.amazon.com/blogs/machine-learning/detecting-fraud-in-heterogeneous-networks-using-amazon-sagemaker-and-deep-graph-library/) | **เลือกเมื่อโจทย์คือ transaction fraud** มี transaction/identity tables; anonymous attributes และ shared values ต้องตรวจความหมายก่อนถือว่าเป็นตัวบุคคล/อุปกรณ์เดียวกัน; graph ต้องเคารพ prediction-time cutoff ไม่สร้างจาก future transactions ทั้งไฟล์; webpage Kaggle อ่าน body ไม่ได้ในเครื่องมือรอบนี้ จึงใช้เอกสาร implementation corroborate โครงสร้าง ไม่อ้างว่า raw files ตรวจผ่าน |
| ศึกษา flow graph และ illicit transaction บน crypto | [Elliptic paper](https://arxiv.org/html/1908.02591), [ผู้สร้าง](https://www.elliptic.co/newsroom/elliptic-releases-bitcoin-transactions-data/) | มี directed flow graph จริง แต่เป็น Bitcoin; unlabelled transactions ต้องรักษาเป็น unknown ไม่ติดป้าย legitimate; ไม่ถ่ายผลไปยังการโอนบัญชีธนาคารโดยอัตโนมัติ |
| Contact-network anomaly ใน consumer lending | [DGraph paper](https://yangy.org/works/dgraph/dgraph_2022.pdf), [PyG DGraphFin docs](https://pytorch-geometric.readthedocs.io/en/latest/generated/torch_geometric.datasets.DGraphFin.html) | สำหรับ contact-network task ที่ยอมรับ operational label ของผู้สร้าง; ไม่ใช่ชุดหลักสำหรับ confirmed payment fraud, ATO หรือ AML; exact variant/split/terms ต้องตรวจอีกครั้งก่อนใช้ |

ไม่มีชุดเดียวในรายการนี้ครอบคลุม fraud ทุกประเภท ผู้ใช้ควรเลือก **event ที่จะให้ model ทำนาย** ก่อน เช่น transaction fraud หรือ account-level mule case แล้วเลือก unit ของ label และ graph ให้ตรงกัน ไม่เริ่มจากชื่อ algorithm แล้วตีความ dataset ให้เข้ากับชื่อ

## 6. Approach ที่เสนอให้ทดลองเมื่อได้ข้อมูลใหม่

ข้อเสนอนี้เป็น research design ยังไม่ได้ติดตั้ง graph stack หรือฝึก model ในรอบนี้

1. ระบุ unit, event definition, prediction time, label horizon และเวลาที่ label พร้อมใช้ สร้างตาราง `events` แยกจาก `labels`; ทุก feature/edge ที่ใช้ทำนายต้องพร้อมแล้ว ณ prediction time เก็บ occurrence time และ ingestion/availability time เมื่อมีความล่าช้า
2. ถ้าเป็น transfers ใช้ `account → account` directed multigraph โดย key บัญชีรวม bank identifier เพื่อป้องกัน identifier ชนกัน; ถ้าเป็น payment fraud ใช้ heterogeneous graph ของ transaction กับ entities ที่นิยามและ link ได้จริง อย่าใช้ demographic similarity เป็นหลักฐานการร่วมขบวนการ
3. เปรียบเทียบ **CatBoost/LightGBM จาก tabular events → trees เพิ่ม historical graph features → GNN** บน cohorts/inputs/cutoffs เดียวกัน Graph features อาจใช้จำนวน counterparties, incoming/outgoing activity และเส้นทางที่มีในอดีต; ต้องทดสอบประโยชน์จริง ไม่สรุปว่า degree สูงแปลว่า fraud
4. เริ่ม GNN ที่รักษา edge type/direction และ event attributes; R-GCN/HeteroConv เป็น candidates สำหรับ heterogeneity ส่วน directed message passing / Multi-GNN เป็น candidates เมื่อมี repeated transfers ไม่เลือกว่าดีที่สุดก่อนเห็นผลที่ตรวจสอบได้
5. แบ่ง train/validation/test ตาม **prediction timestamp ของ event**; ในการทำนายเมื่อเกิดธุรกรรม timestamp นี้ตรงกับ event occurrence time ส่วนงานตรวจย้อนหลังให้ระบุ prediction timestamp แยกต่างหาก ณ training cutoff ใช้เฉพาะ labels ที่รู้ผลแล้วตาม label availability time; pending/unknown ไม่เท่ากับ negative ตรวจ outcomes ใน evaluation cohorts ให้มีระยะติดตามและความสมบูรณ์เพียงพอตาม label definition ห้ามใช้วันยืนยัน label เป็นแกนแบ่งจนสลับลำดับ prediction time
6. สร้าง graph snapshot ณ แต่ละ prediction time โดยใช้ links/events/features ที่พร้อมแล้ว ห้ามใช้ future edges หรือ held-out labels ผ่าน neighbor messages ธุรกรรมที่เกิดในอดีตและยังไม่มีผลสอบสวนสามารถเป็น unlabeled historical context ได้; การใช้ fraud status ของมันเป็น feature ต้องรอเวลาที่รู้ผล บัญชีเดิมที่เคยอยู่ใน train graph อาจปรากฏอีกได้ในการทำนายอนาคต จึงวัด temporal generalization และ unseen-entity performance แยกกัน หากทำ static transductive benchmark ให้รายงานข้อมูลที่เห็นและถือผลตาม setting นั้น ไม่ใช้แทนการทดสอบอนาคต
7. วัด average precision, precision/recall ที่ investigation budget คงที่, false alerts ต่อจำนวน events และ latency; วัด monetary loss capture เมื่อมี loss labels ที่เชื่อถือได้ AUC ของ credit-default model เดิมไม่วัด fraud performance; ไม่ตั้ง threshold จากอัตรา 22.12% ของ UCI
8. ทำ failure analysis แยก unseen accounts/devices, low-degree/isolate nodes, shared infrastructure, missing identifiers, time drift และ unknown labels; ablation แบบ no-edge/edge shuffle/edge-type removal ช่วยตรวจว่าได้ประโยชน์จาก relationships จริงหรือจาก feature/leakage ถ้าการ shuffle ยังใช้ node degrees เดิมต้องระบุว่าไม่ได้ลบ graph signal ทุกชนิด
9. Freeze pipeline และเกณฑ์เลือกก่อน independent future test จาก population เป้าหมาย ผลจาก synthetic ใช้ยืนยันพฤติกรรมบน scenario ที่จำลองไว้; ผลจาก bank cohort ใช้ประเมินความสามารถใน cohort/horizon ที่ตรวจจริง และวัดผลของ intervention แยกต่างหาก

Prototype stack ที่เสนอ: Python + pandas/Parquet หรือ DuckDB สำหรับ joins/event-time tables; CatBoost/LightGBM สำหรับ baselines; PyTorch + [PyTorch Geometric HeteroConv](https://pytorch-geometric.readthedocs.io/en/latest/generated/torch_geometric.nn.conv.HeteroConv.html) สำหรับ candidate GNN; JSON/CSV/Parquet/SHA-256 + pytest สำหรับ artifacts/data contracts ยังไม่จำเป็นต้องเพิ่ม graph database จนกว่าจะมี requirement เรื่อง query/serving ที่แสดงประโยชน์ชัดเจน agent ช่วยค้นข้อมูล ตรวจคุณภาพและสรุป case พร้อมหลักฐาน ส่วน score ต้องมาจาก pipeline/version ที่ตรวจซ้ำได้

## 7. Reference verification และขอบเขตการตรวจ

ใช้ workflow ของ ref-verify แบบ manual เพราะไม่มี CLI ใน PATH อ่าน full text เมื่อใช้ claims เรื่อง construction/label/mechanism ไม่ได้อ้างว่า CLI audit หรือ independent replication เกิดขึ้น ตรวจ metadata เทียบมากกว่าหนึ่ง record ตามรายการด้านล่าง ข้อความหลักฐานสั้นรวมไม่เกิน 25 คำต่อ paper

- **Weber, Domeniconi, Chen, Weidele, Bellei, Robinson, Leiserson (2019).** *Anti-Money Laundering in Bitcoin: Experimenting with Graph Convolutional Networks for Financial Forensics.* Workshop tutorial, KDD Anomaly Detection in Finance; ไม่ใช่ main-track comparative bank benchmark. [arXiv record](https://arxiv.org/abs/1908.02591) และผู้สร้าง Elliptic ยืนยัน paper; full text §2.1 ระบุ “the nodes represent transactions and the edges represent the flow of Bitcoin currency”. Metadata verified; ข้อความผู้สร้างใช้ชื่อย่อ “Experiments” แต่ arXiv/full text ใช้ “Experimenting” จึงใช้ชื่อตามต้นฉบับ ไม่มี publisher DOI ที่ตรวจในรอบนี้
- **Dou, Liu, Sun, Deng, Peng, Yu (2020).** *Enhancing Graph Neural Network-based Fraud Detectors against Camouflaged Fraudsters.* CIKM, 315–324, DOI [10.1145/3340531.3411903](https://doi.org/10.1145/3340531.3411903). Crossref metadata และ arXiv ตรงกัน; DOI ส่งไป ACM แล้วได้ HTTP 403; อ่าน full text arXiv ได้ §4.1: “We use the Yelp review dataset” และ “Amazon review dataset”. Content verified; publisher page access restricted, ไม่ใช่ DOI ตาย
- **Huang, Yang, Wang, Wang, Zhang, Xu, Chen, Vazirgiannis (2022).** *DGraph: A Large-Scale Financial Dataset for Graph Anomaly Detection.* NeurIPS 35, Datasets and Benchmarks. [Proceedings](https://proceedings.neurips.cc/paper_files/paper/2022/hash/8f1918f71972789db39ec0d85bb31110-Abstract-Datasets_and_Benchmarks.html) และ [arXiv](https://arxiv.org/abs/2207.03579) ยืนยัน title/authors/year; full text §3.2: “label nodes based on their borrowing behaviors”. NeurIPS metadata ลง DOI `10.52202/068431-1654`; web DOI resolver เปิดไม่สำเร็จรอบนี้ จึงไม่รับรอง DOI resolution
- **Altman, Blanuša, von Niederhäusern, Egressy, Anghel, Atasu (2023).** *Realistic Synthetic Financial Transactions for Anti-Money Laundering Models.* NeurIPS 36, Datasets and Benchmarks. [Proceedings](https://proceedings.neurips.cc/paper_files/paper/2023/hash/5f38404edff6f3f642d6fa5892479c42-Abstract-Datasets_and_Benchmarks.html) และ [arXiv](https://arxiv.org/abs/2306.16424) ยืนยัน metadata; full text Fig. 1–2/§3 รองรับรูปแบบ graph และ synthetic labels; ข้อความหลักฐาน: “a set of synthetically generated AML (Anti-Money Laundering) datasets”. DOI `10.52202/075280-1300` จาก proceedings เปิด resolver ไม่สำเร็จ จึงไม่รับรอง DOI resolution
- **Egressy, von Niederhäusern, Blanuša, Altman, Wattenhofer, Atasu (2024).** *Provably Powerful Graph Neural Networks for Directed Multigraphs.* AAAI 38(10), 11838–11846, DOI [10.1609/aaai.v38i10.29069](https://doi.org/10.1609/aaai.v38i10.29069). Publisher, Crossref และ arXiv ยืนยัน metadata; DOI redirect ไป publisher HTTP 200, title ไม่ปรากฏใน body ที่ urllib อ่าน แต่ web reader อ่าน publisher title/full paper ได้ ข้อความหลักฐานใน full text หน้า 11840: “a separate message-passing layer for the incoming and outgoing edges”. Content verified; arXiv submission ปี 2023 และ publication ปี 2024 เป็นคนละวันที่ ไม่ใช่ metadata conflict

ไม่พบ retraction notice ใน records/pages ที่เปิดอ่านหรือจาก targeted title/retraction searches การตรวจนี้ไม่รับรองว่าครอบคลุมฐานข้อมูลถอนบทความทั้งหมด Source claims ที่ใช้เป็นคำอธิบายข้อมูล/วิธีในขอบเขตที่อ่านได้; คำแนะนำเรื่อง dataset/approach/event coverage เป็น synthesis ของโครงการ ไม่ใช่ผลทดลองเพิ่มเติมจาก papers

agy review ผ่าน native CLI ใน plan mode สำเร็จ โดยได้รับ note ฉบับก่อนแก้ครบทั้งฉบับและ raw-audit JSON เป็น supplied-material review ไม่มี independent source/raw-file inspection และไม่เรียก Gemini CLI ดู [review disposition](AGY_GRAPH_SCOPE_REVIEW_TH.md) สำหรับข้อเสนอที่รับ ปรับความหมาย หรือไม่รับ ไม่ถือว่าความเห็น agent เป็นหลักฐานว่าข้อมูลใหม่หรือ model ผ่านการตรวจแล้ว
