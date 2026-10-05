"""Verify every feature value/index against frozen legacy V2 on the actual snapshot."""

import sys
from pathlib import Path

import pandas as pd

from creditrisk.artifacts import write_json
from creditrisk.features import make_features
from creditrisk.schema import TARGET, load_dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from credit_features_v2 import trajectory_features  # noqa: E402


def main():
    data = load_dataset(ROOT / "data/raw/kaggle_credit_card/UCI_Credit_Card.csv")
    checks = []
    for variant in ("behavior", "trajectory", "trajectory_no_demographics"):
        old, new = trajectory_features(data, variant), make_features(data, variant)
        pd.testing.assert_frame_equal(old, new, check_exact=True)
        sample = data.iloc[[910, 24, 52, 1]].drop(columns=["ID", TARGET])
        pd.testing.assert_frame_equal(
            trajectory_features(sample, variant), make_features(sample, variant), check_exact=True
        )
        checks.append(
            {
                "variant": variant,
                "rows": len(data),
                "columns": len(new.columns),
                "exact_parity": True,
            }
        )
    write_json(ROOT / "outputs/experiment_v3/feature_migration.json", {"checks": checks})
    print(checks)


if __name__ == "__main__":
    main()
