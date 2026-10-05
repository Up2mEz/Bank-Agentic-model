import joblib
import numpy as np
import pandas as pd
import pytest

from creditrisk.features import make_features
from creditrisk.models import Component, CreditPipeline, catboost_model
from creditrisk.nested import SearchPolicy, nested_fit
from creditrisk.splits import predictor_groups


def test_inner_search_refits_all_training_rows_without_an_eval_set(monkeypatch, rows):
    calls = []

    class SpyModel:
        def __init__(self, config, iterations):
            self.depth, self.iterations = config["depth"], iterations

        def fit(self, x, y, **kwargs):
            if "eval_set" in kwargs:
                held_features, held_target = kwargs["eval_set"]
                assert set(x.index).isdisjoint(held_features.index)
                assert len(y) + len(held_target) == len(rows)
                self.tree_count_ = 7 if self.depth == 4 else 11
            else:
                self.tree_count_ = self.iterations
                assert len(x) == len(rows)
                assert not kwargs
            calls.append({"rows": len(x), "kwargs": kwargs, "trees": self.tree_count_})
            return self

        def get_best_iteration(self):
            return self.tree_count_ - 1

        def predict_proba(self, x):
            p = 0.5 if self.depth == 4 else 0.8
            return np.tile([1 - p, p], (len(x), 1))

    monkeypatch.setattr(
        "creditrisk.nested.catboost_model",
        lambda config, iterations, seed, threads: SpyModel(config, iterations),
    )
    configs = ({"name": "d4", "depth": 4}, {"name": "d6", "depth": 6})
    policy = SearchPolicy(configs, max_iterations=15, patience=3)
    model, record = nested_fit(
        make_features(rows), np.arange(len(rows)) % 2, predictor_groups(rows), policy
    )
    assert record["selected_config"]["depth"] == 4
    assert record["refit_iterations"] == model.tree_count_ == 7
    assert len(calls) == 7
    assert calls[-1]["rows"] == len(rows) and not calls[-1]["kwargs"]
    assert all("eval_set" in call["kwargs"] for call in calls[:-1])


def test_real_saved_model_batch_single_permutation_parity(tmp_path, rows):
    features = make_features(rows)
    model = catboost_model(
        {"depth": 2, "l2_leaf_reg": 5, "learning_rate": 0.05}, iterations=8, seed=7, threads=1
    )
    model.fit(features, np.arange(len(rows)) % 2)
    pipeline = CreditPipeline([Component("catboost", model, list(features))], [1.0])
    selected = rows.iloc[[7, 1, 33]].copy()
    selected.index = [900, 17, 17]
    batch = pipeline.predict(selected)
    assert list(batch.index) == [900, 17, 17]
    assert list(batch.input_row_position) == [0, 1, 2]
    for position in range(len(selected)):
        one = pipeline.predict(selected.iloc[[position]])
        assert one.calibrated_probability.iloc[0] == pytest.approx(
            batch.calibrated_probability.iloc[position]
        )
    path = tmp_path / "model.joblib"
    joblib.dump(pipeline, path)
    pd.testing.assert_frame_equal(joblib.load(path).predict(selected), batch)


def test_pipeline_rejects_invalid_weights(rows):
    pipeline = CreditPipeline([Component("catboost", None, [])], [-1.0])
    with pytest.raises(ValueError, match="weights"):
        pipeline.predict(rows)
