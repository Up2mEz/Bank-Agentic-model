"""Model adapters centralize categorical handling and inference contracts."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from lightgbm import LGBMClassifier

from .calibration import Calibrator
from .features import make_features
from .metrics import valid_probabilities
from .schema import CATEGORIES, TARGET, validate_predictors


def catboost_model(config: dict, *, iterations: int, seed: int, threads: int):
    return CatBoostClassifier(
        depth=config["depth"],
        l2_leaf_reg=config["l2_leaf_reg"],
        iterations=iterations,
        learning_rate=config["learning_rate"],
        loss_function="Logloss",
        eval_metric="Logloss",
        cat_features=list(CATEGORIES),
        random_seed=seed,
        thread_count=threads,
        verbose=False,
        allow_writing_files=False,
    )


def lightgbm_model(*, seed: int, threads: int):
    return LGBMClassifier(
        num_leaves=15,
        n_estimators=700,
        learning_rate=0.025,
        min_child_samples=100,
        reg_lambda=10.0,
        colsample_bytree=0.9,
        random_state=seed,
        n_jobs=threads,
        verbosity=-1,
    )


def categorical_input(features: pd.DataFrame, categories: dict | None = None) -> pd.DataFrame:
    result = features.copy()
    for column in CATEGORIES:
        if column not in features:
            continue
        if categories is None:
            result[column] = pd.Categorical(features[column])
        else:
            values = features[column].where(features[column].isin(categories[column]), np.nan)
            result[column] = pd.Categorical(values, categories=categories[column])
    return result


@dataclass
class Component:
    family: str
    estimator: object
    columns: list[str]
    variant: str = "trajectory"
    categories: dict = field(default_factory=dict)

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        x = features.loc[:, self.columns]
        if self.family == "lightgbm":
            x = categorical_input(x, self.categories)
        elif self.family != "catboost":
            raise ValueError(f"Unsupported model family: {self.family}")
        return valid_probabilities(self.estimator.predict_proba(x)[:, 1], size=len(x))


@dataclass
class CreditPipeline:
    components: list[Component]
    weights: list[float]
    calibrator: Calibrator = field(default_factory=Calibrator)
    version: str = "development"
    schema_version: int = 1

    def predict(self, rows: pd.DataFrame) -> pd.DataFrame:
        if self.schema_version != 1:
            raise ValueError("Unsupported pipeline schema version.")
        if not self.components or len(self.components) != len(self.weights):
            raise ValueError("Pipeline requires one weight per component.")
        weights = np.asarray(self.weights, dtype=float)
        if (
            not np.isfinite(weights).all()
            or (weights < 0).any()
            or not np.isclose(weights.sum(), 1)
        ):
            raise ValueError("Pipeline weights must be nonnegative and sum to one.")
        clean = validate_predictors(rows)
        variants = {
            item.variant for item, weight in zip(self.components, weights, strict=True) if weight
        }
        features = {variant: make_features(clean, variant) for variant in variants}
        raw = np.zeros(len(clean))
        for item, weight in zip(self.components, weights, strict=True):
            if weight:
                raw += weight * item.predict(features[item.variant])
        raw = valid_probabilities(raw, size=len(clean))
        return pd.DataFrame(
            {
                "input_row_position": np.arange(len(clean)),
                "model_version": self.version,
                "raw_probability": raw,
                "calibrated_probability": self.calibrator.predict(raw),
                "target": TARGET,
                "purpose": "Development research; no lending decision",
            },
            index=rows.index,
        )
