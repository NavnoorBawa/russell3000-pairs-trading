"""Regression tests for the v31 pre-launch audit.

Every bug covered here was live in a codebase with 94 passing tests and four prior
audits behind it. None of those tests caught any of them, because they all checked
that functions *ran*, not that they were *causal*. These check causality directly.

The strongest pattern here is PREFIX INVARIANCE: for any function that is supposed to
use only past data, computing it on the first k observations must give the same answer
as computing it on the full series and taking the first k. Anything that peeks at the
future — a full-sample variance, a .bfill(), a terminal-date lookup — fails this
immediately, without needing to know what the "right" output value is.
"""

import numpy as np
import pandas as pd
import pytest

from pairs_trading.data_processor import EnhancedRussell3000DataProcessor
from pairs_trading.significance import oos_window_test
from pairs_trading.trading_system import CompleteFixedRussell3000TradingSystem
from pairs_trading.transaction_costs import EnhancedPrimeFundTransactionCostModel


def _prices(n=400, seed=0, start=50.0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range('2021-01-01', periods=n)
    return pd.Series(start * np.exp(np.cumsum(rng.normal(0, 0.012, n))), index=idx)


def _ohlcv(n=400, seed=0):
    close = _prices(n, seed)
    return pd.DataFrame({
        'Open': close.shift(1).fillna(close.iloc[0]),
        'High': close * 1.01,
        'Low': close * 0.99,
        'Close': close,
        'Volume': np.full(n, 2_000_000.0),
    }, index=close.index)


# ── Kalman spread: process noise must not use full-sample variance ─────────────

def test_kalman_spread_is_prefix_invariant():
    """Q was `delta/(1-delta) * np.var(lp2)` over the WHOLE series, including the test
    period, so appending future bars silently changed past spread values."""
    sys_ = CompleteFixedRussell3000TradingSystem.__new__(CompleteFixedRussell3000TradingSystem)
    p1, p2 = _prices(400, seed=1), _prices(400, seed=2)
    k = 200

    full = sys_.calculate_kalman_spread(p1, p2)
    prefix = sys_.calculate_kalman_spread(p1.iloc[:k], p2.iloc[:k])

    np.testing.assert_allclose(full.iloc[:k].values, prefix.values, rtol=1e-9, atol=1e-12,
                               err_msg="Kalman spread for past dates changed when future "
                                       "data was appended — process noise is not causal")


# ── Indicators: no back-filling of future values into the warm-up ──────────────

def test_indicators_are_prefix_invariant():
    """General guard against any full-sample statistic entering the indicator block
    (a full-sample z-score, an expanding std computed over everything, etc.).

    NOTE: this invariant does NOT by itself catch the v31 `.bfill()` bug. That leak was
    bounded inside the first `min_periods` rows, which the prefix and the full series
    share, so both produced the same back-filled head and the comparison passed. The
    test below (`test_indicator_warmup_uses_only_past_bars`) is the one with teeth for
    that bug. Both are kept: they fail on different classes of regression.
    """
    proc = EnhancedRussell3000DataProcessor.__new__(EnhancedRussell3000DataProcessor)
    df = _ohlcv(400, seed=3)
    k = 150

    full = proc._process_indicators(df)
    prefix = proc._process_indicators(df.iloc[:k])

    for col in ('MA_50', 'MA_20', 'RSI_14'):
        if col not in full.columns:
            continue
        np.testing.assert_allclose(
            full[col].iloc[:k].to_numpy(dtype=float),
            prefix[col].to_numpy(dtype=float),
            rtol=1e-9, atol=1e-9,
            err_msg=f"{col} for past dates changed when future data was appended")


def test_indicator_warmup_uses_only_past_bars():
    """The real bfill test: in the warm-up region MA_50[i] must be the mean of bars
    0..i inclusive. The old `.ffill().bfill()` instead stamped every row before the
    first valid window with a mean computed from bars 35-50 — future data at those
    timestamps."""
    proc = EnhancedRussell3000DataProcessor.__new__(EnhancedRussell3000DataProcessor)
    out = proc._process_indicators(_ohlcv(200, seed=4))
    close = out['Close']

    for i in (0, 1, 5, 17, 34, 49):
        expected = close.iloc[:i + 1].mean()
        assert out['MA_50'].iloc[i] == pytest.approx(expected, rel=1e-9), (
            f"MA_50[{i}] is not the mean of bars 0..{i} — warm-up sees the future")

    assert out['MA_50'].iloc[:5].gt(0).all(), "price-level column filled with 0 in warm-up"
    assert not out.isnull().any().any()


# ── Universe screen: must not use the full-sample minimum ─────────────────────

def test_penny_stock_screen_ignores_a_later_collapse():
    """`close.min() < 2.0` over 2020-2025 retroactively deleted any name that ever fell
    below $2, removing future losers from past pair selection."""
    proc = EnhancedRussell3000DataProcessor.__new__(EnhancedRussell3000DataProcessor)
    df = _ohlcv(400, seed=5)
    df['Close'] = df['Close'].clip(lower=20.0)
    assert proc._validate_data(df) is True

    collapsed = df.copy()
    collapsed.iloc[-50:, collapsed.columns.get_loc('Close')] = 0.5
    assert proc._validate_data(collapsed) is True, (
        "a symbol that starts healthy and collapses LATER must still be selectable "
        "for the earlier period")

    penny = df.copy()
    penny['Close'] = 0.5
    assert proc._validate_data(penny) is False, "genuine penny stocks must still screen out"


# ── Market impact: the cap must not be the entire model ──────────────────────

def test_market_impact_is_not_pinned_to_the_cap():
    """The sqrt model was missing its volatility factor and returned ~424 bps at 2%
    participation against a hardcoded `min(..., 2)`, so impact was a flat 2 bps."""
    m = EnhancedPrimeFundTransactionCostModel()
    price, daily_volume = 100.0, 2_000_000.0

    small = m.calculate_market_impact_cost(2_000, price, daily_volume)
    large = m.calculate_market_impact_cost(200_000, price, daily_volume)

    small_bps = small / (2_000 * price) * 1e4
    large_bps = large / (200_000 * price) * 1e4

    assert small_bps < m.market_impact_cap_bps, "impact pinned at the cap for a small trade"
    assert large_bps > small_bps, "impact must increase with participation"
    assert small_bps > 0


# ── Significance: the reported CI must agree with the reported p-value ────────

def test_oos_window_ci_agrees_with_its_pvalue():
    """A t-test p-value was reported beside a percentile-bootstrap CI; on the v31
    windows they contradicted each other (p=0.085 next to a CI excluding zero)."""
    v = np.array([-0.4634, -0.4484, -0.0931, 0.5675, -0.7372,
                  -0.9953, -0.6481, 0.0, 0.0, 0.0]) / 100
    r = oos_window_test(v)

    assert r['ci_method'] == 't'
    not_significant = r['pvalue'] > 0.05
    ci_spans_zero = r['ci_lo'] < 0.0 < r['ci_hi']
    assert not_significant == ci_spans_zero, (
        f"p={r['pvalue']:.3f} and 95% CI [{r['ci_lo']:.5f}, {r['ci_hi']:.5f}] disagree")


@pytest.mark.parametrize('seed', [0, 1, 2, 3, 4])
def test_oos_window_ci_agrees_on_random_samples(seed):
    rng = np.random.default_rng(seed)
    r = oos_window_test(rng.normal(0, 0.01, 12))
    assert (r['pvalue'] > 0.05) == (r['ci_lo'] < 0.0 < r['ci_hi'])


# ── JSON export must never emit bare NaN / Infinity ──────────────────────────

def test_export_never_writes_bare_nan_or_infinity():
    """`json.dump` writes NaN/Infinity as bare tokens, which is valid JavaScript but
    invalid JSON (RFC 8259). Three shipped exports are unparseable by strict parsers
    because a pair with no losing trades produced `"profit_factor": Infinity`."""
    import io
    import json as _json
    from pairs_trading.json_export import _dump_json

    payload = {
        'profit_factor': float('inf'),
        'neg': float('-inf'),
        'vol': float('nan'),
        'np_nan': np.float64('nan'),
        'np_int': np.int64(7),
        'np_bool': np.bool_(True),
        'arr': np.array([1.0, np.inf, 3.0]),
        'nested': [{'a': float('inf')}, {'b': 2.5}],
        'finite': 1.25,
    }
    buf = io.StringIO()
    _dump_json(payload, buf)
    raw = buf.getvalue()

    assert 'Infinity' not in raw and 'NaN' not in raw

    def _reject(c):
        raise AssertionError(f'bare {c} token in export')

    parsed = _json.loads(raw, parse_constant=_reject)

    assert parsed['profit_factor'] is None
    assert parsed['arr'] == [1.0, None, 3.0]
    assert parsed['np_int'] == 7 and isinstance(parsed['np_int'], int)
    assert parsed['nested'][0]['a'] is None
    assert parsed['finite'] == 1.25, "finite values must pass through untouched"


def test_shipped_exports_are_strict_json():
    """Regression guard for the files the site and downstream consumers read."""
    import glob
    import json as _json
    import os

    def _reject(c):
        raise AssertionError(f'bare {c}')

    fresh = [f for f in glob.glob('outputs/*.json') if 'unbiased' in f or 'fund_type' in f]
    if not fresh:
        pytest.skip('no current exports on disk (run the backtest first)')

    for f in fresh:
        with open(f) as fh:
            _json.loads(fh.read(), parse_constant=_reject), os.path.basename(f)
