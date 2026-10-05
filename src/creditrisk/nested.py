"""Inner-only depth/iteration selection; outer labels never enter this fitter."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .metrics import probability_metrics
from .models import catboost_model
from .splits import group_folds


@dataclass(frozen=True)
class SearchPolicy:
    candidates: tuple[dict, ...]
    max_iterations: int = 2000
    patience: int = 100
    inner_folds: int = 3
    model_seed: int = 20261005
    split_seed: int = 20261006
    threads: int = 2


DEFAULT_POLICY = SearchPolicy(
    candidates=(
        {"name": "depth4", "depth": 4, "learning_rate": 0.03, "l2_leaf_reg": 10},
        {"name": "depth6", "depth": 6, "learning_rate": 0.03, "l2_leaf_reg": 20},
    )
)


def nested_fit(features: pd.DataFrame, target, groups, policy: SearchPolicy):
    """Search inside supplied training data, then refit all supplied rows.

    The median of the chosen candidate's inner best tree counts fixes refit
    iterations. This is a predefined training-size heuristic, not an optimality
    guarantee. No outer evaluation set is supplied to the refit.
    """
    target = np.asarray(target)
    groups = np.asarray(groups)
    folds = group_folds(target, groups, count=policy.inner_folds, seed=policy.split_seed)
    records = []
    for config in policy.candidates:
        diagnostics = []
        for fold, (train, hold) in enumerate(folds):
            model = catboost_model(
                config,
                iterations=policy.max_iterations,
                seed=policy.model_seed,
                threads=policy.threads,
            )
            model.fit(
                features.iloc[train],
                target[train],
                eval_set=(features.iloc[hold], target[hold]),
                early_stopping_rounds=policy.patience,
                use_best_model=True,
            )
            trees = int(model.get_best_iteration()) + 1
            if not 1 <= trees <= policy.max_iterations or model.tree_count_ != trees:
                raise ValueError("Unexpected best-iteration/tree-count mismatch.")
            p = model.predict_proba(features.iloc[hold])[:, 1]
            diagnostics.append(
                {
                    "fold": fold,
                    "train_rows": len(train),
                    "hold_rows": len(hold),
                    "best_iterations": trees,
                    "metrics": probability_metrics(target[hold], p),
                    "training_groups": len(np.unique(groups[train])),
                    "heldout_groups": len(np.unique(groups[hold])),
                    "groups_disjoint": True,
                }
            )
        records.append(
            {
                "config": config,
                "folds": diagnostics,
                "mean_inner_log_loss": float(
                    np.mean([d["metrics"]["log_loss"] for d in diagnostics])
                ),
            }
        )
    chosen = min(records, key=lambda record: record["mean_inner_log_loss"])
    iterations = int(np.median([record["best_iterations"] for record in chosen["folds"]]))
    refitted = catboost_model(
        chosen["config"], iterations=iterations, seed=policy.model_seed, threads=policy.threads
    )
    refitted.fit(features, target)
    if refitted.tree_count_ != iterations:
        raise ValueError("Refit did not use the frozen inner-derived iteration budget.")
    return refitted, {
        "selected_config": chosen["config"],
        "refit_iterations": iterations,
        "inner_search": records,
        "fit_rows": len(target),
        "no_outer_eval_set": True,
    }
