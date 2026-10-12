"""Tests for pairs_trading.transaction_costs — institutional + profile cost models."""
import pytest

from pairs_trading.transaction_costs import (
    EnhancedPrimeFundTransactionCostModel, calculate_profile_trade_costs,
)
from pairs_trading.fund_profiles import FUND_PROFILES


@pytest.fixture
def model():
    return EnhancedPrimeFundTransactionCostModel()


def test_total_cost_positive_and_components(model):
    costs = model.calculate_total_trade_costs(
        long_position=1000, short_position=1000,
        long_price=50.0, short_price=40.0,
        long_symbol="AAA", short_symbol="BBBB", holding_days=10,
    )
    assert costs['total_cost'] > 0
    for k in ('total_entry_cost', 'total_exit_cost', 'total_borrow_cost', 'financing_cost'):
        assert k in costs and costs[k] >= 0


def test_cost_scales_with_position_size(model):
    small = model.calculate_total_trade_costs(100, 100, 50, 50, "AAA", "BBB", 5)['total_cost']
    big = model.calculate_total_trade_costs(10000, 10000, 50, 50, "AAA", "BBB", 5)['total_cost']
    assert big > small


def test_borrow_only_charged_on_short_leg(model):
    # zero short position -> no borrow cost
    costs = model.calculate_total_trade_costs(1000, 0, 50, 50, "AAA", "BBB", 30)
    assert costs['short_borrow'] == 0


def test_borrow_fee_does_not_depend_on_ticker_length(model):
    """v32: the borrow tier used to come from the ticker's LENGTH (GOOGL paid 2%/yr)."""
    fees = {sym: model.calculate_borrow_cost(1_000_000, sym, 365) for sym in ("T", "AAPL", "GOOGL", "BRK-B")}
    assert len(set(fees.values())) == 1
    assert fees["GOOGL"] == pytest.approx(1_000_000 * model.gc_borrow_rate)


def test_spread_cost_falls_with_liquidity(model):
    illiquid = model.calculate_leg_cost(10_000, 50.0, daily_volume_shares=50_000)['bid_ask']
    liquid = model.calculate_leg_cost(10_000, 50.0, daily_volume_shares=50_000_000)['bid_ask']
    assert illiquid > liquid > 0


def test_commission_uses_point_in_time_shares(model):
    adjusted = model.calculate_leg_cost(100_000, 10.0, point_in_time_price=100.0)['commission']
    real = model.calculate_leg_cost(10_000, 100.0)['commission']
    assert adjusted == pytest.approx(real)


def test_profile_impact_charged_on_entry_and_exit():
    from pairs_trading.transaction_costs import sqrt_impact_bps
    profile = FUND_PROFILES['quant_hf']
    out = calculate_profile_trade_costs(2_000_000, profile, 10, daily_volatility=0.02, adv_dollars=1e8)
    one_way = sqrt_impact_bps(1_000_000 / 1e8, 0.02, profile.market_impact_coeff,
                              profile.market_impact_cap_bps)
    assert out['market_impact'] == pytest.approx(2 * 2 * 1_000_000 * one_way / 1e4)
    assert one_way < profile.market_impact_cap_bps, "impact must not be pinned to the cap"


def test_longer_hold_costs_more_borrow(model):
    short_hold = model.calculate_total_trade_costs(0, 1000, 50, 50, "AAA", "ZZZZZ", 1)['short_borrow']
    long_hold = model.calculate_total_trade_costs(0, 1000, 50, 50, "AAA", "ZZZZZ", 100)['short_borrow']
    assert long_hold > short_hold


def test_profile_costs_positive_for_every_profile():
    for key, profile in FUND_PROFILES.items():
        out = calculate_profile_trade_costs(1_000_000, profile, holding_days=10)
        assert out['total_cost'] > 0, f"{key} produced non-positive cost"
        assert out['total_bps'] > 0


def test_profile_costs_scale_with_notional():
    profile = next(iter(FUND_PROFILES.values()))
    small = calculate_profile_trade_costs(100_000, profile, 10)['total_cost']
    big = calculate_profile_trade_costs(10_000_000, profile, 10)['total_cost']
    assert big > small
