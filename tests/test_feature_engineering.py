from __future__ import annotations

import numpy as np
import pytest

from data_generation import SyntheticDataGenerator
from feature_engineering import FeatureTransformer


@pytest.fixture()
def pool():
    return SyntheticDataGenerator(3).generate(60, "feat")


def _assert_dims(X, n, n_features):
    assert X.shape == (n, n_features)


def test_fit_transform_dims(pool):
    tr = FeatureTransformer().fit(pool)
    X = tr.transform(pool)
    assert X.shape == (len(pool), tr.n_features)


def test_transform_requires_fit(pool):
    tr = FeatureTransformer()
    with pytest.raises(RuntimeError):
        tr.transform(pool)


def test_transform_invariant_to_repeated_fit(pool):
    tr = FeatureTransformer().fit(pool)
    X1 = tr.transform(pool)
    X2 = tr.transform(pool)
    np.testing.assert_allclose(X1, X2)


def test_fewer_demo_samples_work(pool):
    tr = FeatureTransformer().fit(pool)
    small = pool[:10]
    X = tr.transform(small)
    assert X.shape == (10, tr.n_features)


def test_numeric_columns_standardized(pool):
    tr = FeatureTransformer().fit(pool)
    X = tr.transform(pool)
    # First NUMERIC_FEATURES columns should now be ~standardized.
    num = X[:, :7]
    means = num.mean(axis=0)
    assert np.allclose(means, 0.0, atol=1e-6)
    stds = num.std(axis=0)
    # Should not all be zero (information preserved).
    assert np.all(stds > 0.01)
