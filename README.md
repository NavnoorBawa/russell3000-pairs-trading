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
= <!--m:study.dev.facts.ff_alpha_oos_t-->−2.25<!--/m-->, though the Sharpe ratio's two-sided
bootstrap interval (<!--m:significance.oos_daily.boot_lo-->−2.09<!--/m--> to <!--m:significance.oos_daily.boot_hi-->+0.05<!--/m-->) just includes zero; <!--m:oos.windows_positive-->4<!--/m--> of <!--m:oos.windows-->11<!--/m--> quarterly windows
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

The search was tested too. Of <!--m:study.dev.snooping.results.n-->38<!--/m--> variants of the
design declared before any ran (a <!--m:study.dev.snooping.grid_points-->27<!--/m-->-point grid of
the entry, exit and stop thresholds and <!--m:study.dev.snooping.toggles-->11<!--/m--> design
toggles), <!--m:study.dev.snooping.results.positive-->7<!--/m--> have a positive Sharpe ratio
(best <!--m:study.dev.snooping.results.sharpe_best-->+0.21<!--/m-->,
median <!--m:study.dev.snooping.results.sharpe_median-->−0.40<!--/m-->). None beats cash, even
before the search is allowed for (best t = <!--m:study.dev.snooping.results.spa_zero.best_t-->0.38<!--/m-->;
Hansen's SPA p = <!--m:study.dev.snooping.results.spa_zero.p-->0.964<!--/m-->, White's Reality Check
p = <!--m:study.dev.snooping.results.spa_zero.rc_p-->0.977<!--/m-->; the Romano–Wolf stepdown
rejects <!--m:study.dev.snooping.results.rw_rejected-->0<!--/m-->), nor the distance method on a
Sharpe scale (SPA p = <!--m:study.dev.snooping.results.spa_gatev_unit_vol.p-->0.489<!--/m-->). The
variant that is best on one half of the days ranks below the median on the other half
in <!--m:study.dev.snooping.results.pbo_pct-->79.4<!--/m-->% of splits, where a ranking without
information would do so in half, and its Sharpe ratio there
averages <!--m:study.dev.snooping.results.pbo_is_best_oos_sharpe-->−0.87<!--/m-->
against <!--m:study.dev.snooping.results.pbo_median_oos_sharpe-->−0.53<!--/m--> for the median
variant: choosing parameters on this family would overfit. Deflated with the family's effective number of
trials (<!--m:study.dev.snooping.results.effective_rank-->13.7<!--/m-->, rounded up
to <!--m:study.dev.snooping.results.dsr.n_trials-->14<!--/m-->) and its own Sharpe dispersion, the
best variant's deflated Sharpe ratio is <!--m:study.dev.snooping.results.dsr_best.dsr_pct-->13.5<!--/m-->%
and the design's <!--m:study.dev.snooping.results.dsr.dsr_pct-->6.3<!--/m-->%. The headline is also a
favourable path of the rule: started on each of <!--m:study.dev.facts.start_matched_of-->11<!--/m-->
later dates a month apart, the same rule has the lower Sharpe ratio on its own days than the
published run in <!--m:study.dev.facts.start_matched_wins-->10<!--/m--> (median
gap <!--m:study.dev.facts.start_matched_gap_median-->0.51<!--/m-->), and on
the <!--m:study.dev.facts.start_common_days-->397<!--/m--> days all twelve share the published run
ranks <!--m:study.dev.facts.start_common_rank-->3<!--/m-->rd
(median <!--m:study.dev.facts.start_common_sharpe_median-->−0.47<!--/m-->).
The pre-registered falsification test on 2026 data,
with <!--m:study.dev.facts.ho_power_1-->16<!--/m-->% power against a true Sharpe ratio of 1, stated
in advance, was run once on 2026-10-26: neither tested arm rejects zero (Holm
p <!--m:study.holdout.arms.0.p_holm-->0.955<!--/m--> for H1 and <!--m:study.holdout.arms.1.p_holm-->0.955<!--/m--> for H2).

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

v32 is kept as the published record and ran frozen, without a test, as the descriptive arm
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
- **Cointegration persists only at the base rate.** On a wider pair set than v33's (every pair of the 300
  most liquid names of 2022, any industry, one-year windows),
  of <!--m:study.dev.facts.pers_of-->7,334<!--/m--> pairs cointegrated in one year of
  2020–2024, <!--m:study.dev.facts.pers_count-->370<!--/m--> were cointegrated the next,
  against <!--m:study.dev.facts.pers_expected-->403.4<!--/m--> at that year's base rate, itself
  close to the test's 5% level (on S&P 500 constituents, Clegg 2014 finds that the evidence does
  not support persistence either); of the traded pairs, <!--m:study.dev.facts.pers_traded_count-->6<!--/m-->
  of <!--m:study.dev.facts.pers_traded_of-->115<!--/m-->. On the strategy's own candidate pairs
  (the same-industry pairs of the first formation) the pooled rate
  is <!--m:study.dev.facts.pers_s1_pct-->5.18<!--/m-->% against a base rate
  of <!--m:study.dev.facts.pers_s1_expected_pct-->5.55<!--/m-->%
  (z = <!--m:study.dev.facts.pers_s1_z-->−0.55<!--/m-->).
- **Costs and capacity only make it worse.** Each declared scenario re-runs the whole backtest
  (`scripts/cost_sensitivity.py`; trade counts differ because sizes are a share of equity and the
  30% gross cap binds): impact Y = 1.0 gives a Sharpe
  of <!--m:study.dev.cost_sensitivity.scenarios.impact_1_0.full.sharpe-->−0.70<!--/m-->, borrow at
  3% <!--m:study.dev.cost_sensitivity.scenarios.borrow_3.full.sharpe-->−0.71<!--/m-->, a \$5B
  book <!--m:study.dev.cost_sensitivity.scenarios.capital_5b.full.sharpe-->−1.50<!--/m--> (an order
  the closing auction could not absorb, so that row understates the cost).

## The pre-registered 2026 test

**Status: run once, on 2026-10-26. Neither null hypothesis is rejected.** The pre-registration,
[`docs/PREREGISTRATION.md`](https://github.com/NavnoorBawa/russell3000-pairs-trading/blob/7c7d3f904ec643b9a9dc658c2aa46bad506cc3a5/docs/PREREGISTRATION.md),
was committed alone and pushed as commit `7c7d3f9` before any daily price history of a security
for dates after 2025-12-31 was fetched into the project (network checks that asked for one stock's
five-day chart discarded the answer unread). The record that no such price history was fetched begins with the
repository's first commit (2026-06-12, version 25): every committed version of the fetch code ended its
requests at 2025-12-31 until the 2026 calendar was added. Versions 8 to 24, developed from
2026-02-20, left no code or session logs; only the engineering log covers them, and it records
their price data ending on 2025-12-30. `scripts/run_holdout.sh` then ran every arm once from
a fresh full clone at that commit, in one attempt. The exports, the evaluation, the membership,
the price-fetch manifest and the logs are in `results/holdout2026/`; the attempt's lines are in
`results/trial_attempts.jsonl` and the trial's registry entry, `holdout2026`, is in
`results/trial_registry.jsonl`.

| Arm | Hypothesis | Net return | Net Sharpe [95% interval] | One-sided p | Holm p | Decision |
|---|---|---:|---:|---:|---:|---|
| S1, v33 pairs | H1 | <!--m:study.holdout.arms.0.ret_pct-->+0.08<!--/m-->% | <!--m:study.holdout.arms.0.sharpe-->+0.05<!--/m--> [<!--m:study.holdout.arms.0.lo-->−1.81<!--/m-->, <!--m:study.holdout.arms.0.hi-->+1.83<!--/m-->] | <!--m:study.holdout.arms.0.p_one_sided-->0.478<!--/m--> | <!--m:study.holdout.arms.0.p_holm-->0.955<!--/m--> | not rejected |
| S2, Avellaneda–Lee | H2 | <!--m:study.holdout.arms.1.ret_pct-->−1.59<!--/m-->% | <!--m:study.holdout.arms.1.sharpe-->−0.27<!--/m--> [<!--m:study.holdout.arms.1.lo-->−2.36<!--/m-->, <!--m:study.holdout.arms.1.hi-->+1.81<!--/m-->] | <!--m:study.holdout.arms.1.p_one_sided-->0.608<!--/m--> | <!--m:study.holdout.arms.1.p_holm-->0.955<!--/m--> | not rejected |
| S3, v32 frozen | none (descriptive) | <!--m:study.holdout.arms.2.ret_pct-->−0.48<!--/m-->% | <!--m:study.holdout.arms.2.sharpe-->−0.41<!--/m--> [<!--m:study.holdout.arms.2.lo-->−1.48<!--/m-->, <!--m:study.holdout.arms.2.hi-->+1.30<!--/m-->] | <!--m:study.holdout.arms.2.p_one_sided-->0.690<!--/m--> | — | not tested |

Over the <!--m:study.holdout.arms.0.days-->200<!--/m--> trading days from 2026-01-02 to
2026-10-19 neither tested arm earns a mean daily net return distinguishable from zero. The test
had <!--m:study.dev.facts.ho_power_1-->16<!--/m-->% power against a true Sharpe ratio of 1,
stated before the run, so not rejecting the nulls is not evidence of zero edge: the test rules out
Sharpe ratios above <!--m:study.holdout.arms.0.ucb-->1.64<!--/m--> for S1
and <!--m:study.holdout.arms.1.ucb-->1.38<!--/m--> for S2 (one-sided 95% bounds).

That period had ended before the filing, and the project was developed during it (versions 8 to
33). The test is sealed, not prospective: before the filing the project's code and caches held no
daily 2026 prices of the traded securities, but the designers' general knowledge of 2026 markets
cannot be sealed. The
2026 information the project did receive (each security's latest price and 52-week high and low
in the price vendor's responses, the market values and last sale prices of the stock screener
behind the v32 universe file, identity data, factor files that include the short-term reversal
factor, and the rate, VIX and industry series, ETF pages, index changes, short-interest and ticker
lists that surveys of free
data sources downloaded) is listed under Known limitations and in the pre-registration. The
project's working storage, caches and raw downloads included, was lost when its
container was recycled, by 2026-10-22 at 17:29 UTC; the pre-registration says what was lost and how the one untracked input
the holdout reads, the v32 universe file, was rebuilt with the same symbols.

| Arm | Strategy | Role |
|---|---|---|
| S1 | v33 pairs, the design above | H1: net mean return > 0 |
| S2 | Avellaneda–Lee sector-ETF residual reversion, published parameters | H2: net mean return > 0 |
| S3 | v32 as published, frozen | reported, tested in no family (its universe is ranked on market values inside 2026) |

Test: one-sided Newey–West t on the daily net returns, Holm-adjusted across H1 and H2 at a
familywise 5%. Power, stated in advance from the shape of S1's development returns: a test at Holm's first
step detects with 80% probability only an annualised Sharpe ratio of
about <!--m:study.dev.facts.ho_mde_025-->2.96<!--/m-->,
with <!--m:study.dev.facts.ho_power_1-->16<!--/m-->% power against a true Sharpe of 1. The holdout
is a falsification check: it can reject a large edge, but it cannot confirm a small one.

## What is in the repository

| Path | What it holds |
|---|---|
| [`pairs_trading/`](pairs_trading/) | The system: study profiles and calendars (`study_config.py`), the point-in-time universe (`universe.py`), data and price anchoring (`data_processor.py`), pair selection with an exact numpy Engle–Granger (`pair_selector.py`, `fast_coint.py`), the engine (`trading_system.py`), costs (`transaction_costs.py`), significance, power and data-snooping tests (`significance.py`, `power.py`, `snooping.py`), baselines (`benchmark.py`), the evidence layer (`anatomy.py`, `evidence.py`) and the second family (`residual_statarb.py`) |
| [`scripts/`](scripts/) | Runbooks (`run_dev_studies.sh`, `run_holdout.sh`), the evidence scripts, the holdout evaluator, the trial registry, the site and paper builders and the publication checker |
| [`results/`](results/) | Every published run, with its provenance: `v33_dev/` (this study, with `anatomy.json`, `cost_sensitivity.json` and `robustness.json`), `residual_dev/` (S2), `validation/`, `v32_dev/` (the published v32 run), `variant_family/` (the declared family of variants, its runs and the data-snooping tests), `holdout2026/` (the pre-registered 2026 test: the three arms' exports, `evaluation.json`, the membership, the price-fetch manifest and the attempt's logs), `rehearsal2025/` and `rehearsal2025b/` (the two scripted dress rehearsals of the runbook, on 2025 data), `trial_attempts.jsonl` (every attempt of the runbook) and `trial_registry.jsonl` (the registered trials; the page's Section 7 lists the runs it does not hold) |
| [`reference/`](reference/) | IWV N-PORT holdings snapshots, the CUSIP-to-ticker map and the industry map, with how each was built and checked |
| [`docs/`](docs/) | `PROGRESS.md` (the full engineering log, deliberately unflattering), `EXECUTION_COSTS.md`, `FREE_RESOURCES.md` |
| `index.html`, [`assets/`](assets/) | The research note; `assets/study.json` is built from `results/` by `scripts/build_site_data.py`. The page opens with the answer: an interval chart of every Sharpe ratio it rests on (`scripts/build_hero.py`) and the key findings, each linked to its evidence. Any number on it can be checked against its data in the browser (`assets/verify.js`, by the same rule as `scripts/check_published_numbers.py`); every cross-reference is a link (`scripts/link_refs.py`); Section 1 draws the pre-registration's timeline (`scripts/build_prereg_timeline.py`); tables read as cards on phones and copy or export as CSV (`assets/tables.js`). Without JavaScript it shows the paper's figures. Its fonts are subsets of IBM Plex, renamed as the font licence requires (`scripts/build_fonts.py`, `assets/fonts/README.md`) |
| [`paper/`](paper/) | The Typst paper and its committed PDF, built from the same data as the page (`scripts/build_paper.py`) |
| [`tests/`](tests/) | The test suite (below) |

## Reproduce

```bash
# the environment pinned in requirements.txt (Python 3.12; CPU torch as in CI)
python3.12 -m venv .venv
.venv/bin/pip install --no-deps torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -r requirements.txt

# a fresh run of the development-period studies, beside the published ones: main, anatomy,
# costs, residual, variants, validation, publish, robustness, into results/v33_dev_repro/
# (no trial registered; about two hours on four cores with 16 GB of memory, most of it the
# variant family; each step logs to logs/v33_dev_repro_<step>.log)
RUN=v33_dev_repro PYTHON=.venv/bin/python bash scripts/run_dev_studies.sh
RUN=v33_dev_repro PYTHON=.venv/bin/python bash scripts/run_dev_studies.sh main anatomy   # or any steps

# its values beside the published ones (the 'refetch' section of a preview study.json)
.venv/bin/python scripts/build_site_data.py --refetch v33_dev_repro --out /tmp/study.json

# the site's data, the drift table, and the check of every marked number in README.md and index.html
.venv/bin/python scripts/build_site_data.py              # results/ -> assets/study.json
.venv/bin/python scripts/build_drift_table.py            # the table below, from assets/study.json
.venv/bin/python scripts/check_published_numbers.py      # against results/v33_dev/headline_metrics.json

# the pre-registered 2026 test is spent: scripts/run_holdout.sh refuses to run it again
```

The runbooks clear every `PAIRS_*` switch of the calling shell, set `PYTHONHASHSEED=0`, refuse
an environment that differs from `requirements.txt` (`scripts/check_pins.py`) or uncommitted
code, and record the commit, the design and calendar hashes and the price cache's sha256 in
every export. A single run is `python -m pairs_trading.main --profile v33 --calendar dev
--output-dir outputs/v33_dev`. Prices come from Yahoo's chart API and are cached under `data/`
with a fetch manifest; a later fetch will not match the cached data bit for bit, because vendors
revise history. `data/`, `logs/` and `outputs/` are git-ignored. The default `RUN=v33_dev` is the
original publication path: it would write over the committed `results/v33_dev/`,
`results/variant_family/` and `results/validation/`, so it refuses to start while their trials
are registered, and `scripts/robustness_checks.py` refuses a price cache that is not the one the
run recorded.

### The run again, on prices fetched afresh

The price and macro caches the development run pinned (`sha256 3a9a93cc…a7be`) were lost with
the working storage by 22 October 2026, so its numbers cannot be rebuilt from that exact input.
The same design, calendar and steps were run again, from the main backtest to the robustness
checks, on prices fetched afresh: `results/v33_dev_refetch/` (price cache `sha256 ca8a39e6…51b6`),
with its fetch manifest, a fingerprint of every symbol's price series (`price_cache_hashes.json`,
written by `scripts/hash_cache.py`) and the commit of each part (`PROVENANCE.md`).

Every headline number of the main backtest, the walk-forward and the baselines agrees with the
published one to the precision the page shows. The table lists those numbers, the evidence layer's
main numbers and every other quoted value that moved: of its <!--m:study.refetch.rows_n-->111<!--/m--> rows, <!--m:study.refetch.rows_moved-->55<!--/m--> moved and <!--m:study.refetch.rows_same-->56<!--/m--> agree. The
moves are small where a number pools many trades and large where it rests on one path: <!--m:study.refetch.variants_moved-->3<!--/m--> of the <!--m:study.dev.snooping.results.n-->38<!--/m-->
declared variants moved by <!--m:study.refetch.variants_move_min-->0.41<!--/m--> to <!--m:study.refetch.variants_move_max-->0.51<!--/m--> in Sharpe ratio, because under the 30% exposure cap a small
change in one price can change which later signals are filled. A single configuration's Sharpe ratio
is therefore sensitive to revisions of the prices, beyond what its bootstrap interval, which
resamples one path, shows. The learned ranker becomes the family's best variant (Sharpe <!--m:study.refetch.values.dev.snooping.results.sharpe_best-->+0.51<!--/m-->,
against <!--m:study.dev.snooping.results.sharpe_best-->+0.21<!--/m--> for the published best).

No conclusion about the strategy changes: no variant beats cash after the search (SPA p = <!--m:study.refetch.values.dev.snooping.results.spa_zero.p-->0.880<!--/m-->,
Romano–Wolf rejects <!--m:study.refetch.values.dev.snooping.results.rw_rejected-->0<!--/m-->) or the distance method on a Sharpe scale (SPA p = <!--m:study.refetch.values.dev.snooping.results.spa_gatev_unit_vol.p-->0.421<!--/m-->), and choosing one
would still overfit (PBO <!--m:study.refetch.values.dev.snooping.results.pbo_pct-->65.5<!--/m-->%). One description changes in degree: on every pair of the 300 most
liquid names, persistence falls below the base rate at the 5% level (z = <!--m:study.refetch.values.dev.facts.pers_z-->−2.17<!--/m-->, against <!--m:study.dev.facts.pers_z-->−1.71<!--/m--> as
published), rather than matching it; on the strategy's own candidate pairs it is unchanged
(z = <!--m:study.refetch.values.dev.facts.pers_s1_z-->−0.55<!--/m-->). The table is written by `scripts/build_drift_table.py`.

<!-- drift-table:begin -->

| Measure | Published | Re-fetch | Difference |
|---|---:|---:|---:|
| **Main backtest, net of costs** | | | |
| Sharpe ratio | <!--m:main.sharpe-->−0.06<!--/m--> | <!--m:study.refetch.values.main.sharpe-->−0.06<!--/m--> | <!--m:study.refetch.diff.main.sharpe-->0.00<!--/m--> |
| Bootstrap 95% interval, lower end | <!--m:significance.main.boot_lo-->−1.29<!--/m--> | <!--m:study.refetch.values.significance.main.boot_lo-->−1.29<!--/m--> | <!--m:study.refetch.diff.significance.main.boot_lo-->0.00<!--/m--> |
| Bootstrap 95% interval, upper end | <!--m:significance.main.boot_hi-->+1.16<!--/m--> | <!--m:study.refetch.values.significance.main.boot_hi-->+1.16<!--/m--> | <!--m:study.refetch.diff.significance.main.boot_hi-->0.00<!--/m--> |
| Return, % | <!--m:main.total_return_pct-->−0.39<!--/m--> | <!--m:study.refetch.values.main.total_return_pct-->−0.39<!--/m--> | <!--m:study.refetch.diff.main.total_return_pct-->0.00<!--/m--> |
| Trades | <!--m:main.trades-->213<!--/m--> | <!--m:study.refetch.values.main.trades-->213<!--/m--> | <!--m:study.refetch.diff.main.trades-->0<!--/m--> |
| Win rate, % | <!--m:main.win_rate_pct-->47.9<!--/m--> | <!--m:study.refetch.values.main.win_rate_pct-->47.9<!--/m--> | <!--m:study.refetch.diff.main.win_rate_pct-->0.0<!--/m--> |
| Maximum drawdown, % | <!--m:main.max_drawdown_pct-->−4.05<!--/m--> | <!--m:study.refetch.values.main.max_drawdown_pct-->−4.05<!--/m--> | <!--m:study.refetch.diff.main.max_drawdown_pct-->0.00<!--/m--> |
| Average gross exposure, % of equity | <!--m:main.avg_gross_exposure_pct-->26.9<!--/m--> | <!--m:study.refetch.values.main.avg_gross_exposure_pct-->26.9<!--/m--> | <!--m:study.refetch.diff.main.avg_gross_exposure_pct-->0.0<!--/m--> |
| Annual turnover, times | <!--m:main.annual_turnover_x-->9.0<!--/m--> | <!--m:study.refetch.values.main.annual_turnover_x-->9.0<!--/m--> | <!--m:study.refetch.diff.main.annual_turnover_x-->0.0<!--/m--> |
| Newey–West t | <!--m:significance.main.hac_t-->−0.10<!--/m--> | <!--m:study.refetch.values.significance.main.hac_t-->−0.10<!--/m--> | <!--m:study.refetch.diff.significance.main.hac_t-->0.00<!--/m--> |
| Newey–West p | <!--m:significance.main.hac_p-->0.923<!--/m--> | <!--m:study.refetch.values.significance.main.hac_p-->0.923<!--/m--> | <!--m:study.refetch.diff.significance.main.hac_p-->0.000<!--/m--> |
| Probabilistic Sharpe ratio, % | <!--m:significance.main.psr_pct-->46.1<!--/m--> | <!--m:study.refetch.values.significance.main.psr_pct-->46.1<!--/m--> | <!--m:study.refetch.diff.significance.main.psr_pct-->0.0<!--/m--> |
| Deflated Sharpe ratio, % | <!--m:significance.main.dsr_pct-->1.4<!--/m--> | <!--m:study.refetch.values.significance.main.dsr_pct-->1.4<!--/m--> | <!--m:study.refetch.diff.significance.main.dsr_pct-->0.0<!--/m--> |
| **Walk-forward, net of costs** | | | |
| Sharpe ratio | <!--m:oos.pooled_sharpe-->−1.04<!--/m--> | <!--m:study.refetch.values.oos.pooled_sharpe-->−1.04<!--/m--> | <!--m:study.refetch.diff.oos.pooled_sharpe-->0.00<!--/m--> |
| Bootstrap 95% interval, lower end | <!--m:significance.oos_daily.boot_lo-->−2.09<!--/m--> | <!--m:study.refetch.values.significance.oos_daily.boot_lo-->−2.09<!--/m--> | <!--m:study.refetch.diff.significance.oos_daily.boot_lo-->0.00<!--/m--> |
| Bootstrap 95% interval, upper end | <!--m:significance.oos_daily.boot_hi-->+0.05<!--/m--> | <!--m:study.refetch.values.significance.oos_daily.boot_hi-->+0.05<!--/m--> | <!--m:study.refetch.diff.significance.oos_daily.boot_hi-->0.00<!--/m--> |
| Return of the stitched path, % | <!--m:oos.total_return_pct-->−6.24<!--/m--> | <!--m:study.refetch.values.oos.total_return_pct-->−6.24<!--/m--> | <!--m:study.refetch.diff.oos.total_return_pct-->0.00<!--/m--> |
| Windows that made money | <!--m:oos.windows_positive-->4<!--/m--> | <!--m:study.refetch.values.oos.windows_positive-->4<!--/m--> | <!--m:study.refetch.diff.oos.windows_positive-->0<!--/m--> |
| Mean return per window, % | <!--m:oos.avg_window_return_pct-->−0.58<!--/m--> | <!--m:study.refetch.values.oos.avg_window_return_pct-->−0.58<!--/m--> | <!--m:study.refetch.diff.oos.avg_window_return_pct-->0.00<!--/m--> |
| Its 95% interval, lower end, % | <!--m:significance.oos_windows.ci_lo_pct-->−1.28<!--/m--> | <!--m:study.refetch.values.significance.oos_windows.ci_lo_pct-->−1.28<!--/m--> | <!--m:study.refetch.diff.significance.oos_windows.ci_lo_pct-->0.00<!--/m--> |
| Its 95% interval, upper end, % | <!--m:significance.oos_windows.ci_hi_pct-->+0.12<!--/m--> | <!--m:study.refetch.values.significance.oos_windows.ci_hi_pct-->+0.12<!--/m--> | <!--m:study.refetch.diff.significance.oos_windows.ci_hi_pct-->0.00<!--/m--> |
| Its p | <!--m:significance.oos_windows.p-->0.096<!--/m--> | <!--m:study.refetch.values.significance.oos_windows.p-->0.096<!--/m--> | <!--m:study.refetch.diff.significance.oos_windows.p-->0.000<!--/m--> |
| Newey–West t | <!--m:significance.oos_daily.hac_t-->−1.87<!--/m--> | <!--m:study.refetch.values.significance.oos_daily.hac_t-->−1.87<!--/m--> | <!--m:study.refetch.diff.significance.oos_daily.hac_t-->0.00<!--/m--> |
| Newey–West p | <!--m:significance.oos_daily.hac_p-->0.061<!--/m--> | <!--m:study.refetch.values.significance.oos_daily.hac_p-->0.061<!--/m--> | <!--m:study.refetch.diff.significance.oos_daily.hac_p-->0.000<!--/m--> |
| Probabilistic Sharpe ratio, % | <!--m:significance.oos_daily.psr_pct-->3.9<!--/m--> | <!--m:study.refetch.values.significance.oos_daily.psr_pct-->3.9<!--/m--> | <!--m:study.refetch.diff.significance.oos_daily.psr_pct-->0.0<!--/m--> |
| Deflated Sharpe ratio, % | <!--m:significance.oos_daily.dsr_pct-->0.0<!--/m--> | <!--m:study.refetch.values.significance.oos_daily.dsr_pct-->0.0<!--/m--> | <!--m:study.refetch.diff.significance.oos_daily.dsr_pct-->0.0<!--/m--> |
| **Baselines** | | | |
| Gatev distance method, Sharpe ratio | <!--m:benchmarks.gatev.sharpe-->−0.80<!--/m--> | <!--m:study.refetch.values.benchmarks.gatev.sharpe-->−0.80<!--/m--> | <!--m:study.refetch.diff.benchmarks.gatev.sharpe-->0.00<!--/m--> |
| Gatev distance method, return, % | <!--m:benchmarks.gatev.total_return_pct-->−9.55<!--/m--> | <!--m:study.refetch.values.benchmarks.gatev.total_return_pct-->−9.55<!--/m--> | <!--m:study.refetch.diff.benchmarks.gatev.total_return_pct-->0.00<!--/m--> |
| Strategy minus Gatev, Sharpe ratio | <!--m:benchmarks.sharpe_diff_vs_gatev.diff-->+0.73<!--/m--> | <!--m:study.refetch.values.benchmarks.sharpe_diff_vs_gatev.diff-->+0.73<!--/m--> | <!--m:study.refetch.diff.benchmarks.sharpe_diff_vs_gatev.diff-->0.00<!--/m--> |
| Its Ledoit–Wolf p | <!--m:benchmarks.sharpe_diff_vs_gatev.p-->0.364<!--/m--> | <!--m:study.refetch.values.benchmarks.sharpe_diff_vs_gatev.p-->0.364<!--/m--> | <!--m:study.refetch.diff.benchmarks.sharpe_diff_vs_gatev.p-->0.000<!--/m--> |
| Strategy's percentile among the random-pair draws | <!--m:benchmarks.random_control.strategy_percentile-->37<!--/m--> | <!--m:study.refetch.values.benchmarks.random_control.strategy_percentile-->37<!--/m--> | <!--m:study.refetch.diff.benchmarks.random_control.strategy_percentile-->0<!--/m--> |
| Median draw, Sharpe ratio | <!--m:benchmarks.random_control.median_sharpe-->+0.09<!--/m--> | <!--m:study.refetch.values.benchmarks.random_control.median_sharpe-->+0.09<!--/m--> | <!--m:study.refetch.diff.benchmarks.random_control.median_sharpe-->0.00<!--/m--> |
| 5th percentile draw, Sharpe ratio | <!--m:benchmarks.random_control.p5_sharpe-->−1.85<!--/m--> | <!--m:study.refetch.values.benchmarks.random_control.p5_sharpe-->−1.85<!--/m--> | <!--m:study.refetch.diff.benchmarks.random_control.p5_sharpe-->0.00<!--/m--> |
| 95th percentile draw, Sharpe ratio | <!--m:benchmarks.random_control.p95_sharpe-->+1.17<!--/m--> | <!--m:study.refetch.values.benchmarks.random_control.p95_sharpe-->+1.17<!--/m--> | <!--m:study.refetch.diff.benchmarks.random_control.p95_sharpe-->0.00<!--/m--> |
| **Cost schedules and scenarios** | | | |
| Cost schedule A, return, % | <!--m:fund_profiles.institutional.total_return_pct-->−0.56<!--/m--> | <!--m:study.refetch.values.fund_profiles.institutional.total_return_pct-->−0.56<!--/m--> | <!--m:study.refetch.diff.fund_profiles.institutional.total_return_pct-->0.00<!--/m--> |
| Cost schedule D, return, % | <!--m:fund_profiles.quant_hf.total_return_pct-->−7.12<!--/m--> | <!--m:study.refetch.values.fund_profiles.quant_hf.total_return_pct-->−7.12<!--/m--> | <!--m:study.refetch.diff.fund_profiles.quant_hf.total_return_pct-->0.00<!--/m--> |
| Book of $5B, larger leg, % of a day's volume | <!--m:study.dev.cost_sensitivity.scenarios.capital_5b.full.adv_pct-->72.84<!--/m--> | <!--m:study.refetch.values.dev.cost_sensitivity.scenarios.capital_5b.full.adv_pct-->72.85<!--/m--> | <!--m:study.refetch.diff.dev.cost_sensitivity.scenarios.capital_5b.full.adv_pct-->+0.01<!--/m--> |
| **Pair selection, first formation** | | | |
| Pairs tested | <!--m:fdr.pairs_tested-->5,082<!--/m--> | <!--m:study.refetch.values.fdr.pairs_tested-->5,082<!--/m--> | <!--m:study.refetch.diff.fdr.pairs_tested-->0<!--/m--> |
| At raw p < 0.05 | <!--m:fdr.significant_raw_p05-->489<!--/m--> | <!--m:study.refetch.values.fdr.significant_raw_p05-->489<!--/m--> | <!--m:study.refetch.diff.fdr.significant_raw_p05-->0<!--/m--> |
| Surviving Benjamini–Hochberg at q = 0.10 | <!--m:fdr.survive_bh_fdr_q10-->1<!--/m--> | <!--m:study.refetch.values.fdr.survive_bh_fdr_q10-->1<!--/m--> | <!--m:study.refetch.diff.fdr.survive_bh_fdr_q10-->0<!--/m--> |
| Pairs selected | <!--m:fdr.final_selected_pairs-->309<!--/m--> | <!--m:study.refetch.values.fdr.final_selected_pairs-->309<!--/m--> | <!--m:study.refetch.diff.fdr.final_selected_pairs-->0<!--/m--> |
| **Prices and universe** | | | |
| Symbols with price history | <!--m:study.dev.run.symbols-->2,538<!--/m--> | <!--m:study.refetch.values.dev.run.symbols-->2,533<!--/m--> | <!--m:study.refetch.diff.dev.run.symbols-->−5<!--/m--> |
| Share of the symbols requested, % | <!--m:study.dev.facts.cached_pct-->82.2<!--/m--> | <!--m:study.refetch.values.dev.facts.cached_pct-->82.0<!--/m--> | <!--m:study.refetch.diff.dev.facts.cached_pct-->−0.2<!--/m--> |
| Failed the fetch or the data checks, % | <!--m:study.dev.facts.fetch_other_pct-->3.6<!--/m--> | <!--m:study.refetch.values.dev.facts.fetch_other_pct-->3.8<!--/m--> | <!--m:study.refetch.diff.dev.facts.fetch_other_pct-->+0.2<!--/m--> |
| Fetch-coverage rule, % | <!--m:study.dev.facts.coverage_pct-->98.8<!--/m--> | <!--m:study.refetch.values.dev.facts.coverage_pct-->98.6<!--/m--> | <!--m:study.refetch.diff.dev.facts.coverage_pct-->−0.2<!--/m--> |
| Histories moved more than 10% by anchoring to N-PORT | <!--m:study.dev.facts.anchor_moved-->732<!--/m--> | <!--m:study.refetch.values.dev.facts.anchor_moved-->733<!--/m--> | <!--m:study.refetch.diff.dev.facts.anchor_moved-->+1<!--/m--> |
| Index weight of members without price history, first formation, % | <!--m:universe.missing_value_weight_pct-->3.192<!--/m--> | <!--m:study.refetch.values.universe.missing_value_weight_pct-->3.214<!--/m--> | <!--m:study.refetch.diff.universe.missing_value_weight_pct-->+0.022<!--/m--> |
| Index weight of holdings without a usable ticker, % | <!--m:universe.unmapped_value_weight_pct-->0.142<!--/m--> | <!--m:study.refetch.values.universe.unmapped_value_weight_pct-->0.142<!--/m--> | <!--m:study.refetch.diff.universe.unmapped_value_weight_pct-->0.000<!--/m--> |
| Members without price history, first formation | <!--m:study.dev.facts.gap_first_missing-->444<!--/m--> | <!--m:study.refetch.values.dev.facts.gap_first_missing-->449<!--/m--> | <!--m:study.refetch.diff.dev.facts.gap_first_missing-->+5<!--/m--> |
| Survivorship gap, first formation, % of index weight | <!--m:study.dev.facts.gap_first_pct-->3.33<!--/m--> | <!--m:study.refetch.values.dev.facts.gap_first_pct-->3.36<!--/m--> | <!--m:study.refetch.diff.dev.facts.gap_first_pct-->+0.03<!--/m--> |
| Of it, names no longer served (HTTP 404), points | <!--m:study.dev.facts.gap_first_not_found_pct-->2.75<!--/m--> | <!--m:study.refetch.values.dev.facts.gap_first_not_found_pct-->2.75<!--/m--> | <!--m:study.refetch.diff.dev.facts.gap_first_not_found_pct-->0.00<!--/m--> |
| Of it, failed fetches, points | <!--m:study.dev.facts.gap_first_fetch_failed_pct-->0.34<!--/m--> | <!--m:study.refetch.values.dev.facts.gap_first_fetch_failed_pct-->0.36<!--/m--> | <!--m:study.refetch.diff.dev.facts.gap_first_fetch_failed_pct-->+0.02<!--/m--> |
| Of it, failed data checks, points | <!--m:study.dev.facts.gap_first_data_checks_pct-->0.10<!--/m--> | <!--m:study.refetch.values.dev.facts.gap_first_data_checks_pct-->0.10<!--/m--> | <!--m:study.refetch.diff.dev.facts.gap_first_data_checks_pct-->0.00<!--/m--> |
| Members without price history, last formation | <!--m:study.dev.facts.gap_last_missing-->237<!--/m--> | <!--m:study.refetch.values.dev.facts.gap_last_missing-->242<!--/m--> | <!--m:study.refetch.diff.dev.facts.gap_last_missing-->+5<!--/m--> |
| Survivorship gap, last formation, % of index weight | <!--m:study.dev.facts.gap_last_pct-->1.08<!--/m--> | <!--m:study.refetch.values.dev.facts.gap_last_pct-->1.09<!--/m--> | <!--m:study.refetch.diff.dev.facts.gap_last_pct-->+0.01<!--/m--> |
| Of it, names no longer served (HTTP 404), points | <!--m:study.dev.facts.gap_last_not_found_pct-->0.72<!--/m--> | <!--m:study.refetch.values.dev.facts.gap_last_not_found_pct-->0.72<!--/m--> | <!--m:study.refetch.diff.dev.facts.gap_last_not_found_pct-->0.00<!--/m--> |
| Of it, failed fetches, points | <!--m:study.dev.facts.gap_last_fetch_failed_pct-->0.25<!--/m--> | <!--m:study.refetch.values.dev.facts.gap_last_fetch_failed_pct-->0.26<!--/m--> | <!--m:study.refetch.diff.dev.facts.gap_last_fetch_failed_pct-->+0.01<!--/m--> |
| Of it, failed data checks, points | <!--m:study.dev.facts.gap_last_data_checks_pct-->0.09<!--/m--> | <!--m:study.refetch.values.dev.facts.gap_last_data_checks_pct-->0.09<!--/m--> | <!--m:study.refetch.diff.dev.facts.gap_last_data_checks_pct-->0.00<!--/m--> |
| **Evidence layer** | | | |
| Gross per trade, bp (equal-weighted) | <!--m:study.dev.facts.gross_bp-->−7.9<!--/m--> | <!--m:study.refetch.values.dev.facts.gross_bp-->−7.9<!--/m--> | <!--m:study.refetch.diff.dev.facts.gross_bp-->0.0<!--/m--> |
| Cost per trade, bp | <!--m:study.dev.facts.cost_bp-->16.1<!--/m--> | <!--m:study.refetch.values.dev.facts.cost_bp-->16.1<!--/m--> | <!--m:study.refetch.diff.dev.facts.cost_bp-->0.0<!--/m--> |
| Gross per trade after formation, bp | <!--m:study.dev.facts.decay_oos_bp-->−12.6<!--/m--> | <!--m:study.refetch.values.dev.facts.decay_oos_bp-->−12.6<!--/m--> | <!--m:study.refetch.diff.dev.facts.decay_oos_bp-->0.0<!--/m--> |
| Short-term reversal loading, t | <!--m:study.dev.facts.st_rev_t_main-->4.01<!--/m--> | <!--m:study.refetch.values.dev.facts.st_rev_t_main-->4.01<!--/m--> | <!--m:study.refetch.diff.dev.facts.st_rev_t_main-->0.00<!--/m--> |
| Median Sharpe ratio over the 12 start dates | <!--m:study.dev.facts.start_sharpe_median-->−0.65<!--/m--> | <!--m:study.refetch.values.dev.facts.start_sharpe_median-->−0.65<!--/m--> | <!--m:study.refetch.diff.dev.facts.start_sharpe_median-->0.00<!--/m--> |
| **Persistence of cointegration, every pair of the 300 most liquid names** | | | |
| Pairs cointegrated in one year, pooled | <!--m:study.dev.facts.pers_of-->7,334<!--/m--> | <!--m:study.refetch.values.dev.facts.pers_of-->7,320<!--/m--> | <!--m:study.refetch.diff.dev.facts.pers_of-->−14<!--/m--> |
| Of them, cointegrated again the next year | <!--m:study.dev.facts.pers_count-->370<!--/m--> | <!--m:study.refetch.values.dev.facts.pers_count-->359<!--/m--> | <!--m:study.refetch.diff.dev.facts.pers_count-->−11<!--/m--> |
| Share, % | <!--m:study.dev.facts.pers_pct-->5.04<!--/m--> | <!--m:study.refetch.values.dev.facts.pers_pct-->4.90<!--/m--> | <!--m:study.refetch.diff.dev.facts.pers_pct-->−0.14<!--/m--> |
| Its 95% interval, lower end, % | <!--m:study.dev.facts.pers_lo_pct-->4.56<!--/m--> | <!--m:study.refetch.values.dev.facts.pers_lo_pct-->4.42<!--/m--> | <!--m:study.refetch.diff.dev.facts.pers_lo_pct-->−0.14<!--/m--> |
| Its 95% interval, upper end, % | <!--m:study.dev.facts.pers_hi_pct-->5.57<!--/m--> | <!--m:study.refetch.values.dev.facts.pers_hi_pct-->5.42<!--/m--> | <!--m:study.refetch.diff.dev.facts.pers_hi_pct-->−0.15<!--/m--> |
| Expected at the next year's base rate | <!--m:study.dev.facts.pers_expected-->403.4<!--/m--> | <!--m:study.refetch.values.dev.facts.pers_expected-->401.3<!--/m--> | <!--m:study.refetch.diff.dev.facts.pers_expected-->−2.1<!--/m--> |
| z against the base rate | <!--m:study.dev.facts.pers_z-->−1.71<!--/m--> | <!--m:study.refetch.values.dev.facts.pers_z-->−2.17<!--/m--> | <!--m:study.refetch.diff.dev.facts.pers_z-->−0.46<!--/m--> |
| **Persistence of cointegration, the strategy's candidate pairs** | | | |
| Pairs cointegrated in one year | <!--m:study.dev.facts.pers_s1_of-->1,196<!--/m--> | <!--m:study.refetch.values.dev.facts.pers_s1_of-->1,196<!--/m--> | <!--m:study.refetch.diff.dev.facts.pers_s1_of-->0<!--/m--> |
| Of them, cointegrated again the next year | <!--m:study.dev.facts.pers_s1_count-->62<!--/m--> | <!--m:study.refetch.values.dev.facts.pers_s1_count-->62<!--/m--> | <!--m:study.refetch.diff.dev.facts.pers_s1_count-->0<!--/m--> |
| z against the base rate | <!--m:study.dev.facts.pers_s1_z-->−0.55<!--/m--> | <!--m:study.refetch.values.dev.facts.pers_s1_z-->−0.55<!--/m--> | <!--m:study.refetch.diff.dev.facts.pers_s1_z-->0.00<!--/m--> |
| **Second family (S2)** | | | |
| Avellaneda–Lee, net Sharpe ratio | <!--m:study.residual.sharpe-->−0.28<!--/m--> | <!--m:study.refetch.values.residual.sharpe-->−0.28<!--/m--> | <!--m:study.refetch.diff.residual.sharpe-->0.00<!--/m--> |
| Newey–West p | <!--m:study.residual.p-->0.598<!--/m--> | <!--m:study.refetch.values.residual.p-->0.599<!--/m--> | <!--m:study.refetch.diff.residual.p-->+0.001<!--/m--> |
| Gross per trade, bp | <!--m:study.residual.gross_bp-->+5.35<!--/m--> | <!--m:study.refetch.values.residual.gross_bp-->+5.36<!--/m--> | <!--m:study.refetch.diff.residual.gross_bp-->+0.01<!--/m--> |
| Gross P&amp;L, $M | <!--m:study.residual.gross_usd_m-->2.71<!--/m--> | <!--m:study.refetch.values.residual.gross_usd_m-->2.72<!--/m--> | <!--m:study.refetch.diff.residual.gross_usd_m-->+0.01<!--/m--> |
| Mean trade net of stock-leg costs, bp | <!--m:study.dev.facts.s2c_net_mean_bp-->−4.54<!--/m--> | <!--m:study.refetch.values.dev.facts.s2c_net_mean_bp-->−4.53<!--/m--> | <!--m:study.refetch.diff.dev.facts.s2c_net_mean_bp-->+0.01<!--/m--> |
| **Variant family: data-snooping tests** | | | |
| Variants with a positive Sharpe ratio | <!--m:study.dev.snooping.results.positive-->7<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.positive-->6<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.positive-->−1<!--/m--> |
| Best variant's Sharpe ratio | <!--m:study.dev.snooping.results.sharpe_best-->+0.21<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.sharpe_best-->+0.51<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.sharpe_best-->+0.30<!--/m--> |
| Best variant's return, % | <!--m:study.dev.snooping.results.ret_best_pct-->+1.14<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.ret_best_pct-->+2.89<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.ret_best_pct-->+1.75<!--/m--> |
| Rank of the v33 design by Sharpe ratio | <!--m:study.dev.snooping.results.base_rank-->9<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.base_rank-->8<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.base_rank-->−1<!--/m--> |
| Hansen SPA against cash, p | <!--m:study.dev.snooping.results.spa_zero.p-->0.964<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.spa_zero.p-->0.880<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.spa_zero.p-->−0.084<!--/m--> |
| Its lower p | <!--m:study.dev.snooping.results.spa_zero.p_lower-->0.905<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.spa_zero.p_lower-->0.751<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.spa_zero.p_lower-->−0.154<!--/m--> |
| Its upper p | <!--m:study.dev.snooping.results.spa_zero.p_upper-->0.975<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.spa_zero.p_upper-->0.904<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.spa_zero.p_upper-->−0.071<!--/m--> |
| White Reality Check against cash, p | <!--m:study.dev.snooping.results.spa_zero.rc_p-->0.977<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.spa_zero.rc_p-->0.886<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.spa_zero.rc_p-->−0.091<!--/m--> |
| Best variant against cash, studentized mean | <!--m:study.dev.snooping.results.spa_zero.best_t-->0.38<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.spa_zero.best_t-->0.80<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.spa_zero.best_t-->+0.42<!--/m--> |
| Hansen SPA against Gatev at unit volatility, p | <!--m:study.dev.snooping.results.spa_gatev_unit_vol.p-->0.489<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.spa_gatev_unit_vol.p-->0.421<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.spa_gatev_unit_vol.p-->−0.068<!--/m--> |
| Its Reality Check p | <!--m:study.dev.snooping.results.spa_gatev_unit_vol.rc_p-->0.499<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.spa_gatev_unit_vol.rc_p-->0.322<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.spa_gatev_unit_vol.rc_p-->−0.177<!--/m--> |
| Best variant against Gatev at unit volatility, studentized mean | <!--m:study.dev.snooping.results.spa_gatev_unit_vol.best_t-->1.35<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.spa_gatev_unit_vol.best_t-->1.50<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.spa_gatev_unit_vol.best_t-->+0.15<!--/m--> |
| Hansen SPA against Gatev on daily returns, p | <!--m:study.dev.snooping.results.spa_gatev.p-->0.219<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.spa_gatev.p-->0.191<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.spa_gatev.p-->−0.028<!--/m--> |
| Its Reality Check p | <!--m:study.dev.snooping.results.spa_gatev.rc_p-->0.232<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.spa_gatev.rc_p-->0.165<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.spa_gatev.rc_p-->−0.067<!--/m--> |
| Best variant against Gatev on daily returns, studentized mean | <!--m:study.dev.snooping.results.spa_gatev.best_t-->1.54<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.spa_gatev.best_t-->1.64<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.spa_gatev.best_t-->+0.10<!--/m--> |
| Romano–Wolf stepdown, variants rejected at 5% | <!--m:study.dev.snooping.results.rw_rejected-->0<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.rw_rejected-->0<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.rw_rejected-->0<!--/m--> |
| Its smallest adjusted p | <!--m:study.dev.snooping.results.rw_min_p-->0.98<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.rw_min_p-->0.91<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.rw_min_p-->−0.07<!--/m--> |
| Model confidence set, 90%, variants kept | <!--m:study.dev.snooping.results.mcs_included-->38<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.mcs_included-->38<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.mcs_included-->0<!--/m--> |
| Its smallest p | <!--m:study.dev.snooping.results.mcs_min_p-->0.60<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.mcs_min_p-->0.51<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.mcs_min_p-->−0.09<!--/m--> |
| Effective number of independent trials | <!--m:study.dev.snooping.results.effective_rank-->13.7<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.effective_rank-->13.8<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.effective_rank-->+0.1<!--/m--> |
| Variants' Sharpe dispersion, standard deviation | <!--m:study.dev.snooping.results.dsr.sd_sr-->0.52<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.dsr.sd_sr-->0.53<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.dsr.sd_sr-->+0.01<!--/m--> |
| Expected best null Sharpe ratio | <!--m:study.dev.snooping.results.dsr.sr_star-->0.91<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.dsr.sr_star-->0.92<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.dsr.sr_star-->+0.01<!--/m--> |
| Best variant's probabilistic Sharpe ratio, % | <!--m:study.dev.snooping.results.dsr_best.psr_pct-->62.8<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.dsr_best.psr_pct-->79.2<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.dsr_best.psr_pct-->+16.4<!--/m--> |
| Best variant's deflated Sharpe ratio, % | <!--m:study.dev.snooping.results.dsr_best.dsr_pct-->13.5<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.dsr_best.dsr_pct-->25.4<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.dsr_best.dsr_pct-->+11.9<!--/m--> |
| The v33 design's deflated Sharpe ratio, % | <!--m:study.dev.snooping.results.dsr.dsr_pct-->6.3<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.dsr.dsr_pct-->6.0<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.dsr.dsr_pct-->−0.3<!--/m--> |
| Probability of backtest overfitting, % | <!--m:study.dev.snooping.results.pbo_pct-->79.4<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.pbo_pct-->65.5<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.pbo_pct-->−13.9<!--/m--> |
| Best of one half, on the other: mean Sharpe ratio | <!--m:study.dev.snooping.results.pbo_is_best_oos_sharpe-->−0.87<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.pbo_is_best_oos_sharpe-->−0.71<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.pbo_is_best_oos_sharpe-->+0.16<!--/m--> |
| Its splits with a loss, % | <!--m:study.dev.snooping.results.pbo_is_best_loss_pct-->99.2<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.pbo_is_best_loss_pct-->90.9<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.pbo_is_best_loss_pct-->−8.3<!--/m--> |
| Median variant on the same splits: mean Sharpe ratio | <!--m:study.dev.snooping.results.pbo_median_oos_sharpe-->−0.53<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.pbo_median_oos_sharpe-->−0.52<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.pbo_median_oos_sharpe-->+0.01<!--/m--> |
| Variant–splits with a loss, % | <!--m:study.dev.snooping.results.pbo_base_loss_pct-->76.6<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.pbo_base_loss_pct-->76.8<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.pbo_base_loss_pct-->+0.2<!--/m--> |
| **Declared variants whose Sharpe ratio moved** | | | |
| Entry 1.5, exit 0.25, stop 1.5, Sharpe ratio | <!--m:study.dev.snooping.results.variants.1.sharpe-->+0.02<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.variants.1.sharpe-->−0.49<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.variants.1.sharpe-->−0.51<!--/m--> |
| Entry 2.1, exit 0.75, stop 1.0, Sharpe ratio | <!--m:study.dev.snooping.results.variants.24.sharpe-->−0.80<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.variants.24.sharpe-->−0.32<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.variants.24.sharpe-->+0.48<!--/m--> |
| Learned ranker on, Sharpe ratio | <!--m:study.dev.snooping.results.variants.33.sharpe-->+0.10<!--/m--> | <!--m:study.refetch.values.dev.snooping.results.variants.33.sharpe-->+0.51<!--/m--> | <!--m:study.refetch.diff.dev.snooping.results.variants.33.sharpe-->+0.41<!--/m--> |

<!-- drift-table:end -->

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
  were seen; an exploratory v33 run was seen before the published one (it is in the trial
  registry); and the second family ran under two earlier universe rules, the second changed
  after a review measured the P&L of the names the change removes (registered after the fact as
  `residual_earlier_rules`). The pre-registered holdout addresses it, and the declared variant family
  measures it: no variant beats cash, even before the search is allowed for, or the distance
  method on a Sharpe scale, and parameter choice on the family would overfit.
- **The 2026 test is sealed, not prospective.** The test period ended before the pre-registration
  was filed, and the project was developed during it; the designers' general knowledge of 2026
  markets cannot be sealed.
- **The 2026 test is short, and tests two arms.** Over
  its <!--m:study.holdout.arms.0.days-->200<!--/m--> trading days, with returns shaped like S1's
  development returns, it has 80% power only against an annual Sharpe ratio of
  about <!--m:study.dev.facts.ho_mde_025-->2.96<!--/m--> at Holm's first step, stated in advance;
  the Newey–West test is asymptotic, and its size at this length is a little above 5% (simulated
  in the pre-registration); an edge in one arm would say nothing about the other.
- **The path depends on the start date.** Sizing is a share of equity and the 30% cap binds, so
  the same rule on the same days gives different trades from different start dates. On each
  later start's own days the published path has the higher Sharpe ratio
  in <!--m:study.dev.facts.start_matched_wins-->10<!--/m--> of <!--m:study.dev.facts.start_matched_of-->11<!--/m-->
  cases, which flatters the headline; on the days all twelve share it
  ranks <!--m:study.dev.facts.start_common_rank-->3<!--/m-->rd. Unmatched, over windows of different
  length, it is the highest of the twelve (median
  Sharpe <!--m:study.dev.facts.start_sharpe_median-->−0.65<!--/m-->). Every comparison and the two
  halves as separate runs are reported.
- **Vendor prices carry corporate actions after the window.** Yahoo back-applies later splits
  and dividends to the whole history; price levels are anchored to N-PORT's price at each snapshot
  date, and returns are unaffected.
- **Some inputs are dated 2026.** Identity data (identifier map, SIC codes, listing venue), the
  French factor files (daily factors to August 2026, among them the short-term reversal factor,
  close to the signals of both tested arms), FRED rates and the v32 universe file were fetched in
  2026; the price API's responses carry each security's latest price and 52-week high and low
  (read by no study code; one data review stored such responses outside the repository, since
  deleted); and adjusted price levels carry 2026 corporate actions. The stock screener behind the
  v32 universe file also gave each stock's last sale price and volume; surveys of free data
  sources downloaded daily VIX, rate and spread series to October 2026, French industry returns to
  August 2026, the ETF's product pages and index changes, FINRA short interest to 2026-09-30, Tiingo's ticker
  list with each ticker's last price date and SEC filing lists; and one survey asked for 300 stocks'
  2026 monthly charts to list their splits. The EDGAR list of IWV's N-PORT filings and the header
  pages of its two 2026 reports were downloaded too. A few of these values were displayed while files were
  checked, and every such file was deleted, or lost with the working storage, before the filing.
  Two rules of the industry map use 2026 information (a ticker missing from the SEC's 2026 company
  list has no industry; a name first held in 2026 needs to be among the 3,000 largest of 18 October
  2026); they are disclosed in the pre-registration. None of these inputs is a 2026 daily price
  history of a traded security, factors are truncated at each calendar's end, and no strategy
  reads the factors, rates or survey files; the direction is that they may flatter the holdout.
- **The frozen v32 arm's universe looks ahead into 2026.** It is ranked on market values downloaded on
  18 October 2026 (the close of 16 October at the latest), which is why S3 is descriptive only.
- **Renamed securities can look delisted.** A ticker change with a new CUSIP is remapped through
  N-PORT's reported tickers, issuer successions and price checks.
- **Borrow is one fee for every name.** Specials and recalls are not modelled; 1% and 3% stress
  runs bound the effect.
- **Fills are close-to-close.** The closing auction is assumed, with no queue, auction-volume or
  intraday model; participation is measured against full-day volume, so participation in the
  auction is a multiple of it and the largest books in the capacity scenarios could not be filled
  at the close; impact is stressed at Y = 0.6 and 1.0. This probably flatters.
- **Cost parameters are published averages, not measurements.** No free tick or quote data:
  spreads and impact come from published estimates, with Y = 0.3 at the low end of them. This
  probably flatters.
- **Cost scenarios change the trades.** Each re-run is a new path, so the headline trades are
  also re-priced under every scenario.
- **Hedge ratios below one leave market exposure.** The book carries a small market loading,
  reported with an eight-factor attribution.
- **The main backtest and the walk-forward overlap.** With no model to refit they are one rule
  from two start dates; the holdout is the independent test.
- **One period, one regime.** 30 months with three-month T-bills
  near <!--m:study.dev.facts.cash_tbill_yield_pct-->4.79<!--/m-->%, and one path. Within the period no
  split by the previous day's VIX or sector dispersion separates the returns (highest minus lowest
  VIX tercile, t = <!--m:study.dev.facts.vix_diff_t-->0.74<!--/m-->), but the terciles are the
  period's own; the 2026 test is another period.
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
| v33 | the pre-registered design: point-in-time universe, same-industry pairs, full re-formation, no regime gate or ranker, one borrow fee; the evidence layer, a second strategy family, the declared variant family and its data-snooping tests, robustness checks, the trial registry and the 2026 holdout, pre-registered and evaluated. Development run of 21 Oct 2026: no detectable edge |

---

*Research project. Not investment advice; no claim of deployable performance.*
