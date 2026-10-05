"""Frozen V3 nested-search procedure and comparisons on exposed historical data."""

from __future__ import annotations

import importlib.metadata
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, replace
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .artifacts import read_json, sha256, utc_now, verify_hashes, write_json
from .calibration import select_calibrator
from .features import make_features
from .metrics import probability_metrics, valid_probabilities
from .models import Component, CreditPipeline, catboost_model, categorical_input, lightgbm_model
from .nested import DEFAULT_POLICY, SearchPolicy, nested_fit
from .schema import CATEGORIES, PAY_CODES, PREDICTORS, TARGET, load_dataset
from .splits import disjoint_groups, validate_assignment

CAT_WEIGHT = 0.75
MIN_GAIN = 0.001
QUIET_TOLERANCE = 0.001


def policy_from(protocol: dict, *, fold: int = 0) -> SearchPolicy:
    settings = protocol["search_policy"].copy()
    settings["candidates"] = tuple(settings["candidates"])
    settings["split_seed"] += fold
    return SearchPolicy(**settings)


def paths_from(root: Path, protocol: dict) -> tuple[Path, Path, Path, Path]:
    paths = protocol["paths"]
    return tuple(root / paths[key] for key in ("data", "folds", "baseline_oof", "lightgbm_oof"))


def prepare(root: Path, output: Path, *, data_path: Path, reference: Path) -> dict:
    if (output / "protocol.json").exists():
        raise FileExistsError("V3 protocol already frozen; do not overwrite completed research.")
    rows = load_dataset(data_path)
    folds_path, baseline_path = reference / "folds.csv", reference / "selected_oof.csv"
    lightgbm_path = reference / "lightgbm_oof.csv"
    folds = pd.read_csv(folds_path, dtype={"group": str})
    validate_assignment(rows, folds)
    source_paths = {
        "data": data_path,
        "folds": folds_path,
        "baseline_oof": baseline_path,
        "lightgbm_oof": lightgbm_path,
    }
    relative_paths = {
        key: path.resolve().relative_to(root.resolve()).as_posix()
        for key, path in source_paths.items()
    }
    code_paths = sorted((root / "src/creditrisk").glob("*.py"))
    protocol = {
        "experiment": "experiment_v3",
        "created_utc": utc_now(),
        "paths": relative_paths,
        "hashes": {
            path.resolve().relative_to(root.resolve()).as_posix(): sha256(path)
            for path in [*source_paths.values(), *code_paths]
        },
        "search_policy": asdict(DEFAULT_POLICY),
        "outer_folds": 3,
        "outer_partition": "Original fit16500; identical to V2 outer folds",
        "procedure": "3 inner group folds select depth and stopping iterations; median chosen inner tree counts; refit all outer-training rows with no evaluation set",
        "candidate": "One adaptive procedure: inner-selected CatBoost plus fixed V2 LightGBM15, weights 0.75/0.25; no outer-fold weight search",
        "comparison": "Frozen V2 winner OOF, previously selected on these folds. Both data and comparator have adaptive research history; no independent validation claim.",
        "calibration": "Identity/sigmoid/isotonic by 5 group folds inside reused calibration4500 only; fit on all calibration after selection",
        "promotion_gate": {
            "minimum_pooled_log_loss_gain": MIN_GAIN,
            "every_fold_log_loss_improves": True,
            "pooled_brier_not_worse": True,
            "max_quiet_segment_log_loss_increase": QUIET_TOLERANCE,
        },
        "final_fit": "Original fit16500; repeat predefined inner procedure for final settings. Do not choose a depth or iteration from outer-fold outcomes.",
        "references": "Original validation/test are exposed; descriptive evaluations after frozen gate; never retune or claim an unbiased new test.",
        "stop_rule": "No extra candidates or tuning after outcomes; retain V2 if gate fails",
        "cpu_budget": "2 simultaneous outer-fold jobs, 2 model threads each",
        "features": "Exact V2 68-column trajectory recipe, including one known redundant ratio for parity",
        "versions": {
            package: importlib.metadata.version(package)
            for package in ("pandas", "numpy", "scikit-learn", "catboost", "lightgbm")
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "protocol.json", protocol, exclusive=True)
    return protocol


def load_inputs(root: Path, output: Path):
    protocol = read_json(output / "protocol.json")
    verify_hashes(root, protocol["hashes"])
    data_path, folds_path, baseline_path, lightgbm_path = paths_from(root, protocol)
    rows = load_dataset(data_path)
    folds = pd.read_csv(folds_path, dtype={"group": str})
    validate_assignment(rows, folds)
    fit = np.flatnonzero(folds.original_partition == "fit")
    baseline, lightgbm = pd.read_csv(baseline_path), pd.read_csv(lightgbm_path)
    for frame in (baseline, lightgbm):
        if not np.array_equal(frame.ID, rows.ID.iloc[fit]):
            raise ValueError("Frozen OOF IDs or row order differ from fit partition.")
    valid_probabilities(baseline.candidate, size=len(fit))
    valid_probabilities(lightgbm.probability, size=len(fit))
    if not np.array_equal(baseline.fold, folds.cv_fold.iloc[fit]):
        raise ValueError("Baseline OOF fold assignment changed.")
    if set(folds.cv_fold.iloc[fit]) != set(range(protocol["outer_folds"])):
        raise ValueError("Unexpected outer fold numbers.")
    return protocol, rows, folds, fit, baseline, lightgbm


def run_outer_fold(root: Path, output: Path, fold: int) -> dict:
    record_path = output / "cv" / f"fold_{fold}.json"
    predictions_path = output / "cv" / f"fold_{fold}.csv"
    if record_path.exists() or predictions_path.exists():
        raise FileExistsError(f"Outer fold {fold} already has artifacts; refuse silent reuse.")
    protocol, rows, folds, fit, _, lightgbm = load_inputs(root, output)
    cv_folds = folds.cv_fold.iloc[fit].to_numpy()
    train, hold = fit[cv_folds != fold], fit[cv_folds == fold]
    disjoint_groups(folds.group.to_numpy(), train, hold)
    features = make_features(rows)
    target = rows[TARGET].to_numpy()
    started = time.perf_counter()
    model, search = nested_fit(
        features.iloc[train],
        target[train],
        folds.group.iloc[train].to_numpy(),
        policy_from(protocol, fold=fold),
    )
    cat_probability = model.predict_proba(features.iloc[hold])[:, 1]
    frozen_lightgbm = lightgbm.probability.to_numpy()[cv_folds == fold]
    candidate = CAT_WEIGHT * cat_probability + (1 - CAT_WEIGHT) * frozen_lightgbm
    record = {
        "fold": fold,
        "train_rows": len(train),
        "hold_rows": len(hold),
        "search": search,
        "metrics": probability_metrics(target[hold], candidate),
        "catboost_only_metrics": probability_metrics(target[hold], cat_probability),
        "outer_groups_disjoint": True,
        "seconds": time.perf_counter() - started,
    }
    predictions_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "ID": rows.ID.iloc[hold],
            "catboost_probability": cat_probability,
            "probability": candidate,
        }
    ).to_csv(predictions_path, index=False)
    write_json(record_path, record, exclusive=True)
    print(
        f"OUTER fold={fold} depth={search['selected_config']['depth']} "
        f"trees={search['refit_iterations']} log_loss={record['metrics']['log_loss']:.6f}",
        flush=True,
    )
    return record


def run_cv(root: Path, output: Path) -> None:
    protocol, *_ = load_inputs(root, output)
    pending = []
    for fold in range(protocol["outer_folds"]):
        record = output / "cv" / f"fold_{fold}.json"
        predictions = output / "cv" / f"fold_{fold}.csv"
        if record.exists() != predictions.exists():
            raise ValueError(f"Incomplete artifacts for fold {fold}; investigate before resuming.")
        if not record.exists():
            pending.append(fold)
    if not pending:
        raise FileExistsError("All outer folds completed; refuse a new CV evaluation.")
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run_outer_fold, root, output, fold) for fold in pending]
        for future in as_completed(futures):
            future.result()


def select(root: Path, output: Path) -> dict:
    if (output / "selection.json").exists():
        raise FileExistsError("Gate selection already frozen.")
    protocol, rows, folds, fit, baseline, lightgbm = load_inputs(root, output)
    candidate = np.empty(len(fit))
    cat_only = np.empty(len(fit))
    cv_folds = folds.cv_fold.iloc[fit].to_numpy()
    diagnostics = []
    for fold in range(protocol["outer_folds"]):
        hold = cv_folds == fold
        saved = pd.read_csv(output / "cv" / f"fold_{fold}.csv")
        if not np.array_equal(saved.ID, rows.ID.iloc[fit[hold]]):
            raise ValueError("Outer OOF prediction IDs/order changed.")
        candidate[hold], cat_only[hold] = saved.probability, saved.catboost_probability
        expected = (
            CAT_WEIGHT * cat_only[hold] + (1 - CAT_WEIGHT) * lightgbm.probability.to_numpy()[hold]
        )
        if not np.allclose(candidate[hold], expected, rtol=1e-12, atol=1e-12):
            raise ValueError("Candidate does not match the frozen blend recipe.")
        diagnostics.append(read_json(output / "cv" / f"fold_{fold}.json"))
    target = rows[TARGET].to_numpy()[fit]
    reference = baseline.candidate.to_numpy()
    candidate_metrics = probability_metrics(target, candidate)
    reference_metrics = probability_metrics(target, reference)
    fold_deltas = [
        probability_metrics(target[cv_folds == k], candidate[cv_folds == k])["log_loss"]
        - probability_metrics(target[cv_folds == k], reference[cv_folds == k])["log_loss"]
        for k in range(protocol["outer_folds"])
    ]
    quiet = rows.loc[:, PAY_CODES].iloc[fit].le(0).all(axis=1).to_numpy()
    quiet_delta = (
        probability_metrics(target[quiet], candidate[quiet])["log_loss"]
        - probability_metrics(target[quiet], reference[quiet])["log_loss"]
    )
    gain = reference_metrics["log_loss"] - candidate_metrics["log_loss"]
    checks = {
        "minimum_gain": gain >= protocol["promotion_gate"]["minimum_pooled_log_loss_gain"],
        "all_folds_improve": all(delta < 0 for delta in fold_deltas),
        "brier_not_worse": candidate_metrics["brier"] <= reference_metrics["brier"],
        "quiet_segment_not_materially_worse": quiet_delta
        <= protocol["promotion_gate"]["max_quiet_segment_log_loss_increase"],
    }
    passed = all(checks.values())
    result = {
        "selected_utc": utc_now(),
        "gate_passed": passed,
        "gate_checks": checks,
        "selected_pipeline": "v3_nested" if passed else "v2_retained",
        "log_loss_gain": gain,
        "candidate_oof": candidate_metrics,
        "baseline_v2_oof": reference_metrics,
        "fold_log_loss_deltas": fold_deltas,
        "quiet_segment_log_loss_delta": quiet_delta,
        "outer_search": diagnostics,
        "protocol_sha256": sha256(output / "protocol.json"),
        "interpretation": "Nested search keeps outer labels outside current training selection. Previous data/feature/model selection and promotion remain adaptive; descriptive within-cohort evidence only.",
    }
    pd.DataFrame(
        {
            "ID": rows.ID.iloc[fit],
            "fold": cv_folds,
            "reference": reference,
            "candidate": candidate,
            "catboost_only": cat_only,
        }
    ).to_csv(output / "oof.csv", index=False)
    write_json(output / "selection.json", result, exclusive=True)
    return result


def fit_lightgbm(features, target, *, seed: int, threads: int) -> Component:
    model = lightgbm_model(seed=seed, threads=threads)
    encoded = categorical_input(features)
    categories = {column: list(encoded[column].cat.categories) for column in CATEGORIES}
    model.fit(encoded, target)
    return Component("lightgbm", model, list(features), categories=categories)


def finalize(root: Path, output: Path) -> dict:
    if (output / "reference_results.json").exists() or (output / "models").exists():
        raise FileExistsError(
            "Final models/references already exist; refuse a duplicate evaluation."
        )
    protocol, rows, folds, _, _, _ = load_inputs(root, output)
    selection = read_json(output / "selection.json")
    selection_hash = sha256(output / "selection.json")
    indexes = {
        part: np.flatnonzero(folds.original_partition == part)
        for part in ("fit", "calibration", "validation", "test")
    }
    features, target = make_features(rows), rows[TARGET].to_numpy()
    policy = replace(policy_from(protocol), split_seed=DEFAULT_POLICY.split_seed + 100)
    started = time.perf_counter()
    nested_model, search = nested_fit(
        features.iloc[indexes["fit"]],
        target[indexes["fit"]],
        folds.group.iloc[indexes["fit"]].to_numpy(),
        policy,
    )
    print(
        f"FINAL nested depth={search['selected_config']['depth']} trees={search['refit_iterations']}",
        flush=True,
    )
    v2_config = {"depth": 6, "learning_rate": 0.03, "l2_leaf_reg": 20}
    fixed_model = catboost_model(
        v2_config, iterations=1000, seed=policy.model_seed, threads=policy.threads
    )
    fixed_model.fit(features.iloc[indexes["fit"]], target[indexes["fit"]])
    lightgbm = fit_lightgbm(
        features.iloc[indexes["fit"]],
        target[indexes["fit"]],
        seed=policy.model_seed,
        threads=policy.threads,
    )
    pipelines = {
        "v2_reference": CreditPipeline(
            [Component("catboost", fixed_model, list(features)), lightgbm],
            [CAT_WEIGHT, 1 - CAT_WEIGHT],
            version="experiment_v3/v2_retained",
        ),
        "v3_candidate": CreditPipeline(
            [Component("catboost", nested_model, list(features)), lightgbm],
            [CAT_WEIGHT, 1 - CAT_WEIGHT],
            version="experiment_v3/v3_nested",
        ),
    }
    results, calibrations = [], {}
    for name, pipeline in pipelines.items():
        calibration_rows = rows.loc[:, PREDICTORS].iloc[indexes["calibration"]]
        calibration_raw = pipeline.predict(calibration_rows).raw_probability.to_numpy()
        fitted, scores = select_calibrator(
            calibration_raw,
            target[indexes["calibration"]],
            folds.group.iloc[indexes["calibration"]].to_numpy(),
            seed=20261004,
        )
        pipeline.calibrator = fitted
        calibrations[name] = {"kind": fitted.kind, "oof_scores": scores}
        for part in ("validation", "test"):
            p = pipeline.predict(rows.loc[:, PREDICTORS].iloc[indexes[part]])
            pd.DataFrame(
                {
                    "ID": rows.ID.iloc[indexes[part]],
                    "raw_probability": p.raw_probability.to_numpy(),
                    "probability": p.calibrated_probability.to_numpy(),
                }
            ).to_csv(output / f"{name}_{part}_predictions.csv", index=False)
            results.append(
                {
                    "pipeline": name,
                    "partition": f"exposed_{part}",
                    "calibration": fitted.kind,
                    **probability_metrics(target[indexes[part]], p.calibrated_probability),
                }
            )
    selected = pipelines["v3_candidate" if selection["gate_passed"] else "v2_reference"]
    models = output / "models"
    models.mkdir()
    for name, pipeline in {**pipelines, "selected": selected}.items():
        joblib.dump(pipeline, models / f"{name}.joblib")
        restored = joblib.load(models / f"{name}.joblib")
        probe = rows.loc[:, PREDICTORS].iloc[indexes["validation"][:30]]
        if not np.allclose(
            pipeline.predict(probe).calibrated_probability,
            restored.predict(probe).calibrated_probability,
            rtol=1e-12,
            atol=1e-12,
        ):
            raise ValueError("Saved pipeline prediction parity failed.")
    if sha256(output / "selection.json") != selection_hash:
        raise ValueError("Selection changed during finalization.")
    result = {
        "evaluated_utc": utc_now(),
        "results": results,
        "calibration": calibrations,
        "selected_pipeline": selection["selected_pipeline"],
        "final_search": search,
        "selection_sha256": selection_hash,
        "seconds": time.perf_counter() - started,
        "no_unbiased_holdout_claim": True,
    }
    write_json(output / "reference_results.json", result, exclusive=True)
    pd.DataFrame(results).to_csv(output / "reference_metrics.csv", index=False)
    return result
