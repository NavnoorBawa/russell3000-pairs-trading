"""
TRANSFORMER ENCODER FOR PAIRS TRADING - BASELINE BENCHMARKS
===========================================================
Does the cointegration + Kalman pipeline actually beat the textbook?

Two baselines, run on the SAME universe, the SAME out-of-sample period, the SAME
execution convention and the SAME cost model as the main strategy:

  1. Gatev, Goetzmann & Rouwenhorst (2006) distance method — the canonical academic
     pairs benchmark. Every 6 months, pick the 20 pairs whose normalised price paths
     were closest over the prior 12 months (smallest sum of squared deviations), then
     trade them for 6 months: open when the normalised prices diverge by more than two
     formation standard deviations, close at the next crossing.

  2. Random-pair control — the identical rule, costs and fills applied to pairs drawn
     at random (20 distinct pairs, uniformly from the same eligible set the distance
     method ranks: the coverage-screened universe minus near-duplicate listings),
     re-drawn every block, 200 portfolios, seeded and deterministic. It
     answers "is the pair SELECTION worth anything, or would any pairs do?" with a
     distribution rather than a point: a strategy Sharpe is reported as a percentile of
     the random-pair Sharpe distribution.

Execution and accounting (v32 — mirrors the engine in trading_system.py):
  * One-day wait. A signal computed on the close of day t is filled at the close of
    day t+1 (the next bar's OPEN when PAIRS_FILL=open), exactly like the pipeline. GGR
    (2006) make the one-day-wait rule their headline because same-bar fills capture
    bid-ask bounce: a close that prints at the bid looks "cheap" only because it is at
    the bid, and filling at that very print books the bounce as profit. The same-bar
    variant is kept only as a labelled sensitivity (execution_lag=0).
  * Costs. Every leg execution is priced with the pipeline's own cost model
    (EnhancedPrimeFundTransactionCostModel.calculate_leg_cost) at a stated per-leg
    notional — $2,000,000 by default, i.e. a pair of $4M gross, ~4% of a $100M book —
    using the stock's own 20-day average share volume and 20-day volatility as of the
    execution date; plus stock borrow on the short leg and financing on gross over the
    holding period. A flat round-trip charge (`cost_roundtrip`) is available only as an
    explicit override.
  * Returns on committed capital. A pair commits one per-leg notional N ($N long and $N
    short); its daily return is its dollar P&L / N, costs included, and the portfolio
    return is the equal-weighted mean over the nominated pairs whether or not they are
    trading — GGR's "return on committed capital". Legs are buy-and-hold from the fill
    (fixed share counts, so each leg's weight drifts with its price), and every day is
    marked to market from real closes.

Look-ahead: pairs, formation standard deviations and the universe screen of each block
use only the 12 months before the block starts; the normalisation base is the block's
first close; every trading decision uses closes <= the decision day.

Reference: Gatev, Goetzmann & Rouwenhorst (2006), "Pairs Trading: Performance of a
Relative-Value Arbitrage Rule", Review of Financial Studies 19(3).
"""

import inspect
import os

from pairs_trading.config import pd, np, logging
from pairs_trading.significance import align_return_series, annualized_sharpe, sharpe_difference_test
from pairs_trading.transaction_costs import EnhancedPrimeFundTransactionCostModel

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252
FORMATION_DAYS = 252            # ~12 months (GGR 2006)
TRADING_DAYS = 126              # ~6 months
MIN_FORMATION_DAYS = 60         # a block with less formation history is skipped
DEFAULT_LEG_NOTIONAL = 2_000_000.0   # per leg: $4M gross per pair, ~4% of a $100M book
DEFAULT_RANDOM_DRAWS = 200
_FIELDS = ('Close', 'Open', 'Volume_MA', 'Volatility_20', 'Close_PIT')
_SHARPE_PCTS = (5, 25, 50, 75, 95)


def fill_column_from_env(value=None) -> str:
    """OHLCV column a t+1 fill reads: 'Open' only for PAIRS_FILL=open, else 'Close'.

    Mirrors trading_system.resolve_fill_column (kept local to avoid importing the engine
    here — trading_system imports this module; tests assert the two rules agree).
    """
    if value is None:
        value = os.environ.get('PAIRS_FILL', 'close')
    return 'Open' if str(value).lower() == 'open' else 'Close'


# ──────────────────────────────────────────────────────────────────────────────
# Data alignment
# ──────────────────────────────────────────────────────────────────────────────

def _calendar_days(index) -> pd.DatetimeIndex:
    """Timestamps -> tz-naive midnight calendar dates (local wall-clock date kept)."""
    idx = pd.DatetimeIndex(pd.to_datetime(index))
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return idx.normalize()


def _aligned_panel(processed_data, symbols, fields=_FIELDS) -> dict:
    """{field: DataFrame(calendar dates x symbols)} on the union calendar of the closes.

    Symbol indices are normalised to tz-naive calendar dates before aligning so the
    same trading day lines up across symbols — otherwise heterogeneous timestamps (tz,
    intraday time) explode the outer-join index and collapse per-symbol coverage.
    A non-positive close is treated as no bar (the engine's rule).
    """
    per_field = {f: {} for f in fields}
    for s in symbols:
        df = processed_data.get(s)
        if df is None or 'Close' not in getattr(df, 'columns', []):
            continue
        cols = [f for f in fields if f in df.columns]
        sub = df[cols].copy()
        sub.index = _calendar_days(sub.index)
        sub = sub[~sub.index.duplicated(keep='last')]
        for f in cols:
            per_field[f][s] = sub[f].astype(float)
    if not per_field['Close']:
        return {}
    close = pd.DataFrame(per_field['Close']).sort_index()
    close = close.where(close > 0)
    out = {'Close': close}
    for f in fields:
        if f == 'Close':
            continue
        frame = pd.DataFrame(per_field[f]) if per_field[f] else pd.DataFrame(index=close.index)
        out[f] = frame.reindex(index=close.index, columns=close.columns)
    return out


def _aligned_closes(processed_data, symbols, start=None, end=None):
    """Aligned Close prices (calendar dates x symbols) for the given symbols/date range."""
    panel = _aligned_panel(processed_data, symbols, fields=('Close',))
    if not panel:
        return pd.DataFrame()
    px = panel['Close']
    if start is not None:
        px = px[px.index >= pd.Timestamp(start)]
    if end is not None:
        px = px[px.index <= pd.Timestamp(end)]
    return px


def _normalize(px):
    """Normalise each column to 1.0 at its first valid price in the window."""
    return px.divide(px.bfill().iloc[0], axis=1)


# ──────────────────────────────────────────────────────────────────────────────
# Universe and pair selection
# ──────────────────────────────────────────────────────────────────────────────

def _screen_universe(px_formation, min_coverage: float = 0.9) -> list:
    """Symbols with a real close on more than `min_coverage` of the formation days."""
    if px_formation.empty:
        return []
    cov = px_formation.notna().mean()
    return [c for c in px_formation.columns if cov[c] > min_coverage]


def _sample_symbols(cols, max_symbols, seed) -> list:
    """Seeded random subset of `cols` (in original order) — replaces a first-N cut."""
    if max_symbols is None or len(cols) <= max_symbols:
        return list(cols)
    rng = np.random.default_rng(seed)
    keep = np.sort(rng.choice(len(cols), size=int(max_symbols), replace=False))
    return [cols[i] for i in keep]


def _candidate_pairs(norm: np.ndarray, min_spread_std: float):
    """All pairs (i < j) of the columns of `norm` with their SSD and spread std.

    Vectorised: SSD_ij = |x_i|^2 + |x_j|^2 - 2 x_i.x_j and var(x_i - x_j) from the same
    Gram matrix, so the whole screened universe (~400 names, ~80k pairs) costs one
    matrix product instead of an O(n^2) Python loop — which is why the v31 cap of the
    first `max_symbols` names (alphabetical, in practice) is no longer needed.
    Pairs whose spread std (ddof=1) is below `min_spread_std` are dropped: the very
    smallest-SSD pairs are near-duplicate listings (dual-class shares, ETF vs
    constituent) with ~zero divergence, which never produce a real trade.
    """
    T, n = norm.shape
    if n < 2 or T < 3:
        empty = np.zeros(0, dtype=int)
        return empty, empty, np.zeros(0), np.zeros(0)
    sq = np.einsum('ti,ti->i', norm, norm)
    gram = norm.T @ norm
    ssd = np.maximum(sq[:, None] + sq[None, :] - 2.0 * gram, 0.0)
    mean = norm.mean(axis=0)
    var = np.maximum((ssd - T * (mean[:, None] - mean[None, :]) ** 2) / (T - 1), 0.0)
    ia, ib = np.triu_indices(n, k=1)
    ssd_v, sd_v = ssd[ia, ib], np.sqrt(var[ia, ib])
    keep = np.isfinite(ssd_v) & np.isfinite(sd_v) & (sd_v >= min_spread_std)
    return ia[keep], ib[keep], ssd_v[keep], sd_v[keep]


def select_distance_pairs(px_formation, n_pairs=20, max_symbols=None, min_spread_std=0.005,
                          min_coverage=0.9, seed=42):
    """The Gatev distance criterion: the n_pairs smallest-SSD pairs of normalised prices.

    The universe is the symbols with > `min_coverage` close coverage in the formation
    window (v32: previously the first `max_symbols` columns in dict order were kept —
    roughly alphabetical — and the random control had no screen at all). `max_symbols`
    now only caps the universe by a SEEDED RANDOM sample; the default (None) keeps
    every screened name since the SSD scan is vectorised.
    """
    cols = _sample_symbols(_screen_universe(px_formation, min_coverage), max_symbols, seed)
    if len(cols) < 2:
        return []
    norm = _normalize(px_formation[cols]).ffill().bfill().to_numpy(dtype=float)
    ia, ib, ssd, _ = _candidate_pairs(norm, min_spread_std)
    order = np.lexsort((ib, ia, ssd))[:n_pairs]
    return [(cols[ia[k]], cols[ib[k]]) for k in order]


# ──────────────────────────────────────────────────────────────────────────────
# Trading rule (vectorised across pairs)
# ──────────────────────────────────────────────────────────────────────────────

def _simulate_pairs(close_ff, has_bar, fill_px, ia, ib, threshold, execution_lag=1):
    """Run the GGR rule on P pairs over one trading block, all pairs at once.

    close_ff  : (T, n) last real close at or before each day (carried over bar gaps)
    has_bar   : (T, n) a real close exists that day
    fill_px   : (T, n) t+1 fill price (close, or open for PAIRS_FILL=open); NaN = no bar
    ia, ib    : (P,) column indices of the two legs; threshold : (P,) entry distance
    execution_lag : 1 = decide on close t, fill at t+1 (headline); 0 = fill at the
                    signal close itself (same-bar sensitivity; always at the close).

    Rule. Prices are re-normalised to 1.0 at the block's first close (GGR), d = pA - pB.
    A flat pair with |d| > threshold (both legs trading that day) goes long the cheap leg
    and short the rich one; an open pair is closed at the next CROSSING (d changes sign
    relative to entry, or touches zero), when either leg has no bar on the decision day
    (it has stopped trading — detected causally, as of that close), or at the block's
    last close (a scheduled exit, so it needs no lag). An entry whose fill would land on
    the block's last bar is not taken: it could only be opened and closed at once.
    An entry whose fill day lacks a real bar on either leg is cancelled; an exit leg
    without a bar on the fill day is valued at its last real close (engine rules).

    Accounting per $1 of per-leg notional: $1 long / $1 short at the fill, fixed shares
    after that (buy-and-hold legs), P&L marked to the close every day; the path
    telescopes to the round-trip P&L exactly. Returns (gross (T, P), trades dict).
    """
    T = close_ff.shape[0]
    P = len(ia)
    gross = np.zeros((T, P))
    trades = {k: [] for k in ('pair', 'dir', 'entry_k', 'exit_k', 'eA', 'eB', 'xA', 'xB')}
    if T == 0 or P == 0:
        return gross, {k: np.zeros(0) for k in trades}
    base = close_ff[0]
    cA, cB = close_ff[:, ia], close_ff[:, ib]
    d = cA / base[ia] - cB / base[ib]
    bar = has_bar[:, ia] & has_bar[:, ib]
    fA, fB = fill_px[:, ia], fill_px[:, ib]

    direction = np.zeros(P)                 # +1 long A / short B, -1 short A / long B
    qA, qB = np.zeros(P), np.zeros(P)       # shares per $1 of per-leg notional (signed)
    mA, mB = np.zeros(P), np.zeros(P)       # last marked price
    entry_k = np.full(P, -1)
    eA_, eB_ = np.zeros(P), np.zeros(P)
    pend_entry = np.zeros(P)                # direction of an entry to fill next bar
    pend_exit = np.zeros(P, dtype=bool)

    def _open(idx, k, dirs, pa, pb):
        direction[idx] = dirs
        qA[idx] = dirs / pa
        qB[idx] = -dirs / pb
        mA[idx], mB[idx] = pa, pb
        entry_k[idx] = k
        eA_[idx], eB_[idx] = pa, pb

    def _close(idx, k, xa, xb):
        gross[k, idx] += qA[idx] * (xa - mA[idx]) + qB[idx] * (xb - mB[idx])
        for key, val in (('pair', idx), ('dir', direction[idx]), ('entry_k', entry_k[idx]),
                         ('exit_k', np.full(len(idx), k)), ('eA', eA_[idx]), ('eB', eB_[idx]),
                         ('xA', xa), ('xB', xb)):
            trades[key].append(np.array(val, dtype=float))
        direction[idx] = 0.0
        qA[idx] = qB[idx] = 0.0

    for t in range(T):
        if execution_lag == 1 and t > 0:
            idx = np.nonzero(pend_exit)[0]
            if idx.size:
                xa = np.where(has_bar[t, ia[idx]] & np.isfinite(fA[t, idx]), fA[t, idx], cA[t, idx])
                xb = np.where(has_bar[t, ib[idx]] & np.isfinite(fB[t, idx]), fB[t, idx], cB[t, idx])
                _close(idx, t, xa, xb)
                pend_exit[idx] = False
            idx = np.nonzero(pend_entry)[0]
            if idx.size:
                ok = bar[t, idx] & np.isfinite(fA[t, idx]) & np.isfinite(fB[t, idx])
                go = idx[ok]
                if go.size:
                    _open(go, t, pend_entry[go], fA[t, go], fB[t, go])
                pend_entry[idx] = 0.0

        held = np.nonzero(direction)[0]
        if held.size:                                   # mark to today's close
            gross[t, held] += qA[held] * (cA[t, held] - mA[held]) + qB[held] * (cB[t, held] - mB[held])
            mA[held], mB[held] = cA[t, held], cB[t, held]

        if t == T - 1:                                  # block end: close at this close
            if held.size:
                _close(held, t, cA[t, held], cB[t, held])
            break

        # ── decisions on the close of day t ──
        is_held = direction != 0
        crossed = is_held & ((d[t] * direction >= 0) | ~bar[t])
        can_enter = (~is_held) & bar[t] & (np.abs(d[t]) > threshold)
        if execution_lag == 1 and t + 1 == T - 1:
            can_enter[:] = False                        # fill would be the last bar
        new_dir = -np.sign(d[t])
        if execution_lag == 1:
            pend_exit |= crossed
            pend_entry[can_enter] = new_dir[can_enter]
        else:
            idx = np.nonzero(crossed)[0]
            if idx.size:
                _close(idx, t, cA[t, idx], cB[t, idx])
            idx = np.nonzero(can_enter)[0]
            if idx.size:
                _open(idx, t, new_dir[idx], cA[t, idx], cB[t, idx])

    out = {k: (np.concatenate(v) if v else np.zeros(0)) for k, v in trades.items()}
    for key in ('pair', 'entry_k', 'exit_k'):
        out[key] = out[key].astype(int)
    return gross, out


def _accepts_kwarg(func, name: str) -> bool:
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False
    return name in params or any(p.kind == p.VAR_KEYWORD for p in params.values())


def _trade_costs(trades, ia, ib, symbols, day_numbers, adv, dvol, pit_ratio, leg_notional,
                 cost_model, cost_roundtrip, shape):
    """Per-(day, pair) costs as a fraction of the per-leg notional, and per-trade totals.

    Model costs (default): each of the four leg executions of a round trip through
    cost_model.calculate_leg_cost at the fill price with the stock's own ADV/volatility
    of the execution day; stock borrow on the short leg's entry notional and financing
    on the gross entry notional over the calendar-day holding period (min 1 day, as in
    the engine). Entry costs are booked on the entry fill day, exit + carry costs on the
    exit fill day. `cost_roundtrip` (a fraction) replaces all of it with a flat charge,
    half at entry and half at exit.
    """
    cost = np.zeros(shape)
    n = len(trades['pair'])
    per_trade = np.zeros(n)
    if n == 0:
        return cost, per_trade
    pair, k0, k1 = trades['pair'], trades['entry_k'], trades['exit_k']
    if cost_roundtrip is not None:
        np.add.at(cost, (k0, pair), cost_roundtrip / 2.0)
        np.add.at(cost, (k1, pair), cost_roundtrip / 2.0)
        per_trade[:] = cost_roundtrip
        return cost, per_trade

    N = float(leg_notional)
    pass_pit = pit_ratio is not None and _accepts_kwarg(cost_model.calculate_leg_cost,
                                                        'point_in_time_price')

    def _leg(sym_col, k, shares, price):
        kw = {'daily_volume_shares': float(adv[k, sym_col]),
              'daily_volatility': float(dvol[k, sym_col])}
        if pass_pit:
            ratio = float(pit_ratio[k, sym_col])
            if np.isfinite(ratio) and ratio > 0 and ratio != 1.0:
                kw['point_in_time_price'] = price * ratio
        return cost_model.calculate_leg_cost(shares, price, **kw)['total']

    entry_memo = {}
    for j in range(n):
        p = pair[j]
        a, b = ia[p], ib[p]
        e_a, e_b, x_a, x_b = trades['eA'][j], trades['eB'][j], trades['xA'][j], trades['xB'][j]
        sh_a, sh_b = N / e_a, N / e_b
        ent = 0.0
        for col, sh, px in ((a, sh_a, e_a), (b, sh_b, e_b)):
            key = (col, k0[j])                           # entry: $N at that day's fill
            if key not in entry_memo:
                entry_memo[key] = _leg(col, k0[j], sh, px)
            ent += entry_memo[key]
        ext = _leg(a, k1[j], sh_a, x_a) + _leg(b, k1[j], sh_b, x_b)
        short_col = b if trades['dir'][j] > 0 else a
        days = max(1, int(day_numbers[k1[j]] - day_numbers[k0[j]]))
        carry = (cost_model.calculate_borrow_cost(N, symbols[short_col], days)
                 + cost_model.calculate_financing_cost(2.0 * N, days))
        cost[k0[j], p] += ent / N
        cost[k1[j], p] += (ext + carry) / N
        per_trade[j] = (ent + ext + carry) / N
    return cost, per_trade


# ──────────────────────────────────────────────────────────────────────────────
# Statistics
# ──────────────────────────────────────────────────────────────────────────────

def _sharpe(r, periods=TRADING_DAYS_PER_YEAR) -> float:
    return annualized_sharpe(r, periods)


def _series_stats(returns, dates=None, periods=TRADING_DAYS_PER_YEAR) -> dict:
    """Return / Sharpe / vol / drawdown of a daily series, plus the series with its dates."""
    r = np.asarray(returns, dtype=float)
    if r.size == 0:
        return {'total_return_pct': 0.0, 'sharpe_ratio': 0.0, 'ann_volatility_pct': 0.0,
                'max_drawdown_pct': 0.0, 'n_days': 0, 'daily_returns': [], 'daily_dates': []}
    equity = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(np.concatenate([[1.0], equity]))[1:]
    return {
        'total_return_pct': round(float(equity[-1] - 1.0) * 100, 4),
        'sharpe_ratio': round(_sharpe(r, periods), 3),
        'ann_volatility_pct': round(float(r.std(ddof=1) * np.sqrt(periods) * 100) if r.size > 1 else 0.0, 4),
        'max_drawdown_pct': round(float(np.min(equity / peak - 1.0)) * 100, 4),
        'n_days': int(r.size),
        'daily_returns': [float(x) for x in r],
        'daily_dates': list(dates) if dates is not None else [],
    }


def _distribution(values) -> dict:
    v = np.asarray(values, dtype=float)
    if v.size == 0:
        return {}
    out = {'mean': float(v.mean()), 'std': float(v.std(ddof=1)) if v.size > 1 else 0.0,
           'min': float(v.min()), 'max': float(v.max())}
    for q in _SHARPE_PCTS:
        out['median' if q == 50 else f'p{q}'] = float(np.percentile(v, q))
    return {k: round(x, 4) for k, x in out.items()}


def empirical_percentile(value, sample) -> float:
    """Percentile (0-100) of `value` within `sample`, ties counted as half (mid-rank)."""
    s = np.asarray(sample, dtype=float)
    s = s[np.isfinite(s)]
    try:
        value = float(value)
    except (TypeError, ValueError):
        return float('nan')
    if s.size == 0 or not np.isfinite(value):
        return float('nan')
    return float(100.0 * (np.sum(s < value) + 0.5 * np.sum(s == value)) / s.size)


def random_control_percentile(strategy_sharpe, random_control: dict) -> float:
    """Where a Sharpe ratio falls in the random-pair control's distribution (0-100).

    Uses the per-draw Sharpes of the random control over the benchmark's own calendar.
    A value near 50 means the strategy's pair selection did no better than picking
    pairs at random; >= 95 is the conventional "beats random selection" bar. For a
    strategy whose calendar differs from the benchmark's, prefer the date-aligned
    'vs_strategy' block of run_benchmarks (strategy_series=...).
    """
    return empirical_percentile(strategy_sharpe, (random_control or {}).get('draw_sharpes', []))


# ──────────────────────────────────────────────────────────────────────────────
# Driver
# ──────────────────────────────────────────────────────────────────────────────

def _block_arrays(panel, fill_col):
    """Numpy views of the panel used by the simulator and the cost model."""
    close = panel['Close']
    close_ff = close.ffill().to_numpy(dtype=float)
    has_bar = close.notna().to_numpy()
    if fill_col == 'Open':
        op = panel['Open'].where(panel['Open'] > 0).to_numpy(dtype=float)
        fill = np.where(has_bar, np.where(np.isfinite(op), op, close_ff), np.nan)
    else:
        fill = np.where(has_bar, close_ff, np.nan)
    adv = panel['Volume_MA'].ffill().to_numpy(dtype=float)
    dvol = (panel['Volatility_20'] / np.sqrt(TRADING_DAYS_PER_YEAR)).ffill().to_numpy(dtype=float)
    pit = None
    if panel['Close_PIT'].notna().any().any():
        pit = (panel['Close_PIT'] / close).ffill().to_numpy(dtype=float)
    return close_ff, has_bar, fill, adv, dvol, pit


def _naive_day(ts):
    ts = pd.Timestamp(ts)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts.normalize()


def run_benchmarks(processed_data, universe_symbols,
                   formation_end=None, trade_start='2023-07-01', trade_end=None,
                   n_pairs=20, entry_z=2.0, cost_roundtrip=None, seed=42, max_symbols=None,
                   n_random_draws=DEFAULT_RANDOM_DRAWS, leg_notional=DEFAULT_LEG_NOTIONAL,
                   execution_lag=1, fill=None, cost_model=None, min_coverage=0.9,
                   min_spread_std=0.005, formation_days=FORMATION_DAYS,
                   trading_days=TRADING_DAYS, strategy_series=None, n_boot=5000,
                   sensitivities=True):
    """Run the distance-method baseline and the random-pair control distribution.

    processed_data   : {symbol: OHLCV frame} with Volume_MA / Volatility_20 (the pipeline's
                       processed frames); universe_symbols : the names eligible for pairs.
    trade_start/end  : the out-of-sample period; it is cut into consecutive `trading_days`
                       blocks, each formed on the `formation_days` before it.
    formation_end    : ignored (v31 made the scheme rolling; kept so old call sites work).
    n_pairs, entry_z : GGR's 20 pairs and 2-sigma trigger.
    execution_lag    : 1 (default) = t+1 fills like the engine; 0 = same-bar sensitivity.
    fill             : None -> PAIRS_FILL env ('open' -> next open, else next close).
    leg_notional     : dollars per leg used to price costs (default $2M).
    cost_roundtrip   : optional flat round-trip cost (fraction of per-leg notional) that
                       REPLACES the cost model — a sensitivity knob, not the headline.
    max_symbols      : optional cap on the screened universe per block (seeded sample).
    n_random_draws   : random-pair portfolios, each re-drawn every block (default 200).
    strategy_series  : optional {label: (dates, daily_returns)} — each is compared with
                       the baselines on common dates (Ledoit-Wolf Sharpe-difference test
                       vs the distance method, percentile in the random distribution),
                       under out['vs_strategy'][label]. The FIRST entry is the headline:
                       its test is also out['sharpe_diff_vs_gatev'] and its percentile
                       out['random_control']['strategy_percentile'].

    Returns {} when there is no usable data, else a dict with 'config',
    'distance_method' and 'random_control' (each baseline's daily series carries
    'daily_dates'), 'sensitivity' (same-bar fills; gross of costs) and, with
    strategy_series, 'vs_strategy' / 'sharpe_diff_vs_gatev'.
    """
    if execution_lag not in (0, 1):
        raise ValueError("execution_lag must be 0 (same-bar sensitivity) or 1 (t+1)")
    fill_col = 'Close' if execution_lag == 0 else fill_column_from_env(fill)
    cost_model = cost_model or EnhancedPrimeFundTransactionCostModel()

    logger.info("=" * 70)
    logger.info("BASELINE BENCHMARKS — distance method (Gatev 2006) + random-pair control")
    logger.info("=" * 70)

    panel = _aligned_panel(processed_data, universe_symbols)
    if not panel:
        logger.warning("Benchmark: no usable price data.")
        return {}
    close = panel['Close']
    symbols = list(close.columns)
    cal = close.index
    t_start = _naive_day(trade_start)
    in_trade = cal >= t_start
    if trade_end is not None:
        in_trade &= cal <= _naive_day(trade_end)
    trade_pos = np.nonzero(in_trade)[0]
    if len(trade_pos) < 20:
        logger.warning("Benchmark: insufficient trading-period history.")
        return {}

    col_of = {s: i for i, s in enumerate(symbols)}
    close_ff, has_bar, fill_px, adv, dvol, pit = _block_arrays(panel, fill_col)
    day_numbers = cal.to_numpy().astype('datetime64[D]').astype(np.int64)
    date_str = np.asarray(cal.strftime('%Y-%m-%d'))

    blocks = [trade_pos[i:i + trading_days] for i in range(0, len(trade_pos), trading_days)]
    blocks = [b for b in blocks if len(b) >= 20]
    fill_txt = 'same-bar close (sensitivity)' if execution_lag == 0 else f't+1 {fill_col.lower()}'
    cost_txt = (f'flat {cost_roundtrip * 1e4:.1f} bp round trip' if cost_roundtrip is not None
                else f'pipeline cost model @ ${leg_notional:,.0f}/leg')
    logger.info(f"  Rolling scheme: {len(blocks)} x {trading_days}-day trading blocks, each formed "
                f"on the prior {formation_days} days | fills: {fill_txt} | costs: {cost_txt}")

    dist_parts, rand_parts, dates_parts = [], [], []
    same_bar_parts, gross_parts = [], []
    block_info = []
    n_trades = 0
    trade_costs, holding = [], []
    same_bar_trades = 0

    for b_no, pos in enumerate(blocks):
        p0, p1 = int(pos[0]), int(pos[-1]) + 1
        f0 = max(0, p0 - formation_days)
        form = close.iloc[f0:p0]
        info = {'start': str(date_str[p0]), 'end': str(date_str[p1 - 1]),
                'formation_days': int(len(form))}
        if len(form) < MIN_FORMATION_DAYS:
            info['skipped'] = 'insufficient formation history'
            block_info.append(info)
            continue
        uni = [c for c in _screen_universe(form, min_coverage)
               if np.isfinite(close_ff[p0, col_of[c]])]
        uni = _sample_symbols(uni, max_symbols, [seed, b_no, 0])
        info['universe'] = len(uni)
        if len(uni) < 2:
            info['skipped'] = 'fewer than 2 screened symbols'
            block_info.append(info)
            continue
        cols = np.array([col_of[c] for c in uni])
        norm = _normalize(form[uni]).ffill().bfill().to_numpy(dtype=float)
        ca, cb, ssd, sd = _candidate_pairs(norm, min_spread_std)
        info['candidate_pairs'] = int(len(ca))
        if len(ca) == 0:
            info['skipped'] = 'no eligible pairs'
            block_info.append(info)
            continue
        K = int(min(n_pairs, len(ca)))
        dist_sel = np.lexsort((cb, ca, ssd))[:K]
        rng = np.random.default_rng([seed, b_no, 1])
        rand_sel = (np.stack([rng.choice(len(ca), size=K, replace=False)
                              for _ in range(n_random_draws)]).ravel()
                    if n_random_draws > 0 else np.zeros(0, dtype=int))
        sel = np.concatenate([dist_sel, rand_sel]).astype(int)
        ia, ib = cols[ca[sel]], cols[cb[sel]]
        thr = entry_z * sd[sel]

        rows = slice(p0, p1)
        gross, trades = _simulate_pairs(close_ff[rows], has_bar[rows], fill_px[rows],
                                        ia, ib, thr, execution_lag)
        cost, per_trade = _trade_costs(trades, ia, ib, symbols, day_numbers[rows], adv[rows],
                                       dvol[rows], None if pit is None else pit[rows],
                                       leg_notional, cost_model, cost_roundtrip, gross.shape)
        net = gross - cost
        T_b = p1 - p0
        dist_parts.append(net[:, :K].mean(axis=1))
        rand_parts.append(net[:, K:].reshape(T_b, n_random_draws, K).mean(axis=2)
                          if n_random_draws > 0 else np.zeros((T_b, 0)))
        dates_parts.append(date_str[p0:p1])
        is_dist = trades['pair'] < K
        n_trades += int(is_dist.sum())
        trade_costs.extend(per_trade[is_dist].tolist())
        holding.extend((trades['exit_k'][is_dist] - trades['entry_k'][is_dist]).tolist())
        info.update({'pairs': [[symbols[ia[k]], symbols[ib[k]]] for k in range(K)],
                     'distance_trades': int(is_dist.sum())})
        block_info.append(info)

        if sensitivities:
            gross_parts.append(gross[:, :K].mean(axis=1))
            if execution_lag == 1:
                g0, tr0 = _simulate_pairs(close_ff[rows], has_bar[rows], fill_px[rows],
                                          ia[:K], ib[:K], thr[:K], execution_lag=0)
                c0, _ = _trade_costs(tr0, ia[:K], ib[:K], symbols, day_numbers[rows], adv[rows],
                                     dvol[rows], None if pit is None else pit[rows],
                                     leg_notional, cost_model, cost_roundtrip, g0.shape)
                same_bar_parts.append((g0 - c0).mean(axis=1))
                same_bar_trades += len(tr0['pair'])

    used = [b for b in block_info if 'skipped' not in b]
    if not dist_parts:
        logger.warning("Benchmark: no tradable block.")
        return {}

    dates = [str(x) for x in np.concatenate(dates_parts)]
    dist_r = np.concatenate(dist_parts)
    rand_m = np.concatenate(rand_parts, axis=0)          # (days, draws)

    distance = _series_stats(dist_r, dates)
    distance.update({
        'n_pairs': int(max(len(b.get('pairs', [])) for b in used)),
        'n_blocks': len(used),
        'n_trades': n_trades,
        'avg_holding_days': round(float(np.mean(holding)), 2) if holding else 0.0,
        'avg_round_trip_cost_bps': round(float(np.mean(trade_costs)) * 1e4, 3) if trade_costs else 0.0,
    })

    random_control = {}
    if rand_m.shape[1] > 0:
        draw_sharpes = np.array([_sharpe(rand_m[:, j]) for j in range(rand_m.shape[1])])
        draw_returns = (np.prod(1.0 + rand_m, axis=0) - 1.0) * 100
        sh_dist, ret_dist = _distribution(draw_sharpes), _distribution(draw_returns)
        random_control = {
            'n_draws': int(rand_m.shape[1]),
            'n_pairs_per_draw': distance['n_pairs'],
            'redrawn_every_block': True,
            # kept for older readers: mean over draws (NOT the Sharpe of an average)
            'sharpe_ratio': round(sh_dist['mean'], 3),
            'total_return_pct': round(ret_dist['mean'], 4),
            'return_pct_range': [round(ret_dist['min'], 4), round(ret_dist['max'], 4)],
            'sharpe_distribution': sh_dist,
            'total_return_pct_distribution': ret_dist,
            'distance_sharpe_percentile': round(empirical_percentile(distance['sharpe_ratio'], draw_sharpes), 2),
            'draw_sharpes': [round(float(x), 4) for x in draw_sharpes],
            'draw_total_returns_pct': [round(float(x), 4) for x in draw_returns],
            # the average random portfolio, day by day (its Sharpe is NOT the median draw's)
            'mean_daily_returns': [float(x) for x in rand_m.mean(axis=1)],
            'daily_dates': dates,
        }

    out = {
        'config': {
            'trade_start_requested': str(_naive_day(trade_start).date()),
            'trade_start': dates[0], 'trade_end': dates[-1],
            'n_pairs': n_pairs, 'entry_z': entry_z,
            'scheme': 'rolling 12m formation / 6m trading (Gatev et al. 2006); prices '
                      're-normalised at each block start; exit at the next crossing',
            'formation_days': formation_days,
            'trading_block_days': trading_days,
            'n_trading_blocks': len(blocks),
            'n_blocks_used': len(used),
            'execution_lag': execution_lag,
            'fill': ('same-bar close (sensitivity)' if execution_lag == 0
                     else f't+1 {fill_col.lower()} (signal on the day-t close)'),
            'cost_basis': ('pipeline cost model: commission + half-spread + sqrt impact per leg '
                           'execution (own ADV/vol), borrow on the short leg, financing on gross'
                           if cost_roundtrip is None else 'flat round-trip override (sensitivity)'),
            'leg_notional': float(leg_notional),
            'cost_roundtrip_bps': None if cost_roundtrip is None else cost_roundtrip * 1e4,
            'return_basis': 'committed capital: pair P&L / per-leg notional, equal-weighted '
                            'over the nominated pairs (idle pairs earn 0)',
            'universe_size': len(universe_symbols),
            'universe_with_data': len(symbols),
            'min_coverage': min_coverage,
            'max_symbols': max_symbols,
            'effective_universe_size': [b['universe'] for b in used],
            'effective_universe_median': float(np.median([b['universe'] for b in used])),
            'n_random_draws': n_random_draws,
            'seed': seed,
            # per block: dates, formation length, screened universe, eligible pairs, and
            # the distance method's pairs (random draws are summarised, not listed)
            'blocks': block_info,
        },
        'distance_method': distance,
        'random_control': random_control,
    }

    if sensitivities:
        sens = {'distance_gross_of_costs': {k: v for k, v in _series_stats(np.concatenate(gross_parts)).items()
                                            if k not in ('daily_returns', 'daily_dates')}}
        if same_bar_parts:
            sb = _series_stats(np.concatenate(same_bar_parts))
            sens['distance_same_bar_fills'] = {k: v for k, v in sb.items()
                                               if k not in ('daily_returns', 'daily_dates')}
            sens['distance_same_bar_fills']['n_trades'] = same_bar_trades
            sens['distance_same_bar_fills']['note'] = ('fills at the signal close (no one-day '
                                                       'wait): captures bid-ask bounce; NOT comparable '
                                                       'to the t+1 pipeline')
        out['sensitivity'] = sens

    if strategy_series:
        out['vs_strategy'] = {
            label: _compare_to_strategy(dates_s, rets_s, dates, dist_r, rand_m, n_boot, seed)
            for label, (dates_s, rets_s) in strategy_series.items()
        }
        # The FIRST series is the headline one; surface its results under the flat keys
        # the headline exporter reads (json_export.sharpe_diff_vs_gatev /
        # random_control_summary), date-aligned rather than recomputed on mismatched calendars.
        head_label = next(iter(strategy_series))
        head = out['vs_strategy'][head_label]
        if 'sharpe_difference_vs_distance' in head:
            out['sharpe_diff_vs_gatev'] = dict(head['sharpe_difference_vs_distance'],
                                               strategy=head_label,
                                               n_common_days=head['n_common_days'])
        if random_control and 'strategy_percentile_in_random' in head:
            random_control['strategy_percentile'] = head['strategy_percentile_in_random']
            random_control['strategy_percentile_series'] = head_label

    logger.info(f"  {'Distance method (Gatev)':<28} return {distance['total_return_pct']:+8.3f}% | "
                f"Sharpe {distance['sharpe_ratio']:+.2f} | {distance['n_pairs']} pairs x "
                f"{distance['n_blocks']} blocks | {n_trades} trades, avg round-trip cost "
                f"{distance['avg_round_trip_cost_bps']:.1f} bp")
    if random_control:
        sd_ = random_control['sharpe_distribution']
        logger.info(f"  {'Random-pair control':<28} {random_control['n_draws']} draws | Sharpe median "
                    f"{sd_['median']:+.2f} [p5 {sd_['p5']:+.2f}, p95 {sd_['p95']:+.2f}] | distance "
                    f"method at the {random_control['distance_sharpe_percentile']:.0f}th percentile")
    logger.info(f"  Effective universe per block: {out['config']['effective_universe_size']}")
    logger.info("=" * 70)
    return out


def _compare_to_strategy(dates_s, rets_s, bench_dates, dist_r, rand_m, n_boot, seed) -> dict:
    """Date-aligned comparison of one strategy series with the baselines."""
    common, rs, rd = align_return_series(dates_s, rets_s, bench_dates, dist_r)
    out = {'n_common_days': len(common),
           'coverage_of_benchmark_days': round(len(common) / max(len(bench_dates), 1), 4)}
    if len(common) < 20:
        out['note'] = 'fewer than 20 common dates; no comparison'
        return out
    pos = {d: i for i, d in enumerate(bench_dates)}
    rows = np.array([pos[d] for d in common])
    s_sharpe = _sharpe(rs)
    out.update({
        'common_start': common[0], 'common_end': common[-1],
        'strategy_sharpe': round(s_sharpe, 3),
        'distance_sharpe': round(_sharpe(rd), 3),
        'sharpe_difference_vs_distance': sharpe_difference_test(rs, rd, n_boot=n_boot, seed=seed),
    })
    if rand_m.shape[1] > 0:
        sub = rand_m[rows]
        draws = np.array([_sharpe(sub[:, j]) for j in range(sub.shape[1])])
        out['random_sharpe_distribution'] = _distribution(draws)
        out['strategy_percentile_in_random'] = round(empirical_percentile(s_sharpe, draws), 2)
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
    logger.info(f"  {'Distance method (Gatev 2006), t+1':<40} "
                f"ret {d.get('total_return_pct', 0):+7.3f}% | Sharpe {d.get('sharpe_ratio', 0):+.2f}")
    if r:
        sd = r.get('sharpe_distribution', {})
        logger.info(f"  {'Random-pair control, median of %d' % r.get('n_draws', 0):<40} "
                    f"ret {r.get('total_return_pct_distribution', {}).get('median', 0):+7.3f}% | "
                    f"Sharpe {sd.get('median', 0):+.2f}  [p5 {sd.get('p5', 0):+.2f}, p95 {sd.get('p95', 0):+.2f}]")
        logger.info(f"  Strategy Sharpe percentile among random-pair draws: "
                    f"{random_control_percentile(strategy_sharpe, r):.1f}")
    for label, cmp_ in (benchmarks.get('vs_strategy') or {}).items():
        t = cmp_.get('sharpe_difference_vs_distance') or {}
        if not t:
            continue
        logger.info(f"  [{label}] vs distance on {cmp_.get('n_common_days')} common days: "
                    f"Sharpe diff {t.get('diff', float('nan')):+.2f} "
                    f"(95% CI [{t.get('ci_lo', float('nan')):+.2f}, {t.get('ci_hi', float('nan')):+.2f}], "
                    f"p={t.get('pvalue', float('nan')):.3f}, Ledoit-Wolf, block {t.get('block')}) | "
                    f"random-draw percentile {cmp_.get('strategy_percentile_in_random', float('nan')):.1f}")
    sens = benchmarks.get('sensitivity') or {}
    if 'distance_same_bar_fills' in sens:
        s = sens['distance_same_bar_fills']
        logger.info(f"  (sensitivity) distance method with SAME-BAR fills: ret {s['total_return_pct']:+.3f}% | "
                    f"Sharpe {s['sharpe_ratio']:+.2f} — bid-ask bounce, not comparable")
    logger.info("=" * 70)
