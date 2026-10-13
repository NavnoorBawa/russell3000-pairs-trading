# Russell 3000 Statistical Arbitrage — Pairs Trading Research System

[![CI](https://github.com/NavnoorBawa/russell3000-pairs-trading/actions/workflows/ci.yml/badge.svg)](https://github.com/NavnoorBawa/russell3000-pairs-trading/actions/workflows/ci.yml)
[![CodeQL](https://github.com/NavnoorBawa/russell3000-pairs-trading/actions/workflows/codeql.yml/badge.svg)](https://github.com/NavnoorBawa/russell3000-pairs-trading/actions/workflows/codeql.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-1a1a1a.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-1a1a1a.svg)](LICENSE)

**[Live project page →](https://navnoorbawa.github.io/russell3000-pairs-trading/)**

A research system that asks one question and is built to answer it honestly: **does a
cointegration pairs-trading strategy on the Russell 3000 have an edge after realistic
execution and costs, out of sample?** It selects pairs on formation data only, trades a
Kalman-filtered spread with next-day fills and a per-stock cost model, validates with a
continuous walk-forward simulation, and then tests whether the result is distinguishable
from zero (Probabilistic and Deflated Sharpe, Newey-West, block bootstrap) and from two
baselines (Gatev et al. 2006 distance method, random pairs).

> **Status — v32 (October 2026): the engine was rebuilt; the published v31.1 figures are
> withdrawn until the study is re-run.**
>
> A complete audit of v31.1 (about 270 findings across seven review areas, nearly all
> confirmed by an independent adversarial re-check) found defects in the trading engine itself: entry
> and exit used different z-scores, the Kalman "hedge ratio" was a price-level ratio that
> changed with the data vendor's back-adjustment, each trade's final P&L reached the
> position sizer and the loss cool-off on the day it was **opened**, P&L was booked on
> exit days only, and the walk-forward silently discarded trades still open at a window's
> end. v32 rewrites the engine, the cost model, the ranker training, the benchmarks and the
> outputs ([what changed](#what-v32-changed)). Some of these defects flattered the old
> result and others changed the strategy itself, so the net direction cannot be predicted —
> the v31.1 numbers are therefore withdrawn, not adjusted.
>
> v32 has **not yet been re-run on the study data** (the universe file is not
> redistributable and the price cache is local to the author). It is validated instead on
> synthetic markets with known answers ([below](#validation-on-markets-with-known-answers)),
> by 300+ hermetic tests (89% line coverage) and by an end-to-end run of the full pipeline
> in CI (with classical ranking; the trained-ranker path is tested separately). The results table below fills itself from the next study run.

---

## Results

| | v32 | v31.1 (withdrawn) |
|---|---|---|
| Main backtest (Jul 2023 – 2025): return | <!--m:main.total_return_pct-->—<!--/m--> | −0.31% |
| Main backtest: Sharpe | <!--m:main.sharpe-->—<!--/m--> | −0.31 |
| Main backtest: trades | <!--m:main.trades-->—<!--/m--> | 14 |
| Walk-forward OOS: average window return | <!--m:oos.avg_window_return_pct|3-->—<!--/m--> | −0.282% |
| Walk-forward OOS: pooled daily Sharpe | <!--m:oos.pooled_sharpe-->—<!--/m--> | −1.23 |
| Walk-forward OOS: windows positive | <!--m:oos.windows_positive-->—<!--/m--> of <!--m:oos.windows-->—<!--/m--> | 1 of 10 |
| Per-window t-test p-value | <!--m:significance.oos_windows.p|3-->—<!--/m--> | 0.085 |
| Gatev (2006) distance method, same period: Sharpe | <!--m:benchmarks.gatev.sharpe-->—<!--/m--> | +0.26 |
| Ranker out-of-sample AUC (0.5 = no skill) | <!--m:ranker.oos_auc|3-->—<!--/m--> | not measured |

"—" means not yet run. After a run, `python scripts/check_published_numbers.py --write`
fills every marked number in this README and on the site from
`outputs/headline_metrics.json`, and the same script without `--write` fails CI-style if
any published number disagrees with the run.

**What v31.1 concluded, for the record:** no edge — negative out-of-sample, not
statistically distinguishable from zero, zero pairs surviving a Benjamini-Hochberg
correction, and beaten by the textbook distance method. Whether v32 confirms that is what
the re-run will show; nothing here assumes it.

## Validation on markets with known answers

A backtest on real data can only say what a strategy did, not whether the code measures
what it claims. [`scripts/synthetic_validation.py`](scripts/synthetic_validation.py) runs
the real engine, with its full cost model, on synthetic markets whose answer is known
([`pairs_trading/synthetic.py`](pairs_trading/synthetic.py)); CI runs two markets per
scenario on every push to main and on pull requests. Five independent markets per scenario:

| Check | What must happen | v32 result |
|---|---|---|
| Planted cointegrated pairs (OU spreads, half-life 5–14 days) | find a large positive edge | 2,241 trades, +80.7 bp gross per trade (t = 23.7), median net Sharpe 3.3 |
| Correlated but not cointegrated pairs (random-walk spread, no drift), forced into the universe | no edge (a positive mean would be look-ahead) | 2,485 trades, +4.6 bp (t = 1.15); 16 more markets: 8,325 trades, +0.25 bp (t = 0.12) |
| Kalman hedge ratio vs the true slope | recover it | median absolute error 0.031 (90th percentile 0.073) |
| Pair selection on 2020–2022 data, 6 planted pairs among 24 names | find them, admit few others | 100% of planted pairs found; unrelated pairs admitted: 2.4 of 270 per market with planted pairs, 2.6 of 276 per market with none (≤ 3% in every market) |

The test suite adds causality checks with teeth: every result dated before T is unchanged
when all prices after T are replaced (the check catches a deliberately re-introduced
sizer look-ahead at every cut-off tried), the same trades are taken at the same z-scores
when the vendor back-adjusts history for a split after the sample, and the daily P&L
series reconciles exactly with the per-trade P&L.

## Architecture (v32)

```
universe: data/marketcap.csv (Russell 3000 constituents) · daily OHLCV 2020–2025 · VIX + 11 sector ETFs
  │
  ├─ Pair selection — formation data to 2022-12-31 only
  │    screens on point-in-time (split-unadjusted) price and dollar volume; 300 most liquid
  │    positive return correlation ≥ 0.25 · two-direction Engle-Granger p < 0.05 (Bonferroni)
  │    half-life 4–25 days on the cointegrating spread · heuristic quality score
  │    PCA (5 factors) residual cointegration → quality bonus · Benjamini-Hochberg diagnostic
  │    re-selection every 90 trading days: 2-year re-test + 126-day check (p ≤ 0.30)
  │
  ├─ Spread model
  │    two-state Kalman filter (slope + intercept) on log prices centred on their burn-in
  │    means: β is a hedge ratio, and every signal is invariant to vendor back-adjustment
  │
  ├─ Trading rule — one z-score for everything
  │    z = locked spread (lp1 − β_t·lp2) vs its mean/std over the last 30–60 bars (3 × half-life), frozen at the signal
  │    entry |z| ≥ 1.8 · target |z| ≤ 0.5 · stop 1.5 further against · time stop clamp(2.5·HL, 10, 25) days
  │    signal at day-t close, fill at the t+1 close (entry and exit); legs $1 vs $β
  │    gates: 20-day return correlation ≥ 0.20, β in [0.25, 4], loss cool-off (a 1%-of-equity cost rail never binds here)
  │
  ├─ Ranker (optional, PAIRS_USE_TRANSFORMER=0 disables)
  │    classifier of P(trade profitable) on 30 features, trained on outcomes of the actual rule,
  │    used only to ORDER same-day candidates; out-of-sample AUC reported
  │
  ├─ Portfolio and risk
  │    $100M · 3–10% per pair · 30% gross cap · 8 entries/day · no shared legs
  │    VIX / sector-dispersion regime scaling · drawdown and daily-loss kill switch (flattens)
  │    daily mark-to-market; commissions, spreads and impact booked on fill days
  │
  ├─ Costs (per stock, per fill)
  │    $0.002/share commission · half-spread by dollar-ADV bucket · square-root impact on own σ and ADV
  │    general-collateral borrow 25 bp/yr on the short leg · prime-broker carry on the short half
  │
  ├─ Walk-forward: ONE continuous out-of-sample simulation (252-day train / 63-day test grid),
  │    ranker refit per window on that window's train period, positions carried across windows
  │
  └─ Evidence layer
       significance.py: PSR, DSR (32 trials), Newey-West t, Politis-White block bootstrap,
       Lo (2002) adjusted Sharpe, Ledoit-Wolf Sharpe-difference test, PBO (CSCV)
       benchmark.py: Gatev (2006) distance method, t+1 fills, same costs · 200-draw random-pair control
       market-beta attribution · capital utilisation · rejection funnel
```

18 modules in [`pairs_trading/`](pairs_trading/). Entry point: `python -m pairs_trading.main`
(or `pairs-trading` after `pip install -e .`).

## What v32 changed

Each row is a defect the audit confirmed in v31.1 and how v32 handles it. "Flatters" marks
defects that made the old backtest look better than the strategy was.

| Area | v31.1 | v32 |
|---|---|---|
| **Look-ahead** | each trade's final P&L was recorded with the position sizer and the loss-streak cool-off **on its entry day** (flatters) | outcomes reach the sizer and cool-off only after the exit fill; a perturbation test enforces it |
| **Look-ahead** | one-state Kalman without intercept on log prices: β absorbed the price level (true 0.90 read as ≈1.27), and a vendor back-adjustment for a split or dividend after the sample changed every past signal | two-state filter on burn-in-centred log prices; signals are invariant to such back-adjustment (a test enforces it) |
| Signal | entry used an expanding-window z of the Kalman residual; target, stop and time stop used a β-locked z — two different spreads | one β-locked z with reference statistics frozen at the signal, used for every decision |
| Hedge | equal-dollar legs regardless of β | legs weighted $1 : $β; β outside [0.25, 4] is skipped, not clamped |
| Accounting | a trade's whole P&L booked on its exit day (understates volatility and drawdown) | daily mark-to-market; costs on fill days; end-of-data positions force-closed, never dropped |
| Walk-forward | independent 63-day windows; trades still open at a window's end were discarded (flatters) | one continuous simulation with per-window ranker refits; per-window figures are slices of it |
| Sizing | z multiplier applied after the 3–10% clamp, so the strongest signals were vetoed by the 10% limit | multiplier inside the clamp; one quality threshold (0.55) instead of a dead 0.40 pre-filter |
| Entry gates | CUSUM and Hurst gates on 30–90 bars | measured near-random at these lengths (CUSUM rejects 0–8% and Hurst 5–11% of random walks and mean-reverting spreads alike); off by default, kept as flags |
| Re-selection | inconsistent p-value definitions; pair statistics frozen at the 2022 selection | one Bonferroni p-value; statistics re-estimated at every re-selection; opt-in full re-search (`PAIRS_RESELECT=full`) |
| Selection | half-life on the β = 1 spread; share-volume screen on split-adjusted data; negative correlations admitted; a silent screen-free fallback | half-life on the cointegrating spread; point-in-time dollar-volume screen; positive correlation; no fallback; deterministic leg order |
| Costs | effective commission ≈0.09 bp; the same 0.8 bp spread for every stock; impact from a fixed share volume (so it scaled with 1/√price); fund profiles: impact without volatility (its cap bound on every trade), charged on entry only, institutional costs 10× too small (unit error) | per-share commission; half-spread by dollar-ADV bucket; square-root impact on each stock's own σ and dollar ADV, on entry and exit; GC borrow and financing; fund-profile units and impact fixed |
| Data | universe screens on split-adjusted prices (later splits decided membership); partial fetches cached as the study; an unreadable cache was silently refetched and overwritten; last trading day dropped | point-in-time screens; fetch coverage ≥ 90% enforced, retries with backoff, manifest; caches written atomically and never overwritten; inclusive end date |
| Ranker | trained on a different target than the rule it ranks, from features extracted with empty stock data; 8 always-zero inputs; class weighting left the score uncalibrated; a 1,000-episode "RL" loop updated nothing | labels from the actual rule (outcome complete inside the training window); live features; 30 real inputs; prior-corrected probabilities; failures score the base rate; out-of-sample AUC and Brier reported; RL loop removed |
| Benchmarks | Gatev baseline filled on the signal bar at 2.5–5× lower cost than the strategy; 5-draw random control | t+1 fills and the same per-stock cost model; Gatev re-normalisation and crossing exits; 200-draw random control with its distribution; Ledoit-Wolf test of the Sharpe difference |
| Statistics | fixed 10-day bootstrap blocks; DSR = 1.0 when one trial; constant series gave a Sharpe of 10¹⁶ | Politis-White block length; Lo (2002) adjustment; PBO; one Sharpe definition with a zero-variance guard |
| Outputs | publication check scraped a log (could not parse signed numbers, matched integers as substrings); a failed stage still exited 0 | `headline_metrics.json` plus marker check (and `--write`); provenance block in every export; failed stages make the run exit non-zero |

The full record of v32 (and every earlier version) is in [docs/PROGRESS.md](docs/PROGRESS.md).

## Known limitations

These hold for v32 and should be read with any result it produces.

- **Survivorship.** The universe is close to current Russell 3000 membership back-filled
  with prices: of 36 names that failed, delisted or were acquired in 2020–2025, one is
  present. Pairs that broke because a company failed are missing, which flatters a pairs
  strategy. Fixing it needs a point-in-time dataset such as CRSP.
- **Design choices were made on the same data.** Thresholds, gates and the regime rule
  were chosen across 32 versions using 2020–2025. The walk-forward is out of sample for
  pair selection and the ranker, not for those choices. The Deflated Sharpe counts 32
  trials (a lower bound), and `scripts/parameter_sensitivity.py` reports how fragile the
  chosen thresholds are (PBO).
- **Re-selection can drop pairs but not add them** unless `PAIRS_RESELECT=full` (slow).
- **Borrow is general-collateral for every name** (25 bp/yr); hard-to-borrow fees, recalls,
  short rebates and regulatory fees are not modelled.
- **Fills are close-to-close**; no auction, queue or intraday modelling. Capacity is
  reported as average ADV participation rather than simulated.
- **Ranker features include pair statistics estimated on the formation window** that also
  produces its earliest training labels. The ranker only orders same-day candidates, and
  its out-of-sample AUC is reported.
- **The "transformer" sees one 30-feature vector** — a sequence of length one — so it is
  functionally a residual MLP. Its scores are not bit-identical across CPU thread counts
  or devices.
- **Sector features are coarse.** The sector map covers about 315 of 2,542 symbols; the rest
  get neutral sector inputs. Pairs are not restricted to one industry.
- **The 126-day re-selection check has little power.** At n ≈ 87 bars (asymptotic MacKinnon
  p-values) the rule p ≤ 0.30 passes 27% of non-cointegrated pairs and only 32–63% of truly
  cointegrated ones (half-life 14 down to 5 days), so it removes many healthy pairs at every
  re-selection. It is kept as the documented v8 design; `RESEL_RECENT_MAX_P = 1.0` turns it off.
- **The price cache used through v31 was built with a full-sample penny-stock screen**, and
  its fill step also wrote forward-filled prices into rows where the vendor returned none.
  v32 does neither, but a cache built before v32 keeps both until it is re-fetched.
- **"Point-in-time" prices undo splits, not dividends.** The cached closes are dividend-
  adjusted, so early prices are understated by the yield of later dividends (a few percent
  a year for high-yield names) in the $5 price and dollar-volume screens.

Literature context: Do & Faff (2010, *Financial Analysts Journal*; 2012, *Journal of
Financial Research*) find that simple distance-method pairs trading became largely
unprofitable after 2002 once trading costs are counted. That is indirect support for a
negative result here, not a test of this strategy.

## Reproducing

```bash
pip install -r requirements.txt          # Python 3.12; or: pip install -e ".[dev]"
mkdir -p logs outputs

# the study (needs data/marketcap.csv; the price cache is fetched if absent)
python -m pairs_trading.main 2>&1 | tee logs/backtest.log

# publish: fill every marked number in README.md and index.html, then verify them
python scripts/check_published_numbers.py --write
python scripts/make_og_image.py          # social card from the same JSON
cp -r outputs outputs_headline           # keep the headline run: every run rewrites outputs/

# evidence beyond the headline (each run rewrites outputs/; the publishing scripts refuse a
# JSON from a non-default switch unless --allow-variant is given)
python scripts/synthetic_validation.py   # known-answer checks (~4 min)
python scripts/parameter_sensitivity.py  # threshold grid + PBO on the study data (slow)
PAIRS_USE_TRANSFORMER=0 python -m pairs_trading.main > logs/backtest_noml.log 2>&1   # ranker ablation
PAIRS_FILL=open python -m pairs_trading.main > logs/backtest_open.log 2>&1          # fill sensitivity
```

| Switch | Default | Effect |
|---|---|---|
| `PAIRS_SEED` | 42 | seeds Python, NumPy and torch; recorded in every export |
| `PAIRS_USE_TRANSFORMER` | 1 | `0` skips ranker training: classical ranking on the same code path |
| `PAIRS_FILL` | close | `open` fills at the next bar's open instead of its close |
| `PAIRS_RESELECT` | pool | `full` re-runs the complete pair search at every re-selection |
| `PAIRS_ALLOW_PARTIAL_FETCH` | unset | `1` accepts a price fetch covering < 90% of the universe |
| `PAIRS_DEMO_UNIVERSE` | unset | `1` uses an 85-symbol smoke-test universe when `data/marketcap.csv` is absent (does not reproduce the study) |
| `PAIRS_SKIP_REPROCESS` | unset | `1` loads the price cache verbatim |

Inputs: `data/marketcap.csv` (the study universe; required and not redistributed —
the loader stops with instructions rather than substituting another universe),
`data/enhanced_russell_3000_data.pkl` (price cache) and `data/macro_data.pkl` (VIX and
sector ETFs). Outputs go to `outputs/` (JSON exports, `headline_metrics.json`, charts).
`data/`, `logs/` and `outputs/` are git-ignored.

A run exits non-zero if any analysis stage fails; its exports are still written, marked
`"complete": false`, for debugging.

## Testing

```bash
pip install -e ".[dev]"
ruff check .
pytest --cov=pairs_trading                # ~3 min, hermetic: no data files, no network
```

The suite runs the whole pipeline end to end (classical ranking) on a synthetic market
written to a temporary directory in the exact on-disk format of the study, trains and uses
the ranker in a separate test, and tests the engine for causality
(future-perturbation and back-adjustment invariance), accounting (daily P&L reconciles
with trades; mark-to-market telescopes), the trading rule (one z definition, timing,
exposure caps, run-off), the cost model, pair selection, the ranker (calibration,
out-of-sample metrics, as-of features), the statistics (against reference
implementations), the benchmarks, the exports and the publication scripts. CI also runs
the known-answer validation, `pip-audit` on the installed environment, `ruff` and CodeQL;
pandas/NumPy `FutureWarning`s are errors, so a silent behaviour change in a dependency
fails the build.

```
├── pairs_trading/   # the system (main.py is the entry point; synthetic.py is test-only)
├── tests/           # pytest suite
├── scripts/         # publication check, social card, synthetic validation, parameter sensitivity
├── docs/            # PROGRESS.md (complete engineering log) and research notes
├── index.html       # project page
└── data/ logs/ outputs/   # local only (git-ignored)
```

## What this project is not

- **Not a deployable strategy.** It is a framework for finding out whether one exists.
- **Not reinforcement learning.** There is no policy, value function or environment loop;
  v32 deleted a loop that was labelled as training but updated nothing.
- **Not "AI-driven".** The learned component only orders candidates that the classical
  rule has already accepted. In v31.1 its contribution was exactly zero; v32 measures its
  out-of-sample skill directly.

## Version history (highlights)

Full engineering log in [docs/PROGRESS.md](docs/PROGRESS.md) — deliberately unflattering.

| Version | Change |
|---|---|
| v9–v12 | first look-ahead fixes (P&L, pair selection, Kalman β drift) |
| v16–v19 | Kalman spread fixes, β-weighted P&L, PCA residual cointegration, dynamic hold |
| v24–v26.1 | ranker trained and wired in (ranking only); controlled ablation; a label bug that had disabled training |
| v28–v29 | significance layer and baselines; t+1 entry fills (OOS +0.49% → +0.08%/qtr) |
| v30 | leakage audit: survivorship confirmed, selection-clean window tagging |
| v31–v31.1 | pre-launch audit: inverted stop-loss, same-bar exits, future re-selections in the walk-forward and more; OOS −0.28%/qtr |
| v32 | full audit (≈270 confirmed findings): engine, Kalman model, accounting, walk-forward, costs, ranker, benchmarks and outputs rebuilt; synthetic known-answer validation; v31.1 figures withdrawn pending a re-run |

---

*Research project. Not investment advice; no claim of deployable performance.*
