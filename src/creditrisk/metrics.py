"""Probability quality and failure diagnostics; no silent invalid-probability repair."""

from __future__ import annotations

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

EPSILON = 1e-7  # Preserves the legacy metric convention for paired comparisons.


def valid_probabilities(values, *, size: int | None = None) -> np.ndarray:
    probability = np.asarray(values, dtype=float)
    if probability.ndim != 1 or (size is not None and len(probability) != size):
        raise ValueError("Probability must be a one-dimensional array matching row count.")
    if not np.isfinite(probability).all() or ((probability < 0) | (probability > 1)).any():
        raise ValueError("Probabilities must be finite and in [0, 1].")
    return probability


def probability_metrics(target, probability) -> dict[str, float | None]:
    target = np.asarray(target)
    if target.ndim != 1 or not np.isin(target, [0, 1]).all() or len(target) == 0:
        raise ValueError("Target must be a nonempty binary vector.")
    raw = valid_probabilities(probability, size=len(target))
    clipped = np.clip(raw, EPSILON, 1 - EPSILON)
    both_classes = len(np.unique(target)) == 2
    return {
        "roc_auc": float(roc_auc_score(target, clipped)) if both_classes else None,
        "average_precision": float(average_precision_score(target, clipped))
        if both_classes
        else None,
        "log_loss": float(log_loss(target, clipped, labels=[0, 1])),
        "brier": float(brier_score_loss(target, clipped)),
    }


def confusion(target, probability, threshold: float = 0.5) -> dict[str, int | float]:
    target = np.asarray(target, dtype=int)
    p = valid_probabilities(probability, size=len(target))
    flagged = p >= threshold
    tp = int(((target == 1) & flagged).sum())
    fp = int(((target == 0) & flagged).sum())
    fn = int(((target == 1) & ~flagged).sum())
    tn = int(((target == 0) & ~flagged).sum())
    return {
        "threshold": threshold,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "flagged_rate": float(flagged.mean()),
    }


def capacity_counts(target, probability, capacities=(0.1, 0.2, 0.3, 0.4, 0.5)) -> list[dict]:
    target = np.asarray(target, dtype=int)
    p = valid_probabilities(probability, size=len(target))
    order = np.argsort(-p, kind="stable")
    rows = []
    for capacity in capacities:
        count = int(np.ceil(len(target) * capacity))
        captured = int(target[order[:count]].sum())
        rows.append(
            {
                "capacity": capacity,
                "flagged_rows": count,
                "events_captured": captured,
                "precision": captured / count,
                "recall": captured / int(target.sum()) if target.sum() else 0.0,
            }
        )
    return rows
