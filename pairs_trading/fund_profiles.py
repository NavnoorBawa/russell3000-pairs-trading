"""
TRANSFORMER ENCODER FOR PAIRS TRADING - FUND PROFILES
======================================================
Defines realistic institutional fund profiles for the fund-type comparison.

Each profile encodes:
  - Transaction cost parameters (commission, bid-ask, market impact, borrow, financing)
  - Position sizing and leverage assumptions
  - Risk limits

Sources: Bloomberg 2020 Commission Report, Norges Bank GPFG 2024,
         Morgan Stanley Prime Brokerage Data (quant avg 645%, multi-strat avg 444%),
         AQR Trading Costs Research, NBIM Reports 2024.
"""

from dataclasses import dataclass
from typing import Dict


@dataclass
class FundProfile:
    # Identity
    key: str
    name: str
    description: str
    example_firms: str

    # ── Transaction cost parameters (all in bps unless noted) ─────────────────
    commission_bps: float        # per leg, one-way (electronic algo execution)
    bid_ask_bps: float           # half-spread per leg, one-way
    market_impact_coeff: float   # coefficient in sqrt model: I = coeff * sqrt(Q/V) * 10000
    market_impact_cap_bps: float # hard cap on per-leg market impact
    borrow_rate_easy: float      # annual rate, easy-to-borrow stocks (decimal)
    borrow_rate_general: float   # annual rate, general collateral (decimal)
    borrow_rate_hard: float      # annual rate, hard-to-borrow (decimal)
    financing_spread: float      # annual spread over SOFR paid on leveraged cash (decimal)
    daily_volume_dollars: float  # assumed average daily dollar volume of traded stocks

    # ── Position sizing ───────────────────────────────────────────────────────
    base_position_pct: float     # base fraction of equity per trade (before z-score scaling)
    max_position_pct: float      # hard cap per single trade / pair (fraction of equity)
    max_daily_trades: int        # max new trades entered per day
    max_drawdown_limit: float    # portfolio-level kill-switch (fraction)

    # ── Leverage narrative ────────────────────────────────────────────────────
    # Gross leverage = total long + short exposure / equity.
    # In the comparison simulation, a trade at base_position_pct × leverage_scale
    # is capped at max_position_pct.  The concurrent-position argument maps to
    # the research numbers:
    #   avg concurrent open trades ≈ max_daily_trades × avg_holding_days (~5d)
    #   implied gross leverage = avg_concurrent × base_position_pct
    gross_leverage_label: str    # human-readable e.g. "~5x"


# ──────────────────────────────────────────────────────────────────────────────
# Five profiles derived from the research documents
# ──────────────────────────────────────────────────────────────────────────────
FUND_PROFILES: Dict[str, FundProfile] = {

    # ── 1. Quantitative / Stat-Arb Hedge Fund ────────────────────────────────
    # Renaissance, Two Sigma, D.E. Shaw, PDT Partners
    # Commission: 0.65 CPS electronic (Bloomberg 2020) → ~1 bps for mid-cap
    # Leverage: Morgan Stanley PB data — quant avg 645% gross
    # Market impact: small (tiny per-order size spread across thousands of pairs)
    'quant_hf': FundProfile(
        key='quant_hf',
        name='Quantitative Hedge Fund',
        description='Systematic stat-arb (Renaissance, Two Sigma, D.E. Shaw, PDT)',
        example_firms='Renaissance Technologies, Two Sigma, D.E. Shaw, PDT Partners',

        commission_bps=1.0,
        bid_ask_bps=2.0,
        market_impact_coeff=0.40,
        market_impact_cap_bps=12.0,
        borrow_rate_easy=0.0030,    # 30 bps/yr
        borrow_rate_general=0.0060,
        borrow_rate_hard=0.0250,
        financing_spread=0.0050,    # SOFR + 50 bps (prime brokerage rate)
        daily_volume_dollars=1e9,   # assume $1B ADV (large-cap universe)

        base_position_pct=0.12,     # 12% equity per trade before z-scaling
        max_position_pct=0.30,      # cap any single position at 30% equity
        max_daily_trades=8,
        max_drawdown_limit=0.20,

        gross_leverage_label='~5-7x'
    ),

    # ── 2. Multi-Strategy Pod Shop ────────────────────────────────────────────
    # Citadel (Wellington), Millennium, Balyasny, ExodusPoint
    # Commission: algo blended 1.5 bps
    # Leverage: Morgan Stanley PB data — multi-strat avg 444%
    'multi_strat': FundProfile(
        key='multi_strat',
        name='Multi-Strategy Pod Shop',
        description='Multi-manager platform (Citadel, Millennium, Balyasny)',
        example_firms='Citadel (Wellington), Millennium Management, Balyasny, ExodusPoint',

        commission_bps=1.5,
        bid_ask_bps=4.0,
        market_impact_coeff=0.60,
        market_impact_cap_bps=20.0,
        borrow_rate_easy=0.0050,
        borrow_rate_general=0.0100,
        borrow_rate_hard=0.0500,
        financing_spread=0.0100,    # SOFR + 100 bps (higher PB spread, pass-through model)
        daily_volume_dollars=1e9,

        base_position_pct=0.08,
        max_position_pct=0.20,
        max_daily_trades=6,
        max_drawdown_limit=0.15,

        gross_leverage_label='~4x (avg 444%)'
    ),

    # ── 3. Fundamental Long/Short Hedge Fund ──────────────────────────────────
    # Tiger, Viking, Coatue, Pershing Square
    # Commission: 2.67 CPS high-touch (Bloomberg 2020) → ~5-10 bps depending on price
    # Leverage: 120-200% gross (industry standard)
    'fundamental_ls': FundProfile(
        key='fundamental_ls',
        name='Fundamental Long/Short HF',
        description='Traditional discretionary L/S (Tiger, Viking, Coatue)',
        example_firms='Tiger Global, Viking Global, Coatue Management, Point72',

        commission_bps=5.0,         # high-touch rate (2.67 CPS on ~$50 stock ≈ 5.3 bps)
        bid_ask_bps=10.0,
        market_impact_coeff=1.20,
        market_impact_cap_bps=50.0,
        borrow_rate_easy=0.0100,    # 100 bps/yr (higher — they hold positions longer)
        borrow_rate_general=0.0200,
        borrow_rate_hard=0.0800,
        financing_spread=0.0150,    # SOFR + 150 bps
        daily_volume_dollars=5e8,   # they trade less liquid, concentrated names

        base_position_pct=0.04,
        max_position_pct=0.10,
        max_daily_trades=4,
        max_drawdown_limit=0.12,

        gross_leverage_label='~1.5-2x'
    ),

    # ── 4. Buy-Side Institutional (Pension / Sovereign Wealth) ───────────────
    # Norges Bank GPFG, CalSTRS, CPPIB, GIC Singapore
    # Actual Norges Bank 2024: direct costs 0.42 bps, indirect 1.19 bps, total 1.61 bps
    # No leverage: 1x gross only
    'institutional': FundProfile(
        key='institutional',
        name='Buy-Side Institutional',
        description='Pension / sovereign wealth fund (Norges Bank, CalSTRS, CPPIB)',
        example_firms='Norges Bank GPFG ($1.8T), CalSTRS, CPPIB, GIC Singapore',

        commission_bps=0.42,        # Norges Bank actual 2024 direct cost
        bid_ask_bps=1.19,           # Norges Bank actual 2024 indirect cost
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

        gross_leverage_label='1x (no leverage)'
    ),

    # ── 5. Retail / Small Prop Trader ─────────────────────────────────────────
    # Interactive Brokers retail, small family office, boutique prop desk
    # Commission: ~$0.005/share (IB tiered) ≈ 5 bps at $100/share → higher for cheap stocks
    # No leverage beyond standard 2:1 (1x for this comparison — no portfolio margin)
    'retail': FundProfile(
        key='retail',
        name='Retail / Small Prop Trader',
        description='Retail algo or small family office (Interactive Brokers, small prop)',
        example_firms='IB retail account, small family office, boutique prop desk',

        commission_bps=7.0,         # IB retail at volume tier 1 ($0.35/100 shares ≈ 7 bps)
        bid_ask_bps=15.0,           # wider spread — smaller, less liquid names
        market_impact_coeff=2.50,
        market_impact_cap_bps=80.0,
        borrow_rate_easy=0.0300,    # 3% (retail borrow is expensive)
        borrow_rate_general=0.0600,
        borrow_rate_hard=0.1500,    # 15% hard-to-borrow penalty
        financing_spread=0.0300,    # SOFR + 3% = ~8% margin rate at retail
        daily_volume_dollars=1e8,   # smaller liquidity pool

        base_position_pct=0.02,
        max_position_pct=0.05,
        max_daily_trades=2,
        max_drawdown_limit=0.15,

        gross_leverage_label='1x (no leverage)'
    ),
}


def get_profile_borrow_rate(profile: FundProfile, symbol: str) -> float:
    """Return the annual borrow rate for a symbol based on its likely liquidity tier."""
    # Simple heuristic matching the original get_borrow_category logic
    sym = symbol.upper()
    if len(sym) <= 3 and sym.isalpha():
        return profile.borrow_rate_easy
    elif len(sym) == 4 and sym.isalpha():
        return profile.borrow_rate_general
    else:
        return profile.borrow_rate_hard


def get_profile_summary_table() -> str:
    """Return a readable summary table of all profiles for logging."""
    lines = [
        "\n" + "=" * 100,
        f"{'FUND TYPE COMPARISON — PROFILE PARAMETERS':^100}",
        "=" * 100,
        f"{'Profile':<25} {'Commission':>12} {'Bid-Ask':>10} {'MI Cap':>10} {'Borrow (easy)':>15} "
        f"{'Financing':>12} {'Base Pos%':>10} {'Max Pos%':>10} {'Leverage':>12}",
        "-" * 100,
    ]
    for profile in FUND_PROFILES.values():
        lines.append(
            f"{profile.name:<25} {profile.commission_bps:>10.2f}bp {profile.bid_ask_bps:>8.2f}bp "
            f"{profile.market_impact_cap_bps:>8.1f}bp {profile.borrow_rate_easy*100:>13.2f}%/yr "
            f"{profile.financing_spread*100:>10.2f}%/yr {profile.base_position_pct*100:>8.1f}% "
            f"{profile.max_position_pct*100:>8.1f}% {profile.gross_leverage_label:>12}"
        )
    lines.append("=" * 100)
    return "\n".join(lines)
