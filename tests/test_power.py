"""Tests for pairs_trading.power — the Sharpe-ratio standard error with non-normal, AR(1)
returns and the power report built on it.

Known answers: the unit tests and the rho = 0.2 numeric example of the reference code
(github.com/zoonek/2025-sharpe-ratio, functions.py), the closed-form variance of a
Gaussian AR(1), and the published v32 main-backtest series
(tests/fixtures/v32_main_daily_returns.csv: daily_equity_curve of
outputs/pairs_trading_results_2023_2025_unbiased.json, sha256 0d2e376f...).
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats as sps

from pairs_trading.power import (
    critical_sharpe_ratio, minimum_detectable_sharpe, minimum_track_record_length,
    power_report, sharpe_ratio_power, sharpe_ratio_variance,
)
from pairs_trading.significance import annualized_sharpe

FIXTURE = Path(__file__).parent / 'fixtures' / 'v32_main_daily_returns.csv'

# the reference's numeric example: monthly hedge-fund returns, mean 3.6%, sd 7.9%
SR_EX, G3_EX, G4_EX = 0.036 / 0.079, -2.448, 10.164


def _ar1(rho, shape, rng):
    e = rng.normal(0.0, 1.0, shape)
    x = np.empty_like(e)
    x[:, 0] = e[:, 0] / np.sqrt(1.0 - rho ** 2)
    for t in range(1, shape[1]):
        x[:, t] = rho * x[:, t - 1] + e[:, t]
    return x


# ── port of the reference functions ──────────────────────────────────────────

def test_reference_unit_tests():
    """test_sharpe_ratio_variance / test_minimum_track_record_length /
    test_sharpe_ratio_power of the reference functions.py."""
    assert round(np.sqrt(sharpe_ratio_variance(SR_EX, 24, G3_EX, G4_EX)), 3) == 0.329
    assert round(np.sqrt(sharpe_ratio_variance(SR_EX, 24)), 3) == 0.214
    assert round(minimum_track_record_length(SR_EX, 0.0, G3_EX, G4_EX, alpha=0.05), 3) == 13.029
    assert round(1 - sharpe_ratio_power(0.0, 0.5, 24, G3_EX, G4_EX), 3) == 0.315


@pytest.mark.parametrize('rho, sd, mintrl, crit, power', [
    (0.0, 0.3285885940427956, 7.908995929745377, 0.2615956178874353, 0.7575308318962203),
    (0.2, 0.37948999753333174, 11.863493894618065, 0.32038789138615015, 0.6762921036696303),
])
def test_reference_numeric_example_with_autocorrelation(rho, sd, mintrl, crit, power):
    """Values of the reference implementation at alpha = 0.10 (its numeric example),
    evaluated with the downloaded functions.py; the AR(1) terms a, b, c all enter."""
    assert np.sqrt(sharpe_ratio_variance(SR_EX, 24, G3_EX, G4_EX, rho)) == pytest.approx(sd, rel=1e-12)
    assert minimum_track_record_length(SR_EX, 0.0, G3_EX, G4_EX, rho, 0.10) == pytest.approx(mintrl, rel=1e-12)
    assert critical_sharpe_ratio(0.0, 24, G3_EX, G4_EX, rho, 0.10) == pytest.approx(crit, rel=1e-12)
    assert sharpe_ratio_power(0.0, 0.5, 24, G3_EX, G4_EX, rho, 0.10) == pytest.approx(power, rel=1e-12)


@pytest.mark.parametrize('rho', [-0.4, 0.0, 0.3, 0.6])
def test_variance_matches_gaussian_ar1_closed_form(rho):
    """Gaussian AR(1): Var(sqrt(T) mean) = sigma^2 (1+rho)/(1-rho) and Var(sqrt(T) s^2) =
    2 sigma^4 (1+rho^2)/(1-rho^2), so by the delta method
    T Var(SR_hat) = (1+rho)/(1-rho) + SR^2/2 (1+rho^2)/(1-rho^2)."""
    for sr in (0.0, 0.1, 0.5):
        expected = ((1 + rho) / (1 - rho) + sr ** 2 / 2 * (1 + rho ** 2) / (1 - rho ** 2)) / 500
        assert sharpe_ratio_variance(sr, 500, 0.0, 3.0, rho) == pytest.approx(expected, rel=1e-12)
    with pytest.raises(ValueError):
        sharpe_ratio_variance(0.1, 500, rho=1.0)


def test_mintrl_is_infinite_when_the_sharpe_does_not_exceed_the_null():
    assert minimum_track_record_length(0.0, 0.0) == np.inf
    assert minimum_track_record_length(-0.1, 0.0) == np.inf       # reference: finite
    assert np.isfinite(minimum_track_record_length(0.1, 0.0))


def test_power_is_alpha_at_the_null_and_target_at_the_mde():
    args = (0.17, 6.7, 0.07)
    assert sharpe_ratio_power(0.0, 0.0, 628, *args, alpha=0.05) == pytest.approx(0.05, abs=1e-12)
    mde = minimum_detectable_sharpe(0.0, 628, *args, alpha=0.05, power=0.80)
    assert sharpe_ratio_power(0.0, mde, 628, *args, alpha=0.05) == pytest.approx(0.80, abs=1e-9)
    assert mde > critical_sharpe_ratio(0.0, 628, *args, alpha=0.05)
    low = minimum_detectable_sharpe(0.0, 628, *args, alpha=0.05, power=0.30)
    assert sharpe_ratio_power(0.0, low, 628, *args, alpha=0.05) == pytest.approx(0.30, abs=1e-9)
    with pytest.raises(ValueError):
        minimum_detectable_sharpe(0.0, 628, power=1.0)


def test_ar1_critical_value_has_nominal_size_and_iid_one_does_not():
    """Size check on simulated AR(1) returns with zero mean (rho = 0.3, T = 500): the
    one-sided 5% test with the AR(1) critical Sharpe rejects about 5% of the time; the
    IID critical value (rho = 0) over-rejects (about 11%)."""
    rng = np.random.default_rng(0)
    x = _ar1(0.3, (4000, 500), rng)
    sr_hat = x.mean(axis=1) / x.std(axis=1, ddof=1)
    rej_ar = np.mean(sr_hat > critical_sharpe_ratio(0.0, 500, rho=0.3))
    rej_iid = np.mean(sr_hat > critical_sharpe_ratio(0.0, 500, rho=0.0))
    assert 0.035 <= rej_ar <= 0.065
    assert rej_iid >= 0.09


# ── power_report ─────────────────────────────────────────────────────────────

def _v32_main():
    return pd.read_csv(FIXTURE)['daily_return_pct'].to_numpy() / 100.0


def test_power_report_reproduces_the_v32_research_numbers():
    """research_stat_testing.json (power finding), main backtest T = 628: critical SR
    1.12, MDE (80%) 1.69, one-sided 95% upper bound 1.04, power 0.43 against SR 1,
    Bayes factors 1.4 / 3.5 / 15 / 106, MinTRL 12.4 / 3.1 / 1.4 years. The research note
    used rho = 0.068 (this estimate: 0.0675) and the null spread for the alternative in
    the MDE; the variance at the alternative gives 1.684."""
    rep = power_report(_v32_main())
    assert rep['n'] == 628
    assert rep['sr_ann'] == pytest.approx(-0.0710, abs=5e-4)
    assert rep['skew'] == pytest.approx(0.172, abs=1e-3)
    assert rep['kurtosis'] == pytest.approx(6.711, abs=1e-3)
    assert rep['rho'] == pytest.approx(0.0675, abs=1e-4)
    assert rep['critical_sr_ann'] == pytest.approx(1.115, abs=1e-3)
    assert rep['min_detectable_sr_ann'] == pytest.approx(1.684, abs=1e-3)
    assert rep['upper_bound_ann'] == pytest.approx(1.044, abs=1e-3)
    by_sr = {row['sr_ann']: row for row in rep['alternatives']}
    assert [round(by_sr[x]['bayes_factor_null_vs_alt'], 1) for x in (0.5, 1.0, 1.5, 2.0)] == [1.4, 3.5, 14.7, 106.1]
    assert [round(by_sr[x]['min_trl_years'], 1) for x in (0.5, 1.0, 1.5)] == [12.4, 3.1, 1.4]
    assert by_sr[1.0]['power'] == pytest.approx(0.43, abs=0.005)
    assert by_sr[1.0]['p_sr_at_least'] == pytest.approx(0.057, abs=1e-3)


def test_power_report_conventions_and_duality():
    r = _v32_main()
    rep = power_report(r, alternatives=(0.9, 1.0, 1.1))
    ann = np.sqrt(252)
    n, g3, g4, rho = rep['n'], rep['skew'], rep['kurtosis'], rep['rho']
    sr = annualized_sharpe(r) / ann
    # se at the estimate; critical value at the null
    assert rep['se_ann'] == pytest.approx(np.sqrt(sharpe_ratio_variance(sr, n, g3, g4, rho)) * ann)
    assert rep['critical_sr_ann'] == pytest.approx(
        1.6448536269514722 * np.sqrt(sharpe_ratio_variance(0.0, n, g3, g4, rho)) * ann)
    # p(SR >= x) < alpha exactly when x lies above the upper confidence bound
    ucb = rep['upper_bound_ann']
    for row in rep['alternatives']:
        assert (row['p_sr_at_least'] < 0.05) == (row['sr_ann'] > ucb)
    at_ucb = power_report(r, alternatives=(ucb,))['alternatives'][0]['p_sr_at_least']
    assert at_ucb == pytest.approx(0.05, abs=1e-9)
    # TOST: the larger of the two one-sided p-values
    row = rep['alternatives'][1]
    p_low = sps.norm.sf((sr + 1.0 / ann) / (rep['se_ann'] / ann))
    assert row['p_equivalence'] == pytest.approx(max(row['p_sr_at_least'], p_low))
    assert set(rep['variance_at']) >= {'se_ann', 'critical_sr_ann', 'upper_bound_ann', 'p_sr_at_least'}


def test_bayes_factor_direction_and_formula():
    rng = np.random.default_rng(1)
    noise = rng.normal(0.0, 1.0, 750)
    noise = (noise - noise.mean()) / noise.std(ddof=1) * 0.01      # mean 0, sd exactly 1%
    flat = power_report(noise)                                     # observed SR exactly 0
    assert all(row['bayes_factor_null_vs_alt'] > 1 for row in flat['alternatives'])
    bfs = [row['bayes_factor_null_vs_alt'] for row in flat['alternatives']]
    assert bfs == sorted(bfs)                                      # farther alternatives lose more
    strong = power_report(noise + 2.0 * 0.01 / np.sqrt(252))       # observed SR exactly 2
    assert strong['sr_ann'] == pytest.approx(2.0, abs=1e-9)
    row = next(x for x in strong['alternatives'] if x['sr_ann'] == 2.0)
    assert row['bayes_factor_null_vs_alt'] < 0.01
    # each hypothesis evaluated at its own variance
    ann, n = np.sqrt(252), strong['n']
    sr, args = strong['sr_ann'] / ann, (strong['skew'], strong['kurtosis'], strong['rho'])
    v0, v2 = sharpe_ratio_variance(0.0, n, *args), sharpe_ratio_variance(2.0 / ann, n, *args)
    expected = sps.norm.pdf(sr, 0.0, np.sqrt(v0)) / sps.norm.pdf(sr, 2.0 / ann, np.sqrt(v2))
    assert row['bayes_factor_null_vs_alt'] == pytest.approx(expected, rel=1e-9)


def test_power_report_sr0_shifts_the_null():
    r = _v32_main()
    base, shifted = power_report(r), power_report(r, sr0=0.5)
    assert shifted['critical_sr_ann'] > base['critical_sr_ann'] + 0.45
    assert shifted['upper_bound_ann'] == pytest.approx(base['upper_bound_ann'])
    assert next(x for x in shifted['alternatives'] if x['sr_ann'] == 0.5)['min_trl_years'] == np.inf


@pytest.mark.parametrize('r', [[], [0.01, 0.02, 0.0], np.zeros(100), np.full(50, 0.001)])
def test_power_report_degenerate_inputs_keep_the_key_set(r):
    rep = power_report(r)
    full = power_report(_v32_main())
    assert set(rep) == set(full)
    assert np.isnan(rep['upper_bound_ann']) and np.isnan(rep['alternatives'][0]['power'])
    assert set(rep['alternatives'][0]) == set(full['alternatives'][0])
