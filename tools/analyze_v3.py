"""Verify V3 artifacts and produce paired failure diagnostics without selecting a model."""

from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import matplotlib
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from creditrisk.artifacts import read_json, sha256, utc_now, write_json
from creditrisk.experiment import load_inputs
from creditrisk.metrics import EPSILON, capacity_counts, confusion, probability_metrics
from creditrisk.models import CreditPipeline
from creditrisk.schema import BILLS, PAY_CODES, PAYMENTS, PREDICTORS, TARGET

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def bootstrap_differences(target, groups, reference, candidate, *, seed=20261007, count=300):
    """Conditional group resampling only; not a CI for adaptive model selection."""
    _, inverse = np.unique(groups, return_inverse=True)
    groups_count = int(inverse.max()) + 1
    random = np.random.default_rng(seed)
    reference = np.clip(reference, EPSILON, 1 - EPSILON)
    candidate = np.clip(candidate, EPSILON, 1 - EPSILON)
    scores = {name: [] for name in ("roc_auc", "log_loss", "brier")}
    for _ in range(count):
        multiplicities = np.bincount(
            random.integers(0, groups_count, groups_count), minlength=groups_count
        )
        weights = multiplicities[inverse]
        if np.unique(target[weights > 0]).size != 2:
            continue
        for name, function in (
            ("roc_auc", roc_auc_score),
            ("log_loss", log_loss),
            ("brier", brier_score_loss),
        ):
            difference = function(target, candidate, sample_weight=weights) - function(
                target, reference, sample_weight=weights
            )
            scores[name].append(float(difference))
    return {
        "replicates": len(scores["log_loss"]),
        "percentile_95_differences": {
            name: np.quantile(values, [0.025, 0.975]).tolist() for name, values in scores.items()
        },
        "interpretation": "Conditional on frozen predictions; ignores adaptive selection, training variance and overlapping CV training sets. Descriptive intervals, no formal population coverage claim.",
    }


def slice_masks(rows):
    codes = rows.loc[:, PAY_CODES]
    quiet = codes.le(0).all(axis=1).to_numpy()
    zero_payments = rows.loc[:, PAYMENTS].eq(0).sum(axis=1).to_numpy()
    return {
        "all_rows": np.ones(len(rows), dtype=bool),
        "no_positive_pay_code": quiet,
        "any_positive_pay_code": ~quiet,
        "quiet_zero_payments_3plus": quiet & (zero_payments >= 3),
        "quiet_zero_payments_under3": quiet & (zero_payments < 3),
        "recent_positive_code_ge2": rows.PAY_0.ge(2).to_numpy(),
        "recent_bill_nonpositive": rows.BILL_AMT1.le(0).to_numpy(),
        "negative_bill_any": rows.loc[:, BILLS].lt(0).any(axis=1).to_numpy(),
        "zero_payments_3plus": zero_payments >= 3,
        "unknown_education_marriage": (
            rows.EDUCATION.isin([0, 5, 6]) | rows.MARRIAGE.eq(0)
        ).to_numpy(),
        "SEX_1": rows.SEX.eq(1).to_numpy(),
        "SEX_2": rows.SEX.eq(2).to_numpy(),
        "AGE_under30": rows.AGE.lt(30).to_numpy(),
        "AGE_60plus": rows.AGE.ge(60).to_numpy(),
    }


def analyze(output: Path):
    if (output / "analysis.json").exists():
        raise FileExistsError("V3 failure analysis already completed.")
    protocol, rows, folds, fit, _, _ = load_inputs(ROOT, output)
    selection = read_json(output / "selection.json")
    selection_hash = sha256(output / "selection.json")
    references = read_json(output / "reference_results.json")
    if selection_hash != references["selection_sha256"]:
        raise ValueError("Reference results do not match the frozen selection.")
    oof = pd.read_csv(output / "oof.csv")
    if not np.array_equal(oof.ID, rows.ID.iloc[fit]):
        raise ValueError("OOF row order differs from development partition.")
    datasets = {"development_oof": (fit, oof.reference.to_numpy(), oof.candidate.to_numpy())}
    for part in ("validation", "test"):
        positions = np.flatnonzero(folds.original_partition == part)
        reference = pd.read_csv(output / f"v2_reference_{part}_predictions.csv")
        candidate = pd.read_csv(output / f"v3_candidate_{part}_predictions.csv")
        if not np.array_equal(reference.ID, rows.ID.iloc[positions]) or not np.array_equal(
            candidate.ID, reference.ID
        ):
            raise ValueError(f"Reference {part} IDs/order do not match.")
        for name, predictions in (("v2_reference", reference), ("v3_candidate", candidate)):
            actual = probability_metrics(rows[TARGET].iloc[positions], predictions.probability)
            saved = next(
                result
                for result in references["results"]
                if result["pipeline"] == name and result["partition"] == f"exposed_{part}"
            )
            for metric, value in actual.items():
                if not np.isclose(value, saved[metric], atol=1e-12, rtol=1e-12):
                    raise ValueError(f"Recomputed {part}/{name}/{metric} differs.")
        datasets[f"exposed_{part}"] = (
            positions,
            reference.probability.to_numpy(),
            candidate.probability.to_numpy(),
        )

    records, capacities, intervals = [], [], {}
    for partition, (positions, reference, candidate) in datasets.items():
        subset = rows.iloc[positions]
        target = subset[TARGET].to_numpy()
        for name, probability in (("v2_reference", reference), ("v3_candidate", candidate)):
            for label, mask in slice_masks(subset).items():
                if not mask.any():
                    continue
                metrics = probability_metrics(target[mask], probability[mask])
                record = {
                    "partition": partition,
                    "pipeline": name,
                    "slice": label,
                    "rows": int(mask.sum()),
                    "events": int(target[mask].sum()),
                    "event_rate": float(target[mask].mean()),
                    "mean_probability": float(probability[mask].mean()),
                    **metrics,
                    **confusion(target[mask], probability[mask]),
                }
                records.append(record)
            capacities.extend(
                {"partition": partition, "pipeline": name, **record}
                for record in capacity_counts(target, probability)
            )
        intervals[partition] = bootstrap_differences(
            target, folds.group.iloc[positions].to_numpy(), reference, candidate
        )

    # Compare the cleaned V2 refit with the exact historical V2 winner.
    old_results = read_json(ROOT / "reports/v2/reference_results.json")
    parity = []
    for part in ("validation", "test"):
        old = next(
            result
            for result in old_results["results"]
            if result["model"] == "candidate_blend" and result["partition"] == f"exposed_{part}"
        )
        new = next(
            result
            for result in references["results"]
            if result["pipeline"] == "v2_reference" and result["partition"] == f"exposed_{part}"
        )
        for metric in ("roc_auc", "average_precision", "log_loss", "brier"):
            if not np.isclose(old[metric], new[metric], atol=1e-10, rtol=1e-10):
                raise ValueError(f"Clean V2 refit changed {part}/{metric}.")
        legacy_predictions = (
            ROOT / "outputs/experiment_v2" / f"candidate_blend_{part}_predictions.csv"
        )
        maximum = None
        if legacy_predictions.exists():
            old_p = pd.read_csv(legacy_predictions)
            new_p = pd.read_csv(output / f"v2_reference_{part}_predictions.csv")
            if not np.array_equal(old_p.ID, new_p.ID):
                raise ValueError("Legacy/new prediction IDs differ.")
            maximum = float(
                np.max(np.abs(old_p.probability.to_numpy() - new_p.probability.to_numpy()))
            )
            if maximum > 1e-10:
                raise ValueError("V2 probability migration parity failed.")
        parity.append(
            {"partition": part, "metrics_match": True, "maximum_prediction_difference": maximum}
        )

    pipeline = joblib.load(output / "models/selected.joblib")
    if not isinstance(pipeline, CreditPipeline):
        raise ValueError("Selected model is not a CreditPipeline.")
    probe = rows.loc[:, PREDICTORS].iloc[[1, 917, 50, 20]].copy()
    probe.index = [89, 4, 4, -1]
    predicted = pipeline.predict(probe)
    for position in range(len(probe)):
        one = pipeline.predict(probe.iloc[[position]])
        if not np.isclose(
            one.calibrated_probability.iloc[0],
            predicted.calibrated_probability.iloc[position],
            atol=1e-12,
            rtol=1e-12,
        ):
            raise ValueError("Single-row versus batch inference parity failed.")
    selected_kind = "v3_candidate" if selection["gate_passed"] else "v2_reference"
    if pipeline.version != f"experiment_v3/{selection['selected_pipeline']}":
        raise ValueError("Saved scoring pipeline differs from the gate decision.")
    test_positions, ref_p, cand_p = datasets["exposed_test"]
    selected_expected = cand_p if selection["gate_passed"] else ref_p
    scoring = pipeline.predict(
        rows.loc[:, PREDICTORS].iloc[test_positions]
    ).calibrated_probability.to_numpy()
    if not np.allclose(scoring, selected_expected, atol=1e-12, rtol=1e-12):
        raise ValueError("Selected model disagrees with reference prediction artifact.")
    if sha256(output / "selection.json") != selection_hash:
        raise ValueError("Selection mutated during analysis.")
    slices = pd.DataFrame(records)
    slices.to_csv(output / "failure_slices.csv", index=False)
    capacity_frame = pd.DataFrame(capacities)
    capacity_frame.to_csv(output / "capacity_comparison.csv", index=False)
    result = {
        "analyzed_utc": utc_now(),
        "selection_unchanged": True,
        "selected_pipeline": selected_kind,
        "paired_group_bootstrap": intervals,
        "migration_parity": parity,
        "failure_slices": records,
        "interpretation": "Outcome-blind fitting boundaries verified. Historical adaptivity, weak segments and absence of new labeled cohorts remain unresolved.",
    }
    write_json(output / "analysis.json", result, exclusive=True)
    write_json(
        output / "verification.json",
        {
            "verified_utc": utc_now(),
            "protocol_hashes_match": True,
            "selection_sha256": selection_hash,
            "prediction_ids_order_match": True,
            "recomputed_metrics_match": True,
            "clean_v2_refit_parity": parity,
            "batch_single_row_nonunique_index_parity": True,
            "selected_saved_model_reference_parity": True,
            "feature_migration": read_json(output / "feature_migration.json"),
            "no_new_holdout": True,
        },
        exclusive=True,
    )
    plot_diagnostics(output, selection, slices, capacity_frame)
    print(
        {
            "selection": selection["selected_pipeline"],
            "parity": parity,
            "exposed_test_intervals": intervals["exposed_test"],
        }
    )


def plot_diagnostics(output, selection, slices, capacities):
    figure, axes = plt.subplots(1, 3, figsize=(14, 4.2))
    axes[0].bar(range(3), selection["fold_log_loss_deltas"], color="#397a99")
    axes[0].axhline(0, color="#333333", linewidth=1)
    axes[0].set(title="Outer fold log-loss difference", xlabel="Fold", ylabel="Candidate minus V2")
    axes[0].set_xticks(range(3))
    subset = capacities.loc[capacities.partition == "exposed_test"]
    for name, group in subset.groupby("pipeline"):
        axes[1].plot(group.capacity * 100, group.events_captured, marker="o", label=name)
    axes[1].set(
        title="Exposed test: fixed review capacity",
        xlabel="Rows flagged (%)",
        ylabel="Events captured",
    )
    axes[1].legend(fontsize=8)
    subset = slices.loc[
        (slices.partition == "exposed_test")
        & (slices.slice.isin(["no_positive_pay_code", "any_positive_pay_code"]))
    ]
    labels = ["No positive PAY code", "Any positive PAY code"]
    for offset, name in enumerate(("v2_reference", "v3_candidate")):
        group = subset.loc[subset.pipeline == name].set_index("slice")
        axes[2].bar(
            np.arange(2) + (offset - 0.5) * 0.32,
            [
                group.loc[key, "log_loss"]
                for key in ("no_positive_pay_code", "any_positive_pay_code")
            ],
            width=0.32,
            label=name,
        )
    axes[2].set_xticks(range(2), labels, fontsize=8)
    axes[2].set(title="Exposed test: segment log loss", ylabel="Log loss")
    axes[2].legend(fontsize=8)
    figure.suptitle("V3 development diagnostics - exposed historical cohort", fontsize=13)
    figure.tight_layout()
    figure.savefig(output / "diagnostics.png", dpi=170)
    plt.close(figure)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/experiment_v3")
    analyze(parser.parse_args().output)
