"""Deterministic synthetic market for hermetic engine tests (no data files, no network).

`make_market` builds OHLCV frames shaped exactly like the yfinance cache the pipeline
reads (tz-aware America/New_York daily bars) plus a macro dict (tz-naive VIX + sector
ETFs). Pairs SAxx/SBxx are cointegrated by construction: log A = c + beta * log B + s,
with s an Ornstein-Uhlenbeck spread of known half-life, so the true hedge ratio and the
existence of an edge are known in advance. SNxx names are unrelated random walks.
"""
import numpy as np
import pandas as pd

from pairs_trading.data_processor import EnhancedRussell3000DataProcessor
from pairs_trading.trading_system import CompleteFixedRussell3000TradingSystem

SECTOR_ETFS = ['XLK', 'XLC', 'XLF', 'XLV', 'XLY', 'XLP', 'XLE', 'XLI', 'XLB', 'XLU', 'XLRE']


def _ohlcv(logp, rng, idx):
    close = np.exp(logp)
    r = np.diff(logp, prepend=logp[0])
    prev_close = np.concatenate([[close[0]], close[:-1]])
    open_ = prev_close * np.exp(0.3 * r + rng.normal(0, 0.002, len(r)))
    high = np.maximum(open_, close) * np.exp(np.abs(rng.normal(0, 0.004, len(r))))
    low = np.minimum(open_, close) * np.exp(-np.abs(rng.normal(0, 0.004, len(r))))
    volume = rng.lognormal(np.log(6e6), 0.3, len(r)).round()
    return pd.DataFrame({'Open': open_, 'High': high, 'Low': low, 'Close': close,
                         'Volume': volume}, index=idx)


def make_market(n_pairs=6, n_noise=4, seed=0, cointegrated=True, betas=None,
                start='2020-01-01', end='2025-12-31'):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, end, tz='America/New_York')
    T = len(idx)
    mkt = rng.normal(0.0003, 0.010, T)
    frames, true_beta = {}, {}
    for k in range(n_pairs):
        lb = np.log(rng.uniform(20, 150)) + np.cumsum(mkt + rng.normal(0, 0.014, T))
        beta = betas[k] if betas is not None else rng.uniform(0.7, 1.3)
        if cointegrated:
            phi = np.exp(-np.log(2) / rng.uniform(5, 14))
            eps = rng.normal(0, 0.012, T)
            s = np.zeros(T)
            for t in range(1, T):
                s[t] = phi * s[t - 1] + eps[t]
        else:
            s = np.cumsum(rng.normal(0, 0.012, T))
        la = np.log(rng.uniform(20, 150)) + beta * (lb - lb[0]) + s
        frames[f'SA{k:02d}'] = _ohlcv(la, rng, idx)
        frames[f'SB{k:02d}'] = _ohlcv(lb, rng, idx)
        true_beta[(f'SA{k:02d}', f'SB{k:02d}')] = beta
    for k in range(n_noise):
        lp = np.log(rng.uniform(20, 150)) + np.cumsum(mkt + rng.normal(0, 0.016, T))
        frames[f'SN{k:02d}'] = _ohlcv(lp, rng, idx)
    naive = idx.tz_localize(None)
    vix = pd.Series(24.0 + np.clip(rng.normal(0, 1.0, T), -3, 3), index=naive)
    sectors = {e: pd.Series(50 * np.exp(np.cumsum(mkt + rng.normal(0, 0.0005, T))), index=naive)
               for e in SECTOR_ETFS}
    return frames, {'VIX': vix, 'sectors': sectors}, true_beta


def perturb_after(frames, cutoff, seed=123, scale=0.03):
    """Copy of `frames` whose prices strictly after `cutoff` follow a different path.

    Everything dated <= cutoff is untouched, so any computation that is causal must give
    identical results for all dates <= cutoff on the original and the perturbed market.
    """
    rng = np.random.default_rng(seed)
    out = {}
    for sym, df in frames.items():
        df = df.copy()
        after = df.index > pd.Timestamp(cutoff, tz=df.index.tz)
        n = int(after.sum())
        if n:
            shock = np.exp(np.cumsum(rng.normal(0, scale, n)))
            for col in ('Open', 'High', 'Low', 'Close'):
                df.loc[after, col] = df.loc[after, col].to_numpy() * shock
        out[sym] = df
    return out


def build_system(frames, macro, pairs=None, half_life=8.0, quality=0.8, capital=100_000_000):
    """A ready-to-backtest system over `frames` without touching disk or the network."""
    proc = EnhancedRussell3000DataProcessor.__new__(EnhancedRussell3000DataProcessor)
    system = CompleteFixedRussell3000TradingSystem(initial_capital=capital)
    system.processed_data = {s: proc._process_indicators(df) for s, df in frames.items()}
    system.macro_data = macro
    if pairs is None:
        pairs = sorted((a, 'SB' + a[2:]) for a in frames if a.startswith('SA'))
    system.pair_selector.pair_statistics = {
        f'{a}-{b}': {'half_life': half_life, 'quality_score': quality, 'correlation': 0.6,
                     'cointegration_pvalue': 0.01} for a, b in pairs}
    system.selected_pairs = list(pairs)
    system.spread_data = {p: system._pair_spread(*p) for p in pairs}
    return system
