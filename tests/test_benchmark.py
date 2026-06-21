"""Tests for pairs_trading.benchmark — Gatev distance + random-pair baselines.

Hermetic: builds a tiny synthetic price universe in-memory.
"""
import numpy as np
import pandas as pd
import pytest

from pairs_trading.benchmark import (
    _aligned_closes, _normalize, select_distance_pairs,
    _portfolio_stats, run_benchmarks,
)

RNG = np.random.default_rng(0)


def _synth_universe(n_syms=12, n_days=400, tz="America/New_York"):
    """Build {sym: DataFrame[Close]} on a shared calendar with tz-aware odd timestamps."""
    idx = pd.date_range("2022-01-03", periods=n_days, freq="B", tz=tz)
    # mangle the time-of-day so alignment must normalise to dates
    idx = idx + pd.Timedelta(hours=9, minutes=30)
    data = {}
    for i in range(n_syms):
        steps = RNG.normal(0.0005, 0.02, n_days).cumsum()
        close = 50.0 * np.exp(steps)
        df = pd.DataFrame({"Close": close}, index=idx)
        data[f"S{i}"] = df
    return data


def test_aligned_closes_normalises_dates():
    data = _synth_universe()
    px = _aligned_closes(data, list(data.keys()))
    assert not px.empty
    # index should be tz-naive midnight calendar dates, one row per business day
    assert px.index.tz is None
    assert (px.index == px.index.normalize()).all()
    # every symbol should have near-full coverage (alignment worked)
    assert (px.notna().mean() > 0.9).all()


def test_normalize_starts_at_one():
    data = _synth_universe()
    px = _aligned_closes(data, list(data.keys()))
    norm = _normalize(px)
    first = norm.apply(lambda c: c.dropna().iloc[0])
    assert np.allclose(first.values, 1.0)


def test_select_distance_pairs_excludes_degenerates():
    data = _synth_universe(n_syms=8)
    # make S1 an exact duplicate of S0 -> zero-variance spread, must be excluded
    data["S1"] = data["S0"].copy()
    px = _aligned_closes(data, list(data.keys()))
    pairs = select_distance_pairs(px, n_pairs=10, min_spread_std=0.005)
    assert ("S0", "S1") not in pairs and ("S1", "S0") not in pairs
    assert len(pairs) > 0


def test_portfolio_stats_sign_and_keys():
    idx = pd.date_range("2023-01-02", periods=100, freq="B")
    up = pd.Series(np.full(100, 0.001), index=idx)
    st = _portfolio_stats([up, up])
    assert st['total_return_pct'] > 0
    assert st['n_pairs'] == 2
    assert set(['total_return_pct', 'sharpe_ratio', 'daily_returns']).issubset(st)


def test_run_benchmarks_smoke():
    data = _synth_universe(n_syms=12, n_days=400)
    out = run_benchmarks(
        data, list(data.keys()),
        formation_end="2022-12-30", trade_start="2023-01-02",
        n_pairs=4, max_symbols=12,
    )
    assert 'distance_method' in out
    assert 'random_control' in out
    assert 'config' in out
    assert out['distance_method']['n_pairs'] >= 1
