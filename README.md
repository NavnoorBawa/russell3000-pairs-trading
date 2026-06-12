# Russell 3000 Statistical Arbitrage — Pairs Trading Research System

A modular pairs-trading research system: cointegration-based pair selection over the
Russell 3000, Kalman-filtered spreads, z-score mean-reversion signals, regime-aware
position scaling, walk-forward validation, and institutional cost modeling — plus a
learned signal-quality layer whose contribution was measured with a **controlled
ablation** and found to be ≈ zero.

That last clause is the point of this project. The headline result is not a Sharpe
ratio; it is a defensible experimental process: every component's contribution is
measured, every metric is reproducible from the logs, and the negative results are
reported alongside the positive ones.

---

## Architecture

```
data (2,542 Russell 3000 symbols, 2020–2025, America/New_York)
  │
  ├─ Pair selection (quarterly re-selection)
  │    Engle-Granger cointegration (rolling ADF) + adaptive 6-month re-test
  │    PCA factor decomposition: 5 systematic factors (~58% variance) stripped;
  │    pairs also cointegrating on idiosyncratic residuals get a quality bonus
  │    Half-life filter (4–25 days), Hurst exponent, CUSUM structural-break check
  │
  ├─ Spread construction
  │    1-D Kalman filter → time-varying hedge ratio β_t
  │    Beta-weighted P&L: log_ret1 − β·log_ret2, allocation total/(1+|β|) per leg
  │
  ├─ Signal rule
  │    Entry |z| > 1.8, exit |z| < 0.5, half-life-adaptive z lookback,
  │    dynamic max hold = clamp(2.5 × half-life, 10–25 days)
  │
  ├─ Learned signal-quality layer (v24, switchable)
  │    Transformer-encoder scorer (input: 38 features) trained on entry-outcome
  │    labels — P(spread reverts within 10 days | entry-grade signal).
  │    Used for opportunity RANKING ONLY, never as a trade gate.
  │    PAIRS_USE_TRANSFORMER=0 disables it → classical-only system.
  │
  ├─ Regime gate
  │    VIX bands (>30 → 0.5×, >40 → 0.25×) and 63-day cumulative sector
  │    dispersion ("walking on ice": VIX < 20 with high dispersion → 0.4×);
  │    hard skip when >20% of trailing 63 days were reduced-scale
  │
  └─ Risk manager + portfolio accounting
       $100M initial capital, 3–10% position sizes, volatility-scaled,
       walk-forward: 252-day train / 63-day test, 19 windows (2020–2025)
```

14 Python modules under [pairs_trading/](pairs_trading/). Entry point:
`python3 -m pairs_trading.main`.

## The ablation: does the ML layer earn its place?

The transformer scorer is trained leak-free (labels only from each window's own
training slice) and its prediction replaces a hardcoded quality score in opportunity
ranking. Both system variants run on identical data and code, switched by one flag:

| Metric (same data, same code, one flag) | Classical only | + Transformer | Δ |
|---|---|---|---|
| Main backtest return / Sharpe | +0.31% / 0.22 | identical | 0 |
| Walk-forward IS avg return / Sharpe | +5.26%/qtr / 4.504 | identical | 0 |
| Walk-forward OOS avg return / Sharpe | +1.30%/qtr / 1.217 | +1.32%/qtr / 1.232 | +0.02pp / +0.015 |
| Walk-forward OOS win rate | 74.3% | 74.5% | +0.2pp |
| Institutional cost profiles (5) | all negative (−0.65% to −5.41%) | identical to the cent | 0 |

**Measured contribution of the learned layer: +0.02pp/qtr OOS — indistinguishable
from noise.** The training diagnostics explain why: at every training run, final BCE
loss ≈ the entropy of a constant base-rate prediction (e.g. 0.315 vs 0.309), because
82–91% of |z| > 1.8 entries revert within the horizon regardless of features — the
entry rule has already extracted the signal the labels contain. The model converges
to predicting the prior, the ranking barely changes, and the system is unchanged.

The ML layer is therefore presented as **tested and rejected**, and the system's edge
is attributed to what the ablation says it comes from: pair selection, mean-reversion
timing, and regime gating.

## Results (v25 — corrected metrics, runs of 2026-06-12)

Sharpe figures in logs before v25 were inflated: the stats code dropped zero-PnL
days before computing mean/std, then annualized by √252 — on a window with 3 active
days out of 63 this overstates Sharpe ~6×. v25 computes portfolio Sharpe on all
calendar days. Returns, trade counts, win rates, and drawdowns are unaffected.

| Metric | Classical only | + Transformer | Δ |
|---|---|---|---|
| Main backtest return | +0.31% / Sharpe 0.22 / 34 trades / WR 52.9% | identical | 0 |
| Walk-forward IS (W1–W9) avg | +5.26%/qtr / Sharpe 4.504 / WR 84.4% | identical | 0 |
| Walk-forward OOS (W10–W19) avg | +1.30%/qtr / Sharpe 1.217 / WR 74.3% | +1.32%/qtr / Sharpe 1.232 / WR 74.5% | +0.02pp |
| Walk-forward windows profitable | 17/19 | 17/19 | 0 |
| IS→OOS return degradation | ~75% | ~75% | 0 |
| Institutional cost profiles | all negative (−0.65% to −5.41%) | identical to the cent | 0 |

### What is honestly claimable

- Positive gross OOS walk-forward returns: **+1.3%/qtr average** over the ten windows
  following the 2023 regime break (W10–W19), 74% win rate, 17/19 windows profitable
  (two of the profitable windows have ≤3 trades and should not be leaned on).
- **No deployable net edge at institutional cost structures.** All five modeled fund
  profiles (quant HF ~5–7×, pod shop ~4×, fundamental L/S ~1.5–2×, unlevered
  institutional, retail) lose money on the recent-period backtest. This is disclosed,
  not hidden: the gross edge is too thin to survive realistic costs and leverage.
- IS→OOS degradation is ~75%, well above the 30–50% often quoted for healthy
  strategies. Whether that is regime break, overfit, or both is **not settled** by
  this work.

## What this project is not

- **Not an "AI-enhanced" strategy.** The transformer is real, trained, and wired in —
  and measurably contributes nothing. Versions v10–v23 of this project carried a
  transformer as dead code while results came from the classical rule; v24 fixed the
  wiring, and the ablation quantified the truth. See
  [docs/PROGRESS.md](docs/PROGRESS.md) for the full audit trail.
- **Not reinforcement learning.** No DDPG/SAC/policy network exists in this codebase.
- **Not a deployable fund strategy** at the cost profiles modeled (see above).
- The encoder runs on a single feature vector (sequence length 1), so self-attention
  attends over one token — architecturally equivalent to an MLP head. It is described
  as a "learned signal-quality scorer," not as a sequence model.

## Reproducing

```bash
# full pipeline, transformer-ranked (v24+ default)
python3 -m pairs_trading.main > logs/backtest.log 2>&1

# classical-only ablation (same code path, quality ranking disabled)
PAIRS_USE_TRANSFORMER=0 python3 -m pairs_trading.main > logs/backtest_noml.log 2>&1
```

Inputs: `data/enhanced_russell_3000_data.pkl` (price cache; auto-refetched if absent),
`data/macro_data.pkl` (VIX + sector ETFs). Outputs: charts and JSON exports in
[outputs/](outputs/), logs in [logs/](logs/).

```
├── pairs_trading/   # source (14 modules; main.py is the entry point)
├── data/            # price + macro caches
├── docs/            # PROGRESS.md — complete version history v6→v25, every bug documented
├── logs/            # one log per backtest version
├── outputs/         # charts + JSON exports
├── scripts/         # diagnostics
└── archive/         # old versions, patches
```

## Version history (highlights)

Full engineering log in [docs/PROGRESS.md](docs/PROGRESS.md) — including the bugs:
survivorship bias (v9), Kalman spread `pct_change` on a zero-crossing series (v16),
beta-normalization of P&L (v17), the dead-code audit (v24), and the Sharpe
computation fix (v25). The log is kept deliberately unflattering; it is the most
honest artifact in the repository.

| Version | Change |
|---|---|
| v9–v12 | bias fixes, regime gate, threshold tightening |
| v16–v19 | Kalman spread fixes, beta-weighted P&L, PCA residual cointegration, dynamic hold |
| v24 | transformer actually trained + wired in (ranking-only); controlled ablation; `PAIRS_USE_TRANSFORMER` switch |
| v25 | portfolio Sharpe corrected (all-days); final verification runs |

---

*Research project. Not investment advice; no claim of deployable performance.*
