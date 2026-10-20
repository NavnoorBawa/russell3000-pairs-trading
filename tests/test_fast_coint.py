"""pairs_trading.fast_coint.engle_granger against statsmodels' coint.

Hermetic: simulated log-price pairs, fixed seeds. The fast test must reproduce coint's
statistic to rounding on every kind of input the selector sees (cointegrated and not,
trending, the 60-90 observation re-selection windows, near-degenerate data), take the
same p < 0.05 decision, and return exactly what coint returns (or raise what it raises)
on degenerate input.
"""
import warnings

import numpy as np
import pandas as pd
import pytest
from statsmodels.regression.linear_model import OLS
from statsmodels.tsa.stattools import adfuller, coint
from statsmodels.tsa.tsatools import add_trend

from pairs_trading import fast_coint
from pairs_trading.fast_coint import engle_granger
from pairs_trading.pair_selector import FixedPrimeFundPairSelector


def _ou(n, half_life, sd, rng):
    phi = np.exp(-np.log(2) / half_life)
    s = np.zeros(n)
    e = rng.normal(0, sd, n)
    for t in range(1, n):
        s[t] = phi * s[t - 1] + e[t]
    return s


def _random_walk(n, rng, sd=0.02, start=4.0):
    return start + np.cumsum(rng.normal(0, sd, n))


def _pair(kind, n, rng):
    """One simulated (log p1, log p2) pair of the given kind."""
    x = _random_walk(n, rng)
    if kind == 'cointegrated':
        return 0.5 + rng.uniform(0.4, 1.6) * x + _ou(n, rng.uniform(2, 40), 0.015, rng), x
    if kind == 'independent':
        return _random_walk(n, rng), x
    if kind == 'common_factor':        # correlated legs, random-walk spread
        return 3.0 + 0.8 * x + _random_walk(n, rng, sd=0.012, start=0.0), x
    if kind == 'trending':             # deterministic drift the constant-only test does not absorb
        drift = rng.uniform(-0.003, 0.003) * np.arange(n)
        return 2.0 + 0.7 * x + drift + _ou(n, rng.uniform(3, 30), 0.015, rng), x + 0.001 * np.arange(n)
    if kind == 'near_collinear':       # R^2 close to, but below, coint's collinearity cut
        return 1.0 + 1.2 * x + rng.normal(0, 10 ** rng.uniform(-4.5, -3), n), x
    if kind == 'stale':                # cent-rounded prices: runs of zero log changes
        p1 = np.round(np.exp(0.5 + 0.9 * x + _ou(n, 8, 0.01, rng)) / 10, 2)
        p2 = np.round(np.exp(x) / 10, 2)
        return np.log(p1), np.log(p2)
    if kind == 'high_level':           # log prices ~13 (a $400k share), small variance
        return 13.0 + 0.3 * (x - 4.0) + _ou(n, 10, 0.004, rng), 12.0 + 0.5 * (x - 4.0)
    if kind == 'heavy_tailed':
        y = 4.0 + np.cumsum(0.01 * rng.standard_t(2.5, n))
        return 1.0 + 0.9 * y + _ou(n, 6, 0.02, rng), y
    raise ValueError(kind)


KINDS = ('cointegrated', 'independent', 'common_factor', 'trending', 'near_collinear', 'stale',
         'high_level', 'heavy_tailed')
LENGTHS = (60, 67, 75, 87, 90, 126, 252, 503, 703, 755)


def _cases(n_cases=320, seed=20240611):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n_cases):
        kind = KINDS[i % len(KINDS)]
        n = LENGTHS[(i // len(KINDS)) % len(LENGTHS)]
        out.append((kind, n, *_pair(kind, n, rng)))
    return out


CASES = _cases()


@pytest.fixture(scope='module')
def comparisons():
    """(kind, n, statsmodels (t, p), fast (t, p), fast path used) in both directions of every case."""
    calls = []
    original = fast_coint._statsmodels_coint

    def spy(y0, y1):
        calls.append(1)
        return original(y0, y1)

    rows = []
    fast_coint._statsmodels_coint = spy
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            for kind, n, y1, y2 in CASES:
                for a, b in ((y1, y2), (y2, y1)):
                    t_sm, p_sm, _ = coint(a, b)
                    before = len(calls)
                    t_fast, p_fast = engle_granger(a, b)
                    rows.append((kind, n, (t_sm, p_sm), (t_fast, p_fast), len(calls) == before))
    finally:
        fast_coint._statsmodels_coint = original
    return rows


def test_statistic_matches_statsmodels_to_rounding(comparisons):
    """The largest difference is ~3e-14; 1e-10 (the spec asks for 1e-8) also fails the
    centred normal equations once used for the cointegrating regression (5e-10 here)."""
    assert len(comparisons) >= 600
    worst = 0.0
    for kind, n, (t_sm, _), (t_fast, _), _ in comparisons:
        if np.isinf(t_sm):
            assert t_fast == t_sm, (kind, n)
        else:
            worst = max(worst, abs(t_fast - t_sm))
    assert worst < 1e-10


def test_p_values_and_decisions_match_statsmodels(comparisons):
    for kind, n, (_, p_sm), (_, p_fast), _ in comparisons:
        assert abs(p_fast - p_sm) < 1e-12, (kind, n)
        assert (p_fast < 0.05) == (p_sm < 0.05), (kind, n)


def test_every_kind_and_length_runs_on_the_fast_path(comparisons):
    """The agreement above is the port's, not statsmodels' own: only near-collinear pairs
    (R^2 within 1e-9 of the cut) may be handed to statsmodels."""
    for kind in KINDS:
        rows = [r for r in comparisons if r[0] == kind]
        fast_share = np.mean([r[4] for r in rows])
        assert fast_share >= (0.5 if kind == 'near_collinear' else 1.0), (kind, fast_share)
    assert {r[1] for r in comparisons if r[4]} == set(LENGTHS)
    tested = [r for r in comparisons if r[4]]
    assert any(r[3][1] < 0.05 for r in tested) and any(r[3][1] > 0.5 for r in tested)


def test_regular_input_never_calls_statsmodels(monkeypatch):
    def forbidden(y0, y1):
        raise AssertionError('statsmodels called on regular input')
    monkeypatch.setattr(fast_coint, '_statsmodels_coint', forbidden)
    rng = np.random.default_rng(3)
    for kind in ('cointegrated', 'independent', 'trending'):
        y1, y2 = _pair(kind, 755, rng)
        t, p = engle_granger(y1, y2)
        assert np.isfinite(t) and 0.0 <= p <= 1.0


def test_array_like_inputs_match_statsmodels():
    rng = np.random.default_rng(5)
    y1, y2 = _pair('cointegrated', 300, rng)
    idx = pd.bdate_range('2021-01-04', periods=300)
    t_sm, p_sm, _ = coint(y1, y2)
    for a, b in ((list(y1), list(y2)), (pd.Series(y1, index=idx), pd.Series(y2, index=idx))):
        t, p = engle_granger(a, b)
        assert abs(t - t_sm) < 1e-10 and abs(p - p_sm) < 1e-10


def _outcome(fn, *args):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        try:
            out = fn(*args)
        except Exception as exc:
            return type(exc)
    return tuple(np.asarray(v, dtype=float).tobytes() for v in out[:2])


def _degenerate_inputs():
    rng = np.random.default_rng(11)
    x = _random_walk(200, rng)
    y = 1.0 + 0.8 * x + _ou(200, 5, 0.01, rng)
    with_nan, with_inf = y.copy(), x.copy()
    with_nan[50] = np.nan
    with_inf[7] = np.inf
    return {
        'constant y1': (y, np.full(200, 4.0)),
        'constant y0': (np.full(200, 4.0), x),
        'perfectly collinear': (2.0 * x + 1.0, x),
        'nan in y0': (with_nan, x),
        'inf in y1': (y, with_inf),
        'n = 3': (y[:3], x[:3]),
        'n = 4': (y[:4], x[:4]),
        'two regressors': (y, np.column_stack([x, _random_walk(200, rng)])),
        'unequal lengths': (y, x[:150]),
    }


@pytest.mark.parametrize('name', list(_degenerate_inputs()))
def test_degenerate_input_returns_or_raises_what_statsmodels_does(name):
    y0, y1 = _degenerate_inputs()[name]
    expected = _outcome(lambda a, b: coint(a, b)[:2], y0, y1)
    assert _outcome(engle_granger, y0, y1) == expected


def test_perfectly_collinear_pair_is_cointegrated_with_p_zero():
    x = _random_walk(300, np.random.default_rng(2))
    with pytest.warns(Warning, match='colinear'):
        t, p = engle_granger(3.0 * x - 2.0, x)
    assert t == -np.inf and p == 0.0


def _pair_with_r_squared(r_squared, n=300, seed=8):
    """(y0, y1) whose cointegrating regression has the given R^2 (the residual is scaled
    noise made exactly orthogonal to [y1, 1])."""
    rng = np.random.default_rng(seed)
    x = _random_walk(n, rng)
    design = np.column_stack([x, np.ones(n)])
    w = rng.normal(0, 1, n)
    w -= design @ np.linalg.lstsq(design, w, rcond=None)[0]
    signal = 0.8 ** 2 * np.sum((x - x.mean()) ** 2)
    w *= np.sqrt(signal * (1.0 - r_squared) / r_squared / (w @ w))
    return 1.0 + 0.8 * x + w, x


@pytest.mark.parametrize('side', [+1, -1])
def test_r_squared_within_the_margin_of_the_collinearity_cut_is_left_to_statsmodels(side, monkeypatch):
    """R^2 half the margin above coint's cut (statsmodels: collinear, t = -inf) and half
    the margin below it (statsmodels: the ADF test) both get statsmodels' own result."""
    y0, y1 = _pair_with_r_squared(fast_coint._COLLINEAR_R2 + side * fast_coint._R2_MARGIN / 2)
    r_squared = fast_coint._first_stage(y0, y1)[1]
    assert abs(r_squared - fast_coint._COLLINEAR_R2) < fast_coint._R2_MARGIN
    assert (r_squared >= fast_coint._COLLINEAR_R2) == (side > 0)
    calls = []
    original = fast_coint._statsmodels_coint

    def spy(a, b):
        calls.append(1)
        return original(a, b)

    monkeypatch.setattr(fast_coint, '_statsmodels_coint', spy)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        expected = coint(y0, y1)[:2]
        assert engle_granger(y0, y1) == expected
    assert calls == [1] and (expected[0] == -np.inf) == (side > 0)


def test_short_series_use_the_capped_lag_search(monkeypatch):
    """Below 18 observations the cap n // 2 - 1 binds (Schwert's rule would allow more lags);
    odd lengths still leave a residual degree of freedom and run on the fast path."""
    monkeypatch.setattr(fast_coint, '_statsmodels_coint', lambda a, b: pytest.fail('statsmodels called'))
    rng = np.random.default_rng(12)
    for n in (11, 13, 15, 17):
        assert n // 2 - 1 < np.ceil(12.0 * (n / 100.0) ** 0.25)
        for kind in ('cointegrated', 'independent'):
            y1, y2 = _pair(kind, n, rng)
            assert abs(engle_granger(y1, y2)[0] - coint(y1, y2)[0]) < 1e-10, (n, kind)


def test_first_stage_is_statsmodels_own_to_the_bit():
    """The cointegrating regression's residual and R^2 are coint's bit for bit, also for an
    ill-conditioned [y1, 1] (y1 a level of 3 with a standard deviation of ~1e-7, cond
    ~1e8), where the centred normal equations would be off by 4e-7 in t."""
    rng = np.random.default_rng(1)
    x = _random_walk(300, rng)
    flat = 3.0 + 1e-8 * np.cumsum(rng.normal(0, 1, 300))
    inputs = [(y1, y2) for _, _, y1, y2 in CASES[:48]] + [(1.0 + 0.5 * x, flat)]
    for y1, y2 in inputs:
        for a, b in ((y1, y2), (y2, y1)):
            res = OLS(a, add_trend(b[:, None], 'c', prepend=False)).fit()
            u, r_squared = fast_coint._first_stage(a, b)
            assert u.tobytes() == res.resid.tobytes() and r_squared == res.rsquared
    assert abs(engle_granger(1.0 + 0.5 * x, flat)[0] - coint(1.0 + 0.5 * x, flat)[0]) < 1e-12


def _ill_conditioned_inputs():
    """Pairs whose ADF design is too ill-conditioned for the QR route to match pinv.

    The first-stage residual is a +-0.01 sawtooth (x is made exactly orthogonal to it), so
    the lagged differences are collinear with the lagged level; the noise added to it sets
    the condition number of the ADF design (~1e15 and ~1e10). With the condition guards
    removed the fast route returns p = 0.81 where coint returns p = 0 on the first input,
    and p = 0.003 where coint returns p = 0.95 on the second.
    """
    rng = np.random.default_rng(1)
    n = 300
    x = _random_walk(n, rng)
    alt = (-1.0) ** np.arange(n)
    x_orth = x - (alt @ x) / n * alt
    return {
        'exact sawtooth': (2.0 + 0.7 * x_orth + 0.01 * alt, x_orth),
        'sawtooth + 1e-10 noise': (2.0 + 0.7 * x_orth + 0.01 * alt + rng.normal(0, 1e-10, n), x_orth),
    }


@pytest.mark.parametrize('name', list(_ill_conditioned_inputs()))
def test_ill_conditioned_adf_design_is_left_to_statsmodels(name, monkeypatch):
    y0, y1 = _ill_conditioned_inputs()[name]
    calls = []
    original = fast_coint._statsmodels_coint

    def spy(a, b):
        calls.append(1)
        return original(a, b)

    monkeypatch.setattr(fast_coint, '_statsmodels_coint', spy)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        expected = coint(y0, y1)[:2]
        assert engle_granger(y0, y1) == expected
    assert calls == [1]


def _cycle_residual_pair(n, period, noise, rng, walk=0.0):
    """(y0, y1) whose cointegrating residual is a +-0.01 cycle of the given period plus noise
    (and, with walk > 0, a random walk whose steps have standard deviation walk x noise).

    The lagged differences of a cycle are collinear with its lagged level, so the noise
    sets the condition number of the ADF design (from ~10 at 1e-2 to ~1e9 at 1e-8).
    """
    x = _random_walk(n, rng)
    u = (0.01 * np.cos(2 * np.pi * np.arange(n) / period) + rng.normal(0, noise, n)
         + walk * np.cumsum(rng.normal(0, noise, n)))
    design = np.column_stack([x, np.ones(n)])
    u -= design @ np.linalg.lstsq(design, u, rcond=None)[0]
    return 2.0 + 0.7 * x + u, x


def test_condition_guard_keeps_rounding_far_below_the_aic_tie_margin():
    """On every ADF design the condition guard admits, each lag order's AIC is statsmodels'
    to within 1% of the tie margin and the statistic to 1e-9; every design it refuses is
    statsmodels' own result. The sweep spans the guard: admitted designs reach a tenth of
    it, and more than ten are refused."""
    rng = np.random.default_rng(17)
    admitted, refused = [], 0
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        for n in (87, 755):
            for period in (2, 3):
                for noise in 10.0 ** -np.arange(2.0, 8.25, 0.25):
                    y0, y1 = _cycle_residual_pair(n, period, noise, rng)
                    u, _ = fast_coint._first_stage(y0, y1)
                    autolag = adfuller(u, regression='n', autolag='aic', regresults=True)[-1].autolag_results
                    maxlag = len(autolag) - 1
                    r, nobs, k = fast_coint._adf_factor(u, np.diff(u), maxlag, level_first=True)
                    expected = coint(y0, y1)[:2]
                    if not fast_coint._well_conditioned(r[:k, :k]):
                        refused += 1
                        assert engle_granger(y0, y1) == expected
                        continue
                    s = np.linalg.svd(r[:k, :k], compute_uv=False)
                    admitted.append(s[0] / s[-1])
                    sm_aic = np.array([autolag[m].aic for m in sorted(autolag)])
                    fast_aic = fast_coint._lag_aic(r, nobs, k)
                    assert np.abs(fast_aic - sm_aic).max() < fast_coint._AIC_MARGIN / 100, admitted[-1]
                    assert abs(engle_granger(y0, y1)[0] - expected[0]) < 1e-9, admitted[-1]
    assert refused > 10 and len(admitted) > 40
    assert max(admitted) > fast_coint._MAX_CONDITION / 10


def test_design_whose_aic_rounding_exceeds_the_tie_margin_is_left_to_statsmodels(monkeypatch):
    """An ADF design with condition number ~6e6: through the QR route its AIC values differ
    from statsmodels' by ~5e-6, more than the tie margin, so two lag orders that the
    margin calls distinct could be ranked differently. A guard of 1e7 admitted it."""
    y0, y1 = _cycle_residual_pair(755, 2, 1e-10, np.random.default_rng(6), walk=0.02)
    u, _ = fast_coint._first_stage(y0, y1)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        autolag = adfuller(u, regression='n', autolag='aic', regresults=True)[-1].autolag_results
        r, nobs, k = fast_coint._adf_factor(u, np.diff(u), len(autolag) - 1, level_first=True)
        s = np.linalg.svd(r[:k, :k], compute_uv=False)
        assert 1e6 < s[0] / s[-1] < 1e7
        sm_aic = np.array([autolag[m].aic for m in sorted(autolag)])
        assert np.abs(fast_coint._lag_aic(r, nobs, k) - sm_aic).max() > fast_coint._AIC_MARGIN

        calls = []
        original = fast_coint._statsmodels_coint

        def spy(a, b):
            calls.append(1)
            return original(a, b)

        monkeypatch.setattr(fast_coint, '_statsmodels_coint', spy)
        assert engle_granger(y0, y1) == coint(y0, y1)[:2]
    assert calls == [1]


def test_ambiguous_lag_choice_is_left_to_statsmodels(monkeypatch):
    """Every AIC gap below the margin is treated as a tie: the call is statsmodels' own."""
    monkeypatch.setattr(fast_coint, '_AIC_MARGIN', np.inf)
    rng = np.random.default_rng(4)
    y1, y2 = _pair('cointegrated', 400, rng)
    t_sm, p_sm, _ = coint(y1, y2)
    assert engle_granger(y1, y2) == (t_sm, p_sm)


def test_cointegration_pvalue_is_the_statsmodels_bonferroni_p():
    rng = np.random.default_rng(9)
    for kind in ('cointegrated', 'independent', 'stale'):
        for n in (87, 755):
            l1, l2 = _pair(kind, n, rng)
            expected = min(1.0, 2.0 * min(coint(l1, l2)[1], coint(l2, l1)[1]))
            assert abs(FixedPrimeFundPairSelector.cointegration_pvalue(l1, l2) - expected) < 1e-9
    assert FixedPrimeFundPairSelector.cointegration_pvalue(l1, l2[:-5]) == 1.0
