import numpy as np

from creditrisk.calibration import Calibrator, fit_calibrator, logit, select_calibrator
from creditrisk.splits import group_folds


def test_sigmoid_uses_clipped_2d_logit_and_returns_probabilities():
    raw = np.array([0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    target = np.array([0, 1, 0, 1, 0, 1])
    transformed = logit(raw)
    assert transformed.shape == (6, 1)
    assert np.isfinite(transformed).all()
    calibrated = fit_calibrator("sigmoid", raw, target)
    assert isinstance(calibrated, Calibrator)
    predictions = calibrated.predict(raw)
    np.testing.assert_allclose(predictions, calibrated.estimator.predict_proba(transformed)[:, 1])
    assert ((predictions[1:-1] > 0) & (predictions[1:-1] < 1)).all()


def test_fold_list_reusable_and_all_calibrators_scored():
    target = np.arange(120) % 2
    raw = np.linspace(0.1, 0.9, len(target))
    groups = np.arange(len(target)).astype(str)
    folds = group_folds(target, groups, count=5, seed=7)
    assert isinstance(folds, list)
    assert sum(len(hold) for _, hold in folds) == sum(len(hold) for _, hold in folds) == 120
    calibrator, scores = select_calibrator(raw, target, groups, seed=7)
    assert set(scores) == {"identity", "sigmoid", "isotonic"}
    assert np.isfinite(list(scores.values())).all()
    assert np.isfinite(calibrator.predict(raw)).all()
