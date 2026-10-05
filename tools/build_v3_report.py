"""Build a Thai report directly from measured artifacts; never infer missing results."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from creditrisk.artifacts import read_json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/experiment_v3"


def main():
    selection = read_json(OUT / "selection.json")
    results = read_json(OUT / "reference_results.json")
    analysis = read_json(OUT / "analysis.json")
    verification = read_json(OUT / "verification.json")
    slices = pd.read_csv(OUT / "failure_slices.csv")
    capacity = pd.read_csv(OUT / "capacity_comparison.csv")
    lines = [
        "# ผลวิจัย credit-default รอบสาม และ failure analysis",
        "",
        "5 ตุลาคม 2026 — non-commercial research — Taiwan 2005 UCI/Kaggle cohort เดิม",
        "",
        (
            "**ผลการตัดสินใจ: เปลี่ยนเป็น V3**"
            if selection["gate_passed"]
            else "**ผลการตัดสินใจ: คง V2; candidate รอบสามไม่ผ่าน gate ที่ล็อกก่อนรัน**"
        ),
        "",
        "รอบนี้ปรับวิธีเลือกความลึก/จำนวนต้นไม้ให้ใช้ inner group folds ก่อน refit outer train ทั้งชุด โดยไม่มี outer eval_set แยก schema, features, calibration, model adapters และ scoring เป็น package ที่ตรวจด้วย tests ได้ ไม่เปลี่ยนข้อมูลเดิมหรือ feature values เพื่อให้คะแนนดูดีขึ้น",
        "",
        "## ผล OOF บน original fit 16,500 แถว",
        "",
        "| กระบวนการ | ROC-AUC ↑ | AP ↑ | Log loss ↓ | Brier ↓ |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, key in (
        ("V2 frozen blend", "baseline_v2_oof"),
        ("V3 nested candidate", "candidate_oof"),
    ):
        m = selection[key]
        lines.append(
            f"| {name} | {m['roc_auc']:.6f} | {m['average_precision']:.6f} | {m['log_loss']:.6f} | {m['brier']:.6f} |"
        )
    lines.extend(
        [
            "",
            f"Pooled log-loss gain = {selection['log_loss_gain']:.9f}; เปรียบเทียบแบบจับคู่บนแถว/folds เดิม มี historical model/feature selection จึงไม่ใช่คะแนนยืนยันจากข้อมูลใหม่",
            "",
            "| Outer fold | Inner-selected depth | Refit trees | Candidate log loss | Candidate − V2 log loss |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row, delta in zip(
        selection["outer_search"], selection["fold_log_loss_deltas"], strict=True
    ):
        search = row["search"]
        lines.append(
            f"| {row['fold']} | {search['selected_config']['depth']} | {search['refit_iterations']} | {row['metrics']['log_loss']:.6f} | {delta:+.6f} |"
        )
    lines.extend(["", "| Gate ที่กำหนดล่วงหน้าสำหรับรอบนี้ | ผล |", "|---|---|"])
    names = {
        "minimum_gain": "Log-loss gain ≥ .001",
        "all_folds_improve": "Log loss ดีขึ้นทุก outer fold",
        "brier_not_worse": "Pooled Brier ไม่แย่ลง",
        "quiet_segment_not_materially_worse": "Quiet-segment log loss เพิ่มไม่เกิน .001",
    }
    lines.extend(
        f"| {names[key]} | {'PASS' if passed else 'FAIL'} |"
        for key, passed in selection["gate_checks"].items()
    )
    lines.extend(
        [
            "",
            "คะแนน pooled ดีขึ้นยังไม่พอสำหรับเปลี่ยนโมเดลตามเกณฑ์นี้ หากหนึ่งเงื่อนไขไม่ผ่านให้คง V2 ไม่เปลี่ยน gate หรือเพิ่ม candidates หลังเห็นผล การบังคับทุก fold เป็น development criterion ที่เลือกไว้ ไม่ใช่ statistical significance test",
            "",
            "## Old validation/test หลังล็อก gate: ใช้เชิงพรรณนาเท่านั้น",
            "",
            "| Pipeline | Partition | Calibration | AUC | AP | Log loss | Brier |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in results["results"]:
        lines.append(
            f"| {row['pipeline']} | {row['partition']} | {row['calibration']} | {row['roc_auc']:.6f} | {row['average_precision']:.6f} | {row['log_loss']:.6f} | {row['brier']:.6f} |"
        )
    final_search = results["final_search"]
    lines.extend(
        [
            "",
            f"Final nested candidate เลือก depth {final_search['selected_config']['depth']}, {final_search['refit_iterations']} trees จาก inner procedure บน fit 16,500 ใหม่ ไม่ดึง depth/trees จาก outer scores มาเลือก การเลือก calibrator ใช้ group folds ใน calibration 4,500 เดิม และทั้งสอง pipeline ประเมิน references หลัง gate ล็อกแล้ว",
            "",
            "แม้คะแนน old test จะดีขึ้นก็ไม่ใช้เปลี่ยนคำตัดสินหรือจูนต่อ; old test เคยใช้ในงานเดิม จึงไม่ใช่ independent holdout การ split ใหม่จากแถวเดิมไม่แก้ข้อจำกัดนี้",
            "",
            "## Failure analysis: สัญญาณใดดีขึ้น และสิ่งใดยังไม่แก้",
            "",
            "| Partition / slice | Rows / events | V2 LL | V3 LL | V2 AUC | V3 AUC | V2 FN@.5 | V3 FN@.5 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for partition in ("development_oof", "exposed_test"):
        for label in (
            "no_positive_pay_code",
            "any_positive_pay_code",
            "quiet_zero_payments_3plus",
            "quiet_zero_payments_under3",
        ):
            group = slices.loc[(slices.partition == partition) & (slices.slice == label)].set_index(
                "pipeline"
            )
            ref, candidate = group.loc["v2_reference"], group.loc["v3_candidate"]
            lines.append(
                f"| {partition}/{label} | {int(ref['rows'])}/{int(ref.events)} | {ref.log_loss:.6f} | {candidate.log_loss:.6f} | {ref.roc_auc:.6f} | {candidate.roc_auc:.6f} | {int(ref.fn)} | {int(candidate.fn)} |"
            )
    quiet = slices.loc[
        (slices.partition == "exposed_test") & (slices.slice == "no_positive_pay_code")
    ].set_index("pipeline")
    base, new = quiet.loc["v2_reference"], quiet.loc["v3_candidate"]
    lines.extend(
        [
            "",
            f"Quiet group บน old test มี {int(base['rows'])} แถว/{int(base.events)} events; V2 mean probability {base.mean_probability:.4f}, V3 {new.mean_probability:.4f}, observed rate {base.event_rate:.4f} ให้ดูแยกจาก recall@.5 ซึ่งขึ้นกับ threshold มาก ทั้งสองตัวเลขไม่บอกสาเหตุของ default",
            "",
            "การใช้ threshold .5 ในกลุ่มที่มี event rate ประมาณ .12 ทำให้เกิด FN จำนวนมากตามคะแนนที่วัด แต่ไม่ใช่ข้อกำหนดการปล่อยสินเชื่อ การลด threshold เปลี่ยนจำนวนที่ส่งตรวจและ FP/FN ไม่ได้ทำให้ AUC/log loss ของโมเดลดีขึ้นโดยตัวมันเอง ต้องมีต้นทุน/ความสามารถตรวจเคสที่ทราบก่อนออก policy",
            "",
            f"OOF quiet-group log-loss delta = {selection['quiet_segment_log_loss_delta']:+.9f} จึงยังไม่เห็นการแก้ปัญหานี้อย่างมีสาระจากการเปลี่ยนวิธีเลือกต้นไม้เพียงอย่างเดียว ภายในกลุ่มมีความต่างของ zero-payment/bill/code histories จาก EDA จริง แต่ features เดิมมีสรุปเหล่านี้แล้ว การทดลองนี้ไม่ได้เพิ่มสัญญาณใหม่",
            "",
            "**สมมติฐานที่ยังไม่พิสูจน์:** จำนวนต้นไม้ที่เลือกจาก inner training ขนาดประมาณ 7,333 แถวอาจเหมาะต่างจาก outer refit ประมาณ 11,000 แถว; median-tree rule ไม่รับประกัน optimum ของขนาดใหม่ ความแปรปรวนของการเลือกและ fixed blend อาจอธิบาย fold ที่แย่ลงได้ แต่ยังไม่ใช่ causal attribution ห้ามจูน iteration multiplier ย้อนหลังให้ fold นี้ดีขึ้นแล้วอ้างเป็น independent improvement",
            "",
            "ยังไม่มีข้อมูลรายได้ ภาระหนี้นอกบัญชี หรือเหตุการณ์ใหม่ที่วัดใน CSV นี้ ไม่อ้างว่าปัจจัยใดทำให้ทำนายพลาด และ exact-vector label conflicts ไม่ใช่หลักฐานให้แก้/ลบ labels",
            "",
            "## Review capacity บน old test",
            "",
            "| จำนวนแถวที่เลือกตรวจ | V2 captured events | V3 captured events |",
            "|---|---:|---:|",
        ]
    )
    test_capacity = capacity.loc[capacity.partition == "exposed_test"]
    for fraction, group in test_capacity.groupby("capacity"):
        counts = group.set_index("pipeline").events_captured
        lines.append(
            f"| {fraction:.0%} | {int(counts['v2_reference'])} | {int(counts['v3_candidate'])} |"
        )
    lines.extend(
        [
            "",
            "ใช้ fixed top-N และ stable tie ordering เพื่อเปรียบเทียบเท่านั้น ไม่เลือก capacity ที่ดูดีที่สุดจาก old test ไปกำหนด business policy",
            "",
            "## Uncertainty และข้อจำกัด",
            "",
            "300 paired exact-vector group bootstrap replicates จาก probabilities ที่ตรึงแล้ว; ต่อไปนี้เป็น candidate − V2, conditional descriptive percentile intervals ไม่รวม adaptive selection/training variance หรือความทับซ้อนของ CV training sets และไม่อ้าง formal coverage",
            "",
            "| Partition | AUC difference interval | Log-loss difference interval | Brier difference interval |",
            "|---|---|---|---|",
        ]
    )
    for partition, record in analysis["paired_group_bootstrap"].items():
        bounds = record["percentile_95_differences"]
        formatted = [
            f"[{bounds[name][0]:+.6f}, {bounds[name][1]:+.6f}]"
            for name in ("roc_auc", "log_loss", "brier")
        ]
        lines.append(f"| {partition} | {' | '.join(formatted)} |")
    lines.extend(
        [
            "",
            "Nested inner selection แก้ขอบเขตการ fit ของรอบนี้ แต่ไม่ลบประวัติที่เลือก data/features/architecture จาก cohort นี้ ต้อง freeze pipeline ก่อนเปิด labeled cohort ใหม่ซึ่งตรง target/population และแยกเวลา/borrower จึงจะอ้าง independent validation ได้",
            "",
            "## Clean code และหลักฐานตรวจ",
            "",
            "- `src/creditrisk` แยกหน้าที่และใช้ CLI `credit-risk`/`python -m creditrisk.cli`; input schema และ probability checks ชัดเจน ไม่อาศัยตัวแปร global ของ legacy experiment ใน inference",
            "- feature migration ตรงกับ V2 ทุกเซลล์ของจริง 30,000 แถว (37/68/64 columns ตาม variant) และไม่ขึ้นกับ ID/target",
            "- clean V2 refit ได้ metrics ตรงเดิม และเปรียบเทียบ probability ทุกแถวกับ local historical V2 artifacts ตาม `verification.json`",
            "- saved model ตรงผล reference ที่ gate เลือก; single/batch/nonunique-index/reload parity ผ่าน; group/hash/ID/order/metric checks ผ่าน",
            "- unit tests รวม real small CatBoost model ปกป้อง boundaries/invalid inputs/unknown categories/zero denominators ไม่ใช้ raw downloaded data หรือ token; Ruff lint/format และ compile checks ใช้กับ maintained code",
            "- historical V1/V2 scripts/outputs คงหลักฐานเดิม และ Git attributes รักษา byte hashes ของ historical scripts/public evidence; raw data/models/.env/local agent logs ถูก ignore",
            "- native agy method/code review เป็น supplied-material review; primary researcher ตรวจข้ออ้างและข้อแก้จริง ไม่ใช้คำเสนอของ agent แทน measurements ไม่มี Gemini CLI",
            "",
            "CLI preflight ครั้งแรกพบ dispatch `cv`/`run_cv` ไม่ตรงกันก่อนเริ่ม model fit แก้ entry point เพิ่ม regression test และเก็บ unused protocol/failure record ใน `outputs/experiment_v3/preflight_failed` แล้ว freeze corrected protocolก่อน training ไม่มีผลลัพธ์ถูกใช้เปลี่ยน grid/gate",
            "",
            "## ทำซ้ำและใช้ pipeline ที่ผ่านการเลือก",
            "",
            "```powershell",
            "uv pip install --python .venv\\Scripts\\python.exe -r requirements-core.txt -r requirements-dev.txt -e .",
            ".venv\\Scripts\\python.exe scripts/fetch_data.py",
            ".venv\\Scripts\\python.exe tools/verify_input_sources.py",
            ".venv\\Scripts\\python.exe tools/verify_feature_migration.py",
            ".venv\\Scripts\\python.exe -m creditrisk.cli prepare",
            ".venv\\Scripts\\python.exe -m creditrisk.cli cv",
            ".venv\\Scripts\\python.exe -m creditrisk.cli select",
            ".venv\\Scripts\\python.exe -m creditrisk.cli finalize",
            ".venv\\Scripts\\python.exe tools/analyze_v3.py",
            ".venv\\Scripts\\python.exe tools/build_v3_report.py",
            "```",
            "",
            "ใช้ workspace/output ใหม่สำหรับ rerun ไม่เขียนทับ completed artifacts; full legacy/TabPFN environment เก็บใน `requirements.lock.txt` แยกจาก core experiment ไม่ต้องมี TabPFN key สำหรับรอบนี้",
            "",
            "![Development diagnostics](diagnostics.png)",
            "",
            "ดู [literature review และ data exploration](../../research/ITERATION_3_RESEARCH_TH.md), [protocol](protocol.json), [selection](selection.json), [verification](verification.json), [AGY review disposition](../../research/AGY_V3_REVIEW_DISPOSITION_TH.md)",
            "",
            "Dataset: I-Cheng Yeh (2009), [UCI Default of Credit Card Clients](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients), [DOI 10.24432/C55S3H](https://doi.org/10.24432/C55S3H), CC BY 4.0; mirror Kaggle เทียบต้นฉบับตรงทุกเซลล์ นิยาม default แบบ regulatory ยังไม่ยืนยัน ไม่มี Thai-bank/OOT/rejected-applicant validation ไม่ใช่ production lending model",
            "",
        ]
    )
    if not verification["selected_saved_model_reference_parity"]:
        raise ValueError("Cannot report an unverified selected pipeline.")
    (OUT / "REPORT_TH.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Built {OUT.relative_to(ROOT) / 'REPORT_TH.md'}")


if __name__ == "__main__":
    main()
