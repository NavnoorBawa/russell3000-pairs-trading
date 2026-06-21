"""Tests for the pure analytics helpers in pairs_trading.json_export."""
import numpy as np
import pytest

from pairs_trading.json_export import (
    calculate_profit_factor, calculate_max_drawdown_from_returns,
    calculate_equity_curve, calculate_action_statistics,
)


# ── profit factor ───────────────────────────────────────────────────────────
def test_profit_factor_known_value():
    # gains sum 0.3, losses sum 0.1 -> PF 3.0
    pf = calculate_profit_factor(np.array([0.2, 0.1, -0.05, -0.05]))
    assert pf == pytest.approx(3.0, rel=1e-9)


def test_profit_factor_no_losses_capped():
    assert calculate_profit_factor(np.array([0.1, 0.2])) == 999.0   # finite, JSON-safe


def test_profit_factor_no_wins_zero():
    assert calculate_profit_factor(np.array([-0.1, -0.2])) == 0.0


# ── max drawdown ────────────────────────────────────────────────────────────
def test_max_drawdown_known_value():
    # cum = [1.0, 0.7] -> DD 0.30 (returned as a positive magnitude)
    assert calculate_max_drawdown_from_returns(np.array([0.0, -0.30])) == pytest.approx(0.30, abs=1e-9)


def test_max_drawdown_zero_when_only_gains():
    assert calculate_max_drawdown_from_returns(np.array([0.01, 0.02])) == pytest.approx(0.0, abs=1e-12)


def test_max_drawdown_empty_is_zero():
    assert calculate_max_drawdown_from_returns(np.array([])) == 0.0


# ── equity curve ────────────────────────────────────────────────────────────
def test_equity_curve_shapes_and_compounding():
    out = calculate_equity_curve([0.1, -0.05, 0.02], 100.0)
    assert len(out['values']) == 3
    assert len(out['dates']) == 3
    assert out['values'][0] == pytest.approx(110.0)             # 100 * 1.1
    assert out['values'][-1] == pytest.approx(100 * 1.1 * 0.95 * 1.02)
    assert all(d >= 0 for d in out['drawdowns'])


def test_equity_curve_uses_supplied_dates():
    out = calculate_equity_curve([0.01, 0.01], 100.0, daily_dates=["2023-07-03", "2023-07-05"])
    assert out['dates'] == ["2023-07-03", "2023-07-05"]


# ── action statistics ───────────────────────────────────────────────────────
def test_action_statistics_split_and_winrate():
    trades = [
        {'action': 'LONG', 'net_pnl_pct': 0.02},
        {'action': 'LONG', 'net_pnl_pct': -0.01},
        {'action': 'SHORT', 'net_pnl_pct': 0.03},
    ]
    out = calculate_action_statistics(trades)
    assert out['LONG']['count'] == 2
    assert out['LONG']['win_rate_pct'] == 50.0
    assert out['SHORT']['count'] == 1
    assert out['SHORT']['win_rate_pct'] == 100.0


def test_action_statistics_empty_trades():
    out = calculate_action_statistics([])
    assert out['LONG']['count'] == 0 and out['SHORT']['count'] == 0
