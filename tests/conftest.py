import numpy as np
import pandas as pd
import pytest

from creditrisk.schema import BILLS, PAY_CODES, PAYMENTS, PREDICTORS


@pytest.fixture
def rows():
    random = np.random.default_rng(37)
    count = 120
    values = {column: np.zeros(count) for column in PREDICTORS}
    values.update(
        LIMIT_BAL=random.integers(1, 20, count) * 10000,
        SEX=random.integers(1, 3, count),
        EDUCATION=random.integers(0, 7, count),
        MARRIAGE=random.integers(0, 4, count),
        AGE=random.integers(21, 70, count),
    )
    for column in PAY_CODES:
        values[column] = random.integers(-2, 4, count)
    for column in BILLS:
        values[column] = random.integers(-4000, 200000, count)
    for column in PAYMENTS:
        values[column] = random.integers(0, 30000, count)
    frame = pd.DataFrame(values)
    frame.loc[0, "LIMIT_BAL"] = 0
    frame.loc[1, list(BILLS)] = 0
    return frame
