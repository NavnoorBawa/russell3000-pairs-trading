# Built with free resources only

Every input to this study — data, code, papers, tools — is free. This page lists what each
free resource provided, and, just as importantly, what free resources could NOT provide and
how the study bounds or discloses each gap. Nothing here required an account, an API key or
a paid licence.

## Data

| Resource | What it gives the study | Notes |
|---|---|---|
| Yahoo Finance chart API (`query2.finance.yahoo.com/v8/finance/chart`) | daily OHLCV, dividends and splits, ~3,000 stocks and the 11 sector SPDRs: 2020-2025 for the development period (no bar after 2025-12-31 has been fetched); 2023-2026 for the holdout, once the registered commit unseals it | called directly; split-unadjusted prices are reconstructed for point-in-time screens, and anchored to N-PORT's price at each snapshot for point-in-time members |
| SEC EDGAR N-PORT filings of the iShares Russell 3000 ETF (IWV) | point-in-time Russell 3000 membership, quarterly 2019-2025 (26 snapshots, ~2,600 equity holdings each), and each holding's price on the snapshot date | `scripts/build_pit_universe.py`; the index provider's own constituent files are not free |
| OpenFIGI mapping API | CUSIP -> ticker for every N-PORT holding; with N-PORT's own reported tickers, issuer successions and mappings checked against N-PORT's value per share, 98.96-99.99% of index weight is mapped | keyless tier |
| SEC EDGAR company submissions | SIC industry code per company | mapped to the Fama-French 49 industries |
| Kenneth French Data Library | Fama-French 5 factors, momentum, short- and long-term reversal and the 1-month T-bill (daily); the SIC -> 49-industry definitions | the eight-factor attribution (truncated at each calendar's end; the files reach 2026); the 1-month T-bill return of the evidence block (<!--m:study.dev.facts.tbill_rf_pct-->13.38<!--/m-->% over the main backtest: French's daily RF, the one-month bill's return, compounded over the backtest's trading days); industry classification |
| FRED (St. Louis Fed) | 3-month T-bill (DTB3) and effective fed funds rates | DTB3 is the anatomy's cash comparison: <!--m:study.dev.facts.cash_tbill_pct-->12.72<!--/m-->% over the main backtest's own dates, against the strategy's <!--m:main.total_return_pct-->−0.39%<!--/m--> (`anatomy.cash_returns`: the three-month bill's investment yield accrued over calendar days, the first day earning nothing). The two T-bill figures differ because they are different bills accrued differently; the site and the paper quote the DTB3 figure. The fed funds rate is read by no study code |
| Nasdaq Trader symbol directory | primary listing venue per stock | closing-auction cost references differ by venue |
| Nasdaq stock screener | the market-cap universe of the v32 design | ranked on 2026-10-18, so the frozen v32 arm of the holdout is descriptive only |

## Code (all open source)

numpy, pandas, scipy, statsmodels (cointegration tests, HAC regressions), scikit-learn (the
gradient-boosting ranker ablation), arch (model confidence set; the SPA and Romano-Wolf tests
are re-implemented and checked against it), matplotlib, Observable Plot and d3 (the site's
charts), Typst (the paper), pytest and Hypothesis (tests), Playwright and axe-core (site
checks), GitHub Actions and GitHub Pages.

## Research (all freely readable)

Avellaneda & Lee (2010); Bertram (2010); Gatev, Goetzmann & Rouwenhorst (2006); Do & Faff
(2010, 2012); Krauss (2017); Clegg & Krauss (2018); Clegg (2014); Bailey & López de Prado
(2012, 2014); Bailey, Borwein, López de Prado & Zhu (2017); López de Prado, Lipton &
Zoonekynd (2025); Hansen (2005); White (2000); Romano & Wolf (2005, 2016); Hansen, Lunde &
Nason (2011); Harvey, Liu & Zhu (2016); Ledoit & Wolf (2008); Politis & Romano (1994);
Politis & White (2004); Newey & West (1987); Lo (2002); Almgren et al. (2005); Tóth et al.
(2011); Frazzini, Israel & Moskowitz (2018); Goyal, Jegadeesh & Wu (2025); Muravyev, Pearson &
Pollet (2025); D'Avolio (2002); Kendall (1954).

## What free resources could not provide — and what the study does about it

| Gap | Effect | Treatment |
|---|---|---|
| Price histories of delisted stocks (CRSP, paid vendors) | survivorship: point-in-time members that later delisted cannot be traded | measured at every formation date (`universe_by_formation` in every export): in the v33 development run, after the cache's top-up, <!--m:study.dev.facts.gap_first_pct-->3.33<!--/m-->% of index weight at the first formation (snapshot 2022-12-30) and <!--m:study.dev.facts.gap_last_pct-->1.08<!--/m-->% at the last (snapshot 2025-06-30); the measurements before the top-up are in `reference/README.md`. By the fetch outcomes in `results/v33_dev/price_fetch_manifest.json`, <!--m:study.dev.facts.gap_first_not_found_pct-->2.75<!--/m--> points of the first formation's gap are names the vendor no longer serves (HTTP 404), largely acquired or delisted since, <!--m:study.dev.facts.gap_first_fetch_failed_pct-->0.34<!--/m--> points failed the fetch and <!--m:study.dev.facts.gap_first_data_checks_pct-->0.10<!--/m--> failed the data checks. Takeover targets and failures are the names likeliest to have had jump-driven spread breaks, so the gap probably flatters a convergence strategy; its effect is not measured |
| The index provider's constituent lists | IWV's holdings stand in for the index (about 97% of its names; quarterly, not daily) | snapshots used strictly as of their report date |
| Tick, quote and closing-auction data (TAQ, exchange feeds) | spreads and impact cannot be measured per stock and day | published estimates (Goyal-Jegadeesh-Wu 2025 auction impact, Frazzini et al. 2018) and a band test against them; cost scenarios re-run in full |
| Stock-borrow fees and availability (Markit, S3) | borrow is a single fee, specials are not modelled | the median buy-side fee plus 1% and 3% stress runs (net Sharpe <!--m:study.dev.cost_sensitivity.scenarios.borrow_1.full.sharpe-->−0.26<!--/m--> and <!--m:study.dev.cost_sensitivity.scenarios.borrow_3.full.sharpe-->−0.71<!--/m--> in the full re-runs) |
| Point-in-time industry classification (GICS history) | today's SIC code is used for every date | industries rarely change; affects which pairs are candidates, not prices |
| Ticker changes with a new CUSIP | a renamed or reorganised stock can look like a delisted one | remapped through N-PORT's reported ticker, the issuer's successor CUSIP, or a price check against N-PORT's value per share that gives 85 identifiers their successor's line; a search over every identifier still without a priced ticker finds no other |
| Corporate actions after the price download | the vendor back-applies later splits and dividends to the whole history, so early price levels (the $5 screen, per-share costs) carry them | `Close_PIT` anchored to N-PORT's price at every snapshot date: in the v33 development run the median rescaling exceeded 10% for <!--m:study.dev.facts.anchor_moved-->732<!--/m--> of <!--m:study.dev.facts.anchor_symbols-->2,538<!--/m--> symbols (ratios from 1/<!--m:study.dev.facts.anchor_min_ratio_inv-->80<!--/m--> to <!--m:study.dev.facts.anchor_max_ratio-->25.6<!--/m-->); returns use the adjusted close and are unaffected |
