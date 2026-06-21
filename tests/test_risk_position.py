"""Tests for the trade-gating logic: position sizing + risk validation.

These two modules gate every trade, so their clamps and rejection rules are worth
guarding explicitly.
"""
import pandas as pd
import pytest

from pairs_trading.position_sizer import FixedPrimeFundPositionSizer
from pairs_trading.risk_manager import FixedPrimeFundRiskManager

CAP = 100_000_000.0


# ── Position sizer ──────────────────────────────────────────────────────────
@pytest.fixture
def sizer():
    return FixedPrimeFundPositionSizer()


def test_position_fraction_within_clamp(sizer):
    size = sizer.calculate_optimal_position_size("A-B", 0.8, 0.7, CAP, risk_scaling_factor=1.0)
    frac = size / CAP
    assert sizer.min_position_size - 1e-9 <= frac <= sizer.max_position_size + 1e-9


def test_position_scales_linearly_with_risk_factor(sizer):
    full = sizer.calculate_optimal_position_size("A-B", 0.8, 0.7, CAP, risk_scaling_factor=1.0)
    half = sizer.calculate_optimal_position_size("A-B", 0.8, 0.7, CAP, risk_scaling_factor=0.5)
    assert half == pytest.approx(0.5 * full, rel=1e-9)


def test_stronger_signal_not_smaller(sizer):
    weak = sizer.calculate_optimal_position_size("A-B", 0.55, 0.6, CAP)
    strong = sizer.calculate_optimal_position_size("A-B", 0.95, 0.6, CAP)
    assert strong >= weak


def test_record_trade_tracks_history(sizer):
    for pnl in [0.01, -0.02, 0.03]:
        sizer.record_trade("A-B", pnl)
    assert len(sizer.trade_history) == 3
    assert sizer.pair_performance["A-B"] == [0.01, -0.02, 0.03]


# ── Risk manager ────────────────────────────────────────────────────────────
@pytest.fixture
def rm():
    return FixedPrimeFundRiskManager()


def _market(zscore=2.0, pair_quality=0.7, volatility=0.02, volume=2e6):
    return {"zscore": zscore, "pair_quality": pair_quality,
            "volatility": volatility, "volume": volume}


def test_valid_signal_passes(rm):
    ok, _ = rm.validate_signal(("A", "B"), 2, 0.8, _market(),
                              position_size=0.05 * CAP, current_portfolio_value=CAP,
                              current_date=pd.Timestamp("2023-07-03"))
    assert ok is True


def test_reject_non_directional_action(rm):
    ok, _ = rm.validate_signal(("A", "B"), 1, 0.8, _market(), 0.05 * CAP, CAP)
    assert ok is False


def test_reject_weak_signal_strength(rm):
    ok, _ = rm.validate_signal(("A", "B"), 2, 0.2, _market(), 0.05 * CAP, CAP)
    assert ok is False


def test_reject_low_zscore(rm):
    ok, _ = rm.validate_signal(("A", "B"), 2, 0.8, _market(zscore=0.5), 0.05 * CAP, CAP)
    assert ok is False


def test_reject_low_pair_quality(rm):
    ok, _ = rm.validate_signal(("A", "B"), 2, 0.8, _market(pair_quality=0.2), 0.05 * CAP, CAP)
    assert ok is False


def test_reject_oversized_position(rm):
    ok, _ = rm.validate_signal(("A", "B"), 2, 0.8, _market(), 0.20 * CAP, CAP)  # 20% > 10% cap
    assert ok is False


def test_reject_when_daily_limit_reached(rm):
    rm.daily_trade_count = rm.max_daily_trades
    ok, _ = rm.validate_signal(("A", "B"), 2, 0.8, _market(), 0.05 * CAP, CAP)
    assert ok is False


def test_should_stop_on_max_drawdown(rm):
    assert rm.should_stop_trading(0.0)[0] is False
    rm.current_drawdown = rm.max_drawdown_limit + 0.01
    assert rm.should_stop_trading(0.0)[0] is True


def test_should_stop_on_single_day_loss(rm):
    assert rm.should_stop_trading(-(rm.max_single_day_loss + 0.01))[0] is True


def test_profit_scaling_reduces_at_high_profit(rm):
    assert rm.get_profit_scaling_factor(CAP) == pytest.approx(1.0)          # no profit
    assert rm.get_profit_scaling_factor(CAP * 1.7) == pytest.approx(0.5)    # >60% profit


def test_volatility_scaling_full_without_history(rm):
    assert rm.get_volatility_scaling_factor() == 1.0
