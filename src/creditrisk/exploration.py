"""Additional exploratory tables restricted to the original development partition."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .artifacts import sha256, utc_now, write_json
from .features import make_features
from .schema import BILLS, CATEGORIES, PAY_CODES, PAYMENTS, TARGET, load_dataset
from .splits import predictor_groups, validate_assignment


def rate_interval(events: int, count: int) -> tuple[float, float]:
    """Wilson 95% interval: descriptive binomial interval, not simultaneous inference."""
    z = 1.959963984540054
    rate = events / count
    denominator = 1 + z * z / count
    center = (rate + z * z / (2 * count)) / denominator
    radius = z * np.sqrt(rate * (1 - rate) / count + z * z / (4 * count * count)) / denominator
    return float(center - radius), float(center + radius)


def event_summary(rows: pd.DataFrame, name: str) -> dict:
    count, events = len(rows), int(rows[TARGET].sum())
    lower, upper = rate_interval(events, count)
    return {
        "segment": name,
        "rows": count,
        "events": events,
        "event_rate": events / count,
        "wilson_lower": lower,
        "wilson_upper": upper,
    }


def explore(data_path: Path, folds_path: Path, output: Path) -> dict:
    if (output / "exploration.json").exists():
        raise FileExistsError("Exploration snapshot already exists; preserve it.")
    rows = load_dataset(data_path)
    folds = pd.read_csv(folds_path, dtype={"group": str})
    validate_assignment(rows, folds)
    fit = rows.loc[folds.original_partition == "fit"].copy()
    codes = fit.loc[:, PAY_CODES]
    quiet = codes.le(0).all(axis=1)
    zero_payments = fit.loc[:, PAYMENTS].eq(0).sum(axis=1)
    nonpositive_bills = fit.loc[:, BILLS].le(0).sum(axis=1)
    slices = {
        "all_fit": np.ones(len(fit), dtype=bool),
        "no_positive_pay_code": quiet,
        "any_positive_pay_code": ~quiet,
        "quiet_zero_payments_3plus": quiet & zero_payments.ge(3),
        "quiet_zero_payments_under3": quiet & zero_payments.lt(3),
        "quiet_nonpositive_bills_3plus": quiet & nonpositive_bills.ge(3),
        "quiet_nonpositive_bills_under3": quiet & nonpositive_bills.lt(3),
        "quiet_all_six_codes_minus2": quiet & codes.eq(-2).all(axis=1),
        "quiet_all_six_codes_zero": quiet & codes.eq(0).all(axis=1),
        "quiet_other_code_history": quiet & ~codes.eq(-2).all(axis=1) & ~codes.eq(0).all(axis=1),
    }
    summaries = [
        event_summary(fit.loc[mask], name) for name, mask in slices.items() if np.sum(mask)
    ]
    categories = []
    for column in CATEGORIES:
        for code, subset in fit.groupby(column, observed=True):
            categories.append(
                {"column": column, "code": int(code), **event_summary(subset, f"{column}={code}")}
            )
    features = make_features(fit)
    numerical = features.select_dtypes(include="number")
    quality = []
    for column in numerical:
        observed = numerical[column].dropna()
        quantiles = observed.quantile([0, 0.001, 0.01, 0.5, 0.99, 0.999, 1])
        quality.append(
            {
                "feature": column,
                "missing_rows": int(numerical[column].isna().sum()),
                "quantiles": {str(q): float(value) for q, value in quantiles.items()},
            }
        )

    conflicts = pd.DataFrame({"group": predictor_groups(fit), "target": fit[TARGET].to_numpy()})
    counts = conflicts.groupby("group").target.agg(["size", "sum", "nunique"])
    ambiguous = counts.loc[counts["nunique"] > 1]
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(summaries).to_csv(output / "development_segments.csv", index=False)
    pd.DataFrame(categories).to_csv(output / "development_category_rates.csv", index=False)
    result = {
        "created_utc": utc_now(),
        "scope": "Original fit rows only; no model or threshold selection",
        "data_sha256": sha256(data_path),
        "folds_sha256": sha256(folds_path),
        "rows": len(fit),
        "events": int(fit[TARGET].sum()),
        "segments": summaries,
        "feature_quality": quality,
        "exact_vector_ambiguity": {
            "conflicting_groups": len(ambiguous),
            "rows_in_conflicts": int(ambiguous["size"].sum()),
            "minimum_deterministic_errors_on_observed_vectors": int(
                np.minimum(ambiguous["sum"], ambiguous["size"] - ambiguous["sum"]).sum()
            ),
            "interpretation": "Observed feature vectors can have different outcomes; not proof of label noise or a population Bayes-error floor.",
        },
        "redundant_features": [["recent_bill_utilization", "bill_limit_ratio_1"]],
        "limitations": [
            "Category associations are observational, not causal effects or underwriting policy.",
            "Intervals are descriptive, not adjusted for multiple exploratory comparisons.",
            "Negative/zero repayment codes and negative bills retain unknown semantic details.",
            "No new cohort or genuinely out-of-time data was obtained.",
        ],
    }
    write_json(output / "exploration.json", result, exclusive=True)
    return result
