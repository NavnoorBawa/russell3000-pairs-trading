"""
PAIRS TRADING - ANATOMY OF THE NULL
===================================
Where a near-zero net Sharpe comes from, computed from a run's exported results JSON
(json_export.export_testing_results_to_json) and, where the export does not carry what a
diagnostic needs, from the price cache the run traded on. Every number is a function of
the run's own trades and daily equity; nothing here feeds back into the strategy.

  reconstruction  Each trade's daily mark-to-market P&L rebuilt from the cached closes
                  with the engine's share counts and fills, and checked against every
                  trade's exported gross P&L before it is used. It supplies the daily
                  gross/cost split (net = gross - costs, per previous-day equity) that
                  exports before v33 do not carry.
  gross_vs_net    Gross, cost and net P&L per trade in bp of gross notional; the
                  break-even cost multiple k* (every cost scaled by k: total net P&L is
                  zero at k* = gross P&L / costs); the daily Sharpe at k = 0, 0.5, 1, 1.5,
                  2; the cost mix; a borrow-fee stress (every short at 1% and 3% a year,
                  Muravyev, Pearson & Pollet 2025 Table 1: median 0.38%, 90th percentile
                  3%); and the square-root impact coefficient Y = 0.3 / 0.6 / 1.0 (Toth et
                  al. 2011 eq. 1; Kyle & Obizhaeva 2016 Table V imply Y ~ 0.6) re-priced
                  execution by execution with the cost model's 50 bp cap.
  shortfall       Implementation shortfall (Perold 1988; Frazzini, Israel & Moskowitz
                  2018, eqs. 1-6): a paper P&L filled at the signal-day closes
                  (unattainable: those closes are the signal's own inputs), minus the
                  one-day delay on entry and on exit, half-spread, impact, commission,
                  borrow and financing, which leaves the booked net P&L exactly.
  exit_race       Profit targets against stop-losses among the trades that hit either
                  barrier, compared with the same rule on a driftless random walk
                  (gambler's ruin, and simulated with the time stop) and on OU spreads
                  with the pairs' formation half-lives.
  persistence     Clegg (2014): of the pairs cointegrated in one calendar year, the share
                  still cointegrated the next year, against the 5% nominal chance rate and
                  the next year's base rate; and the traded pairs' formation and
                  out-of-sample p-values and half-lives with Kendall's (1954) small-sample
                  correction of the AR(1) coefficient.
  decay           The same rule on the same traded pairs in their formation window and out
                  of sample, by per-pair re-simulation with the engine's own rule.
  breakdowns      P&L by side, exit reason, |z| bucket, year and month; concentration.
  exposure        Hedge ratios and each trade's net dollar and implied market-beta exposure.
  capacity        Net bp per trade and Sharpe at $10M to $5B, impact re-priced per execution.
  cash            The compounded 3-month T-bill over the window: the engine's equity earns
                  no interest, so its returns and Sharpe ratios are excess-of-cash figures,
                  up to the bill interest on the book's net dollar exposure (reported).

Units: bp are of a trade's gross notional (position_size_dollars: both legs at the
signal-day close, $1 of leg 1 against $beta of leg 2), daily returns are fractions of
the previous day's portfolio value, and $ are dollars of the run's book.
"""

import copy
import io
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from scipy import stats as sps

from pairs_trading.config import logging
from pairs_trading.pair_selector import FixedPrimeFundPairSelector
from pairs_trading.significance import annualized_sharpe, hac_tstat_mean
from pairs_trading.trading_system import (
    TRADING_DAYS_PER_YEAR, CompleteFixedRussell3000TradingSystem as Engine, resolve_fill_column,
)
from pairs_trading.transaction_costs import EnhancedPrimeFundTransactionCostModel

logger = logging.getLogger(__name__)

SCHEMA = 1
COST_MULTIPLES = (0.0, 0.5, 1.0, 1.5, 2.0)
# Cost components in the order the shortfall waterfall subtracts them.
COST_COMPONENTS = ('bid_ask', 'market_impact', 'commission', 'borrow', 'financing')
COST_LABELS = {'bid_ask': 'Half-spread', 'market_impact': 'Market impact', 'commission': 'Commission',
               'borrow': 'Borrow', 'financing': 'Financing'}
BORROW_STRESS_RATES = (0.01, 0.03)          # every short leg, per year
IMPACT_COEFFICIENTS = (0.3, 0.6, 1.0)       # square-root impact Y
CAPACITY_AUM = (10e6, 100e6, 1e9, 5e9)
EXIT_REASONS = ('target', 'stop', 'time', 'end_of_data', 'risk_halt')
SIDES = ('LONG', 'SHORT')
Z_BUCKETS = ((1.8, 2.0, '1.8-2.0'), (2.0, 2.5, '2.0-2.5'), (2.5, 3.0, '2.5-3.0'), (3.0, None, '>=3.0'))
# The export rounds net P&L and each cost component to cents: a rebuilt gross P&L within
# 5 cents of net + costs reproduces the trade "to within rounding".
GROSS_TOLERANCE_USD = 0.05
# The exported z has 3 decimals and the exported hedge ratio 4: the reference window is
# recovered when some window reproduces z to this tolerance.
Z_MATCH_TOLERANCE = 0.0025
PERSISTENCE_ALPHA = 0.05
PERSISTENCE_YEARS = (2020, 2021, 2022, 2023, 2024)
# Version of the cointegration_persistence table: a saved table is reused only if it matches.
PERSISTENCE_SCHEMA = 2
# A calendar year has ~250 bars; the selector's own 420-day minimum needs ~1.7 years.
PERSISTENCE_MIN_DAYS = 200
MARKET_BETA_DAYS = 252
EXIT_RACE_PATHS = 20_000


# ──────────────────────────────────────────────────────────────────────────────
# Small helpers
# ──────────────────────────────────────────────────────────────────────────────

def _day(x) -> pd.Timestamp:
    """Tz-naive trading date of a 'YYYY-MM-DD...' string or Timestamp."""
    return pd.Timestamp(str(x)[:10])


def _naive(df: pd.DataFrame) -> pd.DataFrame:
    """`df` with a tz-naive DatetimeIndex (the price cache's bars are America/New_York)."""
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is None:
        return df
    out = df.copy(deep=False)
    out.index = idx.tz_localize(None)
    return out


def _f(x) -> Optional[float]:
    """float(x), or None when missing or not finite (JSON-safe)."""
    if x is None:
        return None
    x = float(x)
    return x if np.isfinite(x) else None


def _mean_t(x) -> Dict:
    """n, mean, median, sample sd and iid t-statistic of the mean of a 1-D sample."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = int(x.size)
    if n == 0:
        return {'n': 0, 'mean': None, 'median': None, 'sd': None, 't': None}
    sd = float(x.std(ddof=1)) if n > 1 else None
    t = float(x.mean() / (sd / np.sqrt(n))) if sd else None
    return {'n': n, 'mean': float(x.mean()), 'median': float(np.median(x)), 'sd': sd, 't': t}


def _clustered_t(values, groups) -> Optional[float]:
    """t of the mean with standard errors clustered by group (CR1: G/(G-1) small-sample factor).

    Trades signalled in the same month share market moves; clustering by month keeps
    their correlation out of the t-statistic.
    """
    x = np.asarray(values, dtype=float)
    g = pd.Index(groups)
    n, n_groups = x.size, g.nunique()
    if n < 2 or n_groups < 2:
        return None
    u = pd.Series(x - x.mean()).groupby(np.asarray(g)).sum().to_numpy()
    var = float((u ** 2).sum()) / n ** 2 * n_groups / (n_groups - 1)
    return float(x.mean() / np.sqrt(var)) if var > 0 else None


def _daily_block(r) -> Dict:
    """Annualised Sharpe, compounded return (%) and Newey-West t of a daily return series."""
    r = np.asarray(r, dtype=float)
    h = hac_tstat_mean(r)
    return {'sharpe': annualized_sharpe(r, TRADING_DAYS_PER_YEAR),
            'total_return_pct': float((np.prod(1.0 + r) - 1.0) * 100.0) if r.size else 0.0,
            'hac_t': h['tstat'], 'hac_p': h['pvalue']}


def _z_bucket(abs_z: float) -> str:
    for lo, hi, label in Z_BUCKETS:
        if abs_z >= lo and (hi is None or abs_z < hi):
            return label
    return f'<{Z_BUCKETS[0][0]}'


def _half_life(phi: float) -> Optional[float]:
    """-ln 2 / ln phi for 0 < phi < 1; None when the AR(1) does not mean-revert."""
    if phi is None or not np.isfinite(phi) or not 0.0 < phi < 1.0:
        return None
    return float(-np.log(2.0) / np.log(phi))


def kendall_half_life(phi: float, n: int) -> Dict:
    """Half-life of an OLS AR(1) coefficient, raw and with Kendall's (1954) bias correction.

    For an AR(1) with an estimated mean, E[phi_hat - phi] = -(1 + 3 phi) / n + O(n^-2)
    (Kendall 1954; Marriott & Pope 1954): OLS overstates the speed of mean reversion, and
    pairs selected for a short half-life are selected partly on that error. The corrected
    coefficient is phi_c = phi_hat + (1 + 3 phi_hat) / n. A half-life is None where the
    coefficient implies no mean reversion (phi outside (0, 1)).
    """
    phi = _f(phi)
    if phi is None or not n:
        return {'phi': phi, 'n': int(n or 0), 'phi_kendall': None, 'half_life': None,
                'half_life_kendall': None}
    phi_c = phi + (1.0 + 3.0 * phi) / n
    return {'phi': phi, 'n': int(n), 'phi_kendall': phi_c, 'half_life': _half_life(phi),
            'half_life_kendall': _half_life(phi_c)}


# ──────────────────────────────────────────────────────────────────────────────
# Inputs: trades, prices on the run's calendar, formation windows
# ──────────────────────────────────────────────────────────────────────────────

def trade_table(results: Dict) -> pd.DataFrame:
    """One row per exported trade, with the quantities every section uses.

    symbol1/symbol2 are the pair's legs in the engine's orientation (the spread is
    log p1 - beta log p2; a LONG spread is long leg 1). cost_usd is the sum of the cost
    components and gross_usd = net_pnl_dollars + cost_usd: the export rounds each of them
    to cents, so gross_usd is within a few cents of net + transaction_costs_dollars and
    the cost waterfall closes exactly on the exported net P&L.
    """
    rows = []
    for t in results.get('all_trades') or []:
        cb = t.get('cost_breakdown_dollars') or {}
        comps = {k: float(cb.get(k) or 0.0) for k in COST_COMPONENTS}
        cost = float(sum(comps.values()))
        net = float(t['net_pnl_dollars'])
        notional = float(t['position_size_dollars'])
        long_spread = t['action'] == 'LONG'
        rows.append({
            'trade_id': int(t['trade_id']), 'pair': t['pair'], 'action': t['action'],
            'symbol1': t['long_symbol'] if long_spread else t['short_symbol'],
            'symbol2': t['short_symbol'] if long_spread else t['long_symbol'],
            'long_symbol': t['long_symbol'], 'short_symbol': t['short_symbol'],
            'signal_date': _day(t['signal_date']), 'entry_date': _day(t['entry_date']),
            'exit_signal_date': _day(t.get('exit_signal_date') or t['exit_date']),
            'exit_date': _day(t['exit_date']), 'exit_reason': t['exit_reason'],
            'hedge_ratio': float(t['hedge_ratio']), 'zscore': float(t['zscore']),
            'abs_z': abs(float(t['zscore'])),
            'notional': notional, 'long_notional': float(t['long_notional_dollars']),
            'short_notional': float(t['short_notional_dollars']),
            'calendar_days': int(t['holding_days_calendar']), 'trading_days': int(t['trading_days_held']),
            'net_usd': net, 'cost_usd': cost, 'gross_usd': net + cost,
            'transaction_costs_usd': float(t['transaction_costs_dollars']),
            **{f'cost_{k}': v for k, v in comps.items()},
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        for col in ('gross', 'cost', 'net'):
            df[f'{col}_bp'] = df[f'{col}_usd'] / df['notional'] * 1e4
    return df


def run_capital(results: Dict) -> float:
    """The run's starting capital (metadata.initial_capital, else the first equity value)."""
    cap = _f((results.get('metadata') or {}).get('initial_capital'))
    if cap:
        return cap
    return float(results['daily_equity_curve'][0]['portfolio_value'])


def run_calendar(results: Dict, trades: pd.DataFrame) -> pd.DatetimeIndex:
    """The run's trading dates: the daily equity curve's, plus any trade date not on it."""
    dates = {_day(c['date']) for c in results.get('daily_equity_curve') or []}
    for col in ('signal_date', 'entry_date', 'exit_signal_date', 'exit_date'):
        if col in trades:
            dates.update(trades[col])
    return pd.DatetimeIndex(sorted(dates))


class PricePanel:
    """Cached prices on a run's calendar, read the way the engine reads them.

    close(sym)        last real, positive close at or before each calendar date: the
                      engine's valuation price and the exit price of a leg without a bar
    fill_price / exit_price   the engine's t+1 fill on a calendar day
                      (TradingSystem._fill_price / _exit_price)
    leg_inputs(sym)   20-day average share volume, daily volatility (20-day, annualised
                      / sqrt 252) and the point-in-time / adjusted price ratio as of each
                      date: the cost model's inputs (TradingSystem._aligned)
    pair_log_prices   log closes on the dates where both legs have a real, positive
                      close: the rows of the pair's Kalman state
    frame(sym)        the symbol's bars with a tz-naive index
    """

    def __init__(self, prices: Dict[str, pd.DataFrame], calendar: Sequence):
        self.prices = prices
        self.calendar = pd.DatetimeIndex(calendar)
        self._frames: Dict[str, pd.DataFrame] = {}
        self._aligned: Dict[str, Dict[str, np.ndarray]] = {}

    def frame(self, sym: str) -> pd.DataFrame:
        if sym not in self._frames:
            df = self.prices.get(sym)
            if df is None:
                raise KeyError(f"{sym} is not in the price cache")
            self._frames[sym] = _naive(df)
        return self._frames[sym]

    def _align(self, sym: str) -> Dict[str, np.ndarray]:
        a = self._aligned.get(sym)
        if a is not None:
            return a
        df, cal = self.frame(sym), self.calendar
        nan = np.full(len(cal), np.nan)
        close = df['Close'].where(df['Close'] > 0)

        def ffill(series):
            return series.reindex(cal, method='ffill').to_numpy(dtype=float)

        a = {'close': ffill(close.dropna()),
             'has_bar': close.reindex(cal).notna().to_numpy(),
             'open': (df['Open'].where(df['Open'] > 0).reindex(cal).to_numpy(dtype=float)
                      if 'Open' in df.columns else nan),
             'adv': ffill(df['Volume_MA']) if 'Volume_MA' in df.columns else nan,
             'dvol': (ffill(df['Volatility_20'] / np.sqrt(TRADING_DAYS_PER_YEAR))
                      if 'Volatility_20' in df.columns else nan),
             'pit_ratio': (ffill(df['Close_PIT'] / df['Close']) if 'Close_PIT' in df.columns
                           else np.ones(len(cal)))}
        self._aligned[sym] = a
        return a

    def close(self, sym: str) -> np.ndarray:
        return self._align(sym)['close']

    def fill_price(self, sym: str, k: int, fill_col: str = 'Close') -> float:
        a = self._align(sym)
        if not a['has_bar'][k]:
            return float('nan')
        if fill_col == 'Open' and np.isfinite(a['open'][k]):
            return float(a['open'][k])
        return float(a['close'][k])

    def exit_price(self, sym: str, k: int, fill_col: str = 'Close') -> float:
        p = self.fill_price(sym, k, fill_col)
        return p if np.isfinite(p) else float(self._align(sym)['close'][k])

    def leg_inputs(self, sym: str, k: int) -> Tuple[float, float, float]:
        a = self._align(sym)
        return float(a['adv'][k]), float(a['dvol'][k]), float(a['pit_ratio'][k])

    def pair_log_prices(self, s1: str, s2: str) -> Tuple[pd.DatetimeIndex, np.ndarray, np.ndarray]:
        c1, c2 = self.frame(s1)['Close'], self.frame(s2)['Close']
        common = c1.index.intersection(c2.index)
        p1, p2 = c1.loc[common], c2.loc[common]
        ok = (p1.notna() & p2.notna() & (p1 > 0) & (p2 > 0)).to_numpy()
        return (pd.DatetimeIndex(common[ok]), np.log(p1.to_numpy(dtype=float)[ok]),
                np.log(p2.to_numpy(dtype=float)[ok]))

    def window(self, sym: str, start, end) -> pd.DataFrame:
        df = self.frame(sym)
        return df[(df.index >= _day(start)) & (df.index <= _day(end))]


def formation_schedule(results: Dict) -> List[Tuple[pd.Timestamp, pd.Timestamp]]:
    """(formation date, first date of its data window) of every pair selection of the run.

    Runs that export universe_by_formation (v33 on) list every formation date and select
    on the trailing profile.formation_calendar_days (TradingSystem._full_reselection);
    otherwise the one selection at the pair-selection cutoff used every bar from the
    data start (v32: 2020-01-02 to 2022-12-31).
    """
    rc = results.get('run_config') or {}
    study = rc.get('study') or {}
    data_start = _day((rc.get('data') or {}).get('data_start')
                      or (study.get('calendar') or {}).get('data_start') or '2020-01-01')
    window_days = (study.get('profile') or {}).get('formation_calendar_days')
    dates = [u['formation_date'] for u in results.get('universe_by_formation') or [] if u.get('formation_date')]
    if not dates:
        cutoff = ((results.get('walk_forward_validation') or {}).get('pair_selection_cutoff')
                  or (study.get('calendar') or {}).get('selection_cutoff'))
        if not cutoff:
            raise ValueError("the export names no pair-selection cutoff or formation dates")
        dates = [cutoff]
    out = []
    for d in sorted({_day(x) for x in dates}):
        start = data_start if not window_days else max(data_start, d - pd.Timedelta(days=int(window_days) - 1))
        out.append((d, start))
    return out


def backtest_window(results: Dict) -> Tuple[pd.Timestamp, pd.Timestamp]:
    """First and last date of the main backtest (metadata.backtest_period, else the curve)."""
    bp = (results.get('metadata') or {}).get('backtest_period') or {}
    curve = results.get('daily_equity_curve') or [{}]
    return _day(bp.get('start') or curve[0]['date']), _day(bp.get('end') or curve[-1]['date'])


def pair_windows(trades: pd.DataFrame, results: Dict) -> pd.DataFrame:
    """Per traded pair: the formation that selected it and its out-of-sample window.

    The formation is the latest one dated on or before the pair's first signal (the
    engine trades the pairs of the latest selection dated <= each day); out of sample is
    the main backtest after that formation date.
    """
    schedule = formation_schedule(results)
    bt_start, bt_end = backtest_window(results)
    rows = []
    for (s1, s2), g in trades.groupby(['symbol1', 'symbol2'], sort=True):
        first = g['signal_date'].min()
        earlier = [f for f in schedule if f[0] <= first] or schedule[:1]
        f_date, f_start = earlier[-1]
        rows.append({'symbol1': s1, 'symbol2': s2, 'pair': f'{s1}-{s2}', 'trades': int(len(g)),
                     'formation_start': f_start, 'formation_end': f_date,
                     'oos_start': max(bt_start, f_date + pd.Timedelta(days=1)), 'oos_end': bt_end})
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────────────────────
# Reconstruction of the daily gross P&L
# ──────────────────────────────────────────────────────────────────────────────

def _leg_path(close: np.ndarray, entry: float, exit_: float, ke: int, kx: int) -> np.ndarray:
    """Per-share mark-to-market of one leg on calendar days ke..kx (entry to exit fill).

    Entry day: fill -> close; days in between: close -> close; exit day: previous close
    -> exit fill (TradingSystem._build_trade_path), so the path sums to exit - entry.
    """
    if kx <= ke:
        return np.array([exit_ - entry])
    path = np.empty(kx - ke + 1)
    path[0] = close[ke] - entry
    path[1:-1] = np.diff(close[ke:kx])
    path[-1] = exit_ - close[kx - 1]
    return path


def reconstruct_trades(trades: pd.DataFrame, panel: PricePanel, fill_col: str = 'Close') -> Dict:
    """Each trade's daily gross P&L rebuilt from cached prices, verified against the export.

    The engine fixes share counts from the signal-day close and fills at the next bar;
    the export records each leg's notional at the entry fill, so shares = notional /
    entry fill price. Returns the share counts, fill prices and rebuilt gross P&L per
    trade, the daily gross dollars on the panel's calendar, and the check: every trade's
    rebuilt gross must be within GROSS_TOLERANCE_USD of its exported gross.
    """
    cal = panel.calendar
    daily = np.zeros(len(cal))
    rec = []
    for t in trades.itertuples(index=False):
        ke, kx = cal.get_loc(t.entry_date), cal.get_loc(t.exit_date)
        legs = {}
        for side, sym, notional in (('long', t.long_symbol, t.long_notional),
                                    ('short', t.short_symbol, t.short_notional)):
            e = panel.fill_price(sym, ke, fill_col)
            x = panel.exit_price(sym, kx, fill_col)
            legs[side] = {'shares': notional / e, 'entry': e, 'exit': x,
                          'path': _leg_path(panel.close(sym), e, x, ke, kx)}
        path = legs['long']['shares'] * legs['long']['path'] - legs['short']['shares'] * legs['short']['path']
        daily[ke:kx + 1] += path
        rec.append({'q_long': legs['long']['shares'], 'q_short': legs['short']['shares'],
                    'entry_long': legs['long']['entry'], 'entry_short': legs['short']['entry'],
                    'exit_long': legs['long']['exit'], 'exit_short': legs['short']['exit'],
                    'gross_usd': float(path.sum())})
    per_trade = pd.DataFrame(rec, index=trades.index)
    err = (per_trade['gross_usd'] - trades['gross_usd']).to_numpy() if len(trades) else np.zeros(0)
    bad = int((~(np.abs(err) <= GROSS_TOLERANCE_USD)).sum())
    return {
        'per_trade': per_trade, 'daily_gross_usd': daily, 'fill': fill_col,
        'check': {'trades': int(len(trades)), 'max_abs_error_usd': float(np.abs(err).max()) if err.size else 0.0,
                  'sum_error_usd': float(err.sum()), 'tolerance_usd': GROSS_TOLERANCE_USD,
                  'trades_outside_tolerance': bad, 'verified': bad == 0},
    }


def daily_series(results: Dict, trades: pd.DataFrame, reconstruction: Optional[Dict] = None,
                 panel: Optional[PricePanel] = None) -> Dict:
    """Daily net, gross and cost returns of the main backtest (fractions of the previous
    day's equity), with net = gross - costs.

    The engine books every open position's mark-to-market P&L and the costs filled that
    day against the previous day's equity (TradingSystem.run_comprehensive_backtest).
    Exports from v33 on carry gross_return_pct and cost_pct per day; they are used as
    exported, and a reconstruction, if given, is checked against them. Older exports
    carry only the equity curve: the gross dollars then come from the reconstruction and
    a day's costs are gross$ - (equity_t - equity_{t-1}). That split is used only if it
    passes its check: every trade reconstructed within rounding, and implied costs that
    are non-negative, zero on days without a fill and sum to the trades' exported costs;
    otherwise gross and cost are None.
    """
    curve = results['daily_equity_curve']
    dates = pd.DatetimeIndex([_day(c['date']) for c in curve])
    pv = np.array([c['portfolio_value'] for c in curve], dtype=float)
    prev = np.concatenate([[run_capital(results)], pv[:-1]])
    net_usd = pv - prev
    out = {'dates': dates, 'equity': pv, 'equity_prev': prev, 'net_usd': net_usd, 'net': net_usd / prev,
           'gross': None, 'cost': None, 'source': None, 'check': {}}
    rec_usd = None
    if reconstruction is not None and panel is not None:
        rec_usd = reconstruction['daily_gross_usd'][panel.calendar.get_indexer(dates)]
    exported = bool(curve) and all(c.get('gross_return_pct') is not None and c.get('cost_pct') is not None
                                   for c in curve)
    if exported:
        out['gross'] = np.array([c['gross_return_pct'] for c in curve], dtype=float) / 100.0
        out['cost'] = np.array([c['cost_pct'] for c in curve], dtype=float) / 100.0
        out['source'] = 'export'
        if rec_usd is not None:
            diff = rec_usd / prev - out['gross']
            # gross_return_pct has 6 decimals: 5e-9 of equity
            out['check'] = {'max_abs_diff_reconstructed_vs_exported_gross_pct': float(np.abs(diff).max() * 100),
                            'verified': bool(np.abs(diff).max() < 1e-7)}
    elif rec_usd is not None:
        cost_usd = rec_usd - net_usd
        fills = np.zeros(len(dates), dtype=bool)
        for col in ('entry_date', 'exit_date') if len(trades) else ():
            pos = dates.get_indexer(trades[col])
            fills[pos[pos >= 0]] = True
        off = np.abs(cost_usd[~fills]).max() if (~fills).any() else 0.0
        total = float(cost_usd.sum())
        booked = float(trades['cost_usd'].sum()) if len(trades) else 0.0
        tol_total = GROSS_TOLERANCE_USD * (len(trades) + 1)
        verified = bool(reconstruction['check']['verified'] and off <= GROSS_TOLERANCE_USD
                        and cost_usd.min() >= -GROSS_TOLERANCE_USD and abs(total - booked) <= tol_total)
        out['check'] = {'min_daily_cost_usd': float(cost_usd.min()) if cost_usd.size else 0.0,
                        'max_abs_cost_usd_on_days_without_fills': float(off),
                        'implied_cost_usd': total, 'trades_cost_usd': booked, 'verified': verified}
        if verified:
            out.update(gross=rec_usd / prev, cost=cost_usd / prev, source='reconstructed')
        else:
            out['source'] = 'reconstruction failed its check: not used'
    return out


def execution_table(trades: pd.DataFrame, panel: PricePanel, reconstruction: Dict) -> pd.DataFrame:
    """The four executions of every trade (each leg at the entry and at the exit fill) with
    the cost model's inputs on that day: shares, fill price, 20-day average share volume,
    daily volatility and the point-in-time price ratio (TradingSystem._leg_costs)."""
    cal = panel.calendar
    rows = []
    for (i, t), (_, r) in zip(trades.iterrows(), reconstruction['per_trade'].iterrows()):
        for when, date in (('entry', t['entry_date']), ('exit', t['exit_date'])):
            k = cal.get_loc(date)
            for side, sym, shares in (('long', t['long_symbol'], r['q_long']), ('short', t['short_symbol'], r['q_short'])):
                adv, dvol, pit = panel.leg_inputs(sym, k)
                rows.append({'trade': i, 'trade_id': t['trade_id'], 'when': when, 'date': date, 'symbol': sym,
                             'shares': shares, 'price': r[f'{when}_{side}'], 'adv': adv, 'dvol': dvol,
                             'pit_ratio': pit})
    return pd.DataFrame(rows)


def execution_impact(execs: pd.DataFrame, coefficient: Optional[float] = None, scale: float = 1.0,
                     cost_model: Optional[EnhancedPrimeFundTransactionCostModel] = None) -> np.ndarray:
    """Square-root market impact (dollars) of each execution, at `scale` x the traded size.

    The cost model's own calculate_leg_cost (its square-root law Y sigma sqrt(Q/ADV),
    50 bp cap and defaults for missing inputs) with impact coefficient Y = `coefficient`
    (default: the model's). `scale` multiplies the share count: a book `scale` times
    larger trades `scale` times more shares of the same stocks.
    """
    model = copy.copy(cost_model or EnhancedPrimeFundTransactionCostModel())
    if coefficient is not None:
        model.market_impact_coefficient = float(coefficient)
    out = np.empty(len(execs))
    for j, e in enumerate(execs.itertuples(index=False)):
        pit = e.price * e.pit_ratio if np.isfinite(e.pit_ratio) else None
        out[j] = model.calculate_leg_cost(e.shares * scale, e.price, daily_volume_shares=e.adv,
                                          daily_volatility=e.dvol, point_in_time_price=pit)['market_impact']
    return out


def _impact_check(trades: pd.DataFrame, execs: pd.DataFrame, base: np.ndarray) -> Dict:
    """Per-trade sum of the re-priced impacts against the exported market_impact."""
    per_trade = pd.Series(base).groupby(execs['trade'].to_numpy()).sum().reindex(trades.index, fill_value=0.0)
    err = (per_trade - trades['cost_market_impact']).to_numpy()
    bad = int((~(np.abs(err) <= GROSS_TOLERANCE_USD)).sum())
    return {'max_abs_error_usd': float(np.abs(err).max()) if err.size else 0.0,
            'trades_outside_tolerance': bad, 'verified': bad == 0}


# ──────────────────────────────────────────────────────────────────────────────
# (a) Gross vs net, cost multiples, cost mix, borrow and impact scenarios
# ──────────────────────────────────────────────────────────────────────────────

def _cost_by_day(daily: Dict, dates, usd) -> np.ndarray:
    """Dollar amounts booked on `dates`, summed per day of the daily series."""
    out = np.zeros(len(daily['dates']))
    pos = daily['dates'].get_indexer(pd.DatetimeIndex(dates))
    if (pos < 0).any():
        raise ValueError("a fill date is not on the run's daily calendar")
    np.add.at(out, pos, np.asarray(usd, dtype=float))
    return out


def _scenario_returns(daily: Dict, extra_cost_usd: np.ndarray) -> np.ndarray:
    """Daily net returns with extra costs (dollars per day) booked against the same equity."""
    return daily['gross'] - daily['cost'] - extra_cost_usd / daily['equity_prev']


def gross_vs_net(trades: pd.DataFrame, daily: Dict, execs: Optional[pd.DataFrame] = None,
                 execs_verified: bool = False,
                 cost_model: Optional[EnhancedPrimeFundTransactionCostModel] = None) -> Dict:
    """Per-trade gross vs net, the break-even cost multiple, the cost-multiple curve, the
    cost mix and the borrow-fee and impact-coefficient scenarios.

    k* = total gross P&L / total costs (dollars): with every cost component scaled by k
    and the trades held fixed, total net P&L is zero at k = k*. It is undefined (None)
    when the gross P&L is not positive: no cost level breaks even. The daily curve scales
    the run's daily cost series, r_k = gross - k x costs (both per previous-day equity);
    the trades are held fixed, as the engine's ex-ante cost gate never binds for screened
    names. The Sharpe crosses zero at mean(gross) / mean(costs).

    Borrow stress: every short leg pays `rate` a year on its notional at the entry fill
    for the trade's calendar days, booked at the exit fill (TradingSystem._finalise_trade),
    in place of the modelled fee. Impact: each execution is re-priced with the cost
    model at Y = 0.3 / 0.6 / 1.0, cap included, when the re-priced impacts at the model's
    own Y reproduce every trade's exported impact; otherwise the exported impact is scaled
    by Y / Y_model (linear, cap ignored, booked half at entry and half at exit).
    """
    model = cost_model or EnhancedPrimeFundTransactionCostModel()
    n = len(trades)
    out: Dict = {'trades': int(n)}
    if n == 0:
        return out
    gross, cost, net = (float(trades[c].sum()) for c in ('gross_usd', 'cost_usd', 'net_usd'))
    notional = float(trades['notional'].sum())
    out['per_trade'] = {
        'gross_bp': _mean_t(trades['gross_bp']), 'cost_bp': _mean_t(trades['cost_bp']),
        'net_bp': _mean_t(trades['net_bp']),
        'gross_win_rate': float((trades['gross_usd'] > 0).mean()),
        'net_win_rate': float((trades['net_usd'] > 0).mean()),
        'notional_weighted_gross_bp': gross / notional * 1e4,
        'notional_weighted_cost_bp': cost / notional * 1e4,
    }
    out['totals'] = {'gross_usd': gross, 'cost_usd': cost, 'net_usd': net,
                     'gross_to_cost_ratio': gross / cost if cost > 0 else None,
                     'breakeven_cost_multiple': gross / cost if cost > 0 and gross > 0 else None}
    out['cost_mix'] = [{'component': k, 'usd': float(trades[f'cost_{k}'].sum()),
                        'share': float(trades[f'cost_{k}'].sum()) / cost if cost > 0 else None,
                        'bp_of_notional': float(trades[f'cost_{k}'].sum()) / notional * 1e4,
                        'mean_bp_per_trade': float((trades[f'cost_{k}'] / trades['notional']).mean() * 1e4)}
                       for k in COST_COMPONENTS]
    have_daily = daily.get('gross') is not None
    if have_daily:
        g, c = daily['gross'], daily['cost']
        out['daily_source'] = daily['source']
        out['cost_curve'] = [{'k': k, **_daily_block(g - k * c), 'trade_net_usd': gross - k * cost}
                             for k in COST_MULTIPLES]
        out['sharpe_breakeven_multiple'] = (float(g.mean() / c.mean())
                                            if g.mean() > 0 and c.mean() > 0 else None)

    # Borrow-fee stress
    short_days = trades['short_notional'] * trades['calendar_days'] / 365.0
    has_short = short_days > 0
    implied = (trades['cost_borrow'][has_short] / short_days[has_short]) if has_short.any() else pd.Series(dtype=float)
    rows = []
    for rate in BORROW_STRESS_RATES:
        extra = (rate * short_days - trades['cost_borrow']).to_numpy()
        row = {'rate': rate, 'borrow_usd': float((rate * short_days).sum()), 'net_usd': net - float(extra.sum()),
               'net_bp_per_trade': float(((trades['net_usd'] - extra) / trades['notional']).mean() * 1e4)}
        if have_daily:
            row.update({k: v for k, v in _daily_block(_scenario_returns(
                daily, _cost_by_day(daily, trades['exit_date'], extra))).items() if k in ('sharpe', 'total_return_pct')})
        rows.append(row)
    out['borrow_stress'] = {'modelled_rate_median': float(implied.median()) if len(implied) else None,
                            'scenarios': rows}

    # Impact coefficient
    base_y = float(model.market_impact_coefficient)
    exact = execs is not None and execs_verified
    base = execution_impact(execs, cost_model=model) if exact else None
    rows = []
    for y in IMPACT_COEFFICIENTS:
        if exact:
            new = execution_impact(execs, coefficient=y, cost_model=model)
            delta_exec = new - base
            per_trade = pd.Series(delta_exec).groupby(execs['trade'].to_numpy()).sum().reindex(trades.index, fill_value=0.0)
            day_usd = _cost_by_day(daily, execs['date'], delta_exec) if have_daily else None
            capped = int((new / (execs['shares'] * execs['price']) * 1e4 >= model.market_impact_cap_bps - 1e-9).sum())
        else:
            per_trade = trades['cost_market_impact'] * (y / base_y - 1.0)
            day_usd = (_cost_by_day(daily, trades['entry_date'], per_trade / 2.0)
                       + _cost_by_day(daily, trades['exit_date'], per_trade / 2.0)) if have_daily else None
            capped = None
        row = {'coefficient': y, 'impact_usd': float(trades['cost_market_impact'].sum() + per_trade.sum()),
               'net_usd': net - float(per_trade.sum()),
               'net_bp_per_trade': float(((trades['net_usd'] - per_trade) / trades['notional']).mean() * 1e4),
               'capped_executions': capped}
        if have_daily:
            row.update({k: v for k, v in _daily_block(_scenario_returns(daily, day_usd)).items()
                        if k in ('sharpe', 'total_return_pct')})
        rows.append(row)
    out['impact_sensitivity'] = {'model_coefficient': base_y, 'cap_bps': float(model.market_impact_cap_bps),
                                 'method': 'repriced per execution' if exact else 'linear in Y (cap ignored)',
                                 'scenarios': rows}
    return out


# ──────────────────────────────────────────────────────────────────────────────
# (b) Implementation shortfall
# ──────────────────────────────────────────────────────────────────────────────

SHORTFALL_STEPS = (('paper', 'Paper P&L at signal closes (unattainable)'),
                   ('entry_delay', 'Entry delay (signal close to fill)'),
                   ('exit_delay', 'Exit delay (exit signal to fill)'),
                   ('gross', 'Gross P&L'),
                   *((k, COST_LABELS[k]) for k in COST_COMPONENTS),
                   ('net', 'Net P&L'))


def implementation_shortfall(trades: pd.DataFrame, panel: PricePanel, reconstruction: Dict,
                             daily: Dict, capital: float) -> Dict:
    """Implementation-shortfall waterfall per trade and in total (Perold 1988; Frazzini,
    Israel & Moskowitz 2018, eqs. 1-6).

    paper        the same shares bought and sold at the SIGNAL-day closes: entry at the
                 signal close, exit at the exit-signal close. Unattainable: those closes
                 are inputs of the decisions they would fill.
    entry delay  the paper position's P&L from the signal close to the entry fill (the
                 move the t+1 fill gives up), q (fill - signal close) per leg
    exit delay   minus the P&L from the exit-signal close to the exit fill (the move the
                 position still carries after its exit is decided)
    gross        paper - entry delay - exit delay: the booked gross P&L
    costs        half-spread, impact, commission, borrow and financing as booked
    net          gross - costs: the booked net P&L

    paper is defined as exported gross + the two delays, so the waterfall closes exactly
    on the exported net; the paper P&L recomputed directly from prices is reported next
    to it. Units: dollars, % of starting capital, bp of total gross notional, and per
    trade the mean bp of the trade's own notional and mean % of equity at the signal.
    """
    if trades.empty:
        return {'steps': [], 'trades': 0}
    cal = panel.calendar
    rec = reconstruction['per_trade']
    rows = []
    for (i, t), (_, r) in zip(trades.iterrows(), rec.iterrows()):
        ks, kxs = cal.get_loc(t['signal_date']), cal.get_loc(t['exit_signal_date'])
        cl, cs = panel.close(t['long_symbol']), panel.close(t['short_symbol'])
        ql, qs = r['q_long'], r['q_short']
        entry = ql * (r['entry_long'] - cl[ks]) - qs * (r['entry_short'] - cs[ks])
        exit_ = -(ql * (r['exit_long'] - cl[kxs]) - qs * (r['exit_short'] - cs[kxs]))
        paper_px = ql * (cl[kxs] - cl[ks]) - qs * (cs[kxs] - cs[ks])
        row = {'trade_id': t['trade_id'], 'paper': t['gross_usd'] + entry + exit_, 'entry_delay': entry,
               'exit_delay': exit_, 'gross': t['gross_usd'], 'net': t['net_usd'], 'paper_from_prices': paper_px}
        row.update({k: t[f'cost_{k}'] for k in COST_COMPONENTS})
        rows.append(row)
    df = pd.DataFrame(rows, index=trades.index)
    eq = pd.Series(daily['equity'], index=daily['dates'])
    equity_at_signal = eq.reindex(trades['signal_date']).to_numpy()
    keys = [k for k, _ in SHORTFALL_STEPS]
    notional = trades['notional'].to_numpy()
    totals = {k: float(df[k].sum()) for k in keys}
    detail = {
        k: {'usd': totals[k], 'pct_of_capital': totals[k] / capital * 100.0,
            'bp_of_notional': totals[k] / notional.sum() * 1e4,
            'mean_bp_per_trade': float((df[k].to_numpy() / notional).mean() * 1e4),
            'mean_pct_of_equity_per_trade': float(np.nanmean(df[k].to_numpy() / equity_at_signal) * 100.0)}
        for k in keys}
    # Bars for the waterfall exhibit, in integer cents so every bar starts where the
    # previous one ended and the last one ends on the net P&L.
    cents = {k: int(round(totals[k] * 100)) for k in ('entry_delay', 'exit_delay', 'net', *COST_COMPONENTS)}
    cents['gross'] = cents['net'] + sum(cents[k] for k in COST_COMPONENTS)
    cents['paper'] = cents['gross'] + cents['entry_delay'] + cents['exit_delay']
    steps, level = [], 0
    for key, label in SHORTFALL_STEPS:
        if key in ('paper', 'gross', 'net'):
            level = cents[key]
            steps.append({'key': key, 'step': label, 'usd': level / 100, 'start': 0.0, 'end': level / 100})
        else:
            steps.append({'key': key, 'step': label, 'usd': -cents[key] / 100, 'start': level / 100,
                          'end': (level - cents[key]) / 100})
            level -= cents[key]
    per_trade = [{'trade_id': int(r.trade_id), **{f'{k}_bp': float(getattr(r, k) / n * 1e4) for k in keys}}
                 for r, n in zip(df.itertuples(index=False), notional)]
    return {
        'trades': int(len(df)), 'steps': steps, 'totals': detail,
        'paper_from_prices_usd': float(df['paper_from_prices'].sum()),
        'paper_from_prices_max_abs_diff_usd': float((df['paper_from_prices'] - df['paper']).abs().max()),
        'delay_bp_by_exit_reason': {
            reason: {'trades': int(len(g)), 'entry_delay_bp': float((g['entry_delay'] / trades.loc[g.index, 'notional']).mean() * 1e4),
                     'exit_delay_bp': float((g['exit_delay'] / trades.loc[g.index, 'notional']).mean() * 1e4)}
            for reason, g in df.groupby(trades['exit_reason'])},
        'per_trade': per_trade,
    }


# ──────────────────────────────────────────────────────────────────────────────
# (c) Exit race
# ──────────────────────────────────────────────────────────────────────────────

def _reference_window(half_life: float) -> int:
    """The engine's z reference window for a half-life, with every W >= 60 bars (which give
    the same z: TradingSystem._locked_signal uses the last 60 bars of the window) as 60."""
    w = max(Engine.REF_MIN, min(int(float(half_life) * Engine.REF_HL_MULT), Engine.REF_MAX))
    return min(w, Engine.REF_STATS_BARS)


def signal_windows(trades: pd.DataFrame, panel: PricePanel,
                   formation_half_life: Optional[pd.Series] = None) -> pd.DataFrame:
    """The reference window behind each trade's exported z-score, and the spread's daily
    volatility in z units.

    The engine's signal (TradingSystem._locked_signal) is z = (lk_t - m) / sd on the
    beta-locked spread lk = log p1 - beta log p2 over the trailing W = clamp(int(3 x
    half-life), 30, 90) pair bars, with m and sd over its last min(W, 60) bars, frozen for
    the life of the trade. W depends on the half-life in force at the signal, which the
    export does not carry; it is recovered as a W whose z reproduces the exported z to
    Z_MATCH_TOLERANCE (z has 3 decimals in the export, beta 4). Every W >= 60 gives the
    same z (reported as 60), so the window identifies the half-life only below 60 bars.
    When several windows match, the one the pair's formation half-life implies is taken
    if it is among them, else the closest match; 'candidates' counts the matches. After
    the signal z moves by the spread's daily change over the frozen sd, so its per-day
    volatility in z units is sd(daily changes of lk) / sd(lk) over the reference bars.
    """
    rows = []
    for i_t, t in zip(trades.index, trades.itertuples(index=False)):
        idx, lp1, lp2 = panel.pair_log_prices(t.symbol1, t.symbol2)
        i = idx.get_loc(t.signal_date)
        fits = {}
        for w in range(Engine.REF_MIN, Engine.REF_STATS_BARS + 1):
            lk = lp1[max(0, i - w + 1):i + 1] - t.hedge_ratio * lp2[max(0, i - w + 1):i + 1]
            ref = lk[-min(Engine.REF_STATS_BARS, len(lk)):]
            sd = ref.std()
            if sd > 0:
                fits[w] = (abs((lk[-1] - ref.mean()) / sd - t.zscore), float(np.diff(ref).std() / sd))
        matches = [w for w, (err, _) in fits.items() if err <= Z_MATCH_TOLERANCE]
        prior = (_reference_window(formation_half_life.loc[i_t])
                 if formation_half_life is not None and np.isfinite(formation_half_life.loc[i_t]) else None)
        if prior in matches:
            w = prior
        elif fits:
            w = min(fits, key=lambda k: (fits[k][0], k))
        else:
            w = None
        err, sigma = fits[w] if w is not None else (float('inf'), float('nan'))
        rows.append({'trade_id': t.trade_id, 'window': w, 'z_error': err, 'sigma_z': sigma,
                     'matched': bool(err <= Z_MATCH_TOLERANCE), 'candidates': len(matches)})
    return pd.DataFrame(rows, index=trades.index)


def half_life_at_signal(window: Optional[int], formation_half_life: float) -> float:
    """The half-life consistent with the reference window W = clamp(int(3 hl), 30, 90).

    Below 60 bars W pins int(3 hl) (the window's midpoint hl = (W + 0.5) / 3 is used);
    W >= 60 means hl >= 20; W = 30 means hl < 31/3. Within those bounds, and when the
    window is unknown, the pair's formation half-life is used.
    """
    hl = float(formation_half_life)
    if window is None:
        return hl
    if window >= Engine.REF_STATS_BARS:
        return max(hl, Engine.REF_STATS_BARS / Engine.REF_HL_MULT)
    if window > Engine.REF_MIN:
        return (window + 0.5) / Engine.REF_HL_MULT
    return min(hl, (Engine.REF_MIN + 1) / Engine.REF_HL_MULT - 1e-9)


def gamblers_ruin_target_probability(z0: float, exit_z: float = Engine.EXIT_Z,
                                     stop_z: float = Engine.STOP_Z) -> float:
    """P(profit target before stop-loss) for a driftless random walk started at |z| = z0.

    The target is z0 - exit_z away and the stop stop_z away on the other side; for a
    continuous martingale the probability of reaching a before -b is b / (a + b)
    (gambler's ruin), so P = stop_z / (z0 - exit_z + stop_z): 1.5 / 2.8 = 0.536 at the
    entry threshold 1.8, independent of the spread's volatility, without a time stop.
    """
    return float(stop_z / (z0 - exit_z + stop_z))


def simulate_exit_race(z0: float, sigma: float, max_hold: int, phi: float = 1.0,
                       n_paths: int = EXIT_RACE_PATHS, rng: Optional[np.random.Generator] = None,
                       exit_z: float = Engine.EXIT_Z, stop_z: float = Engine.STOP_Z) -> Dict:
    """Exit shares of the engine's rule on simulated spreads started at |z| = z0.

    Days count from the signal close: the entry fills on day 1 and the exit rule is
    tested on days 2 .. max_hold + 1 (TradingSystem._scan_exit starts on the first bar
    after the entry fill and fires the time stop on its max_hold-th test; the target is
    tested before the stop on the same day). The z of the trade's side, oriented so that
    reversion is falling, follows z_d = phi z_{d-1} + sigma eps_d against the frozen
    reference: phi = 1 is a driftless random walk with daily volatility sigma (z units),
    phi = 2^(-1/HL) an OU spread with half-life HL reverting to the reference mean.
    """
    rng = rng if rng is not None else np.random.default_rng(0)
    steps = int(max_hold) + 1
    eps = rng.standard_normal((n_paths, steps))
    z = np.empty((n_paths, steps))
    level = np.full(n_paths, float(z0))
    for d in range(steps):
        level = phi * level + sigma * eps[:, d]
        z[:, d] = level
    tests = z[:, 1:]                                  # days 2 .. max_hold + 1
    target, stop = tests < exit_z, tests > z0 + stop_z
    hit = target | stop
    any_hit = hit.any(axis=1)
    first = hit.argmax(axis=1)
    tgt = any_hit & target[np.arange(n_paths), first]
    n_hit = int(any_hit.sum())
    return {'target': float(tgt.mean()), 'stop': float((any_hit & ~tgt).mean()),
            'time': float(1.0 - any_hit.mean()),
            'target_given_barrier': float(tgt.sum() / n_hit) if n_hit else float('nan')}


def _race_test(observed: int, p: np.ndarray) -> Dict:
    """Observed targets against independent Bernoulli(p_i) trades: expected count and z."""
    p = np.asarray(p, dtype=float)
    expected, var = float(p.sum()), float((p * (1.0 - p)).sum())
    z = (observed - expected) / np.sqrt(var) if var > 0 else None
    return {'expected_targets': expected, 'expected_share': expected / p.size if p.size else None,
            'z': _f(z), 'p_two_sided': _f(2.0 * sps.norm.sf(abs(z))) if z is not None else None,
            'p_more_targets': _f(sps.norm.sf(z)) if z is not None else None}


def exit_race(trades: pd.DataFrame, windows: pd.DataFrame, formation_half_life: pd.Series,
              engine: Engine, n_paths: int = EXIT_RACE_PATHS, seed: int = 0) -> Dict:
    """Profit-target vs stop-loss exits among barrier exits, against no-mean-reversion nulls.

    For each trade that exited at the target or the stop: z0 = |z| at the signal, sigma =
    its spread's daily volatility in z units (signal_windows), the time stop
    clamp(2.5 x half-life, 10, 25) at the half-life in force at the signal
    (half_life_at_signal) and the pair's formation half-life. Nulls, each giving the
    probability p_i that the trade's barrier exit is the target:
      random_walk   the rule on a driftless random walk with the trade's sigma and time
                    stop (simulated): the spread does not mean-revert at all
      gamblers_ruin the same without the time stop, in closed form (a check on the
                    simulation: p_i = 1.5 / (z0 - 0.5 + 1.5))
      ou            an OU spread with the pair's formation half-life (what the selection
                    promised)
    The observed target count is compared with sum p_i, variance sum p_i (1 - p_i)
    (independent trades): z > 0 means more targets than the null, as mean reversion
    would produce.
    """
    barrier = trades['exit_reason'].isin(['target', 'stop'])
    b = trades[barrier]
    out = {'targets': int((b['exit_reason'] == 'target').sum()), 'stops': int((b['exit_reason'] == 'stop').sum()),
           'barrier_exits': int(len(b)), 'other_exits': int((~barrier).sum())}
    if b.empty:
        return out
    rng = np.random.default_rng(seed)
    fallback_sigma = float(windows.loc[windows['matched'], 'sigma_z'].median()) if windows['matched'].any() else 0.3
    p_rw, p_gr, p_ou, holds = [], [], [], []
    for i, t in b.iterrows():
        w = windows.loc[i]
        hl_form = float(formation_half_life.loc[i])
        hold = engine._max_hold_days({'half_life': half_life_at_signal(w['window'] if w['matched'] else None, hl_form)})
        sigma = float(w['sigma_z']) if w['matched'] and np.isfinite(w['sigma_z']) else fallback_sigma
        holds.append(hold)
        p_gr.append(gamblers_ruin_target_probability(t['abs_z']))
        phi = 2.0 ** (-1.0 / hl_form) if hl_form > 0 else 1.0
        for p_list, coef in ((p_rw, 1.0), (p_ou, phi)):
            p = simulate_exit_race(t['abs_z'], sigma, hold, coef, n_paths, rng)['target_given_barrier']
            p_list.append(p if np.isfinite(p) else p_gr[-1])      # no simulated path reached a barrier
    observed = out['targets']
    rw = _race_test(observed, p_rw)
    out.update({
        'observed_share': observed / len(b),
        'expected_targets': rw['expected_targets'], 'z': rw['z'],
        'nulls': {'random_walk': rw, 'gamblers_ruin': _race_test(observed, p_gr), 'ou': _race_test(observed, p_ou)},
        'inputs': {'mean_abs_z': float(b['abs_z'].mean()), 'median_sigma_z': float(windows.loc[b.index, 'sigma_z'].median()),
                   'median_time_stop': float(np.median(holds)),
                   'median_formation_half_life': float(formation_half_life.loc[b.index].median()),
                   'z_windows_matched': int(windows.loc[b.index, 'matched'].sum()),
                   'z_windows_ambiguous': int((windows.loc[b.index, 'candidates'] > 1).sum()),
                   'paths_per_trade': int(n_paths),
                   'seed': int(seed)},
    })
    return out


# ──────────────────────────────────────────────────────────────────────────────
# (d) Cointegration persistence (Clegg 2014) and the traded pairs' half-lives
# ──────────────────────────────────────────────────────────────────────────────

def liquid_universe(prices: Dict[str, pd.DataFrame], cutoff, selector: Optional[FixedPrimeFundPairSelector] = None) -> List[str]:
    """The pair selector's symbol screen on data dated <= cutoff: its most liquid names.

    The rules of FixedPrimeFundPairSelector.find_quality_pairs: >= 300 bars, mean point-
    in-time price >= $5, mean point-in-time dollar volume >= min_dollar_volume,
    annualised volatility in (5%, 80%), < 10% missing closes; the max_universe largest
    by dollar volume (ties by symbol). tests/test_anatomy.py checks that it returns the
    selector's own universe.
    """
    sel = selector or FixedPrimeFundPairSelector()
    cut = _day(cutoff)
    screened = []
    for sym in sorted(prices):
        data = _naive(prices[sym])
        data = data[data.index <= cut]
        if len(data) < 300:
            continue
        price = data['Close_PIT'] if 'Close_PIT' in data.columns else data['Close']
        shares = data['Volume_PIT'] if 'Volume_PIT' in data.columns else data['Volume']
        if price.mean() < 5.0:
            continue
        dollar_volume = float((price * shares).mean())
        if not np.isfinite(dollar_volume) or dollar_volume < sel.min_dollar_volume:
            continue
        if not 0.05 < data['Returns'].std() * np.sqrt(252) < 0.8:
            continue
        if data['Close'].isnull().sum() / len(data) >= 0.10:
            continue
        screened.append((sym, dollar_volume))
    screened.sort(key=lambda kv: (-kv[1], kv[0]))
    return sorted(sym for sym, _ in screened[:sel.max_universe])


def _persistence_selector() -> FixedPrimeFundPairSelector:
    sel = FixedPrimeFundPairSelector()
    sel.min_common_days = PERSISTENCE_MIN_DAYS
    return sel


def _test_pairs(frames: Dict[str, pd.DataFrame], pairs: List[Tuple[str, str]], screen: bool) -> List[Tuple]:
    """(correlation, p) per pair on one window, with the selector's own tests.

    With `screen`, p is computed only for pairs whose return correlation passes the
    selector's threshold (correlation_threshold); without it, for every pair. p is the
    two-direction Bonferroni Engle-Granger p-value (test_cointegration), None when the
    pair has fewer than PERSISTENCE_MIN_DAYS common days or was screened out.
    """
    sel = _persistence_selector()
    out = []
    for s1, s2 in pairs:
        d1, d2 = frames.get(s1), frames.get(s2)
        if d1 is None or d2 is None:
            out.append((None, None))
            continue
        corr = sel.calculate_correlation(d1, d2) if screen else None
        if screen and corr < sel.correlation_threshold:
            out.append((corr, None))
            continue
        n = len(sel._aligned_log_prices(d1, d2)[0])
        out.append((corr, sel.test_cointegration(d1, d2)[1] if n >= sel.min_common_days else None))
    return out


def _run_tests(frames, pairs, screen, n_jobs, chunk=1500):
    tasks = [pairs[i:i + chunk] for i in range(0, len(pairs), chunk)]
    if n_jobs > 1 and len(tasks) > 1:
        parts = Parallel(n_jobs=n_jobs)(delayed(_test_pairs)(frames, task, screen) for task in tasks)
    else:
        parts = [_test_pairs(frames, task, screen) for task in tasks]
    return [r for part in parts for r in part]


def _share(k: int, n: int, alpha: float) -> Dict:
    """Share k/n with its Clopper-Pearson 95% interval and the binomial test against alpha."""
    if n == 0:
        return {'count': 0, 'of': 0, 'share': None, 'ci95': [None, None], 'binom_p_vs_chance': None}
    test = sps.binomtest(int(k), int(n), alpha)
    ci = test.proportion_ci(confidence_level=0.95, method='exact')
    return {'count': int(k), 'of': int(n), 'share': k / n, 'ci95': [float(ci.low), float(ci.high)],
            'binom_p_vs_chance': float(test.pvalue)}


def _against_base_rate(k: int, n: int, base: Optional[float]) -> Optional[float]:
    """Two-sided binomial p of k successes in n trials against the rate `base`."""
    if not n or base is None or not 0.0 < base < 1.0:
        return None
    return float(sps.binomtest(int(k), int(n), base).pvalue)


def cointegration_persistence(prices: Dict[str, pd.DataFrame], symbols: Sequence[str],
                              years: Sequence[int] = PERSISTENCE_YEARS, alpha: float = PERSISTENCE_ALPHA,
                              n_jobs: int = 1) -> Dict:
    """Clegg (2014) persistence of cointegration, year by year.

    For each calendar year Y of `years` and the year after the last: every pair of
    `symbols` whose daily return correlation in that year passes the selector's screen
    (>= 0.25) is tested for cointegration on the year's log prices with the study's own
    test, PairSelector.cointegration_pvalue (two-direction Engle-Granger, Bonferroni p =
    min(1, 2 min(p12, p21))); the share with p < alpha is the year's base rate. For each
    Y of `years`, among the pairs with p < alpha in Y: the share still p < alpha in Y + 1
    (pairs without PERSISTENCE_MIN_DAYS common days in Y + 1, e.g. a delisted leg, are
    counted apart), with a Clopper-Pearson interval and binomial tests against alpha and
    against Y + 1's base rate.

    Two references, because alpha is only the nominal chance rate: MacKinnon's p-values
    with AIC lag selection are slightly liberal in a year of data, and the Bonferroni
    combination does not bring the size back under alpha (on 6,000 pairs of independent
    250-day Gaussian random walks the test rejects 5.7%, standard error 0.3%). The base
    rate of Y + 1 is the model-free reference: if being cointegrated in Y carried no
    information about Y + 1, the conditional share would equal it. Pairs share legs, so
    the binomial intervals overstate the precision. Clegg (2014), on pairs of S&P 500
    constituents in each year of 2002-2012, finds that the evidence does not support
    cointegration as a persistent property (the abstract; its per-year percentages were
    not checked against the paper).
    """
    symbols = sorted(symbols)
    threshold = _persistence_selector().correlation_threshold
    pairs = [(a, b) for i, a in enumerate(symbols) for b in symbols[i + 1:]]
    naive = {s: _naive(prices[s])[['Close', 'Returns']] for s in symbols}

    def year_frames(y):
        lo, hi = pd.Timestamp(f'{y}-01-01'), pd.Timestamp(f'{y}-12-31')
        return {s: df[(df.index >= lo) & (df.index <= hi)] for s, df in naive.items()}

    screened = {y: _run_tests(year_frames(y), pairs, True, n_jobs) for y in sorted({*years, max(years) + 1})}
    tested = {y: [(pair, p) for pair, (_, p) in zip(pairs, res) if p is not None] for y, res in screened.items()}
    base = {y: _share(sum(p < alpha for _, p in t), len(t), alpha) for y, t in tested.items()}
    rows = []
    for y in years:
        sig = [pair for pair, p in tested[y] if p < alpha]
        nxt = _run_tests(year_frames(y + 1), sig, False, n_jobs) if sig else []
        testable = [p for _, p in nxt if p is not None]
        k = sum(p < alpha for p in testable)
        logger.info(f"Persistence {y}: {len(sig)}/{len(tested[y])} correlated pairs cointegrated, "
                    f"{k}/{len(testable)} still in {y + 1} (base rate {y + 1}: {base[y + 1]['share']})")
        rows.append({'year': int(y), 'next_year': int(y + 1),
                     'correlated_pairs': int(sum(1 for c, _ in screened[y] if c is not None and c >= threshold)),
                     'cointegrated': base[y],
                     'still_cointegrated_next_year': {
                         **_share(k, len(testable), alpha),
                         'next_year_base_rate': base[y + 1]['share'],
                         'binom_p_vs_next_year_base_rate': _against_base_rate(k, len(testable), base[y + 1]['share'])},
                     'untestable_next_year': int(len(nxt) - len(testable))})
    return {'schema': PERSISTENCE_SCHEMA, 'symbols': len(symbols), 'pairs': len(pairs), 'alpha': alpha,
            'test': 'two-direction Engle-Granger, Bonferroni p = min(1, 2 min(p12, p21)) (PairSelector.cointegration_pvalue)',
            'correlation_screen': threshold, 'min_common_days': PERSISTENCE_MIN_DAYS, 'years': rows,
            'base_rates': [{'year': int(y), **b} for y, b in base.items()],
            'pooled_still_cointegrated': _pooled_persistence([r['still_cointegrated_next_year'] for r in rows], alpha)}


def _pooled_persistence(still: List[Dict], alpha: float) -> Dict:
    """The years' 'still cointegrated' counts pooled: the share against alpha, and the count
    against the next-year base rates (expected sum n_Y b_{Y+1}, variance sum n_Y b (1 - b),
    independent pairs)."""
    k, n = sum(s['count'] for s in still), sum(s['of'] for s in still)
    rates = [(s['of'], s['next_year_base_rate']) for s in still if s['of'] and s['next_year_base_rate'] is not None]
    expected = float(sum(m * b for m, b in rates))
    var = float(sum(m * b * (1.0 - b) for m, b in rates))
    return {**_share(k, n, alpha), 'expected_at_next_year_base_rates': expected,
            'z_vs_next_year_base_rates': _f((k - expected) / np.sqrt(var)) if var > 0 else None}


def _window_stats(sel: FixedPrimeFundPairSelector, d1: pd.DataFrame, d2: pd.DataFrame) -> Dict:
    """Common days, Bonferroni Engle-Granger p and the AR(1) half-life (raw and Kendall)."""
    lp1, lp2 = sel._aligned_log_prices(d1, d2)
    n = len(lp1)
    p = sel.cointegration_pvalue(lp1, lp2) if n >= PERSISTENCE_MIN_DAYS else None
    phi, n_ar = sel.spread_ar1(d1, d2)
    return {'days': int(n), 'p': _f(p), **kendall_half_life(phi, n_ar)}


def _half_lives(values) -> List[Optional[float]]:
    """Half-lives with 'no mean reversion' (None or NaN) as None."""
    return [None if v is None or not np.isfinite(v) else float(v) for v in values]


def _median_half_life(values) -> Optional[float]:
    """Median half-life counting 'no mean reversion' (None) as infinitely slow."""
    x = np.array([np.inf if v is None else v for v in _half_lives(values)], dtype=float)
    if not x.size:
        return None
    return _f(np.median(x))


def traded_pair_stats(pairs: pd.DataFrame, panel: PricePanel) -> pd.DataFrame:
    """Formation and out-of-sample p-value and half-life of each traded pair (pair_windows)."""
    sel = FixedPrimeFundPairSelector()
    rows = []
    for r in pairs.itertuples(index=False):
        form = _window_stats(sel, panel.window(r.symbol1, r.formation_start, r.formation_end),
                             panel.window(r.symbol2, r.formation_start, r.formation_end))
        oos = _window_stats(sel, panel.window(r.symbol1, r.oos_start, r.oos_end),
                            panel.window(r.symbol2, r.oos_start, r.oos_end))
        rows.append({'pair': r.pair, **{f'formation_{k}': v for k, v in form.items()},
                     **{f'oos_{k}': v for k, v in oos.items()},
                     'formation_half_life_selector': sel.calculate_half_life(
                         panel.window(r.symbol1, r.formation_start, r.formation_end),
                         panel.window(r.symbol2, r.formation_start, r.formation_end))})
    return pd.DataFrame(rows, index=pairs.index)


def traded_pair_persistence(pairs: pd.DataFrame, stats: pd.DataFrame, max_half_life: float,
                            alpha: float = PERSISTENCE_ALPHA) -> Dict:
    """Summary of traded_pair_stats: how many traded pairs were cointegrated in their
    formation window and still are out of sample, and how their half-lives drift."""
    out = {'pairs': int(len(pairs)), 'alpha': alpha}
    for when in ('formation', 'oos'):
        p = stats[f'{when}_p']
        testable = p.notna()
        hl, hl_c = _half_lives(stats[f'{when}_half_life']), _half_lives(stats[f'{when}_half_life_kendall'])
        out[when] = {
            'cointegrated': _share(int((p[testable] < alpha).sum()), int(testable.sum()), alpha),
            'median_p': _f(p[testable].median()) if testable.any() else None,
            'median_half_life': _median_half_life(hl), 'median_half_life_kendall': _median_half_life(hl_c),
            'share_no_mean_reversion': float(np.mean([v is None for v in hl])),
            'share_half_life_above_max': float(np.mean([v is None or v > max_half_life for v in hl])),
            'share_half_life_kendall_above_max': float(np.mean([v is None or v > max_half_life for v in hl_c])),
        }
    out['max_half_life'] = max_half_life
    out['per_pair'] = [{'pair': r['pair'], 'trades': int(t),
                        **{k: _f(r[k]) if not isinstance(r[k], (int, np.integer)) else int(r[k])
                           for k in ('formation_p', 'formation_half_life', 'formation_half_life_kendall',
                                     'formation_n', 'oos_p', 'oos_half_life', 'oos_half_life_kendall', 'oos_n')}}
                       for (_, r), t in zip(stats.iterrows(), pairs['trades'])]
    return out


# ──────────────────────────────────────────────────────────────────────────────
# In-sample -> out-of-sample decay of the same rule on the same pairs
# ──────────────────────────────────────────────────────────────────────────────

def rule_trades(engine: Engine, s1: str, s2: str, half_life: float, start, end) -> List[Dict]:
    """The engine's rule on one pair, one position at a time, for signals in [start, end].

    The engine's own signal and exit functions (_locked_signal, _scan_exit,
    _max_hold_days, _rolling_corr_ok, the hedge-ratio band and the minimum history) on
    the pair's Kalman state, with `half_life` fixed throughout; no portfolio, regime,
    quality or cool-off gates. Shares are fixed from the signal-day close ($1 of leg 1 :
    $beta of leg 2 per $(1 + beta) of gross notional) and fill at the next pair bar's close
    on entry and exit, as in the engine, which can open the next position on the
    exit-fill day. Returns per trade the signal date, |z|, exit reason and the gross
    return per $ of gross notional.
    """
    state = engine.get_pair_state(s1, s2)
    if state.empty:
        return []
    idx = pd.DatetimeIndex(state.index)
    idx = idx.tz_localize(None) if idx.tz is not None else idx
    lp1, lp2, beta_arr = (state[c].to_numpy() for c in ('lp1', 'lp2', 'beta'))
    p1, p2 = np.exp(lp1), np.exp(lp2)
    stats = {'half_life': float(half_life)}
    max_hold = engine._max_hold_days(stats)
    i = max(int(idx.searchsorted(_day(start))), engine.MIN_SPREAD_HISTORY - 1)
    last = int(idx.searchsorted(_day(end), side='right')) - 1
    out = []
    while i <= last and i + 2 < len(state):
        beta = float(beta_arr[i])
        if not (engine.BETA_MIN <= beta <= engine.BETA_MAX) or not engine._rolling_corr_ok(state, i):
            i += 1
            continue
        sig, _ = engine._locked_signal(state, i, stats)
        if sig is None or abs(sig['z']) < engine.ENTRY_Z:
            i += 1
            continue
        action = 0 if sig['z'] < 0 else 2
        e = i + 1
        rows = list(range(e + 1, min(e + 1 + max_hold, len(state))))
        j, reason = engine._scan_exit(lp1, lp2, rows, sig, action, max_hold)
        if j is None or rows[j] + 1 >= len(state):
            break
        x = rows[j] + 1
        sign = 1.0 if action == 0 else -1.0
        n1, n2 = 1.0 / (1.0 + beta), beta / (1.0 + beta)
        ret = sign * (n1 * (p1[x] - p1[e]) / p1[i] - n2 * (p2[x] - p2[e]) / p2[i])
        out.append({'signal_date': idx[i], 'abs_z': abs(float(sig['z'])), 'reason': reason, 'gross_return': float(ret)})
        i = x
    return out


def _decay_row(label: str, bp: np.ndarray, months) -> Dict:
    s = _mean_t(bp)
    half = 1.96 * s['sd'] / np.sqrt(s['n']) if s['sd'] else None
    return {'period': label, 'n': s['n'], 'bp': s['mean'], 'lo': s['mean'] - half if half is not None else None,
            'hi': s['mean'] + half if half is not None else None, 't': s['t'],
            't_month_clustered': _clustered_t(bp, months) if s['n'] else None}


def decay(trades: pd.DataFrame, pairs: pd.DataFrame, formation_half_life: pd.Series, engine: Engine) -> Dict:
    """Gross bp per trade of the same rule on the same traded pairs, in sample and out.

    For every pair the engine traded: rule_trades in its formation window (the data the
    pair was selected on: in sample) and in its out-of-sample window, at its formation
    half-life; next to the engine's own trades. 95% intervals are iid (mean +- 1.96 se);
    t_month_clustered clusters trades by signal month. A selection that found genuine
    mean reversion keeps most of its in-sample edge out of sample.
    """
    sims = {'formation': [], 'oos': []}
    for r, hl in zip(pairs.itertuples(index=False), formation_half_life):
        sims['formation'] += rule_trades(engine, r.symbol1, r.symbol2, hl, r.formation_start, r.formation_end)
        sims['oos'] += rule_trades(engine, r.symbol1, r.symbol2, hl, r.oos_start, r.oos_end)

    def months(dates):
        return [pd.Timestamp(d).strftime('%Y-%m') for d in dates]

    span = {k: [str(pairs[f'{k}_start'].min().date()), str(pairs[f'{k}_end'].max().date())]
            for k in ('formation', 'oos')}
    span['engine'] = [str(trades['signal_date'].min().date()), str(trades['signal_date'].max().date())]
    label = {'formation': 'Formation (in sample), same rule', 'oos': 'Out of sample, same rule'}
    rows = [{**_decay_row(label[k], np.array([s['gross_return'] for s in sims[k]]) * 1e4,
                          months(s['signal_date'] for s in sims[k])), 'span': span[k]} for k in ('formation', 'oos')]
    rows.append({**_decay_row('Engine trades', trades['gross_bp'].to_numpy(), months(trades['signal_date'])),
                 'span': span['engine']})
    exits = {k: {r: int(sum(s['reason'] == r for s in sims[k])) for r in ('target', 'stop', 'time')} for k in sims}
    return {'rows': rows, 'exit_reasons': exits, 'pairs': int(len(pairs))}


# ──────────────────────────────────────────────────────────────────────────────
# (e) Breakdowns, concentration and exposure
# ──────────────────────────────────────────────────────────────────────────────

def group_table(trades: pd.DataFrame, key: pd.Series, order: Sequence[str], capital: float) -> List[Dict]:
    """Per-group trade statistics: count, gross/cost/net bp, net dollars and win rates."""
    rows = []
    for k in order:
        g = trades[key == k]
        if g.empty:
            continue
        gb = _mean_t(g['gross_bp'])
        rows.append({'group': k, 'trades': int(len(g)), 'gross_bp': gb['mean'], 'gross_t': gb['t'],
                     'cost_bp': float(g['cost_bp'].mean()), 'net_bp': float(g['net_bp'].mean()),
                     'gross_usd': float(g['gross_usd'].sum()), 'net_usd': float(g['net_usd'].sum()),
                     'net_pct_of_capital': float(g['net_usd'].sum() / capital * 100.0),
                     'net_win_rate': float((g['net_usd'] > 0).mean()),
                     'gross_win_rate': float((g['gross_usd'] > 0).mean())})
    return rows


def calendar_breakdown(daily: Dict) -> Dict:
    """Daily-series return, Sharpe and net dollars per calendar year, and per month."""
    df = pd.DataFrame({'r': daily['net'], 'usd': daily['net_usd']}, index=daily['dates'])
    years = [{'year': int(y), 'days': int(len(g)), 'return_pct': float((np.prod(1 + g['r']) - 1) * 100),
              'sharpe': annualized_sharpe(g['r'].to_numpy(), TRADING_DAYS_PER_YEAR), 'net_usd': float(g['usd'].sum())}
             for y, g in df.groupby(df.index.year)]
    months = [{'month': f'{p}', 'days': int(len(g)), 'return_pct': float((np.prod(1 + g['r']) - 1) * 100),
               'net_usd': float(g['usd'].sum())}
              for p, g in df.groupby(df.index.to_period('M'))]
    return {'years': years, 'months': months}


def concentration(trades: pd.DataFrame, months: List[Dict], results: Dict) -> Dict:
    """How much of the result one month, one walk-forward window or a few pairs carry.

    Shares are signed ratios to the period total (a month that earned more than the
    whole period has a share above 1, or a negative one when the total is a loss).
    """
    out: Dict = {}
    if months:
        total = float(sum(m['net_usd'] for m in months))
        positive = float(sum(m['net_usd'] for m in months if m['net_usd'] > 0))
        best = max(months, key=lambda m: m['net_usd'])
        worst = min(months, key=lambda m: m['net_usd'])
        out['months'] = {
            'total_net_usd': total,
            'best': {**best, 'share_of_total': best['net_usd'] / total if total else None,
                     'share_of_positive_months': best['net_usd'] / positive if positive else None},
            'worst': {**worst, 'share_of_total': worst['net_usd'] / total if total else None},
            'total_excluding_best_usd': total - best['net_usd'],
        }
    wf = results.get('walk_forward_validation') or {}
    windows = [w for w in wf.get('windows') or [] if w.get('total_return_pct') is not None]
    if windows:
        stitched = wf.get('stitched_total_return_pct')
        best = max(windows, key=lambda w: w['total_return_pct'])
        worst = min(windows, key=lambda w: w['total_return_pct'])

        def share(w):
            return w['total_return_pct'] / stitched if stitched else None

        out['walk_forward'] = {
            'windows': len(windows), 'stitched_total_return_pct': stitched,
            'best': {'window': best.get('window'), 'return_pct': best['total_return_pct'], 'share_of_total': share(best)},
            'worst': {'window': worst.get('window'), 'return_pct': worst['total_return_pct'], 'share_of_total': share(worst)},
        }
    if not trades.empty:
        by_pair = trades.groupby('pair')['net_usd'].sum().sort_values()
        out['pairs'] = {'traded': int(len(by_pair)), 'trades_per_pair_max': int(trades['pair'].value_counts().max()),
                        'net_usd_total': float(by_pair.sum()),
                        'net_usd_top5': float(by_pair.tail(5).sum()), 'net_usd_bottom5': float(by_pair.head(5).sum()),
                        'net_usd_excluding_top5_and_bottom5': float(by_pair.iloc[5:-5].sum()) if len(by_pair) > 10 else None}
    return out


def market_proxy_returns(sectors: Dict[str, pd.Series]) -> pd.Series:
    """Equal-weight daily return of the sector SPDR ETFs (the engine's market proxy in
    TradingSystem._factor_attribution), on a tz-naive index."""
    rets = pd.DataFrame({k: v.pct_change(fill_method=None) for k, v in sectors.items() if len(v) > 10})
    m = rets.mean(axis=1).dropna()
    m.index = pd.DatetimeIndex(m.index).tz_localize(None) if pd.DatetimeIndex(m.index).tz is not None else pd.DatetimeIndex(m.index)
    return m


def market_exposure(trades: pd.DataFrame, panel: PricePanel, market: Optional[pd.Series]) -> Dict:
    """Hedge ratios and each trade's net dollar and implied market-beta exposure.

    Per $ of gross notional the engine holds $1/(1+beta) of leg 1 and $beta/(1+beta) of
    leg 2, long leg 1 for a LONG spread: the net dollar exposure (long notional - short
    notional) / gross is (1 - beta)/(1 + beta) for a long spread and -(1 - beta)/(1 + beta)
    for a short one, zero only at beta = 1. With b_L, b_S the legs' market betas (OLS of
    daily returns on the market proxy over the MARKET_BETA_DAYS days to the signal date)
    and L, S the leg notionals at the entry fill, the implied net market beta per $ of
    gross is (L b_L - S b_S) / (L + S), and the trade's market P&L is (L b_L - S b_S) x
    the proxy's compounded return from the entry fill to the exit fill. Gross P&L ex market
    is the rest; 'market_share_of_gross_variance' is 1 - var(ex market) / var(gross).
    """
    if trades.empty:
        return {}
    beta = trades['hedge_ratio']
    side = np.where(trades['action'] == 'LONG', 1.0, -1.0)
    net_dollar = (trades['long_notional'] - trades['short_notional']) / (trades['long_notional'] + trades['short_notional'])
    out = {
        'hedge_ratio': {'mean': float(beta.mean()), 'share_below_1': float((beta < 1).mean()),
                        **{f'p{q}': float(beta.quantile(q / 100)) for q in (10, 25, 50, 75, 90)}},
        'net_dollar_per_gross': {'mean': float(net_dollar.mean()), 'mean_abs': float(net_dollar.abs().mean()),
                                 'implied_by_hedge_ratio_mean': float((side * (1 - beta) / (1 + beta)).mean()),
                                 'by_side': {s: float(net_dollar[trades['action'] == s].mean())
                                             for s in SIDES if (trades['action'] == s).any()}},
    }
    if market is None or market.empty:
        return out
    mret = market.sort_index()
    rows = []
    for t in trades.itertuples(index=False):
        b = {}
        for sym in (t.long_symbol, t.short_symbol):
            close = panel.frame(sym)['Close']
            r = close.where(close > 0).pct_change(fill_method=None)
            r = r[r.index <= t.signal_date].dropna().tail(MARKET_BETA_DAYS)
            m = mret.reindex(r.index)
            ok = m.notna().to_numpy()
            x, y = m.to_numpy()[ok], r.to_numpy()[ok]
            b[sym] = float(np.cov(y, x)[0, 1] / x.var(ddof=1)) if x.size > 20 and x.var() > 0 else float('nan')
        exposure = t.long_notional * b[t.long_symbol] - t.short_notional * b[t.short_symbol]
        hold = mret[(mret.index > t.entry_date) & (mret.index <= t.exit_date)]
        market_usd = exposure * float(np.prod(1.0 + hold.to_numpy()) - 1.0)
        rows.append({'net_beta': exposure / (t.long_notional + t.short_notional), 'market_usd': market_usd})
    df = pd.DataFrame(rows, index=trades.index)
    ex = (trades['gross_usd'] - df['market_usd'])
    ex_bp = ex / trades['notional'] * 1e4
    var_g = float(trades['gross_usd'].var())
    out['net_market_beta_per_gross'] = {'mean': float(df['net_beta'].mean()), 'mean_abs': float(df['net_beta'].abs().mean()),
                                        'by_side': {s: float(df['net_beta'][trades['action'] == s].mean())
                                                    for s in SIDES if (trades['action'] == s).any()}}
    out['market_component'] = {
        'market_usd': float(df['market_usd'].sum()), 'gross_usd': float(trades['gross_usd'].sum()),
        'gross_ex_market_bp': _mean_t(ex_bp),
        'market_share_of_gross_variance': float(1.0 - ex.var() / var_g) if var_g > 0 else None,
        'by_side': {s: {'gross_usd': float(trades['gross_usd'][trades['action'] == s].sum()),
                        'market_usd': float(df['market_usd'][trades['action'] == s].sum())}
                    for s in SIDES if (trades['action'] == s).any()},
        'proxy': 'equal-weight daily return of the sector SPDR ETFs', 'beta_window_days': MARKET_BETA_DAYS,
    }
    return out


# ──────────────────────────────────────────────────────────────────────────────
# (f) Capacity
# ──────────────────────────────────────────────────────────────────────────────

def capacity_curve(trades: pd.DataFrame, daily: Dict, execs: Optional[pd.DataFrame], execs_verified: bool,
                   base_aum: float, aums: Sequence[float] = CAPACITY_AUM,
                   cost_model: Optional[EnhancedPrimeFundTransactionCostModel] = None) -> Dict:
    """Net bp per trade, net return and Sharpe of the same trades at other book sizes.

    A book `s = AUM / base_aum` times larger holds s times every position: gross P&L,
    commissions, half-spreads, borrow and financing scale with s (unchanged per $ of
    notional; the per-order commission minimum is ignored), while each execution's
    participation scales with s, so its square-root impact per $ grows with sqrt(s) up to
    the cost model's 50 bp cap. Each execution is re-priced at s x its shares (when the
    re-pricing reproduces the exported impacts; otherwise the exported impact is scaled
    by sqrt(s), cap ignored). Returns and Sharpe are those of the base-size series with
    the impact difference booked on each fill day. A completeness item: with gross P&L
    per trade near zero, more capital can only lose more.
    """
    model = cost_model or EnhancedPrimeFundTransactionCostModel()
    if trades.empty:
        return {'rows': []}
    exact = execs is not None and execs_verified
    base = execution_impact(execs, cost_model=model) if exact else None
    have_daily = daily.get('gross') is not None
    rows = []
    for aum in aums:
        s = aum / base_aum
        if exact:
            delta_exec = execution_impact(execs, scale=s, cost_model=model) / s - base
            per_trade = pd.Series(delta_exec).groupby(execs['trade'].to_numpy()).sum().reindex(trades.index, fill_value=0.0)
            day_usd = _cost_by_day(daily, execs['date'], delta_exec) if have_daily else None
        else:
            per_trade = trades['cost_market_impact'] * (np.sqrt(s) - 1.0)
            day_usd = (_cost_by_day(daily, trades['entry_date'], per_trade / 2.0)
                       + _cost_by_day(daily, trades['exit_date'], per_trade / 2.0)) if have_daily else None
        impact_bp = (trades['cost_market_impact'] + per_trade) / trades['notional'] * 1e4
        row = {'aum_musd': aum / 1e6, 'net_bp': float(((trades['net_usd'] - per_trade) / trades['notional']).mean() * 1e4),
               'impact_bp': float(impact_bp.mean())}
        if have_daily:
            row.update({k: v for k, v in _daily_block(_scenario_returns(daily, day_usd)).items()
                        if k in ('sharpe', 'total_return_pct')})
        rows.append(row)
    return {'rows': rows, 'base_aum_musd': base_aum / 1e6,
            'method': 'repriced per execution' if exact else 'sqrt(AUM) scaling (cap ignored)'}


# ──────────────────────────────────────────────────────────────────────────────
# (g) Cash
# ──────────────────────────────────────────────────────────────────────────────

def parse_fred_csv(text: str, series_id: str) -> pd.Series:
    """A FRED graph CSV (fredgraph.csv?id=SERIES) as a float Series indexed by date.

    The first column holds the dates ('observation_date'; 'DATE' in older files), the
    series' column its values in percent; a missing observation is empty or '.'.
    Anything else that is not a number raises.
    """
    df = pd.read_csv(io.StringIO(text), na_values=['', '.'], keep_default_na=False)
    col = series_id if series_id in df.columns else df.columns[1]
    values = pd.to_numeric(df[col], errors='raise').to_numpy(dtype=float)
    return pd.Series(values, index=pd.DatetimeIndex(pd.to_datetime(df[df.columns[0]])), name=series_id).sort_index()


def bill_investment_yield(discount_pct, days: int = 91):
    """Investment (bond-equivalent) yield of a Treasury bill from its discount yield, as a fraction.

    DTB3 quotes the 3-month bill's bank-discount rate r (percent, 360-day year). For a
    bill of d <= 182 days the investment rate is i = 365 r / (360 - r d) (r as a
    fraction; the Treasury's formula), which accrues per calendar day on 365.
    """
    r = np.asarray(discount_pct, dtype=float) / 100.0
    return 365.0 * r / (360.0 - r * days)


def cash_returns(dtb3: pd.Series, dates: Sequence) -> np.ndarray:
    """Daily return of the 3-month T-bill on each date of a series.

    Day t earns the investment yield of the last DTB3 observation on or before day t-1
    for the calendar days from t-1 to t (interest known in advance); the first date earns
    nothing (the window starts at its close).
    """
    dates = pd.DatetimeIndex(dates)
    rates = dtb3.dropna().sort_index()
    y = bill_investment_yield(rates.reindex(dates[:-1], method='ffill').to_numpy(dtype=float))
    days = np.diff(dates.to_numpy()).astype('timedelta64[D]').astype(float)
    return np.concatenate([[0.0], y * days / 365.0])


def excess_of_cash(results: Dict, daily: Dict, dtb3: Optional[pd.Series],
                   trades: Optional[pd.DataFrame] = None) -> Dict:
    """Strategy return against cash over the main window, and what the Sharpe measures.

    The engine's equity earns no interest (a day's return is the positions' P&L net of
    costs over the previous day's equity), and every Sharpe in the study is the mean
    over the standard deviation of those returns without subtracting a risk-free rate.
    For a self-financing, dollar-neutral long-short book that is the excess-of-cash
    Sharpe: invested in T-bills, the same book would earn r_t + rf_t, whose excess over
    rf_t is r_t. This recomputes the Sharpe from the daily returns and confirms it equals
    the exported one; 'sharpe_if_cash_were_subtracted' shows the (wrong) figure a second
    deduction of the T-bill rate would give.

    A trade with long notional L and short notional S is not dollar-neutral unless the
    hedge ratio is 1: with the equity in bills and the short proceeds earning the bill
    rate, its excess-of-cash P&L is the engine's plus rf x (S - L) over the holding.
    'net_dollar_carry_usd' is that interest summed over the trades (positive when the
    book was net short on balance), at the daily bill returns from the entry fill to the
    exit fill: the gap between the engine's returns and strict excess-of-cash returns.
    """
    r = np.asarray(daily['net'], dtype=float)
    reported = _f((results.get('overall_performance') or {}).get('sharpe_ratio'))
    recomputed = annualized_sharpe(r, TRADING_DAYS_PER_YEAR)
    out = {'strategy_return_pct': float((np.prod(1.0 + r) - 1.0) * 100.0),
           'sharpe_reported': reported, 'sharpe_recomputed': recomputed,
           'sharpe_is_excess_of_cash': bool(reported is not None and abs(reported - recomputed) < 1e-3),
           'period': [str(daily['dates'][0].date()), str(daily['dates'][-1].date())]}
    if dtb3 is None or dtb3.dropna().empty:
        return out
    rc = cash_returns(dtb3, daily['dates'])
    last_rate = dtb3.dropna().index.max()
    out.update({
        'tbill_return_pct': float((np.prod(1.0 + rc) - 1.0) * 100.0),
        'tbill_mean_yield_pct': float(rc[1:].sum() / max((daily['dates'][-1] - daily['dates'][0]).days, 1) * 365.0 * 100.0),
        'strategy_plus_cash_return_pct': float((np.prod(1.0 + r + rc) - 1.0) * 100.0),
        'strategy_minus_cash_return_pct': float((np.prod(1.0 + r) / np.prod(1.0 + rc) - 1.0) * 100.0),
        'sharpe_if_cash_were_subtracted': annualized_sharpe(r - rc, TRADING_DAYS_PER_YEAR),
        'rates_cover_window': bool(last_rate >= daily['dates'][-2]) if len(daily['dates']) > 1 else True,
        'source': 'FRED DTB3 (3-month T-bill, discount basis) as bond-equivalent yield, act/365 daily accrual',
    })
    if trades is not None and not trades.empty:
        growth = np.cumprod(1.0 + rc)
        entry, exit_ = (daily['dates'].get_indexer(pd.DatetimeIndex(trades[c])) for c in ('entry_date', 'exit_date'))
        if (entry < 0).any() or (exit_ < 0).any():
            raise ValueError("a fill date is not on the run's daily calendar")
        carry = (trades['short_notional'] - trades['long_notional']).to_numpy() * (growth[exit_] / growth[entry] - 1.0)
        out['net_dollar_carry_usd'] = float(carry.sum())
        out['net_dollar_carry_pct_of_capital'] = float(carry.sum() / daily['equity_prev'][0] * 100.0)
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Assembly
# ──────────────────────────────────────────────────────────────────────────────

def site_persistence(clegg: Optional[Dict], traded: Optional[Dict]) -> Optional[Dict]:
    """The persistence exhibit's data: share still cointegrated per window vs the chance rate
    (and, per window, the next year's base rate: see cointegration_persistence)."""
    windows = []
    for row in (clegg or {}).get('years') or []:
        still = row['still_cointegrated_next_year']
        if still['share'] is not None:
            base = still.get('next_year_base_rate')
            windows.append({'window': f"{row['year']}→{row['next_year']}", 'pct': still['share'] * 100.0,
                            'pairs': still['of'], 'base_pct': base * 100.0 if base is not None else None})
    if traded and traded.get('oos', {}).get('cointegrated', {}).get('share') is not None:
        windows.append({'window': 'Traded pairs, out of sample', 'pct': traded['oos']['cointegrated']['share'] * 100.0,
                        'pairs': traded['oos']['cointegrated']['of']})
    if not windows:
        return None
    alpha = (clegg or traded)['alpha']
    return {'chance_pct': alpha * 100.0, 'windows': windows}


def build_anatomy(results: Dict, prices: Dict[str, pd.DataFrame], sectors: Optional[Dict[str, pd.Series]] = None,
                  dtb3: Optional[pd.Series] = None, persistence: Optional[Dict] = None,
                  n_paths: int = EXIT_RACE_PATHS, seed: int = 0,
                  cost_model: Optional[EnhancedPrimeFundTransactionCostModel] = None) -> Dict:
    """The anatomy of one run (see the module docstring), as a JSON-safe dict.

    `prices` is the run's price cache (symbol -> bars with Close, Open, Volume_MA,
    Volatility_20, Close_PIT, Returns); `sectors` the sector-ETF closes of macro_data
    (market proxy); `dtb3` the FRED DTB3 series; `persistence` the run-independent
    cointegration_persistence result. Deterministic for a given seed.
    """
    model = cost_model or EnhancedPrimeFundTransactionCostModel()
    trades = trade_table(results)
    capital = run_capital(results)
    rc = results.get('run_config') or {}
    out: Dict = {'schema': SCHEMA, 'run': {
        'commit': rc.get('git_commit'), 'timestamp_utc': rc.get('run_timestamp_utc'),
        'profile': (rc.get('effective') or {}).get('profile'), 'calendar': (rc.get('effective') or {}).get('calendar'),
        'period': [str(d.date()) for d in backtest_window(results)], 'trades': int(len(trades)), 'capital': capital}}
    panel = PricePanel(prices, run_calendar(results, trades))
    fill_col = resolve_fill_column((rc.get('effective') or {}).get('fill') or 'close')
    recon = reconstruct_trades(trades, panel, fill_col)
    daily = daily_series(results, trades, recon, panel)
    execs = execution_table(trades, panel, recon) if len(trades) else None
    impact_check = (_impact_check(trades, execs, execution_impact(execs, cost_model=model))
                    if execs is not None else {'verified': False})
    out['reconstruction'] = {'trades': recon['check'], 'daily': {'source': daily['source'], **daily['check']},
                             'impact': impact_check, 'fill': fill_col}
    if daily['source'] == 'reconstructed':
        out['daily_decomposition'] = {'dates': [str(d.date()) for d in daily['dates']],
                                      'gross_pct': (daily['gross'] * 100).tolist(),
                                      'cost_pct': (daily['cost'] * 100).tolist(), 'source': daily['source']}
    out['gross_vs_net'] = gross_vs_net(trades, daily, execs, impact_check['verified'], model)
    wf = results.get('walk_forward_daily')
    if wf and all(d.get('gross_return_pct') is not None and d.get('cost_pct') is not None for d in wf):
        g = np.array([d['gross_return_pct'] for d in wf]) / 100.0
        c = np.array([d['cost_pct'] for d in wf]) / 100.0
        out['gross_vs_net']['walk_forward_cost_curve'] = [{'k': k, **_daily_block(g - k * c)} for k in COST_MULTIPLES]

    if trades.empty:
        return out
    if recon['check']['verified']:
        sd = implementation_shortfall(trades, panel, recon, daily, capital)
        out['shortfall'] = sd.pop('steps')
        out['shortfall_detail'] = sd
    else:
        out['shortfall_detail'] = {'skipped': 'the cached prices do not reproduce every trade (reconstruction)'}

    pairs = pair_windows(trades, results)
    stats = traded_pair_stats(pairs, panel)
    hl_by_pair = dict(zip(zip(pairs['symbol1'], pairs['symbol2']), stats['formation_half_life_selector']))
    trade_hl = pd.Series([hl_by_pair[legs] for legs in zip(trades['symbol1'], trades['symbol2'])],
                         index=trades.index, dtype=float)
    engine = Engine(initial_capital=capital)
    engine.processed_data = {s: prices[s] for s in set(trades['symbol1']) | set(trades['symbol2'])}
    windows = signal_windows(trades, panel, trade_hl)
    out['exit_race'] = exit_race(trades, windows, trade_hl, engine, n_paths, seed)
    selector = FixedPrimeFundPairSelector()
    traded = traded_pair_persistence(pairs, stats, float(selector.max_half_life))
    out['persistence'] = site_persistence(persistence, traded)
    out['persistence_detail'] = {'clegg': persistence, 'traded_pairs': traded}
    dec = decay(trades, pairs, stats['formation_half_life_selector'], engine)
    out['decay'] = dec.pop('rows')
    out['decay_detail'] = dec

    zkey = trades['abs_z'].map(_z_bucket)
    cal = calendar_breakdown(daily)
    out['breakdowns'] = {
        'by_side': group_table(trades, trades['action'], SIDES, capital),
        'by_exit_reason': group_table(trades, trades['exit_reason'], EXIT_REASONS, capital),
        'by_abs_z': group_table(trades, zkey, [b[2] for b in Z_BUCKETS], capital),
        'by_signal_year': group_table(trades, trades['signal_date'].dt.year.astype(str),
                                      sorted(trades['signal_date'].dt.year.astype(str).unique()), capital),
        **cal,
    }
    out['concentration'] = concentration(trades, cal['months'], results)
    out['exposure'] = market_exposure(trades, panel, market_proxy_returns(sectors) if sectors else None)
    cap = capacity_curve(trades, daily, execs, impact_check['verified'], capital, CAPACITY_AUM, model)
    out['capacity'] = cap.pop('rows')
    gross_bp = out['gross_vs_net']['per_trade']['gross_bp']
    out['capacity_detail'] = {**cap, 'gross_bp_per_trade': gross_bp['mean'], 'gross_bp_t': gross_bp['t'],
                              'note': 'completeness item: costs re-priced for the same trades; a gross edge '
                                      'indistinguishable from zero is not made an edge by a smaller book'}
    out['cash'] = excess_of_cash(results, daily, dtb3, trades)
    return out


def summary_lines(anatomy: Dict) -> List[str]:
    """A short plain-text summary of build_anatomy's output."""
    def g(*path):
        x = anatomy
        for p in path:
            if not isinstance(x, (dict, list)):
                return None
            if isinstance(x, list):
                x = x[p] if -len(x) <= p < len(x) else None
            else:
                x = x.get(p)
        return x

    def num(x, fmt='+.2f'):
        return 'n/a' if x is None else format(x, fmt)

    run = anatomy.get('run') or {}
    lines = [f"Anatomy of the null: {run.get('trades')} trades, {' to '.join(run.get('period') or [])}"
             f" (profile {run.get('profile') or 'v32'}, commit {str(run.get('commit'))[:7]})"]
    rec = anatomy.get('reconstruction') or {}
    lines.append(f"  reconstruction: max |gross error| ${num(g('reconstruction', 'trades', 'max_abs_error_usd'), '.3f')}"
                 f" over {g('reconstruction', 'trades', 'trades')} trades, verified={g('reconstruction', 'trades', 'verified')};"
                 f" daily split from {g('reconstruction', 'daily', 'source')}"
                 f" (verified={g('reconstruction', 'daily', 'verified')}); impact re-pricing verified={rec.get('impact', {}).get('verified')}")
    pt = g('gross_vs_net', 'per_trade') or {}
    if pt:
        lines.append(f"  per trade: gross {num(pt['gross_bp']['mean'], '+.1f')} bp (t {num(pt['gross_bp']['t'])}),"
                     f" cost {num(pt['cost_bp']['mean'], '.1f')} bp, net {num(pt['net_bp']['mean'], '+.1f')} bp;"
                     f" break-even cost multiple k* = {num(g('gross_vs_net', 'totals', 'breakeven_cost_multiple'), '.2f')}")
    curve = g('gross_vs_net', 'cost_curve') or []
    if curve:
        lines.append('  net Sharpe at cost x k: ' + ', '.join(f"{r['k']:g}x {r['sharpe']:+.2f}" for r in curve))
    steps = anatomy.get('shortfall') or []
    if steps:
        lines.append('  shortfall ($k): ' + ' | '.join(f"{s['key']} {s['usd'] / 1e3:+,.0f}" for s in steps))
    er = anatomy.get('exit_race') or {}
    if er.get('barrier_exits'):
        lines.append(f"  exit race: {er['targets']} targets / {er['stops']} stops; random-walk null"
                     f" {num(g('exit_race', 'nulls', 'random_walk', 'expected_targets'), '.1f')} (z {num(er.get('z'))}),"
                     f" gambler's ruin {num(g('exit_race', 'nulls', 'gamblers_ruin', 'expected_targets'), '.1f')}"
                     f" (z {num(g('exit_race', 'nulls', 'gamblers_ruin', 'z'))}), OU at formation half-lives"
                     f" {num(g('exit_race', 'nulls', 'ou', 'expected_targets'), '.1f')} (z {num(g('exit_race', 'nulls', 'ou', 'z'))})")
    for row in g('persistence_detail', 'clegg', 'years') or []:
        c, s = row['cointegrated'], row['still_cointegrated_next_year']
        base = s.get('next_year_base_rate')
        lines.append(f"  persistence {row['year']}: {c['count']}/{c['of']} cointegrated ({num(c['share'] and c['share'] * 100, '.1f')}%),"
                     f" still in {row['next_year']}: {s['count']}/{s['of']} ({num(s['share'] and s['share'] * 100, '.1f')}%;"
                     f" {row['next_year']} base rate {num(base and base * 100, '.1f')}%)")
    tp = g('persistence_detail', 'traded_pairs') or {}
    if tp:
        lines.append(f"  traded pairs: p<0.05 formation {num(g('persistence_detail', 'traded_pairs', 'formation', 'cointegrated', 'share'), '.0%')},"
                     f" out of sample {num(g('persistence_detail', 'traded_pairs', 'oos', 'cointegrated', 'share'), '.0%')};"
                     f" median half-life {num(g('persistence_detail', 'traded_pairs', 'formation', 'median_half_life'), '.1f')}"
                     f" -> {num(g('persistence_detail', 'traded_pairs', 'oos', 'median_half_life'), '.1f')} days"
                     f" (Kendall {num(g('persistence_detail', 'traded_pairs', 'formation', 'median_half_life_kendall'), '.1f')}"
                     f" -> {num(g('persistence_detail', 'traded_pairs', 'oos', 'median_half_life_kendall'), '.1f')})")
    for row in anatomy.get('decay') or []:
        lines.append(f"  decay: {row['period']}: {num(row['bp'], '+.1f')} bp (t {num(row['t'])}, n {row['n']})")
    years = g('breakdowns', 'years') or []
    if years:
        lines.append('  Sharpe by year: ' + ', '.join(f"{y['year']} {y['sharpe']:+.2f}" for y in years))
    m = g('concentration', 'months', 'best')
    if m:
        lines.append(f"  best month {m['month']}: {m['return_pct']:+.2f}% (${m['net_usd'] / 1e3:+,.0f}k)"
                     f" against ${g('concentration', 'months', 'total_net_usd') / 1e3:+,.0f}k in total")
    ex = anatomy.get('exposure') or {}
    if ex.get('hedge_ratio'):
        lines.append(f"  hedge ratio median {ex['hedge_ratio']['p50']:.2f} ({ex['hedge_ratio']['share_below_1']:.0%} below 1);"
                     f" net market beta per $ gross mean {num(g('exposure', 'net_market_beta_per_gross', 'mean'))},"
                     f" market P&L ${num(g('exposure', 'market_component', 'market_usd') and g('exposure', 'market_component', 'market_usd') / 1e3, '+,.0f')}k")
    capacity = anatomy.get('capacity') or []
    if capacity:
        lines.append('  capacity (net bp/trade): ' + ', '.join(f"${r['aum_musd']:,.0f}M {r['net_bp']:+.1f}" for r in capacity)
                     + f" (completeness item: gross t {num(g('capacity_detail', 'gross_bp_t'))})")
    cash = anatomy.get('cash') or {}
    if cash:
        lines.append(f"  cash: T-bill {num(cash.get('tbill_return_pct'))}% vs strategy {num(cash.get('strategy_return_pct'))}%"
                     f" over the window; Sharpe {num(cash.get('sharpe_reported'))} is excess of cash:"
                     f" {cash.get('sharpe_is_excess_of_cash')}; bill interest on the net dollar exposure"
                     f" {num(cash.get('net_dollar_carry_pct_of_capital'), '+.3f')}% of capital")
    return lines


__all__ = ['build_anatomy', 'summary_lines', 'cointegration_persistence', 'liquid_universe', 'parse_fred_csv',
           'trade_table', 'reconstruct_trades', 'daily_series', 'gross_vs_net', 'implementation_shortfall',
           'exit_race', 'simulate_exit_race', 'gamblers_ruin_target_probability', 'kendall_half_life',
           'rule_trades', 'decay', 'market_exposure', 'capacity_curve', 'excess_of_cash', 'PricePanel',
           'COST_MULTIPLES']
