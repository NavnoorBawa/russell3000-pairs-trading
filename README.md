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

## Results (v26.1/v27 — post-audit, runs of 2026-06-14)

All figures are from the post-audit codebase. The main backtest return (+1.86%, Sharpe 0.58)
and walk-forward OOS (+0.36%/qtr, Sharpe 0.47) are stable v26.1 figures and are unaffected
by v27 changes. **Note:** the fund comparison Sharpe values below were computed on trade
exit-days only (~71 obs), not the full equity curve — a known v27 bug fix; these values are
inflated and will be replaced when the v27 re-run completes. Fund total returns are correct.
See [docs/PROGRESS.md](docs/PROGRESS.md) §v26 and §v27 for the full audit trail.

| Metric | Classical only | + Transformer |
|---|---|---|
| Main backtest (Jul 2023–2025) return / Sharpe | +1.86% / 0.58 | identical |
| Main backtest trades / win rate | 71 / 56.3% | identical |
| Walk-forward IS (W1–W9) avg / Sharpe | +3.12%/qtr / 4.65 | +3.00%/qtr / 4.70 |
| Walk-forward OOS (W10–W19) avg / Sharpe | **+0.36%/qtr / 0.47** | +0.53%/qtr (4-seed mean) |
| Walk-forward windows profitable | 14/19 (OOS 5/10) | ~identical |

**The transformer contributes ≈ 0, and that's a seed-robustness result, not a guess.**
The main backtest and all five cost profiles are bit-identical with and without it
(ranking only binds in the walk-forward). The transformer *does* train correctly here —
BCE falls below coin-flip entropy, so it genuinely discriminates — and **one** training
seed showed an OOS gain (+0.74%/qtr). A four-seed check (42, 1, 2, 7) dissolved it: OOS
spans 0.30–0.74%/qtr (mean +0.53 vs classical +0.36), a spread wider than the mean
effect, with one seed below baseline. So the apparent gain was a lucky draw; the edge is
the classical pipeline.

### Institutional cost profiles (the v26 reversal)

The same trade signals replayed under five fund-cost structures. In earlier versions
all five were negative — but that was **largely a bug**: the cost comparison inverted
the P&L of every short trade. Corrected:

| Profile (leverage) | Net return | Sharpe †  | Max DD |
|---|---|---|---|
| Quant HF (~5–7×) | +5.94% | 1.47 | −10.4% |
| Multi-Strat pod (~4×) | +3.60% | 1.33 | −7.2% |
| Fundamental L/S (~1.5–2×) | +1.14% | 0.86 | −4.0% |
| Buy-side institutional (1×) | +1.58% | 2.23 | −1.4% |
| Retail (1×) | −0.09% | −0.12 | −2.4% |

† *Sharpe values inflated (v27 bug fix in progress): computed on ~71 exit-days, not the full ~503-day equity curve. Total returns are correct.*

### What is honestly claimable — and what is not

- **The "no deployable edge / all profiles negative" headline from earlier versions
  was substantially a sign bug**, not a property of the strategy. Corrected, four of
  five cost profiles are net-positive on the main backtest. This is disclosed as a
  correction, not buried.
- **The binding constraint is the walk-forward OOS, and it is thin: +0.36%/qtr
  (~1.4%/yr gross), Sharpe 0.47, 5/10 OOS windows positive.** The fund table is
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
| v27 | second code audit: 6 bugs fixed — `get_pair_stats()` feature skew, `_active_symbols` concentration check never enforced, fund-comparison Sharpe computed on exit-days-only, deprecated fillna, signal-strength bucket off-by-one |

---

*Research project. Not investment advice; no claim of deployable performance.*
