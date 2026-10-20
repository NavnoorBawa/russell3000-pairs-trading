"""Multiple testing across trials: effective number of trials, the cross-sectional
variance of trial Sharpes, the DSR-vs-N curve and t-ratio hurdles as Sharpe ratios.

Known answers: the effective-rank unit test of the reference code
(github.com/zoonek/2025-sharpe-ratio, functions.py, test_effective_rank), the hurdle
numbers of research_stat_testing.json for the v32 main backtest (T = 628, lag-1
autocorrelation 0.0675), and closed forms.
"""
import numpy as np
import pandas as pd
import pytest
from scipy import stats as sps

from pairs_trading.significance import (
    _entropy_effective_rank, annualized_sharpe, deflated_sharpe_ratio, dsr_curve,
    effective_number_of_trials, probabilistic_sharpe_ratio, sharpe_hurdles, trial_sharpe_variance,
)


def _equicorrelated(rho, n_trials, T, rng):
    common = rng.normal(0.0, 1.0, (T, 1))
    return (np.sqrt(rho) * common + np.sqrt(1 - rho) * rng.normal(0.0, 1.0, (T, n_trials))) * 0.01


# ── effective number of trials ───────────────────────────────────────────────

def test_entropy_effective_rank_reference_values():
    C = np.array([[10, 1, 7], [1, 10, 8], [7, 8, 10]]) / 10
    assert _entropy_effective_rank(np.eye(3)) == pytest.approx(3.0, abs=1e-12)
    assert abs(_entropy_effective_rank(C[:2, :2]) - 2) < 0.02
    assert abs(_entropy_effective_rank(C) - 1.84) < 0.01          # non-PSD: negative eigenvalue dropped
    assert _entropy_effective_rank(np.ones((4, 4))) == pytest.approx(1.0)


def test_effective_number_of_trials_independent_redundant_and_equicorrelated():
    rng = np.random.default_rng(0)
    indep = effective_number_of_trials(rng.normal(0.0, 0.01, (5000, 12)))
    assert indep['n_trials'] == 12
    assert indep['effective_rank'] == pytest.approx(12, rel=0.01)
    assert indep['n_eff_avg_corr'] == pytest.approx(12, rel=0.02)

    base = rng.normal(0.0, 0.01, (2000, 1))
    clones = effective_number_of_trials(base + 1e-5 * rng.normal(0.0, 1.0, (2000, 10)))
    assert clones['effective_rank'] < 1.05 and clones['n_eff_avg_corr'] < 1.01

    eq = effective_number_of_trials(_equicorrelated(0.5, 10, 20000, rng))
    assert eq['avg_correlation'] == pytest.approx(0.5, abs=0.02)
    assert eq['n_eff_avg_corr'] == pytest.approx(10 / (1 + 9 * 0.5), rel=0.03)
    # eigenvalues 1 + 9 rho and (1 - rho) x 9: entropy rank in closed form
    lam = np.array([5.5] + [0.5] * 9) / 10
    assert eq['effective_rank'] == pytest.approx(np.exp(-np.sum(lam * np.log(lam))), rel=0.02)


def test_effective_number_of_trials_edge_cases():
    rng = np.random.default_rng(1)
    R = pd.DataFrame(rng.normal(0.0, 0.01, (300, 3)), columns=list('abc'))
    R['dead'] = 0.0                                    # a variant that never traded
    R.iloc[7, 0] = np.nan
    out = effective_number_of_trials(R)
    assert out['n_trials'] == 3 and out['n_constant'] == 1
    anti = effective_number_of_trials(np.column_stack([R['b'], -R['b'] + 1e-4 * rng.normal(size=300)]))
    assert anti['avg_correlation'] < -0.99 and anti['n_eff_avg_corr'] == 2.0     # capped at N
    single = effective_number_of_trials(R[['a']])
    assert single['effective_rank'] == 1.0 and single['n_eff_avg_corr'] == 1.0
    assert effective_number_of_trials(np.zeros((50, 2)))['n_trials'] == 0
    with pytest.raises(ValueError):
        effective_number_of_trials(np.zeros(10))


# ── trial Sharpe variance and the DSR curve ──────────────────────────────────

def test_trial_sharpe_variance_null_and_redundant_families():
    """Independent null trials: the cross-sectional variance of annual Sharpes is the
    sampling variance periods / T; identical trials have none."""
    rng = np.random.default_rng(2)
    T = 500
    R = rng.normal(0.0, 0.01, (T, 400))
    v = trial_sharpe_variance(R)
    assert v == pytest.approx(np.var([annualized_sharpe(R[:, k]) for k in range(400)], ddof=1), rel=1e-12)
    assert v == pytest.approx(252 / T, rel=0.15)
    same = np.repeat(rng.normal(0.0, 0.01, (T, 1)), 5, axis=1) * np.arange(1, 6)
    assert trial_sharpe_variance(same) == pytest.approx(0.0, abs=1e-20)
    assert np.isnan(trial_sharpe_variance(rng.normal(0.0, 0.01, (T, 1))))
    eq = trial_sharpe_variance(_equicorrelated(0.8, 400, T, rng))
    assert eq < 0.4 * 252 / T                          # (1 - rho) of the independent case


def test_dsr_curve_matches_deflated_sharpe_and_decreases_with_n():
    r = np.random.default_rng(3).normal(6e-4, 0.01, 700)
    curve = dsr_curve(r, [1, 2, 10, 100, 1000])
    assert [row['n_trials'] for row in curve] == [1, 2, 10, 100, 1000]
    assert curve[0]['dsr'] == pytest.approx(probabilistic_sharpe_ratio(r)['psr'])
    for row in curve:
        assert row['dsr'] == pytest.approx(deflated_sharpe_ratio(r, row['n_trials'])['dsr'])
    dsrs = [row['dsr'] for row in curve]
    stars = [row['sr_star_ann'] for row in curve]
    assert dsrs == sorted(dsrs, reverse=True) and stars == sorted(stars)
    low_var = dsr_curve(r, [100], var_sr_trials_ann=0.05)[0]
    assert low_var['sr_star_ann'] < curve[3]['sr_star_ann'] and low_var['dsr'] > curve[3]['dsr']


# ── hurdles ──────────────────────────────────────────────────────────────────

def test_sharpe_hurdles_known_answers():
    """IID mapping SR_ann = t sqrt(252 / T): HLZ t = 3 -> 1.90, CGS t = 3.8 -> 2.41 at
    T = 628. With the AR(1) long-run variance at rho = 0.0675 the one-sided Bonferroni
    hurdles are the research note's 2.00 / 1.97 / 2.61 for N = 32 / 27 / 864; IID they are
    1.87 / 1.84 / 2.44, and Harvey-Liu's two-sided line gives 2.00 at N = 32."""
    h = sharpe_hurdles(628, 32)
    sr = {k: v['sr_ann'] for k, v in h['hurdles'].items()}
    assert sr['hlz'] == pytest.approx(1.900, abs=1e-3)
    assert sr['cgs'] == pytest.approx(2.407, abs=1e-3)
    assert sr['single_test'] == pytest.approx(1.042, abs=1e-3)
    assert sr['bonferroni_one_sided'] == pytest.approx(1.872, abs=1e-3)
    assert sr['bonferroni_two_sided'] == pytest.approx(2.004, abs=1e-3)
    assert h['hurdles']['bonferroni_one_sided']['t'] == pytest.approx(sps.norm.ppf(1 - 0.05 / 32))
    ar = [sharpe_hurdles(628, n, rho=0.0675)['hurdles']['bonferroni_one_sided']['sr_ann']
          for n in (32, 27, 864)]
    assert [round(x, 2) for x in ar] == [2.00, 1.97, 2.61]
    one = sharpe_hurdles(628, 1)['hurdles']
    assert one['bonferroni_one_sided']['t'] == pytest.approx(one['single_test']['t'])


def test_sharpe_hurdles_validation():
    with pytest.raises(ValueError):
        sharpe_hurdles(1, 5)
    with pytest.raises(ValueError):
        sharpe_hurdles(628, 0)
    with pytest.raises(ValueError):
        sharpe_hurdles(628, 5, rho=1.0)
