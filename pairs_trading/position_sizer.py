"""
TRANSFORMER ENCODER FOR PAIRS TRADING - POSITION SIZER
=======================================================
Fixed Prime Fund Position Sizer with balanced sizing.
DO NOT MODIFY ANY PARAMETERS IN THIS FILE.
"""

from pairs_trading.config import (
    pd, logging
)

logger = logging.getLogger(__name__)


class FixedPrimeFundPositionSizer:
    """ADAPTIVE: Position sizing with risk scaling"""

    def __init__(self):
        self.base_position_size = 0.04
        self.max_position_size = 0.10
        self.min_position_size = 0.03  # v18: raised from 0.02 — cost drag kills sub-3% positions

        self.lookback_trades = 50
        self.trade_history = []
        self.pair_performance = {}

        logger.info("ADAPTIVE Prime Fund Position Sizer - Risk Scaled")

    def calculate_optimal_position_size(self, pair_key: str, signal_strength: float,
                                      pair_quality: float, current_capital: float,
                                      spread_returns: pd.Series = None,
                                      risk_scaling_factor: float = 1.0) -> float:
        """ADAPTIVE: Position calculation with risk manager scaling"""
        try:
            base_size = self.base_position_size

            signal_multiplier = 0.7 + signal_strength * 0.6
            signal_multiplier = min(signal_multiplier, 2.0)

            quality_multiplier = 0.8 + pair_quality * 0.4
            quality_multiplier = min(quality_multiplier, 1.5)

            performance_multiplier = 1.0
            if len(self.trade_history) > 5:
                recent_trades = self.trade_history[-5:]
                recent_win_rate = len([t for t in recent_trades if t > 0]) / len(recent_trades)
                if recent_win_rate < 0.3:
                    performance_multiplier = 0.7
                elif recent_win_rate > 0.7:
                    performance_multiplier = 1.3

            vol_multiplier = 1.0
            if spread_returns is not None and len(spread_returns) > 10:
                volatility = spread_returns.rolling(10, min_periods=5).std().iloc[-1]
                if volatility > 0.08:
                    vol_multiplier = 0.8

            # v26: clamp to [min, max] on the pre-scaling size, THEN apply the
            # risk/regime scaling factor. Previously the min floor was applied AFTER
            # multiplying by risk_scaling_factor, so a regime cut to 0.25x could not
            # push a position below the 3% floor — the gate's deep reductions were
            # silently defeated. Now regime/vol/profit scaling genuinely bites.
            pre_scale_fraction = (base_size * signal_multiplier * quality_multiplier *
                                  performance_multiplier * vol_multiplier)
            pre_scale_fraction = max(self.min_position_size,
                                     min(self.max_position_size, pre_scale_fraction))

            final_fraction = pre_scale_fraction * risk_scaling_factor

            position_size = final_fraction * current_capital

            return position_size

        except Exception:
            return self.base_position_size * current_capital * risk_scaling_factor

    def record_trade(self, pair_key: str, pnl_percent: float):
        """Record trade result"""
        self.trade_history.append(pnl_percent)

        if pair_key not in self.pair_performance:
            self.pair_performance[pair_key] = []

        self.pair_performance[pair_key].append(pnl_percent)

        if len(self.trade_history) > self.lookback_trades:
            self.trade_history = self.trade_history[-self.lookback_trades:]
