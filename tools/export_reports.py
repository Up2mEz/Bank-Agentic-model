"""Publish a curated evidence snapshot, excluding raw data, models and local agent logs."""

from __future__ import annotations

import shutil
from pathlib import Path

from creditrisk.artifacts import sha256, utc_now, write_json

ROOT = Path(__file__).resolve().parents[1]
EXPORTS = {
    "v1": [
        "REPORT_TH.md",
        "evaluation.png",
        "metrics.csv",
        "protocol.json",
        "data_audit.json",
        "verification.json",
        "model_card.json",
        "test_results.json",
        "tabpfn_v3_5_results.json",
    ],
    "v2": [
        "REPORT_TH.md",
        "protocol.json",
        "selection.json",
        "analysis.json",
        "reference_metrics.csv",
        "reference_results.json",
        "failure_followup.json",
        "failure_slices_comparison.csv",
        "capacity_comparison.csv",
        "threshold_comparison.csv",
        "learning_curve_diagnostics.csv",
        "development_diagnostics.png",
        "tabpfn_4000_results.json",
        "folds.csv",
        "selected_oof.csv",
    ],
    "v3": [
        "REPORT_TH.md",
        "protocol.json",
        "selection.json",
        "reference_results.json",
        "reference_metrics.csv",
        "analysis.json",
        "failure_slices.csv",
        "capacity_comparison.csv",
        "diagnostics.png",
        "verification.json",
    ],
}


def export(version: str) -> None:
    source, destination = ROOT / "outputs" / f"experiment_{version}", ROOT / "reports" / version
    destination.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name in EXPORTS[version]:
        original = source / name
        if not original.exists():
            raise FileNotFoundError(f"Required evidence is absent: {original.relative_to(ROOT)}")
        shutil.copyfile(original, destination / name)
        manifest.append(
            {
                "source": original.relative_to(ROOT).as_posix(),
                "export": name,
                "sha256": sha256(original),
            }
        )
    if version == "v2":
        original = source / "cv/lightgbm_trajectory_15/oof.csv"
        shutil.copyfile(original, destination / "lightgbm_oof.csv")
        manifest.append(
            {
                "source": original.relative_to(ROOT).as_posix(),
                "export": "lightgbm_oof.csv",
                "sha256": sha256(original),
            }
        )
    write_json(
        destination / "export_manifest.json",
        {
            "exported_utc": utc_now(),
            "files": manifest,
            "data_attribution": "Derived from Yeh (2009), UCI Default of Credit Card Clients, CC BY 4.0; exact-vector groups are not verified borrower identities.",
        },
    )
    print(f"Exported {version}: {len(manifest)} evidence files")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", choices=EXPORTS)
    export(parser.parse_args().version)
