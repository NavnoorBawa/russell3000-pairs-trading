"""Deterministic synthetic market with known answers (no data files, no network).

Used by the test suite and by scripts/synthetic_validation.py. Not used by the study.

`make_market` builds OHLCV frames shaped exactly like the yfinance cache the pipeline
reads (tz-aware America/New_York daily bars) plus a macro dict (tz-naive VIX + sector
ETFs). Pairs SAxx/SBxx are cointegrated by construction: log A = c + beta * log B + s,
with s an Ornstein-Uhlenbeck spread of known half-life, so the true hedge ratio and the
existence of an edge are known in advance. With cointegrated=False the spread s is a
driftless-increment random walk instead: the legs stay correlated but are NOT cointegrated.
SNxx names are unrelated random walks.

`make_residual_market` builds the known-answer market of the sector-ETF residual strategy
(pairs_trading/residual_statarb.py): stocks = beta x sector ETF + a planted OU or
random-walk residual.

`write_calendar_caches` and `write_reference` put a synthetic market on disk in the files
a study run reads (a calendar's price cache with its fetch manifest and its macro cache;
the point-in-time membership snapshots and the industry map of reference/), so the
pipeline, the residual arm's script and the holdout evaluator run end to end offline.
"""
import json
import pathlib
import pickle

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
                start='2020-01-01', end='2025-12-31', drift=0.0003):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, end, tz='America/New_York')
    T = len(idx)
    mkt = rng.normal(drift, 0.010, T)
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


def make_residual_market(n_sectors=3, stocks_per_sector=12, seed=0, residual='ou',
                         half_life=(5.0, 10.0), residual_vol=0.015, etf_vol=0.010,
                         start='2021-01-01', end='2023-12-31'):
    """Known-answer market for the sector-ETF residual strategy (residual_statarb.py).

    Each sector ETF's daily simple return is N(0, etf_vol), so its price is a martingale.
    Stock i of a sector has the daily simple return  beta_i x (ETF return) + (X_t - X_{t-1}),
    the A&L model (eq. 11) with zero drift. With residual='ou', X is an AR(1) with a
    half-life drawn uniformly from `half_life` days and innovation sd `residual_vol`: the
    residual mean-reverts, so a correct strategy has a large positive gross edge. With
    residual='random_walk', X has i.i.d. N(0, residual_vol) increments: every stock and
    ETF price is a martingale, so no rule that trades on past data can have a non-zero
    expected P&L, and a significantly positive mean is look-ahead.

    Returns (frames, sector_closes, sector_map, true_beta): frames shaped like the price
    cache (tz-aware America/New_York OHLCV), tz-naive ETF closes, {symbol: ETF} and
    {symbol: beta}. Sectors are the first n_sectors of SECTOR_ETFS; symbols are
    R<sector><stock>, e.g. R0007.
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, end, tz='America/New_York')
    T = len(idx)
    frames, sector_closes, sector_map, true_beta = {}, {}, {}, {}
    for g, etf in enumerate(SECTOR_ETFS[:n_sectors]):
        r_etf = rng.normal(0.0, etf_vol, T)
        r_etf[0] = 0.0
        sector_closes[etf] = pd.Series(50.0 * np.cumprod(1.0 + r_etf), index=idx.tz_localize(None))
        for n in range(stocks_per_sector):
            beta = rng.uniform(0.6, 1.4)
            eps = rng.normal(0.0, residual_vol, T)
            if residual == 'ou':
                phi = np.exp(-np.log(2) / rng.uniform(*half_life))
                x = np.zeros(T)
                for t in range(1, T):
                    x[t] = phi * x[t - 1] + eps[t]
            elif residual == 'random_walk':
                eps[0] = 0.0
                x = np.cumsum(eps)
            else:
                raise ValueError(f"residual must be 'ou' or 'random_walk', not {residual!r}")
            r = beta * r_etf + np.diff(x, prepend=x[0])
            sym = f'R{g}{n:03d}'
            frames[sym] = _ohlcv(np.log(rng.uniform(20, 150) * np.cumprod(1.0 + r)), rng, idx)
            sector_map[sym] = etf
            true_beta[sym] = beta
    return frames, sector_closes, sector_map, true_beta


def perturb_after(frames, cutoff, seed=123, scale=0.03):
    """Copy of `frames` whose prices AND volumes strictly after `cutoff` follow a different path.

    Everything dated <= cutoff is untouched, so any computation that is causal must give
    identical results for all dates <= cutoff on the original and the perturbed market.
    Pair with perturb_macro_after so the VIX / sector inputs change too.
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
            if 'Volume' in df.columns:
                df.loc[after, 'Volume'] = (df.loc[after, 'Volume'].to_numpy()
                                           * np.exp(rng.normal(0, 0.5, n))).round()
        out[sym] = df
    return out


def perturb_macro_after(macro, cutoff, seed=124, scale=0.03):
    """Copy of the macro dict (tz-naive VIX + sector ETFs) with a different path after `cutoff`:
    VIX jumps across the 20 / 30 / 40 regime bands and every sector takes its own random walk."""
    rng = np.random.default_rng(seed)
    cut = pd.Timestamp(cutoff)
    vix = macro['VIX'].copy()
    after = vix.index > cut
    vix[after] = np.clip(vix[after].to_numpy() + rng.normal(0, 12, int(after.sum())), 9, 80)
    sectors = {}
    for k, v in macro['sectors'].items():
        v = v.copy()
        a = v.index > cut
        v[a] = v[a].to_numpy() * np.exp(np.cumsum(rng.normal(0, scale, int(a.sum()))))
        sectors[k] = v
    return {**macro, 'VIX': vix, 'sectors': sectors}


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


def write_calendar_caches(root, calendar, frames, macro):
    """Write `frames` as `calendar`'s price cache under `root`, with a fetch manifest that
    records every symbol as fetched over the calendar's period, and `macro` as its macro
    cache: the files python -m pairs_trading.main --fetch-only leaves for a calendar."""
    root = pathlib.Path(root)
    price, macro_path = root / calendar.price_cache, root / calendar.macro_cache
    price.parent.mkdir(parents=True, exist_ok=True)
    macro_path.parent.mkdir(parents=True, exist_ok=True)
    with open(price, 'wb') as f:
        pickle.dump(dict(sorted(frames.items())), f)
    manifest = {'start': calendar.data_start, 'end': calendar.data_end, 'fetched_at': 'synthetic',
                'yfinance_version': 'synthetic', 'cached_symbols': sorted(frames),
                'outcomes': {s: 'ok' for s in sorted(frames)}}
    (root / calendar.price_cache.replace('.pkl', '_manifest.json')).write_text(json.dumps(manifest))
    with open(macro_path, 'wb') as f:
        pickle.dump(macro, f)
    return price, macro_path


def write_reference(root, snapshots, sector_etf=None, industry=None):
    """A reference directory in the committed format (pairs_trading/universe.py).

    snapshots  : {period_date: [tickers]}, written as IWV holdings with equal weights
                 (universe/index.json and universe/iwv_<period_date>.csv; filed 56 days
                 after the period date).
    sector_etf : {ticker: SPDR}; industry: {ticker: Fama-French 49 short name}; together
                 industry_ff49.csv (a ticker in either map gets a row).
    """
    root = pathlib.Path(root)
    (root / 'universe').mkdir(parents=True, exist_ok=True)
    entries = []
    for n, (period, tickers) in enumerate(sorted(snapshots.items())):
        tickers = sorted(tickers)
        rows = ['ticker,cusip,isin,name,weight'] + [
            f'{t},{n:03d}{i:05d}0,US{n:03d}{i:05d}00,{t} Inc,{1.0 / len(tickers)!r}' for i, t in enumerate(tickers)]
        (root / 'universe' / f'iwv_{period}.csv').write_text('\n'.join(rows) + '\n')
        filed = str((pd.Timestamp(period) + pd.Timedelta(days=56)).date())
        entries.append({'period_date': period, 'filing_date': filed, 'accession': f'0000000000-00-{n:06d}',
                        'file': f'iwv_{period}.csv', 'n_holdings': len(tickers), 'n_equity': len(tickers),
                        'n_mapped': len(tickers), 'mapped_value_share': 1.0})
    (root / 'universe' / 'index.json').write_text(json.dumps(
        {'fund': 'synthetic', 'sealed_from': '2026-01-01', 'sealed': [], 'snapshots': entries}, indent=1))
    sector_etf, industry = sector_etf or {}, industry or {}
    rows = ['ticker,cik,sic,ff49,ff49_name,sector_etf,entity_type'] + [
        f'{t},{i + 1},6022,45,{industry.get(t, "")},{sector_etf.get(t, "")},operating'
        for i, t in enumerate(sorted(set(sector_etf) | set(industry)))]
    (root / 'industry_ff49.csv').write_text('\n'.join(rows) + '\n')
    return root
