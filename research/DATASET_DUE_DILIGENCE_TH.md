# การคัดเลือก dataset และสถานะตรวจข้อมูล

ตรวจวันที่ 4 ตุลาคม 2026

> เอกสารนี้บันทึกการคัดกรองก่อนทดลอง ขณะนี้ดาวน์โหลดและตรวจไฟล์ UCI/Kaggle จริงแล้ว ดู [ผล audit และการทดลองล่าสุด](../reports/v1/REPORT_TH.md) ข้อความ pending ด้านล่างเป็นประวัติของรอบแรก

สถานะ: **document-level due diligence completed within available access; raw-file audit pending**

## ข้อเสนอ

เสนอ UCI Default of Credit Card Clients สำหรับเริ่ม benchmark ของลูกหนี้บัตรเครดิตเดิม โดยดาวน์โหลดจากต้นทางเมื่อทำได้ และตรวจความตรงกันของสำเนา Kaggle ก่อนเลือก snapshot งานสมัครสินเชื่อใหม่และ SME ต้องคัด dataset ใหม่ตามโจทย์ ไม่ใช้ข้อมูลชุดนี้แทนเพราะมีคำว่า credit

การเลือกนี้ไม่ได้แปลว่า UCI เป็น dataset ที่ดีที่สุดทุกมิติ แต่เป็นจุดเริ่มที่ตรวจ provenance และสิทธิ์ต้นทางได้ และยอมรับข้อจำกัดทางเวลาอย่างชัดเจน

## 1. หลักเกณฑ์คัดเลือก

| เกณฑ์ | หลักฐานที่ต้องมี | ถ้าไม่มี |
|---|---|---|
| เหตุการณ์เป้าหมาย | default/delinquency definition และ horizon | ห้ามอ้างเป็น PD horizon ที่ต้องการ |
| Population/product | ลูกหนี้เดิม/ผู้สมัคร ประเภทสินเชื่อ ประเทศ ช่วงเวลา | จำกัดความสามารถอ้างผลไปพอร์ตใหม่ |
| Provenance | ผู้เก็บข้อมูล ต้นทาง เวอร์ชัน การแปลง | ไม่เลือกเพราะชื่อ/คะแนน popularity อย่างเดียว |
| สิทธิ์ | terms ของต้นทางและสำเนา | พักไว้จนยืนยันสิทธิ์ตรงกับวัตถุประสงค์ |
| Timing | prediction dates, available_at และ outcome maturity | ไม่มีหลักฐาน out-of-time/point-in-time ที่ครบ |
| Integrity | raw row counts, keys, target counts, domains, duplicates | ต้องตรวจไฟล์ก่อน train |
| Feasibility | format, disk/RAM, join cardinality | ลด scope ตามหลักฐาน ไม่ประกาศว่ารันไหวล่วงหน้า |

## 2. ตัวเลือกที่ค้นและคัดกรอง

| Dataset / link | ผลคัดครั้งนี้ | เหตุผลสำคัญ | สิ่งที่ยังตรวจไม่ได้ |
|---|---|---|---|
| [UCI Default of Credit Card Clients บน Kaggle](https://www.kaggle.com/datasets/uciml/default-of-credit-card-clients-dataset) และ [ต้นทาง](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients) | เลือกแบบมีเงื่อนไขสำหรับ behavioral benchmark | ต้นทางมีคำอธิบายตัวแปรและ CC BY 4.0 | hash/ความตรงกันของสำเนา, category values จริง, duplicates, event prevalence |
| [Home Credit Model Stability](https://www.kaggle.com/competitions/home-credit-credit-risk-model-stability/data) | ไม่เลือกให้โครงการธนาคารทั่วไปโดยไม่มีสิทธิ์เพิ่ม | มีเวลาและหลายตาราง แต่ rules จำกัด Competition Use Only | raw statistics, exact default threshold/horizon, ผู้กู้ซ้ำ, point-in-time semantics |
| [Home Credit Default Risk](https://www.kaggle.com/competitions/home-credit-default-risk/data) | shortlist สำหรับศึกษา application scoring; ยังไม่ผ่าน gate | เป็นการแข่งขันที่ตรงหัวข้อ loan risk มากกว่าข้อมูลบัตรเครดิตเดิม | รอบนี้ยังไม่ได้อ่าน data dictionary/rules ครบหรือ raw files; ไม่ยืนยันจำนวนแถว/numeric target definition |
| [Give Me Some Credit](https://www.kaggle.com/competitions/GiveMeSomeCredit/data) | สำรองเพื่อคัดต่อ | ชื่อการแข่งขันเกี่ยวกับ credit distress แต่ยังไม่อนุมัติจากชื่อ | primary dictionary/rules/raw files และเวลาสำหรับ OOT ยังไม่ยืนยันครบ; จึงไม่คัดลอกจำนวนแถวหรือ target horizon จากบทความทั่วไป |
| [laotse/Credit Risk Dataset](https://www.kaggle.com/datasets/laotse/credit-risk-dataset) | ไม่ใช้เป็นหลักฐานความเสี่ยงจริงในรอบนี้ | Intel example เรียกข้อมูลชุดนี้ว่า simulated; provenance ต้นทางยังไม่ยืนยัน | ใครสร้าง/เก็บ วิธีจำลอง วิธีสร้าง label และ horizon จริง |
| [Lending Club mirror](https://www.kaggle.com/datasets/wordsforthewise/lending-club) | ตัวเลือกคัดต่อเมื่อ application task ชัด | ต้องแยก vintage, status และ outcome maturity อย่างเข้มงวด | รอบนี้ยังไม่ได้ตรวจต้นทาง/สิทธิ์ snapshot/raw schema; ไม่มี license หรือ row-count certification |

คำว่า simulated ของ laotse มาจาก [Intel sample repository](https://github.com/intel-samples/loan-default-risk-prediction) ซึ่งเป็นผู้ใช้ downstream ไม่ใช่หลักฐานจากผู้สร้าง dataset โดยตรง จึงรายงานเป็น provenance concern ไม่ประกาศว่าตรวจวิธีสร้างข้อมูลแล้ว

## 3. สิ่งที่ตรวจจากเอกสาร UCI ได้จริง

ต้นทางระบุ 30,000 instances และ 23 explanatory features มี ID และ binary response แยกจาก features ประวัติชำระ/บิล/ยอดชำระครอบคลุมเมษายน–กันยายน 2005 ในไต้หวัน หน่วยวงเงินและยอดเงินคือ NT dollar เอกสารระบุไม่มี missing values และปัจจุบันระบุใบอนุญาต CC BY 4.0 [UCI documentation](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients)

ตัวเลขนี้เป็น **metadata ของต้นทาง** ไม่ใช่ผลนับจากไฟล์ที่เราโหลดเอง ส่วนชื่อ `default.payment.next.month` เป็นชื่อที่ต้องยืนยันจากไฟล์จริง พร้อมนิยามเหตุการณ์: next-month outcome ไม่เท่ากับการผิดนัดแบบ 90+ DPD ภายใน 12 เดือนโดยอัตโนมัติ ต้องยืนยัน target header/label semantics จาก original file และ paper ก่อนล็อก model card

สำเนาที่เปลี่ยน ID+target ให้เป็น “25 features” จะทำให้จำนวน predictors ผิด ต้องแยก columns ทั้งหมดออกจาก predictive inputs การแบ่ง cohort ต้องไม่อาศัย ID เรียงลำดับหรือเลขเดือนในชื่อ feature เป็นตัวแทน application date

ใบอนุญาตของ mirror ไม่ใช้แทน provenance จากต้นทางโดยอัตโนมัติ หากสำเนาระบุ license ต่างกันให้บันทึกทั้งสองและตรวจสิทธิ์ที่ผู้เผยแพร่มี ในรอบนี้หน้า Kaggle UCI เปิดได้แต่การอ่านข้อความต่อ timeout จึงยังไม่ยืนยัน license ของ mirror เอง

## 4. สิ่งที่ตรวจจากหน้า Home Credit Model Stability ได้จริง

หน้า Data ระบุ `case_id` เป็น key, `date_decision` เป็นวันตัดสินใจ และ `WEEK_NUM` ของ test ต่อจาก train มี depth 0/1/2 พร้อม historical indices และ `feature_definitions.csv` จำนวนทั้งหมดบนหน้าเป็น 138 files, 26.77 GB รวม CSV/Parquet ไม่ใช่ข้อกำหนดว่าต้องโหลดสอง format ทั้งหมด [official data](https://www.kaggle.com/competitions/home-credit-credit-risk-model-stability/data)

เอกสารกล่าวว่า target กำหนดจากการ default หลังระยะหนึ่ง แต่ไม่ระบุระยะเป็นจำนวนในส่วนที่ตรวจ จึง **ไม่เรียกเป็น 12-month PD** และ raw dates/amounts บางกลุ่มถูก transform/mask ต้องตรวจความหมายก่อนคำนวณ economics หรือทำ temporal joins

กฎที่เปิดอ่านจริงมีหัวข้อ Data Access and Use ระบุ “Competition Use Only” และ B.7.A จำกัดการใช้ข้อมูลในงานแข่งขัน/ฟอรัม ไม่ถือว่าการดาวน์โหลดได้หรือการมี mirror ทำให้ได้สิทธิ์ commercial/general project [official rules](https://www.kaggle.com/competitions/home-credit-credit-risk-model-stability/rules)

### จุดที่ต้องตรวจหากมีสิทธิ์ใช้งานชุดนี้ตรงวัตถุประสงค์

- depth 0 ต้องยืนยัน uniqueness ก่อน join; depth 1/2 ต้อง aggregate ตามความหมาย ไม่ join ให้แถว base เพิ่มอย่างเงียบ ๆ
- ต้องรวม shards ทั้งหมดของ train/table group และตรวจ schema compatibility โดยไม่โหลดทั้ง CSV และ Parquet แล้วนับซ้ำ
- `num_groupN=0` มีความหมายพิเศษเมื่อเป็น person index; index ไม่ใช่ predictor เชิงตัวเลขตามธรรมชาติ
- แหล่ง external providers บางตัวอาจไม่มีในอนาคตตามคำอธิบายหน้า Data ต้องทดสอบ dependency และ missing-provider ablation
- `date_decision`, WEEK_NUM และ date-derived predictors ต้องตรวจว่าเป็น metadata ของ competition หรือ feature ที่จะมีในระบบใช้งานจริง
- case-level separation ไม่รับรอง customer-level separation เพราะ case อาจไม่ใช่ผู้กู้ที่ไม่ซ้ำกัน
- hidden test ถูกปิดตามประกาศที่ลิงก์จากหน้า Data อย่าอ้างว่าสามารถใช้ leaderboard เป็น independent validation ได้ในรอบนี้

## 5. Raw audit ที่ยังต้องทำก่อน train UCI

| ตรวจ | วิธีและผลที่ต้องเก็บ | สถานะครั้งนี้ |
|---|---|---|
| Snapshot | download URL, version/time, bytes, SHA-256, license evidence | ยังไม่มีไฟล์ |
| Cross-source equality | เทียบ original XLS กับ Kaggle CSV หลัง normalize headers/order/types; ตรวจเซลล์ด้วย ไม่อาศัย row count อย่างเดียว | ยังไม่ทำ |
| Schema | 23 predictors + ID + target ตามต้นทาง; header และ type จริง | metadata เท่านั้น |
| ID | unique/null/duplicates; ไม่ใช้ ID ทำนาย | ยังไม่ทำ |
| Labels | target domain {0,1}, count ต่อ class, prevalence, null | ยังไม่ทำ; ไม่ใส่ค่าจำจากบทความอื่น |
| Missing | null, empty, special codes; แยก null จริงกับ undocumented category | ยังไม่ทำ |
| Domains | categorical values ที่อยู่นอก dictionary; repayment codes ที่ไม่มีคำอธิบาย | ยังไม่ทำ; ห้ามเดาความหมายแล้ว remap |
| Amounts | zero/negative/extreme bills/payments; units; credit-limit domain | ยังไม่ทำ; negative bill อาจมีเหตุผล ต้องตรวจ |
| Duplicates | แถวซ้ำ, feature-vector ซ้ำเมื่อเอา ID ออก, labels ขัดกันบน feature เดียวกัน | ยังไม่ทำ |
| Split contamination | exact/near duplicates ข้าม split; กลุ่ม feature ที่เหมือนกันต้องพิจารณา grouping | ยังไม่ทำ |
| Timing | mapping เดือน, cutoff, available-at ของ feature และ outcome | เอกสารมีเดือนย้อนหลัง แต่ไม่มีหลักฐาน OOT หลาย cohort |
| Selection | ข้อมูลลูกหนี้เดิม/บัญชีที่สังเกตได้; ไม่มี rejected applicants | ห้ามประเมิน all-applicant policy จากชุดนี้โดยตรง |
| Sensitive/proxy features | ระบุ feature ที่อาจเกี่ยวกับ subgroup; ทดสอบทั้ง policy feature set และ audit-only attributes | ยังไม่ได้กำหนดกฎใช้ feature ของโครงการ |
| Sample sufficiency | events ต่อ split/subgroup/bin; confidence intervals | ยังไม่ทำ |
| Final verdict | ผ่าน integrity gate แล้วเรียกว่า benchmark-ready; ไม่ยกระดับเป็น deployment-ready | pending |

สำหรับ Lending Club หากนำมาคัดต่อ ต้อง audit servicing variables เช่น payment/recovery/last-payment fields เพื่อกัน post-outcome leakage; current loans ไม่ใช่ non-default ที่ mature แล้ว ต้องมี censoring policy หากเลือกเฉพาะ Fully Paid กับ Charged Off ต้องรายงาน selection bias นี่เป็นแผนตรวจ ไม่ใช่ข้อค้นพบจาก snapshot ที่อ่านแล้ว

## 6. ขอบเขตที่ใช้ผลได้

UCI benchmark ที่ทำดีจะตอบได้ว่าโมเดลใดทำนาย label ได้ดีกว่าบน cohort นี้ และ pipeline ทำซ้ำได้หรือไม่ ยังตอบไม่ได้ว่าโมเดลจะเสถียรในปีถัดไป มีผลกับผู้ถูกปฏิเสธสินเชื่ออย่างไร หรือเหมาะกับพอร์ตไทยเพียงใด

ข้อมูลที่จะต้องหาเพิ่มสำหรับใช้งานจริง: borrower/account IDs ที่ควบคุมการเชื่อมโยงได้, product/cohort, timestamps ของเหตุการณ์และการเข้าระบบ, default event และ maturity, ข้อมูล recovery/exposure เมื่อทำ loss modeling และนิยามนโยบายจากเจ้าของงาน

ไม่แปลง probability รายเดือนเป็นรายปีด้วย `1-(1-p)^12` แล้วเรียกว่า PD 12 เดือนจริง สูตรนี้ต้องมีสมมติฐานเกี่ยวกับ hazard และการคงที่ของความเสี่ยงซึ่ง dataset snapshot ไม่ได้พิสูจน์
