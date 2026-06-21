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
