"""
TRANSFORMER ENCODER FOR PAIRS TRADING - TRADING SYSTEM
=======================================================
Complete Fixed Russell 3000 Trading System with balanced improvements.
DO NOT MODIFY ANY PARAMETERS IN THIS FILE.
"""

from pairs_trading.config import (
    pd, np, logging, tqdm, Dict, List, Tuple
)
from statsmodels.tsa.stattools import coint as _coint
from pairs_trading.data_processor import EnhancedRussell3000DataProcessor
from pairs_trading.pair_selector import FixedPrimeFundPairSelector
from pairs_trading.multi_agent_system import FixedTransformerMultiAgentSystem
from pairs_trading.position_sizer import FixedPrimeFundPositionSizer
from pairs_trading.risk_manager import FixedPrimeFundRiskManager
from pairs_trading.transaction_costs import EnhancedPrimeFundTransactionCostModel
from pairs_trading.json_export import export_testing_results_to_json, export_fund_comparison_to_json
from pairs_trading.plotting import plot_results, plot_fund_comparison

logger = logging.getLogger(__name__)


class CompleteFixedRussell3000TradingSystem:
    """FIXED: Complete system with balanced improvements + JSON EXPORT"""

    def __init__(self, initial_capital: float = 100000000):
        self.initial_capital = initial_capital
        self.current_capital = initial_capital

        self.data_processor = EnhancedRussell3000DataProcessor()
        self.pair_selector = FixedPrimeFundPairSelector()
        # v24: the dead standalone transformer_agent (state_dim=20, never called) was
        # removed. The live transformer is rl_agent.signal_transformer — trained inside
        # train_agent() on entry-signal outcomes, used to rank opportunities.
        self.rl_agent = FixedTransformerMultiAgentSystem()
        self.position_sizer = FixedPrimeFundPositionSizer()
        self.risk_manager = FixedPrimeFundRiskManager()
        self.cost_model = EnhancedPrimeFundTransactionCostModel()

        self.processed_data = {}
        self.selected_pairs = []
        self.spread_data = {}
        self.macro_data = {}

        self.trade_history = []
        self.daily_returns = []
        self.portfolio_metrics = {}

        logger.info("COMPLETE FIXED Russell 3000 Trading System initialized with JSON EXPORT")

    def calculate_kalman_spread(self, prices1: pd.Series, prices2: pd.Series,
                                delta: float = 1e-5, R: float = 0.001) -> pd.Series:
        """v12: Kalman filter dynamic hedge ratio.

        Models: log(p1)_t = β_t * log(p2)_t + ε_t
                β_t = β_{t-1} + η_t   (random walk — β drifts slowly)

        delta controls drift speed (smaller = more stable β).
        R is measurement noise variance.
        Returns residual spread: log(p1) - β_t * log(p2).
        """
        lp1 = np.log(prices1.values + 1e-8)
        lp2 = np.log(prices2.values + 1e-8)
        n = len(lp1)

        # Process noise proportional to regressor variance
        Q = delta / (1.0 - delta) * np.var(lp2)

        # Initialise β with OLS on first 30 points to avoid burn-in drift
        init_n = min(30, n)
        if init_n >= 2:
            beta = float(np.polyfit(lp2[:init_n], lp1[:init_n], 1)[0])
        else:
            beta = 1.0
        P = 1.0

        spread = np.empty(n)
        for t in range(n):
            x = lp2[t]
            y = lp1[t]
            P_pred = P + Q
            denom = x * P_pred * x + R
            K = P_pred * x / denom if abs(denom) > 1e-12 else 0.0
            beta = beta + K * (y - x * beta)
            P = (1.0 - K * x) * P_pred
            spread[t] = y - beta * x

        return pd.Series(spread, index=prices1.index)

    def calculate_spread(self, data1: pd.DataFrame, data2: pd.DataFrame) -> pd.Series:
        """v12: Kalman filter dynamic hedge ratio spread."""
        try:
            common_dates = data1.index.intersection(data2.index)
            if len(common_dates) < 100:
                return pd.Series(dtype=float)

            prices1 = data1.loc[common_dates, 'Close']
            prices2 = data2.loc[common_dates, 'Close']

            if prices1.isnull().sum() > len(prices1) * 0.1 or prices2.isnull().sum() > len(prices2) * 0.1:
                return pd.Series(dtype=float)

            prices1 = prices1.ffill().bfill()
            prices2 = prices2.ffill().bfill()

            # v12: Kalman filter replaces fixed log-price difference (β=1)
            spread = self.calculate_kalman_spread(prices1, prices2)
            return spread.dropna()

        except Exception as e:
            logger.debug(f"Spread calculation error: {str(e)}")
            return pd.Series(dtype=float)

    def _cusum_break(self, spread_window: pd.Series, threshold: float = 5.0, k: float = 0.5) -> bool:
        """v12: CUSUM structural break detection on recent spread history.
        Returns True if a structural break is detected (signal to skip this pair today).
        Uses two-sided CUSUM on standardised first differences.
        threshold=5.0, k=0.5 are standard Page-CUSUM values (equivalent to ~5σ sustained shift).
        """
        if len(spread_window) < 20:
            return False
        r = spread_window.diff().dropna()
        mu = r.mean()
        sigma = r.std()
        if sigma < 1e-8:
            return False
        S_pos = S_neg = 0.0
        for val in (r - mu) / sigma:
            S_pos = max(0.0, S_pos + val - k)
            S_neg = max(0.0, S_neg - val - k)
            if S_pos > threshold or S_neg > threshold:
                return True
        return False

    def _hurst_exponent(self, spread_values: np.ndarray) -> float:
        """v14: Hurst exponent via variance-of-increments (log-variance regression).
        H < 0.5: mean-reverting (sub-diffusive) — valid entry.
        H = 0.5: random walk — neutral.
        H > 0.5: trending (super-diffusive) — skip entry.
        Uses lags [1,2,4,8,16]; minimum 3 valid lags required for a stable estimate.
        Research: MDPI 2024, Physica A 2021 — H < 0.45 reliably anticipates mean reversion.
        """
        n = len(spread_values)
        if n < 20:
            return 0.5  # insufficient data → neutral (pass through)

        lags = [l for l in [1, 2, 4, 8, 16] if l < n // 2]
        if len(lags) < 3:
            return 0.5

        log_lags = []
        log_vars = []
        for lag in lags:
            diff = spread_values[lag:] - spread_values[:-lag]
            var = np.var(diff)
            if var < 1e-16:
                continue
            log_lags.append(np.log(lag))
            log_vars.append(np.log(var))

        if len(log_lags) < 3:
            return 0.5

        log_lags_arr = np.array(log_lags)
        log_vars_arr = np.array(log_vars)

        # OLS: log(var) = 2H * log(lag) + const  →  H = slope / 2
        X = np.column_stack([np.ones(len(log_lags_arr)), log_lags_arr])
        try:
            beta = np.linalg.lstsq(X, log_vars_arr, rcond=None)[0]
            H = beta[1] / 2.0
            return float(np.clip(H, 0.0, 1.0))
        except Exception:
            return 0.5

    def prepare_time_split_data(self) -> Tuple[Dict, Dict]:
        """FIXED: More robust time-based data splitting"""
        logger.info("FIXED: Time-based split with improved validation")

        train_spreads = {}
        test_spreads = {}

        train_end_date = pd.Timestamp('2022-12-31')
        test_start_date = pd.Timestamp('2023-01-01')

        for pair_key, spread in self.spread_data.items():
            if len(spread) < 200:
                continue

            try:
                if hasattr(spread.index, 'tz') and spread.index.tz is not None:
                    train_end_tz = train_end_date.tz_localize(spread.index.tz)
                    test_start_tz = test_start_date.tz_localize(spread.index.tz)

                    train_mask = spread.index <= train_end_tz
                    test_mask = spread.index >= test_start_tz
                else:
                    train_mask = spread.index <= train_end_date
                    test_mask = spread.index >= test_start_date

                train_spread = spread[train_mask]
                test_spread = spread[test_mask]

                if len(train_spread) >= 100 and len(test_spread) >= 50:
                    train_spreads[pair_key] = train_spread
                    test_spreads[pair_key] = test_spread

            except Exception as e:
                logger.debug(f"Error processing pair {pair_key}: {str(e)}")
                continue

        logger.info(f"FIXED SPLIT: {len(train_spreads)} pairs for training")
        logger.info(f"FIXED SPLIT: {len(test_spreads)} pairs for testing")

        return train_spreads, test_spreads

    def run_comprehensive_backtest(self, test_spreads: Dict, pair_windows: Dict = None,
                                   date_range: tuple = None) -> Dict:
        """FIXED: Backtest with look-ahead bias corrected + optional quarterly pair re-selection.

        date_range: optional (start, end) tuple to restrict which dates are traded.
        Used by walk-forward validation so full-history spreads can be passed for
        feature context while only the out-of-sample test period is actually traded.
        """
        logger.info("Running CORRECTED backtest - PnL booked on exit date")
        if pair_windows:
            logger.info(f"QUARTERLY RE-SELECTION active: {len(pair_windows)} windows")

        # Reset risk manager peak/drawdown state so a fresh backtest (e.g. each
        # walk-forward window) is not killed immediately by stale peak_portfolio_value
        # accumulated from a prior longer run.
        self.risk_manager.peak_portfolio_value = self.initial_capital
        self.risk_manager.current_drawdown = 0.0
        self.risk_manager.trading_paused = False
        self.risk_manager.daily_returns_history = []
        self.risk_manager.last_trade_dates = {}

        portfolio_value = self.initial_capital
        trades = []
        daily_pnl = []
        daily_metrics = []
        total_costs = 0

        # FIX: Pending PnL keyed by exit date - eliminates look-ahead bias
        pending_pnl: Dict = {}

        # v26: track real concurrent gross exposure. Previously update_daily_stats
        # was called with exposure=0, so current_exposure reset to 0 every day and
        # the 30% total-exposure cap + exposure kill-switch never fired. open_exposure
        # = sum of open position fractions; each entry schedules release on its exit.
        open_exposure = 0.0
        exposure_release: Dict = {}

        # v13: Per-pair consecutive loss tracking for cooling-off after 3 losses
        pair_loss_streak: Dict = {}    # pair_string -> consecutive loss count
        pair_cooloff_until: Dict = {}  # pair_string -> date cooloff triggered (reset after 30 cal days)

        # v22: Cross-symbol exposure limit — prevent same stock in 2+ simultaneous open pairs.
        # Reduces hidden directional concentration (e.g. AAPL-MSFT + AAPL-GOOG open = net AAPL bet).
        _active_symbols: Dict = {}    # symbol -> scheduled exit_date

        monthly_volume = self.initial_capital * 1.0

        # Build master date list from ALL windows if re-selection is active
        all_dates = set()
        if pair_windows:
            for window_spreads in pair_windows.values():
                for spread in window_spreads.values():
                    all_dates.update(spread.index)
        else:
            for spread in test_spreads.values():
                all_dates.update(spread.index)
        all_dates = sorted(list(all_dates))

        # If a date range is specified, restrict trading to that window only.
        # Normalise timezone so the comparison works whether the dates are
        # tz-aware (UTC from yfinance) or tz-naive.
        if date_range is not None:
            dr_start, dr_end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
            if all_dates:
                sample = all_dates[0]
                if getattr(sample, 'tzinfo', None) is not None and dr_start.tzinfo is None:
                    dr_start = dr_start.tz_localize(sample.tzinfo)
                    dr_end   = dr_end.tz_localize(sample.tzinfo)
                elif getattr(sample, 'tzinfo', None) is None and dr_start.tzinfo is not None:
                    dr_start = dr_start.tz_localize(None)
                    dr_end   = dr_end.tz_localize(None)
            all_dates = [d for d in all_dates if dr_start <= d <= dr_end]

        logger.info(f"CORRECTED Backtest: {len(all_dates)} days")

        # ── Regime Gate Precomputation ─────────────────────────────────────────
        # Build fast date-string lookup for VIX and cross-sector dispersion.
        # Catches "Walking on Ice" regime (Q2 2023): VIX ~13-15 looked SAFE but
        # sector dispersion spiked as Mag 7 decoupled from everything else.
        # VIX alone misses this — BIS (March 2024) proved 0DTE + dealer hedging
        # mechanically suppressed VIX below true risk level during Q2 2023.
        _vix_series  = self.macro_data.get('VIX', pd.Series(dtype=float))
        _sector_data = self.macro_data.get('sectors', {})

        _sector_rets = pd.DataFrame(
            {k: v.pct_change() for k, v in _sector_data.items() if len(v) > 10}
        ).dropna(how='all')

        # 63-day cumulative log-return dispersion (v8 Fix: replaces daily cross-section std)
        # WHY: Daily std of sector returns was -0.47σ during Q2 2023 (W10) because NVDA's
        # +0.5%/day gain vs +0.0%/day for other sectors looks small daily but compounds to
        # +37% vs +0% over 63 days. Cumulative log-return dispersion captures this slow-burn
        # structural divergence (Mag 7 effect) that daily metrics completely miss.
        # 2022 comparison: all sectors fell together (-30% across sectors) → low cumulative
        # dispersion → NO false gate firing. Q2 2023: XLK +20%+, rest flat → HIGH dispersion.
        _sector_cum_disp = pd.Series(dtype=float)
        if not _sector_rets.empty:
            _sector_log = np.log(1 + _sector_rets.fillna(0))
            _sector_cum63 = _sector_log.rolling(63, min_periods=30).sum()   # cumulative log returns
            _sector_cum_disp = _sector_cum63.std(axis=1).dropna()            # cross-sectional std

        # Rolling z-score vs 252-day trailing baseline
        _disp_mean = _sector_cum_disp.rolling(252, min_periods=60).mean()
        _disp_std  = _sector_cum_disp.rolling(252, min_periods=60).std()
        _disp_z    = ((_sector_cum_disp - _disp_mean) / (_disp_std + 1e-10)).dropna()

        # Build tz-naive date-string lookup dicts for O(1) per-day access
        _vix_lookup: Dict = {
            str(pd.Timestamp(dt).date()): float(v)
            for dt, v in _vix_series.items()
        }
        _disp_z_lookup: Dict = {
            str(pd.Timestamp(dt).date()): float(z)
            for dt, z in _disp_z.items()
        }
        _regime_scale_counts: Dict = {}
        logger.info(f"Regime gate: loaded {len(_vix_lookup)} VIX days, "
                    f"{len(_disp_z_lookup)} cum-dispersion days (63-day rolling)")
        # ── End Regime Gate Precomputation ────────────────────────────────────

        max_daily_trades = 0
        quality_opportunities = 0

        # Sorted re-selection dates for fast lookup
        resel_dates_sorted = sorted(pair_windows.keys()) if pair_windows else []

        daily_dates = []   # v26: real calendar date per daily_pnl entry (for export)

        for date_idx, date in enumerate(tqdm(all_dates, desc="CORRECTED Backtesting")):
            daily_trades = 0
            # FIX: Start day PnL with any trades that closed today
            day_pnl = pending_pnl.pop(date, 0.0)
            day_costs = 0
            day_trade_details = []

            # v26: release exposure from positions exiting today and expose the
            # running gross total to the risk manager (enforces the 30% cap).
            open_exposure = max(0.0, open_exposure - exposure_release.pop(date, 0.0))
            self.risk_manager.current_exposure = open_exposure

            # Reset daily counters and get adaptive scaling
            self.risk_manager.reset_daily_counters()
            risk_scaling_factor = self.risk_manager.get_combined_scaling_factor(portfolio_value)

            # ── Regime gate (VIX + sector dispersion) ─────────────────────────
            # Walking on Ice detection: LOW VIX + HIGH dispersion = the Q2 2023
            # pattern where the model looks safe but pair correlations break.
            _date_key  = str(date.date()) if hasattr(date, 'date') else str(date)
            _cur_vix   = _vix_lookup.get(_date_key, 18.0)   # neutral default
            _cur_dispz = _disp_z_lookup.get(_date_key, 0.0)

            # VIX scaling — crisis-only gate (v8 Fix: raised from 25/35 to 30/40)
            # Rationale: 2022 avg VIX 25-28 fired the old gate but pairs were profitable.
            # High VIX with macro stress (Fed hikes) ≠ correlation collapse.
            # New thresholds: 30+ is genuine stress; 40+ is crisis (COVID 82, GFC 70).
            if _cur_vix > 40:
                _vix_scale = 0.25
            elif _cur_vix > 30:
                _vix_scale = 0.50
            else:
                _vix_scale = 1.00

            # Dispersion scaling — catches "Walking on Ice" using 63-day cumulative metric
            # (v8 Fix: VIX threshold widened to <20; cum-dispersion z threshold lowered to 1.2)
            # The cumulative metric amplifies slow-burn divergence (NVDA +0.5%/day * 63 days)
            # that daily std misses. With higher sensitivity, 1.2σ threshold is appropriate.
            if _cur_dispz > 2.0:
                _disp_scale = 0.50
            elif _cur_vix < 20 and _cur_dispz > 0.8:  # v11 Fix #3: Lower from 1.2 → earlier detection
                # Low VIX + elevated CUMULATIVE sector divergence = Walking on Ice
                _disp_scale = 0.40
            else:
                _disp_scale = 1.00

            regime_scale = min(_vix_scale, _disp_scale)

            # ── v11 Fix #2: HARD STOP when regime is persistently broken ──────────
            # If >20% of last 63 days are reduced-scale, the regime is genuinely
            # broken (not just transient stress). Suspend trading entirely.
            # Example: v10 W16 had 34/63 reduced days (54%) → lost -6.52%
            if date_idx >= 62:  # Need 63 days of history
                _recent_63_dates = list(all_dates)[max(0, date_idx-62):date_idx+1]
                _recent_reduced = 0
                for _d in _recent_63_dates:
                    _dk = str(_d.date()) if hasattr(_d, 'date') else str(_d)
                    _d_vix = _vix_lookup.get(_dk, 18.0)
                    _d_disp = _disp_z_lookup.get(_dk, 0.0)

                    # Recalculate scale for this date (matches gate logic)
                    if _d_vix > 40:
                        _d_scale = 0.25
                    elif _d_vix > 30:
                        _d_scale = 0.50
                    elif _d_disp > 2.0:
                        _d_scale = 0.50
                    elif _d_vix < 20 and _d_disp > 0.8:  # v11: lowered from 1.2
                        _d_scale = 0.40
                    else:
                        _d_scale = 1.0

                    if _d_scale < 1.0:
                        _recent_reduced += 1

                # If >20% of last quarter is reduced, SKIP NEW ENTRIES this day.
                # v26: still book any P&L from positions exiting today and record the
                # day — the prior code `continue`d before daily_pnl.append/portfolio
                # update, silently discarding realized exit P&L that landed on a
                # hard-stop day (those trades were still counted in win-rate/stats).
                if _recent_reduced / len(_recent_63_dates) > 0.20:
                    logger.debug(f"v11 hard stop: {_recent_reduced}/{len(_recent_63_dates)} days reduced → no new entries {date.date()}")
                    daily_pnl.append(day_pnl)
                    daily_dates.append(date)
                    portfolio_value *= (1 + day_pnl)
                    self.risk_manager.update_daily_stats(0, open_exposure, day_pnl, portfolio_value)
                    should_stop, stop_reason = self.risk_manager.should_stop_trading(day_pnl)
                    if should_stop:
                        logger.warning(f"LOGICAL Risk Management: {stop_reason}")
                        break
                    continue  # Skip new entries today

            risk_scaling_factor *= regime_scale
            _regime_scale_counts[regime_scale] = _regime_scale_counts.get(regime_scale, 0) + 1
            # ── End v11 regime protection ──────────────────────────────────────────

            # v22: clean up expired symbol locks from _active_symbols
            _expired_syms = [s for s, exp in _active_symbols.items() if exp <= date]
            for _s in _expired_syms:
                del _active_symbols[_s]

            # QUARTERLY RE-SELECTION: pick the spread set for this date
            if pair_windows and resel_dates_sorted:
                active_resel_date = resel_dates_sorted[0]
                for rd in resel_dates_sorted:
                    if rd <= date:
                        active_resel_date = rd
                    else:
                        break
                active_spreads = pair_windows[active_resel_date]
            else:
                active_spreads = test_spreads

            pair_opportunities = []

            for pair_key, spread in active_spreads.items():
                if date not in spread.index:
                    continue

                try:
                    symbol1, symbol2 = pair_key
                    pair_string = f"{symbol1}-{symbol2}"

                    # v27: cross-symbol concentration check (v22 intent, now enforced).
                    # If either leg is already in an open position, skip — otherwise we
                    # accumulate a hidden directional bet on a single name across pairs.
                    if symbol1 in _active_symbols or symbol2 in _active_symbols:
                        continue

                    historical_spread = spread.loc[:date]
                    if len(historical_spread) < 50:
                        continue

                    # v13: Rolling 20-day correlation check — skip if pair has recently decoupled.
                    # Threshold 0.20: below static selection floor (0.25) to allow short-term fluctuation,
                    # but above zero — genuinely broken pairs (corr < 0.20) are still blocked.
                    # NOTE: 0.30 was too strict — blocked entries even for quarterly-reselected pairs
                    # in 2023-2025 low-vol regime (Mag7 sector divergence compresses short-term corr).
                    if symbol1 in self.processed_data and symbol2 in self.processed_data:
                        _c1w = self.processed_data[symbol1]['Close'].loc[:date].iloc[-21:]
                        _c2w = self.processed_data[symbol2]['Close'].loc[:date].iloc[-21:]
                        if len(_c1w) >= 21 and len(_c2w) >= 21:
                            _r1 = np.log(_c1w / _c1w.shift(1)).dropna()
                            _r2 = np.log(_c2w / _c2w.shift(1)).dropna()
                            _cidx = _r1.index.intersection(_r2.index)
                            if len(_cidx) >= 15:
                                _rcorr = np.corrcoef(_r1.loc[_cidx].values, _r2.loc[_cidx].values)[0, 1]
                                if np.isnan(_rcorr) or _rcorr < 0.20:
                                    continue

                    # v13: Pair cooling-off — skip pair for 30 calendar days after 3 consecutive losses.
                    # Prevents re-entering pairs in broken regimes until next quarterly re-selection.
                    if pair_string in pair_cooloff_until:
                        _cooloff_start = pair_cooloff_until[pair_string]
                        if (date - _cooloff_start).days < 30:
                            continue
                        else:
                            # Cooloff expired — clear state
                            pair_loss_streak.pop(pair_string, None)
                            pair_cooloff_until.pop(pair_string, None)

                    # v14 (corrected): Locked-β spread filters — CUSUM, Hurst, and reference stats.
                    # The Kalman spread is stationary by construction (H ≈ 0.5, CUSUM rarely fires).
                    # Locked-β spread = log(p1) - β_f × log(p2) with β_f = Kalman β at current date.
                    # This IS the spread of the position we'll hold — it reflects true market dynamics.
                    # At entry date, locked_spread_entry = Kalman_spread_entry (identical by construction).
                    _locked_mean_entry = None
                    _locked_std_entry = None
                    _entry_locked_zscore = None
                    _lk_spread_returns = None   # v18: locked-β daily diffs for position sizer
                    try:
                        _p1c = self.processed_data[symbol1].loc[date, 'Close'] \
                            if date in self.processed_data[symbol1].index else None
                        _p2c = self.processed_data[symbol2].loc[date, 'Close'] \
                            if date in self.processed_data[symbol2].index else None
                        if _p1c is not None and _p2c is not None and _p1c > 0 and _p2c > 0:
                            _lp1c = np.log(_p1c)
                            _lp2c = np.log(_p2c)
                            if date in spread.index and abs(_lp2c) > 1e-4:
                                _beta_f = (_lp1c - spread.loc[date]) / _lp2c
                                # v22: half-life adaptive lookback — pairs with longer HL need
                                # a wider window to get a stable mean/std estimate for z-score.
                                # Use 3× half-life (min 30, max 90 bars).
                                _ps_tmp = self.pair_selector.pair_statistics.get(f"{symbol1}-{symbol2}", {})
                                _hl_tmp = float(_ps_tmp.get('half_life', 21.0))
                                _ref_window = max(30, min(int(_hl_tmp * 3), 90))
                                _p1h = self.processed_data[symbol1]['Close'].loc[:date].iloc[-_ref_window:]
                                _p2h = self.processed_data[symbol2]['Close'].loc[:date].iloc[-_ref_window:]
                                _lk_idx = _p1h.index.intersection(_p2h.index)
                                if len(_lk_idx) >= 20:
                                    _lp1h = np.log(np.maximum(_p1h.loc[_lk_idx].values, 1e-8))
                                    _lp2h = np.log(np.maximum(_p2h.loc[_lk_idx].values, 1e-8))
                                    _lk_hist = _lp1h - _beta_f * _lp2h
                                    # CUSUM on locked-β (structural break detection)
                                    if self._cusum_break(pd.Series(_lk_hist)):
                                        continue
                                    # Hurst on locked-β (trend detection)
                                    if self._hurst_exponent(_lk_hist) > 0.55:
                                        continue
                                    # Reference stats for consistent exit z-score
                                    _n_ref = min(60, len(_lk_hist))
                                    _locked_mean_entry = float(np.mean(_lk_hist[-_n_ref:]))
                                    _locked_std_entry = max(float(np.std(_lk_hist[-_n_ref:])), 1e-8)
                                    _entry_locked_zscore = (spread.loc[date] - _locked_mean_entry) / _locked_std_entry
                                    # v18: daily diffs of locked-β spread for position sizer vol check.
                                    # Kalman diff std (~0.002) never triggers the 0.08 threshold.
                                    # Locked-β diff std (~0.01-0.05) gives a real volatility signal.
                                    _lk_spread_returns = pd.Series(np.diff(_lk_hist))
                    except Exception:
                        pass

                    pair_stats = self.pair_selector.pair_statistics.get(pair_string, {})

                    pair_quality = pair_stats.get('quality_score', 0)
                    if pair_quality < 0.4:
                        continue

                    features = self.rl_agent.extract_advanced_features(
                        historical_spread, pair_stats,
                        self.processed_data.get(symbol1, pd.DataFrame()),
                        self.processed_data.get(symbol2, pd.DataFrame()),
                        macro_data=self.macro_data,
                        symbol1=symbol1, symbol2=symbol2
                    )

                    if self.rl_agent.scaler_fitted:
                        features_scaled = self.rl_agent.scaler.transform(features.reshape(1, -1)).flatten()
                    else:
                        features_scaled = features

                    # v26: the entry decision is governed by the RAW z-score (the
                    # documented |z|>1.8 rule). The prior code also gated on
                    # get_action(), which compared the RobustScaler-SCALED state[0]
                    # to 2.0 — a unit mismatch that silently raised the effective
                    # entry threshold to ~2.7σ and could reject valid 1.8σ signals.
                    zscore = features[0] if len(features) > 0 else 0
                    signal_strength = min(abs(zscore) / 2.5, 1.0)

                    # v18: entry z-score threshold (raw z)
                    if abs(zscore) < 1.8:
                        continue

                    if zscore > 1.8:
                        action = 2
                    elif zscore < -1.8:
                        action = 0
                    else:
                        continue

                    # v26: transformer quality score (RANKING only) computed directly,
                    # defined for every raw-z entry — no longer tied to get_action's
                    # scaled-z neutral short-circuit. Returns 1.0 if no transformer.
                    feature_quality = self.rl_agent.score_signal_quality(features_scaled)

                    quality_opportunities += 1

                    # v16: diff() not pct_change() — Kalman spread is a signed residual that
                    # crosses zero; pct_change() divides by near-zero values and blows up.
                    spread_returns = historical_spread.diff().dropna()

                    # v18: feed locked-β daily diffs to position sizer so its vol check
                    # (volatility > 0.08 → 0.8× multiplier) fires on real pair volatility,
                    # not Kalman residuals (~0.002 std, never triggering the threshold).
                    _sizer_vol_series = _lk_spread_returns if _lk_spread_returns is not None else spread_returns
                    position_size = self.position_sizer.calculate_optimal_position_size(
                        pair_string, signal_strength, pair_quality, portfolio_value, _sizer_vol_series,
                        risk_scaling_factor=risk_scaling_factor
                    )

                    z_multiplier = min(abs(zscore) / 2.3, 2.0)
                    position_size *= z_multiplier

                    # v16: removed duplicate global win-rate boost (was: position_size *= 1.3
                    # when last 5 trades had WR > 55%). The position sizer already has an
                    # internal performance_multiplier from its own trade_history. The manual
                    # boost applied cross-pair performance (all pairs' last 5 trades) to the
                    # current pair's size — logically incorrect.

                    # v16: use locked-β spread std for volatility when available.
                    # Kalman spread diff has near-zero std by construction (Kalman removes
                    # variance). The risk manager was seeing ~0.005 vol for every pair and
                    # never flagging high-risk environments. locked_std_entry is the actual
                    # log-price spread std — the true measure of position risk.
                    if _locked_std_entry is not None:
                        recent_vol = _locked_std_entry
                    else:
                        recent_vol = spread_returns.rolling(10, min_periods=5).std().iloc[-1] if len(spread_returns) >= 10 else 0.02
                    market_data = {
                        'volatility': min(recent_vol, 0.25),
                        'volume': 2e6,
                        'zscore': zscore,
                        'pair_quality': pair_quality,
                        'market_regime': 0
                    }

                    risk_passed, risk_reason = self.risk_manager.validate_signal(
                        pair_key, action, signal_strength, market_data, position_size, portfolio_value, date
                    )

                    if not risk_passed:
                        continue

                    pair_opportunities.append({
                        'pair_key': pair_key,
                        'pair_string': pair_string,
                        'action': action,
                        'signal_strength': signal_strength,
                        'zscore': zscore,
                        'pair_quality': pair_quality,
                        'position_size': position_size,
                        'spread': spread,
                        'historical_spread': historical_spread,
                        'spread_returns': spread_returns,
                        'market_data': market_data,
                        'feature_quality': feature_quality,
                        'pair_stats': pair_stats,   # v19: for dynamic hold time
                        # v14: locked-β reference stats for self-consistent exit z-score
                        'locked_mean_entry': _locked_mean_entry,
                        'locked_std_entry': _locked_std_entry,
                        'entry_locked_zscore': _entry_locked_zscore,
                    })

                except Exception as e:
                    continue

            if date_idx % 50 == 0:
                logger.info(f"Day {date_idx}: {len(pair_opportunities)} quality opportunities (total: {quality_opportunities})")

            pair_opportunities.sort(
                key=lambda x: x['signal_strength'] * x['pair_quality'] * x['feature_quality'],
                reverse=True
            )

            # v27 (audit cont.): use a distinct local for the per-day selection cap.
            # Previously this reused `max_daily_trades` — the SAME name as the
            # running peak-trades-per-day statistic (init 0, updated below at
            # `max_daily_trades = max(max_daily_trades, daily_trades)`). Overwriting
            # it here each day clobbered the cross-day max, so the reported
            # 'max_daily_trades' stat only ever reflected the final day.
            n_select = min(self.risk_manager.max_daily_trades, len(pair_opportunities))
            selected_opportunities = pair_opportunities[:n_select]

            for opportunity in selected_opportunities:
                if daily_trades >= self.risk_manager.max_daily_trades:
                    break

                try:
                    pair_key = opportunity['pair_key']
                    symbol1, symbol2 = pair_key
                    pair_string = opportunity['pair_string']

                    # v27 (audit cont.): enforce cross-symbol concentration WITHIN the
                    # day too. The gathering loop only checks _active_symbols against
                    # prior days' locks (it runs before any of today's trades book), so
                    # two same-day top-ranked opportunities sharing a leg would BOTH
                    # execute — putting one stock in two concurrent pairs (the exact
                    # hidden net-directional bet the v27 lock was meant to prevent).
                    # _active_symbols is populated as trades book below, so this
                    # re-check blocks the second same-day collision.
                    if symbol1 in _active_symbols or symbol2 in _active_symbols:
                        continue

                    action = opportunity['action']
                    signal_strength = opportunity['signal_strength']
                    zscore = opportunity['zscore']
                    pair_quality = opportunity['pair_quality']
                    position_size = opportunity['position_size']
                    spread = opportunity['spread']

                    next_date = None
                    # v14: use locked-β entry z-score for consistent exit comparison.
                    # At entry, locked_spread = Kalman_spread (identical by construction of beta_entry).
                    _locked_mean_entry = opportunity.get('locked_mean_entry')
                    _locked_std_entry = opportunity.get('locked_std_entry')
                    _ent_lz = opportunity.get('entry_locked_zscore')
                    entry_spread_zscore = _ent_lz if _ent_lz is not None else zscore

                    # v12 fix: fetch entry prices and lock beta BEFORE the exit loop.
                    # Kalman β drifts after entry; the old code computed exit z-score using
                    # current Kalman β, so the spread would appear to "revert" purely from
                    # β drift — not from actual price mean reversion. Lock β at entry.
                    current_price1 = self.processed_data[symbol1].loc[date, 'Close'] if date in self.processed_data[symbol1].index else 100
                    current_price2 = self.processed_data[symbol2].loc[date, 'Close'] if date in self.processed_data[symbol2].index else 100
                    current_spread = spread.loc[date]
                    _lp2e = np.log(max(current_price2, 1e-8))
                    beta_entry = (np.log(max(current_price1, 1e-8)) - current_spread) / _lp2e \
                                 if abs(_lp2e) > 1e-4 else 1.0

                    # v19: beta-weighted position sizing — clamp beta to a sane range
                    # v21: tightened clamp [0.5, 2.0] (was [0.1, 10.0]).
                    # Kalman β in regime-transition periods (e.g., W10 Apr-Jul 2023) can spike
                    # to extreme values (β≈8-10) creating 90:10 position ratios — degenerate.
                    # β=2.0 gives max 2:1 short/long ratio (67%/33%), still meaningfully hedged.
                    _safe_beta = max(0.5, min(abs(beta_entry), 2.0))
                    _beta_denom = 1.0 + _safe_beta

                    # v19: dynamic hold time — 2.5× half-life, capped at 25 trading days.
                    # Rationale: OU theory — expected reversion at t = 1 - exp(-t/HL).
                    # Fixed 10-day cap leaves HL=25 pairs only 33% expected reversion; they
                    # almost always time out before reaching z=0.5. 2.5× HL gives ≥85%
                    # expected reversion for every pair in our allowed HL=[4,25] range.
                    _pair_stats_ex = opportunity.get('pair_stats', {})
                    _pair_hl = float(_pair_stats_ex.get('half_life', 10.0))
                    _max_hold_days = max(10, min(int(2.5 * _pair_hl), 25))

                    for future_idx in range(date_idx + 1, min(date_idx + _max_hold_days + 1, len(all_dates))):
                        candidate_date = all_dates[future_idx]
                        if candidate_date not in spread.index:
                            continue

                        # v14: exit z-score uses locked-β spread normalized by locked-β reference stats.
                        # Consistent: same β (beta_entry), same reference mean/std as the entry filter.
                        # Old approach divided locked_spread_cand by Kalman rolling mean/std — mixed scales.
                        p1_cand = self.processed_data[symbol1].loc[candidate_date, 'Close'] \
                                  if candidate_date in self.processed_data[symbol1].index else current_price1
                        p2_cand = self.processed_data[symbol2].loc[candidate_date, 'Close'] \
                                  if candidate_date in self.processed_data[symbol2].index else current_price2
                        locked_spread_cand = np.log(max(p1_cand, 1e-8)) - beta_entry * np.log(max(p2_cand, 1e-8))
                        if _locked_mean_entry is not None and _locked_std_entry is not None:
                            current_zscore = (locked_spread_cand - _locked_mean_entry) / _locked_std_entry
                        else:
                            # Fallback: Kalman rolling stats (pre-v14 behavior, for rare cases where
                            # locked stats could not be computed in the gathering loop)
                            _hist_fb = spread.loc[:candidate_date]
                            if len(_hist_fb) < 30:
                                continue
                            _m_fb = _hist_fb.rolling(60, min_periods=30).mean().iloc[-1]
                            _s_fb = _hist_fb.rolling(60, min_periods=30).std().iloc[-1]
                            if _s_fb < 1e-8:
                                continue
                            current_zscore = (locked_spread_cand - _m_fb) / _s_fb

                        # v26: time-stop counts TRADING days, not calendar days.
                        # _max_hold_days is a trading-day cap (the loop iterates
                        # trading-day indices); the prior `(candidate_date-date).days`
                        # was calendar, firing ~30% early (a 25-trading-day cap hit at
                        # ~25 calendar ≈ 17 trading days).
                        trading_days_held = future_idx - date_idx

                        if action == 0:
                            if current_zscore > -0.5 or (current_zscore - entry_spread_zscore > 1.0) or trading_days_held >= _max_hold_days:
                                next_date = candidate_date
                                break
                        else:
                            if current_zscore < 0.5 or (entry_spread_zscore - current_zscore > 1.0) or trading_days_held >= _max_hold_days:
                                next_date = candidate_date
                                break

                    if next_date is None:
                        continue

                    total_position_value = position_size

                    # v26: enforce the gross-exposure cap against real concurrent
                    # open exposure (the risk manager's 30% limit). Previously
                    # exposure was hardcoded to 0 so this never bound.
                    _pos_pct = total_position_value / portfolio_value
                    if open_exposure + _pos_pct > self.risk_manager.max_total_exposure:
                        continue

                    # v22: equal-dollar position sizing (reverted from v19 beta-weighted).
                    # Empirical evidence across v19-v21: beta-weighted P&L with noisy Kalman β
                    # amplified losses in OOS regime-transition periods (W10 -3.85%, W18 halved).
                    # Equal-dollar is simpler and was v18's formula — the best OOS performer.
                    # The Kalman spread is still used for entry/exit signal generation.
                    if action == 0:   # long p1, short p2
                        long_position_size  = total_position_value / 2.0 / current_price1
                        short_position_size = total_position_value / 2.0 / current_price2
                        long_symbol, short_symbol = symbol1, symbol2
                        long_price, short_price = current_price1, current_price2
                    else:             # short p1, long p2
                        long_position_size  = total_position_value / 2.0 / current_price2
                        short_position_size = total_position_value / 2.0 / current_price1
                        long_symbol, short_symbol = symbol2, symbol1
                        long_price, short_price = current_price2, current_price1

                    holding_days = max(1, (next_date - date).days)

                    trade_costs = self.cost_model.calculate_total_trade_costs(
                        long_position_size, short_position_size,
                        long_price, short_price,
                        long_symbol, short_symbol,
                        holding_days=holding_days
                    )

                    total_trade_cost = trade_costs['total_cost']
                    cost_pct = total_trade_cost / portfolio_value

                    if cost_pct > 0.01:
                        continue

                    # v22: equal-dollar P&L (reverted from v19 beta-weighted).
                    price1_exit = self.processed_data[symbol1].loc[next_date, 'Close'] \
                                  if next_date in self.processed_data[symbol1].index else current_price1
                    price2_exit = self.processed_data[symbol2].loc[next_date, 'Close'] \
                                  if next_date in self.processed_data[symbol2].index else current_price2
                    log_ret1 = np.log(max(price1_exit, 1e-8) / max(current_price1, 1e-8))
                    log_ret2 = np.log(max(price2_exit, 1e-8) / max(current_price2, 1e-8))
                    if action == 0:   # long p1, short p2
                        spread_return = log_ret1 - log_ret2
                    else:             # short p1, long p2
                        spread_return = log_ret2 - log_ret1
                    gross_pnl_pct = spread_return * (total_position_value / 2.0) / portfolio_value

                    net_pnl_pct = gross_pnl_pct - cost_pct

                    trade_record = {
                        'date': date,
                        'pair': pair_string,
                        'action': 'LONG' if action == 0 else 'SHORT',
                        'position_size': total_position_value,
                        'position_pct': total_position_value / portfolio_value,
                        'signal_strength': signal_strength,
                        'zscore': zscore,
                        'pair_quality': pair_quality,
                        'feature_quality': opportunity['feature_quality'],
                        'spread_return': spread_return,
                        'gross_pnl_pct': gross_pnl_pct,
                        'transaction_costs': total_trade_cost,
                        'transaction_cost_pct': cost_pct,
                        'net_pnl_pct': net_pnl_pct,
                        'pnl_dollar': net_pnl_pct * portfolio_value,
                        'holding_days': holding_days,
                        'cost_breakdown': trade_costs
                    }

                    trades.append(trade_record)
                    day_trade_details.append(trade_record)

                    # v13: Update per-pair consecutive loss streak for cooling-off logic
                    _t_pair = trade_record['pair']
                    if trade_record['net_pnl_pct'] < 0:
                        pair_loss_streak[_t_pair] = pair_loss_streak.get(_t_pair, 0) + 1
                        if pair_loss_streak[_t_pair] >= 3:
                            pair_cooloff_until[_t_pair] = date  # trigger 30-cal-day cooloff
                    else:
                        pair_loss_streak[_t_pair] = 0
                        pair_cooloff_until.pop(_t_pair, None)   # win resets cooloff

                    # FIX: Book PnL on exit date, not entry date
                    pending_pnl[next_date] = pending_pnl.get(next_date, 0.0) + net_pnl_pct
                    day_costs += total_trade_cost
                    daily_trades += 1
                    total_costs += total_trade_cost

                    # v26: add to live gross exposure; release it on the exit date.
                    open_exposure += _pos_pct
                    exposure_release[next_date] = exposure_release.get(next_date, 0.0) + _pos_pct
                    # v26: stamp last-trade date on actual EXECUTION (moved out of
                    # validate_signal, which fired for ranked-out candidates too).
                    self.risk_manager.last_trade_dates[pair_string] = date
                    # v27: lock both legs until exit so neither stock can appear in a
                    # concurrent pair (v22 cross-symbol intent, was declared but never populated).
                    _active_symbols[symbol1] = next_date
                    _active_symbols[symbol2] = next_date

                    self.position_sizer.record_trade(pair_string, net_pnl_pct)
                    self.risk_manager.daily_trade_count = daily_trades

                    if len(trades) <= 5:
                        logger.info(f"TRADE {len(trades)}: {pair_string} {trade_record['action']} "
                                   f"zscore={zscore:.2f} quality={pair_quality:.2f} cost={cost_pct:.3%}")

                except Exception as e:
                    continue

            daily_pnl.append(day_pnl)
            daily_dates.append(date)   # v26: real date per daily_pnl entry
            portfolio_value *= (1 + day_pnl)
            max_daily_trades = max(max_daily_trades, daily_trades)

            # Update risk manager with current portfolio state (v26: real exposure)
            self.risk_manager.update_daily_stats(daily_trades, open_exposure, day_pnl, portfolio_value)

            # Check logical risk controls
            should_stop, stop_reason = self.risk_manager.should_stop_trading(day_pnl)
            if should_stop:
                logger.warning(f"LOGICAL Risk Management: {stop_reason}")
                break

        # Log regime gate activation summary
        if _regime_scale_counts:
            full_days = _regime_scale_counts.get(1.0, 0)
            reduced_days = sum(cnt for scale, cnt in _regime_scale_counts.items() if scale < 1.0)
            logger.info(f"Regime gate summary: {full_days} full-scale days, "
                        f"{reduced_days} reduced-scale days | "
                        f"breakdown: {dict(sorted(_regime_scale_counts.items(), reverse=True))}")

        total_return = (portfolio_value - self.initial_capital) / self.initial_capital
        total_cost_impact = total_costs / self.initial_capital

        if len(trades) > 0:
            winning_trades = [t for t in trades if t['net_pnl_pct'] > 0]
            losing_trades = [t for t in trades if t['net_pnl_pct'] < 0]

            win_rate = len(winning_trades) / len(trades)
            avg_win = np.mean([t['net_pnl_pct'] for t in winning_trades]) if winning_trades else 0
            avg_loss = np.mean([abs(t['net_pnl_pct']) for t in losing_trades]) if losing_trades else 0
            profit_factor = (avg_win * len(winning_trades)) / (avg_loss * len(losing_trades)) if avg_loss > 0 and losing_trades else 0

            avg_cost_per_trade = total_costs / len(trades)
            avg_cost_pct = np.mean([t['transaction_cost_pct'] for t in trades])

            avg_signal_strength = np.mean([t['signal_strength'] for t in trades])
            avg_pair_quality = np.mean([t['pair_quality'] for t in trades])
            high_quality_trades = len([t for t in trades if t.get('feature_quality', 0) > 0.7])
        else:
            win_rate = avg_win = avg_loss = profit_factor = 0
            avg_cost_per_trade = avg_cost_pct = 0
            avg_signal_strength = avg_pair_quality = 0
            high_quality_trades = 0

        if len(daily_pnl) > 1:
            # v25: Sharpe/vol on ALL calendar days, flat days included. Dropping
            # zero-PnL days deflated the std and inflated per-window Sharpes
            # (9-20+ in v23 logs); it also zeroed max_drawdown for sparse windows.
            daily_returns = np.array(daily_pnl)
            sharpe_ratio = np.mean(daily_returns) / (np.std(daily_returns) + 1e-8) * np.sqrt(252)
            max_drawdown = self._calculate_max_drawdown(daily_returns)
            volatility = np.std(daily_returns) * np.sqrt(252)
        else:
            sharpe_ratio = max_drawdown = volatility = 0

        results = {
            'total_return': total_return,
            'annualized_return': total_return * 252 / len(all_dates) if len(all_dates) > 0 else 0,
            'final_portfolio_value': portfolio_value,
            'total_trades': len(trades),
            'trade_count': len(trades),
            'trades_per_day': len(trades) / len(all_dates) if len(all_dates) > 0 else 0,
            'max_daily_trades': max_daily_trades,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'volatility': volatility,

            'total_transaction_costs': total_costs,
            'total_cost_impact_pct': total_cost_impact,
            'avg_cost_per_trade': avg_cost_per_trade,
            'avg_cost_pct_per_trade': avg_cost_pct,

            'quality_opportunities': quality_opportunities,
            'avg_signal_strength': avg_signal_strength,
            'avg_pair_quality': avg_pair_quality,
            'high_quality_trades': high_quality_trades,
            'avg_trade_return': np.mean([t['net_pnl_pct'] for t in trades]) if trades else 0,

            'trades': trades,
            'daily_pnl': daily_pnl,
            'daily_returns': daily_pnl,
            # v26: real calendar date per daily_pnl entry (stringified) so the JSON
            # export dates the equity curve correctly instead of synthesizing one.
            'daily_dates': [str(d.date()) if hasattr(d, 'date') else str(d) for d in daily_dates],
            'test_period_days': len(all_dates)
        }

        logger.info(f"FIXED BACKTEST COMPLETED")

        return results

    def _calculate_max_drawdown(self, returns: np.ndarray) -> float:
        """Calculate maximum drawdown"""
        cumulative = np.cumprod(1 + returns)
        peak = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - peak) / peak
        return np.min(drawdown) if len(drawdown) > 0 else 0.0

    def run_walk_forward_validation(self, train_window_days: int = 252, test_window_days: int = 63,
                                    episodes_per_window: int = 200, pair_windows: Dict = None) -> Dict:
        """Walk-forward validation with rolling train/test windows.

        Each window:
          - train_window_days (252 = 1 year) of spread data used for model training
          - test_window_days  (63 = 1 quarter) immediately after, out-of-sample
          - Agent retrained from scratch each window (200 episodes, fast)

        pair_windows: quarterly re-selection output. If provided, the union of all
        pairs across all windows is used as the spread universe (much richer than
        the small initial self.spread_data set).

        Returns aggregated results dict including per-window breakdown.
        """
        logger.info("=" * 60)
        logger.info("WALK-FORWARD VALIDATION")
        logger.info(f"  Train window: {train_window_days} days | Test window: {test_window_days} days")
        logger.info(f"  Episodes/window: {episodes_per_window}")
        logger.info("=" * 60)

        # Build merged spread dict from all quarterly windows so walk-forward
        # has the same rich pair universe as the main backtest.
        # self.spread_data alone only has the initial ~30 pairs (too sparse for
        # short 63-day windows to generate any trades).
        if pair_windows:
            merged_spreads = {}
            for window_spreads in pair_windows.values():
                for pair_key, spread in window_spreads.items():
                    if pair_key not in merged_spreads:
                        merged_spreads[pair_key] = spread
                    else:
                        # Keep the longest spread series for each pair
                        if len(spread) > len(merged_spreads[pair_key]):
                            merged_spreads[pair_key] = spread
            logger.info(f"  Walk-forward spread universe: {len(merged_spreads)} unique pairs "
                        f"(merged from {len(pair_windows)} quarterly windows)")
            spread_source = merged_spreads
        else:
            spread_source = self.spread_data
            logger.info(f"  Walk-forward spread universe: {len(spread_source)} pairs (initial selection)")

        # Collect all available dates across merged spread universe
        all_dates = sorted(set(
            date for spread in spread_source.values() for date in spread.index
        ))
        if len(all_dates) < train_window_days + test_window_days:
            logger.warning("Insufficient data for walk-forward validation")
            return {}

        # Build non-overlapping windows
        windows = []
        idx = 0
        while idx + train_window_days + test_window_days <= len(all_dates):
            train_start = all_dates[idx]
            train_end   = all_dates[idx + train_window_days - 1]
            test_start  = all_dates[idx + train_window_days]
            test_end    = all_dates[min(idx + train_window_days + test_window_days - 1, len(all_dates) - 1)]
            windows.append((train_start, train_end, test_start, test_end))
            idx += test_window_days  # step by one test window (non-overlapping test periods)

        logger.info(f"Walk-forward: {len(windows)} windows")

        wf_results = []
        cumulative_equity = [self.initial_capital]

        for w_idx, (train_start, train_end, test_start, test_end) in enumerate(windows):
            logger.info(f"\nWindow {w_idx+1}/{len(windows)}: "
                        f"Train {train_start.date()}→{train_end.date()} | "
                        f"Test {test_start.date()}→{test_end.date()}")

            # Resolve test date range with proper timezone (use first spread as ref)
            test_date_range = (test_start, test_end)
            for _, ref_spread in spread_source.items():
                try:
                    if hasattr(ref_spread.index, 'tz') and ref_spread.index.tz is not None:
                        tz = ref_spread.index.tz
                        _ts2 = test_start.tz_localize(tz) if test_start.tzinfo is None else test_start
                        _te2 = test_end.tz_localize(tz) if test_end.tzinfo is None else test_end
                        test_date_range = (_ts2, _te2)
                    else:
                        _ts2 = test_start if test_start.tzinfo is None else test_start.tz_localize(None)
                        _te2 = test_end if test_end.tzinfo is None else test_end.tz_localize(None)
                        test_date_range = (_ts2, _te2)
                except Exception:
                    pass
                break  # only need one reference spread

            # Slice spreads for this window
            window_train = {}
            # window_test uses full-history spreads (up to test_end) so that
            # run_comprehensive_backtest has ≥50 days of context for feature
            # extraction. Trading is restricted to test dates via date_range.
            window_test  = {}
            for pair_key, spread in spread_source.items():
                try:
                    if hasattr(spread.index, 'tz') and spread.index.tz is not None:
                        ts  = train_start.tz_localize(spread.index.tz) if train_start.tzinfo is None else train_start
                        te  = train_end.tz_localize(spread.index.tz) if train_end.tzinfo is None else train_end
                        ts2 = test_start.tz_localize(spread.index.tz) if test_start.tzinfo is None else test_start
                        te2 = test_end.tz_localize(spread.index.tz) if test_end.tzinfo is None else test_end
                    else:
                        ts  = train_start if train_start.tzinfo is None else train_start.tz_localize(None)
                        te  = train_end  if train_end.tzinfo  is None else train_end.tz_localize(None)
                        ts2 = test_start if test_start.tzinfo is None else test_start.tz_localize(None)
                        te2 = test_end   if test_end.tzinfo   is None else test_end.tz_localize(None)

                    tr = spread[(spread.index >= ts) & (spread.index <= te)]
                    # Full history up to test_end for context; date_range will
                    # limit which days actually generate trades.
                    tst_check = spread[(spread.index >= ts2) & (spread.index <= te2)]
                    tst_full  = spread[spread.index <= te2]
                    if len(tr) >= 50:
                        window_train[pair_key] = tr
                    if len(tst_check) >= 10:
                        window_test[pair_key] = tst_full
                except Exception:
                    continue

            if not window_train or not window_test:
                logger.warning(f"  Window {w_idx+1}: insufficient spread data, skipping")
                continue

            # Retrain agent on this window's training data
            window_agent = FixedTransformerMultiAgentSystem()
            window_agent.pair_statistics = self.pair_selector.pair_statistics  # v27: real stats
            window_agent.train_agent(window_train, episodes=episodes_per_window)

            # Swap in the window agent temporarily
            original_agent = self.rl_agent
            self.rl_agent = window_agent

            # Run backtest on this window's test period only (full spreads for
            # feature context, date_range restricts trading to test dates)
            window_result = self.run_comprehensive_backtest(
                window_test, date_range=test_date_range
            )

            # Restore original agent
            self.rl_agent = original_agent

            window_return = window_result.get('total_return', 0)
            window_sharpe = window_result.get('sharpe_ratio', 0)
            window_trades = window_result.get('total_trades', 0)
            window_wr     = window_result.get('win_rate', 0)
            window_dd     = window_result.get('max_drawdown', 0)

            cumulative_equity.append(cumulative_equity[-1] * (1 + window_return))

            wf_results.append({
                'window': w_idx + 1,
                'train_start': str(train_start.date()),
                'train_end':   str(train_end.date()),
                'test_start':  str(test_start.date()),
                'test_end':    str(test_end.date()),
                'total_return_pct': round(window_return * 100, 4),
                'sharpe_ratio': round(window_sharpe, 3),
                'max_drawdown_pct': round(window_dd * 100, 4),
                'total_trades': window_trades,
                'win_rate_pct': round(window_wr * 100, 2),
            })

            logger.info(f"  → Return: {window_return:.2%} | Sharpe: {window_sharpe:.2f} | "
                        f"Trades: {window_trades} | WR: {window_wr:.1%} | DD: {window_dd:.2%}")

        # Aggregate
        if not wf_results:
            return {}

        returns = [w['total_return_pct'] / 100 for w in wf_results]
        profitable_windows = sum(1 for r in returns if r > 0)
        stitched_return = cumulative_equity[-1] / self.initial_capital - 1

        summary = {
            'windows': wf_results,
            'total_windows': len(wf_results),
            'profitable_windows': profitable_windows,
            'profitable_window_pct': round(profitable_windows / len(wf_results) * 100, 1),
            'avg_window_return_pct': round(float(sum(returns)) / len(returns) * 100, 4),
            'median_window_return_pct': round(sorted(returns)[len(returns)//2] * 100, 4),
            'avg_sharpe': round(sum(w['sharpe_ratio'] for w in wf_results) / len(wf_results), 3),
            'stitched_total_return_pct': round(stitched_return * 100, 4),
        }

        # ── Hard era split: IS (W1-W9) vs OOS (W10+) ─────────────────────────
        # W10 test starts 2023-04-04 — the confirmed regime break date.
        # Lopez de Prado's "purged cross-validation" principle: treat any window
        # whose TEST period starts after the regime shift as true out-of-sample.
        # IS windows trained and tested fully inside the ZIRP/transition era.
        # OOS windows test in the post-hike, Mag-7-dominated regime.
        _regime_break_date = pd.Timestamp('2023-04-04')

        def _era_stats(windows):
            if not windows:
                return {'count': 0, 'profitable': 0, 'avg_return_pct': 0.0,
                        'avg_sharpe': 0.0, 'avg_win_rate_pct': 0.0, 'avg_max_dd_pct': 0.0}
            _rets = [w['total_return_pct'] / 100 for w in windows]
            return {
                'count':            len(windows),
                'profitable':       sum(1 for r in _rets if r > 0),
                'avg_return_pct':   round(float(np.mean(_rets)) * 100, 4),
                'avg_sharpe':       round(float(np.mean([w['sharpe_ratio'] for w in windows])), 3),
                'avg_win_rate_pct': round(float(np.mean([w['win_rate_pct'] for w in windows])), 2),
                'avg_max_dd_pct':   round(float(np.mean([abs(w['max_drawdown_pct']) for w in windows])), 4),
            }

        is_windows  = [w for w in wf_results if pd.Timestamp(w['test_start']) < _regime_break_date]
        oos_windows = [w for w in wf_results if pd.Timestamp(w['test_start']) >= _regime_break_date]
        is_stats    = _era_stats(is_windows)
        oos_stats   = _era_stats(oos_windows)

        summary['in_sample_era']     = is_stats
        summary['out_of_sample_era'] = oos_stats

        logger.info("\n" + "=" * 60)
        logger.info("WALK-FORWARD SUMMARY")
        logger.info(f"  Windows: {summary['total_windows']} | Profitable: {summary['profitable_windows']} ({summary['profitable_window_pct']}%)")
        logger.info(f"  Avg window return: {summary['avg_window_return_pct']:.4f}%")
        logger.info(f"  Avg Sharpe: {summary['avg_sharpe']:.3f}")
        logger.info(f"  Stitched total return: {summary['stitched_total_return_pct']:.4f}%")
        logger.info("")
        logger.info("  HARD ERA SPLIT (regime break boundary: 2023-04-04)")
        logger.info(f"  In-sample  (W1-W9,  pre-regime) : {is_stats['count']:2d} windows | "
                    f"avg {is_stats['avg_return_pct']:+7.2f}%/qtr | "
                    f"Sharpe {is_stats['avg_sharpe']:5.3f} | "
                    f"WR {is_stats['avg_win_rate_pct']:.1f}%")
        logger.info(f"  OOS (W10-W19, post-regime break): {oos_stats['count']:2d} windows | "
                    f"avg {oos_stats['avg_return_pct']:+7.2f}%/qtr | "
                    f"Sharpe {oos_stats['avg_sharpe']:5.3f} | "
                    f"WR {oos_stats['avg_win_rate_pct']:.1f}%")
        if is_stats['count'] > 0 and oos_stats['count'] > 0:
            _degradation = (is_stats['avg_return_pct'] - oos_stats['avg_return_pct']) / (abs(is_stats['avg_return_pct']) + 1e-8) * 100
            logger.info(f"  IS→OOS degradation: {_degradation:.1f}% "
                        f"[30-50% expected per QuantifiedStrategies research]")
        logger.info("=" * 60)

        return summary

    def build_rolling_pair_schedule(self, all_test_dates: list, reselect_every: int = 90) -> Dict:
        """Build a quarterly pair re-selection schedule.

        Every `reselect_every` trading days, re-test only the initial pair pool
        (found on 2020-2022 data) against a rolling 2-year window ending on that
        date. Pairs that are still cointegrated in the window are kept active.

        This avoids repeating the full O(n²) pair search — which is slow and
        memory-intensive — while still adapting the active universe over time.
        No look-ahead bias: pairs were selected on 2020-2022 data only.
        """
        logger.info(f"Building quarterly pair schedule (every {reselect_every} trading days)...")

        schedule_dates = [all_test_dates[i] for i in range(0, len(all_test_dates), reselect_every)]
        if all_test_dates[0] not in schedule_dates:
            schedule_dates = [all_test_dates[0]] + schedule_dates

        # Candidate pool: initial pairs discovered on 2020-2022 training data
        candidate_pairs = list(self.spread_data.keys())
        logger.info(f"  Candidate pool: {len(candidate_pairs)} initial pairs to re-test each window")

        pair_windows = {}

        for resel_date in schedule_dates:
            logger.info(f"QUARTERLY RE-SELECTION at {resel_date.date()} — re-testing {len(candidate_pairs)} candidate pairs")

            # Build rolling 2-year window ending on resel_date (strictly no look-ahead)
            window_data = {}
            for sym, df in self.processed_data.items():
                try:
                    idx = df.index
                    if hasattr(idx, 'tz') and idx.tz is not None:
                        cutoff = resel_date.tz_localize(idx.tz) if resel_date.tzinfo is None else resel_date
                        start_cutoff = (resel_date - pd.Timedelta(days=730)).tz_localize(idx.tz) if resel_date.tzinfo is None else (resel_date - pd.Timedelta(days=730))
                    else:
                        cutoff = resel_date if resel_date.tzinfo is None else resel_date.tz_localize(None)
                        start_cutoff = cutoff - pd.Timedelta(days=730)
                    filtered = df[(df.index >= start_cutoff) & (df.index <= cutoff)]
                    if len(filtered) >= 100:
                        window_data[sym] = filtered
                except Exception:
                    continue

            # Re-test only the candidate pairs (not all O(n²) combinations)
            window_spreads = {}
            kept = 0
            dropped_6m = 0
            dropped_diverge = 0
            for sym1, sym2 in candidate_pairs:
                if sym1 not in window_data or sym2 not in window_data:
                    continue
                is_coint, p2yr = self.pair_selector.test_cointegration(
                    window_data[sym1], window_data[sym2]
                )
                if not is_coint:
                    continue

                # ── Adaptive 6-month cointegration test ───────────────────────────────
                # A pair that passes the 2-year ADF test but FAILS the recent 6-month
                # test is anchoring on a dead regime (e.g. ZIRP 2020-2022 data dilutes
                # post-hike 2023 signal).  Drop it to avoid trading stale relationships.
                # Root cause of 28% → 8.8% pair survival collapse: pairs kept too long.
                start_6m = resel_date - pd.Timedelta(days=126)  # ~6 calendar months
                d6m_data = {}
                for sym in (sym1, sym2):
                    idx = window_data[sym].index
                    if hasattr(idx, 'tz') and idx.tz is not None:
                        s6m = start_6m.tz_localize(idx.tz) if start_6m.tzinfo is None else start_6m
                    else:
                        s6m = start_6m if start_6m.tzinfo is None else start_6m.tz_localize(None)
                    sliced = window_data[sym][window_data[sym].index >= s6m]
                    if len(sliced) >= 60:
                        d6m_data[sym] = sliced

                if sym1 in d6m_data and sym2 in d6m_data:
                    try:
                        log_p1 = np.log(d6m_data[sym1]['Close'].values + 1e-8)
                        log_p2 = np.log(d6m_data[sym2]['Close'].values + 1e-8)
                        min_len = min(len(log_p1), len(log_p2))
                        if min_len >= 30:
                            _, p6a, _ = _coint(log_p1[:min_len], log_p2[:min_len])
                            _, p6b, _ = _coint(log_p2[:min_len], log_p1[:min_len])
                            p6 = min(p6a, p6b)
                            # v8 Fix: raised from 0.05 to 0.15 — ADF/EG test has ~45% power
                            # at n=90 obs (6 calendar months). The old p<0.05 threshold caused
                            # 88.5% false rejection: valid LIVE pairs dropped as "stale" due to
                            # insufficient data, not actual relationship decay. p<0.15 is still
                            # selective (rejects pairs where recent data is clearly non-cointegrated)
                            # while keeping pairs with moderate but plausible recent evidence.
                            if p6 > 0.15:
                                dropped_6m += 1
                                continue  # Recent 6-month test clearly failed → relationship decayed
                            if abs(p6 - p2yr) > 0.10:
                                dropped_diverge += 1
                                continue  # 6m vs 2yr diverge → structural break underway
                    except Exception:
                        pass  # 6m test error → keep pair conservatively

                spread = self.calculate_spread(
                    self.processed_data[sym1], self.processed_data[sym2]
                )
                if not spread.empty:
                    window_spreads[(sym1, sym2)] = spread
                    kept += 1

            logger.info(f"  Kept {kept}/{len(candidate_pairs)} pairs still cointegrated in rolling window")
            logger.info(f"  Adaptive filter: dropped {dropped_6m} (6m test failed) + {dropped_diverge} (6m/2yr diverge)")
            pair_windows[resel_date] = window_spreads

        logger.info(f"Quarterly schedule built: {len(pair_windows)} windows")
        return pair_windows

    def run_fund_type_comparison(self, main_results: Dict,
                                 main_daily_dates: list = None) -> Dict:
        """
        Replay the SAME trade signals from the main backtest under five different
        institutional fund profiles (costs + position sizing).

        Why replay instead of re-running from scratch?
        ─ Signals (z-score, entry/exit dates, spread returns) are market facts —
          they don't change with fund type.
        ─ Only the ECONOMICS differ: how large the position is and how much it costs.
        ─ This isolates the effect of fund structure on strategy P&L.
        ─ It is also fast (seconds, not hours).

        Approach:
          For each trade record from the main backtest we know:
            trade['zscore'], trade['action'], trade['spread_return'], trade['holding_days']
          We recalculate:
            position size  = profile.base_position_pct × z_scaling, capped at max_position_pct
            transaction costs = profile-specific rates via calculate_profile_trade_costs()
            net PnL         = spread_return × position_fraction ± costs
          Then track the equity curve chronologically, applying a drawdown kill-switch
          when the profile's max_drawdown_limit is hit.
        """
        from pairs_trading.fund_profiles import FUND_PROFILES, get_profile_summary_table
        from pairs_trading.transaction_costs import calculate_profile_trade_costs

        logger.info(get_profile_summary_table())

        trades = main_results.get('trades', [])
        if not trades:
            logger.warning("Fund comparison: no trades in main results, skipping.")
            return {}

        # Sort trades chronologically so per-date equity tracking is correct
        sorted_trades = sorted(trades, key=lambda t: t['date'])

        SOFR = 0.050        # current SOFR (2025)
        comparison = {}

        for profile_key, profile in FUND_PROFILES.items():
            logger.info(f"\n{'─'*70}")
            logger.info(f"Fund comparison — simulating: {profile.name}")
            logger.info(f"  {profile.description}")
            logger.info(f"  Base pos: {profile.base_position_pct:.0%} | "
                        f"Max pos: {profile.max_position_pct:.0%} | "
                        f"Max DD: {profile.max_drawdown_limit:.0%} | "
                        f"Leverage: {profile.gross_leverage_label}")

            equity         = float(self.initial_capital)
            peak_equity    = equity
            max_drawdown   = 0.0
            stopped_early  = False

            # Accumulate daily PnL: date → (gross_pnl, cost, net_pnl)
            # We book PnL on the EXIT date (entry_date + holding_days calendar days).
            # Using a pending-PnL dict keeps us look-ahead-bias free within the replay.
            pending_pnl: Dict = {}   # exit_date → cumulative net_pnl_fraction
            pending_costs: Dict = {} # exit_date → cumulative costs breakdown

            trade_records = []

            for trade in sorted_trades:
                entry_date   = trade['date']
                zscore       = abs(trade['zscore'])
                action       = trade['action']               # 'LONG' or 'SHORT'
                spread_ret   = trade['spread_return']        # signed spread change
                holding_days = max(1, trade['holding_days'])
                pair_str     = trade['pair']
                long_sym     = pair_str.split('-')[0] if '-' in pair_str else 'AAPL'
                short_sym    = pair_str.split('-')[1] if '-' in pair_str else 'MSFT'

                # Skip entry if equity already below initial (deep loss) or stopped
                if stopped_early:
                    break

                # ── Position sizing ─────────────────────────────────────────────
                # z-score scaling (same logic as main backtest): stronger signal → larger pos
                z_mult = min(zscore / 2.3, 2.0)
                raw_fraction = profile.base_position_pct * z_mult
                # Cap at profile max — this is the gross position fraction of equity
                position_fraction = min(raw_fraction, profile.max_position_pct)
                position_value    = position_fraction * equity

                # ── Transaction costs for this profile ──────────────────────────
                cost_dict = calculate_profile_trade_costs(
                    position_value, profile, holding_days, SOFR,
                    long_symbol=long_sym, short_symbol=short_sym
                )
                total_cost    = cost_dict['total_cost']
                cost_fraction = total_cost / max(equity, 1.0)

                # ── Gross PnL ────────────────────────────────────────────────────
                # v26 FIX: trade['spread_return'] is ALREADY directional
                # (profit-positive) — the main backtest stores log_ret1−log_ret2 for
                # longs and log_ret2−log_ret1 for shorts, then books it with NO sign
                # flip. The prior `-spread_ret` for SHORT double-negated every short
                # trade's P&L, inverting winners and losers for ~half the book. Both
                # directions use +spread_ret, matching the main backtest and this
                # function's own docstring (net PnL = spread_return × fraction ± cost).
                gross_fraction = spread_ret * position_fraction

                net_fraction = gross_fraction - cost_fraction

                # Book on EXIT date (entry + holding_days calendar days)
                exit_date = entry_date + pd.Timedelta(days=holding_days)

                pending_pnl[exit_date]  = pending_pnl.get(exit_date, 0.0)  + net_fraction
                # Accumulate cost components for breakdown
                if exit_date not in pending_costs:
                    pending_costs[exit_date] = {k: 0.0 for k in
                                                ['commission','bid_ask','market_impact',
                                                 'borrow','financing']}
                for k in pending_costs[exit_date]:
                    pending_costs[exit_date][k] += cost_dict.get(k, 0.0)

                trade_records.append({
                    'date':             entry_date,
                    'exit_date':        exit_date,
                    'pair':             pair_str,
                    'action':           action,
                    'position_fraction':position_fraction,
                    'gross_fraction':   gross_fraction,
                    'cost_fraction':    cost_fraction,
                    'net_fraction':     net_fraction,
                    'holding_days':     holding_days,
                    'cost_breakdown':   cost_dict,
                })

            # ── Build equity curve by walking through sorted exit dates ──────────
            all_exit_dates = sorted(pending_pnl.keys())
            daily_equity_curve  = []   # (date, equity_value)
            daily_return_series = []

            equity         = float(self.initial_capital)
            peak_equity    = equity
            max_drawdown   = 0.0
            stopped_early  = False
            stopped_date   = None

            for exit_date in all_exit_dates:
                day_net = pending_pnl[exit_date]

                prev_equity = equity
                equity      = equity * (1.0 + day_net)

                daily_return_series.append(day_net)
                daily_equity_curve.append((exit_date, equity))

                # Update peak and drawdown
                if equity > peak_equity:
                    peak_equity  = equity
                current_dd = (peak_equity - equity) / max(peak_equity, 1.0)
                if current_dd > max_drawdown:
                    max_drawdown = current_dd

                # Kill-switch
                if current_dd >= profile.max_drawdown_limit:
                    logger.warning(
                        f"  {profile.name}: Kill-switch at {current_dd:.2%} drawdown "
                        f"on {exit_date.date()} — stopping."
                    )
                    stopped_early = True
                    stopped_date  = exit_date
                    break

            # ── Per-trade metrics — only count trades closed before kill-switch ──
            if stopped_early:
                active_trades = [t for t in trade_records if t['exit_date'] <= stopped_date]
            else:
                active_trades = trade_records

            winning = [t for t in active_trades if t['net_fraction'] > 0]
            losing  = [t for t in active_trades if t['net_fraction'] < 0]
            n_trades = len(active_trades)
            win_rate  = len(winning) / n_trades if n_trades else 0.0
            avg_win   = float(np.mean([t['net_fraction'] for t in winning])) if winning else 0.0
            avg_loss  = float(np.mean([abs(t['net_fraction']) for t in losing]))  if losing  else 0.0
            profit_factor = (
                (avg_win * len(winning)) / (avg_loss * len(losing))
                if avg_loss > 0 and losing else 0.0
            )

            # ── Return / Sharpe ──────────────────────────────────────────────────
            total_return = (equity - self.initial_capital) / self.initial_capital

            # v27: Sharpe on ALL trading days, not just exit dates.
            # Prior code only appended to daily_return_series on exit dates (when
            # pending_pnl had an entry), so the std was understated and Sharpe
            # was inflated — the same bug fixed for the main backtest in v25.
            # Fix: build a zero-padded return series over the full backtest period
            # using main_daily_dates if available; otherwise fall back to exit-only.
            if main_daily_dates:
                # v27 (audit cont.): build a zero-padded daily return series over the
                # full backtest calendar (P&L lands on exit dates, 0 elsewhere). Only
                # returns_arr and n_days are consumed downstream — the earlier draft
                # also recomputed an equity curve / max-drawdown here that was never
                # used (zero-padding can't change total_return or drawdown, which the
                # exit-date loop above already computes), so that dead block is gone.
                full_returns = []
                for d in main_daily_dates:
                    ts = pd.Timestamp(d)
                    if stopped_early and stopped_date is not None and ts > stopped_date:
                        break
                    full_returns.append(pending_pnl.get(ts, 0.0))
                returns_arr = np.array(full_returns)
                n_days = len(full_returns)
            else:
                returns_arr = np.array(daily_return_series)
                n_days = len(daily_return_series)

            sharpe = (
                float(np.mean(returns_arr) / (np.std(returns_arr) + 1e-10) * np.sqrt(252))
                if len(returns_arr) > 1 else 0.0
            )

            # ── Cost breakdown totals (only active trades) ───────────────────────
            cost_components = {k: 0.0 for k in
                               ['commission','bid_ask','market_impact','borrow','financing']}
            for t in active_trades:
                for k in cost_components:
                    cost_components[k] += t['cost_breakdown'].get(k, 0.0)
            total_cost_dollars = sum(cost_components.values())
            cost_pct_of_capital = total_cost_dollars / self.initial_capital * 100.0

            # ── Annualised return ─────────────────────────────────────────────────
            # v27: use actual trading-day count (len of all backtest dates) not
            # exit-date count. Prior code used len(daily_return_series) = number
            # of exit days (~71 trades), grossly overstating annualised return.
            annualized_return = total_return * 252.0 / max(n_days, 1)

            comparison[profile_key] = {
                'profile_key':         profile_key,
                'profile_name':        profile.name,
                'description':         profile.description,
                'example_firms':       profile.example_firms,
                'gross_leverage_label':profile.gross_leverage_label,

                # Risk / cost parameters
                'commission_bps':      profile.commission_bps,
                'bid_ask_bps':         profile.bid_ask_bps,
                'market_impact_cap_bps': profile.market_impact_cap_bps,
                'borrow_rate_easy_pct': profile.borrow_rate_easy * 100,
                'financing_spread_pct': profile.financing_spread * 100,
                'base_position_pct':   profile.base_position_pct * 100,
                'max_position_pct':    profile.max_position_pct * 100,
                'max_drawdown_limit_pct': profile.max_drawdown_limit * 100,

                # Performance
                'total_return_pct':    round(total_return * 100, 4),
                'annualized_return_pct': round(annualized_return * 100, 4),
                'final_equity':        round(equity, 2),
                'max_drawdown_pct':    round(-max_drawdown * 100, 4),
                'sharpe_ratio':        round(sharpe, 3),
                'win_rate_pct':        round(win_rate * 100, 2),
                'profit_factor':       round(profit_factor, 3),
                'total_trades':        n_trades,
                'trades_stopped_early':stopped_early,

                # Cost breakdown
                'total_cost_dollars':        round(total_cost_dollars, 2),
                'total_cost_pct_of_capital': round(cost_pct_of_capital, 4),
                'cost_components': {
                    'commission_dollars':    round(cost_components['commission'], 2),
                    'bid_ask_dollars':       round(cost_components['bid_ask'], 2),
                    'market_impact_dollars': round(cost_components['market_impact'], 2),
                    'borrow_dollars':        round(cost_components['borrow'], 2),
                    'financing_dollars':     round(cost_components['financing'], 2),
                    # As % of initial capital
                    'commission_pct':    round(cost_components['commission']    / self.initial_capital * 100, 4),
                    'bid_ask_pct':       round(cost_components['bid_ask']       / self.initial_capital * 100, 4),
                    'market_impact_pct': round(cost_components['market_impact'] / self.initial_capital * 100, 4),
                    'borrow_pct':        round(cost_components['borrow']        / self.initial_capital * 100, 4),
                    'financing_pct':     round(cost_components['financing']     / self.initial_capital * 100, 4),
                },

                # Daily equity curve for plotting
                'equity_curve': [
                    {'date': str(d.date()), 'value': round(v, 2)}
                    for d, v in daily_equity_curve
                ],
            }

            logger.info(
                f"  → Return: {total_return*100:.2f}% | Sharpe: {sharpe:.2f} | "
                f"MaxDD: {max_drawdown*100:.2f}% | Costs: {cost_pct_of_capital:.2f}% of capital | "
                f"Stopped early: {stopped_early}"
            )

        # Summary log
        logger.info("\n" + "=" * 90)
        logger.info(f"{'FUND TYPE COMPARISON — SUMMARY':^90}")
        logger.info("=" * 90)
        logger.info(
            f"{'Fund Type':<30} {'Return%':>10} {'Sharpe':>8} {'MaxDD%':>8} "
            f"{'WinRate%':>10} {'Cost%':>10} {'Leverage':>12}"
        )
        logger.info("-" * 90)
        for r in comparison.values():
            logger.info(
                f"{r['profile_name']:<30} {r['total_return_pct']:>9.2f}% "
                f"{r['sharpe_ratio']:>8.2f} {r['max_drawdown_pct']:>8.2f}% "
                f"{r['win_rate_pct']:>9.2f}% {r['total_cost_pct_of_capital']:>9.2f}% "
                f"{r['gross_leverage_label']:>12}"
            )
        logger.info("=" * 90)

        return comparison

    def diagnose_regime_break(self, date_range_start: str = '2023-04-04',
                              date_range_end: str = '2023-07-05') -> Dict:
        """Analyze macro conditions during a specific regime break window.

        Default: W10 (Apr–Jul 2023) — the period where win rate dropped from
        61% (W9) to 45% (W10) across 480 trades.

        Reports VIX levels, sector ETF dispersion z-scores, and a structured
        explanation of the root causes.  Data comes from already-loaded macro_data
        so no extra network calls are needed.
        """
        logger.info("\n" + "=" * 70)
        logger.info("REGIME BREAK DIAGNOSIS")
        logger.info(f"Period: {date_range_start} → {date_range_end}")
        logger.info("=" * 70)

        start = pd.Timestamp(date_range_start)
        end   = pd.Timestamp(date_range_end)

        vix_series  = self.macro_data.get('VIX', pd.Series(dtype=float))
        sector_data = self.macro_data.get('sectors', {})

        results: Dict = {}

        # ── VIX Analysis ──────────────────────────────────────────────────────
        if not vix_series.empty:
            vix_in  = vix_series[(vix_series.index >= start) & (vix_series.index <= end)]
            vix_pre = vix_series[vix_series.index < start].tail(252)
            if len(vix_in) > 0:
                results['vix_avg']            = round(float(vix_in.mean()), 2)
                results['vix_min']            = round(float(vix_in.min()),  2)
                results['vix_max']            = round(float(vix_in.max()),  2)
                results['vix_pre_period_avg'] = round(float(vix_pre.mean()), 2) if len(vix_pre) > 0 else 20.0
                logger.info(f"\nVIX during period: avg={results['vix_avg']:.1f}  "
                            f"min={results['vix_min']:.1f}  max={results['vix_max']:.1f}")
                logger.info(f"VIX prior 1yr avg: {results['vix_pre_period_avg']:.1f}  "
                            f"[long-term historical avg ~20]")
                if results['vix_avg'] < 20:
                    logger.info("  → VIX BELOW 20: appeared SAFE — this is the false signal "
                                "('Walking on Ice')")
                else:
                    logger.info("  → VIX elevated: regime stress visible")

        # ── Sector Dispersion Analysis (daily + cumulative) ────────────────────
        if sector_data:
            _sec_rets = pd.DataFrame(
                {k: v.pct_change() for k, v in sector_data.items() if len(v) > 10}
            ).dropna(how='all')

            if not _sec_rets.empty:
                # --- Daily cross-section std (reference metric, NOT used in gate) ---
                _sec_disp_daily = _sec_rets.std(axis=1).dropna()
                _d_mean = _sec_disp_daily.rolling(252, min_periods=60).mean()
                _d_std  = _sec_disp_daily.rolling(252, min_periods=60).std()
                _disp_z_daily = ((_sec_disp_daily - _d_mean) / (_d_std + 1e-10)).dropna()
                disp_in_daily = _disp_z_daily[(_disp_z_daily.index >= start) & (_disp_z_daily.index <= end)]

                # --- 63-day cumulative log-return dispersion (v8 gate metric) ---
                _sec_log = np.log(1 + _sec_rets.fillna(0))
                _sec_cum63 = _sec_log.rolling(63, min_periods=30).sum()
                _sec_cum_disp = _sec_cum63.std(axis=1).dropna()
                _c_mean = _sec_cum_disp.rolling(252, min_periods=60).mean()
                _c_std  = _sec_cum_disp.rolling(252, min_periods=60).std()
                _disp_z_cum = ((_sec_cum_disp - _c_mean) / (_c_std + 1e-10)).dropna()
                disp_in_cum = _disp_z_cum[(_disp_z_cum.index >= start) & (_disp_z_cum.index <= end)]

                if len(disp_in_daily) > 0:
                    results['sector_dispersion_avg_z']     = round(float(disp_in_daily.mean()), 3)
                    results['sector_dispersion_max_z']     = round(float(disp_in_daily.max()),  3)
                    results['days_above_1sigma']            = int((disp_in_daily > 1.0).sum())
                    results['days_above_2sigma']            = int((disp_in_daily > 2.0).sum())
                    results['total_days_in_period']         = len(disp_in_daily)

                if len(disp_in_cum) > 0:
                    results['cum_dispersion_avg_z']        = round(float(disp_in_cum.mean()), 3)
                    results['cum_dispersion_max_z']        = round(float(disp_in_cum.max()),  3)
                    results['days_cum_above_1p2sigma']     = int((disp_in_cum > 1.2).sum())
                    results['days_cum_above_2sigma']       = int((disp_in_cum > 2.0).sum())

                logger.info(f"\nDaily sector dispersion z-score (reference, NOT in gate): "
                            f"avg={results.get('sector_dispersion_avg_z', 0):.2f}σ  "
                            f"max={results.get('sector_dispersion_max_z', 0):.2f}σ")
                logger.info(f"  Days above 1σ: {results.get('days_above_1sigma', 0)} / "
                            f"{results.get('total_days_in_period', 0)}  |  "
                            f"Days above 2σ: {results.get('days_above_2sigma', 0)}")

                logger.info(f"63-day cumulative dispersion z-score (v8 gate metric): "
                            f"avg={results.get('cum_dispersion_avg_z', 0):.2f}σ  "
                            f"max={results.get('cum_dispersion_max_z', 0):.2f}σ")
                logger.info(f"  Days above 1.2σ (WoI gate): {results.get('days_cum_above_1p2sigma', 0)} / "
                            f"{results.get('total_days_in_period', 0)}  |  "
                            f"Days above 2σ (50% scale): {results.get('days_cum_above_2sigma', 0)}")
                cum_avg = results.get('cum_dispersion_avg_z', 0)
                if cum_avg > 1.2:
                    logger.info("  → Cumulative dispersion ELEVATED (>1.2σ): gate would have fired "
                                "if VIX < 20 (Walking on Ice detected)")
                else:
                    logger.info(f"  → Cumulative dispersion below 1.2σ threshold "
                                f"({cum_avg:.2f}σ): Walking on Ice NOT detected by this metric")

        # ── Root Cause Summary ─────────────────────────────────────────────────
        logger.info("\n" + "-" * 70)
        logger.info("ROOT CAUSES — Q2 2023 'WALKING ON ICE' REGIME:")
        logger.info("  A. Fed hit terminal rate 5.25-5.50% (July 2023, +525 bps in 16 months)")
        logger.info("     → Re-priced all equity present values; ZIRP-era cointegration broke")
        logger.info("  B. S&P 500 constituent correlation collapsed to ~8% (near historic low)")
        logger.info("     → Stocks moved almost independently; pair spreads diverged")
        logger.info("  C. VIX 13-15 = FALSE SAFETY SIGNAL (BIS March 2024 analysis)")
        logger.info("     → 0DTE options + structured product dealer hedging")
        logger.info("       mechanically suppressed VIX well below true risk level")
        logger.info("  D. Magnificent 7 = ~80% of S&P 500 YTD return through June 2023")
        logger.info("     → Extreme cross-sector dispersion; pairs trained on ZIRP broke")
        logger.info("  E. 'Walking on Ice' regime (Two Sigma GMM classification)")
        logger.info("     → Surface appears calm (low VIX) but structural foundation broken")
        logger.info("     → RenTech Institutional Equities Fund lost ~15% in Oct 2023")
        logger.info("       from same macro conditions — validates our model failure")
        logger.info("-" * 70)
        logger.info("FIXES APPLIED IN THIS SYSTEM (v8):")
        logger.info("  Problem 3 — Regime gate: VIX + 63-day cumulative sector dispersion z-score")
        logger.info("    cum_disp_z > 2.0 → positions scaled to 50%")
        logger.info("    VIX < 20 AND cum_disp_z > 1.2 (Walking on Ice) → scaled to 60%")
        logger.info("    VIX > 30 → scaled to 50%   |   VIX > 40 → scaled to 25%")
        logger.info("    (v8: raised from 25/35 to 30/40 to remove 2022 false positives)")
        logger.info("    (v8: daily→63d cumulative dispersion catches Mag7 slow-burn divergence)")
        logger.info("  Problem 4 — Adaptive cointegration: 6-month window test")
        logger.info("    Pairs that pass 2yr but fail 6m ADF test (p>0.15) are dropped")
        logger.info("    (v8: raised from p>0.05 to p>0.15 — ADF has ~45% power at n=90 obs)")
        logger.info("    Pairs where |p_6m - p_2yr| > 0.10 are dropped (structural break)")
        logger.info("=" * 70)

        return results

    def run_complete_system(self):
        """Run the complete system"""
        logger.info("Starting COMPLETE FIXED Russell 3000 Trading System")

        symbols = self.data_processor.load_symbols()
        self.processed_data = self.data_processor.load_or_fetch_data(symbols)
        self.macro_data = self.data_processor.load_macro_data()

        # BIAS FIX: Use only training-period data (2020-2022) for pair selection.
        # Using full 2020-2025 data here is look-ahead bias — pairs are cherry-picked
        # because they cointegrated well DURING the test period.
        train_cutoff = pd.Timestamp('2022-12-31')
        train_only_data = {}
        for sym, df in self.processed_data.items():
            try:
                if hasattr(df.index, 'tz') and df.index.tz is not None:
                    cutoff = train_cutoff.tz_localize(df.index.tz)
                else:
                    cutoff = train_cutoff
                filtered = df[df.index <= cutoff]
                if len(filtered) >= 100:
                    train_only_data[sym] = filtered
            except Exception:
                continue
        logger.info(f"UNBIASED PAIR SELECTION: using {len(train_only_data)} symbols with data up to 2022-12-31 only")
        self.selected_pairs = self.pair_selector.find_quality_pairs(train_only_data)

        logger.info("Calculating spreads for selected pairs...")
        for pair in self.selected_pairs:
            symbol1, symbol2 = pair
            if symbol1 in self.processed_data and symbol2 in self.processed_data:
                spread = self.calculate_spread(self.processed_data[symbol1], self.processed_data[symbol2])
                if not spread.empty:
                    self.spread_data[pair] = spread

        train_spreads, test_spreads = self.prepare_time_split_data()

        # v10: Build extended training spreads through 2023-06-30 so the RL agent
        # sees post-hike (2023 Q1-Q2) dynamics in addition to the ZIRP-era training data.
        # The main backtest is then restricted to start 2023-07-01 to avoid look-ahead bias.
        logger.info("v10: Extended RL training to 2023-06-30; main backtest starts 2023-07-01")
        extended_train_spreads = {}
        _ext_cutoff = pd.Timestamp('2023-06-30')
        for pair, spread in self.spread_data.items():
            try:
                if hasattr(spread.index, 'tz') and spread.index.tz is not None:
                    cutoff_tz = _ext_cutoff.tz_localize(spread.index.tz)
                else:
                    cutoff_tz = _ext_cutoff
                sliced = spread[spread.index <= cutoff_tz]
                if len(sliced) >= 100:
                    extended_train_spreads[pair] = sliced
            except Exception:
                continue
        logger.info(f"v10: Extended train set has {len(extended_train_spreads)} pairs (was {len(train_spreads)} in v9)")
        # v27: inject real pair statistics into the agent before training so
        # get_pair_stats() returns actual correlation/half_life/quality_score
        # instead of hardcoded defaults, eliminating the training/serving skew
        # on transformer features 17-19.
        self.rl_agent.pair_statistics = self.pair_selector.pair_statistics
        self.rl_agent.train_agent(extended_train_spreads, episodes=1000)

        # Build quarterly re-selection schedule
        all_test_dates = sorted(set(
            date for spread in test_spreads.values() for date in spread.index
        ))
        pair_windows = self.build_rolling_pair_schedule(all_test_dates, reselect_every=90)

        # SURVIVAL-BIAS FIX (v9): pair_windows contains spread histories going back to 2020.
        # Without date_range, all_dates includes 2020-2022 dates which trade using the FIRST
        # quarterly window (Q1 2023 pairs validated on 2021-2023 data) — backward look-ahead.
        # Restricting to 2023-01-01+ ensures every date only uses pairs selected from
        # data available AT THAT TIME, matching the walk-forward methodology.
        # Pass as plain date strings so run_comprehensive_backtest's tz-handling normalises
        # them uniformly — avoids tz_localize error when mixing tz-naive and tz-aware dates.
        _max_test_date_raw = max(
            (spread.index.max() for spread in test_spreads.values() if not spread.empty),
            default=pd.Timestamp('2026-12-31')
        )
        _max_test_str = str(_max_test_date_raw.date()) if hasattr(_max_test_date_raw, 'date') else '2026-12-31'
        logger.info(f"v10: restricting main backtest to 2023-07-01 → {_max_test_str} (after extended RL training period)")
        results = self.run_comprehensive_backtest(
            test_spreads, pair_windows=pair_windows,
            date_range=('2023-07-01', _max_test_str)
        )

        # Walk-forward validation — pass pair_windows so it uses the full
        # quarterly pair universe instead of the sparse initial selection.
        logger.info("Starting walk-forward validation...")
        wf_summary = self.run_walk_forward_validation(
            train_window_days=252, test_window_days=63, episodes_per_window=200,
            pair_windows=pair_windows
        )
        results['walk_forward'] = wf_summary

        # ── Regime Break Diagnosis ─────────────────────────────────────────────
        # Analyze W10 (Apr-Jul 2023) — the known regime break window.
        # This runs after walk-forward so the log context is clear.
        logger.info("Running regime break diagnosis for W10 (2023-04-04 → 2023-07-05)...")
        regime_diag = self.diagnose_regime_break(
            date_range_start='2023-04-04',
            date_range_end='2023-07-05'
        )
        results['regime_diagnosis'] = regime_diag

        # --- ADDED: JSON Export ---
        export_testing_results_to_json(results, self.processed_data)

        # --- ADDED: Plotting ---
        plot_results(results['daily_returns'], results)

        # ── Fund-type comparison ──────────────────────────────────────────────
        # Replay the same trade signals under 5 different fund economics so the
        # results section can show how performance varies by institution type.
        logger.info("Starting fund-type comparison analysis...")
        fund_comparison = self.run_fund_type_comparison(
            results, main_daily_dates=results.get('daily_dates', [])
        )
        results['fund_comparison'] = fund_comparison

        if fund_comparison:
            plot_fund_comparison(fund_comparison)
            export_fund_comparison_to_json(fund_comparison)

        return results
