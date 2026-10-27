# Handoff: continuing this project in a new Claude Code session

Read this first in any new session. The engineering log (`docs/PROGRESS.md`) has the full
history; this file is the short version of where things stand and the rules that hold.

## Where things stand (27 October 2026)

- The study is complete:
  - v33 design, development run of commit `7442705`.
  - The pre-registered 2026 holdout was filed at `7c7d3f9` and run once on 26 October 2026.
  - Neither null was rejected (Holm p 0.955 for both arms).
- Published, with CI green on `main`:
  - Live note: <https://navnoorbawa.github.io/russell3000-pairs-trading/>
  - Paper: <https://navnoorbawa.github.io/russell3000-pairs-trading/paper/pairs_study.pdf>
- The site's UI round is finished (see "The page as a reader's tool" in `docs/PROGRESS.md`).
- Lighthouse on a local copy:
  - desktop: 100 for performance, accessibility, best practices and SEO;
  - mobile: performance 87 to 89, the other three 100.

## Rules that always hold

1. **The holdout is spent.** Never set `PAIRS_UNSEAL` by hand, and never re-run the holdout. Do
   not change the strategy, its parameters, the test or the decision rule in response to it.
2. **Frozen paths.** `docs/PREREGISTRATION.md`, `pairs_trading/` and `reference/` are frozen.
3. **No number, result, claim or caveat is changed or dropped without evidence.** New text only
   restates the page. Every number in the page's prose is a `<span data-metric="KEY">` marker
   that `scripts/check_published_numbers.py` checks: `study.*` keys resolve against
   `assets/study.json`, the rest against `results/v33_dev/headline_metrics.json`.
4. **Publish the result whatever its sign.** No hype, and no chasing a positive result.
5. **Privacy.** Never send the owner's e-mail address to any service. SEC requests use the
   generic User-Agent `russell3000-pairs-trading research bot admin@example.org`.
6. **Free resources only.** Nothing paid.

## Setting up a cloud session

The environment's setup script (or the first commands of a session):

```bash
python3.12 -m venv .venv && . .venv/bin/activate
python -m pip install --upgrade pip
pip install --no-deps torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
pip install pytest pytest-cov ruff arch hypothesis "typst==0.15.0" fonttools brotli
```

The cloud container already has Node and Playwright with Chromium (`require('playwright')`,
`chromium.launch()` with no options). To preview the site, serve the repository root over HTTP,
for example `python3 -m http.server 8000`.

## Checks before any push

```bash
ruff check .
python scripts/check_published_numbers.py      # every marked number on the page and in the README
python scripts/link_refs.py --check            # every "Exhibit N" / "Section N" is a link
python scripts/build_hero.py --check           # the hero chart under the masthead is current
python scripts/build_prereg_timeline.py --check
python scripts/build_site_data.py --check      # assets/study.json is current
python scripts/build_paper.py                  # the paper records index.html's sha256: rebuild after page edits
python scripts/build_paper.py --check
pytest -q                                      # about 1,190 tests; CI also measures coverage
```

## How changes are published

- Work on the session's branch. Then fast-forward `main` (`git push origin HEAD:main`), so that
  GitHub Pages redeploys.
- CI (`.github/workflows/ci.yml`) runs on `main` and takes about 13 minutes. A newer push cancels
  an older run.
- After a deploy, compare the live files with the repository's (sha256 of `index.html`,
  `assets/*.js`, `assets/site.css`, `paper/pairs_study.pdf`).
- Commit messages say what changed and why.

## Map of the site

| What | Where |
|---|---|
| The page | `index.html` (readable without JavaScript) |
| Styles | `assets/site.css` (hero, tables and charts styles are merged into it); `assets/verify.css` |
| Behaviour | `assets/site.js` (contents, previews, deep links, print, lazy charts); `assets/exhibits.js` (the 24 charts, crosshairs, SVG/PNG export); `assets/tables.js` (phone layouts, Copy/CSV); `assets/verify.js` (checking any number in the browser) |
| Generated blocks in the page | `scripts/build_hero.py` (hero), `scripts/build_prereg_timeline.py` (Section 1 timeline), `scripts/link_refs.py` (cross-reference links) |
| Data | `assets/study.json`, built from `results/` by `scripts/build_site_data.py` |
| Fonts | `assets/fonts/Study*.woff2`: subsets of IBM Plex, renamed as its licence requires (`scripts/build_fonts.py`; originals in `assets/fonts/plex/`) |
| Paper | `paper/` (Typst), built by `scripts/build_paper.py` |

## The standing mandate

**The prioritised roadmap, with an honest assessment of what is still short of the bar and an
acceptance criterion for every item, is in `docs/IMPROVEMENT_PLAN.md`. Work from that file.**

Keep improving the project, one verified and published step at a time, until it meets the bar
below. The bar is the one a top quantitative fund's research review would apply: rigour,
reproducibility, honesty and presentation. It is **not** a positive Sharpe ratio.

- The study's answer is "no detectable edge". It stays the answer unless new, properly
  pre-registered evidence says otherwise.
- The 2026 holdout is spent. Nothing may be tuned toward it.

### The bar (all must hold)

1. **Correctness.**
   - Every published number is checked automatically.
   - Every claim is no stronger than its evidence.
   - Every caveat a reader needs is next to the claim it qualifies.
2. **Reproducibility.**
   - A stranger can rebuild every number, figure, the page and the paper from a clean clone with
     one documented command each.
   - The environment is pinned, ideally with a container image.
   - The data snapshots are archived with checksums.
3. **Statistical hygiene.** Multiple testing, data snooping, power and the start-date path are
   all reported. Any new strategy research is a separate, new pre-registration with its own
   untouched future holdout (see below).
4. **Engineering.**
   - CI is green and covers the page's behaviour in a real browser, not only the Python.
   - No console errors.
   - The page works in Chromium, Firefox and WebKit.
5. **Accessibility.**
   - axe reports 0 violations in both themes, at 390 and 1440 px.
   - Keyboard and screen-reader use is checked by hand (NVDA or VoiceOver flows written down).
6. **Performance.** Lighthouse:
   - mobile: 95 or more for performance and 100 for the other three;
   - desktop: 100 for all four;
   - layout shift below 0.01 on both.
7. **Presentation.** Every exhibit makes one point, has a finding as its title, and works in print
   and without JavaScript. The paper and the page say the same thing in the same words.
8. **Scholarly record.**
   - A versioned release with a DOI.
   - A citation file.
   - A corrections log.
   - The paper posted where quant researchers read (SSRN or arXiv q-fin). That needs the owner
     to act; prepare everything up to the submit button.

### The loop

1. Pick the highest-impact unfinished item below.
2. Implement it.
3. Verify it in a real browser and with every check.
4. Publish: branch, then `main`, then CI green, then the live files match.
5. Move the item to "Done" at the end of this file, with the commit and the measured effect.
6. Repeat.

If an item would change a published number or claim, stop. Write down the evidence and ask the
owner before going further.

## Not finished in the first session (time ran out)

Each item says what is missing and how to know it is done.

### Verification and engineering

- **Cross-browser.**
  - Missing: everything was tested in Chromium only.
  - Do: install Playwright's Firefox and WebKit in a session and run the same checks
    (screenshots at 390 and 1440 px in both themes, deep links, contents sheet, previews,
    number check, tables, print).
  - Known risk: the registry's `<wbr>` breaks are hidden with `display: none` on phones only,
    which is untested in Safari and Firefox.
- **Browser tests in CI.**
  - Missing: CI runs Python only. The browser checks used in this session lived in scratch
    scripts.
  - Do: add a Playwright job that serves the site and asserts:
    - no console errors;
    - all 24 charts draw;
    - deep links land (`#ex-17`, `#f3`, `#t-scenarios`, `#bottom-line`);
    - "Check the numbers" reports every marker matching;
    - axe finds 0 violations at 390 and 1440 px;
    - layout shift below 0.01.
- **Visual regression.** Missing: there is no baseline. Do: commit reference screenshots of the
  opening, one exhibit, one table and print page 1, and diff them in CI with a tolerance.
- **Manual screen-reader pass.**
  - Missing: only axe was run.
  - Do: write `docs/ACCESSIBILITY.md` with NVDA (Firefox) and VoiceOver (Safari) walk-throughs:
    - the opening;
    - the contents sheet;
    - a reference preview;
    - the number check;
    - a phone card table;
    - a chart's keyboard crosshair.
- **Reproducibility.**
  - Missing: there is no container image, and no single command rebuilds everything.
  - Do:
    - add a `Dockerfile` (Python 3.12, CPU torch, the pinned requirements, typst);
    - add `make all`, which rebuilds the site data, page blocks, fonts and paper and runs every
      check;
    - document a clean-clone rebuild.
- **Phone rotation.** Missing: rotating a phone (390 ↔ 844 px) loses the reader's place by
  thousands of pixels, with or without JavaScript. Do: keep the section and offset at the top of
  the window across an orientation change.

### Page and content

- **Mobile performance.**
  - Now: 87 to 89 under simulated slow 4G. The rest is the long page's HTML (about 57 kB
    gzipped) and two first-screen fonts.
  - Options:
    - move the no-JavaScript paper-figure blocks, the hero's hidden text and the long tables
      out of the critical HTML;
    - split rarely read sections into a second page, keeping anchors;
    - inline the first screen's critical CSS.
  - Target: 95 or more with no layout shift.
- **Tablet tables.** At 601 to 1080 px the pre-registered hypotheses table scrolls sideways
  without a sticky first column.
- **Exhibit polish.**
  - Exhibit 2's line-end labels show values without series names.
  - Exhibit 1's 80%-power mark (2.96) falls outside the shared Sharpe axis and is only in the
    text; consider an off-scale arrow marker.
- **Brief view.**
  - Missing: a reader-chosen depth that shows each section's answer and exhibits and hides the
    method text (audit report `editorial [6]`).
  - Watch: the banner must say what is hidden, print stays full, and every caveat stays visible.
- **Paragraphing.** The ledes and prose blocks of about 250 words should be split at their
  natural breaks, with no words changed (`editorial [7]`).
- **Terms.**
  - Missing: a "Terms used in this note" list in the Summary, and links on a term's first use
    that point to where the page itself defines it (`editorial [9]`, `interaction [11]`).
  - Watch: definitions only as the page already words them.
- **Threats index.** Missing: a scannable index of the threats to validity by direction of bias
  (`editorial [10]`).
- **Method notes.** Exhibit notes over about 120 words should keep their qualifying sentences
  visible and move estimator detail into a "Method notes" disclosure (`editorial [12]`).
- **Citations as links.** Missing: Literature rows have no ids, and in-text author-year
  citations do not link to them. Do: add ids such as `lit-gatev-2006` and link each citation
  that matches a row.
- **Every result on record.** Missing: one visual of the trial registry, the 38 variants and the
  12 start dates (`benchmark [8]`). Watch: it must not imply that any of them is a new design.
- **Exhibit "Data & reproduce" panel.**
  - Have: each exhibit exports SVG, PNG and CSV.
  - Missing: the path into `assets/study.json`, the command that rebuilds the exhibit, and links
    to the builder code (`benchmark [6]`).
- **Corrections log.** Missing: a dated, public list of every correction made after first
  publication (the review rounds in `docs/PROGRESS.md` are the source).
- **Paper and page in step.** Missing: the paper does not have the page's key findings or the
  pre-registration timeline. Do: add both to `paper/`, with numbers from the same data, then
  rebuild and check.

### Scholarly record (the owner must act on some steps)

- **DOI.**
  - Do: connect the repository to Zenodo (free) and cut a GitHub release, so the code, data
    snapshots and paper get a DOI.
  - Then: add the DOI to `CITATION.cff`, the page's citation block and the paper.
- **Posting.** Prepare an SSRN or arXiv (q-fin.TR / q-fin.ST) submission package (PDF,
  abstract, keywords). The owner submits.

## New research: only as a new pre-registered study

Any new strategy work, such as another signal, universe or cost model, must:

1. live in a new design version (v34 or later) without touching the frozen paths;
2. be filed as a new pre-registration before any data from its test period exists, with the
   hypotheses, the test, the decision rule, the power and the date its prospective holdout
   starts;
3. be run once on that holdout when it has accrued;
4. be published in full whatever the result.

The development-period data (2020 to 2025) and the spent 2026 holdout cannot confirm a new
design. Report this limit plainly.

## Done

_Nothing yet. Record each finished item here: what, the commit, and the measured effect._
