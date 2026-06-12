# Transformer Encoder — Pairs Trading System
*Feb 2026 · v1.0 (In Progress)*

---

## TL;DR

Built a full pairs trading system on Russell 3000 using a 4-layer Transformer Encoder for supervised trade signal classification. Discovered and eliminated three compounding biases that inflated returns from **617% → 3.97%**. Current unbiased result: **+3.97% total return, 0.91 Sharpe, -19.3% max drawdown** over 2023–2025. Strategy has no edge in current form — documented why, and what fixes it.

---

## System Architecture

| Component | Implementation |
|---|---|
| Universe | Russell 3000 (~3,556 symbols) |
| Pair Selection | Engle-Granger cointegration + Hurst exponent + half-life filter (4–120 days) |
| Signal Model | 4-layer Transformer Encoder (8-head attention, d_model=128) — supervised binary classification |
| Entry Signal | Z-score \|z\| > 1.8, signal strength > 0.50, pair quality > 0.55 |
| Exit Signal | Z-score \|z\| < 0.5 |
| Position Sizing | Kelly-inspired: base 4%, max 10%, scaled by volatility + profit protection |
| Risk Manager | Drawdown kill switch (15%), single-day circuit breaker (5%), intraday pause (-3%) |
| Costs | Bid-ask spread + commission + market impact (total cost impact: 60% of capital on 5,600 trades) |

---

## Data

- **Source:** Yahoo Finance via yfinance
- **Training period:** 2020-01-01 → 2022-12-31 (pair selection + model training)
- **Test period:** 2023-01-01 → 2025-11-17 (751 trading days, fully out-of-sample)
- **Pairs tested:** 45,150 unique combinations from 301 quality-filtered symbols

---

## Honest Backtest Results (Unbiased)

> All three biases eliminated before this run.

| Metric | Value |
|---|---|
| Total Return (2023–2025) | +3.97% |
| Annualized Return | ~1.6% |
| Sharpe Ratio | 0.91 |
| Max Drawdown | -19.29% |
| Total Trades | 416 |
| Win Rate | 57.69% |
| Profit Factor | 1.01 |

**Interpretation:** Profit factor of 1.01 means the strategy is essentially break-even after transaction costs. No real edge in current form on out-of-sample data.

---

## Bias Discovery Log

This is the most important part of this project.

### Bias 1 — Risk Manager Bug (Asymmetric Counter)
**Symptom:** Both 2023–2024 and 2023–2025 backtests produced identical results. Sharpe 7.83.
**Root cause:** Consecutive losing days counter incremented at daily PnL < -0.8% but only reset at PnL > +0.3%. Neutral days (-0.8% to +0.3%) left counter unchanged. Result: trading stopped on day 109 (June 1, 2023) — never actually testing 2024 or 2025.
**Fix:** Replaced with institutional drawdown-based controls (15% max drawdown kill switch, 5% single-day circuit breaker).
**Fake return before fix:** 56% over 109 days

### Bias 2 — Look-Ahead Bias in PnL Booking
**Symptom:** After fixing Bias 1, return jumped to 621% over 751 days.
**Root cause:** Multi-day trade PnL was booked on the entry date using future exit prices. On day 1 of a 5-day trade, the full PnL (calculated from day 5 prices) was credited to day 1 portfolio value. This cascaded through 751 days — every position sized off an inflated "current" portfolio value.
**Fix:** `pending_pnl` dict — PnL stored keyed by exit date, collected only when that date is processed in the main loop.
**Fake return before fix:** 621%

### Bias 3 — Pair Selection Look-Ahead (Most Impactful)
**Symptom:** After fixing Biases 1 and 2, return was still 617%. Top pair ADI-HPE showed 100% win rate across 15 trades. Average signal strength for top 10 pairs: 0.974–0.998.
**Root cause:** `find_quality_pairs()` was called with the full 2020–2025 dataset. Cointegration tests ran on data that included the entire test period (2023–2025). The system cherry-picked pairs that were *known* to cointegrate during the test window, then "tested" those same pairs on the same window.
**Fix:** Filter dataset to 2020–2022 only before calling pair selector. Spreads for backtesting still computed on full dataset using pair relationships learned from training period only.
**Return after fix:** 617% → **3.97%**

```
Bias 1 fix:  56%  (109 days)  →  stopped at June 2023 collapse (-15.6% drawdown)
Bias 2 fix:  621% (751 days)  →  look-ahead PnL eliminated
Bias 3 fix:  617% (751 days)  →  3.97% (honest out-of-sample)
```

---

## Risk Management Design

Replaced arbitrary consecutive-loss counter with five institutional-grade controls:

1. **Max Drawdown Kill Switch** — halts all trading if portfolio drawdown ≥ 15% from peak
2. **Single-Day Circuit Breaker** — halts if daily PnL < -5%
3. **Intraday Loss Pause** — pauses new entries if daily PnL < -3% (resumes when recovered)
4. **Volatility Scaling** — position size scaled to 50% when 20-day rolling vol > 1.5× 2% baseline
5. **Profit Protection** — position size linearly reduced to 50% when portfolio return > 40%, full 50% reduction at > 60% return

---

## What Needs to Improve

1. **Pair stability out-of-sample** — pairs cointegrating 2020–2022 do not maintain cointegration 2023–2025. Need rolling pair re-selection (e.g., quarterly re-screening)
2. **Signal model overfitting** — Transformer Encoder trained on only 3 years of daily spread data. Likely memorizing regime-specific patterns rather than learning generalizable entry/exit rules
3. **Feature set** — current features are price-derived only (MA, RSI, momentum, volatility). Macro regime features (VIX, credit spreads, sector rotation) could improve out-of-sample stability
4. **Transaction costs** — 60% cost impact on $100M over 5,600 trades is realistic but kills edge. Need fewer, higher-conviction trades

---

## Code Structure

```
pairs_trading/
├── main.py                   # Entry point
├── config.py                 # All imports, shared config
├── data_processor.py         # Russell 3000 data fetch + feature engineering
├── pair_selector.py          # Cointegration + quality scoring
├── trading_system.py         # Main orchestrator, backtest loop
├── transformer_encoder.py    # 4-layer Transformer Encoder (8-head, d_model=128)
├── transformer_agent.py      # Supervised signal classifier (binary cross-entropy)
├── multi_agent_system.py     # Multi-signal ensemble system
├── risk_manager.py           # Drawdown controls + position scaling
├── position_sizer.py         # Kelly-inspired sizing with risk scaling
├── transaction_costs.py      # Transaction cost model
├── json_export.py            # Results export
└── plotting.py               # Equity curve visualization
```

**~2,500 lines of Python. Built from scratch.**

---

## Status

- [x] Full system built and modular
- [x] Three look-ahead biases identified and eliminated
- [x] Institutional risk management implemented
- [ ] Quarterly pair re-selection (rolling window)
- [ ] Macro regime features
- [ ] Walk-forward validation

---

*The value here is not the 3.97% return. It's building the infrastructure to find and eliminate biases that fooled the system into showing 617% — and having the intellectual honesty to report what's left.*
