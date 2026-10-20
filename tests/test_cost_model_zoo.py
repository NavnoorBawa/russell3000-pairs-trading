"""The study's cost model against published execution-cost estimates (cost_references.py).

For a liquid large cap (dollar ADV above $500M, daily volatility 1-3%) the model's cost of
one execution — commission + half-spread + square-root impact — must lie inside the band
spanned by the published references at every participation level the study reaches
(0.1%-5% of ADV): above the patient one-day VWAP of Almgren et al. (2005) and below the
liquidity-demanding square-root law with Y = 1. At the study's typical participation
(~1% of ADV) it must sit within a factor of 1.5 of the NYSE closing-auction estimate of
Goyal, Jegadeesh & Wu (2025), the venue where its next-day-close fills execute.
"""
import pytest

from pairs_trading.cost_references import reference_costs_bps
from pairs_trading.transaction_costs import EnhancedPrimeFundTransactionCostModel

PRICE = 100.0
ADV_SHARES = 10e6                    # $1B of daily volume at $100


def model_bps(participation: float, daily_volatility: float) -> float:
    shares = participation * ADV_SHARES
    c = EnhancedPrimeFundTransactionCostModel().calculate_leg_cost(
        shares, PRICE, daily_volume_shares=ADV_SHARES, daily_volatility=daily_volatility)
    return c['total'] / (shares * PRICE) * 1e4


@pytest.mark.parametrize('participation', [0.001, 0.0025, 0.005, 0.01, 0.02, 0.05])
@pytest.mark.parametrize('vol', [0.01, 0.016, 0.03])
def test_model_lies_inside_the_published_band(participation, vol):
    ref = reference_costs_bps(participation, vol)
    ours = model_bps(participation, vol)
    assert ref['almgren_2005'] < ours < ref['sqrt_law_y1'] + 1.0, (ours, ref)   # +1 bp: spread + fee


def test_model_matches_closing_auction_impact_at_typical_participation():
    ours = model_bps(0.01, 0.016)
    nyse = reference_costs_bps(0.01, 0.016)['gjw_2025_nyse']
    assert nyse / 1.5 < ours < nyse * 1.5, (ours, nyse)
    assert ours < reference_costs_bps(0.01, 0.016)['gjw_2025_nasdaq']


def test_reference_formulas_reproduce_their_papers():
    r = reference_costs_bps(0.01, 0.016)
    assert r['gjw_2025_nyse'] == pytest.approx(4.5) and r['gjw_2025_nasdaq'] == pytest.approx(10.2)
    assert r['almgren_2005'] == pytest.approx(0.142 * 0.016 * 0.01 ** 0.6 * 1e4)
    assert r['sqrt_law_y1'] == pytest.approx(16.0) and r['avellaneda_lee'] == 5.0
