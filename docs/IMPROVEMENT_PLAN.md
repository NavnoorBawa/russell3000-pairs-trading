# Improvement plan: taking this project to a top research-review standard

For any future Claude Code session (or person) continuing this project. `docs/HANDOFF.md` says
where things stand, the rules, how to set up and how to publish. This file says **what to improve,
in what order, and how to know each step is done.** Read both; HANDOFF.md's rules override
anything here.

The standard aimed at is the one a top quantitative fund's research review applies to an
intern's final study: **rigour, reproducibility, honesty and presentation.** It is reached by
making the work unimpeachable, not by finding a positive result. The published answer, "no
detectable edge", stays unless a new, properly pre-registered study with its own future holdout
says otherwise. The 2026 holdout is spent and can never be re-run or tuned toward.

This plan was written from the project's own record and from four independent reviews run on
27 October 2026 (research rigour, engineering and reproducibility, scholarly publication, and the
research programme), each of which read the repository and checked numbers against the raw
results files. Items cite what the reviewers verified.

---

## 1. Honest assessment

### Already at or above the bar (keep these; do not undo them)

- **Falsifiable design.** `docs/PREREGISTRATION.md` fixes hypotheses, a one-sided Newey–West
  test, Holm across exactly two arms, a `NEVER_FIXED` list and a crash-fix rule; the seal is
  enforced in code (`study_config.assert_unsealed`); two scripted rehearsals; an append-only
  `results/trial_attempts.jsonl` and `trial_registry.jsonl` (10 trials, including the exploratory
  v33 run and the second family's superseded rules); test size simulated (5.48% per arm) and power
  stated in advance (16% at a true Sharpe of 1; MDE 2.96). The page says plainly that the test is
  sealed, not prospective.
- **Every published number is a checked marker** (`scripts/check_published_numbers.py`,
  `assets/verify.js` with a parity test). A reviewer recomputed the main Sharpe, holdout t and p,
  Holm adjustments, per-trade gross and cost bp, pair concentration, variant counts and the
  snooping statistics from the raw exports: all matched.
- **Data snooping** handled on a family declared before any variant ran
  (`results/variant_family/declaration.json`, 2026-10-20): SPA, Reality Check, Romano–Wolf, model
  confidence set, PBO 0.794, deflated Sharpe at the entropy effective rank 13.7; the design is
  explicitly not re-chosen.
- **Start-date dependence measured** (`results/v33_dev/robustness.json`: 12 starts, matched-day
  comparisons, common-window rank 3 of 12); the walk-forward is correctly called the same rule
  from another start (621 shared days), not a second confirmation.
- **Evidence layer with reconciled accounting**: the shortfall decomposition reproduces every
  trade to within $0.017; decay reports a month-clustered t beside the naive one; the exit race is
  tested against random-walk, gambler's-ruin and OU nulls; persistence on three pair sets; an
  eight-factor attribution exposing the short-term-reversal loading (t = 4.01); synthetic
  known-answer validation with a forced-null look-ahead check.
- **Cost model sourced and stress-tested** (band test against published estimates in
  `tests/test_cost_model_zoo.py`; every scenario a full re-run plus a fixed-trade re-pricing;
  threats table gives direction and size, including self-critical ones).
- **An unflattering engineering log** (`docs/PROGRESS.md`) and a page that opens with the answer,
  lets a reader check any number, links every reference, works without JavaScript and in print.

### Still short of the bar

1. **(P0) The development and holdout price caches were lost, so no development number can be
   rebuilt from an archived input.** `results/v33_dev/headline_metrics.json` pins the cache at
   sha256 `3a9a93cc…a7be`; `docs/PROGRESS.md` records the loss of the working storage by
   2026-10-22. README "Reproduce" and the page's Reproduce section read as if the pinned input
   still existed. No re-fetch reproduction has been attempted, and the fetch manifest has no
   per-symbol content hashes, so a re-fetch cannot be diffed symbol by symbol.
2. **The random-pair control runs through the Gatev rule, not this engine**, and the page says a
   control on the strategy's engine "is planned". A finished note cannot carry an open promise.
3. **No single-command rebuild, no container, no lock file.** `requirements.txt` pins 14 direct
   packages; the holdout's environment listing shows 43 transitive packages pinned nowhere.
4. **`results/variant_family/` and `results/validation/` have no manifest or provenance block**
   (no commit, cache hash or environment), although they carry the SPA p, PBO and deflated Sharpe.
5. **The causality (look-ahead) tests and the CI known-answer gate run only under the v32
   profile** (`tests/conftest.py` pins `PAIRS_PROFILE=v32`); the published design is v33.
6. **Browser behaviour is not under CI**, and only Chromium was ever tested.
7. **The paper and the page do not say the same thing in the same words**: the page's seven key
   findings and the pre-registration timeline are absent from `paper/main.typ`; exhibit titles
   differ; the work has three different titles (README, `CITATION.cff`, page/paper); no release,
   no DOI, no reference list on the page (at least twelve author-year citations resolve to
   nothing).
8. **Length.** 16,254 visible words plus 1,611 of front matter; the Key figures tiles repeat five
   of the hero's six rows; inference is split across Sections 3 and 7.
9. **Any new study needs a layer outside the frozen code.** `study_config.py` hard-codes
   `SEALED_FROM = '2026-01-01'`, so under the freeze rule the frozen engine cannot run any
   post-2025 study directly. And nothing is filed for 2027: unless a pre-registration is pushed
   before 2027-01-04, the next holdout will again be "sealed, not prospective".

---

## 2. Roadmap

Each item: what, why, how to verify. Work by phase; do not start a lower phase while a P0 is
open. Record each finished item in the Done table at the end with its commit and effect. Never
change a published number, result, claim or caveat without evidence; if evidence says one must
change, stop and write it up for the owner first.

### Phase A — Reproducibility (P0 first)

| # | P | Item | Done when |
|---|---|---|---|
| A1 | P0 | **Re-fetch reproduction of the development run.** From a fresh fetch at HEAD, run the development calendar only (`scripts/run_dev_studies.sh main anatomy costs residual variants validation`; never the holdout) and publish it as `results/v33_dev_refetch/` with `publish_run.py` (not `--replace`), leaving `results/v33_dev/` untouched. Add a drift table to the page's Reproduce section and the README: original vs re-fetch for every headline marker. Reword README "Reproduce" and the page's Reproduce note to say the pinned caches were lost with the working storage and give the measured drift. | `results/v33_dev_refetch/` has `MANIFEST.json`, `headline_metrics.json`, `price_fetch_manifest.json`; drift values are markers and `check_published_numbers.py` passes; `results/v33_dev/` and `results/holdout2026/` are byte-identical to before. |
| A2 | P0 | **Hash every cache; archive privately.** `scripts/hash_cache.py` records a sha256 per symbol (Close, Volume, Dividends, Splits) plus the manifest, written as `results/<run>/price_cache_hashes.json` for every run published from now on. Archive the re-fetch price and macro caches privately (owner's Drive or a private GitHub release asset: free, not redistribution) and record location and sha256 in that run's `MANIFEST.json`. | A test asserts every `results/*/MANIFEST.json` dated after 2026-10-27 names an archive location and sha256. |
| A3 | P1 | **Lock the environment; ship a container.** `requirements.lock` generated from the holdout's environment listing (`results/holdout2026/logs/holdout2026_environment_*.txt`, minus pip/setuptools); CI's pinned leg and both runbooks install from and verify against it (`scripts/check_pins.py requirements.lock`); a `Dockerfile` (python 3.12 slim, CPU torch 2.13.0 with `--no-deps`, the lock, typst 0.15.0, Node 22 + Playwright). Fix the stale header in `requirements.txt` and `SECURITY.md` that still says the pins produced withdrawn v31.1 results. | `docker build` succeeds; inside it `check_pins.py requirements.lock` exits 0 and `pytest -q` passes. |
| A4 | P1 | **`make all`.** A Makefile with targets `data`, `site` (hero, timeline, links, fonts), `paper`, `check`, `all`, in the right order; the page's own Reproduce block gains the CPU-torch step it omits. | `make all` from a clean clone on CI ends green with `git status` clean; added as a CI job. |
| A5 | P1 | **The dev runbook regenerates `results/v33_dev/` completely.** Add a `robustness` step after `publish`; make `publish_run.py --replace` refuse to drop files its source lacks unless named; route `variant_family.py` through `publish_run.py`. | A hermetic test (modelled on `tests/test_holdout_protocol.py`) runs the runbook on a synthetic market and the output file set equals the committed manifest's keys. |
| A6 | P1 | **Provenance for the variant family and validation; repo-wide manifest integrity.** Future runs write a `run_config` block and publish through `publish_run.py`; for the committed files add `results/variant_family/PROVENANCE.md` and `results/validation/PROVENANCE.md` stating only what the record supports. `tests/test_results_integrity.py` verifies every manifested file's sha256. | Every directory under `results/` has `MANIFEST.json` or `PROVENANCE.md`; the integrity test fails when any manifested byte changes. |
| A7 | P1 | **Causality tests and known-answer validation under v33.** Parametrise `tests/test_leakage.py` (and the sizer/cool-off causality test) over `('v32', 'v33')` using the fixture pattern of `tests/test_v33_design.py`; add `--profile v33` to `scripts/synthetic_validation.py` with a synthetic point-in-time universe and industry map; run it in CI. No change to `pairs_trading/`. | `pytest tests/test_leakage.py -v` lists each causality test per profile; `synthetic_validation.py --profile v33 --seeds 2` exits 0 in CI. |
| A8 | P2 | Headline smoke test (recompute main Sharpe, return, trades from the export); measure coverage of `scripts/`; a post-deploy job that compares the live files' sha256 with the repository's; decouple the paper from `index.html`'s hash so a page edit no longer re-commits a 1.2 MB PDF. | Each exists in CI and is green. |

### Phase B — Research completeness

All of Phase B is **descriptive** on the development period: no new hypothesis test is counted
as confirmatory, no design is chosen from it, and nothing touches `pairs_trading/`.

| # | P | Item | Done when |
|---|---|---|---|
| B1 | P1 | **The promised control on the strategy's own engine.** `scripts/placebo_control.py`: per formation, placebo A draws as many pairs as the run selected from same-industry candidates that pass the common-days and correlation screens but have Engle–Granger p ≥ 0.05; placebo B draws uniformly from all same-industry candidates; both run through the identical engine, sizing, gates, costs and start date (`run_comprehensive_backtest(…, pair_windows=…)` and `get_pair_state` already accept external pairs); 200 seeded draws each. Report Sharpe, gross bp and trade distributions, the run's percentile in each, and a Ledoit–Wolf difference vs the median draw. Then replace "is planned" on the page, in `paper/main.typ` and README with the result. If B1 is deferred, replace "is planned" now with a statement of fact ("was not run; the comparison is a baseline for the distance method, not for this engine"). | `results/v33_dev_refetch/placebo_control.json` with ≥200 draws per placebo, seed, schedule hash and cache sha256; new exhibit and markers; `grep -niE 'planned\|forthcoming' index.html paper/main.typ README.md` finds no unfinished analysis. |
| B2 | P1 | **Publish each run's selection decisions per formation.** `scripts/export_formations.py` (calls `prepare_study`; no engine change) writes `results/<run>/formations.json`: per formation the screened universe, candidate counts by industry, every selected pair with p-value, half-life, correlation, quality, hedge ratio and window dates. This is the only level at which a re-fetch can be diffed without redistributing prices. | File exists for the re-fetch run with per-formation counts equal to `run.log`'s (317, 229, 170, 128, 232, 187); a test asserts every pair in `all_trades` appears in the formation in force on its signal date. |
| B3 | P1 | **Spread estimators: back the claim or soften it.** `docs/EXECUTION_COSTS.md` line 79 says Corwin–Schultz, Abdi–Ranaldo and EDGE "were tested and rejected" for liquid names, but no script or result in the repository backs that test. Either commit the measurement (script, json, one sentence) or reword the document to say the estimators are not used. *(Replaces an earlier entry here that proposed Corwin–Schultz calibration without knowing this.)* | Either `results/…/spread_estimators.json` with its script exists and the sentence cites it, or `EXECUTION_COSTS.md` no longer claims a test. |
| B4 | P1 | **Development-period power.** State the development sample's minimum detectable Sharpe at 80% power under its own return moments (`pairs_trading/power.py`), next to "cannot tell 0 from 0.5". | Marker on the page and in the paper. |
| B5 | P2 | **Descriptive extension, 2020-01 to 2023-06** (formations from the 2019-12-31 snapshot; point-in-time membership starts at the 2019-09-30 N-PORT filing, so earlier periods are *not* feasible). Define the calendar in the `studies/` layer (Phase E, E1), run once through the frozen engine, publish with a manifest, label "descriptive extension" with its own threats row giving the survivorship gap per formation. No p-value reported. | `results/<name>/MANIFEST.json`; the page row's gap per formation as markers; no test statistic. |
| B6 | P2 | Cross-sectional diagnostics (pair concentration; per-industry and per-size trades, gross edge and cost), reported not acted on; the power of the post-formation cointegration test behind "6 of 115"; likelihood ratios for what the holdout says about S1 and S2; S2 under its two superseded universe rules; the survivorship gap bounded in P&L terms; a statement of which design dimensions the variant family does not cover. | One exhibit or sentence each, every number a marker. |

### Phase C — Engineering and testing

| # | P | Item | Done when |
|---|---|---|---|
| C1 | P1 | **Browser job in CI, three engines.** `tests/site/` (Node 22, Playwright and axe-core pinned with a lockfile): serve the repo; for chromium, firefox and webkit at 390 and 1440 px in both themes assert no console or page error, no request to another origin, 24 charts drawn after scrolling, deep links land (`#ex-17`, `#f3`, `#t-scenarios`, `#bottom-line`), `Verify.audit()` reports zero non-ok markers, axe 0 violations, layout shift < 0.01. | Job green on `main`; a deliberately thrown error in one exhibit on a branch makes it fail. |
| C2 | P1 | **Visual regression.** Reference screenshots (opening, one exhibit, one phone card table, print page 1) diffed with a small tolerance. | Baselines committed; job green. |
| C3 | P2 | Phone rotation keeps the reader's place; `exhibits.js` (2,858 lines) split by responsibility with identical behaviour; one publication library instead of path hacks and three copies of the rounding rule; every script accounted for in README with a `--check` where it writes a committed artefact. | Tests unchanged and green; no results file differs. |

### Phase D — Presentation and publication

| # | P | Item | Done when |
|---|---|---|---|
| D1 | P1 | **One source for shared prose.** A `findings` block and an `exhibit_titles` map in `paper/build/paper_data.json`, rendered into both the page (a generator like `build_hero.py` writing marked blocks) and the paper; add the Key findings box and the pre-registration timeline to `paper/main.typ`. | A test asserts every exhibit title on the page equals the paper's, and each of the seven findings appears verbatim in the compiled paper. |
| D2 | P1 | **No open promise** ("is planned") in a finished note. See B1. | The grep in B1 is clean; `build_paper.py --check` green. |
| D3 | P1 | **Citation record.** One title (the page/paper's) in README's H1 and as `CITATION.cff` `preferred-citation`; tag `v33.0.0` at the holdout-publishing commit and cut a GitHub release; connect the repository to Zenodo first so the release mints a DOI; put the DOI in `CITATION.cff`, the page (citation block, BibTeX, JSON-LD) and the paper; add a content licence (e.g. CC BY 4.0 for the note, MIT stays for code). *Owner clicks: Zenodo connect, release publish.* | `cffconvert --validate` exits 0; the tag and release exist; the DOI resolves and the same string appears in all four places. |
| D4 | P1 | **Reference list on the page.** `scripts/build_references.py` writes a marked References block from `paper/references.bib` (ids `ref-<bibkey>`, DOI links); `link_refs.py` links every in-text author-year citation to its entry, as it does "Exhibit N". | `link_refs.py --check` fails on any unlinked author-year citation; a test asserts the page's `ref-*` ids equal the bib keys. |
| D5 | P1 | **Cite methods where used; add the verified gaps.** Works the code cites but the paper does not (Harvey & Liu 2015; Roy & Vetterli 2007 for the effective rank; MacKinnon 1994 for Engle–Granger p-values; Sullivan, Timmermann & White 1999), the pre-registration rationale (Harvey 2017; Nosek et al. 2018; Arnott, Harvey & Markowitz 2019), and the design lineage (Vidyamurthy 2004; Elliott, van der Hoek & Malcolm 2005). Each only at the sentence that uses it; the existing test forbids uncited entries. | `test_every_reference_is_cited` passes; each new DOI resolves. |
| D6 | P1 | **Shorten the reading path.** Drop the Key figures tiles (the hero prints every number but SPA p; add that as a note line); merge Section 7 into Section 3 as subsections in the paper's order; move the 2026-inputs inventory to an appendix table linked from a ≤80-word threats cell that keeps direction, size and mitigation; estimator detail beyond ~120 words per exhibit note into "Method notes" disclosures. No caveat removed. | Visible words ≤ 12,000 with the same marker count; every threats row title still present; all checks green. |
| D7 | P1 | **SSRN / arXiv q-fin package.** In `paper/main.typ`: a section headed "Abstract", keywords and JEL codes (G11, G12, G14, C12, C58), affiliation ("Independent researcher") and ORCID, "Competing interests: none. Funding: none; free data and compute only.", a labelled "Data and code availability" statement. `paper/submission/README.md` with the abstract and the steps. *Owner submits.* | `pdftotext` of page 1 contains "Abstract", "JEL" and the ORCID; all fonts embedded; `build_paper.py --check` green. |
| D8 | P2 | One point per exhibit (split the two-finding ones, cap title length); README as a front door rather than a second copy of the note; `docs/CORRECTIONS.md` (dated, from the review rounds in PROGRESS.md) linked from the page's History, with a version line on paper and page; mobile Lighthouse performance ≥ 95 (inline critical CSS; a second page for the audit-trail sections with anchors preserved). | Each verified as stated. |

### Phase E — New research, only as new pre-registrations

**Verdict on the engine** (from the programme review): a sound measurement instrument (causality
tests, known-answer validation, provenance in every export, the Profile/Calendar seam), but not an
ablation harness: the pair quality score embeds the selection statistic and the risk manager sizes
by it. **Wrap it; never fork or edit it.**

**Data policy from here on:** 2026 daily data may serve as formation or development data for a
new design (holdout2026 is registered and public); **no 2026 daily return enters any new test
statistic**; every new design choice states whether a 2026 result motivated it; the new
pre-registration names the 2026 result as seen and carries the trial count (10) forward.

| # | P | Item | Done when |
|---|---|---|---|
| E1 | P0 | **A `studies/v34/` layer outside the frozen paths.** A new package that imports the frozen engine and constructs Calendar/Profile objects directly; its own seal (`SEALED_FROM_V34 = '2027-01-01'`, keyed by the single-adding-commit rule to `docs/PREREGISTRATION_V34.md`); its own runbook (the only place that sets the 2026 unseal, for now-public 2026 data, and the v34 unseal after its own checks); its own evaluator; registration through the generic `scripts/register_trial.py`. An **ablation harness** `run_pairs(pairs_by_formation, gates, sizing)` that takes an explicit pair list from any selector (v33's, correlation-only, Gatev distance, random same-industry), applies the engine's gates as one named, hashed set, and reports rule-level trades (`anatomy.rule_trades`) as the primary outcome. | `git diff c4930fd..HEAD -- pairs_trading reference docs/PREREGISTRATION.md` is empty; a hermetic test shows the v34 seal refuses 2027-01-05 without the v34 registration commit and accepts with it; the harness configured as v33 reproduces the engine's exact trade list on `tests/synthetic_market.py`. |
| E2 | P0 | **File `docs/PREREGISTRATION_V34.md` before 2027-01-04**, with a third-party timestamp (a Zenodo record or a GitHub release of the filing commit). Content, as a diff of the 2026 document: S1 (profile v33, hash `d54d21314c22`) and S2 (residual params hash `2d50e388fb12`) unchanged as the confirmatory family, Holm across the two; calendar `holdout2027`, selection cutoff 2026-12-31, first signal 2027-01-04; a group-sequential plan with K yearly looks and a named alpha-spending function; power per look from pre-2027 returns; "What was seen before this filing"; "Inputs dated 2027"; the pair-level hypotheses of E3; data risks pre-registered (primary price source, a measured free fallback such as Stooq with a cross-check tolerance, N-PORT filing lag, dependence correction, what counts as "not a crash"). | The filing commit's `pushed_at` or Zenodo date precedes 2027-01-04; the file has sections "Hypotheses, test and decision rule", "Looks and alpha spending", "Power, stated in advance", "Inputs dated 2027", "Commitments"; a test asserts the v34 evaluator rejects any series containing a 2026 date. |
| E3 | P1 | **Power gate for every future pre-registration** (add to HANDOFF): state the MDE at 80% power for the planned length (`power.minimum_detectable_sharpe`); then either run long enough that the MDE is at or below the smallest Sharpe the study would call an edge, or pre-register a **trade-level** primary test with its MDE in bp per trade and month-clustered errors, or title the study a falsification test. Worked table: a Sharpe-level test at 200 days has MDE ≈ 2.96; ≈ 1.9 at two years, 1.5 at three, 1.2 at five; power against a true 0.5 stays under 20% even at five years. | HANDOFF contains the rule and table; `scripts/power_plan.py` with a test against `power.py`; CI fails on any `docs/PREREGISTRATION_v*.md` without a power table. |
| E4 | P1 | **Candidate 1 (rank 1): a prospective pair-level mechanism study**, the only well-powered test free data allow. H-A persistence: among pairs the frozen v33 selector picks at 2027 formations, the share still cointegrated in the next window exceeds that window's base rate; H-B exit race: the target share of post-formation barrier exits exceeds the random-walk expectation; H-C decay: post-formation gross bp per rule trade > 0 (descriptive or sequential, never confirmatory at one year). Dependence correction pre-registered. | `studies/v34/power_pairlevel.py` writes `power.json` from `results/v33_dev/` only; the pre-registration's power table is a marker-checked copy; each test function runs on the synthetic market in a hermetic test. |
| E5 | P1 | **Candidate 2 (rank 2): the sequential prospective holdout of the unchanged S1 and S2.** 2026's H1/H2 unchanged; K looks with alpha spending; each look run once in arrears from a fresh clone of the registered commit; published whatever its sign; never pooled with 2026 days. This is the only way "sealed" becomes "prospective". | One `results/holdout2027/look_<k>/evaluation.json` per look with information fraction, nominal level, t, p, Holm p, decision, upper bound and MDE; one registry line per look. |
| E6 | P1 | **Candidate 3 (rank 3): selection-rule ablation on one engine.** Phase 1 = B1 (descriptive control on 2023–2025, no selector chosen from it); Phase 2 = the same arms (Engle–Granger vs correlation-only vs distance vs random same-industry) pre-registered for 2027 formations beside E4. H0: equal post-formation target share and gross bp per rule trade across arms. | New exhibit with per-arm counts, target share, gross and net bp with month-clustered t and the gate-set hash. |
| E7 | P2 | Candidate 4: the exit rule (OU-implied or fixed horizon vs the registered target/stop/time-stop) as a paired, pair-level secondary hypothesis on the same rule trades. Candidate 5: the descriptive extension (B5). Candidate 6: is this family short-term reversal in costume? A trade-level factor test (`significance.factor_attribution_multi`) with the factor file's fingerprint recorded. Cost-aware entry thresholds only as a secondary arm with its power stated. | Each specified exactly in the pre-registration (formula, statistic, clustering) and reported with no stronger claim than its test supports. |

---

## 3. How a session should work (so quality compounds)

1. Read `docs/HANDOFF.md` and this file. Run every check in HANDOFF.md's "Checks before any
   push" to confirm a green baseline **before** touching anything.
2. Take the top open item of the lowest open phase. One item at a time.
3. Change the smallest thing that completes it.
4. Verify in a real browser for anything visible (desktop 1440 px and phone 390 px, light and
   dark, print, no JavaScript) and with every check for anything numeric.
5. Rebuild the paper after any page edit (`python scripts/build_paper.py`).
6. Commit with a message that says what changed and why. Push the branch, fast-forward `main`
   (`git push origin HEAD:main`), wait for CI (≈13 min), confirm the live files match (sha256).
7. Record the item in the Done table below and in `docs/PROGRESS.md`.
8. Before each push, read your own diff as a hostile reviewer would. After each phase, run
   independent adversarial reviews (fresh sessions or subagents) that try to break the claims,
   numbers and page, and fix what they reproduce. This session's review rounds found 49, 28 and
   then the findings above, all real.

## 4. Guardrails (never cross)

- Never set `PAIRS_UNSEAL` by hand; never re-run the 2026 holdout; never tune toward it.
- `docs/PREREGISTRATION.md`, `pairs_trading/` and `reference/` are frozen. New studies live in
  `studies/`.
- Free resources only. No paid data, compute or services.
- Never send the owner's e-mail address to any service; SEC requests use the generic
  User-Agent in HANDOFF.md.
- No hype. Every sentence no stronger than its evidence. Publish whatever the sign.

---

## Done

| Date | Item | Commit | Measured effect |
|---|---|---|---|
| | *(nothing yet)* | | |
