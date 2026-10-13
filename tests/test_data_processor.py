"""Tests for pairs_trading.data_processor validation + indicator helpers."""
import numpy as np
import pandas as pd
import pytest

from pairs_trading.data_processor import EnhancedRussell3000DataProcessor

RNG = np.random.default_rng(0)


@pytest.fixture
def dp():
    return EnhancedRussell3000DataProcessor()


def _df(close):
    idx = pd.date_range("2022-01-03", periods=len(close), freq="B")
    return pd.DataFrame({"Close": close}, index=idx)


# ── _validate_data ──────────────────────────────────────────────────────────
def test_validate_accepts_clean_data(dp):
    assert dp._validate_data(_df(np.linspace(50, 80, 200))) is True


def test_validate_rejects_missing_close(dp):
    df = pd.DataFrame({"Open": [10, 11, 12]})
    assert dp._validate_data(df) is False


def test_validate_rejects_nonpositive_prices(dp):
    c = np.linspace(50, 80, 100)
    c[10] = -1.0
    assert dp._validate_data(_df(c)) is False


def test_validate_rejects_penny_stock(dp):
    assert dp._validate_data(_df(np.full(100, 1.0))) is False     # min < $2 floor


# ── _calculate_rsi ──────────────────────────────────────────────────────────
def test_rsi_bounded_0_100(dp):
    prices = pd.Series(100 * np.exp(np.cumsum(RNG.normal(0, 0.01, 300))))
    rsi = dp._calculate_rsi(prices)
    assert rsi.min() >= 0.0 and rsi.max() <= 100.0


def test_rsi_high_for_monotonic_uptrend(dp):
    prices = pd.Series(np.linspace(10, 50, 100))                  # only gains
    rsi = dp._calculate_rsi(prices)
    assert rsi.iloc[-1] > 90.0


def test_rsi_length_matches_input(dp):
    prices = pd.Series(np.linspace(10, 50, 60))
    assert len(dp._calculate_rsi(prices)) == 60


# ── v32: point-in-time reconstruction and gap handling ─────────────────────────

from pairs_trading.data_processor import EnhancedRussell3000DataProcessor as _P  # noqa: E402


def _split_frame(traded, split_at, ratio):
    """Yahoo-style back-adjusted frame for a stock that traded at `traded` and split
    `ratio`:1 on row `split_at` (earlier closes / ratio, earlier volumes x ratio)."""
    idx = pd.bdate_range('2021-01-01', periods=len(traded), tz='America/New_York')
    adj = traded.astype(float).copy()
    adj[:split_at] = traded[:split_at] / ratio
    vol = np.where(np.arange(len(traded)) < split_at, 1e6 * ratio, 1e6)
    df = pd.DataFrame({'Open': adj, 'High': adj * 1.01, 'Low': adj * 0.99, 'Close': adj,
                       'Volume': vol, 'Stock Splits': 0.0}, index=idx)
    df.iloc[split_at, df.columns.get_loc('Stock Splits')] = ratio
    return df


@pytest.mark.parametrize('pre, post, ratio', [(19.0, 1.9, 10.0), (1.5, 15.0, 0.1)])
def test_point_in_time_price_and_volume_undo_later_splits(pre, post, ratio):
    traded = np.r_[np.full(150, pre), np.full(150, post)]
    df = _split_frame(traded, 150, ratio)
    out = _P.__new__(_P)._process_indicators(df)
    np.testing.assert_allclose(out['Close_PIT'].to_numpy(), traded)
    np.testing.assert_allclose(out['Volume_PIT'].to_numpy(), 1e6)
    f = _P.future_split_factor(df)
    assert f.iloc[149] == pytest.approx(ratio) and f.iloc[150] == 1.0


def test_penny_screen_uses_the_traded_price():
    """A $19 stock that later split 10:1 shows ~$1.90 in adjusted history; it must pass
    the $2 screen, which is about the price at the time."""
    proc = _P.__new__(_P)
    rng = np.random.default_rng(0)
    traded = np.r_[19.0 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))), np.full(100, 1.9)]
    assert proc._validate_data(_split_frame(traded, 300, 10.0)) is True


def test_returns_keep_the_true_move_across_a_missing_close():
    idx = pd.bdate_range('2022-01-03', periods=400, tz='America/New_York')
    close = 50 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.01, 400)))
    df = pd.DataFrame({'Open': close, 'High': close, 'Low': close, 'Close': close,
                       'Volume': 1e6}, index=idx)
    df.iloc[100, df.columns.get_loc('Close')] = np.nan
    out = _P.__new__(_P)._process_indicators(df)
    r = out['Returns'].to_numpy()
    assert r[100] == 0.0                                       # no invented move on the gap day
    assert (1 + r[100]) * (1 + r[101]) - 1 == pytest.approx(close[101] / close[99] - 1)
    assert r[99] == pytest.approx(close[99] / close[98] - 1)
    assert np.isnan(out['Close'].iloc[100])                    # raw close stays unfilled
