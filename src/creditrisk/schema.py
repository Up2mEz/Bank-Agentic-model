"""Dataset contracts shared by training, exploration and inference."""

from __future__ import annotations

import numpy as np
import pandas as pd

TARGET = "default.payment.next.month"
PAY_CODES = ("PAY_0", "PAY_2", "PAY_3", "PAY_4", "PAY_5", "PAY_6")
CATEGORIES = ("SEX", "EDUCATION", "MARRIAGE", *PAY_CODES)
DEMOGRAPHICS = ("SEX", "EDUCATION", "MARRIAGE", "AGE")
BILLS = tuple(f"BILL_AMT{i}" for i in range(1, 7))
PAYMENTS = tuple(f"PAY_AMT{i}" for i in range(1, 7))
PREDICTORS = ("LIMIT_BAL", "SEX", "EDUCATION", "MARRIAGE", "AGE", *PAY_CODES, *BILLS, *PAYMENTS)


def validate_predictors(rows: pd.DataFrame) -> pd.DataFrame:
    """Require the original 23 columns, preserve rows, and retain unknown integer codes.

    Out-of-distribution category codes are accepted as nominal values. Dataset
    semantics do not justify invented relabeling or rejecting negative bills.
    """
    if rows.empty:
        raise ValueError("At least one input row is required.")
    if not rows.columns.is_unique or set(rows.columns) != set(PREDICTORS):
        raise ValueError("Exactly 23 unique original predictors required; exclude ID and target.")
    clean = rows.loc[:, PREDICTORS].copy()
    if not all(pd.api.types.is_numeric_dtype(dtype) for dtype in clean.dtypes):
        raise ValueError("Predictors must be numeric, not string or object values.")
    if not np.isfinite(clean.to_numpy(dtype=float)).all():
        raise ValueError("All original predictor values must be finite.")
    integer_values = clean.loc[:, (*CATEGORIES, "AGE")].to_numpy(dtype=float)
    if not np.equal(integer_values, np.floor(integer_values)).all():
        raise ValueError("Category codes and AGE must be integers.")
    return clean


def load_dataset(path) -> pd.DataFrame:
    """Read a complete labeled snapshot without silently coercing the target."""
    rows = pd.read_csv(path)
    if not rows.columns.is_unique or set(rows) != {"ID", TARGET, *PREDICTORS}:
        raise ValueError("Dataset schema does not match the UCI/Kaggle credit-card snapshot.")
    validate_predictors(rows.loc[:, PREDICTORS])
    if rows.ID.isna().any() or not rows.ID.is_unique:
        raise ValueError("Dataset IDs must be present and unique.")
    if rows[TARGET].isna().any() or set(rows[TARGET]) != {0, 1}:
        raise ValueError("Dataset target must contain both binary classes, 0 and 1.")
    return rows
