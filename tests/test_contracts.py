import numpy as np
import pandas as pd
import pytest

from creditrisk.features import make_features
from creditrisk.metrics import probability_metrics, valid_probabilities
from creditrisk.models import categorical_input
from creditrisk.schema import TARGET, validate_predictors
from creditrisk.splits import disjoint_groups, group_folds, predictor_groups


def test_features_ignore_outcomes_and_preserve_permutation_and_single_rows(rows):
    baseline = make_features(rows)
    augmented = rows.assign(ID=np.arange(len(rows)), **{TARGET: np.ones(len(rows))})
    pd.testing.assert_frame_equal(baseline, make_features(augmented))
    positions = [25, 0, 91, 1]
    sample = rows.iloc[positions].copy()
    sample.index = [91, 3, 3, -8]  # Duplicate and unordered caller indexes must remain positional.
    expected = baseline.iloc[positions].copy()
    expected.index = sample.index
    pd.testing.assert_frame_equal(make_features(sample), expected)
    for position in range(len(sample)):
        pd.testing.assert_frame_equal(
            make_features(sample.iloc[[position]]), expected.iloc[[position]]
        )


def test_unknown_codes_negative_bills_and_zero_denominators_are_preserved(rows):
    rows.loc[0, "EDUCATION"] = 97
    rows.loc[0, "PAY_0"] = -2
    rows.loc[0, "BILL_AMT1"] = -10
    transformed = make_features(validate_predictors(rows))
    assert transformed.loc[0, "EDUCATION"] == "97"
    assert transformed.loc[0, "PAY_0"] == "-2"
    assert transformed.loc[0, "BILL_AMT1"] == -10
    assert np.isnan(transformed.loc[0, "payment_bill_ratio_1"])
    assert np.isnan(transformed.loc[0, "recent_bill_utilization"])
    assert np.isnan(transformed.loc[1, "sum_payment_over_sum_positive_bill"])


@pytest.mark.parametrize("invalid", [np.nan, np.inf, -np.inf])
def test_invalid_numeric_input_is_rejected(rows, invalid):
    rows["BILL_AMT2"] = rows.BILL_AMT2.astype(float)
    rows.loc[0, "BILL_AMT2"] = invalid
    with pytest.raises(ValueError, match="finite"):
        validate_predictors(rows)


def test_schema_rejects_target_duplicate_columns_and_fractional_category(rows):
    with pytest.raises(ValueError, match="23"):
        validate_predictors(rows.assign(**{TARGET: 0}))
    duplicated = pd.concat([rows, rows[["PAY_0"]]], axis=1)
    with pytest.raises(ValueError, match="unique"):
        validate_predictors(duplicated)
    rows["PAY_0"] = rows.PAY_0.astype(float)
    rows.loc[0, "PAY_0"] = 0.25
    with pytest.raises(ValueError, match="integers"):
        validate_predictors(rows)


def test_conflicting_label_duplicates_stay_in_same_fold(rows):
    duplicate = rows.iloc[[1]].copy()
    frame = pd.concat([rows, duplicate], ignore_index=True)
    groups = predictor_groups(frame)
    target = np.arange(len(frame)) % 2
    target[-1] = 1 - target[1]
    assert groups[1] == groups[-1]
    for train, hold in group_folds(target, groups, count=3, seed=37):
        assert (1 in hold) == (len(frame) - 1 in hold)
        disjoint_groups(groups, train, hold)
    with pytest.raises(ValueError, match="cross"):
        disjoint_groups(groups, [1], [len(frame) - 1])


def test_lightgbm_unknown_categories_use_training_dictionary(rows):
    features = make_features(rows)
    train = categorical_input(features.iloc[1:])
    categories = {
        column: list(train[column].cat.categories) for column in train.select_dtypes("category")
    }
    probe = features.iloc[[0]].copy()
    probe["EDUCATION"] = "999"
    encoded = categorical_input(probe, categories)
    assert encoded.EDUCATION.isna().all()
    assert list(encoded.SEX.cat.categories) == categories["SEX"]


@pytest.mark.parametrize("bad", [[np.nan], [1.01], [-0.01], [[0.5]]])
def test_bad_probabilities_are_not_silently_clipped(bad):
    with pytest.raises(ValueError):
        valid_probabilities(bad)


def test_single_class_slice_has_undefined_ranking_metrics_but_finite_loss():
    metrics = probability_metrics([0, 0], [0.2, 0.3])
    assert metrics["roc_auc"] is None and metrics["average_precision"] is None
    assert metrics["log_loss"] > 0
