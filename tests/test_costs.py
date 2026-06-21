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


def test_borrow_category_by_ticker_length(model):
    assert model.get_borrow_category("AB") == "easy_to_borrow"      # <=3 alpha
    assert model.get_borrow_category("ABCD") == "general_collateral"  # 4 alpha
    assert model.get_borrow_category("ABCDE") == "very_hard_to_borrow"  # >=5


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
