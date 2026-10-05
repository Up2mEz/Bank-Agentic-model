"""Pure within-row summaries, numerically compatible with the frozen V2 recipe."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .schema import BILLS, CATEGORIES, DEMOGRAPHICS, PAY_CODES, PAYMENTS, PREDICTORS


def make_features(rows: pd.DataFrame, variant: str = "trajectory") -> pd.DataFrame:
    if variant not in {"raw", "behavior", "trajectory", "trajectory_no_demographics"}:
        raise ValueError(f"Unknown feature variant: {variant}")
    features = rows.loc[:, PREDICTORS].copy()
    for column in CATEGORIES:
        features[column] = features[column].astype(int).astype(str)
    if variant == "raw":
        return features

    limit = rows.LIMIT_BAL.where(rows.LIMIT_BAL > 0)
    for month in range(1, 7):
        bill = rows[f"BILL_AMT{month}"]
        features[f"payment_bill_ratio_{month}"] = rows[f"PAY_AMT{month}"] / bill.where(bill > 0)
        features[f"nonpositive_bill_{month}"] = (bill <= 0).astype(int)
    features["recent_bill_utilization"] = rows.BILL_AMT1 / limit
    features["bill_change_1_6"] = rows.BILL_AMT1 - rows.BILL_AMT6
    if variant == "behavior":
        return features

    codes = rows.loc[:, PAY_CODES].to_numpy(dtype=float)
    positive = np.maximum(codes, 0)
    # A zero contribution does not assign a meaning to negative/zero category codes.
    features["positive_code_count"] = (codes > 0).sum(axis=1)
    features["code_ge2_count"] = (codes >= 2).sum(axis=1)
    features["max_positive_code"] = positive.max(axis=1)
    features["mean_positive_code"] = positive.mean(axis=1)
    features["latest_positive_minus_prior_mean"] = positive[:, 0] - positive[:, 1:].mean(axis=1)
    features["latest_positive_minus_prior_max"] = positive[:, 0] - positive[:, 1:].max(axis=1)
    features["adjacent_positive_pairs"] = ((codes[:, :-1] > 0) & (codes[:, 1:] > 0)).sum(axis=1)
    features["recent_positive_code_count"] = (codes[:, :3] > 0).sum(axis=1)

    bills = rows.loc[:, BILLS].to_numpy(dtype=float)
    payments = rows.loc[:, PAYMENTS].to_numpy(dtype=float)
    for month in range(1, 7):
        features[f"bill_limit_ratio_{month}"] = rows[f"BILL_AMT{month}"] / limit
        features[f"payment_limit_ratio_{month}"] = rows[f"PAY_AMT{month}"] / limit
    features["zero_payment_count"] = (payments == 0).sum(axis=1)
    features["recent_zero_payment_count"] = (payments[:, :3] == 0).sum(axis=1)
    features["negative_bill_count"] = (bills < 0).sum(axis=1)
    features["bill_std_limit"] = bills.std(axis=1) / limit
    features["bill_range_limit"] = (bills.max(axis=1) - bills.min(axis=1)) / limit
    features["payment_std_limit"] = payments.std(axis=1) / limit
    features["payment_mean_limit"] = payments.mean(axis=1) / limit
    time = np.arange(6, dtype=float)
    time -= time.mean()
    features["bill_slope_limit"] = (bills[:, ::-1] @ time) / (time @ time) / limit
    features["payment_slope_limit"] = (payments[:, ::-1] @ time) / (time @ time) / limit
    features["recent_bill_change_limit"] = (bills[:, 0] - bills[:, 2]) / limit
    denominator = np.maximum(bills, 0).sum(axis=1)
    features["sum_payment_over_sum_positive_bill"] = np.divide(
        payments.sum(axis=1),
        denominator,
        out=np.full(len(rows), np.nan),
        where=denominator > 0,
    )
    # bill_limit_ratio_1 intentionally duplicates recent_bill_utilization for V2 parity.
    if variant == "trajectory_no_demographics":
        return features.drop(columns=list(DEMOGRAPHICS))
    return features
