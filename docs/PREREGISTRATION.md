# Pre-registration: the 2026 out-of-sample test

## Status and freeze rule

**Frozen at the commit that adds this file** (the registered commit). It is the single commit in
HEAD's history that adds `docs/PREREGISTRATION.md`, with renames not followed
(`study_config.preregistration_commit`). It must be an ancestor of HEAD and be pushed before the
test runs. The commit's date is set by its author and is not evidence of when it was pushed.
`scripts/run_holdout.sh` refuses to run:

- from a shallow clone;
- when this file has no adding commit in HEAD's history or more than one, or the adding commit is
  not an ancestor of HEAD;
- when the registered commit is on no remote-tracking branch of the clone
  (`git branch -r --contains`: the refs of the clone's last fetch or push, not a query of the
  remote);
- when anything under `pairs_trading/`, `scripts/`, `reference/`, `requirements.txt`,
  `pyproject.toml`, `.gitignore` or this file differs from the registered commit, unless
  `HOLDOUT_CRASH_FIX` is set and no file in `NEVER_FIXED` differs (commitment 2; the runbook does
  not check that the change is a crash fix);
- when anything under those paths is uncommitted or untracked (files that `.gitignore` ignores,
  such as `__pycache__/`, are not checked; `.gitignore` itself is frozen and in `NEVER_FIXED`);
- when `reference/holdout_inputs.sha256` is missing, or an input differs from the hash it pins.

Everything below was committed and pushed before this project fetched a daily price history of a
security for dates after 2025-12-31 into its code, caches or working files, and before it downloaded
any N-PORT holdings document for a 2026 report period. That covers the three strategies and their
code, the data rules, the hypotheses, the test and the decision rule. Two kinds of request before
this commit did reach into 2026: network checks that asked for one stock's five-day daily chart and
discarded the answer unread, and a survey that asked for 300 stocks' 2026 monthly charts and kept
only their split events. Both are listed under "Inputs dated 2026". For the two 2026 reports
(periods 2026-03-31 and 2026-06-30) only the EDGAR filing list and the filings' header pages were
downloaded. They give each filing's period, filing date and acceptance time, accession number, size
and document list. The development price cache ends on 2025-12-31: its fetch manifest records
`"end": "2025-12-31"` (`results/v32_dev/price_fetch_manifest.json` for the first fetch, of
2026-10-18; `results/v33_dev/price_fetch_manifest.json` after the top-ups of 2026-10-20 and
2026-10-21). The project did receive other 2026 market information before this commit, including the
latest-quote metadata that comes with every price request. All of it that the project's records show
is listed under "Inputs dated 2026", which also says how those records were searched and where they
end.

The seal is enforced in code. A fetch of prices, of the VIX and sector-ETF series, or of N-PORT
holdings for a period that ends on or after 2026-01-01 is refused unless the environment variable
`PAIRS_UNSEAL` names the registered commit and that commit is an ancestor of HEAD
(`study_config.assert_unsealed`, called by `pairs_trading/data_processor.py` and
`scripts/build_pit_universe.py`). Apart from the tests, which use temporary repositories or block
every request, only `scripts/run_holdout.sh` sets `PAIRS_UNSEAL`, after the checks above. Nothing
stops a person from setting it by hand once the registered commit exists. The commitment is that no
one does: from this commit until the trial is registered, no price bar or macro series dated after
2025-12-31, and no 2026 N-PORT holding, is fetched or examined outside `scripts/run_holdout.sh`. The
runbook's first attempt refuses to start if the holdout price cache, the holdout macro cache or
`results/holdout2026/` already exists. The price cache's manifest
(`data/holdout2026_prices_manifest.json`, published as
`results/holdout2026/price_fetch_manifest.json`) records when it was fetched and every top-up. The
macro cache has no manifest: each run's provenance records its sha256 and file time, and the data
step's log (`logs/holdout2026_a<N>_data.log`, published) time-stamps its fetch.

## Why a pre-registered test

Every design decision in versions 1 to 33 was made while looking at 2020-2025 data. The
development-period statistics correct for that as far as statistics can: a deflated Sharpe ratio
over the 32 versions counted in `N_TRIALS` of `trading_system.CompleteFixedRussell3000TradingSystem`
(v1-v32, a lower bound), the
probability of backtest overfitting, Hansen's SPA test and the Romano-Wolf stepdown over a family
of variants declared before any of them was run (`results/variant_family/declaration.json`). The
only clean test of a trading rule is data that played no part in designing it. This is that test.
Each strategy runs on it once, apart from the re-runs that commitments 1 and 2 allow, all of
them on record.

The test period, 2026-01-02 to 2026-10-19, ended before this document was committed, and the
project was developed during it: versions 8 to 32 are dated 2026-02-20 to 2026-10-12 in
`docs/PROGRESS.md`, and version 33 was built after that, up to the registered commit (git
history). The test is therefore sealed, not prospective. It rests on the project's data and code
having held no 2026 prices of the traded securities beyond those listed under "Inputs dated
2026". General knowledge of 2026 markets among the people who designed the strategies cannot be
sealed. No design choice is known to depend on it, and none can be shown not to.


## What is tested

Three strategies run on the holdout calendar, `holdout2026` (`study_config.CALENDARS`). Two are
confirmatory and one is descriptive (`scripts/evaluate_holdout.py`, `REGISTERED` and
`CONFIRMATORY`):

| Label | Strategy | Role | Registered by | ID in `evaluation.json` |
|---|---|---|---|---|
| S1 | v33 pairs: study profile `v33`, the design this document registers | confirmatory, H1 | profile hash `d54d21314c22` | `v33_pairs` |
| S2 | Avellaneda-Lee sector-ETF residual reversion, with the paper's window, mean-reversion threshold and s-score cut-offs, on S1's universe rule, fills and cost model (`residual_statarb.py`) | confirmatory, H2 | parameter hash `2d50e388fb12` | `avellaneda_lee` |
| S3 | v32 as published, frozen: study profile `v32` | descriptive only, tested in no family | profile hash `b5665398f3ad` | `v32_pairs` |

H1 and H2, the test and the decision rule are given under "Hypotheses, test and decision rule".
S3 is reported with the same statistics as S1 and S2 but is not tested. Its universe file,
`data/marketcap.csv`, lists the stocks that the Nasdaq screener ranked largest by market value
when it was downloaded on 2026-10-18, inside the test period, so a rejection could reflect
survivorship rather than an edge.

A profile hash is the first 12 hex digits of the sha256 of the profile's fields as JSON with sorted
keys (`study_config.Profile.config_hash`). S2's is the same digest of
`residual_statarb.ResidualStatArbParams()`, registered as `study_config.RESIDUAL_PARAMS_HASH`. Every
export records its hash (`run_config.study`). `scripts/run_residual_statarb.py` refuses to run when
the code's default parameters hash to anything else (a run with other parameters is a variant; see
S2), and `scripts/evaluate_holdout.py` refuses a pairs run whose hash is not its profile's in
`study_config.PROFILES` and a residual run whose hash is not the registered one. `study_config.py`
is in `NEVER_FIXED`. A hash covers only its own fields: a profile's universe source and size,
industry rule, re-formation scheme, regime gate, ranker and financing charges, and S2's parameters,
among them its kappa cut and s-score thresholds. S1's and S3's screens, thresholds and gates given
below are set in the code, outside their profiles' hashes; the registered commit fixes them.

**S1.** At each formation date the universe is the point-in-time Russell 3000 as held by the iShares
Russell 3000 ETF (IWV): the mapped tickers of the latest N-PORT snapshot whose report period ends on
or before that date (`universe.PITUniverse.members_asof`). A snapshot is used from its period date,
53 to 62 days before its filing was public (see "Universe"). On the holdout calendar the snapshots
are read from `data/holdout2026_reference/`, which step 1 of the runbook writes
(`universe.reference_root`). Pairs are first selected on the calendar's data to its selection
cutoff, 2025-12-31: three years, from `data_start` (2023-01-01). The whole selection is then re-run
every 126 trading days on the trailing 1,095 calendar days (`study_config.PROFILES['v33']`;
`trading_system.build_rolling_pair_schedule`), the first time on the first session after the cutoff.
On each day the pairs of the latest formation dated on or before it are tradeable, and positions
already open run off under their own exit rules. On the holdout that first session is the calendar's
first trading day, 2026-01-02, so the initial selection governs no trade, as in the development run
and both rehearsals. At each formation the members with price history are screened
(`pair_selector.screen_symbols`, on the trailing window): at least 300 bars, mean point-in-time
close of at least $5, mean point-in-time dollar volume of at least $10M, annualised volatility
strictly between 5% and 80%, and fewer than 10% missing closes. The 500 most liquid by that dollar
volume are kept. Candidate pairs lie within one Fama-French 49 industry
(`reference/industry_ff49.csv`). A pair is selected when its two legs have returns on at least 420
common sessions in the window (so a name with 300 to 419 bars can pass the screen and take one of
the 500 places but forms no pair), its return correlation is at least 0.25, its two-direction
Engle-Granger p-value is below 0.05 (Bonferroni over the two directions), its half-life is 4 to 25
days and its quality score exceeds 0.4. The hedge ratio is Kalman-filtered. A position opens
at |z| >= 1.8 on the beta-locked spread. It closes at the target (z > -0.5 for a long spread,
z < +0.5 for a short spread), at a stop 1.5 further against the entry, or at a time stop of
max(10, min(floor(2.5 x half-life), 25)) sessions. Candidates are ranked by signal strength,
min(|z| / 2.5, 1), times pair quality; there is no learned ranker and no regime gate.

A signal must also pass the engine's gates and the risk manager (`trading_system.py`,
`risk_manager.py`, `position_sizer.py`): pair quality of at least 0.55, so a pair selected with a
quality between 0.4 and 0.55 never trades; a 20-day return correlation of at least 0.20; a hedge
ratio in [0.25, 4]; at least 50 bars of pair history; no cool-off (30 calendar days after three
consecutive losing trades on the pair); a locked-spread standard deviation of at most 0.30; a
smaller leg's 20-day dollar ADV of at least $1M; and an ex-ante round-trip cost below 1% of equity.
No position is signalled on a day whose return is below -3%, and no stock is in two open pairs. A
position's gross size is set by signal strength, pair quality, min(|z| / 2.3, 2) and the run's
recent record: once more than five trades have closed, it is multiplied by 0.7 when fewer than two
of the last five closed trades made money after costs, and by 1.3 when more than three did.
Separately, it is multiplied by 0.8 when the standard deviation of the locked spread's last 10 daily
changes exceeds 0.08 (`position_sizer.py`). The result is clamped to 3% to 10% of equity, then
multiplied by the risk manager's volatility and profit scaling, which can take it below 3%. At most
8 new trades are taken a day, and gross exposure is capped at 30% of equity, measured as the sum of
the open positions' gross sizes, each as a share of equity at the close of its signal day, the day
before its fill (`trading_system.py`, `open_exposure`). A drawdown of 15% from peak equity, a daily
return below -5%, or that sum above 30% flattens the book at the next close and stops new trades for
the rest of the run. The cap and the exposure kill switch divide each position's entry size by the
equity at the close of its own signal day. The reported gross exposure divides the same entry sizes
by the previous close's equity, so when equity has fallen since the positions' signal days it can
stand slightly above 30% without tripping the switch: in the development run it was above 30% on 5
days, at most 30.11% of equity. Neither measure marks the positions to market. The same rules apply
to S3. Fills, costs and the formation schedule are given under "Data and calendar".

**S2, Avellaneda-Lee residual reversion.** The ETF variant of Avellaneda and Lee (2010), as
implemented in `pairs_trading/residual_statarb.py` and run by `scripts/run_residual_statarb.py`.
Its registered parameters are the defaults of `ResidualStatArbParams`: the paper's window, kappa
cut and s-score thresholds (below), a position of 0.5% of equity, a universe of 500 names
re-ranked every 21 sessions on S1's 1,095-day window, 20-day cost inputs and $100M of capital.
They hash to `2d50e388fb12` (`study_config.RESIDUAL_PARAMS_HASH`). The script stops before it
reads any data when the code's defaults hash to anything else, and `scripts/evaluate_holdout.py`
refuses an export with another hash. The hash fixes the parameters, not the code that uses them.

Each stock is assigned one of the 11 Select Sector SPDR ETFs (XLK, XLC, XLF, XLV, XLY, XLP, XLE,
XLI, XLB, XLU, XLRE) by the `sector_etf` column of `reference/industry_ff49.csv`. At each close,
for each stock with 60 daily returns between consecutive real bars in the trailing window, the
stock's returns are regressed on its ETF's by OLS with an intercept; the cumulative residual X_k
(k = 1 to 60) is fitted by an AR(1), X_{n+1} = a + b X_n + zeta, also by OLS; and
kappa = -ln(b) x 252, m = a / (1 - b) and sigma_eq = sqrt(Var(zeta) / (1 - b^2)). The model is
accepted only when 0 < b < 1 and kappa > 252/30 (8.4), a mean-reversion time below half the
window. The signal is the paper's pure mean-reversion s-score, centred across stocks:
s = -(m - <m>) / sigma_eq, where <m> is the mean of m over the day's universe members whose model
is accepted. The drift-adjusted s-score is not used. A position opens long at s < -1.25 and short
at s > +1.25. A long closes at s > -0.50, a short at s < +0.75, and a held position closes when
its model is rejected. A day without an estimate for the stock (a missing bar in the window, or a
degenerate regression) leaves its position unchanged. Only universe members open positions; a
held position is managed by the same rules after its stock leaves the universe.

A position buys (or sells) stock worth 0.5% of current equity and sells (or buys) beta times that
notional of the stock's ETF. It is held unchanged until it closes. The ETF hedges of all positions
are netted, so each day only the change in each ETF's net position trades. None of S1's gates,
caps or kill switches applies: S2 has no limit on the number of positions or on gross exposure.
In its development run (`results/residual_dev/`) the gross exposure of its stock and ETF legs
averaged 1.20 times equity and reached 2.00 times, with up to 283 positions open.

S2's universe follows S1's rule (`residual_statarb.LiquidityUniverse`). On the first signal day,
2026-01-02, and every 21st session after it, the candidates are the members of the IWV snapshot
in force that day with price history. Their bars in the trailing 1,095 calendar days go through
S1's symbol screen, and the 500 most liquid by mean point-in-time dollar volume that have a sector
ETF form the universe until the next ranking day. A screened name without a sector ETF is passed
over for the next one, and each ranking records how many of S1's own 500 were replaced that way.
On the NYSE's 2026 schedule there are ten ranking days, the last on 2026-10-05; since 126 sessions
are six ranking intervals, S2 ranks on both days S1 re-forms. Only snapshots filed by 2026-10-19
are read (`run_residual_statarb.membership`).

Fills and the cost model are S1's (below). A short stock leg pays the borrow fee of profile v33,
0.38% a year, on its entry notional over the calendar days held. The day's net ETF trades go
through the same cost function at an assumed dollar ADV of $1 trillion
(`ETF_ASSUMED_ADV_DOLLARS`), so they pay the lowest half-spread, 0.75 bp, and almost no impact;
a net short ETF position pays the borrow fee daily. `residual_statarb.s1_cost_model` refuses a
profile with a prime-broker spread, which the residual book does not model. The deviations from
the paper (next-day fills, this cost model in place of 5 bp a side, 11 sector ETFs in place of
15, S1's universe, a fixed position size in place of a leverage target) are declared in the
module's docstring.

A finished run is not a run of the arm when a ranking day selects no names, or fewer than S1's
rule selects (the smaller of 500 and the number of names that pass S1's screen) because too few
screened names have a sector ETF, or when the run makes no trade. The script then writes its
export with `complete` false and the reasons, and exits 2. It also exits 2 before it computes
anything: when the code's default parameters hash to anything else, when the checkout is not at
`PAIRS_EXPECTED_COMMIT`, when a cache is missing, belongs to another period or fails the checks
under "Partial data", or when a sector ETF of the map lacks closes from 2026-01-02 through the
last price date. It never fetches. Another universe size, position size or sector map makes a
variant, listed in the export's `non_default_switches`; the evaluator refuses an incomplete export
and one with a switch.

**S3, v32 as published, frozen.** The v32 profile (`study_config.PROFILES['v32']`, hash
`b5665398f3ad`), run by the same engine as S1, with S1's thresholds, gates and risk rules. Its
universe is the `Symbol` column of the v32 universe file, `data/marketcap.csv`, which is not
point-in-time (see "Universe"). The 300 most liquid of those names that pass the symbol screen are
searched (`max_universe` 300), and a pair may join any two of them (`same_industry` False). The
pairs selected on data to 2025-12-31 form a pool that is re-tested every 90 sessions on the trailing
730 calendar days; no new pair can enter. The regime gate is on. A position's size is multiplied by
0.25 when the VIX is above 40, by 0.5 when it is above 30 or when the dispersion of 63-day
sector-ETF returns is more than two standard deviations above its trailing-year mean, and by 0.4
when the VIX is below 20 and that dispersion is more than 0.8 but at most two standard deviations
above its mean (the smaller of the VIX factor and the dispersion factor applies). No new trade opens
while more than 20% of the last 63 sessions were scaled down. Candidates are ranked by signal
strength times pair quality times the score of a learned transformer ranker, trained on the pool's
signals whose outcomes, exit fill included, are complete by 2025-12-31. The holding costs are v32's:
a borrow fee of 0.25% a year and a prime-broker spread of 0.5% a year on the short half of gross
notional. S3 is reported with the same statistics as S1 and S2 and tested in no family, because its
universe file was ranked on market values from inside the test period (see "Inputs dated 2026"): a
name that failed during 2026 is not in it. The test suite checks that the v32 profile, with the
ranker off, makes the decisions of the v32 code (commit `fa4c02b`) on a synthetic market
(`tests/test_pipeline_e2e.py`).

## Data and calendar

**Calendars.** Each run is one calendar of `study_config.CALENDARS`, whose fields and hash every
export records. The holdout calendar, `holdout2026` (hash `c19018232a36`), loads prices from
2023-01-01 (`data_start`) to 2026-10-19 (`data_end`), forms its first pairs on data to 2025-12-31
(`selection_cutoff`), completes ranker labels by 2025-12-31 (`model_train_end`, read only by S3's
ranker) and takes its first signals on 2026-01-02 (`backtest_start`). It runs no walk-forward
and has caches of its own, `data/holdout2026_prices.pkl` and `data/holdout2026_macro.pkl`. Its
three years of formation data match the development calendar `dev` (hash `0bcc31796bad`): prices
2020-01-01 to 2025-12-31, selection cutoff 2022-12-31, ranker labels to 2023-06-30, first entry
2023-07-01, walk-forward on. The rehearsal calendar, `rehearsal2025`, has hash `aad3ad2a0b80`. A
cache belongs to one calendar: a price cache whose manifest describes another period, and any
cache with a bar after the calendar's last date, is refused (`data_processor._check_cache_period`,
`load_macro_data`), so the development cache is never extended into 2026.

From 2026-01-02 to 2026-10-19 the NYSE's published 2026 holiday schedule has 200 sessions. That
number is a design value, used for the power calculation (`HOLDOUT_SESSIONS` in
`scripts/build_site_data.py`); no code derives it from an exchange calendar. A run's sessions are
the dates of the vendor's bars: the trading dates of its pairs for S1 and S3, those of the
sector-ETF closes for S2. Each arm's daily series starts on the first of them with a zero return,
because the first orders fill at the next close, and ends on the last. The evaluator requires the
three series to have identical dates inside the calendar, and records whether they run from
2026-01-02 to 2026-10-19 (`period_matches_calendar`). On the rehearsal calendar the series had
199 dates, its sessions on the NYSE's 2025 schedule.

**Formation schedule.** S1 forms its first pairs on the bars of 2023-01-01 to 2025-12-31 among the
members of the 2025-12-31 snapshot. It re-runs the whole selection on the first session,
2026-01-02, and every 126 sessions after it, each time on the trailing 1,095 calendar days among
the members of the snapshot in force: on the NYSE schedule, on 2026-01-02 and 2026-07-07. On each
day the pairs of the latest formation dated on or before it may open positions, so the formation
of 2025-12-31 is superseded on 2026-01-02, before any trade. S3 selects its pool on the same
three years and re-tests it on 2026-01-02 and every 90 sessions after it (2026-05-13 and
2026-09-22 on that schedule). S2's ranking days are given above.

**Prices.** Daily bars come from Yahoo's chart API, requested directly
(`data_processor._download_history`), not through the yfinance package, whose cookie handshake
Yahoo rate-limits. yfinance 0.2.57 is installed, and its version is recorded in each fetch
manifest. A request covers the calendar's whole range, 2023-01-01 to 2026-10-19 for the holdout,
and bars outside it are dropped. Closes, opens, highs and lows are adjusted for splits and
dividends as of the fetch, and volumes for splits; split and dividend events come back only inside
the requested range. Every return, spread, z-score, hedge ratio and S2 regression is computed on
the adjusted closes. One price cache serves the three arms. Step 2 of the runbook fills it for S1
first, with every member of the IWV snapshots in force from 2025-12-31 to 2026-10-19 (those of
2025-12-31, 2026-03-31 and 2026-06-30), and writes it with its manifest; S3's data step then adds
the symbols of `data/marketcap.csv` that the cache has not attempted, over the same range
(`_top_up`). S2 only reads the cache (`load_cached_data`).

**Price levels.** The $5 screen, the screen's dollar volume and the per-share commission read
`Close_PIT` and `Volume_PIT` rather than the adjusted series, which scales early levels by later
corporate actions. Both first undo the splits inside the fetched range (`future_split_factor`).
For S1 and S2 the levels are then anchored to N-PORT's value per share
(`data_processor.anchor_point_in_time`, applied to every member by `anchor_all`): each bar's
`Close_PIT` is multiplied by the ratio of N-PORT's price to `Close_PIT` on the latest snapshot
date on or before the bar (before the first, by the first ratio), so it equals N-PORT's price on
every snapshot date, and `Volume_PIT` is divided by the same ratio. A snapshot date without a bar
in the four days up to it is skipped. In the holdout the anchors include the two sealed snapshots
built in step 1. Anchoring changes no return and no z-score. It also leaves dollar volume as it
was, the adjusted close times the split-adjusted volume, which later dividends lower; the
dollar-volume screen and the spread bucket read it on that basis. S3's levels are not anchored
(`trading_system._anchor_point_in_time_prices` runs only for a point-in-time universe), so they
still carry later dividends.

**Fills.** A signal uses data through the close of day t, and its order fills at the close of
t + 1, in the closing auction, which is assumed: there is no queue, auction-volume or intraday
model. Share counts are fixed from the day-t close. An entry needs a real bar on t + 1 for every
stock it trades; an exit on a day without a bar fills at the stock's last real close. No position
is signalled on the last two sessions. Positions are marked to market daily on the adjusted
closes, so dividends are in the P&L, and a position still open at the last bar, 2026-10-19,
closes at that close (`end_of_data`). The runbook clears `PAIRS_FILL`, so the next-open variant
cannot run.

**Costs.** Every execution of a stock leg pays three one-way costs
(`transaction_costs.EnhancedPrimeFundTransactionCostModel.calculate_leg_cost`), from the stock's
own 20-day average volume and 20-day volatility of daily returns on the fill day:

- a commission of $0.002 a share, at least $0.50 an order, on the share count at the
  point-in-time price;
- half the typical quoted spread for the stock's 20-day dollar ADV: 0.75 bp at $500M or more,
  2 bp from $100M, 5 bp from $20M, 15 bp from $5M and 40 bp below;
- square-root market impact, Y x daily volatility x sqrt(shares / ADV in shares) of the notional,
  with Y = 0.3 and a cap of 50 bp.

Entry costs are booked on the entry fill day, and exit costs and holding costs on the exit fill
day (apart from S2's ETF borrow, above). The short leg pays a borrow fee on its entry notional for
the calendar days held: 0.38% a year for S1 and S2 (profile v33), 0.25% for S3 (profile v32). S3
also pays a prime-broker spread of 0.5% a year on half of each position's gross notional
(`calculate_financing_cost`); S1 and S2 pay none. Cash earns no interest. Specials, recalls and
SEC and FINRA transaction fees are not modelled. Every arm starts with $100M.

**Macro series.** The VIX and the 11 sector ETFs are fetched from the same API over the same range
into the calendar's macro cache, in step 2, by S1's data step when it finds no macro cache; if
that fetch leaves a series missing, S1's data step writes no macro cache and still finishes, and
S3's data step fetches all twelve again. The fetch is
sealed like the price fetch (`study_config.assert_unsealed`), the cache is written only when the
VIX and all 11 ETFs came back, and a cache with a value after 2026-10-19 is refused. The ETF
closes are S2's hedges and, as their equal-weighted daily return, the market proxy of every pairs
run's market attribution. The VIX and the ETFs are the inputs of S3's regime gate and of its
ranker's features, and an S3 run stops unless every series reaches the last price date. S1
trades on neither.

**Network.** Three steps of the runbook can make requests; S2's run, the evaluation and the
publishing step read files only. Step 2 asks Yahoo's chart API for the bars and the macro series
above. Step 1 downloads the sealed filings from EDGAR and asks
OpenFIGI for the identifiers it maps. The pairs runs of step 3 read the Kenneth French factor files
for their export's attribution block, and download them if `data/external/french/` is absent.

**Partial data.** Each price symbol gets up to four attempts in a fetch's first pass; an HTTP 404
(`not_found`), fewer than 200 bars (`short`) or a failed data check (`invalid`) is final at once. A
symbol whose four attempts all end in another error or an empty answer gets a second pass of up to
four more attempts, one symbol at a time, after a 30-second pause
(`EnhancedRussell3000DataProcessor._fetch_many`, in a first fetch and a top-up alike), so a fetch
makes at most eight attempts per symbol. The VIX and sector-ETF series get four attempts each, with
no second pass. A fetch that leaves more than 10% of the symbols with an error or an empty answer is
refused, and nothing is written to the cache (`data_processor.MIN_FETCH_COVERAGE` = 0.90; for a
top-up, the test is the merged cache's coverage of the universe). The data step has then not
finished, and it can be run again. A failure recorded in a written cache's manifest is final: no
later fetch retries it. Each run refuses its cache unless it covers at least 90% of the run's own
universe, counting a symbol as covered if it is cached or its outcome is `not_found`, `short` or
`invalid`. S2 also refuses a cache that never attempted one of its point-in-time members, since it
fetches nothing (`EnhancedRussell3000DataProcessor.load_cached_data`). `PAIRS_ALLOW_PARTIAL_FETCH=1`
would let a run accept a partial cache, but it is recorded as a non-default switch, which the
evaluator refuses, and the runbook clears every `PAIRS_*` variable it inherits.

**One cache for every arm.** The data step's first load, S1's, fills the price cache with the
members of every snapshot in force from S1's selection cutoff to the calendar's last date
(`trading_system.py`, `_study_symbols`); on the holdout and rehearsal calendars these include all of
S2's snapshots. S3's load then tops the cache up with the symbols of `data/marketcap.csv` that have
no outcome in its manifest, over the cache's own dates, and records the top-up in the manifest's
`top_ups` (`EnhancedRussell3000DataProcessor._top_up`). The macro cache, the daily closes of the VIX
and the eleven sector SPDR ETFs, is written only when all twelve were fetched. S3's load stops
unless all twelve have closes through the last price date (`trading_system.py`,
`_check_macro_coverage`), so the data step cannot finish without them. S2 stops unless every sector
ETF its map names has closes from the first signal date through the last price date
(`run_residual_statarb.check_sector_closes`).

## Universe

S1 and S2 draw their universe from the point-in-time Russell 3000 as held by the iShares Russell
3000 ETF (IWV; iShares Trust, CIK 1100663, series S000004341) in its N-PORT-P filings
(`universe.PITUniverse`; `scripts/build_pit_universe.py`; `reference/README.md` documents the build
and its checks). S3 trades v32's universe file instead (below). The rules:

- **Membership is point-in-time by period date.** Each filing gives one snapshot: the equity-common
  holdings (`assetCat` EC), one row per CUSIP (or ISIN where N-PORT gives none), with the holding's
  share of the equity-common value and N-PORT's value per share. Only the report for the third month
  of each fiscal quarter is public. A snapshot is in force from its period date until the next
  one's: a formation of S1 uses the latest snapshot whose period ends on or before the formation
  date (`PITUniverse.members_asof`), and S2 does the same on each ranking day, among the snapshots
  filed by the calendar's last date (`run_residual_statarb.membership`). Filings are public 53 to 62
  days after their period date, so a snapshot is used about two months before it was public, and
  changes inside a quarter appear at the next quarter end. IWV is a fund, not the index: the
  committed snapshots hold 2,581 to 2,895 equity-common securities each.
- **Committed and sealed snapshots.** The 26 snapshots dated 2019-09-30 to 2025-12-31 are committed
  in `reference/universe/`. Its `index.json` lists the two 2026 filings under `sealed`, by period,
  filing date, accession and form only: 2026-03-31 (filed 2026-05-26, `0000940400-26-020829`) and
  2026-06-30 (filed 2026-08-27, `0000940400-26-035008`). Only step 1 of the holdout downloads and
  builds them (`build_pit_universe.build_sealed`), into `data/holdout2026_reference/universe/`,
  which S1 and S2 read on the holdout calendar (`universe.reference_root`). Step 1 copies the
  committed snapshots there byte for byte, builds the sealed ones from exactly the listed
  accessions, stops if a filing's header or document gives another series or period, and writes
  nothing under `reference/`. A filing the index does not list is not read.
- **CUSIP to ticker.** OpenFIGI maps each identifier to a US ticker (`cusip_ticker_map.json`: 4,258
  entries, 3,882 with a ticker, all mapped on 2026-10-20): the US composite line's, else another US
  venue's, else a delisted line's last ticker, in Yahoo's style (`BRK/B` becomes `BRK-B`). That is
  the security's latest ticker, under which Yahoo serves its whole history. Without an active US
  line, a candidate ticker is accepted when its US composite record has the same share-class FIGI or
  a matching issuer name (`same_security`). From the 2022-09-30 filing on, N-PORT reports each
  holding's ticker, and an identifier OpenFIGI leaves unmapped, or maps only to a delisted line
  under another ticker, is resolved through it the same way. Placeholder CUSIPs of contingent value
  rights and escrow claims stay in the weights without a ticker.
- **`reused`.** When the ticker of a delisted line, or one N-PORT reported, now belongs to a
  different security, the identifier gets status `reused` and no ticker, so no member is joined to
  another security's prices (Barnes Group's `B` is now another issuer's). The price check's
  rejections and the shared-ticker rule give the same status; 72 entries are `reused`.
- **Issuer successions.** A CUSIP without an active mapping that is replaced in the very next
  snapshot by exactly one new CUSIP with a ticker, the same six-character issuer number and the same
  issuer name takes that ticker, unless another holding held alongside it carries the ticker
  (`issuer_successions`; 21 links in `index.json`, General Electric's CUSIP before its 2021 reverse
  split among them). Step 1 adds the links found among the two sealed snapshots alone.
- **The price check.** Where identity data cannot make the link (a rename or a reorganisation under
  a new issuer number) or cannot tell a successor from a later security under the same ticker, a
  data review of 2026-10-20 and 2026-10-21 compared N-PORT's value per share on every held period
  date with the ticker's split-unadjusted close on the last session on or before it. It covered
  every identifier whose ticker or status had changed against the map at commit `4bcc8b5`, and every
  other mapping not made by OpenFIGI's own active US line, except tickers with no bar dated 2025 or
  earlier. A mapping passed when the two agreed within 2% on every held date (`reference/README.md`
  lists the exceptions, mostly a constant ratio). The check's code is not in the repository; its
  verdicts are, applied by `vet_mappings` on every online build: `ACCEPTED_MAPPINGS` gives 85
  identifiers the ticker under which their history sits, and `REJECTED_MAPPINGS` takes from 17 a
  ticker whose history is another security's.
- **The shared-ticker rule.** When a holding is mapped to a ticker by its own CUSIP or ISIN as an
  active US line, another holding of the same snapshot that reaches that ticker only indirectly gets
  status `reused` and no ticker (OmniAb's two earnout CUSIPs under `OABI`). `RDUS` and `STR` stay
  shared by two delisted holdings in 13 committed snapshots; the development cache has no prices for
  either.
- **New identifiers in the sealed snapshots.** An identifier already in the committed map keeps its
  ticker, unless the shared-ticker rule takes it away in a sealed snapshot. Identifiers first held
  in a sealed snapshot are mapped by step 1 with OpenFIGI, with the tickers N-PORT reports for them,
  into its copy of the map, by OpenFIGI's rules and the shared-ticker rule only. The price check is
  not repeated for them.
- **Industries and sector ETFs** come from `reference/industry_ff49.csv`, last built on 2026-10-21
  for every ticker in a committed snapshot (to 2025-12-31) or in `data/marketcap.csv`. Each ticker
  gets the SEC SIC code current when it was downloaded (2026-10-20 or 2026-10-21), not a
  point-in-time one. A ticker without an industry has no
  sector ETF either. S1 cannot pair such a name, though it still takes one of S1's 500 places if
  it passes the screen, and S2 passes it over. Two rules of the file use information from inside
  the test period, and both keep out of S1 and S2 names according to what happened to them during
  2026. First, a ticker missing from SEC's company list of 2026-10-20 (by the builder's
  description, delisted or renamed by then) has no industry; neither has a ticker whose EDGAR record
  gives no SIC code, or SIC 0 (Bank OZK and Preferred Bank, held on 2025-12-31 and priced, give
  none). On
  the 2025-12-31 snapshot, 108 of the 2,589 mapped members (0.574% of its equity value) have no
  CIK in the file, and 111 (0.583%) no industry. 103 of these (0.567%) also have no development
  prices; 8 members with prices (0.017%) have no industry, and 11 (0.048%) no sector ETF. Second, a
  ticker held in a 2026 snapshot but in no committed snapshot has an industry only if it is also in
  `data/marketcap.csv`, the v32 universe file, whose tickers the industry file also lists
  (`scripts/build_reference_data.py`, `study_tickers`). A name first held in a 2026 snapshot
  therefore has an industry and a sector ETF only if it was among the 3,000 largest US common
  stocks of the Nasdaq screener on 2026-10-18; one that was smaller then, or no longer listed, has
  neither, with the consequences above. Of the v32 file's 2,999 symbols, 562 are in no committed
  snapshot: 429 of them have an industry and 428 a sector ETF. S1 and S2 read the committed file
  (`universe.industry_map`, `universe.sector_etf_map`); the runbook does not rebuild it.
- **Coverage of the latest committed snapshot.** The 2025-12-31 snapshot governs S1's first
  formations and S2's first ranking days in the holdout. In the development cache, 2,422 of the
  snapshot's 2,589 mapped members have cached history, 99.152% of its equity value
  (`PITUniverse.coverage` on the `cached_symbols` of `results/v33_dev/price_fetch_manifest.json`).
  The other 167 hold 0.836%: 81 `not_found` (0.370%), 26 with an HTTP error (0.301%), 41
  `invalid` (0.094%) and 19 `short` (0.070%). The seven holdings without a ticker hold 0.013%.
  That cache was fetched from 2026-10-18 to 2026-10-21, so these outcomes are the vendor's of
  October 2026. The nine heaviest of the 167, together 0.366%, are Warner Bros Discovery (0.102%),
  Electronic Arts, AvalonBay Communities, Coterra Energy, Exact Sciences, Qnity Electronics,
  Hologic, TopBuild and Comerica (0.018%). The first three failed with an HTTP error; Qnity, first
  held on 2025-12-31, had fewer than 200 bars to that date (`short`); the other five are
  `not_found`. Seven of the nine (all but Warner Bros Discovery and Qnity) have no CIK in
  `reference/industry_ff49.csv`, so by the first rule above they have no industry and no sector
  ETF in the holdout, whatever its fetch returns for them. The holdout's cache is fetched afresh,
  and its coverage of this snapshot is known only when its runs report it.
- **The survivorship gap is reported at every formation.** For each formation date, S1's export
  records the snapshot in force and its filing date, the number of members and of members with
  prices in the run's cache, the index weight of the members without prices
  (`missing_value_weight`) and of the holdings without a ticker (`unmapped_value_weight`), and
  the ten heaviest names of each (`universe_by_formation`; `trading_system._formation_members`,
  `PITUniverse.coverage`). S2's export records the same for each snapshot, on the first ranking
  day it governs, and adds the members with prices but no sector ETF, which can never enter its
  universe: their number, weight and ten heaviest names (`no_sector_etf`;
  `run_residual_statarb.universe_record`). S3 has no point-in-time membership and records none.
- **S2's sector ETFs** are the `sector_etf` column of the same file. `build_reference_data.py`
  maps each FF49 industry to a Select Sector SPDR by a fixed table (`FF49_SECTOR_ETF`: by the
  table's own notes, the GICS sector that holds most of the industry's market value), and
  overrides it for 20 SIC ranges (`SECTOR_ETF_SIC_OVERRIDES`; REITs, SIC 6798, go to XLRE). There
  are 11 ETFs: XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV and XLY. French's catch-all
  industry 49, Other, gets none unless an override applies. Of the file's 4,237 tickers, 3,223
  have an industry and 3,218 a sector ETF. A stock's ETF, like its industry, is fixed for the
  whole test.

**The v32 universe file.** S3 reads its universe from `data/marketcap.csv`, which is not in git
(`.gitignore` ignores `data/`). `scripts/build_universe.py` built it on 2026-10-18: the 3,000
largest US common stocks by market value among the Nasdaq stock screener's 7,002 rows
(`results/v32_dev/universe_meta.json`). The loader uses only its Symbol column: it upper-cases
the symbols, writes class shares with a hyphen, drops missing, invalid and duplicate ones and
sorts the rest (`EnhancedRussell3000DataProcessor.load_symbols`). Of the 3,000 rows it kept 2,999
symbols; the one it dropped, `NAN`, is listed in `reference/industry_ff49.csv` without an
industry. The original file was lost with the working storage (by 2026-10-22). On 2026-10-26 it
was rebuilt from `results/v32_dev/price_fetch_manifest.json`, whose `outcomes` hold the 2,999
symbols the loader kept, as a file with one column, `Symbol`, holding those symbols in sorted
order (commit `b68e852` added the recipe to `reference/README.md` and the new pin). The loader
returns the same 2,999 symbols from it, so S3's universe, and with it the holdout data step's
fetch list, are unchanged. The rebuilt file carries no market values, names or sectors. Both
rehearsals read the original file; their S3 exports record its sha256,
`34661d82644fd36d80b91f4a129cc8435afcbf69faf6a61b89977a461197ca3e`. The holdout reads the rebuilt
one: `reference/holdout_inputs.sha256` pins it (sha256
`f1acb6a53a0792e45d6a558e889edb3e38405852ae91e65a77a24ab5bb565fa3`), and the runbook refuses to
start when the file is missing or
differs (`sha256sum --check --strict`).

## Inputs dated 2026

These inputs were on disk at this commit, or were on disk or arrived with a request before it, in
the repository or in the project's working storage outside it. None of them is a daily price
history of a security dated after 2025-12-31, apart from the five-day charts of the network checks,
which were discarded unread. Several carry 2026 market information in other forms: the market
values in the Nasdaq screener responses, with each stock's last sale price, daily change and volume
beside them; the monthly 2026 bars in the answers to the split survey; the daily returns of Kenneth
French's factor and industry files; the latest-quote metadata of Yahoo's responses; the 2026
corporate actions in Yahoo's adjusted price levels; and the daily VIX, rate and spread series,
IWV's product pages and the index-membership changes that two surveys of free data sources
downloaded.

| Input | Fetched | What reaches into 2026 | Used by |
|---|---|---|---|
| `data/marketcap.csv`, the v32 universe file: the 3,000 largest stocks by market value in the Nasdaq screener (columns Symbol, Name, MarketCap, Sector, Industry). Rebuilt on 2026-10-26 with the Symbol column only (see "Universe" and "Loss of the working storage") | 2026-10-18, a Sunday: its values were at the latest those of the close of 2026-10-16 | each listed stock's market value at that close, which set against a 2025 market value gives its change in value over most of the test period; membership of the 3,000 largest. The rebuilt file keeps only the membership | S3's universe (Symbol column); the ticker list of `reference/industry_ff49.csv`, which decides whether a name first held in a 2026 snapshot has an industry and a sector ETF for S1 and S2 (see "Universe"); the holdout data step's fetch list. No code read MarketCap; Sector was read only by the unregistered variant `--sector-map nasdaq`, which the rebuilt file does not support. Operator's attestation: no 2026 return was computed from the file. While this document was drafted (2026-10-21), the original file's header and first two rows (two stocks' market values) were displayed by mistake; no other value was viewed and none was used. Two committed files record the smallest of the 3,000 market values: `results/v32_dev/universe_meta.json` (`smallest_market_cap`) and `docs/PROGRESS.md` (the v32 entry). |
| Nasdaq screener responses: the one `data/marketcap.csv` was built from, by `scripts/build_universe.py`, and a second one fetched by a survey of trading costs | 2026-10-18 and 2026-10-20 | for each of about 7,000 listed stocks, the market value, the last sale price, its net and percentage change and the volume of the latest session (at the latest that of 2026-10-16 in the first response and of 2026-10-19 in the second) | the first only by `scripts/build_universe.py`, which built `data/marketcap.csv` from it: `build_universe.select` reads only each row's symbol, name, country, market value, sector and industry, so no code reads the last sale price, change or volume, and rebuilding the file from the first response reproduced its sha256. The second is read by no study code. The first row of each response was displayed (see "Values displayed"). Both were deleted on 2026-10-21 at 15:11 UTC, before this commit. |
| Kenneth French daily factors (five factors, momentum, short- and long-term reversal; `data/external/french/`) | 2026-10-20 | daily factor returns to 2026-08-31 (vintage 202608; each export records the files' last date in `evidence.factors.source.last_date`), among them the short-term reversal factor, which is close to the reversal signals of S1 and S2 | the factor attribution and the T-bill (RF) cash return in the evidence block of every pairs run, truncated at the run's last date (`evidence.load_factors(end=...)`). These files were lost with the working storage, so the holdout's S1 and S3 runs download the library's files current on the day they run, with whatever later returns those hold; the exports record their vintage and last date. No strategy reads them to trade. |
| FRED DTB3 and EFFR (`data/external/fred/`) | 2026-10-20 | 2026 observations | DTB3: the development anatomy's cash comparison, read on that run's own dates (`anatomy.cash_returns`); EFFR: read by no study code. Neither is read by a strategy or by the holdout's runs. Lost with the working storage. |
| OpenFIGI CUSIP-to-ticker map, SEC company tickers and SIC codes, Nasdaq Trader symbol directory | 2026-10-20 (some SEC codes 2026-10-21) | identity data as of that date, including 2026 delistings, renames and reorganisations | universe mapping, including the `reused` status that leaves Avidity Biosciences without a ticker; industry and sector-ETF classification (see "Universe"). `reference/listing_venue.csv` is built but read by no study code. The raw downloads were lost with the working storage; the committed files built from them are unchanged. |
| Yahoo adjusted closes and split-adjusted volumes in the development and rehearsal caches | development prices 2026-10-18, with top-ups on 2026-10-20 and 2026-10-21; development macro series 2026-10-18; each rehearsal cache when its rehearsal ran | split, reverse-split, spin-off and dividend adjustment as of the fetch date, including 2026 corporate actions that a request ending 2026-01-01 does not return as events (`reference/README.md` finds 51 identifiers at a constant ratio to N-PORT's price) | price and volume levels; returns are unaffected; S1's and S2's levels are anchored to N-PORT, S3's are not. The caches were lost with the working storage; each run's provenance records their sha256. |
| Yahoo chart API responses | with every price request: the development and rehearsal fetches, and the data review's price check of the CUSIP map (2026-10-20 and 2026-10-21) | the response metadata carries the security's latest quote: the last price and its time, that session's high, low and volume, and the 52-week high and low | read by no study code: `data_processor._download_history` reads only the exchange time zone from it and stores no response. The data review's price check, whose code is not in the repository, stored its raw responses, this metadata included, outside the repository; it parsed them only for daily bars dated 2025 or earlier, and one response's metadata was displayed (see "Values displayed"). Those copies (1,537 files) were deleted on 2026-10-21 at 07:45 UTC, before this commit; the record of their paths and sha256 was lost with the working storage. Operator's attestation: no value of these fields was used or analysed. |
| Downloads of two surveys of free data sources and trading costs, outside the repository | 2026-10-20 | FRED VIXCLS, BAA10Y, BAMLH0A0HYM2, DFF, DGS3MO, DTB3, EFFR, OBFR and SOFR to 2026-10-16, T10Y2Y to 2026-10-19 and IORB to 2026-10-20; Cboe's daily VIX open, high, low and close to 2026-10-19 (the VIX is the series of S3's regime gate); further copies of the French factor files, and the French 49-industry portfolios' daily returns, to 2026-08-31; S&P 500 constituent changes to 2026-08-18, from a public repository; Tiingo's list of supported tickers with each ticker's last price date; FINRA short interest to 2026-09-30; SEC filing lists and Nasdaq Trader symbol files of 2026-10-20 | read by no study code. The last observations of eight of the FRED series and the last rows of the French factor files were displayed (see "Values displayed"). Deleted on 2026-10-21 at 15:11 UTC, before this commit, with the screener responses and the IWV pages (137 files); the record of their paths and sha256 was lost with the working storage. |
| iShares product pages of IWV, saved on 2026-10-18 while looking for IWV's holdings file and again by the two surveys (some under `.csv` or `.json` names; all are HTML) | 2026-10-18 and 2026-10-20 | the fund's closing price, NAV, 52-week range, shares outstanding and net assets as of a session from 2026-10-16 to 2026-10-19, and its daily premium or discount to NAV from 2025-01-02 to the fetch | read by no study code; deleted on 2026-10-21 at 15:11 UTC, before this commit. |
| Requests whose window reached into 2026, outside the runbook | 2026-09-24, 2026-10-12 and 2026-10-18; 2026-10-20 | network checks asked Yahoo for AAPL's five-day daily chart (five requests on three days) and iShares for IWV's holdings file (2026-10-18); every answer was discarded unread and only the HTTP status printed, and an attempt at a second price source failed. The survey of trading costs asked Yahoo for the 2026 monthly chart (2026-01-01 to 2026-10-24) of 300 large stocks to list their 2026 splits: the answers carried monthly price bars and the latest quote, and the script kept and printed only the split ratios (ten stocks) | nothing; the split list was deleted on 2026-10-21 at 15:11 UTC. |
| EDGAR list of IWV's N-PORT filings (`data/raw/nport/filings.atom`) and the header pages of the 2026-03-31 and 2026-06-30 reports | 2026-10-20 | each filing's period, filing date and acceptance time, accession number, size and document list (the 2026-06-30 filing also lists an exhibit, not downloaded) | the sealed list in `reference/universe/index.json`. The downloads were lost with the working storage; step 1 of the runbook downloads the two filings again from the accessions that list registers. |

Since commit `3066d3a` (2026-10-20), every pairs run truncates the French factor files at its own
calendar's last date. Two runs on the rehearsal calendar, S1 and S3 on 2026-10-20 in the working
clone, started before that change reached their code (their exports are not published). They
loaded the files whole, though their attribution used only their own 2025 trading dates. No
committed export or exhibit contains a 2026 factor return: the exports record only the files' last
date, and the development export's factor fingerprint records `truncated_at` 2025-12-31.
Operator's attestation: no analysis of 2026 factor returns was made; checks of the files' format
displayed their last rows (see "Values displayed"), and the automated checks of their date range
and missing values read every row. None of the three strategies reads factor data to trade.

**Values displayed.** The session logs, searched on 2026-10-21 (see below), show these 2026 values
displayed in a tool's output, each while a file's format or a source's availability was checked:

- on 2026-10-18 and 2026-10-20, the first row of each Nasdaq screener response: one stock's market
  value, last sale price, net and percentage change and volume;
- on 2026-10-20, the last observation of eight FRED series (DTB3, DGS3MO, DFF, EFFR, SOFR,
  BAMLH0A0HYM2 and VIXCLS, the VIX close, of 2026-10-16; IORB of 2026-10-20) and SOFR's
  observations of 2026-10-15 and 2026-10-16;
- on 2026-10-20, the last two or three daily rows, dated 2026-08-27 to 2026-08-31, of the French
  factor files: the five factors, momentum and the two reversal factors;
- on 2026-10-21, one Yahoo response's latest-quote metadata: one stock's last price, that session's
  range and volume, and its 52-week range;
- on 2026-10-21, the header and first two rows of the original `data/marketcap.csv` (above).

Operator's attestation: no displayed value was used in a design, parameter, test or decision
choice.

**How the list was compiled.** On 2026-10-21, after a review of this document found that the list
was incomplete, three searches were made: a scan of the repository and of the working storage for
files whose content carries dates in 2026, which printed paths, counts and date ranges but no
values; a check of the last date in every pickled cache, none of which reached past 2025-12-31; and
a search of the session logs for requests whose window reached into 2026 and for 2026 values in a
tool's output. The files the scan found outside the repository were then deleted (the rows above
give the times). The session logs begin on 2026-09-24; the work before that date, versions 8 to
31.1, has none. Up to commit `ff38599` (2026-10-20, 13:00 UTC), every committed version of the
fetch code, from the repository's first commit on 2026-06-13, ended its price requests at
2025-12-31. That commit added the `holdout2026` calendar, whose requests run to 2026-10-19; every
other calendar ends by 2025-12-31. From commit `a1c76db`, at 18:04 UTC the same day, a fetch for
that calendar is refused unless `PAIRS_UNSEAL` names the registered commit and that commit is an
ancestor of HEAD (`study_config.assert_unsealed`). Between those two commits nothing in the fetch
code refused one: from commit `7cc7593`, at 16:11 UTC, `scripts/run_holdout.sh` refused to start the
holdout before this file was committed, but `python -m pairs_trading.main --calendar holdout2026`
was not refused. The scan of 2026-10-21 found no pickled cache, for the holdout or any other
calendar, with a date after 2025-12-31.

**Loss of the working storage.** The container that held the project's working storage was recycled
by 2026-10-22 at 17:29 UTC, before this commit, and everything outside the committed files was lost:
the development and rehearsal price and macro caches (each run's provenance records their sha256),
the raw downloads under `data/raw/`, the French and FRED files under `data/external/`, the original
`data/marketcap.csv` (rebuilt as described under "Universe"), the cache of OpenFIGI's answers (so
step 1 of the runbook asks OpenFIGI afresh for every identifier it maps), the records of the
deletions above, the logs of the helper sessions that worked on the project, and the working copy of
this document. This document was then rebuilt from the parts of it that the main session's log kept
and from the code, and the rebuilt parts were checked against the code again before this commit. At
this commit the project holds no 2026 market data outside its committed files.

## Hypotheses, test and decision rule

Two hypotheses are tested, each one-sided:

- **H1** (S1, `v33_pairs`): S1's mean daily net return over the holdout days is above zero. The
  null is that it is at most zero.
- **H2** (S2, `avellaneda_lee`): the same for S2.

S3 (`v32_pairs`) is reported with the same statistics and tested in no family: it has no
hypothesis, no adjusted p-value and no decision. Its universe is drawn from the 3,000 largest
stocks by market value at the close of 2026-10-16 at the latest (`data/marketcap.csv`), inside the
test period, so a rejection could reflect survivorship rather than an edge.

**The returns.** Each arm's export gives one net return per trading day of its run, from the
calendar's first session (`backtest_start`, 2026-01-02) to its last (`data_end`, 2026-10-19). That
is 200 days on the NYSE's published 2026 holiday schedule (`HOLDOUT_SESSIONS` in
`scripts/build_site_data.py`). The evaluator does not require 200: it takes the days the runs
record, refuses runs whose days differ or fall outside the calendar (below), and reports whether
they run from its first day to its last (`period_matches_calendar`). For S1 and S3,
`scripts/evaluate_holdout.py` reads the run's `daily_equity_curve`: each day's `daily_return_pct`
divided by 100, which the export rounds to six decimal places of a per cent (`load_pairs_run`). For
S2 it reads `daily_dates` and `daily_net_returns` of `residual_statarb.json` (`load_residual_run`).
In both engines a day's net return is that day's marked-to-market P&L of the positions held, less
the costs booked that day, divided by the previous close's equity; no interest is credited on cash.
A signal at one close fills at the next (`trading_system.py`, `entry_k = k + 1`;
`residual_statarb.simulate_residual_book`), so no position is held on the first session and its net
return is zero in every arm, as it was on 2025-01-02 in all six exports of the two rehearsals. That
day is kept: the test uses every daily net return the export records and drops none.

**The test statistic.** `evaluate_holdout.one_sided_test` takes the Newey-West t of the mean from
`significance.hac_tstat_mean`. For the n daily net returns r_t, with mean m and e_t = r_t - m:

- the lag is L = max(1, floor(4 (n/100)^(2/9))) (`significance._newey_west_lags`). It is 4 for any
  n from 100 to 272, so 4 at 200 days (4 x 2^(2/9) = 4.67); both rehearsals, at 199 days, used 4;
- the autocovariances are g_k = (1/n) x the sum over t = k + 1..n of e_t e_(t-k), for k = 0..L;
- the long-run variance is S = g_0 + 2 x the sum over k = 1..L of (1 - k/(L + 1)) g_k, with
  Bartlett weights, floored at 1e-18;
- t = m / sqrt(S/n), and the one-sided p-value is p = 1 - Phi(t), where Phi is the standard normal
  distribution function.

There is no small-sample correction: the autocovariances are divided by n, not by n - k or n - 1,
and p comes from the normal distribution, not Student's t. The statistic is that of statsmodels'
OLS on a constant with `cov_type='HAC'` and `use_correction=False`
(`tests/test_reference_implementations.py`). A series of fewer than three days, or one without
dispersion (`significance._is_constant`), has t = 0 and so p = 0.5. The two-sided p-value that
`hac_tstat_mean` also returns is not used.

**Multiplicity.** H1 and H2 are the family, and the only members of it
(`evaluate_holdout.CONFIRMATORY`). Holm's step-down procedure runs across the two at a familywise
alpha of 0.05 (`evaluate_holdout.ALPHA`). With p(1) the smaller of the two one-sided p-values and
p(2) the larger, the adjusted p-values are min(1, 2 p(1)) for the first and
max(min(1, 2 p(1)), p(2)) for the second (`evaluate_holdout.holm`). Comparing them with 0.05 is
Holm's procedure: the smaller p is compared with 0.025 and, only if it is below, the larger with
0.05. S3's p-value does not enter the family. Holm's procedure needs no assumption about the
dependence between the two p-values; S1 and S2 trade on the same days, from the same universe rule,
with the same fills and cost model.

**Decision.** An arm in the family shows an edge out of sample if and only if its Holm-adjusted
p-value is below 0.05: `edge_out_of_sample` is `p_holm < ALPHA`, a strict inequality. In
`results/holdout2026/evaluation.json` S1 and S2 have the `role` `confirmatory`; S3 has the `role`
`descriptive`, and its `p_holm` and `edge_out_of_sample` are null. Nothing else in the report enters
the decision. The gross returns, the Sharpe ratio, its intervals and bounds and the comparisons
with the baselines describe the result; they do not test it.

An edge out of sample is evidence, at a familywise level of 5% (in fact a little above it; see
"Size" below), that the arm's mean daily net return over these 200 days was above zero, under the
engine's fills and modelled costs. It does not show how large the edge is, that it lasted beyond
2026-10-19, that it survives costs above the modelled ones or a book of another size, or that it
holds in another period: the holdout is one period of about ten months. An edge in one arm says
nothing about the other. The absence of an edge is not a finding that the edge is zero (see "Power,
stated in advance").

**Size.** The test is asymptotic, and at 200 days it rejects a true null a little more often than
its nominal level. This was simulated with the evaluator's own functions (`one_sided_test`, `holm`
and `ALPHA` of `scripts/evaluate_holdout.py`, combined as `evaluate` combines them), in 8,000,000
replications, each of two arms: eight runs of 1,000,000 with seeds 2026 to 2033
(`numpy.random.default_rng`). Every Monte Carlo standard error below is under 0.01 percentage
points.

- **I.i.d. normal returns.** For 200 independent N(0, 1) daily returns (the t-statistic does not
  depend on the scale), the one-sided test rejects at 0.05 in 5.48% of the 16,000,000 simulated
  series and at 0.025 in 2.88%. For two independent arms, Holm's procedure rejects at least one
  hypothesis in 5.68% of replications, against a nominal 5%.
- **The development runs' returns.** The 628 daily net returns of S1's and S2's development runs
  (`results/v33_dev` and `results/residual_dev`, named under "Power, stated in advance"), each
  demeaned to a mean of zero, are resampled together, on the same days, in 200-day paths by the
  circular block bootstrap (`significance._circular_block_indices`). The block is 3 days, the
  larger of the two series' Politis-White lengths rounded up (`significance._auto_block`; 2.76 for
  S1, 1.71 for S2), and resampling both series on the same days keeps their correlation (0.098).
  S1's test then rejects at 0.05 in 5.35% of replications and at 0.025 in 2.77%, S2's in 5.36% and
  2.79%, and Holm's procedure rejects at least one hypothesis in 5.44%.

The registered levels are not adjusted for this. The size is stated so that a reader can allow for
it.

### Outcomes that are not crashes

The outcomes below are results or refusals of the registered code, not crashes, and the crash-fix
rule (commitment 2) does not apply to them.

**A refusal by the evaluator's input checks.** `scripts/evaluate_holdout.py` checks its inputs
before it computes anything (`check_runs`, and `residual_problems` for S2). If a check fails, it
prints the reasons, writes no report and exits 2. The runbook then stops at step 4, and neither
hypothesis is tested. The evaluator refuses the runs when:

- on calendar `holdout2026`, the strategies given are not exactly `v33_pairs`, `avellaneda_lee`
  and `v32_pairs`, or one of them is not a run of its registered kind (S1 a pairs run of profile
  `v33`, S3 one of `v32`, S2 the residual arm);
- the runs do not all come from one commit, or not from the commit given with `--expect-commit`,
  which the runbook sets to HEAD;
- they did not all read one price cache and one macro cache, or S1 and S2 did not read one
  membership index (each compared by its recorded sha256);
- a run's calendar or calendar hash is not `study_config`'s, a pairs run's profile hash is not its
  profile's, or S2's parameter hash is not `study_config.RESIDUAL_PARAMS_HASH`;
- a run is not complete, has a non-default switch, or does not record `git_dirty` as false;
- a formation used an IWV snapshot filed after the calendar's `data_end`;
- S2 did not use the committed sector map (`reference/industry_ff49.csv`, by sha256), or did not
  read its membership from the calendar's `universe.reference_root`;
- S2 records no ranking day, a ranking day selected no names or fewer than S1's rule selects, or
  S2 made no trade;
- a run has no daily net return, one that is not finite, or not one per date; its dates fall
  outside `backtest_start` to `data_end`; or they differ from another run's.

Days that lie inside the calendar but do not start on its first day or end on its last are not
refused: the report records `period_matches_calendar` as false.

**An S2 run that does not trade or selects too few names.** `scripts/run_residual_statarb.py`
writes its export with `complete` false and the reasons, and exits 2, when a ranking day selects no
names or fewer than S1's rule would, min(500, the names that pass S1's screen), because too few
screened names have a sector ETF, or when the run makes no trade (`incomplete_reasons`). The
runbook stops at step 3, after S1 and S3 have run, and does not reach the evaluation, which would
refuse such a run anyway. The evaluator takes the three arms together or not at all, so neither
hypothesis is then tested, H1 included.

**A pairs run that opens no position.** The evaluator does not ask S1 or S3 for trades. A pairs run
whose first selection, on data to 2025-12-31, yields no pair with at least 100 bars to that date
and one after it is not this outcome: it stops with an exception (`trading_system.prepare_study`).
If S1 completes without opening a position, because no formation after the first selects a pair or
no signal passes the gates, its daily net return on every day is zero, and it is tested (t = 0,
p = 0.5). If S3 opens no position, because no pair of its fixed pool passes a re-test or no signal
passes the gates, its statistics are reported the same way, untested.

## What is reported for every arm

When the evaluator's input checks pass, and whatever the result of the test,
`results/holdout2026/evaluation.json` reports for each of S1, S2 and S3:

- the first and last trading date, the number of days, total net return, and gross total return
  (before costs), both in per cent and compounded from the daily returns;
- the annualised Sharpe ratio of the daily net returns (mean over standard deviation, times
  sqrt(252)) and of the daily gross returns;
- the net Sharpe ratio's 95% circular block-bootstrap interval
  (`significance.block_bootstrap_sharpe_ci`: percentile interval, block length by the rule of
  Politis and White, 5,000 resamples, seed 42). Only the two bounds are written; the block length
  can be recomputed from the published daily returns;
- the one-sided Newey-West t of the mean daily net return, its number of lags (Bartlett kernel,
  max(1, floor(4 (n/100)^(2/9))), 4 at 200 days; for a series of fewer than three days or without
  dispersion, t is 0 and the lag is recorded as 0) and the one-sided p-value, 1 - Phi(t);
- for S1 and S2 only, the Holm-adjusted p-value and the decision (`edge_out_of_sample`, true when
  that p-value is below 0.05). S3's row is marked `descriptive`, and both fields are null;
- the Sharpe ratio annualised as Lo (2002) does for autocorrelated returns, with autocorrelations
  up to the t-test's lag, and the probabilistic Sharpe ratio (one minus the one-sided p-value of
  the observed Sharpe ratio against zero, allowing for skewness and kurtosis);
- the Sharpe ratio's standard error and its one-sided 95% upper confidence bound, under the
  asymptotic variance of `power.py` for non-normal returns with lag-1 autocorrelation, evaluated
  at the observed Sharpe ratio (`power.power_report`);
- the minimum detectable Sharpe ratio, the annual Sharpe ratio a test of the arm's own length and
  return shape detects with 80% probability, at Holm's first step (one-sided 0.025,
  `min_detectable_sharpe`) and for a single test at 0.05 (`min_detectable_sharpe_single_test`);
- the number of trades, the average and maximum gross exposure in per cent of equity (for S2, its
  stock and ETF legs together) and the number of days with open positions;
- the Ledoit-Wolf (2008) studentised bootstrap test of the difference between the arm's Sharpe
  ratio and the Gatev distance method's on their common days (difference, 95% interval, two-sided
  p-value, common days, the distance method's Sharpe ratio; 5,000 resamples, seed 42), and the
  percentile of the arm's Sharpe ratio among 200 random-pair portfolios, with their median. S1 and
  S3 report what their own run computed (`benchmark.run_benchmarks`). S2 runs no baselines:
  `compare_with_baselines` tests it the same way against S1's (`BASELINE_ARM`) if the two series
  share at least 20 days, and gives the percentile only if S2's trading dates are those of S1's
  random-pair control (otherwise null, with a note);
- the survivorship gap (`universe.PITUniverse.coverage`): for S1 at each formation, for S2 for
  each IWV snapshot on the first ranking day it governs. Each entry gives the snapshot and its
  filing date, the number of members with and without prices, the index weight of the members
  without prices and of the holdings without a ticker, and the ten heaviest of each; S2's entries
  add the members with prices but no sector ETF. S3's universe comes from the v32 universe file,
  not the point-in-time membership, so its list is empty;
- the commit its run came from.

The report also gives the familywise level (0.05), the family (S1 and S2) and the test, and under
`inputs` the calendar and its hash, the expected commit, whether the trading dates run from
2026-01-02 to 2026-10-19 (`period_matches_calendar`), each run's provenance (commit, clean tree,
time, profile or parameter hash, calendar hash, completeness, non-default switches, the sha256 of
the price cache, the macro cache and the membership index or, for S3, the universe file; for S2
also the membership root and the sector map's sha256) and the sha256 of each export file read. A
statistic a series has no value for is null: a strategy that never trades has a Sharpe ratio of
0 and no standard error, probabilistic Sharpe ratio, bootstrap interval, upper bound or minimum
detectable Sharpe.

## Power, stated in advance

The power of the test is stated here in advance, from no return dated after 2025-12-31. It is
computed with `power.minimum_detectable_sharpe` and `power.sharpe_ratio_power`, the functions
behind `power.power_report`, for the registered length of 200 sessions (2026-01-02 to 2026-10-19
on the NYSE's 2026 holiday schedule), one-sided at Holm's first step (0.025, the level the better
of S1 and S2 must reach) and at 0.05. The minimum detectable Sharpe ratio is the annual Sharpe
ratio detected with 80% probability. Both figures depend on the skewness, kurtosis and lag-1
autocorrelation of the holdout's returns, which are not known in advance, so three return shapes
are used. Two are estimated from
the 628 daily net returns, 2023-07-03 to 2025-12-31, of the v33 development run and of the
residual arm's development run, both at commit `7442705`
(`results/v33_dev/pairs_trading_results_2023_2025_unbiased.json`, `daily_equity_curve`, sha256
`0209861c37c3bb97bd9a2f79723490956a4a35af20462a396ec5493622f06b21`;
`results/residual_dev/residual_statarb.json`, `daily_net_returns`, sha256
`7bc4562bf017ce2bb31763ea97effa7e98049abbdd74a27faf452147aed2b222`). Their moments are estimated
as `power.power_report` does; kurtosis is non-excess, as `power.py` expects. The third is i.i.d.
normal returns. Only these three moments of each run are used in this section. Development results
of the v33 profile and of S2, like those of every earlier version, were seen while they were
designed (see "Why a pre-registered test").

| Return shape | Minimum detectable Sharpe, one-sided 0.025 | Minimum detectable Sharpe, one-sided 0.05 | Power at 0.025 against a true Sharpe of 1.0 / 2.0 / 3.0 |
|---|---:|---:|---|
| S1's development returns (skew 0.23, kurtosis 7.73, rho -0.065) | 2.96 | 2.62 | 16% / 48% / 81% |
| S2's development returns (skew -0.22, kurtosis 7.08, rho -0.034) | 3.09 | 2.74 | 15% / 45% / 78% |
| i.i.d. normal (skew 0, kurtosis 3, rho 0) | 3.15 | 2.80 | 14% / 43% / 76% |

These figures use the asymptotic Sharpe-ratio variance of `power.py`, with an AR(1) correction,
which approximates the registered Newey-West test. The holdout can falsify a large edge but cannot
confirm a small one. Not rejecting H0 is **not** evidence that the edge is zero. The report states
each strategy's one-sided upper confidence bound, so the reader sees which Sharpe ratios the
holdout rules out.

## Commitments

1. **One run per strategy, at the registered commit, with no code change in between.** The exact
   commands are in `scripts/run_holdout.sh`. It is run from one dedicated full clone, with the
   interpreter of the environment pinned in `requirements.txt`. The runbook checks the installed
   packages against the pins (`scripts/check_pins.py`) and records the listing. A re-run at the same
   commit skips a step that an earlier attempt at that commit finished, when every file recorded for
   that step is on disk with its recorded sha256 (`trial_attempts.is_done`). A step that failed (an
   exception, or a non-zero exit such as the residual arm's exit 2 for an incomplete run) runs again
   in full at the next attempt at the same commit: at the registered commit without
   `HOLDOUT_CRASH_FIX`, at a crash-fix commit (commitment 2) with `HOLDOUT_CRASH_FIX` set again,
   because the frozen paths still differ from the registered commit. So would a finished step whose
   recorded files had gone missing or changed. The commitment is that no file recorded for a
   finished step is deleted, moved or replaced afterwards, other than by the runbook itself when
   every step runs again at a crash-fix commit (commitment 2): once the data step is recorded as
   done, the holdout caches are not re-fetched, and every later attempt reads them with the sha256
   that step recorded. The code does not check this. Every attempt is on record in
   `results/trial_attempts.jsonl`.

   Before this commit, the same script was run twice as a dress rehearsal (`--rehearsal`), each time
   from a dedicated clone, on calendar `rehearsal2025`. That calendar is the holdout shifted one
   year back inside the development period (2022-01-01 to 2025-10-17, first signal 2025-01-02). The
   first rehearsal, `rehearsal2025`, ran at commit `d83e033`. The second, `rehearsal2025b`, ran at
   commit `6aaf7ef`, after the changes that followed the first (among them the data step's second
   pass over failed requests, `.gitignore` added to the frozen paths and the input hash file
   `reference/holdout_inputs.sha256`). The second rehearsal read the original `data/marketcap.csv`.
   Between `6aaf7ef` and the registered commit, the frozen paths (see "Status and freeze rule")
   differ in this file and in two files under `reference/`: the input pin `holdout_inputs.sha256`
   and its description in `reference/README.md`, changed for the rebuilt `data/marketcap.csv`
   (commits `b68e852` and `6556b66`; see "Universe"), which gives the loader the same symbols. Each
   rehearsal took one attempt, and every step of the runbook completed in it (universe, data, S1,
   S3, S2, evaluation). Their attempts are in `results/trial_attempts.jsonl`, their exports and
   evaluations in `results/rehearsal2025/` and `results/rehearsal2025b/`, and their records in the
   entries of trials `rehearsal2025` and `rehearsal2025b` in `results/trial_registry.jsonl`, whose
   `head`s are `d83e033` and `6aaf7ef`; `git diff` between either commit and the registered commit
   shows what changed after it. The second rehearsal fetched its prices afresh, about five hours
   after the first: the two caches hold the same symbols with the same fetch outcomes, their
   adjusted prices differ by at most 1.2 parts per million and their volumes not at all, the two
   rehearsals made the same trades, and every statistic of their evaluations agrees to four
   significant figures. The rehearsals tested the runbook, not the hypotheses: no holdout decision
   depends on their results. A rehearsal runs every check except the freeze checks, which need the
   registered commit, and the checks that only the holdout applies: the evaluator's check that
   exactly the three registered strategies are given, which it applies on calendar `holdout2026`
   only, and registration's refusal of a run that is not from the attempt's commit or not from a
   clean tree, or of a published export that is not the file evaluated, which it applies only with
   `--prereg-commit`, passed by the runbook only for the holdout. It also does not exercise three
   holdout paths. First, its step 1 rebuilds that year's committed snapshots offline, byte for byte,
   instead of downloading the sealed filings and mapping new identifiers with OpenFIGI. Second, its
   S1 and S2 read their membership from the committed `reference/`: `universe.reference_root`
   returns `reference/` for a calendar that ends before 2026-01-01, so they do not read the step-1
   output. Third, the seal's check never runs: `assert_unsealed` returns at once for data that end
   before 2026-01-01, and a rehearsal sets no `PAIRS_UNSEAL`. These paths run for the first time in
   the holdout. The rehearsal caches were fetched months after their last date, so their adjusted
   price levels carry later corporate actions. The holdout cache is fetched when the holdout runs,
   shortly after 2026-10-19.

   Runs on the same calendar outside the runbook came before them, in the working clone while its
   code was still changing: S1 and S3 on 2026-10-20 (their exports are not published), and the S2
   runs of a review of S2's universe rule. That review measured the rehearsal-calendar P&L of the
   names in S2's then universe that fail S1's screens, before S2 adopted S1's screens;
   `residual_statarb.py`'s docstring records the measurement and the reason given for the change.
   Operator's attestation: no hypothesis, test or decision rule was changed in response to
   rehearsal results.
2. **Crash-fix rule.** A crash is a step that stops with an exception or a non-zero exit, other than
   the outcomes listed under "Outcomes that are not crashes". A failure caused by something outside
   the code, such as a network error, is handled by running the step again at the same commit
   (commitment 1). A crash in the code may be fixed only in code that cannot change a trading
   decision, by a new commit run with `HOLDOUT_CRASH_FIX="<what was fixed>"`. The runbook refuses a
   fix that changes anything in `NEVER_FIXED`: this file, `pairs_trading/study_config.py`,
   `pairs_trading/significance.py`, `scripts/evaluate_holdout.py`, the runbook itself
   (`scripts/run_holdout.sh`), the attempt and registry scripts (`scripts/trial_attempts.py`,
   `scripts/register_trial.py`), the environment check (`scripts/check_pins.py`),
   `requirements.txt`, `pyproject.toml`, `.gitignore` and everything under `reference/` (the sealed
   accession list, the pinned input hashes, the CUSIP map, and the industry and sector-ETF map,
   which the evaluator compares with the copy at the run's own commit). It refuses any other change
   to the frozen paths since the registered commit unless `HOLDOUT_CRASH_FIX` is set to a non-empty
   text; a commit that changes nothing under them is not checked. It does not check that a crash
   occurred or that the change is a crash fix. The check runs from the copies of the runbook and of
   `pairs_trading/study_config.py` (which finds the registered commit) at the crash-fix commit, so
   it is the registered check only while both are unchanged: a commit that changed either would run
   its own version. That they are unchanged is therefore a commitment, open to checking with `git
   diff <registered> <crash-fix commit> -- scripts/run_holdout.sh pairs_trading/study_config.py`.
   The engine (`pairs_trading/` apart from `study_config.py` and `significance.py`) and the other
   scripts are not on the list: a change to them is stopped only by this commitment and shown in
   the published diff. The
   diff of the frozen paths since the registered commit (`git diff <registered> HEAD --
   pairs_trading scripts reference docs/PREREGISTRATION.md requirements.txt pyproject.toml
   .gitignore`) is written to `logs/holdout2026_crash_fix_<first 12 hex digits of the crash-fix
   commit>.diff`. Its sha256 goes into the attempt's note, and it is published in
   `results/holdout2026/logs/` with every attempt's logs when the trial completes. Every step runs
   again at the new commit. The exports of an attempt superseded by a fix are overwritten: only the
   final attempt's exports are published, together with every attempt's logs. Apart from re-running
   a failed step at the same commit (commitment 1), this is the only way a strategy runs on the
   holdout more than once, and every such run is on record. That a fix cannot change a trading
   decision is a commitment, open to checking only through the published diff.
3. **Every attempt is on record.** Every attempt is appended to `results/trial_attempts.jsonl`:
   - when it starts, with its number, its commit, the registered commit, any note and the sha256 of
     the environment listing;
   - after each step, with the sha256 of the step's input and output files;
   - when it fails, with the failing step, and when the trial completes.

   A refusal by the step-0 checks comes before an attempt starts and is not recorded; nothing has
   run at that point. The completed trial is appended once to `results/trial_registry.jsonl`, and a
   name already registered is refused before anything runs. The entry holds all the trial's
   attempts and the evaluation's input hashes. Registration is refused unless every run comes from
   the registered HEAD with a clean tree and the published exports are the files evaluated. These
   records are files in the clone: the runbook neither commits nor pushes them. The operator pushes
   a copy of `results/trial_attempts.jsonl` to the remote after every attempt, failed or completed,
   without committing it on the clone's checked-out branch: a commit there moves HEAD, and every
   step would then run again at the new commit. Because a second clone would start with no record
   of the first, the test runs from one clone only. Both are commitments, not checks. An attempt
   that cannot complete, including one whose inputs the evaluator refuses, stays on record. If the
   registered test cannot be completed under these rules, that outcome and every attempt's logs are
   published in place of a result.
4. **Publication whatever the sign.** The results are published in full in `results/holdout2026/`,
   on the site and in the paper, whether they are positive, negative or null. That covers the three
   runs' exports, the evaluation, the membership built in step 1, the price-fetch manifest and
   every attempt's logs. The site's and the paper's presentation of the result is written after
   it: at this commit the paper's builder stops when the holdout has been evaluated
   (`build_paper.tables`), and its tables for the result are added after the trial is registered.
5. **No change in response to the holdout.** No strategy, parameter, threshold, test or decision
   rule is changed in response to the holdout. Any idea it suggests needs data after 2026-10-19.

## The runbook

From a dedicated, full (not shallow) clone at the registered commit, pushed, with
`reference/holdout_inputs.sha256` committed and `data/marketcap.csv` present and matching it:

```bash
PYTHON=/path/to/venv/bin/python bash scripts/run_holdout.sh
```

`PYTHON` is the interpreter of the environment pinned in `requirements.txt`. The script runs these
steps. Steps 1 to 4 are recorded in `results/trial_attempts.jsonl` when they finish, and a failure
at any step after step 0 is recorded with the step's name. Each attempt's steps are logged to
`logs/holdout2026_a<N>_<name>.log`, where `<name>` is `universe`, `data`, `v33`, `v32`, `residual`
or `evaluation`. A refusal by the step-0 checks is not recorded as an attempt.

| Step | What it does |
|---|---|
| 0. checks | The freeze rule above; `PAIRS_*` cleared, `PYTHONHASHSEED=0`; the name `holdout2026` not yet registered; packages equal the pins; on a first attempt, no holdout cache and no `results/holdout2026/`. Then `PAIRS_EXPECTED_COMMIT` is set to HEAD and `PAIRS_UNSEAL` to the registered commit. |
| 1. universe | `scripts/build_pit_universe.py --include-sealed --sealed-out data/holdout2026_reference/universe`: the committed snapshots copied, the two sealed ones built from their registered accessions. |
| 2. data | `python -m pairs_trading.main --profile v33` and `--profile v32`, `--calendar holdout2026 --fetch-only`: one price cache and one macro cache for every arm. |
| 3. strategies | S1: `python -m pairs_trading.main --profile v33 --calendar holdout2026`; S3: the same with `--profile v32`; S2: `scripts/run_residual_statarb.py --calendar holdout2026`. |
| 4. evaluate | `scripts/evaluate_holdout.py --calendar holdout2026 --expect-commit <HEAD>` on the three runs: input checks, then the registered test and the report, `results/holdout2026/evaluation.json`. |
| 5. publish and register | The three exports (`results/holdout2026/v33_pairs`, `v32_pairs`, `residual`), the step-1 membership, the price-fetch manifest and every attempt's logs are published. Then the trial is registered in `results/trial_registry.jsonl`. |

The script stops if HEAD moves or a frozen file changes while it runs. When it finishes, it prints
`complete: results/holdout2026/ (commit results/ now)`. The operator then commits and pushes
`results/`; the script does not. The `logs/` rule of `.gitignore` also matches
`results/holdout2026/logs/`, so those files are added with `git add -f`, as both rehearsals' logs
were. If the script stops at one of the outcomes listed under
"Outcomes that are not crashes", it publishes nothing: the operator publishes every attempt's logs
and the exports written so far, under commitment 3.
