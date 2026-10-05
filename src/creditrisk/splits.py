"""Validate exact-vector grouping and deterministic group-aware splits."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

from .schema import PREDICTORS


def predictor_groups(rows: pd.DataFrame) -> np.ndarray:
    predictors = rows.loc[:, PREDICTORS]
    hashes = pd.util.hash_pandas_object(predictors, index=False).to_numpy().astype(str)
    if len(np.unique(hashes)) != len(predictors.drop_duplicates()):
        raise ValueError("Predictor-vector hash collision detected.")
    return hashes


def disjoint_groups(groups, train, hold) -> None:
    groups = np.asarray(groups)
    if np.intersect1d(groups[train], groups[hold]).size:
        raise ValueError("Identical predictor groups cross a training/held-out boundary.")


def group_folds(target, groups, *, count: int, seed: int) -> list[tuple[np.ndarray, np.ndarray]]:
    target, groups = np.asarray(target), np.asarray(groups)
    folds = list(
        StratifiedGroupKFold(n_splits=count, shuffle=True, random_state=seed).split(
            np.zeros(len(target)), target, groups
        )
    )
    for train, hold in folds:
        disjoint_groups(groups, train, hold)
        if len(np.unique(target[train])) != 2 or len(np.unique(target[hold])) != 2:
            raise ValueError("Every training and held-out fold must contain both classes.")
    return folds


def validate_assignment(rows: pd.DataFrame, assignment: pd.DataFrame) -> None:
    if not np.array_equal(rows.ID, assignment.ID):
        raise ValueError("Data and split assignment IDs/order differ.")
    if not np.array_equal(predictor_groups(rows), assignment.group.astype(str)):
        raise ValueError("Split groups differ from actual predictor vectors.")
    if assignment.groupby("group").original_partition.nunique().max() != 1:
        raise ValueError("A predictor group crosses original partitions.")
    fit = assignment.original_partition == "fit"
    if assignment.loc[fit].groupby("group").cv_fold.nunique().max() != 1:
        raise ValueError("A predictor group crosses outer CV folds.")
