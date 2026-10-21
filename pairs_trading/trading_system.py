"""
RUSSELL 3000 PAIRS TRADING - BACKTEST ENGINE
============================================
Pair universe -> Kalman hedge ratios -> beta-locked z-score signal -> t+1 execution ->
daily mark-to-market portfolio accounting -> walk-forward validation -> fund-cost replay.

Engine contract (v32). Each rule is exercised by the test suite (tests/test_engine_*.py):

  * Causality. A decision taken at the close of day t uses only data dated <= t: the
    Kalman state is a forward filter, the pair universe is the latest quarterly
    re-selection dated <= t, a trade's outcome reaches the position sizer and the
    cool-off logic only once the position has actually closed, and the ex-ante cost
    gate uses the maximum holding period rather than the realised one.
  * One signal definition. Entry, profit target, stop-loss and time stop are all
    evaluated on the SAME beta-locked spread, log p1 - beta * log p2, normalised by
    reference statistics frozen at the signal date. (Through v31 the entry used an
    expanding-window z of the Kalman residual while the exit used the locked spread,
    i.e. two different scales.)
  * The traded book is the modelled spread. Legs are hedge-ratio weighted ($1 of leg 1
    against $beta of leg 2), so P&L is the change of the spread the signal is computed
    on. beta comes from a two-state (slope + intercept) Kalman filter.
  * t+1 execution on both sides: signal on the day-t close, fill at the next bar's close
    (PAIRS_FILL=open -> next bar's open). Share counts are fixed from the signal-day
    close; the next bar's price is used only as the fill price.
  * Daily mark-to-market. Open positions are revalued every day from real prices; entry
    costs are booked at the entry fill and exit costs + borrow + financing at the exit
    fill. Sharpe, volatility, drawdown, the significance tests and the risk manager's
    kill switches therefore see intra-trade moves.
  * No fabricated prices and no silently dropped trades. An entry needs a real bar on
    the fill date for both legs; a leg without a bar on a valuation/exit date is valued
    at its last real price; a position still open when the data ends is closed at the
    last available bar (exit_reason='end_of_data') instead of being discarded.
"""

import os
from typing import Dict, List, Optional, Tuple

from threadpoolctl import threadpool_limits

from pairs_trading.config import pd, np, logging, SECTOR_ETFS
from pairs_trading.data_processor import EnhancedRussell3000DataProcessor
from pairs_trading.pair_selector import FixedPrimeFundPairSelector, formation_window
from pairs_trading.multi_agent_system import FixedTransformerMultiAgentSystem, classifier_skill
from pairs_trading.position_sizer import FixedPrimeFundPositionSizer
from pairs_trading.risk_manager import FixedPrimeFundRiskManager
from pairs_trading.transaction_costs import EnhancedPrimeFundTransactionCostModel
from pairs_trading.significance import annualized_sharpe
from pairs_trading.study_config import (
    CALENDARS, Calendar, Profile, describe as describe_study, get_calendar, get_profile,
)
from pairs_trading.json_export import (
    build_run_config, export_fund_comparison_to_json, export_headline_metrics,
    export_testing_results_to_json, log_run_config,
)
from pairs_trading.plotting import plot_fund_comparison, plot_ranker_training, plot_results

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252

# The development calendar's dates (study_config.CALENDARS['dev']), kept as module
# constants for callers; the engine itself reads the calendar it was built with.
PAIR_SELECTION_CUTOFF = CALENDARS['dev'].selection_cutoff    # initial pairs use data <= this
MAIN_MODEL_TRAIN_END = CALENDARS['dev'].model_train_end      # ranking model, main backtest
MAIN_BACKTEST_START = CALENDARS['dev'].backtest_start


def resolve_fill_column(value: str) -> str:
    """Map the PAIRS_FILL env value to the OHLCV column the t+1 fill reads.

    Only 'open' (any case) selects the next bar's open; everything else — including an
    unset or malformed value — falls back to 'Close', the conservative headline
    convention. Module-level so tests exercise this rule rather than a copy of it.
    """
    return 'Open' if str(value).lower() == 'open' else 'Close'


def _naive(ts) -> pd.Timestamp:
    """Timestamp -> tz-naive Timestamp with the wall-clock date kept."""
    ts = pd.Timestamp(ts)
    return ts.tz_localize(None) if ts.tzinfo is not None else ts


def _last_index_day(obj) -> Optional[pd.Timestamp]:
    """Last date of a frame's or series' index as a tz-naive day (None if empty)."""
    return _naive(obj.index.max()).normalize() if obj is not None and len(obj) else None


def _align_ts(ts, like) -> pd.Timestamp:
    """Localise or strip `ts` so it compares with timestamps shaped like `like`."""
    ts = pd.Timestamp(ts)
    tz = getattr(like, 'tzinfo', None)
    if tz is not None and ts.tzinfo is None:
        return ts.tz_localize(tz)
    if tz is None and ts.tzinfo is not None:
        return ts.tz_localize(None)
    return ts


def annualised_sharpe(daily_returns, periods: int = TRADING_DAYS_PER_YEAR) -> float:
    """Sharpe of a daily return series: significance.annualized_sharpe (ddof=1)."""
    return annualized_sharpe(daily_returns, periods)


def max_drawdown_from_returns(daily_returns) -> float:
    """Most negative peak-to-trough move of the compounded equity curve (<= 0).

    The starting capital counts as the first peak, so a loss on day one is a drawdown.
    """
    r = np.asarray(daily_returns, dtype=float)
    if r.size == 0:
        return 0.0
    equity = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(np.concatenate([[1.0], equity]))[1:]
    return float(np.min(equity / peak - 1.0))


def geometric_annualised_return(total_return: float, n_days: int,
                                periods: int = TRADING_DAYS_PER_YEAR) -> float:
    """(1 + R)^(periods / n) - 1."""
    if n_days <= 0:
        return 0.0
    if total_return <= -1.0:
        return -1.0
    return float((1.0 + total_return) ** (periods / n_days) - 1.0)


class CompleteFixedRussell3000TradingSystem:
    """End-to-end research pipeline: selection, backtest, walk-forward, diagnostics."""

    # ── Signal / trade-management parameters (values unchanged since v22-v31) ──────
    ENTRY_Z = 1.8                 # |z| on the beta-locked spread to open
    EXIT_Z = 0.5                  # profit target: z back inside +-EXIT_Z
    STOP_Z = 1.5                  # stop-loss: z moves STOP_Z further against the entry
    MIN_HOLD_DAYS, MAX_HOLD_DAYS, HOLD_HL_MULT = 10, 25, 2.5   # time stop, trading days
    REF_MIN, REF_MAX, REF_HL_MULT = 30, 90, 3                    # z reference window, bars
    REF_STATS_BARS = 60           # trailing bars of the reference window used for mean/std
    # v32: the CUSUM and Hurst entry gates are OFF by default. Measured on 2,000 simulated
    # spreads per window (scratch study, v32 audit): at the 30/60/90-bar reference windows
    # the CUSUM gate rejects 0.1%/4.5%/8.3% of pure random walks and 0.2%/2.9%/6.4% of
    # mean-reverting OU(HL 15) spreads; the Hurst gate (H > 0.55) rejects ~11% of random
    # walks and 5-10% of OU(HL 15) spreads. Neither separates trending from reverting
    # spreads at these sample sizes (CUSUM standardises by the in-window mean, so a steady
    # drift is invisible to it; a variance-of-increments Hurst estimate on <= 90 bars has a
    # standard error of roughly 0.1). Both mostly removed a near-random 5-10% of signals.
    # They remain available, unchanged, for sensitivity runs.
    USE_CUSUM_GATE = False
    USE_HURST_GATE = False
    HURST_MAX = 0.55              # used only when USE_HURST_GATE is True
    MIN_ROLLING_CORR = 0.20       # 20-day return-correlation floor (decoupled pairs)
    # v32: the risk manager has always rejected quality < 0.55, so the engine's former
    # 0.40 pre-filter was dead; one threshold, stated once, at its effective value.
    MIN_PAIR_QUALITY = 0.55
    MIN_SPREAD_HISTORY = 50       # bars of pair history before a pair can trade
    # v32: hedge ratios outside this band mean one leg is >4x the other — not a hedged
    # pair. Such signals are skipped rather than clamped: a clamped hedge is a different,
    # partly unhedged position from the spread the signal was computed on.
    BETA_MIN, BETA_MAX = 0.25, 4.0
    COOLOFF_LOSSES, COOLOFF_CAL_DAYS = 3, 30
    # Safety rail only: with gross positions capped at 10% of equity, round-trip costs
    # cannot reach 1% of equity for any screened (>= $5, liquid) name, so this never binds
    # in the study; it guards against pathological inputs (sub-$0.05 prices, no volume).
    MAX_COST_PCT_OF_EQUITY = 0.01
    REGIME_LOOKBACK, REGIME_MAX_REDUCED_FRAC = 63, 0.20
    # Re-selection (every 90 trading days): a pair that passes the 2-year re-test is kept
    # only if its 126-day (~87-bar) Bonferroni p-value is <= RESEL_RECENT_MAX_P (1.0 turns
    # the check off). Measured power at n = 87 (300 simulations each, v32 review): it passes
    # 27% of non-cointegrated random-walk pairs and 63% / 41% / 32% of truly cointegrated
    # pairs with half-life 5 / 10 / 14 days — a weak filter that removes many healthy pairs.
    # v32 dropped a second "divergence" rule (|p_recent - p_2y| > 0.20): because p_2y < 0.05
    # it always bound first (an effective cut of 0.20-0.25), so the documented 0.30 never
    # decided anything.
    RESEL_RECENT_MAX_P = 0.30
    # Disclosed count of strategy configurations explored across the project's versioned
    # history (v1-v32, docs/PROGRESS.md); drives the Deflated Sharpe and the Bonferroni
    # hurdle. A lower bound: configurations tried within a version are not counted (the
    # declared variant family, results/variant_family/, measures that separately).
    N_TRIALS = 32
    # Ranking-model training samples (see build_outcome_samples).
    LABEL_STEP, LABEL_MAX_SAMPLES = 2, 15000

    def __init__(self, initial_capital: float = 100000000, profile=None, calendar=None):
        """`profile`/`calendar`: study_config objects or names (default: environment or the
        study_config defaults)."""
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.profile: Profile = profile if isinstance(profile, Profile) else get_profile(profile)
        self.calendar: Calendar = calendar if isinstance(calendar, Calendar) else get_calendar(calendar)

        self.data_processor = EnhancedRussell3000DataProcessor(
            start_date=self.calendar.data_start, end_date=self.calendar.data_end,
            data_file=self.calendar.price_cache, macro_file=self.calendar.macro_cache)
        self.pair_selector = self._new_pair_selector()
        # The one learned component: a model that scores signal quality and is used for
        # opportunity RANKING only (multi_agent_system.py). The attribute keeps its
        # historical name for API compatibility; this is not reinforcement learning.
        self.rl_agent = self._new_ranker()
        self.position_sizer = FixedPrimeFundPositionSizer()
        self.risk_manager = FixedPrimeFundRiskManager(initial_capital=initial_capital)
        self.cost_model = EnhancedPrimeFundTransactionCostModel(
            borrow_rate=self.profile.borrow_rate,
            pb_financing_spread=self.profile.pb_financing_spread)

        self.processed_data = {}
        self.selected_pairs = []
        self.spread_data = {}
        self.macro_data = {}
        # Point-in-time membership (profile universe 'pit_iwv'; universe.PITUniverse) and the
        # ticker -> Fama-French 49 industry map (profile same_industry). None when unused.
        self.pit_universe = None
        self.industries: Optional[Dict[str, str]] = None
        # Survivorship, measured: at each formation date, the point-in-time members and how
        # many of them (and how much index weight) have no free price history.
        self.universe_coverage_log: List[Dict] = []
        # How far anchoring Close_PIT to N-PORT's prices moved the point-in-time members
        # (_anchor_point_in_time_prices; None when unused).
        self.price_anchor_summary: Optional[Dict] = None
        # v32: per-pair Kalman state (lp1, lp2, beta, alpha, spread) on the pair's common
        # trading dates. It is a deterministic function of the two price series, so it is
        # computed once and shared by re-selection, both backtests and the label builder
        # (through v31 every quarterly re-selection recomputed every spread from scratch).
        self._pair_state_cache: Dict[Tuple[str, str], pd.DataFrame] = {}
        # v32: pair statistics re-estimated at every quarterly re-selection
        # ({reselection_date: {"A-B": stats}}); see build_rolling_pair_schedule.
        self.pair_window_stats: Dict = {}
        self._window_stats_index = None

        self.trade_history = []
        self.daily_returns = []
        self.portfolio_metrics = {}

        logger.info(f"Russell 3000 pairs-trading system initialised: profile {self.profile.name}, "
                    f"calendar {self.calendar.name}")

    def _new_pair_selector(self) -> FixedPrimeFundPairSelector:
        selector = FixedPrimeFundPairSelector()
        selector.max_universe = self.profile.max_universe
        industries = getattr(self, 'industries', None)        # loaded with the universe
        selector.industry_of = industries if self.profile.same_industry else None
        return selector

    def _new_ranker(self) -> FixedTransformerMultiAgentSystem:
        return FixedTransformerMultiAgentSystem(ranker=self.profile.ranker)

    # ════════════════════════════════════════════════════════════════════════════
    # Spread model
    # ════════════════════════════════════════════════════════════════════════════

    def calculate_kalman_state(self, prices1: pd.Series, prices2: pd.Series,
                               delta: float = 1e-5, R: float = 0.001,
                               init_n: int = 30) -> pd.DataFrame:
        """Causal two-state Kalman filter for a time-varying hedge ratio (v32).

        Observation:  log p1_t = beta_t * log p2_t + alpha_t + e_t,   e_t ~ N(0, R)
        State:        (beta_t, alpha_t) = (beta_{t-1}, alpha_{t-1}) + w_t,
                      w_t ~ N(0, delta / (1 - delta) * I)      (Chan 2013, ch. 3)

        v32: through v31 the model had NO INTERCEPT (log p1 = beta * log p2), so beta
        absorbed the ratio of log-price LEVELS instead of the co-movement slope: on
        synthetic pairs with known hedge ratios 0.90 and 1.15 it returned 1.27 and 0.79.
        That number then defined the spread every signal was computed on.

        The state is seeded by OLS on the first `init_n` observations and the recursion
        starts after that burn-in, so row t uses data <= t only; earlier rows are NaN.

        Returns a DataFrame indexed like the inputs with columns lp1, lp2 (raw log
        prices), beta, alpha (intercept in burn-in-centred coordinates) and spread
        (posterior residual of the centred observation).
        """
        idx = prices1.index
        p1 = np.asarray(prices1, dtype=float)
        p2 = np.asarray(prices2, dtype=float)
        n = len(p1)
        out = np.full((n, 3), np.nan)
        lp1 = np.log(np.maximum(p1, 1e-8))
        lp2 = np.log(np.maximum(p2, 1e-8))
        k0 = min(init_n, n)
        if k0 >= 3:
            # v32: filter log prices CENTRED on their burn-in means. Back-adjusted prices
            # (yfinance auto_adjust) carry a constant log offset from splits/dividends that
            # happen AFTER the sample; centring removes it exactly, so beta, the residual and
            # every z-score are invariant to how the vendor later rescaled either history.
            m1, m2 = float(lp1[:k0].mean()), float(lp2[:k0].mean())
            cy, cx = lp1 - m1, lp2 - m2
            x0, y0 = cx[:k0], cy[:k0]
            xm, ym = float(x0.mean()), float(y0.mean())
            sxx = float(((x0 - xm) ** 2).sum())
            b = float(((x0 - xm) * (y0 - ym)).sum() / sxx) if sxx > 1e-12 else 1.0
            a = ym - b * xm
            resid = y0 - (a + b * x0)
            s2 = max(float((resid ** 2).sum() / (k0 - 2)), R)
            if sxx > 1e-12:     # OLS parameter covariance as the prior
                p_bb, p_ab, p_aa = s2 / sxx, -s2 * xm / sxx, s2 * (1.0 / k0 + xm * xm / sxx)
            else:
                p_bb, p_ab, p_aa = 1.0, 0.0, 1.0
            q = delta / (1.0 - delta)
            out[k0 - 1] = (b, a, cy[k0 - 1] - (b * cx[k0 - 1] + a))
            for t in range(k0, n):
                x, y = cx[t], cy[t]
                p_bb += q                          # predict: P <- P + Q
                p_aa += q
                ph_b = p_bb * x + p_ab             # (P H')_beta   with H = [x, 1]
                ph_a = p_ab * x + p_aa             # (P H')_alpha
                s = x * ph_b + ph_a + R            # innovation variance
                e = y - (b * x + a)                # innovation
                kb, ka = ph_b / s, ph_a / s        # Kalman gain
                b += kb * e
                a += ka * e
                p_bb -= kb * ph_b                  # P <- P - K H P
                p_ab -= kb * ph_a
                p_aa -= ka * ph_a
                out[t] = (b, a, y - (b * x + a))
        return pd.DataFrame({'lp1': lp1, 'lp2': lp2, 'beta': out[:, 0],
                             'alpha': out[:, 1], 'spread': out[:, 2]}, index=idx)

    def calculate_kalman_spread(self, prices1: pd.Series, prices2: pd.Series,
                                delta: float = 1e-5, R: float = 0.001) -> pd.Series:
        """Posterior Kalman residual (NaN during the burn-in). See calculate_kalman_state."""
        return self.calculate_kalman_state(prices1, prices2, delta=delta, R=R)['spread']

    def _compute_pair_state(self, data1: pd.DataFrame, data2: pd.DataFrame) -> pd.DataFrame:
        """Kalman state on the dates where BOTH legs have a real, positive close.

        v32: no forward/back-filling. Through v31 missing closes were `.ffill().bfill()`ed
        — the back-fill copied a leg's first real price backwards over dates before it
        traded (look-ahead) — and a full-sample "more than 10% missing" rule decided
        whether a pair existed at all. Dates without two real prices are simply not part
        of the pair's history.
        """
        try:
            c1, c2 = data1['Close'], data2['Close']
        except (KeyError, TypeError):
            return pd.DataFrame()
        common = c1.index.intersection(c2.index)
        if len(common) < 100:
            return pd.DataFrame()
        p1, p2 = c1.loc[common], c2.loc[common]
        ok = p1.notna() & p2.notna() & (p1 > 0) & (p2 > 0)
        p1, p2 = p1[ok], p2[ok]
        if len(p1) < 100:
            return pd.DataFrame()
        return self.calculate_kalman_state(p1, p2).dropna()

    def get_pair_state(self, sym1: str, sym2: str) -> pd.DataFrame:
        """Cached Kalman state of a pair (empty DataFrame if it has too little data)."""
        key = (sym1, sym2)
        state = self._pair_state_cache.get(key)
        if state is None:
            d1, d2 = self.processed_data.get(sym1), self.processed_data.get(sym2)
            state = self._compute_pair_state(d1, d2) if d1 is not None and d2 is not None \
                else pd.DataFrame()
            self._pair_state_cache[key] = state
        return state

    def _pair_stats_asof(self, pair_string: str, date) -> Dict:
        """Pair statistics in force on `date`: those of the latest re-selection dated
        <= date that re-estimated the pair, else the formation-period statistics."""
        stats_by_date = getattr(self, '_window_stats_index', None)
        if stats_by_date:
            d = _naive(date)
            pos = int(np.searchsorted(stats_by_date[0], np.datetime64(d), side='right')) - 1
            while pos >= 0:
                st = stats_by_date[1][pos].get(pair_string)
                if st is not None:
                    return st
                pos -= 1
        return self.pair_selector.pair_statistics.get(pair_string, {})

    def calculate_spread(self, data1: pd.DataFrame, data2: pd.DataFrame) -> pd.Series:
        """Kalman residual spread of a pair (empty Series if the pair has too little data)."""
        state = self._compute_pair_state(data1, data2)
        return state['spread'] if not state.empty else pd.Series(dtype=float)

    def _pair_spread(self, sym1: str, sym2: str) -> pd.Series:
        state = self.get_pair_state(sym1, sym2)
        return state['spread'] if not state.empty else pd.Series(dtype=float)

    # ════════════════════════════════════════════════════════════════════════════
    # Entry-time statistical gates and the trading rule
    # ════════════════════════════════════════════════════════════════════════════

    def _cusum_break(self, spread_window, threshold: float = 5.0, k: float = 0.5) -> bool:
        """Two-sided Page CUSUM on standardised first differences of the spread window.

        Returns True if a structural break is detected (skip this pair today).
        threshold=5.0, k=0.5 are standard Page-CUSUM values.
        """
        s = pd.Series(np.asarray(spread_window, dtype=float))
        if len(s) < 20:
            return False
        r = s.diff().dropna()
        mu = r.mean()
        sigma = r.std()
        if not np.isfinite(sigma) or sigma < 1e-8:
            return False
        s_pos = s_neg = 0.0
        for val in ((r - mu) / sigma).to_numpy():
            s_pos = max(0.0, s_pos + val - k)
            s_neg = max(0.0, s_neg - val - k)
            if s_pos > threshold or s_neg > threshold:
                return True
        return False

    def _hurst_exponent(self, spread_values: np.ndarray) -> float:
        """Hurst exponent via variance of increments (log-variance regression).

        H < 0.5 mean-reverting, H = 0.5 random walk, H > 0.5 trending. Uses lags
        [1, 2, 4, 8, 16] (those < n/2); needs >= 3 valid lags, else neutral 0.5.
        """
        spread_values = np.asarray(spread_values, dtype=float)
        n = len(spread_values)
        if n < 20:
            return 0.5
        lags = [lag for lag in [1, 2, 4, 8, 16] if lag < n // 2]
        if len(lags) < 3:
            return 0.5
        log_lags, log_vars = [], []
        for lag in lags:
            diff = spread_values[lag:] - spread_values[:-lag]
            var = np.var(diff)
            if var < 1e-16:
                continue
            log_lags.append(np.log(lag))
            log_vars.append(np.log(var))
        if len(log_lags) < 3:
            return 0.5
        X = np.column_stack([np.ones(len(log_lags)), np.array(log_lags)])
        try:
            coef = np.linalg.lstsq(X, np.array(log_vars), rcond=None)[0]
            return float(np.clip(coef[1] / 2.0, 0.0, 1.0))
        except Exception:
            return 0.5

    def _max_hold_days(self, pair_stats: Dict) -> int:
        """Time stop in trading days: clamp(2.5 x half-life, 10, 25)."""
        hl = float(pair_stats.get('half_life', 10.0))
        return int(max(self.MIN_HOLD_DAYS, min(int(self.HOLD_HL_MULT * hl), self.MAX_HOLD_DAYS)))

    def _locked_signal(self, state: pd.DataFrame, i: int, pair_stats: Dict) -> Tuple[Optional[Dict], str]:
        """Beta-locked z-score of a pair at row `i` of its Kalman state (data <= row i).

        The hedge ratio is locked at beta_i, and the locked spread over the trailing,
        half-life-adaptive reference window (3 x half-life, 30-90 bars) is
        lp1 - beta_i * lp2 — the intercept is a constant shift and cancels in the z-score.
        Its mean/std over the last REF_STATS_BARS bars are frozen here and reused,
        unchanged, by every exit test of a trade opened on this signal. The optional CUSUM
        and Hurst gates (off by default, see USE_CUSUM_GATE) run on the same window.
        """
        beta = float(state['beta'].iat[i])
        if not np.isfinite(beta):
            return None, 'beta_nan'
        hl = float(pair_stats.get('half_life', 21.0))
        window = max(self.REF_MIN, min(int(hl * self.REF_HL_MULT), self.REF_MAX))
        lo = max(0, i - window + 1)
        lk = state['lp1'].to_numpy()[lo:i + 1] - beta * state['lp2'].to_numpy()[lo:i + 1]
        if len(lk) < 20:
            return None, 'history'
        if self.USE_CUSUM_GATE and self._cusum_break(lk):
            return None, 'cusum'
        if self.USE_HURST_GATE and self._hurst_exponent(lk) > self.HURST_MAX:
            return None, 'hurst'
        ref = lk[-min(self.REF_STATS_BARS, len(lk)):]
        mu = float(ref.mean())
        sd = max(float(ref.std()), 1e-8)
        return {'beta': beta, 'mean': mu, 'std': sd, 'z': (float(lk[-1]) - mu) / sd,
                'lk_diffs': np.diff(lk)}, ''

    def _rolling_corr_ok(self, state: pd.DataFrame, i: int, n: int = 21) -> bool:
        """20-day log-return correlation floor on the pair's common dates (data <= row i)."""
        if i + 1 < n:
            return True
        r1 = np.diff(state['lp1'].to_numpy()[i + 1 - n:i + 1])
        r2 = np.diff(state['lp2'].to_numpy()[i + 1 - n:i + 1])
        if r1.std() < 1e-12 or r2.std() < 1e-12:
            return False
        c = np.corrcoef(r1, r2)[0, 1]
        return bool(np.isfinite(c) and c >= self.MIN_ROLLING_CORR)

    def _scan_exit(self, lp1: np.ndarray, lp2: np.ndarray, rows: List[int], sig: Dict,
                   action: int, max_hold: int) -> Tuple[Optional[int], str]:
        """Index j into `rows` of the first close that triggers an exit, and why.

        rows[j] are the pair-history rows on which the exit rule is evaluated, in date
        order; rows[0] is the first bar AFTER the entry fill, so rows[j] is j + 1 trading
        days after the entry and the time stop fires at j + 1 == max_hold. The profit
        target, stop-loss and time stop all use the z-score frozen in `sig`.
        """
        beta, mu, sd, z0 = sig['beta'], sig['mean'], sig['std'], sig['z']
        for j, r in enumerate(rows):
            z = (lp1[r] - beta * lp2[r] - mu) / sd
            if action == 0:          # long spread, entered at z < -ENTRY_Z: reversion = z rising
                if z > -self.EXIT_Z:
                    return j, 'target'
                if z < z0 - self.STOP_Z:
                    return j, 'stop'
            else:                    # short spread, entered at z > +ENTRY_Z: reversion = z falling
                if z < self.EXIT_Z:
                    return j, 'target'
                if z > z0 + self.STOP_Z:
                    return j, 'stop'
            if j + 1 >= max_hold:
                return j, 'time'
        return None, ''

    # ════════════════════════════════════════════════════════════════════════════
    # Calendar-aligned price access and trade construction
    # ════════════════════════════════════════════════════════════════════════════

    def _aligned(self, cache: Dict, sym: str, calendar: pd.DatetimeIndex) -> Optional[Dict[str, np.ndarray]]:
        """Per-symbol arrays aligned to a run's calendar (built once per run).

        close_ff : last real close at or before each date (NaN before the first bar)
        open     : the real open on that date (NaN if no bar)
        has_bar  : a real, positive close exists on that date
        adv      : 20-day average share volume as of that date (causal)
        dvol     : 20-day daily return volatility as of that date (causal)
        """
        if sym in cache:
            return cache[sym]
        df = self.processed_data.get(sym)
        a = None
        if df is not None and 'Close' in df.columns:
            close = df['Close'].where(df['Close'] > 0)
            has_bar = close.reindex(calendar).notna().to_numpy()
            close_ff = close.dropna().reindex(calendar, method='ffill').to_numpy(dtype=float)
            if 'Open' in df.columns:
                op = df['Open'].where(df['Open'] > 0).reindex(calendar).to_numpy(dtype=float)
            else:
                op = np.where(has_bar, close_ff, np.nan)
            adv = (df['Volume_MA'].reindex(calendar, method='ffill').to_numpy(dtype=float)
                   if 'Volume_MA' in df.columns else np.full(len(calendar), np.nan))
            dvol = ((df['Volatility_20'] / np.sqrt(TRADING_DAYS_PER_YEAR))
                    .reindex(calendar, method='ffill').to_numpy(dtype=float)
                    if 'Volatility_20' in df.columns else np.full(len(calendar), np.nan))
            # point-in-time / adjusted price ratio (1.0 unless a later split is in the data)
            pit_ratio = ((df['Close_PIT'] / df['Close']).reindex(calendar, method='ffill')
                         .to_numpy(dtype=float) if 'Close_PIT' in df.columns
                         else np.ones(len(calendar)))
            a = {'close_ff': close_ff, 'open': op, 'has_bar': has_bar, 'adv': adv, 'dvol': dvol,
                 'pit_ratio': pit_ratio}
        cache[sym] = a
        return a

    @staticmethod
    def _fill_price(a: Dict, k: int, fill_col: str) -> float:
        """Real fill price on calendar day k (NaN if the leg has no bar that day)."""
        if not a['has_bar'][k]:
            return float('nan')
        if fill_col == 'Open':
            p = a['open'][k]
            if np.isfinite(p) and p > 0:
                return float(p)
        return float(a['close_ff'][k])

    def _exit_price(self, a: Dict, k: int, fill_col: str) -> Tuple[float, bool]:
        """Exit fill on day k; a leg without a bar that day is valued at its last real close."""
        p = self._fill_price(a, k, fill_col)
        if np.isfinite(p):
            return p, True
        return float(a['close_ff'][k]), False

    def _leg_costs(self, shares: float, price: float, a: Optional[Dict], k: int) -> Dict[str, float]:
        """One-way execution cost of one leg on calendar day k (the stock's own ADV/vol)."""
        adv = float(a['adv'][k]) if a is not None else None
        dvol = float(a['dvol'][k]) if a is not None else None
        ratio = float(a['pit_ratio'][k]) if a is not None and np.isfinite(a['pit_ratio'][k]) else 1.0
        return self.cost_model.calculate_leg_cost(shares, price, daily_volume_shares=adv,
                                                  daily_volatility=dvol,
                                                  point_in_time_price=price * ratio)

    @staticmethod
    def _build_trade_path(a1: Dict, a2: Dict, q1: float, q2: float, entry_k: int, exit_k: int,
                          e1: float, e2: float, x1: float, x2: float) -> Dict[int, float]:
        """Daily mark-to-market dollar P&L of a two-leg position (costs excluded).

        q1/q2 are signed share counts (positive = long). Valuation uses the last real
        close; the entry day marks fill -> close and the exit day marks previous close ->
        exit fill, so the path telescopes to  q1*(x1 - e1) + q2*(x2 - e2)  exactly.
        """
        c1, c2 = a1['close_ff'], a2['close_ff']
        if exit_k <= entry_k:
            return {entry_k: q1 * (x1 - e1) + q2 * (x2 - e2)}
        path = {entry_k: q1 * (c1[entry_k] - e1) + q2 * (c2[entry_k] - e2)}
        for k in range(entry_k + 1, exit_k):
            path[k] = q1 * (c1[k] - c1[k - 1]) + q2 * (c2[k] - c2[k - 1])
        path[exit_k] = q1 * (x1 - c1[exit_k - 1]) + q2 * (x2 - c2[exit_k - 1])
        return path

    def _finalise_trade(self, t: Dict, exit_signal_k: int, exit_k: int, reason: str,
                        full_dates: List, aligned: Dict, fill_col: str) -> None:
        """(Re)compute a trade's exit, MTM path and costs for a given exit-fill day."""
        a1, a2 = aligned[t['symbol1']], aligned[t['symbol2']]
        x1, real1 = self._exit_price(a1, exit_k, fill_col)
        x2, real2 = self._exit_price(a2, exit_k, fill_col)
        path = self._build_trade_path(a1, a2, t['q1'], t['q2'], t['entry_k'], exit_k,
                                      t['e1'], t['e2'], x1, x2)
        exit_c1 = self._leg_costs(t['q1'], x1, a1, exit_k)
        exit_c2 = self._leg_costs(t['q2'], x2, a2, exit_k)
        cal_days = max(1, (_naive(full_dates[exit_k]) - _naive(full_dates[t['entry_k']])).days)
        if t['q1'] > 0:
            short_sym, short_notional = t['symbol2'], abs(t['q2']) * t['e2']
        else:
            short_sym, short_notional = t['symbol1'], abs(t['q1']) * t['e1']
        borrow = self.cost_model.calculate_borrow_cost(short_notional, short_sym, cal_days)
        financing = self.cost_model.calculate_financing_cost(t['gross_notional'], cal_days)
        exit_cost = exit_c1['total'] + exit_c2['total'] + borrow + financing
        costs_by_k = {t['entry_k']: t['entry_cost']}
        costs_by_k[exit_k] = costs_by_k.get(exit_k, 0.0) + exit_cost
        gross = float(sum(path.values()))
        total_cost = t['entry_cost'] + exit_cost
        eb = t['entry_breakdown']
        t.update({
            'exit_signal_k': exit_signal_k, 'exit_k': exit_k, 'exit_reason': reason,
            'x1': x1, 'x2': x2, 'exit_prices_real': bool(real1 and real2),
            'path': path, 'costs_by_k': costs_by_k,
            'gross_pnl_dollars': gross, 'total_cost': total_cost,
            'net_pnl_dollars': gross - total_cost, 'calendar_days': cal_days,
            'cost_breakdown': {
                'commission': eb['commission'] + exit_c1['commission'] + exit_c2['commission'],
                'bid_ask': eb['bid_ask'] + exit_c1['bid_ask'] + exit_c2['bid_ask'],
                'market_impact': eb['market_impact'] + exit_c1['market_impact'] + exit_c2['market_impact'],
                'borrow': borrow, 'financing': financing, 'total_cost': total_cost,
            },
        })

    # ════════════════════════════════════════════════════════════════════════════
    # Train/test split of the initial universe
    # ════════════════════════════════════════════════════════════════════════════

    def prepare_time_split_data(self) -> Tuple[Dict, Dict]:
        """Split the initial pairs' spreads at the pair-selection cutoff."""
        train_spreads, test_spreads = {}, {}
        for pair_key, spread in self.spread_data.items():
            if len(spread) == 0:
                continue
            # v32: eligibility uses only data known at the cutoff (>= 100 training days);
            # a full-sample ">= 200 bars" rule used to require post-cutoff observations.
            like = spread.index[0]
            cutoff = _align_ts(self.calendar.selection_cutoff, like)
            train = spread[spread.index <= cutoff]
            test = spread[spread.index > cutoff]
            if len(train) >= 100 and len(test) >= 1:
                train_spreads[pair_key] = train
                test_spreads[pair_key] = test
        logger.info(f"Time split: {len(train_spreads)} pairs with >= 100 training days")
        return train_spreads, test_spreads

    # ════════════════════════════════════════════════════════════════════════════
    # Backtest
    # ════════════════════════════════════════════════════════════════════════════

    def _dispersion_z(self) -> pd.Series:
        """Cross-sectional std of 63-day cumulative sector log-returns, z-scored against its
        own trailing 252 days (trailing windows only; tested for prefix invariance)."""
        sectors = self.macro_data.get('sectors', {})
        sector_rets = pd.DataFrame({k: v.pct_change(fill_method=None) for k, v in sectors.items() if len(v) > 10})
        sector_rets = sector_rets.dropna(how='all')
        if sector_rets.empty:
            return pd.Series(dtype=float)
        cum63 = np.log1p(sector_rets.fillna(0)).rolling(63, min_periods=30).sum()
        disp = cum63.std(axis=1).dropna()
        return ((disp - disp.rolling(252, min_periods=60).mean())
                / (disp.rolling(252, min_periods=60).std() + 1e-10)).dropna()

    def _regime_scales(self, full_dates: List) -> np.ndarray:
        """Per-date regime scale from VIX bands and 63-day cumulative sector dispersion.

        VIX > 40 -> 0.25x, > 30 -> 0.50x; dispersion z > 2 -> 0.50x; VIX < 20 with
        dispersion z > 0.8 ("walking on ice") -> 0.40x; the minimum applies. Dispersion
        is the cross-sectional std of 63-day cumulative sector log-returns, z-scored
        against its own trailing 252 days — trailing data only.
        """
        vix = self.macro_data.get('VIX', pd.Series(dtype=float))
        disp_z = self._dispersion_z()
        vix_lookup = {str(pd.Timestamp(d).date()): float(v) for d, v in vix.items()}
        disp_lookup = {str(pd.Timestamp(d).date()): float(z) for d, z in disp_z.items()}
        scales = np.ones(len(full_dates))
        for k, d in enumerate(full_dates):
            key = str(pd.Timestamp(d).date())
            v = vix_lookup.get(key, 18.0)        # neutral default when VIX is missing
            z = disp_lookup.get(key, 0.0)
            vix_scale = 0.25 if v > 40 else (0.50 if v > 30 else 1.0)
            if z > 2.0:
                disp_scale = 0.50
            elif v < 20 and z > 0.8:
                disp_scale = 0.40
            else:
                disp_scale = 1.0
            scales[k] = min(vix_scale, disp_scale)
        logger.info(f"Regime gate: {len(vix_lookup)} VIX days, {len(disp_lookup)} dispersion days")
        return scales

    def run_comprehensive_backtest(self, test_spreads: Dict, pair_windows: Dict = None,
                                   date_range: tuple = None,
                                   model_schedule: List[Tuple] = None) -> Dict:
        """Event-driven daily backtest with t+1 fills and mark-to-market accounting.

        test_spreads   : {pair: spread} used when no re-selection schedule is given.
        pair_windows   : {reselection_date: {pair: spread}}; on each day the pairs of the
                         latest re-selection dated <= that day are tradeable.
        date_range     : (start, end); new positions are opened only on these dates.
                         Positions still open at `end` run off under their own exit rules
                         on the real bars that follow (no new entries); if the data ends
                         first they are closed at the last available bar.
        model_schedule : [(start_date, agent), ...]; the ranking model in force on a day
                         is the latest one whose start_date <= that day (walk-forward).
        """
        self.risk_manager.reset_state(self.initial_capital)
        self.position_sizer = FixedPrimeFundPositionSizer()
        fill_col = resolve_fill_column(os.environ.get('PAIRS_FILL', 'close'))

        universe = pair_windows if pair_windows else {None: test_spreads}
        cal = set()
        for window_spreads in universe.values():
            for pair_key in window_spreads:
                cal.update(self.get_pair_state(*pair_key).index)
        full_dates = sorted(cal)
        if not full_dates:
            logger.warning("Backtest: empty calendar")
            return self._summarise_backtest([], [], [], [], 0.0, 0, 0, 0)
        calendar = pd.DatetimeIndex(full_dates)
        like = full_dates[0]
        n_cal = len(full_dates)

        start = _align_ts(date_range[0], like) if date_range is not None else full_dates[0]
        end = _align_ts(date_range[1], like) if date_range is not None else full_dates[-1]
        first_k = int(calendar.searchsorted(start, side='left'))
        last_trade_k = int(calendar.searchsorted(end, side='right')) - 1
        if first_k >= n_cal or last_trade_k < first_k:
            logger.warning("Backtest: date range outside the calendar")
            return self._summarise_backtest([], [], [], [], 0.0, 0, 0, 0)
        logger.info(f"Backtest: {last_trade_k - first_k + 1} tradeable days "
                    f"({pd.Timestamp(full_dates[first_k]).date()} -> "
                    f"{pd.Timestamp(full_dates[last_trade_k]).date()}), fill={fill_col}")

        resel_keys = sorted(k for k in universe if k is not None)
        resel_index = pd.DatetimeIndex([_align_ts(k, like) for k in resel_keys])
        schedule = sorted(((_align_ts(s, like), m) for s, m in (model_schedule or [])),
                          key=lambda x: x[0])

        scales = self._regime_scales(full_dates) if self.profile.regime_gate else np.ones(n_cal)
        reduced_cum = np.concatenate([[0], np.cumsum(scales < 1.0)])
        regime_counts: Dict[float, int] = {}

        aligned: Dict[str, Optional[Dict]] = {}
        equity = float(self.initial_capital)
        open_trades: List[Dict] = []
        all_trades: List[Dict] = []
        daily_returns: List[float] = []
        daily_dates: List = []
        daily_equity: List[float] = []
        daily_gross: List[float] = []            # gross exposure / equity, positions held
        daily_gross_ret: List[float] = []        # pre-cost MTM P&L / previous equity
        daily_cost_ret: List[float] = []         # costs booked that day / previous equity
        daily_positions: List[int] = []          # positions held through the day
        pair_loss_streak: Dict[str, int] = {}
        pair_cooloff_from: Dict[str, pd.Timestamp] = {}
        quality_opportunities = 0
        max_daily_trades_seen = 0
        halted_on, halt_reason = None, ''
        rejects: Dict[str, int] = {}

        def _reject(key):
            rejects[key] = rejects.get(key, 0) + 1

        k = first_k
        while k < n_cal:
            date = full_dates[k]
            in_range = k <= last_trade_k
            if not in_range and not open_trades:
                break

            # 1) Mark open positions to market and book today's costs.
            equity_prev = equity
            day_pnl = day_gross_pnl = day_cost = 0.0
            for t in open_trades:
                g, c = t['path'].get(k, 0.0), t['costs_by_k'].get(k, 0.0)
                day_pnl += g - c
                day_gross_pnl += g
                day_cost += c
            equity += day_pnl
            r_day = day_pnl / equity_prev if equity_prev > 0 else 0.0
            daily_returns.append(r_day)
            daily_dates.append(date)
            daily_equity.append(equity)
            held = [t for t in open_trades if t['entry_k'] <= k < t['exit_k']]
            daily_gross.append(sum(t['gross_notional'] for t in held) / equity_prev
                               if equity_prev > 0 else 0.0)
            daily_gross_ret.append(day_gross_pnl / equity_prev if equity_prev > 0 else 0.0)
            daily_cost_ret.append(day_cost / equity_prev if equity_prev > 0 else 0.0)
            daily_positions.append(len(held))

            # 2) Positions whose exit filled today close; their outcome is known only now.
            still_open = []
            for t in open_trades:
                if t['exit_k'] != k:
                    still_open.append(t)
                    continue
                net_frac = t['net_pnl_dollars'] / t['equity_at_entry']
                self.position_sizer.record_trade(t['pair'], net_frac)
                if net_frac < 0:
                    pair_loss_streak[t['pair']] = pair_loss_streak.get(t['pair'], 0) + 1
                    if pair_loss_streak[t['pair']] >= self.COOLOFF_LOSSES:
                        pair_cooloff_from[t['pair']] = date
                else:
                    pair_loss_streak[t['pair']] = 0
                    pair_cooloff_from.pop(t['pair'], None)
            open_trades = still_open
            open_exposure = sum(t['exposure_frac'] for t in open_trades)

            # 3) The risk manager sees today's MTM P&L before any new decision.
            self.risk_manager.reset_daily_counters()
            self.risk_manager.update_daily_stats(0, open_exposure, r_day, equity)
            if halted_on is None:
                should_stop, stop_reason = self.risk_manager.should_stop_trading(r_day)
                if should_stop:
                    halted_on, halt_reason = date, stop_reason
                    flat_k = min(k + 1, n_cal - 1)
                    logger.warning(f"Risk halt on {pd.Timestamp(date).date()}: {stop_reason}; "
                                   f"flattening {len(open_trades)} open position(s) at the next bar")
                    kept = []
                    for t in open_trades:
                        if t['entry_k'] > k:            # signalled, not yet filled: cancel
                            all_trades.remove(t)
                            continue
                        if t['exit_k'] > flat_k:
                            self._finalise_trade(t, k, flat_k, 'risk_halt', full_dates, aligned, fill_col)
                        kept.append(t)
                    open_trades = kept
                    open_exposure = sum(t['exposure_frac'] for t in open_trades)

            if not in_range or halted_on is not None or k + 1 >= n_cal - 1:
                k += 1
                continue

            # 4) Regime gate. Persistent stress (> 20% of the last 63 days at reduced
            # scale) blocks new entries; otherwise the scale multiplies position size.
            lo = max(0, k - self.REGIME_LOOKBACK + 1)
            if self.profile.regime_gate and k >= self.REGIME_LOOKBACK - 1 and \
                    (reduced_cum[k + 1] - reduced_cum[lo]) / (k - lo + 1) > self.REGIME_MAX_REDUCED_FRAC:
                _reject('regime_hard_stop_day')
                k += 1
                continue
            regime_scale = float(scales[k])
            regime_counts[regime_scale] = regime_counts.get(regime_scale, 0) + 1
            risk_scaling = self.risk_manager.get_combined_scaling_factor(equity) * regime_scale

            if resel_keys:
                pos = int(resel_index.searchsorted(date, side='right')) - 1
                active = universe[resel_keys[pos]] if pos >= 0 else {}
            else:
                active = universe[None]
            agent = self.rl_agent
            for s_start, s_agent in schedule:
                if s_start <= date:
                    agent = s_agent
                else:
                    break

            locked = set()
            for t in open_trades:
                locked.update((t['symbol1'], t['symbol2']))

            # 5) Gather today's signals.
            candidates = []
            for pair_key in active:
                s1, s2 = pair_key
                if s1 in locked or s2 in locked:
                    continue
                state = self.get_pair_state(s1, s2)
                if state.empty:
                    continue
                i = int(state.index.searchsorted(date))
                if i >= len(state) or state.index[i] != date or i + 1 < self.MIN_SPREAD_HISTORY:
                    continue
                if not self._rolling_corr_ok(state, i):
                    _reject('rolling_corr')
                    continue
                pair_string = f"{s1}-{s2}"
                cool_from = pair_cooloff_from.get(pair_string)
                if cool_from is not None:
                    if (_naive(date) - _naive(cool_from)).days < self.COOLOFF_CAL_DAYS:
                        _reject('cooloff')
                        continue
                    pair_cooloff_from.pop(pair_string, None)
                    pair_loss_streak.pop(pair_string, None)
                pair_stats = self._pair_stats_asof(pair_string, date)
                pair_quality = float(pair_stats.get('quality_score', 0.0))
                if pair_quality < self.MIN_PAIR_QUALITY:
                    _reject('pair_quality')
                    continue
                beta = float(state['beta'].iat[i])
                if not (self.BETA_MIN <= beta <= self.BETA_MAX):
                    _reject('beta_out_of_band')
                    continue
                sig, why = self._locked_signal(state, i, pair_stats)
                if sig is None:
                    _reject(why)
                    continue
                zscore = sig['z']
                _reject('evaluated')                     # funnel denominator: pair-days tested
                if abs(zscore) < self.ENTRY_Z:
                    continue
                action = 0 if zscore < 0 else 2          # 0: long spread, 2: short spread
                quality_opportunities += 1
                a1 = self._aligned(aligned, s1, calendar)
                a2 = self._aligned(aligned, s2, calendar)
                if a1 is None or a2 is None:
                    continue
                feature_quality = 1.0
                if getattr(agent, 'signal_transformer', None) is not None:
                    features = agent.extract_advanced_features(
                        state['spread'].iloc[:i + 1], pair_stats,
                        self.processed_data.get(s1, pd.DataFrame()),
                        self.processed_data.get(s2, pd.DataFrame()),
                        macro_data=self.macro_data, symbol1=s1, symbol2=s2)
                    if agent.scaler_fitted:
                        features = agent.scaler.transform(features.reshape(1, -1)).flatten()
                    feature_quality = agent.score_signal_quality(features)
                signal_strength = min(abs(zscore) / 2.5, 1.0)
                # v32: the z multiplier is applied INSIDE the sizer, before its [3%, 10%]
                # clamp. It used to multiply the clamped size afterwards, so the strongest
                # signals (size > 10%) were vetoed outright by the risk manager's 10% limit
                # and weak ones fell below the 3% floor.
                position_size = self.position_sizer.calculate_optimal_position_size(
                    pair_string, signal_strength, pair_quality, equity,
                    pd.Series(sig['lk_diffs']), risk_scaling_factor=risk_scaling,
                    z_multiplier=min(abs(zscore) / 2.3, 2.0))
                # Liquidity: the smaller leg's 20-day average DOLLAR volume as of today.
                adv_dollars = min(a1['adv'][k] * a1['close_ff'][k], a2['adv'][k] * a2['close_ff'][k])
                market_data = {
                    # locked-spread std (log units); v31 clipped it at 0.25, below the
                    # risk manager's 0.30 limit, so that check could never fire
                    'volatility': float(sig['std']),
                    'volume': float(adv_dollars) if np.isfinite(adv_dollars) else 0.0,
                    'zscore': zscore,
                    'pair_quality': pair_quality,
                    'market_regime': 0,
                }
                ok, why = self.risk_manager.validate_signal(
                    pair_key, action, signal_strength, market_data, position_size, equity, date)
                if not ok:
                    _reject('risk: ' + why.split(':')[0].split(' ')[0].lower())
                    continue
                candidates.append({
                    'pair_key': pair_key, 'pair_string': pair_string, 'action': action,
                    'zscore': zscore, 'signal_strength': signal_strength,
                    'pair_quality': pair_quality, 'feature_quality': feature_quality,
                    'position_size': position_size, 'sig': sig, 'state': state, 'i': i,
                    'pair_stats': pair_stats,
                })

            if k % 50 == 0:
                logger.info(f"Day {pd.Timestamp(date).date()}: {len(candidates)} candidates "
                            f"(signals so far: {quality_opportunities})")

            candidates.sort(key=lambda c: c['signal_strength'] * c['pair_quality'] * c['feature_quality'],
                            reverse=True)

            # 6) Execute the best candidates at the next bar.
            daily_trades = 0
            entry_k = k + 1
            for c in candidates:
                if daily_trades >= self.risk_manager.max_daily_trades:
                    break
                s1, s2 = c['pair_key']
                if s1 in locked or s2 in locked:
                    continue                             # same-day leg collision
                a1, a2 = aligned[s1], aligned[s2]
                e1 = self._fill_price(a1, entry_k, fill_col)
                e2 = self._fill_price(a2, entry_k, fill_col)
                if not (np.isfinite(e1) and np.isfinite(e2)):
                    _reject('no_fill_bar')
                    continue                             # a leg did not trade: no fill
                beta = c['sig']['beta']
                gross = float(c['position_size'])
                exposure_frac = gross / equity
                if open_exposure + exposure_frac > self.risk_manager.max_total_exposure + self.risk_manager.LIMIT_EPS:
                    _reject('gross_exposure_cap')
                    continue
                # Share counts are fixed from the SIGNAL-day close: $1 of leg 1 : $beta of leg 2.
                p1_sig, p2_sig = a1['close_ff'][k], a2['close_ff'][k]
                n1 = gross / (1.0 + beta)
                n2 = gross - n1
                adv1_d, adv2_d = a1['adv'][k] * p1_sig, a2['adv'][k] * p2_sig
                adv_min = min(adv1_d, adv2_d)
                sign = 1.0 if c['action'] == 0 else -1.0     # long spread = long leg 1
                q1 = sign * n1 / p1_sig
                q2 = -sign * n2 / p2_sig
                # Ex-ante cost gate: round trip at signal prices plus borrow/financing over
                # the MAXIMUM hold (calendar days) — never the realised holding period.
                max_hold = self._max_hold_days(c['pair_stats'])
                max_cal_days = int(np.ceil(max_hold * 7 / 5)) + 1
                short_sym, short_notional = (s2, n2) if sign > 0 else (s1, n1)
                est = 2.0 * (self._leg_costs(q1, p1_sig, a1, k)['total'] +
                             self._leg_costs(q2, p2_sig, a2, k)['total'])
                est += self.cost_model.calculate_borrow_cost(short_notional, short_sym, max_cal_days)
                est += self.cost_model.calculate_financing_cost(gross, max_cal_days)
                if est / equity > self.MAX_COST_PCT_OF_EQUITY:
                    _reject('cost_gate')
                    continue

                # Exit: evaluated from the first pair bar after the entry fill.
                state = c['state']
                entry_date = full_dates[entry_k]
                # The first exit test is the first close AFTER the entry-fill date, in both
                # fill modes: PAIRS_FILL=open is a pure fill-PRICE sensitivity (identical
                # signal and exit schedule), so the two runs differ only in execution prices.
                r0 = int(state.index.searchsorted(entry_date, side='right'))
                rows = list(range(r0, min(r0 + max_hold, len(state))))
                j, reason = self._scan_exit(state['lp1'].to_numpy(), state['lp2'].to_numpy(),
                                            rows, c['sig'], c['action'], max_hold)
                if j is not None:
                    exit_signal_k = int(calendar.searchsorted(state.index[rows[j]]))
                    exit_k = exit_signal_k + 1
                    if exit_k > n_cal - 1:
                        exit_k, reason = n_cal - 1, 'end_of_data'
                else:
                    # The pair's history ended before any rule fired (a leg stopped trading or
                    # the data ended): decide on the pair's last bar, fill on the next one.
                    last_row_k = int(calendar.searchsorted(state.index[-1]))
                    exit_signal_k = max(last_row_k, entry_k)
                    exit_k = min(exit_signal_k + 1, n_cal - 1)
                    reason = 'end_of_data'
                if exit_k <= entry_k:
                    continue
                entry_c1 = self._leg_costs(q1, e1, a1, entry_k)
                entry_c2 = self._leg_costs(q2, e2, a2, entry_k)
                t = {
                    'pair': c['pair_string'], 'symbol1': s1, 'symbol2': s2,
                    'q1': q1, 'q2': q2, 'e1': e1, 'e2': e2, 'entry_k': entry_k, 'signal_k': k,
                    'gross_notional': gross, 'exposure_frac': exposure_frac,
                    'equity_at_entry': equity,
                    'entry_cost': entry_c1['total'] + entry_c2['total'],
                    'entry_breakdown': {key: entry_c1[key] + entry_c2[key]
                                        for key in ('commission', 'bid_ask', 'market_impact')},
                    'regime_scale': regime_scale,
                    'leg_daily_vol': float(np.nanmean([a1['dvol'][k], a2['dvol'][k]])),
                    'dvol1': float(a1['dvol'][k]), 'dvol2': float(a2['dvol'][k]),
                    'leg_adv_dollars': float(adv_min) if np.isfinite(adv_min) else None,
                    'adv1_dollars': float(adv1_d) if np.isfinite(adv1_d) and adv1_d > 0 else None,
                    'adv2_dollars': float(adv2_d) if np.isfinite(adv2_d) and adv2_d > 0 else None,
                    'action': c['action'], 'beta': beta, 'zscore': c['zscore'],
                    'signal_strength': c['signal_strength'], 'pair_quality': c['pair_quality'],
                    'feature_quality': c['feature_quality'],
                }
                self._finalise_trade(t, exit_signal_k, exit_k, reason, full_dates, aligned, fill_col)
                open_trades.append(t)
                all_trades.append(t)
                open_exposure += exposure_frac
                locked.update((s1, s2))
                daily_trades += 1
                self.risk_manager.last_trade_dates[c['pair_string']] = date
                self.risk_manager.daily_trade_count = daily_trades
                if len(all_trades) <= 5:
                    logger.info(f"TRADE {len(all_trades)}: {c['pair_string']} "
                                f"{'LONG' if c['action'] == 0 else 'SHORT'} spread  z={c['zscore']:+.2f} "
                                f"beta={beta:.2f} quality={c['pair_quality']:.2f} exit={t['exit_reason']}")
            max_daily_trades_seen = max(max_daily_trades_seen, daily_trades)
            k += 1

        records = [self._trade_record(t, full_dates) for t in all_trades]
        total_costs = float(sum(t['total_cost'] for t in all_trades))
        if regime_counts:
            logger.info(f"Regime gate: {regime_counts.get(1.0, 0)} full-scale days, "
                        f"{sum(c for s, c in regime_counts.items() if s < 1.0)} reduced-scale days, "
                        f"{rejects.get('regime_hard_stop_day', 0)} no-entry (hard-stop) days")
        if rejects:
            logger.info(f"Signal rejections: {dict(sorted(rejects.items()))}")
        out = self._summarise_backtest(records, daily_returns, daily_dates, daily_equity,
                                       total_costs, quality_opportunities, max_daily_trades_seen,
                                       last_trade_k - first_k + 1, halted_on=halted_on,
                                       halt_reason=halt_reason, rejects=rejects)
        out.update(self._utilisation_metrics(records, daily_returns, daily_gross, daily_equity))
        # Daily decomposition (net = gross - costs, both per previous-day equity) for the
        # cost-sensitivity and implementation-shortfall diagnostics (anatomy.py).
        out.update({'daily_gross_returns': daily_gross_ret, 'daily_cost_returns': daily_cost_ret,
                    'daily_gross_exposure': daily_gross, 'daily_open_positions': daily_positions})
        return out

    def _utilisation_metrics(self, trades, daily_returns, daily_gross, daily_equity) -> Dict:
        """Capital utilisation: returns on committed capital hide how little is deployed.

        avg/max gross exposure (fraction of equity), annual turnover (traded notional /
        average equity, entry and exit both count), return on average gross exposure
        (total P&L / (initial capital x average gross)), mean holding period and the
        mean, over trades, of the larger leg participation (leg notional / that leg's own
        dollar ADV).
        """
        n = len(daily_returns)
        if n == 0:
            return {'avg_gross_exposure': 0.0, 'max_gross_exposure': 0.0, 'annual_turnover': 0.0,
                    'return_on_gross_exposure': None, 'avg_trading_days_held': 0.0,
                    'avg_max_leg_adv_participation': None}
        g = np.asarray(daily_gross, dtype=float)
        avg_g = float(g.mean())
        traded = 2.0 * sum(t['position_size'] for t in trades)
        avg_eq = float(np.mean(daily_equity)) if daily_equity else float(self.initial_capital)
        total_pnl = (daily_equity[-1] - self.initial_capital) if daily_equity else 0.0
        # each leg's notional against its OWN dollar ADV; the worse leg per trade
        parts = [max(t['long_notional'] / t['long_adv_dollars'], t['short_notional'] / t['short_adv_dollars'])
                 for t in trades if t.get('long_adv_dollars') and t.get('short_adv_dollars')]
        return {
            'avg_gross_exposure': avg_g,
            'max_gross_exposure': float(g.max()),
            'annual_turnover': traded / avg_eq * TRADING_DAYS_PER_YEAR / n,
            'return_on_gross_exposure': (total_pnl / (self.initial_capital * avg_g)) if avg_g > 0 else None,
            'avg_trading_days_held': float(np.mean([t['trading_days_held'] for t in trades])) if trades else 0.0,
            'avg_max_leg_adv_participation': float(np.mean(parts)) if parts else None,
            'daily_gross_exposure': list(g),
        }

    def _trade_record(self, t: Dict, full_dates: List) -> Dict:
        """Public trade record (exported / replayed) built from an internal trade."""
        eq0 = t['equity_at_entry']
        long_is_1 = t['q1'] > 0
        n1 = abs(t['q1']) * t['e1']
        n2 = abs(t['q2']) * t['e2']
        return {
            'date': full_dates[t['entry_k']],                 # t+1 entry fill date
            'signal_date': full_dates[t['signal_k']],
            'exit_signal_date': full_dates[t['exit_signal_k']] if t['exit_signal_k'] >= 0 else None,
            'exit_date': full_dates[t['exit_k']],             # exit fill date
            'exit_reason': t['exit_reason'],
            'exit_prices_real': t['exit_prices_real'],
            'pair': t['pair'],
            'action': 'LONG' if t['action'] == 0 else 'SHORT',
            'long_symbol': t['symbol1'] if long_is_1 else t['symbol2'],
            'short_symbol': t['symbol2'] if long_is_1 else t['symbol1'],
            'long_notional': n1 if long_is_1 else n2,
            'short_notional': n2 if long_is_1 else n1,
            'hedge_ratio': t['beta'],
            'regime_scale': t['regime_scale'],
            'leg_daily_vol': t['leg_daily_vol'],
            'leg_adv_dollars': t['leg_adv_dollars'],
            'long_adv_dollars': t.get('adv1_dollars') if long_is_1 else t.get('adv2_dollars'),
            'long_daily_vol': t.get('dvol1') if long_is_1 else t.get('dvol2'),
            'short_daily_vol': t.get('dvol2') if long_is_1 else t.get('dvol1'),
            'short_adv_dollars': t.get('adv2_dollars') if long_is_1 else t.get('adv1_dollars'),
            'position_size': t['gross_notional'],
            'position_pct': t['exposure_frac'],
            'signal_strength': t['signal_strength'],
            'zscore': t['zscore'],
            'pair_quality': t['pair_quality'],
            'feature_quality': t['feature_quality'],
            'spread_return': t['gross_pnl_dollars'] / t['gross_notional'],
            'gross_pnl_pct': t['gross_pnl_dollars'] / eq0,
            'transaction_costs': t['total_cost'],
            'transaction_cost_pct': t['total_cost'] / eq0,
            'net_pnl_pct': t['net_pnl_dollars'] / eq0,
            'pnl_dollar': t['net_pnl_dollars'],
            'holding_days': t['calendar_days'],
            'trading_days_held': t['exit_k'] - t['entry_k'],
            'cost_breakdown': t['cost_breakdown'],
            # Daily MTM path per $1 of gross notional (costs excluded), for the fund replay.
            'unit_path': [(str(pd.Timestamp(full_dates[kk]).date()), v / t['gross_notional'])
                          for kk, v in sorted(t['path'].items())],
        }

    def _summarise_backtest(self, trades, daily_returns, daily_dates, daily_equity, total_costs,
                            quality_opportunities, max_daily_trades, n_trade_days,
                            halted_on=None, halt_reason='', rejects=None) -> Dict:
        r = np.asarray(daily_returns, dtype=float)
        final_equity = daily_equity[-1] if daily_equity else float(self.initial_capital)
        total_return = final_equity / self.initial_capital - 1.0
        n_trades = len(trades)
        exit_reasons: Dict[str, int] = {}
        if n_trades:
            nets = np.array([t['net_pnl_pct'] for t in trades], dtype=float)
            wins, losses = nets[nets > 0], nets[nets < 0]
            win_rate = len(wins) / n_trades
            avg_win = float(wins.mean()) if len(wins) else 0.0
            avg_loss = float(np.abs(losses).mean()) if len(losses) else 0.0
            # sum of wins / sum of losses; +inf with no losing trade (exported as null)
            profit_factor = float(wins.sum() / np.abs(losses).sum()) if len(losses) else float('inf')
            avg_cost_pct = float(np.mean([t['transaction_cost_pct'] for t in trades]))
            for t in trades:
                exit_reasons[t['exit_reason']] = exit_reasons.get(t['exit_reason'], 0) + 1
        else:
            win_rate = avg_win = avg_loss = profit_factor = avg_cost_pct = 0.0
        n_days = len(daily_returns)
        return {
            'total_return': total_return,
            'annualized_return': geometric_annualised_return(total_return, n_days),
            'final_portfolio_value': final_equity,
            'total_trades': n_trades,
            'trade_count': n_trades,
            'trades_per_day': n_trades / n_trade_days if n_trade_days else 0.0,
            'max_daily_trades': max_daily_trades,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'sharpe_ratio': annualised_sharpe(r),
            'max_drawdown': max_drawdown_from_returns(r),
            'volatility': float(r.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)) if r.size > 1 else 0.0,
            'total_transaction_costs': total_costs,
            'total_cost_impact_pct': total_costs / self.initial_capital,
            'avg_cost_per_trade': total_costs / n_trades if n_trades else 0.0,
            'avg_cost_pct_per_trade': avg_cost_pct,
            'quality_opportunities': quality_opportunities,
            'avg_signal_strength': float(np.mean([t['signal_strength'] for t in trades])) if trades else 0.0,
            'avg_pair_quality': float(np.mean([t['pair_quality'] for t in trades])) if trades else 0.0,
            'high_quality_trades': sum(1 for t in trades if t.get('feature_quality', 0) > 0.7),
            'avg_trade_return': float(np.mean([t['net_pnl_pct'] for t in trades])) if trades else 0.0,
            'exit_reasons': exit_reasons,
            'trades': trades,
            'daily_pnl': list(daily_returns),
            'daily_returns': list(daily_returns),
            'daily_dates': [str(pd.Timestamp(d).date()) for d in daily_dates],
            'equity_curve': list(daily_equity),
            'test_period_days': n_trade_days,
            'halted_on': str(pd.Timestamp(halted_on).date()) if halted_on is not None else None,
            'halt_reason': halt_reason,
            'signal_rejections': dict(sorted((rejects or {}).items())),
        }

    def _calculate_max_drawdown(self, returns: np.ndarray) -> float:
        """Maximum drawdown of a daily return series (<= 0)."""
        return max_drawdown_from_returns(returns)

    # ════════════════════════════════════════════════════════════════════════════
    # Ranking-model training samples (labels = the actual trading rule)
    # ════════════════════════════════════════════════════════════════════════════

    def build_outcome_samples(self, pairs: List[Tuple[str, str]], end, start=None,
                              agent: FixedTransformerMultiAgentSystem = None,
                              step: int = None, max_samples: int = None, seed: int = 0,
                              signal_end=None):
        """Feature/label samples for the signal-quality ranker from data in [start, end].

        A sample is a pair-day on which the ACTUAL entry rule fires (beta-locked
        |z| >= ENTRY_Z, after any enabled CUSUM/Hurst gate). Its label is 1 if the trade the
        engine would open — hedge-ratio-weighted legs, filled at the next close, exited by
        the same target/stop/time rule and filled at the close after that — has a positive
        gross return, else 0. Only samples whose whole outcome (exit fill included) lies
        on or before `end` are kept, so no label reads past the training window.
        `signal_end` (evaluation only) additionally caps the signal date, so a test
        window's signals can be scored with outcomes that finish after the window.

        v32: through v31 the ranker learned a different target (an expanding-window z of
        the Kalman residual reaching |z| < 0.5 within 10 days) from features extracted
        with EMPTY stock frames and no macro data — constant values at training time for
        14 of the then-38 inputs (30 real + 8 zero pads) that are live at inference.

        Returns (X_raw, y) with X_raw the unscaled N_FEATURES (30) matrix, or (None, None).
        """
        agent = agent or self.rl_agent
        step = step or self.LABEL_STEP
        max_samples = max_samples or self.LABEL_MAX_SAMPLES
        points = []
        for s1, s2 in pairs:
            state = self.get_pair_state(s1, s2)
            if state.empty:
                continue
            like = state.index[0]
            end_ts = _align_ts(end, like)
            last = int(state.index.searchsorted(end_ts, side='right')) - 1
            first = self.MIN_SPREAD_HISTORY - 1
            if start is not None:
                first = max(first, int(state.index.searchsorted(_align_ts(start, like), side='left')))
            stop = last - 2
            if signal_end is not None:
                stop = min(stop, int(state.index.searchsorted(_align_ts(signal_end, like), side='right')))
            lp1, lp2 = state['lp1'].to_numpy(), state['lp2'].to_numpy()
            for i in range(first, stop, step):
                pair_stats = self._pair_stats_asof(f"{s1}-{s2}", state.index[i])
                max_hold = self._max_hold_days(pair_stats)
                beta = state['beta'].iat[i]
                if not (self.BETA_MIN <= beta <= self.BETA_MAX):
                    continue
                sig, _ = self._locked_signal(state, i, pair_stats)
                if sig is None or abs(sig['z']) < self.ENTRY_Z:
                    continue
                action = 0 if sig['z'] < 0 else 2
                entry = i + 1
                rows = list(range(entry + 1, min(entry + 1 + max_hold, last + 1)))
                j, _ = self._scan_exit(lp1, lp2, rows, sig, action, max_hold)
                if j is None or rows[j] + 1 > last:
                    continue                          # outcome not complete inside the window
                x = rows[j] + 1                       # exit fill: the next bar's close
                n1 = 1.0 / (1.0 + beta)
                n2 = 1.0 - n1
                sign = 1.0 if action == 0 else -1.0
                ret = sign * (n1 * (np.exp(lp1[x] - lp1[entry]) - 1.0)
                              - n2 * (np.exp(lp2[x] - lp2[entry]) - 1.0))
                points.append((s1, s2, i, 1.0 if ret > 0 else 0.0))
        if not points:
            return None, None
        if len(points) > max_samples:                  # uniform, deterministic subsample
            rng = np.random.default_rng(seed)
            keep = np.sort(rng.choice(len(points), size=max_samples, replace=False))
            points = [points[p] for p in keep]
        X, y = [], []
        for s1, s2, i, label in points:
            state = self.get_pair_state(s1, s2)
            X.append(agent.extract_advanced_features(
                state['spread'].iloc[:i + 1], self._pair_stats_asof(f"{s1}-{s2}", state.index[i]),
                self.processed_data.get(s1, pd.DataFrame()), self.processed_data.get(s2, pd.DataFrame()),
                macro_data=self.macro_data, symbol1=s1, symbol2=s2))
            y.append(label)
        return np.asarray(X, dtype=np.float32), np.asarray(y, dtype=np.float32)

    def _train_ranker(self, agent: FixedTransformerMultiAgentSystem, pairs, end, start=None) -> None:
        agent.pair_statistics = self.pair_selector.pair_statistics
        if agent.ranker == 'none':
            logger.info("Ranker: none — classical-only ranking (quality = 1.0)")
            return
        X, y = self.build_outcome_samples(pairs, end=end, start=start, agent=agent)
        agent.train_on_samples(X, y)

    RANKER_EVAL_MAX_SAMPLES = 4000

    def _ranker_oos_scores(self, agent: FixedTransformerMultiAgentSystem, pairs, start,
                           signal_end=None, end=None):
        """(p, y) for signals dated in [start, signal_end] on `pairs`, or (None, None).

        Out-of-sample by construction: `start` is after the model's training window.
        Outcomes may finish after `signal_end` (up to `end`, default the last bar);
        this is ex-post measurement only and never feeds back into trading.
        """
        if agent.signal_transformer is None or not pairs:
            return None, None
        end = end if end is not None else max(self.get_pair_state(*pk).index[-1] for pk in pairs)
        X, y = self.build_outcome_samples(pairs, end=end, start=start, agent=agent,
                                          signal_end=signal_end,
                                          max_samples=self.RANKER_EVAL_MAX_SAMPLES, seed=1)
        if X is None:
            return None, None
        return agent.predict_raw(X), y

    # ════════════════════════════════════════════════════════════════════════════
    # Walk-forward validation
    # ════════════════════════════════════════════════════════════════════════════

    def run_walk_forward_validation(self, train_window_days: int = 252, test_window_days: int = 63,
                                    episodes_per_window: int = None, pair_windows: Dict = None,
                                    pair_selection_cutoff: str = None) -> Dict:
        """Walk-forward validation as ONE continuous out-of-sample simulation.

        The calendar is cut into 252-day train / 63-day test windows. For every window
        whose train period ends on or after the first quarterly re-selection (earlier
        slots have no pair universe known at that time and are skipped), a fresh ranking
        model is trained on that window's train period only. The strategy is then run
        continuously from the first eligible test day to the last: the ranking model in
        force is the one trained for the current window, the tradeable pairs are the
        latest re-selection dated <= each day (exactly as in the main backtest), and
        positions carry across window boundaries, as they would in a live book.
        Per-window statistics are calendar slices of that single daily series.

        v32: through v31 each window was an independent 63-day backtest on spreads
        truncated at the window end, so a position opened in a window's last ~25 days
        that had not reverted by the window end had no bar to exit on and was silently
        discarded (a forward-looking winner filter), and each window traded the union of
        every re-selection so far — including pairs later re-tested and dropped.

        `episodes_per_window` is accepted for backward compatibility and ignored.
        `pair_selection_cutoff` defaults to the calendar's.
        """
        pair_selection_cutoff = pair_selection_cutoff or self.calendar.selection_cutoff
        logger.info("=" * 60)
        logger.info("WALK-FORWARD VALIDATION (continuous OOS simulation, per-window refits)")
        logger.info(f"  Train window: {train_window_days} days | Test window: {test_window_days} days")
        logger.info("=" * 60)

        universe = pair_windows if pair_windows else {None: self.spread_data}
        all_pairs = sorted({pk for ws in universe.values() for pk in ws})
        cal = set()
        for pk in all_pairs:
            cal.update(self.get_pair_state(*pk).index)
        all_dates = sorted(cal)
        if len(all_dates) < train_window_days + test_window_days:
            logger.warning("Insufficient data for walk-forward validation")
            return {}

        windows = []
        idx = 0
        while idx + train_window_days + test_window_days <= len(all_dates):
            windows.append((all_dates[idx], all_dates[idx + train_window_days - 1],
                            all_dates[idx + train_window_days],
                            all_dates[idx + train_window_days + test_window_days - 1]))
            idx += test_window_days
        logger.info(f"Walk-forward grid: {len(windows)} windows")

        resel_sorted = sorted(k for k in universe if k is not None)
        first_resel = _naive(resel_sorted[0]) if resel_sorted else None
        schedule, eligible, agents = [], [], []
        for w_idx, (tr_s, tr_e, te_s, te_e) in enumerate(windows):
            if first_resel is not None and _naive(tr_e) < first_resel:
                logger.info(f"  Window {w_idx + 1}: no pair universe selected by "
                            f"{pd.Timestamp(tr_e).date()} — skipped")
                continue
            visible = sorted({pk for key, ws in universe.items()
                              if key is None or _naive(key) <= _naive(tr_e) for pk in ws})
            agent = self._new_ranker()
            self._train_ranker(agent, visible, end=tr_e, start=tr_s)
            schedule.append((te_s, agent))
            eligible.append((w_idx, tr_s, tr_e, te_s, te_e))
            agents.append((agent, visible))

        if not eligible:
            logger.warning("Walk-forward: no eligible windows")
            return {}

        result = self.run_comprehensive_backtest(
            self.spread_data, pair_windows=pair_windows,
            date_range=(eligible[0][3], eligible[-1][4]), model_schedule=schedule)
        dates = [pd.Timestamp(d) for d in result['daily_dates']]
        rets = np.asarray(result['daily_returns'], dtype=float)
        trades = result['trades']

        # Out-of-sample skill of each window's ranker on its own test-window signals
        # (labels may finish after the window). Pooled across windows, this is the one
        # direct measure of whether the learned score carries information.
        pooled_p, pooled_y, ranker_windows = [], [], []
        for (agent, visible), (w_idx, _, _, te_s, te_e) in zip(agents, eligible):
            p, y = self._ranker_oos_scores(agent, visible, start=te_s, signal_end=te_e)
            ranker_windows.append(None if p is None else classifier_skill(
                y, p, agent.training_summary.get('base_rate')))
            if p is not None:
                pooled_p.append(p)
                pooled_y.append(y)

        wf_results = []
        for n_w, (w_idx, tr_s, tr_e, te_s, te_e) in enumerate(eligible):
            lo_d, hi_d = _naive(te_s), _naive(te_e)
            is_last = n_w == len(eligible) - 1
            mask = np.array([(d >= lo_d) and (is_last or d <= hi_d) for d in dates], dtype=bool)
            w_r = rets[mask]
            w_trades = [t for t in trades if lo_d <= _naive(t['signal_date']) <= hi_d]
            w_ret = float(np.prod(1.0 + w_r) - 1.0) if w_r.size else 0.0
            wf_results.append({
                'window': w_idx + 1,
                'train_start': str(pd.Timestamp(tr_s).date()),
                'train_end': str(pd.Timestamp(tr_e).date()),
                'test_start': str(pd.Timestamp(te_s).date()),
                'test_end': str(pd.Timestamp(te_e).date()),
                'selection_clean': str(pd.Timestamp(te_s).date()) > pair_selection_cutoff,
                'n_days': int(w_r.size),
                'total_return_pct': round(w_ret * 100, 4),
                'sharpe_ratio': round(annualised_sharpe(w_r), 3),
                'max_drawdown_pct': round(max_drawdown_from_returns(w_r) * 100, 4),
                'total_trades': len(w_trades),
                'win_rate_pct': round(100.0 * sum(1 for t in w_trades if t['net_pnl_pct'] > 0)
                                      / len(w_trades), 2) if w_trades else 0.0,
                'ranker_trained': agents[n_w][0].signal_transformer is not None,
                'ranker_train_samples': int(agents[n_w][0].training_summary.get('n_samples', 0)),
                'ranker_oos': ranker_windows[n_w],
            })
            logger.info(f"  Window {w_idx + 1}: test {pd.Timestamp(te_s).date()} -> "
                        f"{pd.Timestamp(te_e).date()} | return {w_ret:+.2%} | "
                        f"Sharpe {annualised_sharpe(w_r):+.2f} | trades {len(w_trades)}")

        window_returns = [w['total_return_pct'] / 100.0 for w in wf_results]
        n_clean = sum(1 for w in wf_results if w['selection_clean'])
        summary = {
            'windows': wf_results,
            'total_windows': len(wf_results),
            'skipped_windows': len(windows) - len(eligible),
            'selection_clean_windows': n_clean,
            'pair_selection_cutoff': pair_selection_cutoff,
            'profitable_windows': sum(1 for x in window_returns if x > 0),
            'profitable_window_pct': round(100.0 * sum(1 for x in window_returns if x > 0)
                                           / len(window_returns), 1),
            'avg_window_return_pct': round(float(np.mean(window_returns)) * 100, 4),
            'median_window_return_pct': round(float(np.median(window_returns)) * 100, 4),
            # Mean of per-window annualised Sharpes — NOT a portfolio Sharpe (see pooled).
            'avg_sharpe': round(float(np.mean([w['sharpe_ratio'] for w in wf_results])), 3),
            'stitched_total_return_pct': round(result['total_return'] * 100, 4),
            'pooled_sharpe': round(annualised_sharpe(rets), 3) if rets.size > 1 else None,
            'oos_pooled_sharpe': round(annualised_sharpe(rets), 3) if rets.size > 1 else None,
            'max_drawdown_pct': round(result['max_drawdown'] * 100, 4),
            'total_trades': result['total_trades'],
            'win_rate_pct': round(result['win_rate'] * 100, 2),
            'exit_reasons': result.get('exit_reasons', {}),
            'oos_window_sharpe_var': float(np.var([w['sharpe_ratio'] for w in wf_results], ddof=1))
            if len(wf_results) > 1 else 0.0,
            'oos_start': wf_results[0]['test_start'],
            'oos_end': result['daily_dates'][-1] if result['daily_dates'] else None,
            'halted_on': result.get('halted_on'),
            'windows_with_trained_ranker': sum(1 for a, _ in agents if a.signal_transformer is not None),
            'ranker_oos_pooled': classifier_skill(np.concatenate(pooled_y), np.concatenate(pooled_p))
            if pooled_p else None,
            # Continuous OOS daily series (popped before JSON export by the caller).
            'oos_daily_returns': list(rets),
            'oos_daily_dates': list(result['daily_dates']),
            'all_window_daily_returns': list(rets),
            'oos_daily_detail': {k: list(result.get(k, [])) for k in (
                'daily_gross_returns', 'daily_cost_returns', 'daily_gross_exposure',
                'daily_open_positions')},
        }
        logger.info("=" * 60)
        logger.info("WALK-FORWARD SUMMARY")
        logger.info(f"  Windows: {summary['total_windows']} traded, {summary['skipped_windows']} skipped "
                    f"(no universe yet) | profitable: {summary['profitable_windows']} "
                    f"({summary['profitable_window_pct']}%)")
        logger.info(f"  Avg window return: {summary['avg_window_return_pct']:.4f}% | "
                    f"median {summary['median_window_return_pct']:.4f}%")
        logger.info(f"  Pooled OOS Sharpe: {summary['pooled_sharpe']} | mean of per-window "
                    f"Sharpes: {summary['avg_sharpe']:.3f} (not a portfolio Sharpe)")
        logger.info(f"  Continuous OOS return: {summary['stitched_total_return_pct']:.4f}% | "
                    f"max DD {summary['max_drawdown_pct']:.2f}% | trades {summary['total_trades']}")
        logger.info(f"  Selection-clean windows: {n_clean}/{len(wf_results)} "
                    f"(test start after the pair-selection cutoff {pair_selection_cutoff})")
        logger.info("=" * 60)
        return summary

    # ════════════════════════════════════════════════════════════════════════════
    # Quarterly pair re-selection
    # ════════════════════════════════════════════════════════════════════════════

    def build_rolling_pair_schedule(self, all_test_dates: list, reselect_every: int = None) -> Dict:
        """Periodic re-selection of the tradeable pairs (the profile's scheme).

        Every `reselect_every` trading days (default: the profile's), on the trailing
        window of profile.formation_calendar_days ending on the re-selection date:
          pool  the candidate pairs selected at the pair-selection cutoff are re-tested
                (v32: 2-year window), plus a recent-window check (126 calendar days,
                ~87 trading days); no new pair can enter.
          full  the complete selection is re-run (v33: 3-year window, every 126 days).
        Everything uses data dated <= the re-selection date.
        """
        reselect_every = reselect_every or self.profile.reselect_every
        window_days = self.profile.formation_calendar_days
        logger.info(f"Building the pair schedule (every {reselect_every} trading days, "
                    f"{window_days}-calendar-day formation window)...")
        schedule_dates = [all_test_dates[i] for i in range(0, len(all_test_dates), reselect_every)]
        candidate_pairs = list(self.spread_data.keys())
        full_search = self.profile.reselect == 'full'
        if full_search:
            logger.info("  Re-selection 'full': the complete pair search is re-run on each trailing "
                        "window (new pairs can enter; runtime scales with the universe)")
        else:
            logger.info(f"  Candidate pool: {len(candidate_pairs)} pairs selected on data to "
                        f"{self.calendar.selection_cutoff} (re-tested only; no new pairs can enter)")

        pair_windows = {}
        for resel_date in schedule_dates:
            if full_search:
                pair_windows[resel_date] = self._full_reselection(resel_date)
                continue
            kept = dropped_recent = 0
            window_spreads, window_stats = {}, {}
            for sym1, sym2 in candidate_pairs:
                d1, d2 = self.processed_data.get(sym1), self.processed_data.get(sym2)
                if d1 is None or d2 is None:
                    continue
                cut = _align_ts(resel_date, d1.index[0])
                w1 = d1[(d1.index > cut - pd.Timedelta(days=window_days)) & (d1.index <= cut)]
                w2 = d2[(d2.index > cut - pd.Timedelta(days=window_days)) & (d2.index <= cut)]
                if len(w1) < 100 or len(w2) < 100:
                    continue
                is_coint, p_long = self.pair_selector.test_cointegration(w1, w2)
                if not is_coint:
                    continue
                # Recent-window check (v8 design, 126 calendar days ~ 87 trading days; the
                # comments through v31 called this "6 months / n=90"). v32: legs aligned on
                # common DATES (was positional truncation) and the p-value is the same
                # two-direction Bonferroni p as the 2-year test (was the invalid min-p).
                recent_start = cut - pd.Timedelta(days=126)
                # Same row filter as the 2-year test (common dates with finite, positive
                # closes): a single missing close used to reach coint as a NaN, make the
                # p-value 1.0 and silently drop the pair.
                lp1_r, lp2_r = self.pair_selector._aligned_log_prices(
                    w1.loc[w1.index >= recent_start], w2.loc[w2.index >= recent_start])
                if len(lp1_r) >= 60:
                    # The v8 threshold (min-p > 0.15) restated on the Bonferroni scale
                    # p = 2 * min-p; see RESEL_RECENT_MAX_P for its measured power.
                    p_recent = self.pair_selector.cointegration_pvalue(lp1_r, lp2_r)
                    if p_recent > self.RESEL_RECENT_MAX_P:
                        dropped_recent += 1
                        continue           # no recent evidence of cointegration
                spread = self._pair_spread(sym1, sym2)
                if not spread.empty:
                    window_spreads[(sym1, sym2)] = spread
                    kept += 1
                    # v32: re-estimate the statistics that drive the z window, time stop,
                    # quality gate and ranking on the same trailing 2-year window (they were
                    # frozen at their 2020-2022 values through 2025).
                    pstr = f"{sym1}-{sym2}"
                    base = self.pair_selector.pair_statistics.get(pstr, {})
                    corr = self.pair_selector.calculate_correlation(w1, w2)
                    hl = self.pair_selector.calculate_half_life(w1, w2)
                    quality = self.pair_selector._calculate_balanced_quality_score(
                        corr, p_long, hl, w1, w2, pca_cointegrated=bool(base.get('pca_cointegrated', False)))
                    window_stats[pstr] = {'correlation': corr, 'cointegration_pvalue': p_long,
                                          'half_life': hl, 'quality_score': quality,
                                          'pca_cointegrated': bool(base.get('pca_cointegrated', False))}
            logger.info(f"  {pd.Timestamp(resel_date).date()}: kept {kept}/{len(candidate_pairs)} "
                        f"(126-day check dropped {dropped_recent})")
            pair_windows[resel_date] = window_spreads
            self.pair_window_stats[resel_date] = window_stats
        self._index_window_stats()
        logger.info(f"Quarterly schedule built: {len(pair_windows)} re-selections")
        return pair_windows

    def _full_reselection(self, resel_date) -> Dict:
        """Run the complete selection on the trailing formation window ending at resel_date."""
        window_days = self.profile.formation_calendar_days
        members = self._formation_members(resel_date)
        window_data = {}
        for sym, df in self.processed_data.items():
            if len(df.index) == 0 or (members is not None and sym not in members):
                continue
            w = formation_window(df, resel_date, window_days)
            if len(w) >= 100:
                window_data[sym] = w
        selector = self._new_pair_selector()
        pairs = selector.find_quality_pairs(window_data)
        spreads = {p: self._pair_spread(*p) for p in pairs}
        spreads = {p: sp for p, sp in spreads.items() if not sp.empty}
        self.pair_window_stats[resel_date] = {f"{a}-{b}": selector.pair_statistics[f"{a}-{b}"]
                                              for a, b in spreads}
        logger.info(f"  {pd.Timestamp(resel_date).date()}: full search selected {len(spreads)} pairs")
        return spreads

    def _index_window_stats(self) -> None:
        keys = sorted(self.pair_window_stats, key=_naive)
        self._window_stats_index = (np.array([np.datetime64(_naive(k)) for k in keys]),
                                    [self.pair_window_stats[k] for k in keys]) if keys else None

    # ════════════════════════════════════════════════════════════════════════════
    # Cost-schedule replay
    # ════════════════════════════════════════════════════════════════════════════

    def run_fund_type_comparison(self, main_results: Dict, main_daily_dates: list = None) -> Dict:
        """Replay the main backtest's trades under five archetypal cost/sizing schedules.

        Signals, entry/exit dates and each trade's daily mark-to-market path (per $1 of
        gross notional) are taken from the main backtest; only the economics change:
        position size = profile base % x min(|z|/2.3, 2), capped at the profile max, of
        the profile's own equity at the previous close; at most the profile's
        max_daily_trades new trades per day (main-backtest ranking order); and the
        profile's cost schedule (execution costs split between entry and exit, borrow and
        financing at exit), with market impact from each trade's own volatility and ADV. Each profile's equity is marked to market daily on the main
        backtest calendar; a drawdown beyond the profile limit stops new trades and
        flattens open ones at the next bar.

        The replay does NOT model concurrency limits or margin: the leverage labels are
        descriptive, and the realised peak gross leverage is reported per profile as
        'max_gross_leverage' so the reader can see what was actually run.
        """
        from pairs_trading.fund_profiles import FUND_PROFILES, get_profile_summary_table
        from pairs_trading.transaction_costs import calculate_profile_trade_costs

        logger.info(get_profile_summary_table())
        trades = [t for t in main_results.get('trades', []) if t.get('unit_path')]
        if not trades:
            logger.warning("Fund comparison: no trades in main results, skipping.")
            return {}
        calendar = list(main_daily_dates or main_results.get('daily_dates') or
                        sorted({d for t in trades for d, _ in t['unit_path']}))
        cal_pos = {d: i for i, d in enumerate(calendar)}
        # A trade whose marked dates are not all on the calendar would have part of its P&L
        # silently dropped (the v31.1 DST bug did exactly that); fail loudly instead.
        off = [t for t in trades if any(d not in cal_pos for d, _ in t['unit_path'])]
        if off:
            raise ValueError(f"fund replay: {len(off)} trade(s) have mark-to-market dates off the "
                             f"main calendar (first: {off[0]['pair']} {off[0]['unit_path'][0][0]})")
        by_entry: Dict[str, List[Dict]] = {}
        for t in trades:
            by_entry.setdefault(t['unit_path'][0][0], []).append(t)

        SOFR = 0.050
        comparison = {}
        for profile_key, profile in FUND_PROFILES.items():
            equity = float(self.initial_capital)
            peak = equity
            max_dd = 0.0
            stopped_on = None
            active: List[Dict] = []
            done: List[Dict] = []
            daily_r, curve = [], []
            max_gross = 0.0
            cost_totals = {k: 0.0 for k in ('commission', 'bid_ask', 'market_impact', 'borrow', 'financing')}
            for d in calendar:
                eq_prev = equity
                pnl = 0.0
                if stopped_on is None:
                    # The profile's own daily entry limit (main-backtest ranking order).
                    for t in by_entry.get(d, [])[:profile.max_daily_trades]:
                        z_mult = min(abs(t['zscore']) / 2.3, 2.0)
                        # the market-regime scale the main trade was taken at applies to every
                        # profile (the book-specific vol/profit scaling does not)
                        frac = min(profile.base_position_pct * z_mult, profile.max_position_pct) \
                            * float(t.get('regime_scale', 1.0))
                        G = frac * eq_prev
                        g0 = t['long_notional'] + t['short_notional']
                        lv = G * t['long_notional'] / g0 if g0 > 0 else G / 2
                        c = calculate_profile_trade_costs(
                            G, profile, max(1, int(t['holding_days'])), SOFR,
                            long_symbol=t['long_symbol'], short_symbol=t['short_symbol'],
                            long_value=lv, short_value=G - lv,
                            daily_volatility=t.get('leg_daily_vol'), adv_dollars=t.get('leg_adv_dollars'),
                            long_adv_dollars=t.get('long_adv_dollars'), short_adv_dollars=t.get('short_adv_dollars'),
                            long_daily_vol=t.get('long_daily_vol'), short_daily_vol=t.get('short_daily_vol'))
                        half_ex = 0.5 * (c['commission'] + c['bid_ask'] + c['market_impact'])
                        a = {'G': G, 'path': dict(t['unit_path']), 'exit': t['unit_path'][-1][0],
                             'entry_cost': half_ex,
                             'exit_cost': half_ex + c['borrow'] + c['financing'],
                             'gross': 0.0, 'costs': c}
                        pnl -= a['entry_cost']
                        active.append(a)
                still = []
                for a in active:
                    move = a['path'].get(d, 0.0) * a['G']
                    pnl += move
                    a['gross'] += move
                    if a['exit'] == d:
                        pnl -= a['exit_cost']
                        a['net'] = a['gross'] - a['entry_cost'] - a['exit_cost']
                        for key in cost_totals:
                            cost_totals[key] += a['costs'][key]
                        done.append(a)
                    else:
                        still.append(a)
                active = still
                max_gross = max(max_gross, sum(a['G'] for a in active) / max(eq_prev, 1.0))
                equity += pnl
                daily_r.append(pnl / eq_prev if eq_prev > 0 else 0.0)
                curve.append((d, equity))
                peak = max(peak, equity)
                dd = (peak - equity) / peak if peak > 0 else 0.0
                max_dd = max(max_dd, dd)
                if stopped_on is None and dd >= profile.max_drawdown_limit:
                    stopped_on = d
                    logger.warning(f"  {profile.name}: kill-switch at {dd:.2%} drawdown on {d} — "
                                   f"no new trades; open positions closed at the next bar")
                    nxt_i = cal_pos.get(d, len(calendar) - 1) + 1
                    nxt = calendar[nxt_i] if nxt_i < len(calendar) else d
                    for a in active:
                        a['path'] = {day: v for day, v in a['path'].items()
                                     if cal_pos.get(day, 0) <= cal_pos.get(nxt, 0)}
                        a['exit'] = nxt
            if active:
                logger.error(f"  {profile.name}: {len(active)} trade(s) never reached their exit date")
            closed = done
            n_trades = len(closed)
            nets = np.array([a['net'] for a in closed], dtype=float)
            wins, losses = nets[nets > 0], nets[nets < 0]
            total_return = equity / self.initial_capital - 1.0
            r = np.asarray(daily_r, dtype=float)
            total_cost_dollars = float(sum(cost_totals.values()))
            comparison[profile_key] = {
                'profile_key': profile_key,
                'profile_name': profile.name,
                'description': profile.description,
                'max_gross_leverage': round(max_gross, 3),
                'commission_bps': profile.commission_bps,
                'bid_ask_bps': profile.bid_ask_bps,
                'market_impact_cap_bps': profile.market_impact_cap_bps,
                'borrow_rate_gc_pct': profile.borrow_rate_general * 100,
                # sum of the replayed trades' net P&L; equals final equity minus capital when
                # every replayed trade closed inside the calendar (reconciliation check)
                'replayed_net_pnl': round(float(nets.sum()), 2),
                'unclosed_trades': len(active),
                'financing_spread_pct': profile.financing_spread * 100,
                'base_position_pct': profile.base_position_pct * 100,
                'max_position_pct': profile.max_position_pct * 100,
                'max_drawdown_limit_pct': profile.max_drawdown_limit * 100,
                'total_return_pct': round(total_return * 100, 4),
                'annualized_return_pct': round(geometric_annualised_return(total_return, len(r)) * 100, 4),
                'final_equity': round(equity, 2),
                'max_drawdown_pct': round(-max_dd * 100, 4),
                'sharpe_ratio': round(annualised_sharpe(r), 3),
                'win_rate_pct': round(100.0 * len(wins) / n_trades, 2) if n_trades else 0.0,
                'profit_factor': round(float(wins.sum() / abs(losses.sum())), 3) if len(losses) else float('inf'),
                'total_trades': n_trades,
                'trades_stopped_early': stopped_on is not None,
                'stopped_on': stopped_on,
                'total_cost_dollars': round(total_cost_dollars, 2),
                'total_cost_pct_of_capital': round(total_cost_dollars / self.initial_capital * 100, 4),
                'cost_components': {
                    **{f'{k}_dollars': round(v, 2) for k, v in cost_totals.items()},
                    **{f'{k}_pct': round(v / self.initial_capital * 100, 4) for k, v in cost_totals.items()},
                },
                'equity_curve': [{'date': d, 'value': round(v, 2)} for d, v in curve],
            }
            logger.info(f"  {profile.name}: return {total_return:+.2%} | Sharpe {annualised_sharpe(r):+.2f} | "
                        f"max DD {-max_dd:.2%} | peak gross {max_gross:.2f}x | "
                        f"costs {total_cost_dollars / self.initial_capital:.2%} of capital")

        logger.info("\n" + "=" * 90)
        logger.info(f"{'FUND TYPE COMPARISON — SUMMARY':^90}")
        logger.info("=" * 90)
        logger.info(f"{'Cost schedule':<30} {'Return%':>10} {'Sharpe':>8} {'MaxDD%':>8} "
                    f"{'WinRate%':>10} {'Cost%':>10} {'Peak gross':>11}")
        logger.info("-" * 90)
        for r in comparison.values():
            logger.info(f"{r['profile_name']:<30} {r['total_return_pct']:>9.2f}% "
                        f"{r['sharpe_ratio']:>8.2f} {r['max_drawdown_pct']:>8.2f}% "
                        f"{r['win_rate_pct']:>9.2f}% {r['total_cost_pct_of_capital']:>9.2f}% "
                        f"{r['max_gross_leverage']:>10.2f}x")
        logger.info("=" * 90)
        return comparison

    def _factor_attribution(self, results: Dict, oos_dates: List, oos_rets: List) -> Dict:
        """Market beta/alpha of the strategy's daily returns (equal-weight sector-ETF proxy)."""
        from pairs_trading.significance import align_return_series, factor_attribution
        sectors = self.macro_data.get('sectors', {})
        rets = pd.DataFrame({k: v.pct_change(fill_method=None) for k, v in sectors.items() if len(v) > 10})
        if rets.empty:
            return {}
        market = rets.mean(axis=1).dropna()
        m_dates = [str(pd.Timestamp(d).date()) for d in market.index]
        out = {'market_proxy': f'equal-weight daily return of {rets.shape[1]} sector SPDR ETFs'}
        for label, (dates, r) in {'main_backtest': (results.get('daily_dates', []), results.get('daily_returns', [])),
                                  'walk_forward_oos': (oos_dates, oos_rets)}.items():
            if len(r) > 20 and len(dates) == len(r):
                _, ra, rm = align_return_series(dates, r, m_dates, market.to_numpy())
                out[label] = factor_attribution(ra, rm)
        for label, fa in out.items():
            if isinstance(fa, dict) and 'beta' in fa:
                logger.info(f"Market attribution ({label}): beta {fa['beta']:+.3f} (t {fa['beta_tstat']:+.2f}), "
                            f"alpha {fa['alpha_ann']:+.2%}/yr (t {fa['alpha_tstat']:+.2f}), R2 {fa['r2']:.3f}")
        return out

    # ════════════════════════════════════════════════════════════════════════════
    # Regime diagnostic (descriptive only — no trading effect)
    # ════════════════════════════════════════════════════════════════════════════

    def diagnose_regime_break(self, date_range_start: str = '2023-04-04',
                              date_range_end: str = '2023-07-05') -> Dict:
        """Describe VIX and sector-dispersion conditions over a date range.

        Purely descriptive: it reports statistics computed from the loaded macro data and
        does not feed any trading decision.
        """
        logger.info("\n" + "=" * 70)
        logger.info(f"REGIME DIAGNOSTIC  {date_range_start} -> {date_range_end}")
        logger.info("=" * 70)
        start, end = pd.Timestamp(date_range_start), pd.Timestamp(date_range_end)
        vix = self.macro_data.get('VIX', pd.Series(dtype=float))
        sectors = self.macro_data.get('sectors', {})
        results: Dict = {}

        if not vix.empty:
            vix = vix.copy()
            vix.index = pd.DatetimeIndex([_naive(d) for d in vix.index])
            vin = vix[(vix.index >= start) & (vix.index <= end)]
            vpre = vix[vix.index < start].tail(252)
            if len(vin):
                results.update({
                    'vix_avg': round(float(vin.mean()), 2),
                    'vix_min': round(float(vin.min()), 2),
                    'vix_max': round(float(vin.max()), 2),
                    'vix_pre_period_avg': round(float(vpre.mean()), 2) if len(vpre) else None,
                })
                logger.info(f"VIX: avg {results['vix_avg']:.1f} (min {results['vix_min']:.1f}, "
                            f"max {results['vix_max']:.1f}); prior-year avg {results['vix_pre_period_avg']}")

        if sectors:
            rets = pd.DataFrame({k: v.pct_change(fill_method=None) for k, v in sectors.items() if len(v) > 10}).dropna(how='all')
            if not rets.empty:
                rets.index = pd.DatetimeIndex([_naive(d) for d in rets.index])
                daily = rets.std(axis=1).dropna()
                daily_z = ((daily - daily.rolling(252, min_periods=60).mean())
                           / (daily.rolling(252, min_periods=60).std() + 1e-10)).dropna()
                cum = np.log1p(rets.fillna(0)).rolling(63, min_periods=30).sum().std(axis=1).dropna()
                cum_z = ((cum - cum.rolling(252, min_periods=60).mean())
                         / (cum.rolling(252, min_periods=60).std() + 1e-10)).dropna()
                din = daily_z[(daily_z.index >= start) & (daily_z.index <= end)]
                cin = cum_z[(cum_z.index >= start) & (cum_z.index <= end)]
                if len(din):
                    results.update({
                        'sector_dispersion_avg_z': round(float(din.mean()), 3),
                        'sector_dispersion_max_z': round(float(din.max()), 3),
                        'days_above_1sigma': int((din > 1.0).sum()),
                        'days_above_2sigma': int((din > 2.0).sum()),
                        'total_days_in_period': int(len(din)),
                    })
                if len(cin):
                    results.update({
                        'cum_dispersion_avg_z': round(float(cin.mean()), 3),
                        'cum_dispersion_max_z': round(float(cin.max()), 3),
                        'days_cum_above_0p8sigma': int((cin > 0.8).sum()),
                        'days_cum_above_2sigma': int((cin > 2.0).sum()),
                    })
                logger.info(f"Daily sector-dispersion z: avg {results.get('sector_dispersion_avg_z', 0):.2f}, "
                            f"max {results.get('sector_dispersion_max_z', 0):.2f}")
                logger.info(f"63-day cumulative dispersion z (gate input): avg "
                            f"{results.get('cum_dispersion_avg_z', 0):.2f}, max "
                            f"{results.get('cum_dispersion_max_z', 0):.2f}; days > 0.8 (gate, with VIX < 20): "
                            f"{results.get('days_cum_above_0p8sigma', 0)}; days > 2.0: "
                            f"{results.get('days_cum_above_2sigma', 0)}")
        logger.info("Gate rules: VIX>40 -> 0.25x, VIX>30 -> 0.50x, dispersion z>2 -> 0.50x, "
                    "VIX<20 and dispersion z>0.8 -> 0.40x; >20% reduced days in 63 -> no new entries")
        logger.info("=" * 70)
        return results

    # ════════════════════════════════════════════════════════════════════════════
    # Orchestration
    # ════════════════════════════════════════════════════════════════════════════

    def _study_symbols(self) -> List[str]:
        """The symbols whose prices the run needs.

        'marketcap': the universe file (data/marketcap.csv). 'pit_iwv': every point-in-time
        member of any IWV snapshot in force between the selection cutoff and the end of the
        calendar's data, i.e. every name some formation date of this run can select.
        """
        if self.profile.universe != 'pit_iwv':
            return self.data_processor.load_symbols()
        from pairs_trading.universe import PITUniverse, industry_map, reference_root
        self.pit_universe = PITUniverse(reference_root(self.calendar))
        first = self.pit_universe.snapshot_asof(self.calendar.selection_cutoff)
        last = pd.Timestamp(self.calendar.data_end)
        dates = [s['period_date'] for s in self.pit_universe.snapshots()
                 if first <= pd.Timestamp(s['period_date']) <= last]
        symbols = sorted({t for d in dates for t in self.pit_universe.members_asof(d)})
        logger.info(f"Point-in-time universe: {len(symbols)} distinct members across {len(dates)} "
                    f"IWV snapshots ({dates[0]} -> {dates[-1]})")
        if self.profile.same_industry:
            self.industries = industry_map()
            self.pair_selector = self._new_pair_selector()
        return symbols

    def _formation_members(self, date) -> Optional[set]:
        """Point-in-time members on a formation date (None: no membership restriction).

        Records the date's survivorship gap: members without free price history.
        """
        if self.pit_universe is None:
            return None
        members = set(self.pit_universe.members_asof(date))
        cov = self.pit_universe.coverage(self.processed_data.keys(), date)
        self.universe_coverage_log.append({
            'formation_date': str(pd.Timestamp(date).date()),
            **{k: v for k, v in cov.items() if k != 'missing_symbols'}})
        logger.info(f"  formation {pd.Timestamp(date).date()}: {cov['members']} members "
                    f"(snapshot {cov['snapshot']}), {cov['missing']} without price history "
                    f"({cov['missing_value_weight']:.1%} of index weight)")
        return members

    def _universe_file(self) -> str:
        """The file that defines the run's universe (fingerprinted in its provenance)."""
        if self.pit_universe is not None:
            return str(self.pit_universe.universe_dir / 'index.json')
        return 'data/marketcap.csv'                 # data_processor.load_symbols

    def _check_macro_coverage(self) -> None:
        """The regime gate reads VIX and every sector ETF on each trading day; a missing series
        or a series that stops early reads as calm (full size, no entry block), silently
        another strategy. A gated run therefore needs all of them through the last price date."""
        last = max((d for d in (_last_index_day(df) for df in self.processed_data.values()) if d is not None),
                   default=None)
        series = {'^VIX': self.macro_data.get('VIX'), **{e: self.macro_data.get('sectors', {}).get(e)
                                                          for e in SECTOR_ETFS}}
        short = sorted(k for k, v in series.items()
                       if v is None or len(v) == 0 or (last is not None and _last_index_day(v) < last))
        if short:
            when = last.date() if last is not None else 'the last price date'
            raise RuntimeError(f"The regime gate needs VIX and every sector ETF through {when}; missing or "
                               f"short: {short}. Delete {self.calendar.macro_cache} (if it exists) and re-run "
                               "to fetch them again.")

    def _anchor_point_in_time_prices(self) -> None:
        """Close_PIT and Volume_PIT anchored to N-PORT's price of each member on each IWV
        snapshot date (data_processor.anchor_point_in_time): the vendor's later share-basis
        changes and dividends no longer move the $5 screen or the per-share cost terms."""
        summary = EnhancedRussell3000DataProcessor.anchor_all(self.processed_data, self.pit_universe.traded_prices())
        self.price_anchor_summary = summary
        logger.info(f"Point-in-time prices anchored to N-PORT for {summary['anchored']} symbols; "
                    f"{summary['median_ratio_beyond_10pct']} moved by more than 10% "
                    f"(largest: {summary['largest'][:5]})")

    def load_study_data(self) -> None:
        """Universe, price cache and macro data, then the run's provenance block."""
        symbols = self._study_symbols()
        self.processed_data = self.data_processor.load_or_fetch_data(symbols)
        if self.pit_universe is not None:
            self._anchor_point_in_time_prices()
        self.macro_data = self.data_processor.load_macro_data()
        if self.profile.regime_gate:
            self._check_macro_coverage()
        self._pair_state_cache = {}
        # Provenance first, so the log alone identifies code version, switches and data.
        log_run_config(build_run_config(system_info={
            'total_symbols_processed': len(self.processed_data),
            'initial_capital': self.initial_capital,
            'study': describe_study(self.profile, self.calendar),
            'price_cache': self.calendar.price_cache,
            'macro_cache': self.calendar.macro_cache,
            'universe_file': self._universe_file(),
            'universe_coverage': getattr(self.data_processor, 'universe_coverage', None),
            'universe_cached_fraction': getattr(self.data_processor, 'universe_cached_fraction', None),
            'universe_not_found_fraction': getattr(self.data_processor, 'universe_not_found_fraction', None),
            'price_anchor': self.price_anchor_summary}))

    def share_loaded_data(self, other: 'CompleteFixedRussell3000TradingSystem') -> None:
        """Use another system's loaded universe, prices and macro data (same calendar).

        Lets several designs be prepared on one load of the price cache (variant runs);
        everything derived from a design (pairs, spreads, schedules) stays per system.
        """
        if other.calendar != self.calendar:
            raise ValueError(f"calendars differ: {other.calendar.name} vs {self.calendar.name}")
        self.processed_data = other.processed_data
        self.macro_data = other.macro_data
        self.data_processor = other.data_processor
        self._pair_state_cache = other._pair_state_cache   # a pure function of two price series
        if self.profile.universe == other.profile.universe:
            self.pit_universe = other.pit_universe
        elif self.profile.universe == 'pit_iwv':
            raise ValueError("a point-in-time profile cannot share a non-point-in-time load")
        if self.profile.same_industry:
            if other.industries is None:
                from pairs_trading.universe import industry_map
                other.industries = industry_map()
            self.industries = other.industries
        self.pair_selector = self._new_pair_selector()

    def prepare_study(self):
        """Everything before the backtests, on the loaded data.

        Pair selection on formation data (to the calendar's selection cutoff), the main
        ranking model (outcomes complete by the calendar's model_train_end; skipped when
        the profile's ranker is 'none') and the re-selection schedule. Returns
        (test_spreads, pair_windows, last_test_date). Shared by run_complete_system and
        scripts/parameter_sensitivity.py, so both trade exactly the same universe.
        """
        # Pair selection on data up to the cutoff only (selecting on 2020-2025 data would
        # pick pairs because they cointegrated during the test period).
        cutoff = self.calendar.selection_cutoff
        members = self._formation_members(cutoff)
        train_only_data = {}
        for sym, df in self.processed_data.items():
            if len(df.index) == 0 or (members is not None and sym not in members):
                continue
            filtered = df[df.index <= _align_ts(cutoff, df.index[0])]
            if len(filtered) >= 100:
                train_only_data[sym] = filtered
        logger.info(f"Pair selection on {len(train_only_data)} symbols with data up to {cutoff}")
        self.selected_pairs = self.pair_selector.find_quality_pairs(train_only_data)

        for pair in self.selected_pairs:
            spread = self._pair_spread(*pair)
            if not spread.empty:
                self.spread_data[pair] = spread
        train_spreads, test_spreads = self.prepare_time_split_data()

        # Ranking model for the main backtest: trained on outcomes complete by the
        # calendar's model_train_end (dev: 2023-06-30; the main backtest starts 2023-07-01).
        logger.info(f"Training the ranking model on outcomes complete by {self.calendar.model_train_end}")
        self._train_ranker(self.rl_agent, list(self.spread_data), end=self.calendar.model_train_end)

        all_test_dates = sorted({d for s in test_spreads.values() for d in s.index})
        if not all_test_dates:
            raise RuntimeError("No test-period data for the selected pairs — nothing to backtest.")
        pair_windows = self.build_rolling_pair_schedule(all_test_dates)
        # The initial selection is itself a universe known at the cutoff: date it on the last
        # trading day <= cutoff so the walk-forward window whose training ends there is
        # eligible (it was skipped through v31). Later re-selections supersede it.
        last_train_day = max(d for s in train_spreads.values() for d in s.index) if train_spreads else None
        if last_train_day is not None and last_train_day not in pair_windows:
            pair_windows[last_train_day] = dict(self.spread_data)
            pair_windows = dict(sorted(pair_windows.items(), key=lambda kv: _naive(kv[0])))
        last_test = str(pd.Timestamp(all_test_dates[-1]).date())
        return test_spreads, pair_windows, last_test

    def run_complete_system(self):
        """Run the full study: selection, backtest, walk-forward, diagnostics, exports.

        BLAS runs single-threaded for the whole study (threadpoolctl). A multi-threaded BLAS
        splits a reduction across threads, so the same inputs can round differently under
        different thread settings, and a statistic at a threshold can then flip a
        decision. The study's parallelism is the pair search's worker processes, which
        already use one BLAS thread each; torch's OpenMP threads are not affected.
        """
        with threadpool_limits(limits=1, user_api='blas'):
            return self._run_complete_system()

    def _run_complete_system(self):
        logger.info("Starting Russell 3000 pairs-trading study")
        self.load_study_data()
        test_spreads, pair_windows, last_test = self.prepare_study()

        start = self.calendar.backtest_start
        logger.info(f"Main backtest {start} -> {last_test}")
        results = self.run_comprehensive_backtest(
            test_spreads, pair_windows=pair_windows, date_range=(start, last_test))
        traded_universe = sorted({pk for ws in pair_windows.values() for pk in ws})
        p_oos, y_oos = self._ranker_oos_scores(self.rl_agent, traded_universe, start=start)
        results['ranker_oos'] = (classifier_skill(y_oos, p_oos, self.rl_agent.training_summary.get('base_rate'))
                                 if p_oos is not None else None)
        if results['ranker_oos']:
            r = results['ranker_oos']
            logger.info(f"Ranker out-of-sample ({r['n']} signals from {start}): "
                        f"AUC {r['auc']}, Brier {r['brier']:.4f} vs base-rate {r['brier_base_rate']:.4f}")

        if self.calendar.walk_forward:
            wf_summary = self.run_walk_forward_validation(
                train_window_days=252, test_window_days=63, pair_windows=pair_windows)
        else:
            logger.info(f"Walk-forward validation: not run on the {self.calendar.name} calendar")
            wf_summary = {}
        results['walk_forward'] = wf_summary
        results['fdr_diagnostic'] = getattr(self.pair_selector, 'fdr_diagnostic', {})
        results['universe_by_formation'] = list(self.universe_coverage_log)

        oos_dates = list(wf_summary.get('oos_daily_dates', []))
        oos_rets = list(wf_summary.get('oos_daily_returns', []))
        try:
            from pairs_trading.significance import significance_report, log_significance_report
            clean = [w for w in wf_summary.get('windows', []) if w.get('selection_clean')]
            sig = significance_report(
                daily_returns=results.get('daily_returns', []),
                oos_window_returns=[w['total_return_pct'] / 100.0 for w in clean],
                oos_daily_returns=wf_summary.get('oos_daily_returns', []),
                n_trials=self.N_TRIALS,
            )
            log_significance_report(sig)
            results['significance'] = sig
        except Exception as e:
            # Exports still run (they are needed to debug), but the run is marked failed:
            # main() exits non-zero, so a run without its significance tables cannot be
            # mistaken for a complete one and published.
            logger.error(f"Significance analysis failed: {e}", exc_info=True)
            results.setdefault('pipeline_errors', []).append(f"significance: {e}")
        finally:
            # The continuous out-of-sample daily series leaves the summary (it is bulky) but
            # is kept for the export: the site's charts and the variant tests need it.
            detail = wf_summary.pop('oos_daily_detail', None) or {}
            if oos_dates and len(oos_dates) == len(oos_rets):
                results['walk_forward_daily'] = {'dates': [str(pd.Timestamp(d).date()) for d in oos_dates],
                                                 'returns': oos_rets, **detail}
            wf_summary.pop('oos_daily_returns', None)
            wf_summary.pop('all_window_daily_returns', None)
            wf_summary.pop('oos_daily_dates', None)

        try:
            from pairs_trading.benchmark import run_benchmarks, log_benchmark_vs_strategy
            universe = getattr(self.pair_selector, 'last_quality_symbols', None) or \
                sorted({s for pair in self.selected_pairs for s in pair})
            # The strategy's daily series are passed in so the baselines are compared on
            # common dates with a Ledoit-Wolf Sharpe-difference test (first entry = headline).
            strategy_series = {'main_backtest': (results.get('daily_dates', []),
                                                 results.get('daily_returns', []))}
            if len(oos_dates) == len(oos_rets) and len(oos_rets) > 20:
                strategy_series['walk_forward_oos'] = (oos_dates, oos_rets)
            benchmarks = run_benchmarks(
                self.processed_data, universe,
                trade_start=start, trade_end=last_test, n_pairs=20,
                strategy_series=strategy_series)
            if benchmarks:
                log_benchmark_vs_strategy(benchmarks,
                                          strategy_return_pct=results.get('total_return', 0.0) * 100,
                                          strategy_sharpe=results.get('sharpe_ratio', 0.0))
                results['benchmarks'] = benchmarks
        except Exception as e:
            logger.error(f"Benchmark analysis failed: {e}", exc_info=True)
            results.setdefault('pipeline_errors', []).append(f"benchmarks: {e}")

        results['factor_attribution'] = self._factor_attribution(results, oos_dates, oos_rets)
        try:
            from pairs_trading.evidence import build_evidence, load_factors
            factors, fingerprint, error = load_factors(end=self.calendar.data_end)
            results['evidence'] = build_evidence(results, n_trials=self.N_TRIALS, factors=factors,
                                                 factor_fingerprint=fingerprint, factor_error=error)
        except Exception as e:
            logger.error(f"Evidence layer failed: {e}", exc_info=True)
            results.setdefault('pipeline_errors', []).append(f"evidence: {e}")
        # The 2023 regime break lies in the development period; another calendar's export
        # would carry a 2023 window under its own name.
        results['regime_diagnosis'] = (self.diagnose_regime_break('2023-04-04', '2023-07-05')
                                       if self.calendar.name == 'dev' else {})

        logger.info("Starting the cost-schedule replay...")
        fund_comparison = self.run_fund_type_comparison(results, main_daily_dates=results.get('daily_dates', []))
        results['fund_comparison'] = fund_comparison
        results['ranker_training'] = dict(getattr(self.rl_agent, 'training_summary', {}) or {})

        # Exports: full results, fund table, and the small headline snapshot that README,
        # the site and the social card are checked against (scripts/check_published_numbers.py).
        starts = [df.index.min() for df in self.processed_data.values() if len(df)]
        ends = [df.index.max() for df in self.processed_data.values() if len(df)]
        system_info = {
            'total_symbols_processed': len(self.processed_data),
            'pairs_selected': len(self.selected_pairs),
            'initial_capital': self.initial_capital,
            'data_start': min(starts) if starts else None,
            'data_end': max(ends) if ends else None,
            'universe_coverage': getattr(self.data_processor, 'universe_coverage', None),
            'universe_cached_fraction': getattr(self.data_processor, 'universe_cached_fraction', None),
            'universe_not_found_fraction': getattr(self.data_processor, 'universe_not_found_fraction', None),
            'price_anchor': self.price_anchor_summary,
            'study': describe_study(self.profile, self.calendar),
            'price_cache': self.calendar.price_cache,
            'macro_cache': self.calendar.macro_cache,
            'universe_file': self._universe_file(),
        }
        export_testing_results_to_json(results, system_info)      # sets results['run_config']
        if fund_comparison:
            # one provenance block per run: the fund export reuses the results' run_config
            export_fund_comparison_to_json(fund_comparison, run_config=results.get('run_config'))
        export_headline_metrics(results, system_info)
        plot_results(results['daily_returns'], results, initial_capital=self.initial_capital,
                     dates=results.get('daily_dates'))
        plot_ranker_training(results['ranker_training'])
        if fund_comparison:
            plot_fund_comparison(fund_comparison)
        return results
