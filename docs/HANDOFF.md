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

## Open, optional items

- Mobile Lighthouse performance is 87 to 89. The rest is mostly the long page's HTML and the
  two first-screen fonts.
- At tablet widths (601 to 1080 px), the pre-registered hypotheses table scrolls sideways
  without a sticky first column.
- Exhibit 2's line-end labels show values without series names.
- Exhibit 1's 80%-power mark (2.96) falls outside the shared Sharpe axis and is stated only in
  the text.
- It is untested whether hiding the registry's `<wbr>` breaks keeps them hidden in Safari and
  Firefox.
