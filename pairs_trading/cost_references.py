"""
PAIRS TRADING - PUBLISHED EXECUTION-COST REFERENCES
===================================================
Published estimates of the cost of one execution, in bp of traded value, as functions of
participation p (shares traded / average daily volume) and daily volatility sigma. They
are reference points for the study's own cost model (transaction_costs.py), not inputs to
it: tests/test_cost_model_zoo.py checks that the model stays inside the band they span,
and docs/EXECUTION_COSTS.md tabulates them side by side.

  almgren_2005      temporary impact of a one-day VWAP, eta * sigma * p^beta with eta = 0.142,
                    beta = 0.6 (Almgren, Thum, Hauptmann & Li 2005, "Direct estimation of
                    equity market impact", Risk; the same defaults as QuantConnect LEAN's
                    MarketImpactSlippageModel). Their permanent-impact coefficient, 0.314, is
                    NOT a trading cost and is not used here.
  gjw_2025          closing-auction price impact for large caps, lambda * sqrt(p) with
                    lambda = 0.45% (NYSE) or 1.02% (Nasdaq), i.e. 4.5 / 10.2 bp at 1% of ADV
                    (Goyal, Jegadeesh & Wu 2025, JFQA, Table 3 Model A). The study's fills are
                    next-day closes, i.e. market-on-close orders in this auction.
  sqrt_law_y1       the square-root law with Y = 1, Y * sigma * sqrt(p) (Toth et al. 2011,
                    Phys. Rev. X: "Y of order unity") — a liquidity-demanding upper reference.
  avellaneda_lee    a flat 5 bp per execution (10 bp round trip), the assumption of Avellaneda
                    & Lee (2010) for US statistical arbitrage.
"""

import numpy as np

ALMGREN_ETA, ALMGREN_BETA = 0.142, 0.6
GJW_LAMBDA = {'NYSE': 0.0045, 'Nasdaq': 0.0102}
AVELLANEDA_LEE_BPS = 5.0


def almgren_2005_bps(participation: float, daily_volatility: float) -> float:
    return float(ALMGREN_ETA * daily_volatility * max(participation, 0.0) ** ALMGREN_BETA * 1e4)


def gjw_2025_bps(participation: float, venue: str = 'NYSE') -> float:
    return float(GJW_LAMBDA[venue] * np.sqrt(max(participation, 0.0)) * 1e4)


def sqrt_law_y1_bps(participation: float, daily_volatility: float) -> float:
    return float(daily_volatility * np.sqrt(max(participation, 0.0)) * 1e4)


def reference_costs_bps(participation: float, daily_volatility: float) -> dict:
    """Every reference at one (participation, volatility) point, bp per execution."""
    return {
        'almgren_2005': almgren_2005_bps(participation, daily_volatility),
        'gjw_2025_nyse': gjw_2025_bps(participation, 'NYSE'),
        'gjw_2025_nasdaq': gjw_2025_bps(participation, 'Nasdaq'),
        'sqrt_law_y1': sqrt_law_y1_bps(participation, daily_volatility),
        'avellaneda_lee': AVELLANEDA_LEE_BPS,
    }
