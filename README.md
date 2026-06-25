# Russell 3000 Statistical Arbitrage — Pairs Trading Research System

[![CI](https://github.com/NavnoorBawa/russell3000-pairs-trading/actions/workflows/ci.yml/badge.svg)](https://github.com/NavnoorBawa/russell3000-pairs-trading/actions/workflows/ci.yml)
[![CodeQL](https://github.com/NavnoorBawa/russell3000-pairs-trading/actions/workflows/codeql.yml/badge.svg)](https://github.com/NavnoorBawa/russell3000-pairs-trading/actions/workflows/codeql.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-1a1a1a.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-1a1a1a.svg)](LICENSE)

**[Live project page →](https://navnoorbawa.github.io/russell3000-pairs-trading/)**

A modular pairs-trading research system: cointegration-based pair selection over the
Russell 3000, Kalman-filtered spreads, z-score mean-reversion signals, regime-aware
position scaling, walk-forward validation, institutional cost modeling, and a learned
signal-quality layer whose contribution is measured with a **controlled ablation**.

The point of this project is the process, not a headline Sharpe: every component's
contribution is measured, every metric is reproducible from the logs, and the result is
tested for whether it's real rather than asserted. The honest bottom line (v29): under
realistic t+1 execution there is **no statistically significant edge** — the
out-of-sample Sharpe is 0.08 with p=0.83, every bootstrap CI includes zero, and zero
pairs survive a Benjamini-Hochberg multiple-testing correction. The pipeline still beats
a random-pair control decisively and the textbook distance method on a risk-adjusted
basis. The deliverable is a rigorously validated research framework — and the discipline
to prove to itself that the edge isn't significant — not a deployable alpha.

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
  │    t+1 execution: signal on day-t close, fill at t+1 close (no same-bar look-ahead)
  │
  ├─ Learned signal-quality layer (v24, switchable)
  │    Transformer-encoder scorer (38 features) trained on entry-outcome labels,
  │    used for opportunity RANKING ONLY. PAIRS_USE_TRANSFORMER=0 disables it.
  │
  ├─ Regime gate
  │    VIX bands (>30 → 0.5×, >40 → 0.25×) + 63-day sector-dispersion gate;
  │    hard skip (new entries) when >20% of trailing 63 days were reduced-scale
  │
  ├─ Risk manager + portfolio accounting
  │    $100M capital, 3–10% positions, 30% gross-exposure cap, vol/profit scaling,
  │    walk-forward: 252-day train / 63-day test, 19 windows (2020–2025)
  │
  └─ Rigor layer (v28–v29) — "is the edge real?"
       significance.py: Probabilistic & Deflated Sharpe, Newey-West Sharpe t-stat,
       bootstrap CIs · benchmark.py: Gatev (2006) distance + random-pair control ·
       Benjamini-Hochberg FDR diagnostic on the cointegration p-values
```

16 Python modules under [pairs_trading/](pairs_trading/) (incl. `significance.py` and
`benchmark.py`, the v28–v29 rigor layer). Entry point: `python3 -m pairs_trading.main`.

## Results (v29 — realistic t+1 execution, run of 2026-06-21)

These figures use **t+1 execution**: the |z|>1.8 signal is decided on the day-t close,
but the trade *fills at the next trading day's close*, removing the same-bar look-ahead
of trading at the very price that generated the signal (v29). This is the honest cost of
realistic fills — and it matters a lot: the out-of-sample edge that looked like
+0.49%/qtr under same-bar execution (v27) **collapses to +0.08%/qtr** once you can't trade
on the signal bar. Most of the apparent OOS edge was that look-ahead.

| Metric | Value |
|---|---|
| Main backtest (Jul 2023–2025) return / Sharpe | +0.90% / 0.50 |
| Main backtest trades / win rate / max DD | 41 / 58.5% / −1.15% |
| Walk-forward IS (W1–W9) avg / Sharpe | +2.52%/qtr / 5.08 |
| Walk-forward OOS (W10–W19) avg / Sharpe | **+0.08%/qtr / 0.08** |
| Walk-forward windows profitable | 13/19 (OOS 4/10) |

### Execution sensitivity — the conclusion holds under both fill conventions

t+1-close (above) is the most conservative fill. The standard next-bar alternative is
t+1-**open** (`PAIRS_FILL=open`), which captures the overnight gap. The honest OOS result
straddles zero either way — under neither convention is there a positive, significant edge:

| Out-of-sample | t+1 close (headline) | t+1 open |
|---|---|---|
| Return / qtr | +0.08% | **−0.28%** |
| Stitched-daily Sharpe | 0.14 | −0.49 |
| Newey-West t-stat (p) | 0.21 (p=0.83) | −0.83 (p=0.41) |
| Deflated Sharpe | 3.6% | 0.1% |
| Windows positive | 4/10 | 3/10 |

The overnight gap works slightly *against* the strategy, so t+1-open is marginally worse —
the "no significant edge" conclusion is therefore robust to the fill assumption, not an
artifact of one pessimistic choice. (The pipeline still beats Gatev distance on Sharpe
— 0.40 vs 0.16 — and crushes random pairs under t+1-open too.)

### Is the edge real? — statistical significance (the headline)

The pipeline doesn't just report a Sharpe; it tests whether the Sharpe is distinguishable
from zero ([`significance.py`](pairs_trading/significance.py)). It is not.

| Test | Main backtest | Out-of-sample (stitched daily) |
|---|---|---|
| Annualised Sharpe | 0.50 | 0.14 |
| Newey-West t-stat (Sharpe ≠ 0) | 0.70 (p=0.49) | 0.21 (p=0.83) |
| Probabilistic Sharpe P(SR>0) | 78% | 58% |
| Bootstrap 95% CI on Sharpe | [−0.96, +1.93] | [−1.09, +1.59] |
| Deflated Sharpe (vs best-of-27 trials) | 11% | 3.6% |

The per-window OOS test agrees: mean +0.08%/qtr, t-stat 0.22, **p=0.83**, 4/10 windows
positive, 95% CI **[−0.54%, +0.79%]**. Every CI includes zero; every t-stat is below 1.
**Under realistic execution there is no statistically significant edge.** That conclusion —
reached with standard methods, on logged and reproducible runs — is the deliverable.

### Does it beat the textbook? — baseline benchmarks

[`benchmark.py`](pairs_trading/benchmark.py) runs the canonical Gatev (2006) distance
method and a random-pair control on the **same universe and OOS period**:

| Strategy | Return | Sharpe |
|---|---|---|
| Cointegration + Kalman (this project) | +0.90% | **0.50** |
| Distance method (Gatev 2006) | +1.82% | 0.16 |
| Random-pair control (avg of 5 draws) | −7.69% | −0.35 |

The pipeline crushes random pair selection (so the selection method genuinely matters)
and, while the distance method edges it on raw return, it does so at ~3× the volatility —
this project wins decisively on risk-adjusted return (Sharpe 0.50 vs 0.16). The edge over
the textbook is in *risk control*, not raw return.

### Multiple-testing reality check — FDR

Testing tens of thousands of pairs at p<0.05 manufactures false positives. A
Benjamini-Hochberg pass quantifies it: of **37,546 pairs tested, 6,052 are "cointegrated"
at raw p<0.05 — but ~1,877 of those are expected false positives by chance, and zero
survive BH-FDR at q<0.05** (only 8 at q<0.10). The cointegration signal is far weaker than
the raw p-values suggest. This is reported, not hidden — it's consistent with the
insignificant out-of-sample result above.

### Known limitations (every one biases *upward* on an already-null result)

A skeptical-reviewer pass surfaced three caveats. Crucially, all of them inflate apparent
performance, and the headline is already statistically insignificant — so the *true* edge
is at or below what is reported, and the negative conclusion is conservative, not at risk.

- **Survivorship bias (material, confirmed empirically).** The universe is sourced from
  ~current Russell 3000 membership back-filled with prices: of 36 names that delisted,
  failed, or were acquired during 2020–2025 (SIVB, FRC, SBNY, TWTR, ATVI, VMW, PXD, …),
  only **1 (BBBY) is present**. For pairs trading this biases results upward — the spreads
  that diverged permanently because a company failed (the catastrophic mean-reversion
  losses) are pre-filtered out. A leak-free fix needs a point-in-time, survivorship-free
  dataset (e.g. CRSP), which is not free; the limitation is disclosed rather than hidden.
- **Walk-forward in-sample windows carry pair-selection look-ahead.** The pair universe is
  chosen once on data through 2022-12-31, but windows W1–W9 test in 2020–2023, i.e. they
  trade a universe selected with their own future. Their high numbers (Sharpe ~5) are
  therefore *diagnostic only*, not a clean forward estimate. Only windows whose test period
  starts after the selection cutoff (W10+) are leak-free — and those are the ~0 result the
  conclusion rests on. Each window is now tagged `selection_clean` in the output.
- **The transformer scorer's labels are overlapping** (10-day forward, sampled every 2
  days), so its effective sample size is smaller than the raw count and its training is
  less informative than it looks. It does *not* leak across the train/test boundary (the
  forward horizon is capped inside the training window — verified, with a regression test
  in [`tests/test_leakage.py`](tests/test_leakage.py)) and it contributes ≈0 regardless.

This negative result is also consistent with the published literature: Do & Faff (2010,
*FAJ*; 2012, *J. Financial Research*) document that simple distance/cointegration pairs
profits declined after ~2002 and are largely consumed by trading costs.

### Institutional cost profiles

The same t+1 trade signals replayed under five fund-cost structures (Sharpe on the full
equity curve):

| Profile (leverage) | Net return | Sharpe | Max DD |
|---|---|---|---|
| Quant HF (~5–7×) | +2.87% | 0.54 | −4.5% |
| Multi-Strat pod (~4×) | +1.69% | 0.49 | −3.0% |
| Fundamental L/S (~1.5–2×) | +0.45% | 0.33 | −1.7% |
| Buy-side institutional (1×) | +0.81% | 0.80 | −0.7% |
| Retail (1×) | −0.17% | 0.01 | −1.1% |

Four of five are net-positive (retail goes slightly negative after costs). But these run
on the main backtest — the optimistic bound — and the binding constraint is the
insignificant OOS above.

### What is honestly claimable — and what is not

- **Under realistic (t+1) execution there is no statistically significant edge.** OOS is
  +0.08%/qtr, Sharpe 0.08, p=0.83, CI includes zero, Deflated Sharpe 3.6%, and zero pairs
  survive FDR at q<0.05. This is the honest conclusion, stated plainly — and it holds under
  **both** fill conventions (t+1-open is −0.28%/qtr, slightly worse), so it isn't an
  artifact of one pessimistic execution choice.
- **Much of the prior apparent edge was same-bar look-ahead.** Removing it (v29) cut OOS
  from +0.49%/qtr to +0.08%/qtr. That is exactly the kind of bias rigorous testing exists
  to catch — and it is reported, not buried.
- **The methodology is nonetheless sound:** it beats a random-pair control decisively and
  the textbook distance method on a risk-adjusted basis. The value here is a rigorously
  validated *research framework*, not a deployable alpha.
- **This is not a deployable strategy** — and the project proves that to itself with
  significance tests, a multiple-testing correction, and an execution-realism check,
  rather than overfitting to a number.

## What this project is not

- **Not an "AI-enhanced" strategy.** The transformer is real, trained, wired in — and
  contributes ≈0, confirmed by a four-seed robustness check (one lucky seed suggested
  otherwise). v10–v23 carried it as dead code; v24 wired it in; v26 a label bug stopped
  it training; v26.1 fixed that and the seed check settled it.
- **Not reinforcement learning.** No DDPG/SAC/policy network exists in this codebase.
- **Not a validated deployable edge** — under realistic t+1 execution the OOS edge is
  statistically indistinguishable from zero (see above).
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

# execution sensitivity: fill at the next bar's OPEN instead of CLOSE
PAIRS_FILL=open python3.12 -m pairs_trading.main > logs/backtest_open.log 2>&1
```

Inputs: `data/enhanced_russell_3000_data.pkl` (price cache; auto-refetched if absent),
`data/macro_data.pkl` (VIX + sector ETFs). Outputs: charts and JSON in
[outputs/](outputs/), logs in [logs/](logs/).

## Testing

A hermetic [`pytest`](tests/) suite (91 tests, ~4s, no data files or network) guards the
core math and the fixes from the audits — the engine internals (Kalman spread, max
drawdown, Hurst exponent, CUSUM break), the trade-gating logic (position-size clamps,
risk-validation rejections, drawdown/loss kill-switches), the significance estimators
(PSR, Newey-West t-stat, bootstrap CIs, Deflated Sharpe), the benchmark date-alignment
and degenerate-pair exclusion, the transaction-cost model (sign, scaling, borrow logic),
the pair-selection statistics (correlation, half-life), the JSON analytics helpers, the
data-validation/RSI helpers, and an import/instantiation smoke test.

The deterministic **core-logic modules are 73–97% covered** (transaction costs 97%,
benchmark 77%, significance 75%, position sizer 73%); overall line coverage is lower only
because the data-dependent pipeline (`run_comprehensive_backtest` needs the full price
cache) is validated by the full reproducible runs rather than unit tests. CI runs `ruff`
lint, a compile gate, the suite with coverage, and CodeQL security analysis on every push.

```bash
pip install pytest pytest-cov ruff       # or: pip install -e ".[dev]"
ruff check .                             # lint (clean)
pytest -q --cov=pairs_trading            # 91 tests + coverage
```

```
├── pairs_trading/   # source (16 modules; main.py is the entry point)
├── tests/           # pytest suite (91 hermetic tests; no data files / network)
├── data/            # price + macro caches
├── docs/            # PROGRESS.md — complete version history v6→v29, every bug documented
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
| v28 | rigor layer: statistical-significance module (PSR, Newey-West Sharpe t-stat, bootstrap CIs, Deflated Sharpe) + Gatev (2006) distance-method & random-pair benchmarks — the edge is **not** significant; pipeline beats both baselines on risk-adjusted terms |
| v29 | t+1 execution (removes same-bar look-ahead — OOS edge collapses +0.49%→+0.08%/qtr, confirming most of it was look-ahead) + Benjamini-Hochberg FDR diagnostic (0 pairs survive q<0.05) + configurable fill mode: under t+1-open the OOS is −0.28%/qtr, so the "no edge" conclusion holds under both conventions |

---

*Research project. Not investment advice; no claim of deployable performance.*
