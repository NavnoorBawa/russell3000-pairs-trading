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
tested for whether it's real rather than asserted. The honest bottom line (v31): **the strategy does not work, and it loses
to the textbook.** A pre-launch audit found six result-changing bugs — every one of them
flattering the result — including an inverted stop-loss that cut winners and never stopped
a loss, an exit search truncated to the trading window that silently discarded the trades
that failed to revert, an exit still filling on its own signal bar, and a walk-forward
universe built from the union of *all* quarterly re-selections including future ones. With
those fixed the out-of-sample result is **−0.28%/qtr (pooled Sharpe −1.23, 1 of 10 windows
positive)**, every bootstrap CI still includes zero, and zero pairs survive a
Benjamini-Hochberg correction. Run with its own paper's rolling re-formation, the textbook
Gatev distance method **beats this pipeline** (+0.26 vs −0.31 Sharpe). Against a random-pair
control the pipeline wins on cumulative return (−0.31% vs −1.74%) but **loses on Sharpe**
(−0.31 vs −0.02), so even that comparison is not a clean win. The deliverable is a rigorously validated research framework — and the discipline
to prove to itself that the edge isn't significant — not a deployable alpha.

---

## Architecture

```
data (2,542 Russell 3000 symbols, 2020–2025, America/New_York)
  │
  ├─ Pair selection (re-selected every 90 trading days, ~4 months)
  │    Engle-Granger cointegration (rolling ADF, both directions, p<0.05)
  │    PCA factor decomposition: 5 systematic factors (56.5% variance) stripped;
  │    pairs also cointegrating on idiosyncratic residuals get a quality bonus
  │    Half-life filter (4–25 days) — Hurst and CUSUM are entry-time gates, not
  │
  ├─ Spread construction
  │    1-D Kalman filter → time-varying hedge ratio β_t; β locked at entry for
  │    exit/P&L so β drift can't be booked as profit (v12 fix)
  │
  │    selection filters (they run per-entry in trading_system.py, not here)
  │
  ├─ Signal rule
  │    Entry |z| > 1.8, exit |z| < 0.5, half-life-adaptive z lookback,
  │    per-entry gates on the locked-β spread: Hurst exponent, CUSUM structural break,
  │    dynamic max hold = clamp(2.5 × half-life, 10–25 trading days)
  │    t+1 execution: signal on day-t close; entry AND exit fill at t+1 close (v31)
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
  │    walk-forward: 252-day train / 63-day test, 19 slots (10 with an eligible universe)
  │
  └─ Rigor layer (v28–v29) — "is the edge real?"
       significance.py: Probabilistic & Deflated Sharpe, Newey-West Sharpe t-stat,
       bootstrap CIs · benchmark.py: Gatev (2006) distance + random-pair control ·
       Benjamini-Hochberg FDR diagnostic on the cointegration p-values
```

16 Python modules under [pairs_trading/](pairs_trading/) (incl. `significance.py` and
`benchmark.py`, the v28–v29 rigor layer). Entry point: `python3 -m pairs_trading.main`.

## Results (v31.1 — realistic t+1 execution on entry *and* exit, run of 2026-09-05)

These figures use **t+1 execution**: the |z|>1.8 signal is decided on the day-t close,
but the trade *fills at the next trading day's close*, removing the same-bar look-ahead
of trading at the very price that generated the signal (v29). This is the honest cost of
realistic fills. As of v31 it applies to the **exit as well as the entry** — the exit
previously filled at the exact bar whose close produced the exit signal, which was the same
same-bar look-ahead v29 removed on the entry side. The out-of-sample edge that looked like
+0.49%/qtr under same-bar execution (v27), then +0.08%/qtr under entry-only t+1 (v29), is
**−0.28%/qtr** once the exit is honest too and the selection leaks are closed.

| Metric | Value |
|---|---|
| Main backtest (Jul 2023–2025) return / Sharpe | −0.31% / −0.31 |
| Main backtest trades / win rate / max DD | 14 / 28.6% / −0.81% |
| Walk-forward OOS avg / pooled Sharpe | **−0.28%/qtr / −1.23** |
| Walk-forward windows profitable | 1/10 (3 of the 10 traded nothing) |
| Selection-clean windows | 10/10 — the 9 earliest slots have no eligible universe and are skipped |

### Execution sensitivity — the conclusion holds under both fill conventions

t+1-close (above) is the most conservative fill. The standard next-bar alternative is
t+1-**open** (`PAIRS_FILL=open`), which captures the overnight gap. The honest OOS result
straddles zero either way — under neither convention is there a positive, significant edge:

| Out-of-sample | t+1 close (headline) | t+1 open |
|---|---|---|
| Return / qtr | **−0.28%** | −0.28% |
| Pooled Sharpe | −1.23 | −1.13 |
| Newey-West t-stat (p) | −1.86 (p=0.06) | −1.69 (p=0.09) |
| Deflated Sharpe | 0.0% | 0.0% |
| Windows positive | 1/10 | 2/10 |

> **v31.1 note.** The open-fill column is a logged re-run on the corrected v31 code (seed 42,
> `logs/backtest_v31_open.log`; main backtest under t+1-open: −0.17% / Sharpe −0.18 / 14
> trades). Capturing the overnight gap makes the loss slightly *smaller* but changes nothing
> that matters: under neither convention is there a positive, significant out-of-sample edge,
> so the conclusion is robust to the choice of next-bar fill.

### Is the edge real? — statistical significance (the headline)

The pipeline doesn't just report a Sharpe; it tests whether the Sharpe is distinguishable
from zero ([`significance.py`](pairs_trading/significance.py)). It is not.

| Test | Main backtest | Out-of-sample (stitched daily) |
|---|---|---|
| Annualised Sharpe | −0.31 | −1.23 |
| Newey-West t-stat (mean ≠ 0) | −0.49 (p=0.63) | −1.86 (p=0.06) |
| Probabilistic Sharpe P(SR>0) | 32.5% | 2.2% |
| Bootstrap 95% CI on Sharpe | [−1.70, +0.80] | [−2.41, +0.06] |
| Deflated Sharpe (vs best-of-27 trials) | 0.9% | 0.0% |

The per-window OOS test agrees: mean **−0.282%/qtr**, t-stat −1.94, **p=0.085**, 1/10
windows positive, 95% CI **[−0.611%, +0.047%]** (Student-t, consistent with the t-test).
**The result is negative and not statistically distinguishable from zero.**
That conclusion — reached with standard methods, on logged and reproducible runs — is the
deliverable.

### Does it beat the textbook? — baseline benchmarks

[`benchmark.py`](pairs_trading/benchmark.py) runs the canonical Gatev (2006) distance
method and a random-pair control on the **same universe and OOS period**:

| Strategy | Return | Sharpe |
|---|---|---|
| Cointegration + Kalman (this project) | −0.31% | **−0.31** |
| Distance method (Gatev 2006), rolling 12m/6m | +2.78% | **+0.26** |
| Random-pair control (avg of 5 draws) | −1.74% | −0.02 |

Read carefully, the random-pair row is not the consolation it looks like. The pipeline wins
on cumulative return (−0.31% vs −1.74%) but **loses on Sharpe** (−0.31 vs −0.02) — and this
project judges everything else on risk-adjusted terms, so it does not get to switch measures
here. The five random draws also range from −12.8% to +23.4% (Sharpe −0.45 to +1.08); a
5-draw mean that wide cannot settle the question either way. The defensible statement is
that pair selection is not obviously worse than picking at random. It is **not** better than
the textbook. The earlier claim that it won on risk-adjusted return
(Sharpe 0.50 vs 0.16) was an artifact of how the baseline was run: Gatev was formed **once**
over ~42 months and then traded ~30 months with no re-formation, while this strategy
re-selected every 90 trading days (~4 months). Given the paper's own rolling 12-month formation / 6-month trading
scheme, the distance method wins on both raw and risk-adjusted return.

### Multiple-testing reality check — FDR

Testing tens of thousands of pairs at p<0.05 manufactures false positives. A
Benjamini-Hochberg pass quantifies it: of **36,524 pairs with usable p-values, 3,725 are
"cointegrated" at raw p<0.05 — but ~1,826 of those are expected false positives by chance,
and zero survive BH-FDR at q<0.05** (zero at q<0.10 too). The cointegration signal is far
weaker than the raw p-values suggest. As of v31 these are Bonferroni-corrected across the
two Engle-Granger directions; the previous `min(p₁,p₂)` was not a valid p-value and
inflated the test size, which means the *old* FDR input was itself too optimistic. This is reported, not hidden — it's consistent with the
insignificant out-of-sample result above.

### Known limitations (every one biases *upward* on an already-null result)

A skeptical-reviewer pass and a later verification sweep surfaced four caveats. Crucially, all of them inflate apparent
performance, and the headline is already statistically insignificant — so the *true* edge
is at or below what is reported, and the negative conclusion is conservative, not at risk.

- **Survivorship bias (material, confirmed empirically).** The universe is sourced from
  ~current Russell 3000 membership back-filled with prices: of 36 names that delisted,
  failed, or were acquired during 2020–2025 (SIVB, FRC, SBNY, TWTR, ATVI, VMW, PXD, …),
  only **1 (BBBY) is present**. For pairs trading this biases results upward — the spreads
  that diverged permanently because a company failed (the catastrophic mean-reversion
  losses) are pre-filtered out. A leak-free fix needs a point-in-time, survivorship-free
  dataset (e.g. CRSP), which is not free; the limitation is disclosed rather than hidden.
- **Walk-forward selection look-ahead (fixed in v31; kept here for the record).** Through
  v30 the walk-forward traded a pair universe unioned from *all* quarterly re-selections —
  future ones included — so an early window could trade pairs first identified as
  cointegrated years later, and the Sharpe ~5 those windows once showed was an artifact.
  v31 restricts each window to pairs whose re-selection date is already known by its
  train-end; the nine earliest slots have no eligible universe and are skipped rather than
  back-filled, leaving **10/10 traded windows `selection_clean`**. The published OOS
  (−0.28%/qtr) is therefore leak-free on selection.
- **The transformer scorer's labels are overlapping** (10-day forward, sampled every 2
  days), so its effective sample size is smaller than the raw count and its training is
  less informative than it looks. It does *not* leak across the train/test boundary (the
  forward horizon is capped inside the training window — verified, with a regression test
  in [`tests/test_leakage.py`](tests/test_leakage.py)) and it contributes exactly 0 regardless.
- **The shipped price cache predates the penny-stock-filter fix.** `data/enhanced_russell_3000_data.pkl`
  was built when the sub-$2 screen was applied over the *full* sample, so a name that fell
  below $2 at any point was removed retroactively from the earlier periods in which it
  still traded normally. That is the same direction of bias as survivorship — the worst
  outcomes are pre-filtered — and it cannot be undone without refetching the universe.
  The screen itself is fixed in code; the cache carries the old behaviour.

This negative result is also consistent with the published literature: Do & Faff (2010,
*FAJ*; 2012, *J. Financial Research*) document that simple distance/cointegration pairs
profits declined after ~2002 and are largely consumed by trading costs.

### Institutional cost profiles

The same t+1 trade signals replayed under five fund-cost structures (Sharpe on the full
equity curve):

| Profile (leverage) | Net return | Sharpe | Max DD |
|---|---|---|---|
| Quant HF (~5–7×) | −1.46% | −0.57 | −2.5% |
| Multi-Strat pod (~4×) | −1.03% | −0.60 | −1.7% |
| Fundamental L/S (~1.5–2×) | −0.61% | −0.70 | −1.0% |
| Buy-side institutional (1×) | −0.12% | −0.28 | −0.3% |
| Retail (1×) | −0.44% | −0.96 | −0.6% |

All five are net-negative as of v31. The earlier "four of five positive" table was an
artifact: the fund replay booked **2× gross P&L** (the full notional instead of the per-leg
half) against a 1× cost basis, and it inherited the same-bar exit fill and the discarded
non-reverting trades. Corrected, every profile loses — and the more leverage, the larger the
loss. These run on the main backtest, the optimistic bound; the binding constraint is the
negative OOS above.

### What is honestly claimable — and what is not

- **Under realistic (t+1) execution the result is negative.** OOS is −0.28%/qtr, pooled
  Sharpe −1.23, per-window p=0.085, every CI includes zero, Deflated Sharpe 0.0%, and zero
  pairs survive FDR at q<0.05. There is no edge here to deploy, and the honest statement is
  not "not significant" but "negative and indistinguishable from noise".
- **Essentially all of the prior apparent edge was look-ahead and bugs.** +0.49%/qtr
  (same-bar, v27) → +0.08%/qtr (entry-only t+1, v29) → −0.28%/qtr (v31, once the exit also
  fills at t+1, the stop-loss sign is corrected, unresolved trades stop being discarded, and
  each walk-forward window can only trade a universe already selected at its train-end).
  Every one of those six bugs was biased in the flattering direction.
- **It does not beat the textbook.** Given its own paper's rolling re-formation, the Gatev
  (2006) distance method returns +2.78% at Sharpe +0.26 versus this pipeline's −0.31. The
  pipeline does still beat a random-pair control (−1.74%).
- **Breadth is the structural problem.** 14 trades in the main backtest and 3 of 10
  walk-forward windows with no trades at all. Under Grinold's Fundamental Law
  (IR = IC·√BR) that is far too little breadth to produce a meaningful information ratio at
  any plausible IC, regardless of signal quality.
- **What is actually defensible** is the audit trail: a framework disciplined enough to keep
  finding its own errors until the number stopped flattering it. That is a *research
  framework*, not a deployable alpha.
- **This is not a deployable strategy** — and the project proves that to itself with
  significance tests, a multiple-testing correction, and an execution-realism check,
  rather than overfitting to a number.

## What this project is not

- **Not an "AI-enhanced" strategy.** The transformer is real, trained, wired in — and
  contributes **exactly 0** — the v31 ablation is bit-identical on every reported metric (an
  earlier four-seed check had already placed it within noise; one lucky seed suggested
  otherwise). v10–v23 carried it as dead code; v24 wired it in; v26 a label bug stopped
  it training; v26.1 fixed that and the seed check settled it.
- **Not reinforcement learning.** No DDPG/SAC/policy network exists in this codebase.
- **Not a validated deployable edge** — under realistic t+1 execution the OOS result is
  negative (−0.28%/qtr) and not distinguishable from zero (see above).
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

# guard against stale published figures — fails if README/index.html disagree with the log
python3.12 scripts/check_published_numbers.py --log logs/backtest.log

# regenerate the social card after the numbers change
python3.12 scripts/make_og_image.py
```

> **Before publishing a new result**, run `check_published_numbers.py`. The v31 audit exists
> partly because the site advertised v29 figures long after the code stopped producing them,
> and nothing in the test suite could notice — no test reads the README or the site.

Inputs: `data/marketcap.csv` (the study universe — **required**, and not redistributed
here; `load_symbols()` fails with instructions if it is missing rather than silently
substituting a different universe), `data/enhanced_russell_3000_data.pkl` (price cache;
auto-refetched from yfinance if absent) and `data/macro_data.pkl` (VIX + sector ETFs).

Outputs: charts and JSON are written to `outputs/`, logs to `logs/`. All four directories
are `.gitignore`d — they are machine-generated and would otherwise add ~1 GB to the repo —
so they do not exist in a fresh clone and are created on the first run.

## Testing

A hermetic [`pytest`](tests/) suite (109 tests, ~6s, no data files or network) guards the
core math and the fixes from the audits — the engine internals (Kalman spread, max
drawdown, Hurst exponent, CUSUM break), the trade-gating logic (position-size clamps,
risk-validation rejections, drawdown/loss kill-switches), the significance estimators
(PSR, Newey-West t-stat, bootstrap CIs, Deflated Sharpe), the benchmark date-alignment
and degenerate-pair exclusion, the transaction-cost model (sign, scaling, borrow logic),
the pair-selection statistics (correlation, half-life), the JSON analytics helpers, the
data-validation/RSI helpers, and an import/instantiation smoke test.

The deterministic **core-logic modules are 73–97% covered** (transaction costs 97%,
benchmark 80%, significance 75%, position sizer 73%); overall line coverage is lower only
because the data-dependent pipeline (`run_comprehensive_backtest` needs the full price
cache) is validated by the full reproducible runs rather than unit tests. CI runs `ruff`
lint, a compile gate, the suite with coverage, and CodeQL security analysis on every push.

```bash
pip install pytest pytest-cov ruff       # or: pip install -e ".[dev]"
ruff check .                             # lint (clean)
pytest -q --cov=pairs_trading            # 109 tests + coverage
```

```
├── pairs_trading/   # source (16 modules; main.py is the entry point)
├── tests/           # pytest suite (109 hermetic tests; no data files / network)
├── data/            # price + macro caches
├── docs/            # PROGRESS.md — complete version history v6→v31.1 (25 entries), every bug documented
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
| v30 | skeptical-reviewer leakage audit: confirmed **survivorship bias** (of 36 names that delisted/failed/were acquired 2020–2025, only 1 is in the cache) and pair-selection look-ahead in the walk-forward in-sample windows; added `selection_clean` window tagging, a runtime leak guard, `tests/test_leakage.py`, README "Known limitations", and the Do & Faff (2010/2012) corroboration. Additive only ⇒ v29 numbers unchanged |
| v31 | pre-launch audit (101 findings, 20 agents, adversarial verification): **six result-changing bugs** — inverted stop-loss, exit search truncated to the window (discarded non-reverting trades), same-bar exit fill, walk-forward universe unioned from *future* re-selections, per-stock features read from the study's terminal date, `min(p₁,p₂)` used as a cointegration p-value; plus a 2× gross-PnL error in the fund replay, PCA zero-fill, full-sample Kalman Q, full-sample penny-stock filter, `bfill` look-ahead in indicator warm-up, and a Gatev baseline that never re-formed. **Result: OOS +0.08 → −0.28%/qtr; the textbook baseline now wins.** Security: `pip-audit` 16 → 0 |

---

*Research project. Not investment advice; no claim of deployable performance.*
