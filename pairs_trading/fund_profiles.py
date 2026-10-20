"""
PAIRS TRADING - COST-SCHEDULE ARCHETYPES
========================================
Five illustrative execution-cost and sizing schedules for the cost-schedule replay
(trading_system.run_fund_type_comparison): the main backtest's trades re-costed and
re-sized as an investor with that cost structure would face them.

These are ARCHETYPES, not estimates of any firm's costs: each is a stylised parameter
set spanning the range of published institutional cost levels (commission schedules,
square-root impact coefficients, general-collateral borrow fees). No real firm's terms
are implied. The replay reports the REALISED peak gross leverage of each schedule
('max_gross_leverage'); it does not lever the book up.

Each schedule encodes:
  - Transaction cost parameters (commission, bid-ask, market impact, borrow, financing)
  - Position sizing (base and maximum position, new trades per day)
  - A drawdown kill-switch
"""

from dataclasses import dataclass
from typing import Dict


@dataclass
class FundProfile:
    # Identity
    key: str
    name: str
    description: str

    # ── Transaction cost parameters (all in bps unless noted) ─────────────────
    commission_bps: float        # per leg, one-way (electronic algo execution)
    bid_ask_bps: float           # half-spread per leg, one-way
    market_impact_coeff: float   # Y in the sqrt model: I = Y * sigma_daily * sqrt(Q/ADV) (fraction)
    market_impact_cap_bps: float # hard cap on per-leg market impact
    borrow_rate_easy: float      # reference only, not charged (decimal/yr)
    borrow_rate_general: float   # annual rate charged on the short leg: general collateral (decimal)
    borrow_rate_hard: float      # reference only, not charged (decimal/yr)
    financing_spread: float      # annual prime-broker spread charged on the short notional (decimal)
    daily_volume_dollars: float  # fallback ADV ($) when a trade's own ADV is unknown

    # ── Position sizing ───────────────────────────────────────────────────────
    base_position_pct: float     # base fraction of equity per trade (before z-score scaling)
    max_position_pct: float      # hard cap per single trade / pair (fraction of equity)
    max_daily_trades: int        # max new trades entered per day
    max_drawdown_limit: float    # portfolio-level kill-switch (fraction)


# ──────────────────────────────────────────────────────────────────────────────
# Five archetypal cost schedules, from the cheapest execution to the most expensive
# ──────────────────────────────────────────────────────────────────────────────
FUND_PROFILES: Dict[str, FundProfile] = {

    # ── 1. Systematic stat-arb book ───────────────────────────────────────────
    # Electronic algorithmic execution (~0.65 cents/share, ~1 bp on a mid-cap) and
    # small orders spread across many names; the largest positions of the five.
    'quant_hf': FundProfile(
        key='quant_hf',
        name='Systematic Stat-Arb',
        description='Systematic stat-arb archetype: electronic execution, large positions',

        commission_bps=1.0,
        bid_ask_bps=2.0,
        market_impact_coeff=0.40,
        market_impact_cap_bps=12.0,
        borrow_rate_easy=0.0030,    # 30 bps/yr
        borrow_rate_general=0.0060,
        borrow_rate_hard=0.0250,
        financing_spread=0.0050,    # 50 bps/yr prime-broker spread, charged on the short notional
        daily_volume_dollars=1e9,   # assume $1B ADV (large-cap universe)

        base_position_pct=0.12,     # 12% equity per trade before z-scaling
        max_position_pct=0.30,      # cap any single position at 30% equity
        max_daily_trades=8,
        max_drawdown_limit=0.20,
    ),

    # ── 2. Multi-manager pod ──────────────────────────────────────────────────
    # Blended algorithmic execution (~1.5 bp) with costs passed through to the book.
    'multi_strat': FundProfile(
        key='multi_strat',
        name='Multi-Manager Pod',
        description='Multi-manager pod archetype: blended execution, pass-through costs',

        commission_bps=1.5,
        bid_ask_bps=4.0,
        market_impact_coeff=0.60,
        market_impact_cap_bps=20.0,
        borrow_rate_easy=0.0050,
        borrow_rate_general=0.0100,
        borrow_rate_hard=0.0500,
        financing_spread=0.0100,    # 100 bps/yr prime-broker spread, on the short notional
        daily_volume_dollars=1e9,

        base_position_pct=0.08,
        max_position_pct=0.20,
        max_daily_trades=6,
        max_drawdown_limit=0.15,
    ),

    # ── 3. Discretionary long/short book ──────────────────────────────────────
    # High-touch execution (~2.7 cents/share, ~5 bp on a $50 stock) and impatient fills.
    'fundamental_ls': FundProfile(
        key='fundamental_ls',
        name='Discretionary Long/Short',
        description='Discretionary long/short archetype: high-touch execution',

        commission_bps=5.0,         # high-touch rate (2.67 CPS on ~$50 stock ≈ 5.3 bps)
        bid_ask_bps=10.0,
        market_impact_coeff=1.20,
        market_impact_cap_bps=50.0,
        borrow_rate_easy=0.0100,    # 100 bps/yr (higher — they hold positions longer)
        borrow_rate_general=0.0200,
        borrow_rate_hard=0.0800,
        financing_spread=0.0150,    # 150 bps/yr, on the short notional
        daily_volume_dollars=5e8,   # they trade less liquid, concentrated names

        base_position_pct=0.04,
        max_position_pct=0.10,
        max_daily_trades=4,
        max_drawdown_limit=0.12,
    ),

    # ── 4. Patient institutional (pension-style) book ─────────────────────────
    # Very patient algorithmic execution in the most liquid names, no leverage.
    'institutional': FundProfile(
        key='institutional',
        name='Patient Institutional',
        description='Pension-style archetype: patient algorithmic execution, no leverage',

        # Per-execution values for a patient large-cap algorithmic trader (v32 replaced
        # annual cost-per-AUM figures that had been entered as per-trade costs):
        commission_bps=1.0,
        bid_ask_bps=1.5,
        market_impact_coeff=0.15,   # low — they execute very patiently via algorithms
        market_impact_cap_bps=4.0,
        borrow_rate_easy=0.0005,    # 5 bps/yr (they are preferred counterparties)
        borrow_rate_general=0.0010,
        borrow_rate_hard=0.0050,
        financing_spread=0.0000,    # No leverage, no financing cost
        daily_volume_dollars=2e9,   # they trade only the most liquid stocks

        base_position_pct=0.02,
        max_position_pct=0.05,
        max_daily_trades=3,
        max_drawdown_limit=0.10,
    ),

    # ── 5. Retail / small proprietary account ────────────────────────────────
    # A retail broker's tiered rate ($0.0035/share, ~0.7 bp on a $50 stock), wide
    # effective spreads, expensive borrow and margin; no leverage in this comparison.
    'retail': FundProfile(
        key='retail',
        name='Retail / Small Prop',
        description='Retail or small proprietary account archetype: expensive borrow and margin',

        commission_bps=0.7,
        bid_ask_bps=15.0,           # wider spread — smaller, less liquid names
        market_impact_coeff=2.50,
        market_impact_cap_bps=80.0,
        borrow_rate_easy=0.0300,    # 3% (retail borrow is expensive)
        borrow_rate_general=0.0600,
        borrow_rate_hard=0.1500,    # 15% hard-to-borrow penalty
        financing_spread=0.0300,    # 3%/yr retail margin spread, on the short notional
        daily_volume_dollars=1e8,   # smaller liquidity pool

        base_position_pct=0.02,
        max_position_pct=0.05,
        max_daily_trades=2,
        max_drawdown_limit=0.15,
    ),
}


def get_profile_borrow_rate(profile: FundProfile, symbol: str) -> float:
    """Annual borrow fee charged on the short leg: the profile's general-collateral rate.

    v32: the tier used to be inferred from the LENGTH of the ticker (<= 3 letters "easy",
    4 letters "general", anything else "hard"), which has no relation to borrow
    availability. Specials/hard-to-borrow names are not modelled (disclosed limitation);
    borrow_rate_easy / borrow_rate_hard are kept for reference only.
    """
    return profile.borrow_rate_general


def get_profile_summary_table() -> str:
    """Return a readable summary table of all profiles for logging."""
    lines = [
        "\n" + "=" * 100,
        f"{'COST-SCHEDULE REPLAY — ARCHETYPE PARAMETERS':^100}",
        "=" * 100,
        f"{'Profile':<25} {'Commission':>12} {'Bid-Ask':>10} {'MI Cap':>10} {'Borrow (GC)':>15} "
        f"{'Financing':>12} {'Base Pos%':>10} {'Max Pos%':>10}",
        "-" * 100,
    ]
    for profile in FUND_PROFILES.values():
        lines.append(
            f"{profile.name:<25} {profile.commission_bps:>10.2f}bp {profile.bid_ask_bps:>8.2f}bp "
            f"{profile.market_impact_cap_bps:>8.1f}bp {profile.borrow_rate_general*100:>13.2f}%/yr "
            f"{profile.financing_spread*100:>10.2f}%/yr {profile.base_position_pct*100:>8.1f}% "
            f"{profile.max_position_pct*100:>8.1f}%"
        )
    lines.append("=" * 100)
    return "\n".join(lines)
