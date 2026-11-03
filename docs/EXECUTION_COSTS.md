# Execution and cost model

How the study prices a trade, why the parameters have the values they have, and how far the
conclusions depend on them. Code: `pairs_trading/transaction_costs.py`; published reference
curves: `pairs_trading/cost_references.py`; band test: `tests/test_cost_model_zoo.py`;
scenario re-runs: `scripts/cost_sensitivity.py`.

## What a fill is

A signal is computed on the close of day *t*; both legs are filled at the close of *t + 1*.
In practice that is a market-on-close (MOC) order in each stock's closing auction. It is the
natural execution for a pair: both legs print in the same auction, so there is no legging
risk, and the fill price is the official close the backtest uses. Share counts are fixed
from the signal-day close; the next close is only the fill price. (A next-open variant,
`PAIRS_FILL=open`, is a declared sensitivity, not the design.)

## Components of one execution of one leg

| Component | Formula | Parameter | Source |
|---|---|---|---|
| Commission | shares x 0.2 cents, minimum $0.50 per order | 0.2 cents/share | electronic agency execution is quoted at 0.1-0.5 cents/share |
| Half-spread | half of the stock's typical quoted spread, by its own 20-day dollar ADV | 1.5 / 4 / 10 / 30 / 80 bp full spread for ADV >= $500M / $100M / $20M / $5M / below | Frazzini, Israel & Moskowitz (2018); one tick for mega caps |
| Market impact | Y x sigma_daily x sqrt(shares / ADV shares), capped at 50 bp | Y = 0.3 | Goyal, Jegadeesh & Wu (2026, JFQA 61(6), Table 3 Model A), closing-auction impact for large stocks of 4.5 bp (NYSE) and 10.2 bp (Nasdaq) at an order imbalance of 1% of ADV; at 1.6% daily volatility these correspond to Y of about 0.28 and 0.64 (this project's conversion, not a figure of the paper). Their X is the auction's net order imbalance, not one trader's order, so the comparison is approximate |

Holding costs, charged at the exit fill over the calendar days held:

| Component | v32 profile | v33 profile | Source |
|---|---|---|---|
| Stock borrow (short leg) | 0.25%/yr general collateral | 0.38%/yr | D'Avolio (2002): GC loans ~17 bp, value-weighted ~25 bp; Muravyev, Pearson & Pollet (2025; Table 1 of the 2023 working paper, CRSP stocks matched to Markit, 2006-2020): median buy-side indicative fee 0.38%, 90th percentile 3% |
| Prime-broker carry (short half of gross) | 0.50%/yr | none | v32 charged the short-rebate haircut twice (it IS the borrow fee for GC names); the book never runs leverage |

Not modelled, disclosed: SEC Section 31 and FINRA TAF fees (below 0.3 bp on sells), auction
fees ($0.0009-$0.0027 per share), hard-to-borrow specials (stressed instead, below), and the
SEC Rule 201 short-sale restriction.

## Against published estimates

Cost of one execution in bp of traded value, for a liquid large cap ($1B daily volume,
$100 price, 1.6% daily volatility), from `tests/test_cost_model_zoo.py`:

| Participation (% of ADV) | This study | Almgren et al. 2005 (VWAP, temporary) | GJW 2026 auction, NYSE | GJW 2026 auction, Nasdaq | Square-root law, Y = 1 | Avellaneda-Lee 2010 |
|---:|---:|---:|---:|---:|---:|---:|
| 0.10% | 2.5 | 0.4 | 1.4 | 3.2 | 5.1 | 5.0 |
| 0.25% | 3.4 | 0.6 | 2.2 | 5.1 | 8.0 | 5.0 |
| 0.50% | 4.3 | 0.9 | 3.2 | 7.2 | 11.3 | 5.0 |
| 1.00% | 5.8 | 1.4 | 4.5 | 10.2 | 16.0 | 5.0 |
| 2.00% | 7.7 | 2.2 | 6.4 | 14.4 | 22.6 | 5.0 |
| 5.00% | 11.7 | 3.8 | 10.1 | 22.8 | 35.8 | 5.0 |

The model sits above a patient one-day VWAP (Almgren et al.'s temporary-impact fit; their
0.314 coefficient is *permanent* impact and is not a trading cost), just above the NYSE
closing-auction estimate, below the Nasdaq one, and well below a liquidity-demanding
square-root law with Y = 1. The test fails if a change moves it outside that band. The
published v33 run's larger leg averages about 1.6% of ADV (`avg_max_leg_adv_participation_pct`
in every export), where the model charges about 6.5-7 bp per execution, a little above the 5 bp
per trade Avellaneda & Lee (2010) assumed for US statistical arbitrage.

## How much the conclusions depend on it

Not much, and that is measured rather than asserted (the numbers are the published v33
development run's; the page's Section 5 has each one as a checked value):

- **Gross of all costs there is no significant edge either.** Equal-weighted, the 213 trades
  earned -7.9 bp each before costs (t = -0.25) against 16.1 bp of cost; weighted by size,
  +13.5 bp of notional against 16.9 bp. With every cost set to zero the main backtest's Sharpe
  ratio is +0.29, and net P&L breaks even at 0.80 times the modelled costs. Costs decide the
  sign of a small number, not whether there is an edge.
- **Scenario re-runs** (`scripts/cost_sensitivity.py`, declared in advance): impact Y = 0.6
  and 1.0; every short paying 1% and 3% a year; books of $10M, $1B and $5B. Each scenario
  re-runs the whole backtest, because costs enter the equity path that sizes every later
  position and the 30% exposure cap decides which signals are filled, so the trades differ
  (213 to 273); a second, fixed-trade view re-prices the headline run's own trades. Every
  scenario with higher costs or a larger book makes the result worse. The $10M book, whose
  impact is smaller, does better than the headline (Sharpe -0.004 against -0.06 on its own
  re-run; +0.10, a +0.49% return, on the headline's re-priced trades), and is still not
  distinguishable from zero. Results: `results/<run>/cost_sensitivity.json`.
- **The cost-multiplier curve** (`results/<run>/anatomy.json`): net Sharpe with every cost
  scaled by k = 0, 0.5, 1, 1.5, 2, and the break-even k.

## What free data cannot provide

| Not available free | What the study does instead |
|---|---|
| Per-stock closing-auction imbalances and volumes (exchange feeds, TAQ) | the GJW (2026) published size/venue estimates |
| Historical per-stock borrow fees (Markit, S3) | one buy-side fee plus 1% / 3% stress scenarios |
| Measured effective spreads per stock and day (TAQ) | dollar-ADV spread buckets checked against published levels; daily-bar spread estimators (Corwin-Schultz, Abdi-Ranaldo, EDGE) are not used: for liquid large caps, whose true spreads are a few basis points, their estimates are dominated by noise (no test of them is committed here) |
