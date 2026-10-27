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

---

## 1. Honest assessment of where the project stands

### Already at or above the bar (keep these; do not undo them)

- **Falsifiable design.** A pre-registration (`docs/PREREGISTRATION.md`) filed at commit `7c7d3f9`
  with hypotheses, test, decision rule and power stated in advance; the seal enforced in code
  (`study_config.assert_unsealed`); every attempt on record (`results/trial_attempts.jsonl`,
  `results/trial_registry.jsonl`); the result published whatever its sign.
- **Multiple-testing discipline.** A 38-variant family declared before any variant ran; Hansen's
  SPA, White's Reality Check, Romano–Wolf stepdown, model confidence set, probability of backtest
  overfitting, deflated Sharpe ratio. Few published backtests do this at all.
- **Point-in-time universe** from SEC N-PORT holdings, with survivorship measured and reported per
  formation rather than ignored.
- **An evidence layer** that explains the null trade by trade (shortfall, exit race, decay after
  formation, cointegration persistence, capacity), plus a second strategy family that agrees.
- **Every published number is machine-checked** against the run's files
  (`scripts/check_published_numbers.py`, 1,000+ markers on the page), and the paper, page and
  README are built from the same data.
- **A full, unflattering engineering log** (`docs/PROGRESS.md`): withdrawn results, look-ahead
  bugs found and fixed, the storage loss, every review round. Reviewers trust this more than a
  clean story.
- **The page** opens with the answer, lets a reader check any number in the browser, links every
  reference, works without JavaScript and in print, and scores 100 on desktop Lighthouse.

### Still short of the bar (what a reviewer would still ask for)

Ordered by how much they matter.

1. **No single-command rebuild from a clean clone, and no container image.** A reviewer who
   cannot reproduce the headline number in one command will not trust the rest.
2. **The random-pair control runs through the Gatev rule, not the strategy's own engine.** The
   page says a control on the strategy's engine is "planned". Until it exists, the strongest
   comparison (same engine, random pair selection) is missing.
3. **Costs are published averages, not measurements.** No free tick or quote data, so spreads and
   impact come from literature estimates (Y = 0.3 at the low end). This is disclosed, but a
   reviewer will want the sensitivity made more visible and, where free data allow, a partial
   calibration (e.g. daily high–low spread estimators, Corwin–Schultz 2012, from the same prices).
4. **One period, one regime.** Thirty months. The paper is honest about this; a reviewer will
   still ask what the design does on 2010–2019 as a *descriptive* extension (no new tuning), run
   under the same frozen rules and reported as such.
5. **Browser behaviour is not under CI.** The page's JavaScript (checking numbers, charts,
   tables, previews) was verified by hand in Chromium only. Firefox and WebKit are untested.
6. **No DOI, no release, no posting.** The work is not citable and not where quant researchers
   look.
7. **Length.** The page and the paper are long. A ten-minute reader needs the answer, the design
   and the caveats on one screen (the page now does this) and the rest findable; the paper does
   not yet have the page's key findings and timeline.
8. **Literature gaps.** The cited set (Gatev et al. 2006; Do & Faff 2010, 2012; Avellaneda & Lee
   2010; Engelberg et al. 2009; Clegg 2014; Jacobs & Weber 2015; Rad, Low & Faff 2016; Krauss
   2017; Chen et al. 2019) misses the multiple-testing and backtest-overfitting literature the
   study actually uses (White 2000; Hansen 2005; Romano & Wolf 2005; Bailey & López de Prado
   2014, the deflated Sharpe ratio; Bailey et al. 2017, PBO; Harvey, Liu & Zhu 2016), the
   Sharpe-ratio inference it relies on (Lo 2002; Ledoit & Wolf 2008), cost-model sources
   (Almgren et al. 2005; Frazzini, Israel & Moskowitz 2018), and recent pairs work (e.g. Huck
   2015; Krauss, Do & Huck 2017). These should be cited where used, not padded in.

---

## 2. Roadmap, in order

Each item: what, why, how to verify. Work top to bottom; do not start a lower phase while a P0
is open. Record each finished item in the **Done** table at the end with its commit and effect.

### Phase A — Reproducibility (P0)

| # | Item | Done when |
|---|---|---|
| A1 | **One-command rebuild.** Add a `Makefile` (or `scripts/rebuild_all.sh`) with targets `data`, `site`, `paper`, `check`, `all`: builds `assets/study.json`, the generated page blocks (hero, timeline, links), the fonts, the paper, then runs every check in HANDOFF.md. | `make all` from a clean clone on CI finishes green and leaves `git status` clean (no file differs from the committed one). Add that as a CI job. |
| A2 | **Container image.** A `Dockerfile` pinning Python 3.12, CPU torch, `requirements.txt`, typst 0.15.0, Node + Playwright Chromium for the browser tests. | `docker build` then `docker run … make all` passes. Document in README "Reproduce". |
| A3 | **Data archive with checksums.** The study cannot redistribute Yahoo prices, but can archive everything else it fetched (N-PORT snapshots, factor files, FRED series, identifier maps) with sha256 in one manifest, and give the exact fetch manifest for prices. | `reference/` and `results/*/price_fetch_manifest.json` are listed in one `MANIFEST.sha256`; a script verifies it; CI runs it. |
| A4 | **Headline-number smoke test.** A fast test that recomputes the main Sharpe, return and trade count from the committed results export and compares with `headline_metrics.json`. | Test exists, runs in under a minute, is in CI. |

### Phase B — Research completeness (P0–P1)

| # | Item | Done when |
|---|---|---|
| B1 | **Random-pair control on the strategy's own engine** (P0). Draw N random same-industry pairs (same universe rule, same formation dates), trade them with the v33 engine, same fills and costs; report the strategy's percentile and the control's Sharpe distribution beside the existing Gatev-rule control. No design change; a descriptive comparison. | New exhibit + numbers in `headline_metrics.json`/`study.json`, markers checked; the page's "planned" sentence updated to describe it; paper rebuilt. |
| B2 | **Cost-model sensitivity made legible and partially calibrated** (P1). Add a Corwin–Schultz (2012) high–low spread estimate per name from the same daily data, compare with the assumed spread buckets, and report the gap. Keep every published cost scenario unchanged. | Exhibit comparing assumed vs estimated spreads; one sentence in Threats giving the direction and size of the difference. |
| B3 | **Descriptive extension to earlier periods** (P1). Run the frozen v33 rules on 2010–2019 (or whatever free point-in-time membership allows; otherwise state the limit) as a *descriptive* study: no tuning, no new hypothesis test counted as confirmatory, labelled as such on the page. | New section or appendix with the same statistics as the development period; the Threats row "One period, one regime" updated with the evidence. |
| B4 | **Power statement for the development period** (P1). Alongside the holdout's power, state the development sample's minimum detectable Sharpe at 80% power under its own return distribution, so the "cannot tell 0 from 0.5" claim has a number next to it. | Marker on the page and in the paper; computed by `pairs_trading/power.py`. |
| B5 | **Cross-sectional diagnostics** (P2). Per-industry and per-size-bucket breakdown of trades, gross edge and cost; shows whether the null is uniform or hides pockets (reported, not acted on). | One exhibit with its data table; no claim beyond "reported". |

### Phase C — Engineering and testing (P1)

| # | Item | Done when |
|---|---|---|
| C1 | **Browser tests in CI.** Playwright job: serve the site; assert no console errors; 24 charts draw; deep links land; "Check the numbers" reports all markers matching; axe 0 violations at 390 and 1440 px in both themes; layout shift < 0.01. | Job green on `main`; failures block merges. |
| C2 | **Cross-browser.** Run C1's checks in Firefox and WebKit too (Playwright ships both). Fix anything that differs; the known risk is the `<wbr>` hiding in the registry table. | All three engines green in CI. |
| C3 | **Visual regression.** Reference screenshots (opening, one exhibit, one phone card table, print page 1), diffed in CI with a small tolerance. | Baselines committed; job green. |
| C4 | **Code hygiene.** `trading_system.py` (2,200 lines) and `exhibits.js` (2,860 lines) are large. Split by responsibility *without changing behaviour* (the frozen-path rule forbids changing `pairs_trading/` semantics; a pure file split with identical tests passing is acceptable only if the pre-registration's freeze rule is read to allow it — if in doubt, leave `pairs_trading/` alone and split only `assets/*.js`). | Tests unchanged and green; `check_published_numbers` green; no diff in any results file. |
| C5 | **Phone rotation keeps the reader's place.** | Rotating 390↔844 in Playwright keeps the same section heading within one screen. |

### Phase D — Presentation and publication (P1)

| # | Item | Done when |
|---|---|---|
| D1 | **Paper matches the page.** Add the key findings and the pre-registration timeline to `paper/`, from the same data; make exhibit titles findings, as on the page. | `build_paper.py --check` green; a side-by-side read finds no claim in one that is absent or differently qualified in the other. |
| D2 | **Literature.** Cite the methods papers listed in §1(8) where each method is used; add DOIs. Nothing cited that is not used. | Every method in Section 3 and 7 of the page has its source; `references.bib` updated; paper rebuilt. |
| D3 | **Length discipline.** Move estimator detail beyond ~120 words per exhibit note into "Method notes" disclosures; split 250-word ledes at natural breaks; add a "Terms used in this note" list. No words of a caveat removed. | Word count of the default reading path falls by ≥25%; every caveat still visible by default; `link_refs --check` and numbers check green. |
| D4 | **Corrections log.** `docs/CORRECTIONS.md`: dated list of every correction after first publication (source: the review rounds in `PROGRESS.md`), linked from the page's History section. | File exists; page links it; paper mentions it. |
| D5 | **Release and DOI.** Tag a release; connect the repository to Zenodo (free) so the release gets a DOI; add the DOI to `CITATION.cff`, the page's citation block and the paper. *The owner must click "connect" on Zenodo and publish the release.* | DOI resolves; `CITATION.cff` validates. |
| D6 | **Posting package.** Prepare an SSRN or arXiv (q-fin.TR / q-fin.ST) submission: PDF, 150-word abstract, keywords, JEL codes. *The owner submits.* | Package in `paper/submission/`; README says how to submit. |
| D7 | **Mobile performance ≥ 95.** Remaining weight is the long HTML and two first-screen fonts: inline critical CSS; consider a second page for the audit-trail sections with anchors preserved. | Lighthouse mobile performance ≥ 95, accessibility/best-practices/SEO 100, CLS < 0.01. |

### Phase E — New research (only as new pre-registrations)

Any follow-on study must be a new design version (v34+), filed as a new pre-registration **before
any data from its test period exists**, with its own hypotheses, test, decision rule, power and a
genuinely future holdout, run once and published whatever the result. The spent 2026 holdout and
the 2020–2025 development data cannot confirm a new design. Candidate studies, interesting
whatever their sign and feasible with free data:

| # | Study | Hypothesis | Why interesting even if null |
|---|---|---|---|
| E1 | **Industry-ETF residual reversion with a point-in-time universe** (extends S2) | Residual reversion survives costs at the 500-name liquidity tier | Tests whether the second family's null is universe-specific |
| E2 | **Cointegration vs correlation pair selection, head to head** | Same engine, two selection rules declared in advance; neither beats cash | Direct test of the premise of the Engle–Granger approach |
| E3 | **Hold-time rule: fixed horizon vs OU half-life** | Half-life-based exits reduce the stop share (currently 77 of 213 trades) | The exit race is where the current study's edge is lost |
| E4 | **Cost-aware entry thresholds** | Entry z scaled by estimated spread lowers turnover enough to break even | Only honest route to "after costs"; must be filed before its test period |
| E5 | **Out-of-sample 2027 prospective holdout of the unchanged v33** | The same decision rule, prospectively | The only way to turn "sealed" into "prospective"; costs nothing but patience |

For each: file the pre-registration first; state power from pre-period data only; register the
trial; run once; publish.

---

## 3. How a session should work (so quality compounds instead of drifting)

1. Read `docs/HANDOFF.md` and this file. Run every check in HANDOFF.md's "Checks before any push"
   to confirm a green baseline **before** touching anything.
2. Take the top open item of the lowest open phase. Do one item at a time.
3. Change the smallest thing that completes it. Never change a published number, result, claim
   or caveat without evidence; if evidence says one must change, stop and write it up for the
   owner first.
4. Verify in a real browser for anything visible (desktop 1440 px and phone 390 px, light and
   dark, print, no JavaScript), and with every check for anything numeric.
5. Rebuild the paper (`python scripts/build_paper.py`) after any page edit; it records the page's
   hash.
6. Commit with a message that says what changed and why. Push the branch, then fast-forward
   `main` (`git push origin HEAD:main`). Wait for CI (≈13 min). Confirm the live files match the
   repository (sha256).
7. Record the item in the Done table below and in `docs/PROGRESS.md`.
8. Review your own diff adversarially before each push: what would a hostile reviewer say?

Adversarial review is cheap insurance: after each phase, have independent reviewers (fresh
sessions or subagents) try to break the claims, the numbers and the page, and fix what they
reproduce. The first session's review rounds found 49, then 28, real issues this way.

---

## 4. Guardrails (never cross)

- Never set `PAIRS_UNSEAL` by hand; never re-run the 2026 holdout; never tune anything toward it.
- `docs/PREREGISTRATION.md`, `pairs_trading/` and `reference/` are frozen.
- Free resources only. No paid data, compute or services.
- Never send the owner's e-mail address to any service; SEC requests use the generic
  User-Agent in HANDOFF.md.
- No hype. Every sentence no stronger than its evidence. Publish whatever the sign.

---

## Done

| Date | Item | Commit | Measured effect |
|---|---|---|---|
| | *(nothing yet)* | | |
