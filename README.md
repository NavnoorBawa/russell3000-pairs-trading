# Russell 3000 Statistical Arbitrage — Pairs Trading Research System

**[Live project page →](https://navnoorbawa.github.io/russell3000-pairs-trading/)**

A modular pairs-trading research system: cointegration-based pair selection over the
Russell 3000, Kalman-filtered spreads, z-score mean-reversion signals, regime-aware
position scaling, walk-forward validation, institutional cost modeling, and a learned
signal-quality layer whose contribution is measured with a **controlled ablation**.

The point of this project is the process, not a headline Sharpe: every component's
contribution is measured, every metric is reproducible from the logs, and the bugs —
including ones that flattered results *and* ones that understated them — are documented
in full. The most recent example: a sign error in the cost comparison was making the
results look **worse** than reality; correcting it (v26) reversed the fund-cost
conclusion. Both directions are reported.

---

## Architecture

```
data (2,542 Russell 3000 symbols, 2020–2025, America/New_York)
  │
  ├─ Pair selection (quarterly re-selection)
  │    Engle-Granger cointegration (rolling ADF, both directions, p<0.05)
  │    PCA factor decomposition: 5 systematic factors (~58% variance) stripped;
  │    pairs also cointegrating on idiosyncratic residuals get a quality bonus
  │    Half-life filter (4–25 days), Hurst exponent, CUSUM structural-break check
  │
  ├─ Spread construction
  │    1-D Kalman filter → time-varying hedge ratio β_t; β locked at entry for
  │    exit/P&L so β drift can't be booked as profit (v12 fix)
  │
  ├─ Signal rule
  │    Entry |z| > 1.8, exit |z| < 0.5, half-life-adaptive z lookback,
  │    dynamic max hold = clamp(2.5 × half-life, 10–25 trading days)
  │
  ├─ Learned signal-quality layer (v24, switchable)
  │    Transformer-encoder scorer (38 features) trained on entry-outcome labels,
  │    used for opportunity RANKING ONLY. PAIRS_USE_TRANSFORMER=0 disables it.
  │
  ├─ Regime gate
  │    VIX bands (>30 → 0.5×, >40 → 0.25×) + 63-day sector-dispersion gate;
  │    hard skip (new entries) when >20% of trailing 63 days were reduced-scale
  │
  └─ Risk manager + portfolio accounting
       $100M capital, 3–10% positions, 30% gross-exposure cap, vol/profit scaling,
       walk-forward: 252-day train / 63-day test, 19 windows (2020–2025)
```

14 Python modules under [pairs_trading/](pairs_trading/). Entry point:
`python3 -m pairs_trading.main`.

## Results (v27 — post-audit, run of 2026-06-20)

All figures are from the post-audit (v27) codebase. They **supersede v26.1**: fully
enforcing the cross-symbol concentration limit (no stock in two concurrent pairs, across-
*and* within-day) cut the main backtest from 71 to 42 trades — fewer but higher-quality
(win rate 56→62%, Sharpe 0.58→0.75). See [docs/PROGRESS.md](docs/PROGRESS.md) §v26 and
§v27 for the full audit trail.

| Metric | Classical only | + Transformer |
|---|---|---|
| Main backtest (Jul 2023–2025) return / Sharpe | +1.32% / 0.75 | identical |
| Main backtest trades / win rate | 42 / 61.9% | identical |
| Walk-forward IS (W1–W9) avg / Sharpe | +2.34%/qtr / 4.77 | ~identical |
| Walk-forward OOS (W10–W19) avg / Sharpe | **+0.49%/qtr / 0.86** | ~identical |
| Walk-forward windows profitable | 15/19 (OOS 6/10) | ~identical |

**The transformer contributes ≈ 0 — an established, seed-tested result.** The quality
score only reorders same-day opportunities, so it can bind only when many pairs compete
on one day (the walk-forward), never in the sparse main backtest or the fund replay —
those are independent of it by construction. The transformer *does* train correctly
(BCE below coin-flip entropy, so it genuinely discriminates), and one training seed
showed an OOS gain (+0.74%/qtr); a four-seed check (42/1/2/7, run on the v26.1 codebase)
dissolved it into noise (mean +0.53 vs classical +0.36, a spread wider than the mean
effect, one seed below baseline). The edge is the classical pipeline; the ML layer is
tested-and-rejected.

### Institutional cost profiles

The same 42 trade signals replayed under five fund-cost structures. In versions before
v26 all five were negative — but that was **largely a bug** (the cost comparison inverted
the P&L of every short trade). Corrected, and with Sharpe computed on the full equity
curve (the v27 fix — earlier drafts inflated it on exit-days-only, then briefly zeroed it
on a tz-key bug, both now fixed):

| Profile (leverage) | Net return | Sharpe | Max DD |
|---|---|---|---|
| Quant HF (~5–7×) | +4.45% | 0.59 | −3.7% |
| Multi-Strat pod (~4×) | +2.72% | 0.55 | −2.5% |
| Fundamental L/S (~1.5–2×) | +0.95% | 0.38 | −1.4% |
| Buy-side institutional (1×) | +1.07% | 0.85 | −0.6% |
| Retail (1×) | +0.07% | 0.05 | −0.9% |

All five are net-positive on the main backtest, though retail only marginally (+0.07%).
The unlevered buy-side profile has the best risk-adjusted return (Sharpe 0.85) — lowest
costs, smallest drawdown.

### What is honestly claimable — and what is not

- **The "no deployable edge / all profiles negative" headline from earlier versions
  was substantially a sign bug**, not a property of the strategy. Corrected, all five
  cost profiles are net-positive on the main backtest (retail only marginally). This is
  disclosed as a correction, not buried.
- **The binding constraint is the walk-forward OOS, and it is thin: +0.49%/qtr
  (~2%/yr gross), Sharpe 0.86, 6/10 OOS windows positive.** The fund table is
  computed on the main backtest (a contiguous run with quarterly re-selection — the
  optimistic bound); the walk-forward is the rigorous forward estimate. The truth is
  between them, closer to the thin OOS.
- **This is not a confirmed deployable strategy.** A modest positive gross edge that
  survives leverage on the main backtest, but a thin and fragile out-of-sample
  result, is an honest description — not "it works."
- Notably, the documented 1.8σ entry threshold is **not** OOS-optimal: a stricter
  threshold the buggy code was accidentally using did better out-of-sample. That is
  flagged, not hidden.

## What this project is not

- **Not an "AI-enhanced" strategy.** The transformer is real, trained, wired in — and
  contributes ≈0, confirmed by a four-seed robustness check (one lucky seed suggested
  otherwise). v10–v23 carried it as dead code; v24 wired it in; v26 a label bug stopped
  it training; v26.1 fixed that and the seed check settled it.
- **Not reinforcement learning.** No DDPG/SAC/policy network exists in this codebase.
- **Not a validated deployable edge** — the rigorous OOS is thin (see above).
- The encoder runs on a single feature vector (sequence length 1), so it is
  architecturally an MLP head; described as a "learned signal-quality scorer."

## Reproducing

```bash
pip install -r requirements.txt   # Python 3.12 required; see requirements.txt

# full pipeline, transformer-ranked (default)
python3.12 -m pairs_trading.main > logs/backtest.log 2>&1

# classical-only ablation (same code path, quality ranking disabled)
PAIRS_USE_TRANSFORMER=0 python3.12 -m pairs_trading.main > logs/backtest_noml.log 2>&1

# seed-robustness check (reproduce the 4-seed ablation)
for seed in 42 1 2 7; do
  PAIRS_SEED=$seed python3.12 -m pairs_trading.main > logs/backtest_seed${seed}.log 2>&1
done
```

Inputs: `data/enhanced_russell_3000_data.pkl` (price cache; auto-refetched if absent),
`data/macro_data.pkl` (VIX + sector ETFs). Outputs: charts and JSON in
[outputs/](outputs/), logs in [logs/](logs/).

```
├── pairs_trading/   # source (14 modules; main.py is the entry point)
├── data/            # price + macro caches
├── docs/            # PROGRESS.md — complete version history v6→v27, every bug documented
├── logs/            # one log per backtest version
├── outputs/         # charts + JSON exports
├── scripts/         # diagnostics
└── archive/         # old versions, patches
```

## Version history (highlights)

Full engineering log in [docs/PROGRESS.md](docs/PROGRESS.md) — kept deliberately
unflattering; it is the most honest artifact in the repository.

| Version | Change |
|---|---|
| v9–v12 | bias fixes (survivorship, look-ahead P&L, pair-selection, Kalman β-drift) |
| v16–v19 | Kalman spread fixes, beta-weighted P&L, PCA residual cointegration, dynamic hold |
| v24 | transformer actually trained + wired in (ranking-only); controlled ablation |
| v25 | portfolio Sharpe corrected (computed on all days, not non-zero days) |
| v26 | code audit: fund-comparison sign bug, entry-threshold/hold-time/exposure fixes — reversed the all-negative fund result; rigorous OOS now the binding constraint |
| v26.1 | fixed a label bug that had silently disabled transformer training; 4-seed robustness check confirmed the ML contribution is ≈0 (one lucky seed had suggested otherwise) |
| v27 | second code audit: 9 bugs fixed — `get_pair_stats()` feature skew, cross-symbol concentration not enforced (across- *and* within-day), fund-comparison Sharpe computed on exit-days-only, `max_daily_trades` stat shadowing, deprecated fillna, signal-strength bucket off-by-one, dead code |

---

*Research project. Not investment advice; no claim of deployable performance.*
