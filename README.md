# Russell 3000 Statistical Arbitrage — Pairs Trading Research

[![CI](https://github.com/NavnoorBawa/russell3000-pairs-trading/actions/workflows/ci.yml/badge.svg)](https://github.com/NavnoorBawa/russell3000-pairs-trading/actions/workflows/ci.yml)
[![CodeQL](https://github.com/NavnoorBawa/russell3000-pairs-trading/actions/workflows/codeql.yml/badge.svg)](https://github.com/NavnoorBawa/russell3000-pairs-trading/actions/workflows/codeql.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-1a1a1a.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-1a1a1a.svg)](LICENSE)

**[Research note (live page) →](https://navnoorbawa.github.io/russell3000-pairs-trading/)** ·
[Paper (PDF)](paper/pairs_study.pdf) ·
[Committed results](results/)

One question, answered as strictly as free data allow: **does a cointegration pairs-trading
strategy on the Russell 3000 have an edge after realistic execution and costs?**

## The finding

The v33 design (same-industry cointegrated pairs among the 500 most liquid point-in-time Russell
3000 members, re-formed every six months, next-day fills, a per-stock cost model)
returned <!--m:main.total_return_pct-->−0.39%<!--/m--> net over July 2023 – December 2025
on <!--m:main.trades-->213<!--/m--> trades (Sharpe <!--m:main.sharpe-->−0.06<!--/m-->, 95%
interval <!--m:significance.main.boot_lo-->−1.29<!--/m-->
to <!--m:significance.main.boot_hi-->+1.16<!--/m-->), indistinguishable from zero, from the Gatev
distance method (Sharpe <!--m:benchmarks.gatev.sharpe-->−0.80<!--/m-->) and from random pairs. The
same rule started in February 2023, the walk-forward, lost money:
Sharpe <!--m:oos.pooled_sharpe-->−1.04<!--/m-->, one-sided 95% upper
bound <!--m:study.dev.facts.oos_ucb-->−0.15<!--/m-->, eight-factor alpha t
= <!--m:study.dev.facts.ff_alpha_oos_t-->−2.25<!--/m-->, though its two-sided interval just includes
zero; <!--m:oos.windows_positive-->4<!--/m--> of <!--m:oos.windows-->11<!--/m--> quarterly windows
were positive (mean <!--m:oos.avg_window_return_pct-->−0.58%<!--/m--> per window, p
= <!--m:significance.oos_windows.p-->0.096<!--/m-->).

No gross edge is detected either. Before costs the trades made
\$<!--m:study.dev.facts.gross_usd_m-->1.52<!--/m-->M
(Sharpe <!--m:study.dev.facts.gross_sharpe-->+0.29<!--/m-->, Newey–West p
= <!--m:study.dev.facts.gross_hac_p-->0.645<!--/m-->),
or <!--m:study.dev.facts.break_even_x-->0.80<!--/m--> times the modelled costs: weighted by
size <!--m:study.dev.facts.sf_gross_bp-->+13.5<!--/m--> bp a trade,
equal-weighted <!--m:study.dev.facts.gross_bp-->−7.9<!--/m--> bp (t
= <!--m:study.dev.facts.gross_t-->−0.25<!--/m-->),
against <!--m:study.dev.facts.cost_bp_notional-->16.9<!--/m--> bp of cost. The evidence layer is
consistent with that: the rule's <!--m:study.dev.facts.decay_form_bp-->+64.7<!--/m--> bp a trade on
the data that selected a pair falls to <!--m:study.dev.facts.decay_oos_bp-->−12.6<!--/m--> bp after
formation; after formation the spreads hit their targets about as often as a random walk's would;
and only <!--m:study.dev.facts.pers_traded_count-->6<!--/m--> of
the <!--m:study.dev.facts.pers_traded_of-->115<!--/m--> traded pairs testable after formation are
still cointegrated, about the base rate of any correlated pair. A second family, Avellaneda–Lee
residual reversion, agrees (Sharpe <!--m:study.residual.sharpe-->−0.28<!--/m-->
over <!--m:study.residual.trades-->10,916<!--/m--> trades). The sample rules out a Sharpe ratio
above <!--m:study.dev.facts.sharpe_ucb-->0.92<!--/m--> (one-sided 95%) but cannot tell 0 from 0.5.
The pre-registered falsification test on 2026 data,
with <!--m:study.dev.facts.ho_power_1-->16<!--/m-->% power against a true Sharpe ratio of 1, is
sealed until its protocol is filed.

Every number in this file and on the page is a marker checked against the run's headline JSON
or the site data built from it (`python scripts/check_published_numbers.py`, which fails on any
mismatch; `--write` fills them).

| Development period, Jul 2023 – Dec 2025 | v33 (this study) | v32 (published 18 Oct 2026) |
|---|---|---|
| Main backtest: net return | <!--m:main.total_return_pct-->−0.39%<!--/m--> | <!--m:study.v32.main.ret_pct-->−0.30%<!--/m--> |
| Main backtest: net Sharpe | <!--m:main.sharpe-->−0.06<!--/m--> | <!--m:study.v32.main.sharpe-->−0.07<!--/m--> |
| Main backtest: trades | <!--m:main.trades-->213<!--/m--> | <!--m:study.v32.main.trades-->161<!--/m--> |
| Walk-forward: net Sharpe | <!--m:oos.pooled_sharpe-->−1.04<!--/m--> | <!--m:study.v32.oos.sharpe-->−0.33<!--/m--> |
| Gross bp per trade, equal-weighted (t) | <!--m:study.dev.facts.gross_bp-->−7.9<!--/m--> (<!--m:study.dev.facts.gross_t-->−0.25<!--/m-->) | <!--m:study.v32.gross_bp-->+11.4<!--/m--> (<!--m:study.v32.gross_t-->0.37<!--/m-->) |
| Cost bp per trade | <!--m:study.dev.facts.cost_bp-->16.1<!--/m--> | <!--m:study.v32.cost_bp-->12.5<!--/m--> |
| Gatev distance method: Sharpe | <!--m:benchmarks.gatev.sharpe-->−0.80<!--/m--> | <!--m:study.v32.gatev_sharpe-->+0.07<!--/m--> |
| Percentile among <!--m:benchmarks.random_control.n_draws-->200<!--/m--> random-pair portfolios | <!--m:benchmarks.random_control.strategy_percentile-->37<!--/m--> | <!--m:study.v32.random_percentile-->28<!--/m--> |
| Second family (Avellaneda–Lee): net Sharpe [95%] | <!--m:study.residual.sharpe-->−0.28<!--/m--> [<!--m:study.residual.lo-->−1.47<!--/m-->, <!--m:study.residual.hi-->+0.93<!--/m-->] | not run |

v32 is kept as the published record and runs frozen, without a test, as the descriptive arm
of the holdout. The v33 design changed seven fields of v32, each made after v32's development
results on this same period were seen and fixed before any v33 run: point-in-time index
membership instead of today's largest stocks, the 500 most liquid names instead of 300, pairs within one Fama–French 49 industry, a full re-selection every 126
trading days instead of re-testing the 2022 pool, the regime gate off, no learned ranker, and one
0.38% borrow fee instead of borrow plus a double-counted financing spread
([the site's design section](https://navnoorbawa.github.io/russell3000-pairs-trading/#method)
gives the reason for each).

## Why no edge is detected

The evidence layer (`pairs_trading/anatomy.py`, `scripts/anatomy_of_the_null.py`) takes the
null apart trade by trade, from the committed run:

- **Costs exceed the gross P&L.** Paper P&L at the signal closes was
  \$<!--m:study.dev.facts.sf_paper_usd_k-->1,693.3<!--/m-->k, gross after the next-day fills
  \$<!--m:study.dev.facts.gross_usd_k-->1,520.1<!--/m-->k, modelled costs
  \$<!--m:study.dev.facts.cost_usd_k-->1,907.4<!--/m-->k (<!--m:study.dev.facts.impact_share_pct-->67.4<!--/m-->%
  market impact): net P&L breaks even only at <!--m:study.dev.facts.break_even_x-->0.80<!--/m-->×
  the modelled costs. The gross return itself is indistinguishable from zero and from the cost.
- **The edge is in-sample only.** The same rule on the
  same <!--m:study.dev.facts.decay_pairs-->130<!--/m--> traded pairs
  earns <!--m:study.dev.facts.decay_form_bp-->+64.7<!--/m--> bp a trade on their formation windows
  (t = <!--m:study.dev.facts.decay_form_t-->8.35<!--/m-->)
  and <!--m:study.dev.facts.decay_oos_bp-->−12.6<!--/m--> bp after formation (t
  = <!--m:study.dev.facts.decay_oos_t-->−1.17<!--/m-->). "After formation" is development data; this
  project keeps "out of sample" for the 2026 test.
- **After formation the spreads behave like random
  walks.** <!--m:study.dev.facts.er_targets-->72<!--/m--> trades hit the profit target first
  and <!--m:study.dev.facts.er_stops-->77<!--/m--> the stop; a random-walk spread
  expects <!--m:study.dev.facts.er_rw_expected-->65.9<!--/m--> targets, a spread reverting at its
  formation half-life <!--m:study.dev.facts.er_ou_expected-->121.0<!--/m-->. Of the traded pairs'
  half-lives after formation, <!--m:study.dev.facts.hl_oos_above_max_pct-->60.8<!--/m-->% exceed
  the rule's 25-day maximum.
- **Cointegration persists only at the base rate.** On a broader universe than v33's (the 300 most
  liquid names of 2022, any industry, one-year windows),
  of <!--m:study.dev.facts.pers_of-->7,334<!--/m--> pairs cointegrated in one year of
  2020–2024, <!--m:study.dev.facts.pers_count-->370<!--/m--> were cointegrated the next,
  against <!--m:study.dev.facts.pers_expected-->403.4<!--/m--> at that year's base rate, itself
  close to the test's 5% level (Clegg 2014 found the same); of the traded
  pairs, <!--m:study.dev.facts.pers_traded_count-->6<!--/m-->
  of <!--m:study.dev.facts.pers_traded_of-->115<!--/m-->.
- **Costs and capacity only make it worse.** Each declared scenario re-runs the whole backtest
  (`scripts/cost_sensitivity.py`; trade counts differ because sizes are a share of equity and the
  30% gross cap binds): impact Y = 1.0 gives a Sharpe
  of <!--m:study.dev.cost_sensitivity.scenarios.impact_1_0.full.sharpe-->−0.70<!--/m-->, borrow at
  3% <!--m:study.dev.cost_sensitivity.scenarios.borrow_3.full.sharpe-->−0.71<!--/m-->, a \$5B
  book <!--m:study.dev.cost_sensitivity.scenarios.capital_5b.full.sharpe-->−1.50<!--/m--> (an order
  the closing auction could not absorb, so that row understates the cost).

## The pre-registered 2026 test

**Status: sealed.** No daily price history of any security for dates after 2025-12-31 has been
requested, and the fetch code refuses such a request (`study_config.assert_unsealed`) unless
`PAIRS_UNSEAL` names the registered commit; the commitment is that only the runbook sets it. The
pre-registration will be committed and pushed as `docs/PREREGISTRATION.md` before any 2026
daily price is fetched; until then it is a draft. `scripts/run_holdout.sh` then runs each arm
once from that commit on the <!--m:study.dev.facts.ho_days-->200<!--/m--> trading days from
2026-01-02 to 2026-10-19, records every attempt, and publishes the result whatever it is.

That period has already ended, and the project was developed during it (versions 8 to 33). The
test is sealed, not prospective: the project's code and caches hold no daily 2026 prices of the
traded securities, but the designers' general knowledge of 2026 markets cannot be sealed. The
2026 information the project did receive (the latest quote in the price vendor's responses, the
market values behind the v32 universe file, identity data, factor files) is listed under Known
limitations and in the pre-registration.

| Arm | Strategy | Role |
|---|---|---|
| S1 | v33 pairs, the design above | H1: net mean return > 0 |
| S2 | Avellaneda–Lee sector-ETF residual reversion, published parameters | H2: net mean return > 0 |
| S3 | v32 as published, frozen | reported, tested in no family (its universe is ranked on market values inside 2026) |

Test: one-sided Newey–West t on the daily net returns, Holm-adjusted across H1 and H2 at a
familywise 5%. Power, stated in advance from the development returns' shape: a test at Holm's first
step detects with 80% probability only an annualised Sharpe ratio of
about <!--m:study.dev.facts.ho_mde_025-->2.96<!--/m-->,
with <!--m:study.dev.facts.ho_power_1-->16<!--/m-->% power against a true Sharpe of 1. The holdout
is a falsification check: it can reject a large edge, but it cannot confirm a small one.

## What is in the repository

| Path | What it holds |
|---|---|
| [`pairs_trading/`](pairs_trading/) | The system: study profiles and calendars (`study_config.py`), the point-in-time universe (`universe.py`), data and price anchoring (`data_processor.py`), pair selection with an exact numpy Engle–Granger (`pair_selector.py`, `fast_coint.py`), the engine (`trading_system.py`), costs (`transaction_costs.py`), significance, power and data-snooping tests (`significance.py`, `power.py`, `snooping.py`), baselines (`benchmark.py`), the evidence layer (`anatomy.py`, `evidence.py`) and the second family (`residual_statarb.py`) |
| [`scripts/`](scripts/) | Runbooks (`run_dev_studies.sh`, `run_holdout.sh`), the evidence scripts, the holdout evaluator, the trial registry, the site and paper builders and the publication checker |
| [`results/`](results/) | Every published run, with its provenance: `v33_dev/` (this study, with `anatomy.json` and `cost_sensitivity.json`), `residual_dev/` (S2), `validation/`, `v32_dev/` (the published v32 run), `variant_family/` (the declared family; its run is in progress) and `trial_registry.jsonl` (every trial whose result was seen) |
| [`reference/`](reference/) | IWV N-PORT holdings snapshots, the CUSIP-to-ticker map and the industry map, with how each was built and checked |
| [`docs/`](docs/) | `PROGRESS.md` (the full engineering log, deliberately unflattering), `EXECUTION_COSTS.md`, `FREE_RESOURCES.md` |
| `index.html`, [`assets/`](assets/) | The research note; `assets/study.json` is built from `results/` by `scripts/build_site_data.py` |
| [`paper/`](paper/) | The Typst paper and its committed PDF, built from the same data as the page (`scripts/build_paper.py`) |
| [`tests/`](tests/) | The test suite (below) |

## Reproduce

```bash
# the environment pinned in requirements.txt (Python 3.12; CPU torch as in CI)
python3.12 -m venv .venv
.venv/bin/pip install --no-deps torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -r requirements.txt

# the development-period studies behind the published numbers, in order:
# main, anatomy, costs, residual, variants, validation, publish (each logs to logs/dev_<step>.log)
PYTHON=.venv/bin/python bash scripts/run_dev_studies.sh
PYTHON=.venv/bin/python bash scripts/run_dev_studies.sh main anatomy     # or any steps

# the site's data, and the check of every marked number in README.md and index.html
.venv/bin/python scripts/build_site_data.py              # results/v33_dev -> assets/study.json
.venv/bin/python scripts/check_published_numbers.py      # against results/v33_dev/headline_metrics.json

# the pre-registered 2026 test: once, from a full clone at the registered commit
PYTHON=.venv/bin/python bash scripts/run_holdout.sh
```

The runbooks clear every `PAIRS_*` switch of the calling shell, set `PYTHONHASHSEED=0`, refuse
an environment that differs from `requirements.txt` (`scripts/check_pins.py`) or uncommitted
code, and record the commit, the design and calendar hashes and the price cache's sha256 in
every export. A single run is `python -m pairs_trading.main --profile v33 --calendar dev
--output-dir outputs/v33_dev`. Prices come from Yahoo's chart API and are cached under `data/`
with a fetch manifest; a later fetch will not match the cached data bit for bit, because vendors
revise history. `data/`, `logs/` and `outputs/` are git-ignored.

## Built with free data only

Every input is free and needs no account: Yahoo's chart API for prices, the SEC's N-PORT filings of
the iShares Russell 3000 ETF for point-in-time membership, OpenFIGI for identifiers, SEC SIC codes
for industries, the Kenneth French library for factors, FRED for T-bill rates.
[docs/FREE_RESOURCES.md](docs/FREE_RESOURCES.md) lists what each source provided and what free data
could not provide (delisted histories, tick data, borrow fees), and how the study bounds or
discloses each gap; the survivorship gap, for one, is measured at every formation
(<!--m:study.dev.facts.gap_first_pct-->3.33<!--/m-->% of index weight at the
first, <!--m:study.dev.facts.gap_last_pct-->1.08<!--/m-->% at the last) and split by the outcome
of each symbol's fetch, from the price-fetch manifest published with the run
(`results/v33_dev/price_fetch_manifest.json`). Of the requested symbols,
the vendor served price history for <!--m:study.dev.facts.cached_pct-->82.2<!--/m-->% and answered
HTTP 404 for <!--m:study.dev.facts.not_found_pct-->14.2<!--/m-->%.

## Validation and tests

`scripts/synthetic_validation.py` runs the real engine, with its full cost model, on synthetic
markets whose answer is known (<!--m:study.validation.seeds-->10<!--/m--> markets per scenario,
`results/validation/`):

| Check | What must happen | Result |
|---|---|---|
| Planted cointegrated pairs (OU spreads, half-life 5–14 days) | a large positive gross edge | <!--m:study.validation.edge.mean_bp-->+82.6<!--/m--> bp gross per trade (t = <!--m:study.validation.edge.t-->34.8<!--/m-->) |
| Correlated, not cointegrated pairs forced into the universe | no edge; a positive mean would be look-ahead | <!--m:study.validation.forced_null.mean_bp-->+1.7<!--/m--> bp (t = <!--m:study.validation.forced_null.t-->0.65<!--/m-->) |
| Kalman hedge ratio against the true slope | recover it | median absolute error <!--m:study.validation.hedge_ratio.median_abs_error-->0.032<!--/m--> |
| Pair selection among unrelated names | find the planted pairs; admit at most 5% of the others | recall <!--m:study.validation.selection.recall-->1.000<!--/m-->; worst market <!--m:study.validation.selection.worst_fp_rate-->0.0296<!--/m--> |

```bash
pip install -e ".[dev]"
ruff check .
pytest --cov=pairs_trading                # hermetic: no data files, no network
```

The suite runs the whole pipeline on a synthetic market in the study's on-disk format and tests
the engine for causality (every decision dated on or before T is unchanged when all data after T
are replaced; signals are invariant to vendor back-adjustment), accounting, the trading rule, the
cost model, the point-in-time universe and its sealing, the statistics against reference
implementations, the evidence layer, the holdout protocol, the exports and the publication
scripts; it also checks that `assets/study.json` is current and that every published number
matches the run. CI runs the suite on the pinned and the latest environments, the known-answer
validation, `ruff`, `pip-audit` and CodeQL.

## Known limitations

These are the site's threats to validity, in the same order; the page gives each one's direction
and size.

- **Survivorship is measured, not removed.** Point-in-time members without free price history
  cannot be traded; their index weight is reported at every formation, split by fetch outcome:
  mostly names the vendor no longer serves (HTTP 404), largely acquired or delisted since, the
  rest failed fetches and failed data checks. Among the 500 heaviest members at the first
  formation they include takeover targets and SVB Financial, which failed inside the
  walk-forward. The gap probably flatters a convergence strategy.
- **Design choices were made on the same data.** 33 versions on 2020–2025; the deflated Sharpe's
  32 trials are a lower bound; v33's changes were chosen after v32's results on this same period
  were seen; and an exploratory v33 run was seen before the published one (it is in the trial
  registry). The pre-registered holdout and the declared variant family address it.
- **The 2026 test is sealed, not prospective.** The test period ended before the pre-registration
  is filed, and the project was developed during it; the designers' general knowledge of 2026
  markets cannot be sealed.
- **The path depends on the start date.** Sizing is a share of equity and the 30% cap binds, so
  the same rule on the same days gives different trades from different start dates: on the days
  they share, the main backtest and the walk-forward have Sharpe ratios a point apart, a spread
  one path's bootstrap interval does not include.
- **Vendor prices carry corporate actions after the window.** Yahoo back-applies later splits
  and dividends to the whole history; price levels are anchored to N-PORT's price at each snapshot
  date, and returns are unaffected.
- **Some inputs are dated 2026.** Identity data (identifier map, SIC codes, listing venue), the
  French factor files, FRED rates and the v32 universe file were fetched in 2026, and the price
  API's responses carry the latest quote in their metadata (not read). Two rules of the industry
  map use 2026 information (a ticker missing from the SEC's 2026 company list has no industry; a
  name first held in 2026 needs to be among the 3,000 largest of 18 October 2026); they are
  disclosed in the pre-registration. None of these inputs is a 2026 daily price, factors are
  truncated at each calendar's end, and no strategy reads them.
- **The frozen v32 arm's universe looks ahead into 2026.** It is ranked on market values of
  18 October 2026, which is why S3 is descriptive only.
- **Renamed securities can look delisted.** A ticker change with a new CUSIP is remapped through
  N-PORT's reported tickers, issuer successions and price checks.
- **Borrow is one fee for every name.** Specials and recalls are not modelled; 1% and 3% stress
  runs bound the effect.
- **Fills are close-to-close.** The closing auction is assumed, with no queue, auction-volume or
  intraday model; participation is measured against full-day volume, so the largest books in the
  capacity scenarios could not be filled at the close; impact is stressed at Y = 0.6 and 1.0.
- **Cost parameters are published averages, not measurements.** No free tick or quote data:
  spreads and impact come from published estimates.
- **Cost scenarios change the trades.** Each re-run is a new path, so the headline trades are
  also re-priced under every scenario.
- **Hedge ratios below one leave market exposure.** The book carries a small market loading,
  reported with an eight-factor attribution.
- **The main backtest and the walk-forward overlap.** With no model to refit they are one rule
  from two start dates; the holdout is the independent test.
- **One period, one regime.** 30 months with T-bills near 5%, and one path; returns are not yet
  split by volatility or dispersion regime.
- **The random-pair control trades a different rule.** Random pairs run through the Gatev rule,
  not this engine.

## What this project is not

- **Not a deployable strategy.** It is a framework for finding out whether one exists, and its
  answer for this design, on 2023–2025, is: no detectable edge.
- **Not machine learning.** v33 ranks candidates by signal strength and pair quality; a learned
  ranker showed no skill in v32 and is only a declared variant.
- **Not investment advice.** Hypothetical, backtested results on notional capital.

## Version history (highlights)

Full engineering log in [docs/PROGRESS.md](docs/PROGRESS.md).

| Version | Change |
|---|---|
| v9–v12 | first look-ahead fixes (P&L, pair selection, Kalman β drift) |
| v16–v19 | Kalman spread fixes, β-weighted P&L, PCA residual cointegration, dynamic hold |
| v24–v26.1 | ranker trained and wired in (ranking only); controlled ablation; a label bug that had disabled training |
| v28–v29 | significance layer and baselines; t+1 entry fills |
| v30 | leakage audit: survivorship confirmed, selection-clean window tagging |
| v31–v31.1 | pre-launch audit: inverted stop-loss, same-bar exits, future re-selections in the walk-forward; results withdrawn |
| v32 | full audit (about 270 confirmed findings) and rebuild of the engine, accounting, walk-forward, costs, ranker, benchmarks and outputs; synthetic known-answer validation; study run of 18 Oct 2026: no detectable edge. Kept as the published record and the frozen holdout arm |
| v33 | the design to be pre-registered: point-in-time universe, same-industry pairs, full re-formation, no regime gate or ranker, one borrow fee; the evidence layer, a second strategy family, the trial registry and the sealed 2026 holdout. Development run of 21 Oct 2026: no detectable edge |

---

*Research project. Not investment advice; no claim of deployable performance.*
