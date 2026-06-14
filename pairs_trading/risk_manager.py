"""
TRANSFORMER ENCODER FOR PAIRS TRADING - RISK MANAGER
=====================================================
Fixed Prime Fund Risk Manager with balanced controls.
DO NOT MODIFY ANY PARAMETERS IN THIS FILE.
"""

from pairs_trading.config import (
    pd, np, logging, Dict, Tuple, List
)

logger = logging.getLogger(__name__)


class FixedPrimeFundRiskManager:
    """ADAPTIVE Risk Manager - Volatility & Profit Protection"""

    def __init__(self):
        self.max_position_size = 0.10
        self.max_total_exposure = 0.30
        self.max_daily_trades = 8
        self.max_daily_volatility = 0.30
        self.max_drawdown_limit = 0.15  # 15% max drawdown before stopping
        self.max_single_day_loss = 0.05  # 5% single-day circuit breaker
        self.daily_loss_pause_threshold = 0.03  # Pause new trades at -3% daily loss

        self.base_signal_threshold = 0.50
        self.min_zscore_threshold = 1.5
        self.min_holding_period = 1
        self.min_pair_quality = 0.55

        # State tracking
        self.daily_trade_count = 0
        self.current_exposure = 0
        self.current_drawdown = 0.0
        self.peak_portfolio_value = 100000000
        self.initial_capital = 100000000
        self.risk_alerts = []
        self.last_trade_dates = {}

        # Volatility-based scaling
        self.daily_returns_history: List[float] = []
        self.volatility_lookback = 20  # 20-day rolling vol
        self.baseline_volatility = 0.02  # 2% baseline daily vol
        self.high_vol_threshold = 1.5  # Scale down if vol > 1.5x baseline

        # Profit-based scaling
        self.profit_scale_threshold = 0.40  # Start scaling at 40% profit
        self.high_profit_threshold = 0.60  # Max scaling at 60% profit

        # Intraday loss management
        self.trading_paused = False
        self.current_daily_pnl = 0.0

        logger.info("ADAPTIVE Risk Manager - Volatility & Profit Protection")

    def validate_signal(self, pair_key: Tuple[str, str], action: int, signal_strength: float,
                       market_data: Dict, position_size: float = 0,
                       current_portfolio_value: float = 100000000,
                       current_date: pd.Timestamp = None) -> Tuple[bool, str]:
        """ADAPTIVE: Signal validation with volatility & profit protection"""
        try:
            # Check if trading is paused due to daily losses
            if self.trading_paused:
                return False, "Trading paused due to daily loss limit"

            if action not in [0, 2]:
                return False, "Only directional trades allowed"

            if signal_strength < self.base_signal_threshold:
                return False, f"Signal strength {signal_strength:.3f} below {self.base_signal_threshold}"

            zscore = market_data.get('zscore', 0)
            if abs(zscore) < self.min_zscore_threshold:
                return False, f"Z-score {abs(zscore):.2f} below {self.min_zscore_threshold}"

            pair_quality = market_data.get('pair_quality', 0.5)
            if pair_quality < self.min_pair_quality:
                return False, f"Pair quality {pair_quality:.2f} below {self.min_pair_quality}"

            pair_key_str = f"{pair_key[0]}-{pair_key[1]}"
            if pair_key_str in self.last_trade_dates and current_date:
                days_since_last = (current_date - self.last_trade_dates[pair_key_str]).days
                if days_since_last < self.min_holding_period:
                    return False, f"Must wait {self.min_holding_period} days between trades"

            position_pct = position_size / current_portfolio_value
            if position_pct > self.max_position_size:
                return False, f"Position {position_pct:.2%} exceeds {self.max_position_size:.2%}"

            if self.daily_trade_count >= self.max_daily_trades:
                return False, f"Daily limit of {self.max_daily_trades} trades reached"

            volatility = market_data.get('volatility', 0.02)
            if volatility > self.max_daily_volatility:
                return False, f"Volatility {volatility:.2%} exceeds {self.max_daily_volatility:.2%}"

            if self.current_exposure + position_pct > self.max_total_exposure:
                return False, f"Would exceed {self.max_total_exposure:.1%} exposure limit"

            volume = market_data.get('volume', 1e6)
            if volume < 1e6:
                return False, f"Volume ${volume:,.0f} below $1M minimum"

            # v26: do NOT stamp last_trade_dates here. validate_signal is called for
            # every candidate during the ranking phase; stamping on validation marked
            # pairs as "traded" even when they were ranked out and never executed.
            # The caller now stamps last_trade_dates only on actual execution.
            return True, f"PASS: All adaptive requirements met"

        except Exception as e:
            return False, f"Validation error: {str(e)}"

    def get_volatility_scaling_factor(self) -> float:
        """Calculate position scaling based on recent volatility"""
        if len(self.daily_returns_history) < 10:
            return 1.0  # Not enough data, use full size

        recent_returns = self.daily_returns_history[-self.volatility_lookback:]
        current_vol = np.std(recent_returns) * np.sqrt(252)  # Annualized

        if current_vol <= self.baseline_volatility:
            return 1.0  # Normal volatility, full size

        vol_ratio = current_vol / self.baseline_volatility

        if vol_ratio > self.high_vol_threshold:
            # High volatility: scale down by 50%
            scaling = 0.5
            logger.info(f"HIGH VOLATILITY: {current_vol:.2%} annualized, scaling positions to {scaling:.0%}")
            return scaling
        else:
            # Moderate increase: linear scaling
            scaling = 1.0 - (vol_ratio - 1.0) * 0.5
            return max(0.5, scaling)

    def get_profit_scaling_factor(self, current_portfolio_value: float) -> float:
        """Calculate position scaling based on current profit level"""
        current_return = (current_portfolio_value - self.initial_capital) / self.initial_capital

        if current_return < self.profit_scale_threshold:
            return 1.0  # Normal profits, full size

        if current_return >= self.high_profit_threshold:
            # High profits: scale down by 50%
            scaling = 0.5
            logger.info(f"HIGH PROFIT PROTECTION: {current_return:.1%} return, scaling positions to {scaling:.0%}")
            return scaling
        else:
            # Linear scaling between thresholds
            scale_range = self.high_profit_threshold - self.profit_scale_threshold
            profit_excess = current_return - self.profit_scale_threshold
            reduction = (profit_excess / scale_range) * 0.5
            scaling = 1.0 - reduction
            return max(0.5, scaling)

    def should_pause_new_trades(self) -> Tuple[bool, str]:
        """Check if we should pause new trades due to intraday losses"""
        if self.current_daily_pnl < -self.daily_loss_pause_threshold:
            return True, f"Daily loss {self.current_daily_pnl:.2%} exceeds -{self.daily_loss_pause_threshold:.0%} pause threshold"
        return False, ""

    def get_combined_scaling_factor(self, current_portfolio_value: float) -> float:
        """Get combined scaling from all risk factors"""
        vol_scale = self.get_volatility_scaling_factor()
        profit_scale = self.get_profit_scaling_factor(current_portfolio_value)

        # Take the minimum (most conservative)
        combined = min(vol_scale, profit_scale)

        if combined < 1.0:
            logger.info(f"POSITION SCALING: vol={vol_scale:.2f}, profit={profit_scale:.2f}, combined={combined:.2f}")

        return combined

    def update_daily_stats(self, trade_count: int, exposure: float, daily_pnl: float,
                           current_portfolio_value: float):
        """Update daily statistics and track drawdown"""
        self.daily_trade_count = trade_count
        self.current_exposure = exposure
        self.current_daily_pnl = daily_pnl

        # Track returns for volatility calculation
        self.daily_returns_history.append(daily_pnl)
        if len(self.daily_returns_history) > 100:  # Keep last 100 days
            self.daily_returns_history = self.daily_returns_history[-100:]

        # Track peak and drawdown
        if current_portfolio_value > self.peak_portfolio_value:
            self.peak_portfolio_value = current_portfolio_value
            self.current_drawdown = 0.0
        else:
            self.current_drawdown = (self.peak_portfolio_value - current_portfolio_value) / self.peak_portfolio_value

        # Check if we should pause trading
        pause_needed, pause_reason = self.should_pause_new_trades()
        if pause_needed and not self.trading_paused:
            self.trading_paused = True
            logger.warning(f"TRADING PAUSED: {pause_reason}")
        elif not pause_needed and self.trading_paused:
            self.trading_paused = False
            logger.info("TRADING RESUMED: Daily loss recovered")

    def reset_daily_counters(self):
        """Reset counters at start of new day"""
        self.daily_trade_count = 0
        self.current_daily_pnl = 0.0
        # Don't reset trading_paused - let it recover naturally when loss improves

    def should_stop_trading(self, daily_pnl: float = 0.0) -> Tuple[bool, str]:
        """Logical institutional risk controls"""
        # 1. Max Drawdown - Primary kill switch
        if self.current_drawdown >= self.max_drawdown_limit:
            return True, f"Max drawdown exceeded: {self.current_drawdown:.2%} >= {self.max_drawdown_limit:.2%}"

        # 2. Single-day circuit breaker - Extreme loss protection
        if daily_pnl < -self.max_single_day_loss:
            return True, f"Single-day loss circuit breaker: {daily_pnl:.2%} < -{self.max_single_day_loss:.2%}"

        # 3. Exposure limit - Position sizing safety
        if self.current_exposure > self.max_total_exposure:
            return True, f"Exposure limit exceeded: {self.current_exposure:.2%} > {self.max_total_exposure:.2%}"

        return False, "All risk checks passed"
