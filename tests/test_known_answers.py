"""Known-answer tests: exact values worked by hand or by an independent route.

A mutation-testing run (mutmut 3.8, significance.py against its own tests) left 40% of
the mutants alive, among them a PSR whose '/ denom' became '* denom', dropped
bias=False flags, flipped signs and off-by-one lag windows: for daily returns the PSR
denominator is ~1 and tolerance-based behaviour tests cannot see such changes. Each
test below pins a value that one of those mutants changes:

  * kernels and windows at their boundaries (Parzen, flat-top, the z-score reference
    window, the 21-bar correlation gate, the exit scan's strict inequalities and its
    time stop, the time-stop clamp);
  * the exact output dictionaries on degenerate inputs (callers index these keys);
  * the two bootstraps reproduced draw for draw by loop-per-resample re-implementations
    that consume the same random stream (numpy's Generator gives the same integers
    whether they are drawn in chunks or at once);
  * the significance report as the composition of its parts;
  * the execution-cost model in dollars, bucket boundaries included.
"""
import math

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm

from pairs_trading.significance import (
    _flat_top, _is_constant, _lw_standard_error, _parzen, align_return_series, annualized_sharpe,
    block_bootstrap_sharpe_ci, bootstrap_mean_ci, deflated_sharpe_ratio, hac_tstat_mean,
    lo_annualized_sharpe, oos_window_test, politis_white_block_length, probabilistic_sharpe_ratio,
    sharpe_difference_test, significance_report,
)
from pairs_trading.trading_system import (
    CompleteFixedRussell3000TradingSystem, geometric_annualised_return, max_drawdown_from_returns,
)
from pairs_trading.transaction_costs import (
    EnhancedPrimeFundTransactionCostModel, calculate_profile_trade_costs, half_spread_bps,
    sqrt_impact_bps,
)

S = CompleteFixedRussell3000TradingSystem
NAN = float('nan')


def _same(a, b):
    """Deep equality of nested dicts/lists of numbers, NaN == NaN, floats to 1e-12."""
    if isinstance(a, dict):
        return isinstance(b, dict) and set(a) == set(b) and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)):
        return isinstance(b, (list, tuple)) and len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, (float, np.floating)) and isinstance(b, (float, int, np.floating, np.integer)):
        if math.isnan(a) or math.isnan(b):
            return math.isnan(a) and math.isnan(b)
        return b == pytest.approx(a, rel=1e-12, abs=1e-15)
    return a == b


# ═══════════════════════════════════════════════════════════════════════════════
# Kernels, lag rules and small-sample boundaries
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('x,w', [(0.0, 1.0), (0.25, 1 - 6 / 16 + 6 / 64), (-0.25, 1 - 6 / 16 + 6 / 64),
                                 (0.5, 0.25), (0.75, 2 * 0.25 ** 3), (0.9, 2 * 0.1 ** 3), (1.0, 0.0),
                                 (1.2, 0.0), (-1.5, 0.0)])
def test_parzen_kernel_values(x, w):
    """Parzen-Gallant: 1 - 6x^2 + 6|x|^3 for |x| <= 1/2, 2(1 - |x|)^3 for 1/2 < |x| <= 1, else 0."""
    assert _parzen(x) == pytest.approx(w, abs=1e-15)


def test_flat_top_window_values():
    """Politis-Romano trapezoid: 1 for |x| <= 1/2, 2(1 - |x|) up to 1, 0 beyond."""
    x = np.array([0.0, 0.3, 0.5, -0.5, 0.6, 0.75, -0.9, 1.0, 1.4, -3.0])
    np.testing.assert_allclose(_flat_top(x), [1, 1, 1, 1, 0.8, 0.5, 0.2, 0, 0, 0], rtol=0, atol=1e-15)


def test_sharpe_of_two_points_and_of_missing_values():
    """Two distinct points have a defined Sharpe: mean 0.02, sd sqrt(2e-4) -> 0.02/0.014142
    x sqrt(252) = 22.45. None (a JSON null) and NaN are ignored."""
    expected = 0.02 / math.sqrt(2e-4) * math.sqrt(252)
    assert annualized_sharpe([0.01, 0.03]) == pytest.approx(expected, rel=1e-12)
    assert annualized_sharpe([0.01, None, 0.03, float('nan')]) == pytest.approx(expected, rel=1e-12)
    assert annualized_sharpe([0.01]) == 0.0 and annualized_sharpe([]) == 0.0
    assert annualized_sharpe([0.01, 0.03], periods=12) == pytest.approx(0.02 / math.sqrt(2e-4) * math.sqrt(12))
    assert not _is_constant(np.array([0.01, 0.03])) and _is_constant(np.array([0.01]))


def test_constant_test_is_relative_to_the_level():
    """Constant 'up to rounding of its level': returns quoted in tiny units keep their
    Sharpe; a genuinely flat series at any level has none."""
    r = np.random.default_rng(0).normal(0.0004, 0.01, 300)
    for scale in (1e-12, 1e-6, 1.0, 1e6):
        assert annualized_sharpe(scale * r) == pytest.approx(annualized_sharpe(r), rel=1e-9)
        assert not _is_constant(scale * r)
        assert _is_constant(np.full(300, 0.001 * scale))


def test_degenerate_outputs_have_the_documented_shape():
    """Exact outputs on inputs without a defined statistic (callers index these keys)."""
    assert _same(probabilistic_sharpe_ratio([0.01, 0.02]), {
        'psr': NAN, 'sr_ann': 0.0, 'sr_per_period': NAN, 'skew': NAN, 'kurtosis': NAN, 'n': 2,
        'benchmark_ann': 0.0, 'variance_at': 'estimate'})
    assert _same(probabilistic_sharpe_ratio(np.full(10, 0.01), 0.7, variance_at='null'), {
        'psr': NAN, 'sr_ann': 0.0, 'sr_per_period': NAN, 'skew': NAN, 'kurtosis': NAN, 'n': 10,
        'benchmark_ann': 0.7, 'variance_at': 'null'})
    assert _same(deflated_sharpe_ratio([0.01, 0.03], 5), {
        'dsr': NAN, 'sr_star_ann': NAN, 'n_trials': 5, 'std_sr_trials_ann': NAN,
        'observed_sr_ann': annualized_sharpe([0.01, 0.03])})
    assert _same(deflated_sharpe_ratio([0.01, 0.03, -0.01, 0.0], 0), {
        'dsr': NAN, 'sr_star_ann': NAN, 'n_trials': 0, 'std_sr_trials_ann': NAN,
        'observed_sr_ann': annualized_sharpe([0.01, 0.03, -0.01, 0.0])})
    r3 = [0.01, 0.02, 0.04]
    iid = annualized_sharpe(r3)
    assert _same(lo_annualized_sharpe(r3), {'sharpe': iid, 'eta': math.sqrt(252), 'lags': 0,
                                            'iid_sharpe': iid, 'autocorr': []})
    assert _same(hac_tstat_mean([0.01, 0.03]), {'tstat': 0.0, 'pvalue': 1.0, 'mean': 0.0, 'lags': 0})
    assert _same(block_bootstrap_sharpe_ci([0.01, 0.03]), {
        'lo': NAN, 'hi': NAN, 'point': annualized_sharpe([0.01, 0.03]), 'n_boot': 5000, 'block': 1,
        'block_method': 'politis-white'})
    assert _same(oos_window_test([0.01]), {
        'n': 1, 'mean': 0.01, 'std': NAN, 'stderr': NAN, 'tstat': 0.0, 'pvalue': 1.0,
        'pvalue_mean_lt0': NAN, 'pvalue_mean_gt0': NAN, 'positive': 1, 'ci_lo': NAN, 'ci_hi': NAN,
        'ci_method': 't', 'boot_ci_lo': NAN, 'boot_ci_hi': NAN})
    assert _same(oos_window_test([]), {
        'n': 0, 'mean': 0.0, 'std': NAN, 'stderr': NAN, 'tstat': 0.0, 'pvalue': 1.0,
        'pvalue_mean_lt0': NAN, 'pvalue_mean_gt0': NAN, 'positive': 0, 'ci_lo': NAN, 'ci_hi': NAN,
        'ci_method': 't', 'boot_ci_lo': NAN, 'boot_ci_hi': NAN})
    assert _same(bootstrap_mean_ci([0.02]), {'lo': NAN, 'hi': NAN, 'point': 0.02})
    assert _same(bootstrap_mean_ci([]), {'lo': NAN, 'hi': NAN, 'point': 0.0})
    a = np.linspace(-0.01, 0.02, 19)
    assert _same(sharpe_difference_test(a, a[::-1]), {
        'diff': NAN, 'sharpe_a': NAN, 'sharpe_b': NAN, 'se': NAN, 'tstat': NAN, 'ci_lo': NAN,
        'ci_hi': NAN, 'pvalue': NAN, 'n': 19, 'block': None, 'block_method': 'politis-white',
        'n_boot': 5000, 'alpha': 0.05, 'method': 'Ledoit-Wolf (2008) studentized circular block bootstrap'})


def test_smallest_samples_that_are_estimated():
    """The first length at which each statistic is computed rather than defaulted."""
    r = [0.01, -0.004, 0.02, 0.006]
    assert np.isfinite(probabilistic_sharpe_ratio(r)['psr'])                      # n = 4
    assert np.isfinite(probabilistic_sharpe_ratio(r[:3])['sr_per_period'])        # n = 3
    assert np.isfinite(deflated_sharpe_ratio(r[:3], 5)['sr_star_ann'])            # n = 3
    assert hac_tstat_mean(r[:3])['lags'] == 1                                     # n = 3
    lo4 = lo_annualized_sharpe(r)                                                 # n = 4
    assert lo4['lags'] == 1 and len(lo4['autocorr']) == 1
    assert lo_annualized_sharpe(r + [0.0], max_lag=10)['lags'] == 3               # capped at n - 2
    assert oos_window_test(r[:2])['n'] == 2 and np.isfinite(oos_window_test(r[:2])['stderr'])
    assert np.isfinite(bootstrap_mean_ci(r[:2], n_boot=50)['lo'])
    assert sharpe_difference_test(np.linspace(-0.01, 0.02, 20), np.linspace(0.02, -0.01, 20) ** 2,
                                  n_boot=99)['n'] == 20
    assert np.isfinite(sharpe_difference_test(np.sin(np.arange(20.0)) / 100 + 0.001,
                                              np.cos(np.arange(20.0)) / 100, n_boot=99)['pvalue'])


def test_input_validation_messages():
    with pytest.raises(ValueError, match="variance_at must be 'estimate' or 'null'"):
        probabilistic_sharpe_ratio([0.01, 0.02, 0.03], variance_at='plug-in')
    with pytest.raises(ValueError, match="bootstrap must be 'circular' or 'stationary'"):
        politis_white_block_length(np.arange(10.0), 'moving')
    with pytest.raises(ValueError, match='must be aligned'):
        sharpe_difference_test([0.01, 0.02], [0.01])
    with pytest.raises(ValueError, match='each dates list must match its returns in length'):
        align_return_series(['2024-01-02'], [0.01], ['2024-01-02', '2024-01-03'], [0.01])


def test_lo_sharpe_with_extreme_negative_autocorrelation():
    """Alternating returns: rho_1 = -19/20 = -0.95, so with one lag the variance ratio
    252 + 2 x 251 x (-0.95) = -224.9 is negative and the Lo Sharpe is undefined (NaN)."""
    r = 0.001 + 0.01 * (-1.0) ** np.arange(20)
    lo = lo_annualized_sharpe(r, max_lag=1)
    assert lo['lags'] == 1 and lo['autocorr'] == [pytest.approx(-0.95, abs=1e-12)]
    assert math.isnan(lo['sharpe']) and math.isnan(lo['eta'])
    assert lo['iid_sharpe'] == pytest.approx(annualized_sharpe(r), rel=1e-12)
    assert lo_annualized_sharpe(r, max_lag=0)['autocorr'] == []
    # q = 2 periods: one lag, ratio 2 + 2 x 1 x (-0.95) = 0.1 > 0, eta = 2 / sqrt(0.1)
    lo2 = lo_annualized_sharpe(r, periods=2, max_lag=5)
    assert lo2['lags'] == 1 and lo2['eta'] == pytest.approx(2 / math.sqrt(0.1), rel=1e-12)


def test_dsr_zero_or_negative_trial_variance_means_the_default():
    r = np.random.default_rng(3).normal(0.0006, 0.01, 300)
    default = deflated_sharpe_ratio(r, 10)
    assert default['std_sr_trials_ann'] == pytest.approx(math.sqrt(252 / 300))
    for v in (0.0, -1.0):
        assert _same(deflated_sharpe_ratio(r, 10, var_sr_trials_ann=v), default)
    assert deflated_sharpe_ratio(r, 10, var_sr_trials_ann=0.5)['std_sr_trials_ann'] == pytest.approx(math.sqrt(0.5))


# ═══════════════════════════════════════════════════════════════════════════════
# Politis-White: the guards the arch comparison cannot reach
# ═══════════════════════════════════════════════════════════════════════════════

def test_block_length_is_one_when_the_long_run_variance_estimate_is_not_positive():
    """x = first differences of white noise (an MA(1) with a unit root, long-run variance
    0): the flat-top estimate g(0) = acov_0 + 2 sum lambda acov_k is -0.24 here, so there is
    no usable dependence estimate and the block is 1. (arch, which squares g(0) without a
    guard, returns 31.9 on the same series.)"""
    x = np.diff(np.random.default_rng(1).normal(size=201))
    assert politis_white_block_length(x, 'circular') == 1.0
    assert politis_white_block_length(x, 'stationary') == 1.0


def test_constant_series_has_block_length_one():
    for n in (30, 252):
        x = np.full(n, 0.001)
        assert politis_white_block_length(x) == 1.0
        assert block_bootstrap_sharpe_ci(x, n_boot=10)['block'] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# The bootstraps, draw for draw
# ═══════════════════════════════════════════════════════════════════════════════

def _sharpe_ci_reference(r, block, n_boot, alpha, periods, seed):
    """Circular block bootstrap of the annualised Sharpe, one resample at a time: ceil(n/b)
    blocks of b consecutive (wrapping) observations with uniform start points, truncated
    to n; a resample without dispersion scores 0; percentile interval."""
    n = len(r)
    k = math.ceil(n / block)
    starts = np.random.default_rng(seed).integers(0, n, size=(n_boot, k))
    boots = []
    for row in starts:
        idx = np.concatenate([(s + np.arange(block)) % n for s in row])[:n]
        x = r[idx]
        sd = x.std(ddof=1)
        boots.append(x.mean() / sd * math.sqrt(periods) if sd > 1e-12 * np.abs(x).max() else 0.0)
    return np.percentile(boots, 100 * alpha / 2), np.percentile(boots, 100 * (1 - alpha / 2))


@pytest.mark.parametrize('n,block,n_boot,alpha,periods,seed', [
    (300, 5, 999, 0.05, 252, 42),
    (630, 3, 5000, 0.10, 252, 7),        # n_boot > one chunk: the stream is drawn in two parts
    (61, 60, 200, 0.05, 12, 1),          # n = block + 1, the shortest sample that is resampled
])
def test_block_bootstrap_sharpe_ci_matches_a_per_resample_reference(n, block, n_boot, alpha, periods, seed):
    r = np.random.default_rng(seed + 100).normal(0.0005, 0.01, n)
    got = block_bootstrap_sharpe_ci(r, block=block, n_boot=n_boot, alpha=alpha, periods=periods, seed=seed)
    lo, hi = _sharpe_ci_reference(r, block, n_boot, alpha, periods, seed)
    assert got['lo'] == pytest.approx(lo, rel=1e-12) and got['hi'] == pytest.approx(hi, rel=1e-12)
    assert got['point'] == pytest.approx(annualized_sharpe(r, periods), rel=1e-12)
    assert (got['block'], got['n_boot'], got['block_method']) == (block, n_boot, 'fixed')


def test_block_bootstrap_defaults_and_automatic_block():
    r = np.random.default_rng(5).normal(0.0005, 0.01, 252)
    assert _same(block_bootstrap_sharpe_ci(r, n_boot=300),
                 block_bootstrap_sharpe_ci(r, n_boot=300, alpha=0.05, periods=252, seed=42,
                                           block=math.ceil(politis_white_block_length(r)))
                 | {'block_method': 'politis-white'})
    assert block_bootstrap_sharpe_ci(r[:7], n_boot=50)['block'] == 1           # n < 8: block 1


def _lw_bootstrap_reference(a, b, block, n_boot, seed, alpha, periods):
    """Ledoit & Wolf (2008) section 3.2, one resample at a time: floor(T/b) circular
    blocks, resample length L = floor(T/b) b; the bootstrap SE from block means of the centred
    moments (Wolf's bootStats_Sharpe, without its T/(T-4) factor); two-sided p =
    (#{d* >= d} + 1)/(M + 1); symmetric studentised interval. The original statistic is
    studentised by the project's HAC SE, checked against Wolf's code elsewhere."""
    T = len(a)
    n_blocks = T // block
    L = n_blocks * block

    def moments(x, y):
        return x.mean(), y.mean(), np.mean(x * x), np.mean(y * y)

    def sr_diff(m1, m2, g1, g2):
        return m1 / math.sqrt(g1 - m1 ** 2) - m2 / math.sqrt(g2 - m2 ** 2)

    def gradient(m1, m2, g1, g2):
        v1, v2 = (g1 - m1 ** 2) ** 1.5, (g2 - m2 ** 2) ** 1.5
        return np.array([g1 / v1, -g2 / v2, -0.5 * m1 / v1, 0.5 * m2 / v2])

    diff = sr_diff(*moments(a, b))
    se = _lw_standard_error(a, b)
    d = abs(diff) / se
    starts = np.random.default_rng(seed).integers(0, T, size=(n_boot, n_blocks))
    d_star = []
    for row in starts:
        idx = np.concatenate([(s + np.arange(block)) % T for s in row])[:L]
        A, B = a[idx], b[idx]
        mom = moments(A, B)
        Y = np.column_stack([A - mom[0], B - mom[1], A * A - mom[2], B * B - mom[3]])
        Z = math.sqrt(block) * Y.reshape(n_blocks, block, 4).mean(axis=1)
        se_star = math.sqrt(np.mean((Z @ gradient(*mom)) ** 2) / L)
        d_star.append(abs(sr_diff(*mom) - diff) / se_star)
    d_star = np.array(d_star)
    q = np.quantile(d_star, 1 - alpha)
    ann = math.sqrt(periods)
    return {'pvalue': (np.sum(d_star >= d) + 1) / (n_boot + 1), 'se': se * ann, 'tstat': diff / se,
            'ci_lo': (diff - q * se) * ann, 'ci_hi': (diff + q * se) * ann, 'diff': diff * ann}


@pytest.mark.parametrize('T,block,n_boot,seed,alpha,periods', [
    (300, 4, 999, 42, 0.05, 252),
    (500, 7, 1500, 3, 0.10, 252),
    (120, 6, 4000, 9, 0.05, 12),          # several chunks of the random stream
])
def test_sharpe_difference_bootstrap_matches_a_per_resample_reference(T, block, n_boot, seed, alpha, periods):
    rng = np.random.default_rng(seed)
    common = rng.normal(0, 0.008, T)
    a = common + rng.normal(0.0006, 0.006, T)
    b = 0.5 * common + rng.normal(0.0001, 0.007, T)
    got = sharpe_difference_test(a, b, block=block, n_boot=n_boot, seed=seed, alpha=alpha, periods=periods)
    ref = _lw_bootstrap_reference(a, b, block, n_boot, seed, alpha, periods)
    assert got['pvalue'] == pytest.approx(ref['pvalue'], rel=1e-12)
    for k in ('se', 'tstat', 'ci_lo', 'ci_hi', 'diff'):
        assert got[k] == pytest.approx(ref[k], rel=1e-10), k
    assert got['sharpe_a'] == pytest.approx(a.mean() / a.std() * math.sqrt(periods), rel=1e-12)
    assert got['sharpe_b'] == pytest.approx(b.mean() / b.std() * math.sqrt(periods), rel=1e-12)
    assert (got['n'], got['block'], got['n_boot'], got['alpha'], got['block_method']) == \
        (T, block, n_boot, alpha, 'fixed')


def test_sharpe_difference_block_rules_and_defaults():
    rng = np.random.default_rng(12)
    a = rng.normal(0.0005, 0.01, 200)
    e = rng.normal(0, 0.01, 300)
    b = np.empty(300)
    b[0] = e[0]
    for t in range(1, 300):
        b[t] = 0.8 * b[t - 1] + e[t]
    b = b[100:]
    auto = sharpe_difference_test(a, b, n_boot=199)
    assert auto['block'] == math.ceil(max(politis_white_block_length(a), politis_white_block_length(b)))
    assert auto['block'] > math.ceil(politis_white_block_length(a))       # the persistent series sets it
    assert auto['block_method'] == 'politis-white'
    assert sharpe_difference_test(a, b, block=1000, n_boot=99)['block'] == 100   # at most T // 2
    assert sharpe_difference_test(a, b, block=0, n_boot=99)['block'] == 1
    assert _same(sharpe_difference_test(a, b, n_boot=199),
                 sharpe_difference_test(a, b, n_boot=199, seed=42, alpha=0.05, periods=252))
    # rows non-finite in EITHER series are dropped before anything is computed
    a2, b2 = a.copy(), b.copy()
    a2[3], b2[150] = np.nan, np.inf
    keep = np.isfinite(a2) & np.isfinite(b2)
    assert _same(sharpe_difference_test(a2, b2, block=5, n_boot=99),
                 sharpe_difference_test(a[keep], b[keep], block=5, n_boot=99))


def test_sharpe_difference_identical_series():
    a = np.random.default_rng(13).normal(0.0005, 0.01, 200)
    same = sharpe_difference_test(a, a.copy(), block=4, n_boot=99)
    assert (same['diff'], same['se'], same['tstat'], same['ci_lo'], same['ci_hi'], same['pvalue']) == \
        (0.0, 0.0, 0.0, 0.0, 0.0, 1.0)


def test_sharpe_difference_lockstep_series():
    """b = 3a: identical Sharpe ratios and a difference with no sampling variance."""
    a = np.random.default_rng(13).normal(0.0005, 0.01, 200)
    out = sharpe_difference_test(a, 3 * a, block=4, n_boot=99)
    assert out['pvalue'] == 1.0
    assert abs(out['ci_lo']) < 1e-9 and abs(out['ci_hi']) < 1e-9


def test_bootstrap_mean_ci_matches_a_per_resample_reference():
    v = np.array([0.012, -0.004, 0.0, 0.007, -0.011, 0.003, 0.0, 0.009, -0.002, 0.005])
    rng = np.random.default_rng(42)
    boots = [v[rng.integers(0, len(v), size=len(v))].mean() for _ in range(5000)]
    got = bootstrap_mean_ci(v)
    assert got['lo'] == pytest.approx(np.percentile(boots, 2.5), rel=1e-12)
    assert got['hi'] == pytest.approx(np.percentile(boots, 97.5), rel=1e-12)
    assert got['point'] == pytest.approx(v.mean(), rel=1e-12)
    rng = np.random.default_rng(5)
    boots = [v[rng.integers(0, len(v), size=len(v))].mean() for _ in range(400)]
    got = bootstrap_mean_ci(v, n_boot=400, alpha=0.2, seed=5)
    assert (got['lo'], got['hi']) == pytest.approx((np.percentile(boots, 10), np.percentile(boots, 90)), rel=1e-12)


def test_oos_window_test_matches_statsmodels_t_inference():
    """One-sample t-test, its one-sided p-values and the 95% t interval, against
    statsmodels DescrStatsW; 'positive' counts strictly positive windows."""
    from statsmodels.stats.weightstats import DescrStatsW
    v = np.array([-0.004, -0.002, 0.001, -0.006, -0.003, 0.0, -0.001, 0.002, -0.005, 0.0])
    d = DescrStatsW(v)
    t, p, _ = d.ttest_mean(0.0)
    out = oos_window_test(v)
    assert out['tstat'] == pytest.approx(t, rel=1e-12) and out['pvalue'] == pytest.approx(p, rel=1e-10)
    assert out['pvalue_mean_lt0'] == pytest.approx(d.ttest_mean(0.0, alternative='smaller')[1], rel=1e-10)
    assert out['pvalue_mean_gt0'] == pytest.approx(d.ttest_mean(0.0, alternative='larger')[1], rel=1e-10)
    lo, hi = d.tconfint_mean(alpha=0.05)
    assert (out['ci_lo'], out['ci_hi']) == pytest.approx((lo, hi), rel=1e-12)
    assert out['std'] == pytest.approx(v.std(ddof=1), rel=1e-12)
    assert out['stderr'] == pytest.approx(v.std(ddof=1) / math.sqrt(10), rel=1e-12)
    assert out['positive'] == 2 and out['n'] == 10 and out['ci_method'] == 't'
    boot = bootstrap_mean_ci(v)
    assert (out['boot_ci_lo'], out['boot_ci_hi']) == (boot['lo'], boot['hi'])


def test_significance_report_is_the_composition_of_its_parts():
    rng = np.random.default_rng(21)
    daily, oos = rng.normal(0.0004, 0.01, 260), rng.normal(0.0001, 0.012, 130)
    windows = np.array([0.01, -0.02, 0.015, 0.0])
    rep = significance_report(daily, oos_window_returns=windows, oos_daily_returns=oos,
                              n_trials=12, var_sr_trials_ann=0.3, periods=12)

    def battery(r):
        lo = lo_annualized_sharpe(r, 12)
        return {'n_days': len(r), 'ann_sharpe': annualized_sharpe(r, 12), 'ann_sharpe_lo': lo['sharpe'],
                'lo_eta': lo['eta'], 'lo_lags': lo['lags'],
                'psr_gt0': probabilistic_sharpe_ratio(r, 0.0, 12),
                'psr_gt0_null_variance': probabilistic_sharpe_ratio(r, 0.0, 12, variance_at='null'),
                'hac': hac_tstat_mean(r), 'bootstrap_sharpe_ci': block_bootstrap_sharpe_ci(r, periods=12),
                'deflated_sharpe': deflated_sharpe_ratio(r, 12, 0.3, 12)}
    assert _same(rep, {'main_backtest': battery(daily), 'oos_daily': battery(oos),
                       'oos_windows': oos_window_test(windows)})
    # defaults: one trial (no DSR), 252 periods; OOS parts need > 2 days and >= 2 windows
    base = significance_report(daily, oos_window_returns=windows[:2], oos_daily_returns=oos[:3])
    assert 'deflated_sharpe' not in base['main_backtest']
    assert base['main_backtest']['ann_sharpe'] == pytest.approx(annualized_sharpe(daily, 252))
    assert set(base) == {'main_backtest', 'oos_daily', 'oos_windows'}
    short = significance_report(daily, oos_window_returns=windows[:1], oos_daily_returns=oos[:2], n_trials=2)
    assert set(short) == {'main_backtest'} and 'deflated_sharpe' in short['main_backtest']


def test_align_return_series_known_answer():
    da = ['2024-01-02', '2024-01-03', '2024-01-03', '2024-01-05']
    ra = [0.01, 0.02, 0.025, None]                                 # duplicate: last wins; None missing
    db = ['2024-01-03', '2024-01-04', '2024-01-05', '2024-01-05', '2024-01-02']
    rb = [-0.1, -0.2, -0.3, -0.35, -0.4]
    dates, xa, xb = align_return_series(da, ra, db, rb)
    assert dates == ['2024-01-02', '2024-01-03']
    assert list(xa) == [0.01, 0.025] and list(xb) == [-0.4, -0.1]
    for empty in (align_return_series([], [], db, rb), align_return_series(da, ra, [], [])):
        assert empty[0] == [] and empty[1].shape == (0,) and empty[2].shape == (0,)
    with pytest.raises(ValueError):
        align_return_series(da, ra, db, rb[:-1])


# ═══════════════════════════════════════════════════════════════════════════════
# Engine rules at their boundaries
# ═══════════════════════════════════════════════════════════════════════════════

def _scan(z_path, action, z0, max_hold=25, beta=1.0, mu=0.0, sd=1.0):
    """_scan_exit on a path whose locked z-scores are exactly z_path (lp2 = 0)."""
    lp1 = np.asarray(z_path, float) * sd + mu
    lp2 = np.zeros(len(lp1))
    sig = {'beta': beta, 'mean': mu, 'std': sd, 'z': z0}
    return S.__new__(S)._scan_exit(lp1, lp2, list(range(len(lp1))), sig, action, max_hold)


def test_scan_exit_boundaries_long_spread():
    """Long spread (entered at z0 = -2): target when z > -0.5 strictly, stop when
    z < z0 - 1.5 = -3.5 strictly, time stop on the max_hold-th bar after the fill."""
    assert _scan([-1.0, -0.6, -0.5, -0.49], 0, -2.0) == (3, 'target')
    assert _scan([-3.0, -3.5, -3.51], 0, -2.0) == (2, 'stop')
    assert _scan([-1.0] * 5, 0, -2.0, max_hold=3) == (2, 'time')
    assert _scan([-1.0, -1.0, 0.0], 0, -2.0, max_hold=3) == (2, 'target')      # target beats time
    assert _scan([-1.0, -1.0], 0, -2.0, max_hold=3) == (None, '')
    assert _scan([-1.0], 0, -2.0, max_hold=1) == (0, 'time')


def test_scan_exit_boundaries_short_spread():
    """Short spread (entered at z0 = +2.4): target when z < 0.5, stop when z > 3.9."""
    assert _scan([1.0, 0.5, 0.49], 1, 2.4) == (2, 'target')
    assert _scan([3.0, 3.9, 3.91], 1, 2.4) == (2, 'stop')
    assert _scan([1.0] * 30, 1, 2.4) == (24, 'time')                         # default 25 bars


def test_scan_exit_uses_the_frozen_beta_mean_and_std():
    """z = (lp1 - beta lp2 - mean) / std with the signal's frozen values: here
    (0.9 - 0.8 x 1.0 - 0.1)/0.05 = 0 and (1.0 - 0.8 - 0.1)/0.05 = 2."""
    sig = {'beta': 0.8, 'mean': 0.1, 'std': 0.05, 'z': 2.5}
    ts = S.__new__(S)
    lp1, lp2 = np.array([1.0, 1.0, 0.9]), np.array([1.0, 1.0, 1.0])
    assert ts._scan_exit(lp1, lp2, [0, 1, 2], sig, 1, 25) == (2, 'target')
    assert ts._scan_exit(lp1, lp2, [0, 1], sig, 1, 25) == (None, '')


def _state(n=200, seed=0):
    rng = np.random.default_rng(seed)
    lp2 = 3.0 + np.cumsum(rng.normal(0, 0.01, n))
    lp1 = 2.0 + 0.7 * lp2 + rng.normal(0, 0.01, n)
    idx = pd.bdate_range('2022-01-03', periods=n)
    return pd.DataFrame({'lp1': lp1, 'lp2': lp2, 'beta': 0.7 + 0.001 * np.arange(n),
                         'alpha': 0.0, 'spread': 0.0}, index=idx)


@pytest.mark.parametrize('hl,window', [(21.0, 63), (5.0, 30), (10.4, 31), (40.0, 90), (None, 63)])
def test_locked_signal_reference_window(hl, window):
    """Window = clamp(int(3 x half-life), 30, 90) bars ending at row i (default half-life
    21); the locked spread uses beta at row i; mean and population std over its last 60
    bars (fewer if the window is shorter)."""
    st_ = _state()
    i = 150
    stats = {} if hl is None else {'half_life': hl}
    sig, why = S.__new__(S)._locked_signal(st_, i, stats)
    beta = 0.7 + 0.001 * i
    lk = st_['lp1'].to_numpy()[i - window + 1:i + 1] - beta * st_['lp2'].to_numpy()[i - window + 1:i + 1]
    ref = lk[-60:]
    assert why == '' and sig['beta'] == beta
    assert sig['mean'] == pytest.approx(ref.mean(), rel=1e-12)
    assert sig['std'] == pytest.approx(ref.std(ddof=0), rel=1e-12)
    assert sig['z'] == pytest.approx((lk[-1] - ref.mean()) / ref.std(ddof=0), rel=1e-12)
    np.testing.assert_allclose(sig['lk_diffs'], np.diff(lk), rtol=0, atol=1e-15)


def test_locked_signal_needs_20_bars_and_a_beta():
    st_ = _state()
    ts = S.__new__(S)
    assert ts._locked_signal(st_, 18, {'half_life': 21.0}) == (None, 'history')   # 19 bars
    sig, _ = ts._locked_signal(st_, 19, {'half_life': 21.0})                      # 20 bars
    lk = st_['lp1'].to_numpy()[:20] - sig['beta'] * st_['lp2'].to_numpy()[:20]
    assert sig['z'] == pytest.approx((lk[-1] - lk.mean()) / lk.std(), rel=1e-12)
    st_.loc[st_.index[40], 'beta'] = np.nan
    assert ts._locked_signal(st_, 40, {}) == (None, 'beta_nan')
    flat = st_.assign(lp1=1.0, lp2=0.0)
    sig, _ = ts._locked_signal(flat, 100, {})
    assert sig['std'] == 1e-8 and sig['z'] == 0.0                                 # std floor


def test_rolling_correlation_gate_uses_exactly_20_returns():
    """The gate reads the 21 bars ending at row i (20 log returns). Inside that window the
    legs move together; the return just before it is a huge opposite move, so a window
    one bar longer would see a negative correlation."""
    n = 60
    r2 = np.random.default_rng(1).normal(0, 0.01, n)
    r1 = r2.copy()
    i = 50
    r1[i - 20], r2[i - 20] = 0.5, -0.5                 # the return INTO bar i-20: outside the window
    st_ = pd.DataFrame({'lp1': np.cumsum(r1), 'lp2': np.cumsum(r2)})
    ts = S.__new__(S)
    assert ts._rolling_corr_ok(st_, i) is True
    assert np.corrcoef(np.diff(st_['lp1'].to_numpy()[i - 21:i + 1]),
                       np.diff(st_['lp2'].to_numpy()[i - 21:i + 1]))[0, 1] < 0
    assert ts._rolling_corr_ok(st_.assign(lp1=-st_['lp1']), i) is False
    assert ts._rolling_corr_ok(st_, 19) is True        # fewer than 21 bars: no verdict, pass
    assert ts._rolling_corr_ok(st_.assign(lp2=1.0), i) is False                  # flat leg


@pytest.mark.parametrize('hl,days', [(1.0, 10), (3.9, 10), (4.0, 10), (4.4, 11), (8.0, 20),
                                     (10.0, 25), (10.4, 25), (60.0, 25)])
def test_time_stop_clamp(hl, days):
    """clamp(int(2.5 x half-life), 10, 25) trading days; default half-life 10 -> 25."""
    assert S.__new__(S)._max_hold_days({'half_life': hl}) == days
    assert S.__new__(S)._max_hold_days({}) == 25


def test_fill_and_exit_prices():
    a = {'has_bar': np.array([True, False, True]), 'open': np.array([9.5, np.nan, -1.0]),
         'close_ff': np.array([10.0, 10.0, 11.0])}
    assert S._fill_price(a, 0, 'Open') == 9.5 and S._fill_price(a, 0, 'Close') == 10.0
    assert math.isnan(S._fill_price(a, 1, 'Close'))                    # no bar: no fill
    assert S._fill_price(a, 2, 'Open') == 11.0                         # bad open: the close
    ts = S.__new__(S)
    assert ts._exit_price(a, 1, 'Close') == (10.0, False)              # valued at the last close
    assert ts._exit_price(a, 2, 'Close') == (11.0, True)


def test_return_helpers():
    assert max_drawdown_from_returns([-0.1, 0.05, -0.2, 0.3]) == pytest.approx(0.9 * 1.05 * 0.8 / 1.0 - 1.0)
    assert max_drawdown_from_returns([0.1, -0.5]) == pytest.approx(-0.5)
    assert max_drawdown_from_returns([]) == 0.0
    assert geometric_annualised_return(0.21, 504) == pytest.approx(0.1, rel=1e-12)
    assert geometric_annualised_return(0.1, 0) == 0.0 and geometric_annualised_return(-1.5, 10) == -1.0


# ═══════════════════════════════════════════════════════════════════════════════
# Execution costs, in dollars
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('adv,half', [(2e9, 0.75), (500e6, 0.75), (499.9e6, 2.0), (100e6, 2.0),
                                      (99.9e6, 5.0), (20e6, 5.0), (19.9e6, 15.0), (5e6, 15.0),
                                      (4.9e6, 40.0), (1.0, 40.0), (None, 2.0), (float('nan'), 2.0),
                                      (0.0, 2.0), (-5.0, 2.0)])
def test_half_spread_buckets(adv, half):
    """Half of the full quoted spread by dollar ADV (bucket floors inclusive); unknown or
    invalid liquidity is treated as a $100M mid cap."""
    assert half_spread_bps(adv) == half


def test_sqrt_impact_known_values():
    assert sqrt_impact_bps(0.01, 0.02, 0.3, 50.0) == pytest.approx(6.0)        # 0.3 x 0.02 x 0.1 x 1e4
    assert sqrt_impact_bps(0.25, 0.04, 0.3, 50.0) == 50.0                        # 60 bp, capped
    assert sqrt_impact_bps(0.04, None, 0.5, 100.0) == pytest.approx(20.0)        # default vol 2%
    assert sqrt_impact_bps(0.04, -1.0, 0.5, 100.0) == pytest.approx(20.0)
    assert sqrt_impact_bps(-0.3, 0.02, 0.3, 50.0) == 0.0


def test_leg_cost_known_answer():
    """10,000 shares at $50 with a 1M-share ADV ($50M: 10 bp full spread) and 2% daily vol:
    commission 10,000 x $0.002 = $20; half spread 5 bp of $500k = $250; impact
    0.3 x 0.02 x sqrt(0.01) = 6 bp = $300; total $570."""
    m = EnhancedPrimeFundTransactionCostModel()
    c = m.calculate_leg_cost(10_000, 50.0, daily_volume_shares=1e6, daily_volatility=0.02)
    assert c == pytest.approx({'commission': 20.0, 'bid_ask': 250.0, 'market_impact': 300.0, 'total': 570.0})
    # a sale costs the same; a 1:10 split after the data (point-in-time price $500) means
    # 1,000 real shares, so the per-share commission falls to the $0.50 minimum... of $2
    sold = m.calculate_leg_cost(-10_000, 50.0, daily_volume_shares=1e6, daily_volatility=0.02,
                                point_in_time_price=500.0)
    assert sold['commission'] == pytest.approx(2.0) and sold['bid_ask'] == pytest.approx(250.0)
    assert m.calculate_leg_cost(100, 50.0)['commission'] == 0.5                   # per-order minimum
    defaults = m.calculate_leg_cost(10_000, 50.0)                                 # 5M shares, 2% vol
    assert defaults['bid_ask'] == pytest.approx(500_000 * 2.0 / 1e4)              # $250M ADV bucket
    assert defaults['market_impact'] == pytest.approx(500_000 * 0.3 * 0.02 * math.sqrt(10_000 / 5e6))
    for bad_price in (0.0, -1.0, float('nan')):
        assert m.calculate_leg_cost(10_000, bad_price)['total'] == 0.0
    assert m.calculate_leg_cost(0, 50.0)['total'] == 0.0


def test_holding_costs_known_answer():
    m = EnhancedPrimeFundTransactionCostModel(borrow_rate=0.0038, pb_financing_spread=0.005)
    assert m.calculate_borrow_cost(1_000_000, 'XYZ', 73) == pytest.approx(1e6 * 0.0038 * 0.2)
    assert m.calculate_financing_cost(2_000_000, 73) == pytest.approx(1e6 * 0.005 * 0.2)
    assert m.calculate_borrow_cost(-1_000_000, 'XYZ', -3) == 0.0
    total = m.calculate_total_trade_costs(1000, 2000, 50.0, 25.0, 'L', 'S', holding_days=73,
                                          long_adv_shares=1e6, short_adv_shares=2e6,
                                          long_daily_vol=0.02, short_daily_vol=0.02)
    lc = m.calculate_leg_cost(1000, 50.0, 1e6, 0.02)
    sc = m.calculate_leg_cost(2000, 25.0, 2e6, 0.02)
    assert total['total_entry_cost'] == pytest.approx(lc['total'] + sc['total'])
    assert total['total_exit_cost'] == total['total_entry_cost']
    assert total['short_borrow'] == pytest.approx(50_000 * 0.0038 * 0.2)
    assert total['financing_cost'] == pytest.approx(100_000 / 2 * 0.005 * 0.2)
    assert total['total_cost'] == pytest.approx(2 * (lc['total'] + sc['total']) + total['short_borrow']
                                                + total['financing_cost'])


def test_profile_trade_costs_known_answer():
    """$3M gross ($1M long, $2M short), 4 executions of each leg, 36.5 days held."""
    from types import SimpleNamespace
    prof = SimpleNamespace(commission_bps=1.0, bid_ask_bps=2.0, market_impact_coeff=0.5,
                           market_impact_cap_bps=40.0, borrow_rate_general=0.01, financing_spread=0.02,
                           daily_volume_dollars=1e8)
    out = calculate_profile_trade_costs(3e6, prof, 36, long_value=1e6, short_value=2e6, daily_volatility=0.02,
                                        long_adv_dollars=25e6, short_adv_dollars=200e6)
    imp_long = min(0.5 * 0.02 * math.sqrt(1e6 / 25e6) * 1e4, 40.0)               # 20 bp
    imp_short = min(0.5 * 0.02 * math.sqrt(2e6 / 200e6) * 1e4, 40.0)             # 10 bp
    assert out['commission'] == pytest.approx(2 * 3e6 * 1e-4)
    assert out['bid_ask'] == pytest.approx(2 * 3e6 * 2e-4)
    assert out['market_impact'] == pytest.approx(2 * 1e6 * imp_long / 1e4 + 2 * 2e6 * imp_short / 1e4)
    assert out['borrow'] == pytest.approx(2e6 * 0.01 * 36 / 365)
    assert out['financing'] == pytest.approx(2e6 * 0.02 * 36 / 365)
    total = sum(out[k] for k in ('commission', 'bid_ask', 'market_impact', 'borrow', 'financing'))
    assert out['total_cost'] == pytest.approx(total)
    assert out['total_bps'] == pytest.approx(total / 3e6 * 1e4)
    # without per-leg ADVs both legs use the profile ADV; equal halves without leg values
    even = calculate_profile_trade_costs(3e6, prof, 0, daily_volatility=0.02)
    imp = min(0.5 * 0.02 * math.sqrt(1.5e6 / 1e8) * 1e4, 40.0)
    assert even['market_impact'] == pytest.approx(2 * 2 * 1.5e6 * imp / 1e4)
    assert even['borrow'] == 0.0 and even['financing'] == 0.0


def test_hac_statsmodels_crosscheck_on_a_short_series():
    """A 5-point series by hand: lags = floor(4 x 0.05^(2/9)) = floor(2.06) = 2, Bartlett
    weights 2/3 and 1/3, long-run variance gamma_0 + 2 (2/3 gamma_1 + 1/3 gamma_2)."""
    r = np.array([0.01, -0.004, 0.02, 0.006, -0.012])
    e = r - r.mean()
    lrv = e @ e / 5 + 2 * (2 / 3 * (e[1:] @ e[:-1]) + 1 / 3 * (e[2:] @ e[:-2])) / 5
    out = hac_tstat_mean(r)
    assert out['lags'] == 2
    assert out['tstat'] == pytest.approx(r.mean() / math.sqrt(lrv / 5), rel=1e-12)
    ref = sm.OLS(r, np.ones(5)).fit(cov_type='HAC', cov_kwds={'maxlags': 2, 'use_correction': False})
    assert out['tstat'] == pytest.approx(float(ref.tvalues[0]), rel=1e-12)
