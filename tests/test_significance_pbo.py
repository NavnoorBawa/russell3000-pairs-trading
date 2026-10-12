"""PBO (CSCV) and market-factor attribution."""
import numpy as np
import pytest

from pairs_trading.significance import factor_attribution, pbo_cscv


def test_pbo_high_when_all_configurations_are_noise():
    rng = np.random.default_rng(0)
    res = pbo_cscv(rng.normal(0, 0.01, size=(1000, 20)), n_splits=10)
    assert res['n_combinations'] == 252
    assert 0.3 < res['pbo'] < 0.8           # pure noise: the IS winner is a coin flip OOS


def test_pbo_low_when_one_configuration_is_genuinely_better():
    rng = np.random.default_rng(1)
    M = rng.normal(0, 0.01, size=(1000, 20))
    M[:, 7] += 0.002                         # Sharpe ~3 edge in one configuration
    res = pbo_cscv(M, n_splits=10)
    assert res['pbo'] < 0.05
    assert res['mean_oos_sharpe_of_is_best'] > 1.5


def test_pbo_input_validation():
    with pytest.raises(ValueError):
        pbo_cscv(np.zeros((100, 1)))
    with pytest.raises(ValueError):
        pbo_cscv(np.zeros((100, 4)), n_splits=5)


def test_factor_attribution_recovers_alpha_and_beta():
    rng = np.random.default_rng(2)
    m = rng.normal(0.0004, 0.01, 2000)
    r = 0.0002 + 0.3 * m + rng.normal(0, 0.002, 2000)
    res = factor_attribution(r, m)
    assert res['beta'] == pytest.approx(0.3, abs=0.02)
    assert res['alpha_ann'] == pytest.approx(0.0002 * 252, abs=0.02)
    assert res['beta_tstat'] > 10


def test_factor_attribution_degenerate_input():
    res = factor_attribution(np.zeros(10), np.zeros(10))
    assert np.isnan(res['beta'])
