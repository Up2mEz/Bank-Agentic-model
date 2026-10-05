"""Audit the observed credit snapshot; do not infer edges or fraud labels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from creditrisk.artifacts import sha256, utc_now
from creditrisk.schema import BILLS, PAY_CODES, PAYMENTS, PREDICTORS, TARGET, load_dataset

ROOT = Path(__file__).resolve().parents[1]


def audit(source: Path) -> dict:
    rows = load_dataset(source)
    groups = rows.groupby(list(PREDICTORS), dropna=False, sort=False)[TARGET].agg(
        ["size", "nunique"]
    )
    conflicts = groups["nunique"] > 1
    return {
        "checked_utc": utc_now(),
        "source_file": source.name,
        "source_sha256": sha256(source),
        "audit_script_sha256": sha256(Path(__file__)),
        "source_dictionary": "https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients",
        "rows": len(rows),
        "columns": list(rows.columns),
        "predictors": len(PREDICTORS),
        "target": TARGET,
        "label_counts": {
            str(label): int(count)
            for label, count in rows[TARGET].value_counts().sort_index().items()
        },
        "positive_label_rate": float(rows[TARGET].mean()),
        "missing_cells": int(rows.isna().sum().sum()),
        "unique_ids": int(rows["ID"].nunique()),
        "rows_per_id_max": int(rows["ID"].value_counts().max()),
        "distinct_predictor_vectors": len(groups),
        "identical_predictor_extra_rows": len(rows) - len(groups),
        "conflicting_label_vector_groups": int(conflicts.sum()),
        "rows_in_conflicting_label_vector_groups": int(groups.loc[conflicts, "size"].sum()),
        "historical_month_columns": {
            "payment_status": list(PAY_CODES),
            "bill_amount": list(BILLS),
            "previous_payment_amount": list(PAYMENTS),
        },
        "month_mapping_from_dictionary": {
            "latest": "September 2005",
            "earliest": "April 2005",
            "order": "Latest to earliest across each six-column family",
        },
        "dictionary_and_schema_assessment": {
            "unit": "One card-client row with six historical monthly summaries",
            "id_role": "Row ID; no documented counterparty or cross-entity link",
            "target_role": "Next-month default payment, not a documented fraud outcome",
            "not_provided": [
                "Observed sender-recipient or customer-account relationships",
                "Individual transactions and their timestamps",
                "Merchant, device, IP or login/session identifiers",
                "Investigated fraud/AML outcomes and label availability dates",
                "Fraud loss, recoveries, LGD or EAD outcomes",
                "Repeated monthly prediction cohorts or Thai-bank population",
            ],
            "assessment_method": "Review of the complete column list and UCI dictionary; not keyword matching",
            "limitations": "Does not establish hidden relationships, default threshold, fraud causation or deployability",
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "data/raw/kaggle_credit_card/UCI_Credit_Card.csv",
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "reports/graph_scope/data_readiness.json"
    )
    args = parser.parse_args()
    record = audit(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"Rows={record['rows']}; predictors={record['predictors']}; "
        f"positive_labels={record['label_counts']['1']}; "
        f"distinct_vectors={record['distinct_predictor_vectors']}; "
        f"conflicting_vector_groups={record['conflicting_label_vector_groups']}"
    )
