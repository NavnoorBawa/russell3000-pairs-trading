"""
TRANSFORMER ENCODER FOR PAIRS TRADING - TRANSACTION COSTS
==========================================================
Enhanced Prime Fund Transaction Cost Model with institutional rates.
Also contains profile-aware cost functions for the fund-type comparison.
DO NOT MODIFY ANY PARAMETERS IN THIS FILE.
"""

from pairs_trading.config import (
    np, logging, Dict
)

logger = logging.getLogger(__name__)


class EnhancedPrimeFundTransactionCostModel:
    """ENHANCED: Ultra-low institutional rates for profitability"""

    def __init__(self):
        self.base_commission_rate = 0.15
        self.min_commission_per_trade = 0.50
        self.typical_bid_ask_spread = 0.8
        self.market_impact_coefficient = 0.3

        self.volume_tiers = {
            'tier_1': {'min_volume': 0, 'max_volume': 10e6, 'discount': 0.80},
            'tier_2': {'min_volume': 10e6, 'max_volume': 100e6, 'discount': 0.60},
            'tier_3': {'min_volume': 100e6, 'max_volume': 1e9, 'discount': 0.40},
            'tier_4': {'min_volume': 1e9, 'max_volume': float('inf'), 'discount': 0.20}
        }

        self.stock_borrow_rates = {
            'easy_to_borrow': 0.0005,
            'general_collateral': 0.0010,
            'hard_to_borrow': 0.0050,
            'very_hard_to_borrow': 0.0200
        }
        self.pb_financing_spread = 0.005

        self.sofr_rate = 0.05
        self.margin_rate = self.sofr_rate + self.pb_financing_spread

        logger.info("Prime Fund Transaction Cost Model - Professional Grade")

    def get_volume_discount(self, monthly_volume: float) -> float:
        for tier_name, tier_info in self.volume_tiers.items():
            if tier_info['min_volume'] <= monthly_volume < tier_info['max_volume']:
                return tier_info['discount']
        return 1.0

    def calculate_commission_costs(self, position_size: float, price: float,
                                 monthly_volume: float = 50e6) -> float:
        trade_value = position_size * price
        volume_discount = self.get_volume_discount(monthly_volume)
        effective_rate = self.base_commission_rate * volume_discount
        commission = trade_value * (effective_rate / 10000)
        return max(commission, self.min_commission_per_trade)

    def calculate_market_impact_cost(self, position_size: float, price: float,
                                   daily_volume: float) -> float:
        trade_value = position_size * price

        if daily_volume > 0:
            participation_rate = trade_value / (daily_volume * price)
        else:
            participation_rate = 0.0005

        market_impact_bps = self.market_impact_coefficient * np.sqrt(participation_rate) * 10000
        market_impact_bps = min(market_impact_bps, 2)

        return trade_value * (market_impact_bps / 10000)

    def calculate_bid_ask_cost(self, position_size: float, price: float) -> float:
        trade_value = position_size * price
        return trade_value * (self.typical_bid_ask_spread / 10000)

    def get_borrow_category(self, symbol: str) -> str:
        if len(symbol) <= 3 and symbol.isalpha():
            return 'easy_to_borrow'
        elif len(symbol) == 4 and symbol.isalpha():
            return 'general_collateral'
        elif len(symbol) >= 5:
            return 'very_hard_to_borrow'
        else:
            return 'hard_to_borrow'

    def calculate_total_trade_costs(self, long_position: float, short_position: float,
                                  long_price: float, short_price: float,
                                  long_symbol: str, short_symbol: str,
                                  holding_days: int = 1, monthly_volume: float = 50e6) -> Dict[str, float]:
        costs = {}

        if long_position > 0:
            costs['long_commission'] = self.calculate_commission_costs(long_position, long_price, monthly_volume)
            costs['long_market_impact'] = self.calculate_market_impact_cost(long_position, long_price, 5e6)
            costs['long_bid_ask'] = self.calculate_bid_ask_cost(long_position, long_price)
        else:
            costs['long_commission'] = costs['long_market_impact'] = costs['long_bid_ask'] = 0

        if short_position > 0:
            costs['short_commission'] = self.calculate_commission_costs(short_position, short_price, monthly_volume)
            costs['short_market_impact'] = self.calculate_market_impact_cost(short_position, short_price, 5e6)
            costs['short_bid_ask'] = self.calculate_bid_ask_cost(short_position, short_price)

            short_value = short_position * short_price
            borrow_category = self.get_borrow_category(short_symbol)
            borrow_rate = self.stock_borrow_rates[borrow_category]
            costs['short_borrow'] = short_value * borrow_rate * (holding_days / 365)
        else:
            costs['short_commission'] = costs['short_market_impact'] = 0
            costs['short_bid_ask'] = costs['short_borrow'] = 0

        costs['exit_commission'] = costs['long_commission'] + costs['short_commission']
        costs['exit_market_impact'] = costs['long_market_impact'] + costs['short_market_impact']
        costs['exit_bid_ask'] = costs['long_bid_ask'] + costs['short_bid_ask']

        margin_used = (long_position * long_price + short_position * short_price) * 0.10
        costs['financing_cost'] = margin_used * self.margin_rate * (holding_days / 365)

        costs['total_entry_cost'] = (costs['long_commission'] + costs['short_commission'] +
                                   costs['long_market_impact'] + costs['short_market_impact'] +
                                   costs['long_bid_ask'] + costs['short_bid_ask'])

        costs['total_exit_cost'] = costs['exit_commission'] + costs['exit_market_impact'] + costs['exit_bid_ask']
        costs['total_borrow_cost'] = costs['short_borrow']

        costs['total_cost'] = (costs['total_entry_cost'] + costs['total_exit_cost'] +
                             costs['total_borrow_cost'] + costs['financing_cost'])

        return costs


# ──────────────────────────────────────────────────────────────────────────────
# Profile-aware cost calculator  (used by fund-type comparison)
# ──────────────────────────────────────────────────────────────────────────────

def calculate_profile_trade_costs(
    position_value: float,       # total gross notional (long leg + short leg combined)
    profile,                     # FundProfile instance
    holding_days: int,
    sofr: float = 0.050,
    long_symbol: str = 'AAPL',
    short_symbol: str = 'MSFT',
) -> Dict[str, float]:
    """
    Compute realistic round-trip transaction costs for a pairs trade under
    a given FundProfile.

    Model:
      ─ Commission   : commission_bps per leg, both entry and exit  → 4 leg-trades total
      ─ Bid-ask      : bid_ask_bps per leg, both entry and exit     → 4 leg-trades total
      ─ Market impact: sqrt(participation) model, capped at profile cap, entry only (temporary)
      ─ Stock borrow : borrow_rate × short_value × holding_days/365
      ─ Financing    : leveraged portion × (sofr + financing_spread) × days/365
                       For a market-neutral pair, at 1x leverage the short proceeds fund
                       the long — net financing ≈ 0.  Extra borrowing kicks in only when
                       the portfolio gross leverage exceeds 1x.

    Returns a dict with cost breakdown (all in dollar amounts) plus 'total_cost'.
    """
    from pairs_trading.fund_profiles import get_profile_borrow_rate

    half = position_value / 2.0          # per-leg notional
    long_value  = half
    short_value = half

    # ── Commission (4 leg-trades: entry long, entry short, exit long, exit short) ──
    commission = 4 * half * (profile.commission_bps / 10_000)

    # ── Bid-ask (same 4 leg-trades) ──
    bid_ask = 4 * half * (profile.bid_ask_bps / 10_000)

    # ── Market impact (entry only — temporary, reverses post-trade) ──
    # Participation rate = trade_value / avg_daily_dollar_volume
    participation_long  = long_value  / max(profile.daily_volume_dollars, 1.0)
    participation_short = short_value / max(profile.daily_volume_dollars, 1.0)

    impact_long_bps  = profile.market_impact_coeff * np.sqrt(participation_long)  * 10_000
    impact_short_bps = profile.market_impact_coeff * np.sqrt(participation_short) * 10_000
    impact_long_bps  = min(impact_long_bps,  profile.market_impact_cap_bps)
    impact_short_bps = min(impact_short_bps, profile.market_impact_cap_bps)

    market_impact = long_value  * (impact_long_bps  / 10_000) + \
                    short_value * (impact_short_bps / 10_000)

    # ── Stock borrow (short leg) ──
    borrow_rate = get_profile_borrow_rate(profile, short_symbol)
    borrow_cost = short_value * borrow_rate * (holding_days / 365.0)

    # ── Financing on leveraged cash ──
    # For a perfectly market-neutral book at 1x gross leverage, short proceeds
    # fully fund the long — zero net cash borrowing.  At leverage > 1x, the fund
    # borrows extra cash proportional to (1 − 1/leverage).
    # We approximate: leverage ≈ implied by position as share of avg concurrent book.
    # Here we use a simpler formula: financing = position × max(0, 1 − 1/leverage_factor)
    # where leverage_factor is derived from the profile's base_position_pct and daily trades.
    #   implied_leverage = base_pos_pct × max_daily_trades × avg_holding(5d)
    implied_leverage = profile.base_position_pct * profile.max_daily_trades * 5.0
    implied_leverage = max(implied_leverage, 1.0)     # never below 1x
    leverage_factor = max(0.0, 1.0 - 1.0 / implied_leverage)

    financing_rate = sofr + profile.financing_spread
    financing_cost = position_value * leverage_factor * financing_rate * (holding_days / 365.0)

    total = commission + bid_ask + market_impact + borrow_cost + financing_cost

    return {
        'commission':      commission,
        'bid_ask':         bid_ask,
        'market_impact':   market_impact,
        'borrow':          borrow_cost,
        'financing':       financing_cost,
        'total_cost':      total,
        # bps of notional for diagnostics
        'total_bps':       total / max(position_value, 1.0) * 10_000,
    }
