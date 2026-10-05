"""Verify the fetched raw snapshot against the historical baseline before new research."""

from pathlib import Path

from creditrisk.artifacts import read_json, sha256

ROOT = Path(__file__).resolve().parents[1]


def verify(root: Path) -> None:
    baseline = read_json(root / "reports/v1/protocol.json")
    raw = root / "data/raw/kaggle_credit_card/UCI_Credit_Card.csv"
    if sha256(raw) != baseline["data_sha256"]:
        raise ValueError(
            "Raw snapshot differs from the V1/V2 baseline, including possible label changes. Do not reuse baseline OOF for a new dataset."
        )
    print("Raw snapshot matches the historical baseline SHA-256.")


if __name__ == "__main__":
    verify(ROOT)
