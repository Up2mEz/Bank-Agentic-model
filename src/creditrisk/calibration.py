"""Calibration selection uses only a designated group-disjoint calibration partition."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from .metrics import EPSILON, probability_metrics, valid_probabilities
from .splits import group_folds


def logit(probability) -> np.ndarray:
    clipped = np.clip(valid_probabilities(probability), EPSILON, 1 - EPSILON)
    return np.log(clipped / (1 - clipped)).reshape(-1, 1)


@dataclass
class Calibrator:
    kind: str = "identity"
    estimator: object | None = None

    def predict(self, probability) -> np.ndarray:
        raw = valid_probabilities(probability)
        if self.kind == "identity":
            result = raw
        elif self.kind == "sigmoid":
            result = self.estimator.predict_proba(logit(raw))[:, 1]
        elif self.kind == "isotonic":
            result = self.estimator.predict(raw)
        else:
            raise ValueError(f"Unsupported calibrator: {self.kind}")
        return valid_probabilities(result, size=len(raw))


def fit_calibrator(kind: str, probability, target) -> Calibrator:
    if kind == "identity":
        return Calibrator()
    if kind == "sigmoid":
        estimator = LogisticRegression(C=1e6, max_iter=1000).fit(logit(probability), target)
    elif kind == "isotonic":
        estimator = IsotonicRegression(out_of_bounds="clip").fit(probability, target)
    else:
        raise ValueError(f"Unsupported calibrator: {kind}")
    return Calibrator(kind, estimator)


def select_calibrator(probability, target, groups, *, seed: int) -> tuple[Calibrator, dict]:
    raw = valid_probabilities(probability, size=len(target))
    target = np.asarray(target)
    folds = group_folds(target, groups, count=5, seed=seed)
    scores = {}
    for kind in ("identity", "sigmoid", "isotonic"):
        oof = np.empty(len(target))
        for train, hold in folds:
            fitted = fit_calibrator(kind, raw[train], target[train])
            oof[hold] = fitted.predict(raw[hold])
        scores[kind] = probability_metrics(target, oof)["log_loss"]
    selected = min(scores, key=scores.get)
    return fit_calibrator(selected, raw, target), scores
