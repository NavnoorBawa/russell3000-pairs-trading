"""
TRANSFORMER ENCODER FOR PAIRS TRADING - BASELINE BENCHMARKS
===========================================================
Does the cointegration + Kalman pipeline actually beat the textbook?

Two baselines, run on the SAME universe and SAME out-of-sample period as the main
strategy, so the comparison is apples-to-apples:

  1. Gatev et al. (2006) distance method — the canonical academic pairs benchmark.
     Pick the pairs whose normalised price paths are most similar over a formation
     window (smallest sum of squared deviations), then trade ±2σ divergence with
     mean-reversion exit. No cointegration test, no Kalman filter.

  2. Random-pair control — N random pairs from the same universe, identical trading
     rule. If random pairs make money too, the "edge" is just market beta / the
     trading rule, not the pair-selection method.

All look-ahead-free: pairs are chosen and σ is estimated on the formation window
(≤ formation_end); trading happens strictly after it. Returns are net of a flat,
disclosed round-trip cost so they sit on the same footing as the main backtest.

Reference: Gatev, Goetzmann & Rouwenhorst (2006), "Pairs Trading: Performance of a
Relative-Value Arbitrage Rule", Review of Financial Studies.
"""

from pairs_trading.config import pd, np, logging
import itertools
import random

logger = logging.getLogger(__name__)


def _aligned_closes(processed_data, symbols, start=None, end=None):
    """Return a DataFrame of aligned Close prices for the given symbols/date range.

    Symbol indices are normalised to tz-naive calendar dates (midnight) before aligning
    so the same trading day lines up across symbols — otherwise heterogeneous timestamps
    (tz, intraday time) explode the outer-join index and collapse per-symbol coverage.
    """
    cols = {}
    for s in symbols:
        df = processed_data.get(s)
        if df is None or 'Close' not in getattr(df, 'columns', []):
            continue
        sc = df['Close'].copy()
        idx = pd.to_datetime(sc.index)
        try:
            idx = idx.tz_localize(None)            # tz-aware → naive
        except (TypeError, AttributeError):
            pass                                    # already naive
        sc.index = idx.normalize()                  # collapse to calendar day
        sc = sc[~sc.index.duplicated(keep='last')]
        cols[s] = sc
    if not cols:
        return pd.DataFrame()
    px = pd.DataFrame(cols).sort_index()
    if start is not None:
        px = px[px.index >= pd.Timestamp(start)]
    if end is not None:
        px = px[px.index <= pd.Timestamp(end)]
    return px


def _normalize(px):
    """Normalise each column to start at 1.0 over the given window (cumulative index)."""
    first = px.apply(lambda c: c.dropna().iloc[0] if c.dropna().size else np.nan)
    return px.divide(first, axis=1)


def select_distance_pairs(px_formation, n_pairs=20, max_symbols=200, min_spread_std=0.005):
    """Pick the n_pairs with the smallest sum-of-squared-deviation between normalised
    price paths over the formation window (the Gatev distance criterion).

    Pairs whose normalised-spread std is below ``min_spread_std`` are skipped — the very
    smallest-SSD pairs are typically near-duplicate listings (dual-class shares, ETF vs
    constituent) with ~zero divergence, which would never produce a real trade.
    """
    cols = [c for c in px_formation.columns if px_formation[c].notna().mean() > 0.9]
    cols = cols[:max_symbols]                      # cap the O(n^2) distance scan
    norm = _normalize(px_formation[cols]).ffill().bfill()
    pairs = []
    for a, b in itertools.combinations(cols, 2):
        d = norm[a].values - norm[b].values
        ssd = float(np.nansum(d * d))
        sd = float(np.nanstd(d))
        if sd < min_spread_std:                    # skip degenerate near-duplicate pairs
            continue
        pairs.append(((a, b), ssd))
    pairs.sort(key=lambda x: x[1])
    return [p for p, _ in pairs[:n_pairs]]


def _trade_pair_distance(norm_form, norm_trade, sym_a, sym_b, ret_a, ret_b,
                         entry_z=2.0, cost_roundtrip=0.0010):
    """Trade one pair with the Gatev rule on the trading window.

    Returns a daily net-return series (0 when flat). Long the underperformer / short
    the outperformer when the normalised spread diverges > entry_z formation-σ; exit
    when the spread reverts through its formation mean (or at window end).
    """
    spread_form = (norm_form[sym_a] - norm_form[sym_b]).dropna()
    if len(spread_form) < 30:
        return None
    mu, sd = float(spread_form.mean()), float(spread_form.std())
    if sd <= 0:
        return None

    idx = norm_trade.index
    spread = (norm_trade[sym_a] - norm_trade[sym_b]).reindex(idx)
    daily = np.zeros(len(idx))
    pos = 0           # +1: long a / short b ; -1: short a / long b
    for t in range(len(idx)):
        s = spread.iloc[t]
        if np.isnan(s):
            continue
        # accrue today's P&L from yesterday's position
        if pos != 0 and t > 0:
            ra = ret_a.get(idx[t], 0.0)
            rb = ret_b.get(idx[t], 0.0)
            daily[t] = pos * (ra - rb)
        # update position AFTER booking today's return (decision on close)
        if pos == 0:
            if s > mu + entry_z * sd:
                pos = -1                                       # short a / long b
                daily[t] -= cost_roundtrip / 2.0
            elif s < mu - entry_z * sd:
                pos = +1                                       # long a / short b
                daily[t] -= cost_roundtrip / 2.0
        else:
            reverted = (pos == +1 and s >= mu) or (pos == -1 and s <= mu)
            if reverted:
                daily[t] -= cost_roundtrip / 2.0
                pos = 0
    if pos != 0:
        daily[-1] -= cost_roundtrip / 2.0                       # close at window end
    return pd.Series(daily, index=idx)


def _portfolio_stats(pair_series_list, periods=252):
    """Equal-weight the per-pair daily series into a portfolio and compute stats."""
    series = [s for s in pair_series_list if s is not None]
    if not series:
        return {'total_return_pct': 0.0, 'sharpe_ratio': 0.0, 'n_days': 0, 'n_pairs': 0,
                'daily_returns': []}
    df = pd.concat(series, axis=1).fillna(0.0)
    port = df.mean(axis=1).values                       # equal-weight across pairs
    sd = port.std(ddof=1)
    sharpe = float(port.mean() / sd * np.sqrt(periods)) if sd > 0 else 0.0
    total = float(np.prod(1.0 + port) - 1.0)
    return {
        'total_return_pct': round(total * 100, 4),
        'sharpe_ratio': round(sharpe, 3),
        'n_days': int(len(port)),
        'n_pairs': int(df.shape[1]),
        'daily_returns': port.tolist(),
    }


def run_benchmarks(processed_data, universe_symbols,
                   formation_end='2023-06-30', trade_start='2023-07-01',
                   trade_end=None, n_pairs=20, entry_z=2.0,
                   cost_roundtrip=0.0010, seed=42, max_symbols=200):
    """Run the distance-method and random-pair baselines; return a comparison dict."""
    logger.info("=" * 70)
    logger.info("BASELINE BENCHMARKS — distance method (Gatev 2006) + random control")
    logger.info("=" * 70)

    f_end = pd.Timestamp(formation_end)
    t_start = pd.Timestamp(trade_start)
    px_all = _aligned_closes(processed_data, universe_symbols)
    if px_all.empty:
        logger.warning("Benchmark: no usable price data.")
        return {}

    # tz-align the cutoffs to the data index
    if getattr(px_all.index, 'tz', None) is not None:
        f_end = f_end.tz_localize(px_all.index.tz) if f_end.tzinfo is None else f_end
        t_start = t_start.tz_localize(px_all.index.tz) if t_start.tzinfo is None else t_start
        if trade_end is not None:
            trade_end = pd.Timestamp(trade_end)
            trade_end = trade_end.tz_localize(px_all.index.tz) if trade_end.tzinfo is None else trade_end

    px_form  = px_all[px_all.index <= f_end]
    px_trade = px_all[px_all.index >= t_start]
    if trade_end is not None:
        px_trade = px_trade[px_trade.index <= trade_end]
    if len(px_form) < 60 or len(px_trade) < 20:
        logger.warning("Benchmark: insufficient formation/trade history.")
        return {}

    norm_form  = _normalize(px_form).ffill().bfill()
    norm_trade = px_trade.divide(
        px_form.apply(lambda c: c.dropna().iloc[0] if c.dropna().size else np.nan), axis=1
    )                                                   # same base as formation
    rets = {s: px_trade[s].pct_change().fillna(0.0) for s in px_trade.columns}

    def _run(pairs, label):
        series = []
        for a, b in pairs:
            if a in norm_trade.columns and b in norm_trade.columns:
                series.append(_trade_pair_distance(
                    norm_form, norm_trade, a, b, rets[a], rets[b],
                    entry_z=entry_z, cost_roundtrip=cost_roundtrip))
        st = _portfolio_stats(series)
        logger.info(f"  {label:<26} return {st['total_return_pct']:+7.3f}% | "
                    f"Sharpe {st['sharpe_ratio']:+.2f} | {st['n_pairs']} pairs")
        return st

    # 1) Gatev distance pairs
    dist_pairs = select_distance_pairs(px_form, n_pairs=n_pairs, max_symbols=max_symbols)
    distance = _run(dist_pairs, "Distance method (Gatev)")

    # 2) Random control (averaged over a few draws to reduce luck)
    rng = random.Random(seed)
    cand = [c for c in norm_trade.columns if c in norm_form.columns]
    rand_stats = []
    for k in range(5):
        if len(cand) < 2 * n_pairs:
            break
        picks = rng.sample(cand, 2 * n_pairs)
        rpairs = list(zip(picks[0::2], picks[1::2]))
        rand_stats.append(_run(rpairs, f"Random control (draw {k+1})"))
    if rand_stats:
        random_avg = {
            'total_return_pct': round(float(np.mean([r['total_return_pct'] for r in rand_stats])), 4),
            'sharpe_ratio': round(float(np.mean([r['sharpe_ratio'] for r in rand_stats])), 3),
            'n_draws': len(rand_stats),
            'return_pct_range': [round(min(r['total_return_pct'] for r in rand_stats), 4),
                                 round(max(r['total_return_pct'] for r in rand_stats), 4)],
        }
    else:
        random_avg = {}

    out = {
        'config': {
            'formation_end': str(formation_end), 'trade_start': str(trade_start),
            'n_pairs': n_pairs, 'entry_z': entry_z,
            'cost_roundtrip_bps': cost_roundtrip * 1e4, 'universe_size': len(universe_symbols),
        },
        'distance_method': distance,
        'random_control': random_avg,
    }
    logger.info("=" * 70)
    return out


def log_benchmark_vs_strategy(benchmarks, strategy_return_pct, strategy_sharpe):
    """Log the strategy's numbers next to the baselines for the headline comparison."""
    if not benchmarks:
        return
    d = benchmarks.get('distance_method', {})
    r = benchmarks.get('random_control', {})
    logger.info("\n" + "=" * 70)
    logger.info(f"{'STRATEGY vs BASELINES (same universe, same OOS period)':^70}")
    logger.info("=" * 70)
    logger.info(f"  {'Cointegration + Kalman (this project)':<40} "
                f"ret {strategy_return_pct:+7.3f}% | Sharpe {strategy_sharpe:+.2f}")
    logger.info(f"  {'Distance method (Gatev 2006)':<40} "
                f"ret {d.get('total_return_pct', 0):+7.3f}% | Sharpe {d.get('sharpe_ratio', 0):+.2f}")
    if r:
        logger.info(f"  {'Random-pair control (avg of draws)':<40} "
                    f"ret {r.get('total_return_pct', 0):+7.3f}% | Sharpe {r.get('sharpe_ratio', 0):+.2f}")
    logger.info("=" * 70)
