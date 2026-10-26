#!/usr/bin/env python3
"""Build the study's paper, paper/pairs_study.pdf, from the same data as the site.

The paper is the site in print. It reads the site's data contract (assets/study.json,
built by scripts/build_site_data.py, and the headline JSON that file was built from), so
the two cannot disagree: every number the paper prints is formatted here, once, into
paper/build/paper_data.json, and paper/main.typ only places the formatted strings. A
result that does not exist yet (the sealed 2026 holdout) is null in that file; its exhibit or table is left out of the
body and listed, with what it will show, in the note's table of forthcoming results. A
number that is null prints as "pending" with its reason, never as a number. Sentences whose
wording depends on the data ("every interval spans zero") name a claim that is computed
here; the compile stops if a claim the text makes is false.

Once the pre-registered holdout is evaluated (study.json's 'holdout' is 'complete'), its
results, its run record and its decision are printed from study.json alone: the decision
is the evaluation's (each confirmatory arm's edge and Holm-adjusted p), read and checked,
never recomputed, and a holdout block that contradicts itself stops the build
(holdout_block). Its numbers are rounded as the site rounds them (fmt(half_up=True)); main.typ
words the result by flags and asserts each wording with a claim, and checks that the summary
still fits on page 1.

Products (all committed; CI checks them with --check):

    paper/build/paper_data.json    every printed number and table cell, formatted as the
                                   site formats it; claims; pending reasons; layout
    paper/build/figures/*.svg      the exhibits (matplotlib; IBM Plex from paper/fonts/;
                                   colours from the light theme of assets/site.css)
    paper/pairs_study.pdf          Typst compile of paper/main.typ with a fixed timestamp
    paper/build/manifest.json      sha256 of every compile input and of the PDF

usage:
    python scripts/build_paper.py               # data, figures and PDF
    python scripts/build_paper.py --check       # exit 1 if a committed product is stale
    python scripts/build_paper.py --png DIR     # also render each page to DIR/page-N.png
    python scripts/build_paper.py --study FILE --results DIR [--holdout-calendar NAME] --out DIR
                                                # a paper from other site data (e.g. a stand-in
                                                # of the evaluated holdout), built outside the
                                                # repository, never over the committed products

Deterministic: no wall-clock time (the PDF's timestamp is the paper's date, the newest
dated input), fixed SVG ids, sorted JSON; a rebuild of unchanged inputs is byte-identical.
The typst Python package (pip install -e ".[paper]") is needed to compile the PDF only;
without it --check still verifies the data, the figures and the manifest.
"""
import argparse
import datetime as dt
import hashlib
import html
import io
import json
import math
import pathlib
import re
import shutil
import sys
from decimal import ROUND_HALF_UP, Decimal

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pairs_trading import power as pw  # noqa: E402
from pairs_trading.significance import _autocorrelations  # noqa: E402
from pairs_trading.study_config import CALENDARS, PROFILES  # noqa: E402

SCHEMA = 1
PAPER = ROOT / 'paper'
BUILD = PAPER / 'build'
FIGURES = BUILD / 'figures'
FONTS = PAPER / 'fonts'
MAIN = PAPER / 'main.typ'
BIB = PAPER / 'references.bib'
PDF = PAPER / 'pairs_study.pdf'
DATA = BUILD / 'paper_data.json'
MANIFEST = BUILD / 'manifest.json'
SITE_CSS = ROOT / 'assets' / 'site.css'
SITE_INDEX = ROOT / 'index.html'

MINUS = '−'
PERIODS = 252
EXHIBIT_WIDTH_MM = 162.0                # A4 (210 mm) less 24 mm margins: exhibits and tables span this
MEASURE_MM = 130.0                      # running text: about 75 characters of 10.4 pt Plex Serif
COLUMN_GAP_MM = 6.0
BOOT_SEED, BOOT_RESAMPLES = 42, 5000    # the run's own bootstrap settings (seed, resamples)
_Z95, _Z80 = 1.6448536269514722, 0.8416212335729143   # one-sided 5% test, 80% power
HOLDOUT_DAYS = (126, 200, 252)          # six months, the registered calendar (2026-01-02 to 2026-10-19), a year
HOLM_FIRST_ALPHA = 0.05 / 2             # Holm's first step across the two confirmatory arms
# The pre-registered 2026 test (docs/PREREGISTRATION.md; scripts/evaluate_holdout.py). Each arm:
# its key in the evaluation, its hypothesis (None: descriptive), the paper's id and name.
HOLDOUT_TRIAL = 'holdout2026'
HOLDOUT_CALENDAR = 'holdout2026'
HOLDOUT_ALPHA = 0.05
HOLDOUT_ARMS = (('v33_pairs', 'H1', 's1', 'S1'), ('avellaneda_lee', 'H2', 's2', 'S2'),
                ('v32_pairs', None, 's3', 'S3'))
HOLDOUT_RECORDS = ('results/trial_registry.jsonl', 'results/trial_attempts.jsonl')
# the runbook's steps (trial_attempts.py) by the names the paper gives them
HOLDOUT_STEPS = {'universe': 'universe', 'data': 'data', 'v33': 'S1', 'v32': 'S3', 'residual': 'S2',
                 'evaluate': 'evaluation'}
MONTHS = ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September',
          'October', 'November', 'December')
WORDS = ('no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten')
# Sections of assets/study.json the paper prints. A section the site builder adds later
# (and the paper does not know) stops the build rather than going silently unprinted.
KNOWN_STUDY = {'schema', 'meta', 'dev', 'holdout', 'residual', 'validation',
               'v32',          # the published v32 run: the history and the frozen arm S3
               'trials',       # results/trial_registry.jsonl: every trial whose result was seen
               'registry'}     # the registry's counts of trials, run records and table rows
KNOWN_DEV = {'run', 'daily', 'gatev', 'random_band', 'random_sharpes', 'strategy_sharpe', 'gatev_sharpe',
             'random_percentile', 'walk_forward', 'monthly', 'annual', 'rolling_sharpe', 'forest', 'power',
             'dsr_curve', 'waterfall', 'trades', 'factors', 'funnel', 'universe_by_formation', 'cost_schedules',
             'cost_curve', 'snooping', 'facts',
             # the performance summary and the survivorship gap split by fetch outcome
             'performance', 'survivorship',
             # the evidence layer's anatomy.json, passed through by the site builder
             'shortfall', 'exit_race', 'decay', 'persistence', 'capacity', 'half_lives',
             # scripts/cost_sensitivity.py: each declared scenario re-run in full
             'cost_sensitivity',
             # scripts/robustness_checks.py: start dates, regimes, persistence, clustering
             'robustness'}


class PaperDataError(ValueError):
    """The inputs hold something the paper cannot print truthfully."""


# ──────────────────────────────────────────────────────────────────────────────
# Formatting: one function, the site's conventions (U+2212 minus, explicit '+')
# ──────────────────────────────────────────────────────────────────────────────

_SPEC = re.compile(r'(?P<plus>\+?)(?P<comma>,?)\.(?P<dp>\d)(?P<suffix>.*)')


def fmt(x, spec, half_up=False):
    """`x` formatted by `spec`, e.g. '.2', '+.2%', ',.0', '.2×'; None for a missing value.

    '+' writes an explicit plus on positive values; ',' groups thousands; the digit is the
    number of decimals; anything after it is a suffix. A value that rounds to zero carries
    no sign, so '−0.00' cannot appear. `half_up` rounds as the site's num() does (assets/
    exhibits.js, toLocaleString): half away from zero on the shortest decimal form of the
    value (2.675 -> 2.68), not on its binary one (2.67); the holdout's numbers, which the
    site and the paper print side by side, are rounded so.
    """
    if x is None:
        return None
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        raise TypeError(f'not a number: {x!r}')
    x = float(x)
    if not math.isfinite(x):
        return None
    s = _SPEC.fullmatch(spec)
    if s is None:
        raise ValueError(f'bad format spec {spec!r}')
    dp = int(s['dp'])
    if half_up:
        q = Decimal(repr(abs(x))).quantize(Decimal(1).scaleb(-dp), rounding=ROUND_HALF_UP)
        body = format(q, f',.{dp}f' if s['comma'] else f'.{dp}f')
    else:
        body = f'{abs(x):,.{dp}f}' if s['comma'] else f'{abs(x):.{dp}f}'
    nonzero = float(body.replace(',', '')) != 0.0
    sign = MINUS if x < 0 and nonzero else ('+' if s['plus'] and x > 0 and nonzero else '')
    return sign + body + s['suffix']


NBSP = '\u00a0'                         # dates never break across lines


def long_date(iso):
    """'2023-07-03' -> '3 July 2023'."""
    d = dt.date.fromisoformat(str(iso)[:10])
    return f'{d.day}{NBSP}{MONTHS[d.month - 1]}{NBSP}{d.year}'


def short_date(iso):
    """'2022-12-31' -> '31 Dec 2022'."""
    d = dt.date.fromisoformat(str(iso)[:10])
    return f'{d.day}{NBSP}{MONTHS[d.month - 1][:3]}{NBSP}{d.year}'


def month_name(ym):
    """'2024-07' (or a full date) -> 'July 2024'."""
    return f'{MONTHS[int(str(ym)[5:7]) - 1]}{NBSP}{str(ym)[:4]}'


def ordinal(n):
    n = int(round(n))
    suffix = 'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f'{n}{suffix}'


def word(n):
    return WORDS[n] if 0 <= n < len(WORDS) else str(n)


def _sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def _get(d, *path, default=None):
    for p in path:
        if not isinstance(d, dict) or d.get(p) is None:
            return default
        d = d[p]
    return d


# ──────────────────────────────────────────────────────────────────────────────
# Inputs
# ──────────────────────────────────────────────────────────────────────────────

def load_inputs(root=ROOT, study_path=None, results_root=None, holdout_calendar=HOLDOUT_CALENDAR):
    """study.json, the headline JSON it was built from, and the point-in-time universe index.

    The headline JSON is found among study.json's own sources by its sha256, so the paper
    can only ever pair a study file with the run it was built from. `study_path` (default
    assets/study.json) and `results_root` (default results/, where study.json's 'results/...'
    sources are read) let the paper be built from a study file made with
    build_site_data.py --results; `holdout_calendar` is the calendar a completed holdout must
    be on (the registered holdout2026). Once the holdout is evaluated, every file of its record
    that study.json lists must be unchanged since study.json was built from it.
    """
    root = pathlib.Path(root)
    results_root = pathlib.Path(results_root) if results_root else root / 'results'
    study_path = pathlib.Path(study_path) if study_path else root / 'assets' / 'study.json'

    def at(rel):
        """Where a source of study.json ('results/...' under results_root) is read."""
        return results_root / rel[len('results/'):] if rel.startswith('results/') else root / rel
    study = json.loads(study_path.read_text(encoding='utf-8'))
    meta = study['meta']
    rel = next((p for p, h in sorted(meta['sources'].items())
                if p.endswith('headline_metrics.json') and h == meta['headline_sha256']), None)
    if rel is None:
        raise PaperDataError('assets/study.json lists no headline JSON with its headline_sha256')
    headline_path = at(rel)
    if not headline_path.is_file() or _sha256(headline_path) != meta['headline_sha256']:
        raise PaperDataError(f'{rel} is missing or is not the file assets/study.json was built from; '
                             'rebuild it with scripts/build_site_data.py')
    index_path = root / 'reference' / 'universe' / 'index.json'
    universe = json.loads(index_path.read_text(encoding='utf-8')) if index_path.is_file() else None

    def unchanged(rel):
        path = at(rel)
        if not path.is_file() or _sha256(path) != meta['sources'][rel]:
            raise PaperDataError(f'{rel} changed after assets/study.json was built from it')

    def source(pattern):
        """A source of study.json whose path matches, checked against the sha256 recorded there."""
        hits = [p for p in sorted(meta['sources']) if re.search(pattern, p)]
        if not hits:
            return None, None
        unchanged(hits[0])
        return hits[0], json.loads(at(hits[0]).read_text(encoding='utf-8'))
    # the evaluated holdout's record: its exports, evaluation, logs, the registry and the attempts
    if (study.get('holdout') or {}).get('status') == 'complete':
        for record in sorted(meta['sources']):
            if record.startswith(f'results/{HOLDOUT_TRIAL}/') or record in HOLDOUT_RECORDS:
                unchanged(record)
    # the full export of the run the headline JSON describes (its directory); study.json also
    # lists the published v32 run's export, which is history, not this run
    run_dir = rel.rsplit('/', 1)[0]
    results_path, results = source(r'^' + re.escape(run_dir) + r'/pairs_trading_results_.*(?<!_compact)\.json$')
    if results is None:
        raise PaperDataError(f'assets/study.json lists no full results export in {run_dir}/ among its sources')
    _, declaration = source(r'variant_family/declaration\.json$')
    # The residual arm's numbers come from its published export (results/residual_dev/,
    # scripts/publish_run.py), which must be the file study.json was built from.
    residual_path, residual = source(r'residual_dev/residual_statarb\.json$')
    if study.get('residual') is not None and residual is None:
        raise PaperDataError('assets/study.json has a residual arm but lists no published '
                             'residual_dev/residual_statarb.json among its sources')
    # The published v32 run's universe file: the date it was ranked (the frozen arm S3's universe).
    v32_meta_rel = 'results/v32_dev/universe_meta.json'
    v32_meta_path = at(v32_meta_rel)
    v32_meta = json.loads(v32_meta_path.read_text(encoding='utf-8')) if v32_meta_path.is_file() else None
    # The site's exhibit list, for the concordance of its exhibit numbers with the paper's.
    site_path = root / 'index.html'
    site = site_path.read_text(encoding='utf-8') if site_path.is_file() else None
    return {'study': study, 'study_sha256': _sha256(study_path),
            'headline': json.loads(headline_path.read_text(encoding='utf-8')), 'headline_path': rel,
            'results': results, 'results_path': results_path, 'declaration': declaration,
            'residual_path': residual_path,
            'universe_index': universe,
            'universe_index_sha256': _sha256(index_path) if universe is not None else None,
            'v32_universe': v32_meta,
            'v32_universe_path': v32_meta_rel if v32_meta is not None else None,
            'v32_universe_sha256': _sha256(v32_meta_path) if v32_meta is not None else None,
            'site_exhibits': site_exhibits(site) if site is not None else None,
            'site_sha256': _sha256(site_path) if site is not None else None,
            'preregistered': (root / 'docs' / 'PREREGISTRATION.md').is_file(),
            'holdout_calendar': holdout_calendar}


# Site exhibits drawn as diagrams carry no data-exhibit name; they are matched by title.
SITE_DIAGRAMS = {'The pipeline': 'pipeline', 'Data splits': 'timeline'}


def site_exhibits(page):
    """[{n, name, title}] for every numbered exhibit of the site, in its order."""
    out = []
    for fig in re.finditer(r'<figure class="exhibit[^"]*" id="ex-(\d+)"(?: data-exhibit="(\w+)")?[^>]*>(.*?)</figure>',
                           page, re.S):
        head = re.search(r'<span class="ex-title">(.*?)</span>\s*(?:<span class="ex-sub">|</figcaption>)',
                         fig.group(3), re.S)
        title = ' '.join(html.unescape(re.sub(r'<[^>]+>', '', head.group(1))).split()) if head else ''
        name = fig.group(2) or next((v for k, v in SITE_DIAGRAMS.items() if title.startswith(k)), None)
        out.append({'n': int(fig.group(1)), 'name': name, 'title': title})
    return out


def site_tokens(css_path=SITE_CSS):
    """The light-theme colour tokens of the site (the first :root block of site.css)."""
    css = pathlib.Path(css_path).read_text(encoding='utf-8')
    block = re.search(r':root\s*\{(.*?)\}', css, re.S)
    if block is None:
        raise PaperDataError('no :root block in assets/site.css')
    tokens = dict(re.findall(r'--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;', block.group(1)))
    need = ('ink', 'ink-2', 'ink-3', 'rule', 'rule-2', 'accent', 'sunk', 'series-1', 'series-2', 'series-3',
            'neutral-series', 'pos', 'neg', 'div-mid', 'grid', 'axis', 'ord-1', 'ord-2', 'ord-3', 'ord-4')
    missing = [t for t in need if t not in tokens]
    if missing:
        raise PaperDataError(f'assets/site.css :root lacks {missing}')
    return {k: tokens[k].lower() for k in need}


# ──────────────────────────────────────────────────────────────────────────────
# Derived values (the 'paper' namespace)
# ──────────────────────────────────────────────────────────────────────────────

def _flat_window(w):
    """A walk-forward window whose daily returns are all zero: no return and no drawdown."""
    return not w['ret_pct'] and not w.get('max_dd_pct')


def holdout_power(daily_net_pct, days=HOLDOUT_DAYS):
    """Minimum detectable annual Sharpe of a holdout of n days (80% power, one-sided).

    At HOLM_FIRST_ALPHA (the level the better of the two confirmatory arms must reach) and
    at 5%, for two return shapes: the development returns' (skew, non-excess kurtosis,
    lag-1 autocorrelation; the non-normal AR(1) variance of pairs_trading.power) and
    i.i.d. normal returns. Stated in advance, from no return dated after 2025-12-31.
    """
    r = np.asarray(daily_net_pct, dtype=float) / 100.0
    rep = pw.power_report(r, periods=PERIODS)
    rho = float(_autocorrelations(r, 1)[0])
    ann = math.sqrt(PERIODS)
    rows = []
    for n in days:
        rows.append({'days': n,
                     'mde_shape': pw.minimum_detectable_sharpe(0.0, n, rep['skew'], rep['kurtosis'], rho,
                                                               alpha=HOLM_FIRST_ALPHA) * ann,
                     'mde_shape_05': pw.minimum_detectable_sharpe(0.0, n, rep['skew'], rep['kurtosis'], rho,
                                                                  alpha=0.05) * ann,
                     'mde_normal': pw.minimum_detectable_sharpe(0.0, n, alpha=HOLM_FIRST_ALPHA) * ann})
    return {'skew': rep['skew'], 'kurtosis': rep['kurtosis'], 'rho': rho, 'rows': rows}


def universe_snapshots(index):
    """Point-in-time membership snapshots from IWV's N-PORT filings (development years only).

    The index lists filings dated in the sealed holdout without their holdings; only
    snapshots before index['sealed_from'] are read.
    """
    if not index:
        return None
    sealed_from = index.get('sealed_from') or '2026-01-01'
    snaps = [s for s in index.get('snapshots') or [] if s['period_date'] < sealed_from]
    if not snaps:
        return None
    rows = [{'period': s['period_date'], 'equity': int(s['n_equity']), 'mapped': int(s['n_mapped']),
             'unmapped_weight_pct': 100.0 * (1.0 - float(s['mapped_value_share']))} for s in snaps]
    return {'rows': rows, 'sealed_from': sealed_from, 'fund': index.get('fund'),
            'n': len(rows), 'first': rows[0]['period'], 'last': rows[-1]['period'],
            'equity_min': min(r['equity'] for r in rows), 'equity_max': max(r['equity'] for r in rows),
            'unmapped_min_pct': min(r['unmapped_weight_pct'] for r in rows),
            'unmapped_max_pct': max(r['unmapped_weight_pct'] for r in rows),
            'sealed': len(index.get('sealed') or [])}


def performance(study):
    """The performance summary of the main backtest, the walk-forward and the Gatev baseline,
    as the site builder computes it (assets/study.json, dev.performance; the site prints the
    same table), in the shape tables() reads."""
    sp = study['dev'].get('performance')
    if not sp:
        raise PaperDataError('assets/study.json has no dev.performance section (rebuild it with '
                             'scripts/build_site_data.py)')
    cols = ('main', 'wf', 'gatev')
    out = {c: {**sp[c], 'ret': tuple(sp[c]['ret']), 'vol': tuple(sp[c]['vol']), 'dd_days': tuple(sp[c]['dd_days'])}
           for c in cols}
    out['days'] = {c: sp[c]['days'] for c in cols}
    out['sharpe'] = {c: tuple(sp[c]['sharpe']) for c in ('main', 'wf')}
    return out


# ──────────────────────────────────────────────────────────────────────────────
# The pre-registered 2026 holdout (assets/study.json 'holdout', once evaluated)
# ──────────────────────────────────────────────────────────────────────────────

def _holdout_error(msg):
    return PaperDataError(f'the holdout in assets/study.json: {msg}')


def _finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def holdout_block(study, calendar=HOLDOUT_CALENDAR):
    """The evaluated holdout of study.json, checked; None while it is sealed.

    The decision is the evaluation's as scripts/build_site_data.py passes it on: each
    confirmatory arm's edge (edge_out_of_sample) and Holm-adjusted p, with the flag that p
    is below alpha; nothing here recomputes it. The paper stops rather than print a result
    whose parts disagree: the decision against an arm, an edge against its flag or its p, a
    descriptive arm with a decision, an arm without its registered role or the three arms
    not the registered ones, the calendar against the one expected (`calendar`), the days or
    the daily paths against the arms, the run record against itself. A registered trial whose
    completion line is missing (the runbook stopped between registering it and appending the
    line) is printed as such: the registry line is the record of the completed trial.
    """
    H = study.get('holdout') or {}
    status = H.get('status')
    if status == 'sealed':
        return None
    if status != 'complete':
        raise _holdout_error(f'status {status!r} is neither sealed nor complete')
    cal = CALENDARS.get(calendar)
    if cal is None:
        raise _holdout_error(f'no calendar {calendar!r} in study_config')
    if H.get('trial') != HOLDOUT_TRIAL:
        raise _holdout_error(f'trial {H.get("trial")!r}, not {HOLDOUT_TRIAL}')
    if (H.get('calendar') != calendar or H.get('calendar_hash') != cal.config_hash()
            or [H.get('calendar_start'), H.get('calendar_end')] != [cal.backtest_start, cal.data_end]):
        raise _holdout_error(f'calendar {H.get("calendar")!r} ({H.get("calendar_hash")}, {H.get("calendar_start")} to '
                             f'{H.get("calendar_end")}), not {calendar} ({cal.config_hash()}, {cal.backtest_start} to '
                             f'{cal.data_end})')
    family = [k for k, h, _, _ in HOLDOUT_ARMS if h]
    D = H.get('decision') or {}
    if H.get('alpha') != HOLDOUT_ALPHA or D.get('alpha') != HOLDOUT_ALPHA:
        raise _holdout_error(f'alpha {H.get("alpha")!r} / {D.get("alpha")!r}, not the registered {HOLDOUT_ALPHA}')
    if H.get('family') != family or D.get('family') != family:
        raise _holdout_error(f'family {H.get("family")!r} / {D.get("family")!r}, not the registered {family}')
    arms = H.get('arms') or []
    keys = [a.get('key') for a in arms]
    if keys != [k for k, _, _, _ in HOLDOUT_ARMS]:
        raise _holdout_error(f'arms {keys}; the paper prints the registered arms {[k for k, *_ in HOLDOUT_ARMS]}')
    decided = D.get('arms') or {}
    rejected = D.get('rejected')
    if sorted(decided) != sorted(family) or not isinstance(rejected, list):
        raise _holdout_error(f'the decision covers {sorted(decided)} (rejected {rejected!r}), not the family {family}')
    for a, (key, hyp, _, _) in zip(arms, HOLDOUT_ARMS):
        role = 'confirmatory' if hyp else 'descriptive'
        if a.get('role') != role or a.get('hypothesis') != hyp:
            raise _holdout_error(f'{key} has role {a.get("role")!r} and hypothesis {a.get("hypothesis")!r}, '
                                 f'not {role} {hyp}')
        flat = a.get('flat')
        if not isinstance(flat, bool) or (flat and (a.get('sharpe') is not None or a.get('lags') != 0)) \
                or (not flat and not _finite(a.get('sharpe'))):
            raise _holdout_error(f'{key}: flat {flat!r} with Sharpe {a.get("sharpe")!r} and lag {a.get("lags")!r}')
        if not (_finite(a.get('t')) and _finite(a.get('p_one_sided')) and isinstance(a.get('days'), int)
                and a['days'] > 0 and isinstance(a.get('trades'), int) and a['trades'] >= 0
                and _finite(a.get('ret_pct'))):
            raise _holdout_error(f'{key} lacks its t, one-sided p, days, trades or net return')
        edge, p, below = a.get('edge'), a.get('p_holm'), a.get('p_holm_below_alpha')
        if not hyp:
            if (edge, p, below) != (None, None, None):
                raise _holdout_error(f'{key} is descriptive but carries a decision ({edge!r}, {p!r}, {below!r})')
            continue
        if not isinstance(edge, bool) or not isinstance(below, bool) or not _finite(p) or not 0 <= p <= 1:
            raise _holdout_error(f'{key} is confirmatory but has edge {edge!r}, p_holm {p!r}, below alpha {below!r}')
        if decided[key] != {'hypothesis': hyp, 'edge': edge, 'p_holm': p, 'p_holm_below_alpha': below}:
            raise _holdout_error(f'{key}: the decision {decided[key]} is not the arm\'s ({edge}, {p}, {below})')
        # the flag was taken from the unrounded p; the rounded p must not contradict it
        if edge is not below or (key in rejected) is not edge \
                or (p > HOLDOUT_ALPHA if below else p < HOLDOUT_ALPHA):
            raise _holdout_error(f'{key}: edge {edge}, p_holm {p}, below alpha {below}, rejected {rejected}: '
                                 'the decision contradicts itself')
        if edge and (flat or a['t'] <= 0):
            raise _holdout_error(f'{key} has an edge with a t of {a["t"]} (flat {flat})')
    if rejected != [k for k in family if decided[k]['edge']]:
        raise _holdout_error(f'rejected {rejected}, but the arms with an edge are '
                             f'{[k for k in family if decided[k]["edge"]]}')
    period = arms[0].get('period')
    if any(a.get('days') != arms[0]['days'] or a.get('period') != period for a in arms) \
            or not isinstance(period, list) or len(period) != 2:
        raise _holdout_error('the arms do not share their days')
    matches = H.get('period_matches_calendar')
    if not isinstance(matches, bool) or matches != (period == [cal.backtest_start, cal.data_end]):
        raise _holdout_error(f'period_matches_calendar {matches!r} for trading dates {period}')
    R = H.get('provenance') or {}
    attempts = R.get('attempts') or []
    commit = R.get('commit')
    runs = R.get('run_commits') or {}
    if not attempts or R.get('n_attempts') != len(attempts) \
            or R.get('n_failed') != sum(1 for x in attempts if x.get('failed')) \
            or R.get('n_unfinished') != sum(1 for x in attempts[:-1] if not x.get('failed')):
        raise _holdout_error('the attempt counts are not the attempts\'')
    # the trial's lines of results/trial_attempts.jsonl: those its registry line copies, then the
    # completion line run_holdout.sh appends after registering (absent if it stopped in between)
    copied, lines = _get(R, 'registry', 'attempt_lines'), R.get('attempt_record_lines')
    completed = bool(attempts[-1].get('completed_utc'))
    if attempts[-1].get('failed') or not isinstance(copied, int) or lines != copied + completed \
            or R.get('completed_utc') != attempts[-1].get('completed_utc') \
            or not _get(R, 'registry', 'registered_utc'):
        raise _holdout_error('the last attempt, the registry line and the trial\'s lines in the attempt record '
                             'disagree')
    if not commit or sorted(runs) != sorted(keys) or set(runs.values()) != {commit} \
            or any(a.get('commit') != commit for a in arms) or attempts[-1].get('head') != commit:
        raise _holdout_error(f'the runs ({runs}) and the last attempt are not all from {commit}')
    registered = R.get('registered_commit')
    if not registered or registered != _get(R, 'registry', 'prereg_commit') \
            or R.get('at_registered_commit') is not (commit == registered) \
            or R.get('crash_fix') != attempts[-1].get('crash_fix'):
        raise _holdout_error('the registered commit, the run commit and the last attempt disagree')
    published = {d.get('file', '').rsplit('/', 1)[-1] for d in R.get('crash_fix_diffs') or []}
    if any(x.get('crash_fix') and x['crash_fix'].get('diff') not in published for x in attempts):
        raise _holdout_error('an attempt names a crash-fix diff that is not published')
    daily = H.get('daily')
    if daily is not None:
        dates, cum = daily.get('dates') or [], daily.get('cum') or {}
        if len(dates) != arms[0]['days'] or [dates[0], dates[-1]] != period or set(cum) - set(keys) \
                or any(v is not None and len(v) != len(dates) for v in cum.values()):
            raise _holdout_error('the daily paths are not the arms\' days')
    return H


def _p_text(p, below=None):
    """A p-value as the paper and the site print it: three decimals rounded half up; '<0.050'
    for a Holm-adjusted p that is below alpha but rounds to it (never '0.050' beside a
    rejection), '<0.001' for one that rounds to zero."""
    s = fmt(p, '.3', half_up=True)
    if s is None:
        return None
    if below and s == fmt(HOLDOUT_ALPHA, '.3'):
        return '<' + s
    return '<0.001' if s == '0.000' else s


def _p_rel(text):
    """'0.008' -> '= 0.008', '<0.050' -> '< 0.050': the p-value with its relation, for prose."""
    return None if text is None else (f'< {text[1:]}' if text.startswith('<') else f'= {text}')


_HO_NAMES = {'v33_pairs': 'v33 pairs', 'avellaneda_lee': 'Avellaneda–Lee', 'v32_pairs': 'v32, frozen'}
_HO_FLAT_FIELDS = ('sharpe', 'lo', 'hi', 'gross_sharpe', 'sharpe_lo2002', 'psr_pct', 'sharpe_se', 'ucb', 'mde',
                   'mde_single')


def _utc(ts, zone=' UTC'):
    """'2026-10-21T14:03:09+00:00' -> '2026-10-21 14:03 UTC'."""
    return f'{str(ts)[:10]} {str(ts)[11:16]}{zone}' if ts else None


def _count(n, noun, plural=None):
    """'no crash-fix diff', 'one top-up', '6 step logs': a count in words up to ten."""
    if n is None:
        return None
    return f"{'no' if n == 0 else word(n)} {noun if n == 1 or n == 0 else (plural or noun + 's')}"


def holdout_derived(H):
    """The values the paper states about the evaluated holdout, by arm (s1, s2, s3), with the
    run record; each p-value also as printed text (_p_text). `why` gives the reason a value
    is null: a flat arm (no dispersion in its daily returns) has no Sharpe ratio."""
    arms, R = H['arms'], H['provenance']
    out, why = {}, {}
    for a, (key, hyp, sid, label) in zip(arms, HOLDOUT_ARMS):
        vs, rp, ex = a.get('vs_gatev') or {}, a.get('random_pair') or {}, a.get('exposure') or {}
        gaps = [(u.get('missing_weight_pct') or 0.0) + (u.get('unmapped_weight_pct') or 0.0)
                for u in a.get('universe') or []]
        p_one = _p_text(a['p_one_sided'])
        arm = {
            'key': key, 'hyp': hyp, 'label': label, 'name': _HO_NAMES[key], 'flat': a['flat'],
            'days': a['days'], 'trades': a['trades'], 'ret_pct': a['ret_pct'], 'gross_ret_pct': a.get('gross_ret_pct'),
            'sharpe': a.get('sharpe'), 'lo': a.get('lo'), 'hi': a.get('hi'), 't': a['t'], 'lags': a.get('lags'),
            'gross_sharpe': a.get('gross_sharpe'), 'sharpe_lo2002': a.get('sharpe_lo2002'), 'psr_pct': a.get('psr_pct'),
            'sharpe_se': a.get('sharpe_se'), 'ucb': a.get('ucb'), 'mde': a.get('mde'), 'mde_single': a.get('mde_single'),
            'exp_avg': ex.get('avg_pct'), 'exp_max': ex.get('max_pct'), 'days_open': ex.get('days_open'),
            'gatev_diff': vs.get('diff'), 'gatev_lo': vs.get('lo'), 'gatev_hi': vs.get('hi'), 'gatev_p': vs.get('p'),
            'gatev_sharpe': vs.get('distance_sharpe'), 'gatev_days': vs.get('days'),
            'rp_pct': rp.get('percentile'), 'rp_median': rp.get('median_sharpe'), 'rp_draws': rp.get('n_draws'),
            'p_one_text': p_one, 'p_one_rel': _p_rel(p_one),
            'first_long': long_date(a['period'][0]), 'last_long': long_date(a['period'][1]),
            # an arm with no dispersion: what it did, in words (never a number for its Sharpe ratio)
            'flat_phrase': ('opened no position: its daily net return was zero on every day' if a['trades'] == 0
                            else 'had no dispersion in its daily net returns'),
            'sharpe_or': 'no position' if a['flat'] and a['trades'] == 0 else
                         'not defined' if a['flat'] else fmt(a['sharpe'], '+.2', half_up=True),
            'decision': ('rejected' if a['edge'] else 'not rejected') if hyp else 'not tested',
            'universe_n': len(gaps),
            'gap_first_pct': gaps[0] if gaps else None, 'gap_last_pct': gaps[-1] if gaps else None,
            'gap_min_pct': min(gaps) if gaps else None, 'gap_max_pct': max(gaps) if gaps else None,
        }
        if hyp:
            text = _p_text(a['p_holm'], a['p_holm_below_alpha'])
            arm.update(p_holm_text=text, p_holm_rel=_p_rel(text))
        if a['flat']:
            why.update({f'paper.ho.{sid}.{f}': 'not defined (no dispersion in the daily net returns)'
                        for f in _HO_FLAT_FIELDS})
        if not gaps:
            why.update({f'paper.ho.{sid}.gap_{f}_pct': 'none (no point-in-time universe for this arm)'
                        for f in ('first', 'last', 'min', 'max')})
        out[sid] = arm
    attempts = R['attempts']
    fix = R.get('crash_fix') or {}
    diff = next((d for d in R.get('crash_fix_diffs') or [] if d['file'].endswith('/' + fix.get('diff', '\0'))), {})
    fetch = R.get('price_fetch') or {}
    registered_utc = _get(R, 'registry', 'registered_utc')
    n, nf, nu = R['n_attempts'], R['n_failed'], R['n_unfinished']
    # how the attempts ended, in words: 'one attempt'; 'two attempts: one failed and the last
    # completed'; 'three attempts: one failed, one stopped without finishing or recording a
    # failure and the last completed' (an earlier attempt ends in one of the two; holdout_block)
    ends = ([f'{word(nf)} failed'] if nf else []) + (
        [f'{word(nu)} stopped without finishing or recording a failure'] if nu else []) + [
        'the last completed' if R['completed_utc'] else 'the last registered the trial']
    s1 = arms[0]
    out.update({
        'days': s1['days'], 'first_long': long_date(s1['period'][0]), 'last_long': long_date(s1['period'][1]),
        'calendar_start_long': long_date(H['calendar_start']), 'calendar_end_long': long_date(H['calendar_end']),
        'rejected': [sid for key, _, sid, _ in HOLDOUT_ARMS if key in H['decision']['rejected']],
        'run': {
            'commit': R['commit'][:12], 'registered': R['registered_commit'][:12],
            'n_attempts': n, 'n_failed': nf, 'n_unfinished': nu,
            'attempts_phrase': 'one attempt' if n == 1 else
                               f"{word(n)} attempts: {', '.join(ends[:-1])} and {ends[-1]}",
            'started': _utc(attempts[0]['started_utc']), 'completed': _utc(R['completed_utc']),
            # the end of the run: its completion line, or (without one) the trial's registration
            'until': _utc(R['completed_utc']) or f'{_utc(registered_utc)}, when it registered the trial',
            'registered_long': long_date(registered_utc) if registered_utc else None,
            'crash_fix': fix.get('fix'), 'crash_fix_diff': fix.get('diff'),
            'crash_fix_sha': fix.get('sha256'), 'crash_fix_files': ', '.join(diff.get('files') or []) or None,
            'crash_fix_insertions': diff.get('insertions'), 'crash_fix_deletions': diff.get('deletions'),
            'logs': _get(R, 'logs', 'count'), 'step_logs': _get(R, 'logs', 'step_logs'),
            'environment': _get(R, 'logs', 'environment'), 'diffs': _get(R, 'logs', 'diffs'),
            # what results/holdout2026/logs/ holds, in words: '7 files: 6 step logs, one environment
            # listing and no crash-fix diff'
            'logs_phrase': (f"{_count(_get(R, 'logs', 'count'), 'file')}: "
                            f"{_count(_get(R, 'logs', 'step_logs'), 'step log')}, "
                            f"{_count(_get(R, 'logs', 'environment'), 'environment listing')} and "
                            f"{_count(_get(R, 'logs', 'diffs'), 'crash-fix diff')}")
                           if R.get('logs') else None,
            'fetched': _utc(fetch.get('fetched_utc')), 'fetch_symbols': fetch.get('symbols'),
            'top_ups': fetch.get('top_ups'), 'top_ups_phrase': _count(fetch.get('top_ups'), 'top-up'),
            # the first fetch, then the top-ups ('one top-up, at ...'; 'two top-ups, the last at ...')
            'requested': fetch.get('requested'),
            'first_requested': (fetch['requested'] - (fetch.get('top_up_attempted') or 0)) if fetch.get('requested') else None,
            'first_ok': (fetch['symbols'] - (fetch.get('top_up_fetched') or 0)) if fetch.get('symbols') is not None else None,
            'top_up_attempted': fetch.get('top_up_attempted'), 'top_up_ok': fetch.get('top_up_fetched'),
            'top_ups_when': (f"{_count(fetch['top_ups'], 'top-up')}, {'at' if fetch['top_ups'] == 1 else 'the last at'} "
                             f"{_utc(fetch.get('last_top_up_utc'))}") if fetch.get('top_ups') else None,
        },
        'why': why,
    })
    why.update({f'paper.ho.run.{k}': 'none recorded' for k, v in out['run'].items() if v is None})
    return out


def trade_edge(trades):
    """Gross and cost per trade on one basis: dollars over traded notional (signal-day size).

    The ratio of sums is the basis on which net P&L breaks even (gross / cost dollars);
    the t-statistic is that of the mean gross dollar P&L per trade.
    """
    if not trades:
        return None
    notional = sum(t['position_size_dollars'] for t in trades)
    cost = np.array([t['transaction_costs_dollars'] for t in trades])
    gross = np.array([t['net_pnl_dollars'] for t in trades]) + cost
    t_gross = float(gross.mean() / (gross.std(ddof=1) / math.sqrt(len(gross))))
    return {'gross_bp': 1e4 * gross.sum() / notional, 'cost_bp': 1e4 * cost.sum() / notional,
            'net_bp': 1e4 * (gross.sum() - cost.sum()) / notional, 'gross_t': t_gross}


def _formations(dev):
    """Formation dates of the run (initial selection first), from its universe record."""
    return [u['formation_date'] for u in dev.get('universe_by_formation') or []]


def derived(inp):
    """The 'paper' namespace: values the paper states that the site file holds only implicitly."""
    study, head = inp['study'], inp['headline']
    dev = study['dev']
    run = dev['run']
    calendar = CALENDARS['dev']
    holdout_calendar = CALENDARS['holdout2026']
    study_cfg = _get(head, 'run_config', 'study', default={})
    design = _get(study_cfg, 'profile', 'name') or str(run.get('name') or '').split('_')[0]
    if design not in PROFILES:
        raise PaperDataError(f'the run records no study profile the paper knows ({design!r})')
    profile, v32_profile = PROFILES[design], PROFILES['v32']
    months = dev['monthly']
    best = max(months, key=lambda m: m['ret_pct']) if months else None
    sn = dev.get('snooping') or {}
    hold = study.get('holdout') or {}
    v32 = study.get('v32') or {}
    schedules = dev.get('cost_schedules') or []
    funds = head.get('fund_profiles') or {}

    def fund_ret(s):            # the headline JSON's figure (as the site prints it), else the replay's
        return _get(funds, s['source_key'], 'total_return_pct', default=s['ret_pct'])
    neg = [s for s in schedules if fund_ret(s) < 0]
    ranked = sorted(schedules, key=fund_ret)
    forest = {r['key']: r for r in dev['forest']}
    snaps = universe_snapshots(inp['universe_index'])
    power = holdout_power(dev['daily']['net'])
    # the note's date: its newest dated input (the newest run behind study.json, the declaration
    # of the variant family, or the holdout's registration and completion), never the build
    # machine's clock
    dated = [study['meta']['generated_utc'][:10], (sn.get('declared_utc') or '')[:10],
             (_get(study, 'holdout', 'provenance', 'registry', 'registered_utc') or '')[:10],
             (_get(study, 'holdout', 'provenance', 'completed_utc') or '')[:10]]
    paper_date = max(d for d in dated if d)
    trades = inp['results'].get('all_trades') or []
    boot = re.search(r'\((\d+) resamples, block (\d+) days\)', forest['main']['method'])
    boot_oos = re.search(r'block (\d+) days', forest['oos']['method'])
    diff_oos = forest.get('diff_oos') or {}
    export = inp['results']
    edge = trade_edge(trades)
    wf_windows = export['walk_forward_validation']['windows']
    vs_wf = _get(export, 'benchmarks', 'vs_strategy', 'walk_forward_oos', default={})
    fdr = head['fdr']
    pos = [x['position_pct_of_equity'] for x in trades if x.get('position_pct_of_equity') is not None]
    formations = _formations(dev)
    scen = _get(dev, 'cost_sensitivity', 'scenarios', default={}) or {}
    hl = [p for p in _get(dev, 'half_lives', 'pairs', default=[]) if p.get('f') is not None]
    v32_universe = inp.get('v32_universe') or {}
    trials = study.get('trials') or []
    evaluated = holdout_block(study, inp.get('holdout_calendar', HOLDOUT_CALENDAR))
    return {
        'paper_date': paper_date, 'paper_date_long': long_date(paper_date),
        'run_date_long': long_date(run['timestamp_utc']),
        'run_time': run['timestamp_utc'][:16].replace('T', ' ') + ' UTC',
        'design': design, 'versions_count': int(design.lstrip('v')),
        'profile_hash': _get(study_cfg, 'profile_hash'), 'calendar_hash': _get(study_cfg, 'calendar_hash'),
        'commit': run['commit'][:12], 'commit_short': run['commit'][:7],
        'clean': 'clean' if run['dirty'] is False else 'uncommitted changes',
        'years': f"{run['period'][0][:4]}–{run['period'][1][:4]}",
        'data_years': f"{run['data_span'][0][:4]}–{run['data_span'][1][:4]}",
        'data_first_year': run['data_span'][0][:4], 'formation_year': calendar.selection_cutoff[:4],
        'holdout_year': hold['calendar_start'][:4] if hold.get('calendar_start') else None,
        'period_start_long': long_date(run['period'][0]), 'period_end_long': long_date(run['period'][1]),
        'period_start_month': month_name(run['period'][0]), 'period_end_month': month_name(run['period'][1]),
        'oos_start_long': long_date(run['oos_period'][0]),
        'oos_start_month': month_name(run['oos_period'][0]), 'oos_end_month': month_name(run['oos_period'][1]),
        'data_start_long': long_date(run['data_span'][0]), 'data_end_long': long_date(run['data_span'][1]),
        'formation_cutoff_long': long_date(calendar.selection_cutoff),
        'formation_cutoff_short': short_date(calendar.selection_cutoff),
        'holdout_start_long': long_date(hold['calendar_start']) if hold.get('calendar_start') else None,
        'holdout_end_long': long_date(evaluated['calendar_end'] if evaluated else holdout_calendar.data_end),
        'declared_long': long_date(sn['declared_utc']) if sn.get('declared_utc') else None,
        'best_month': month_name(best['ym']) if best else None,
        'percentile_ordinal': ordinal(dev['random_percentile']) if dev.get('random_percentile') is not None else None,
        'v32_percentile_ordinal': ordinal(v32['random_percentile']) if v32.get('random_percentile') is not None else None,
        'names_prices': run['symbols'],
        # the design profiles (pairs_trading/study_config.py)
        'universe_top': profile.max_universe, 'reselect_every': profile.reselect_every,
        'formation_years': profile.formation_calendar_days / 365, 'borrow_pct': 100 * profile.borrow_rate,
        'formation_years_word': word(profile.formation_calendar_days // 365),
        'v32_universe_top': v32_profile.max_universe, 'v32_reselect_every': v32_profile.reselect_every,
        'v32_formation_years': v32_profile.formation_calendar_days / 365,
        'v32_borrow_bp': 1e4 * v32_profile.borrow_rate, 'v32_financing_bp': 1e4 * v32_profile.pb_financing_spread,
        # the published v32 run and its universe file
        'v32_run_date_long': long_date(v32['run']['timestamp_utc']) if _get(v32, 'run', 'timestamp_utc') else None,
        'v32_commit_short': _get(v32, 'run', 'commit', default='')[:7] or None,
        'v32_universe_as_of_long': long_date(v32_universe['as_of_utc']) if v32_universe.get('as_of_utc') else None,
        'v32_universe_selected': v32_universe.get('selected'),
        # formations of this run
        'formations_word': word(len(formations)) if formations else None,
        'first_formation_long': long_date(formations[0]) if formations else None,
        'last_formation_long': long_date(formations[-1]) if formations else None,
        'schedules_n': len(schedules), 'schedules_n_word': word(len(schedules)),
        'schedules_lose_word': word(len(neg)),
        'holdout': {'status': hold.get('status'), 'sharpe': hold.get('sharpe'), 'lo': hold.get('lo'),
                    'hi': hold.get('hi'), 'p': hold.get('p'), 'trades': hold.get('trades'), 'ret_pct': hold.get('ret_pct')},
        'iwv': ({'n': snaps['n'], 'first_long': long_date(snaps['first']), 'last_long': long_date(snaps['last']),
                 'equity_min': snaps['equity_min'], 'equity_max': snaps['equity_max'],
                 'unmapped_min_pct': snaps['unmapped_min_pct'], 'unmapped_max_pct': snaps['unmapped_max_pct'],
                 'sealed_from_long': long_date(snaps['sealed_from']), 'sealed': snaps['sealed']} if snaps else None),
        'factor_data_end_long': long_date(dev['facts']['factor_data_end']) if dev['facts'].get('factor_data_end') else None,
        'iwv_unmapped_first_pct': snaps['rows'][0]['unmapped_weight_pct'] if snaps else None,
        'iwv_unmapped_last_pct': snaps['rows'][-1]['unmapped_weight_pct'] if snaps else None,
        'iwv_first_year': snaps['first'][:4] if snaps else None, 'iwv_last_year': snaps['last'][:4] if snaps else None,
        'holdout_power_rows': power['rows'],
        'holdout_power': {'rho': power['rho'], 'skew': power['skew'], 'kurtosis': power['kurtosis'],
                          'registered_days': HOLDOUT_DAYS[1],
                          **{f"mde_{r['days']}": r['mde_shape'] for r in power['rows']},
                          **{f"mde_05_{r['days']}": r['mde_shape_05'] for r in power['rows']},
                          **{f"mde_normal_{r['days']}": r['mde_normal'] for r in power['rows']}},
        'prereg_status': 'filed' if inp['preregistered'] else 'not yet filed',
        'results_path': inp['results_path'], 'run_dir': inp['results_path'].rsplit('/', 1)[0],
        'boot_resamples': int(boot.group(1)) if boot else None,
        'boot_block_main': int(boot.group(2)) if boot else None,
        'boot_block_oos': int(boot_oos.group(1)) if boot_oos else None,
        'diff_oos': diff_oos.get('sharpe'), 'diff_oos_p': diff_oos.get('p'),
        'sched_best_id': ranked[-1]['id'] if ranked else None,
        'sched_worst_id': ranked[0]['id'] if ranked else None,
        'sched_best_ret': fund_ret(ranked[-1]) if ranked else None,
        'sched_worst_ret': fund_ret(ranked[0]) if ranked else None,
        # gross and cost per trade, weighted by traded notional (the break-even basis)
        'edge': edge,
        # Lo (2002) autocorrelation-adjusted annualisation of the Sharpe ratio
        'lo_sharpe_main': _get(export, 'significance', 'main_backtest', 'ann_sharpe_lo'),
        'lo_sharpe_oos': _get(export, 'significance', 'oos_daily', 'ann_sharpe_lo'),
        'position_min_pct': min(pos) if pos else None, 'position_max_pct': max(pos) if pos else None,
        # the walk-forward: the last window runs to the walk-forward's last day
        'wf_window_days': wf_windows[0]['n_days'], 'wf_last_days': wf_windows[-1]['n_days'],
        'wf_days': {w['window']: w['n_days'] for w in wf_windows},
        'oos_end_long': long_date(run['oos_period'][1]),
        'gatev_wf_sharpe': vs_wf.get('distance_sharpe'), 'wf_common_sharpe': vs_wf.get('strategy_sharpe'),
        'wf_common_days': vs_wf.get('n_common_days'),
        'performance': performance(study),
        # chance rejections among the "cointegrated" pairs: an upper bound (every pair null)
        'chance_share_pct': 100 * dev['funnel']['pairs'][1]['expected'] / fdr['significant_raw_p05'],
        # how much longer than the minimum track record 80% power takes (normal approximation)
        'trl_power_ratio': ((_Z95 + _Z80) / _Z95) ** 2,
        'gatev_vol_pct': _get(export, 'benchmarks', 'distance_method', 'ann_volatility_pct'),
        'main_vol_pct': _get(export, 'overall_performance', 'annualized_volatility_pct'),
        # the traded pairs' half-lives (anatomy.json, persistence_detail.traded_pairs)
        'hl_pairs': len(hl),
        'hl_none_oos': sum(1 for p in hl if p.get('o') is None),
        # the cost scenarios that re-run the backtest in full
        'scenario_10m_fixed_positive': _get(scen, 'capital_10m', 'fixed', 'sharpe'),
        # the trial registry
        'trials_n': len(trials), 'trials_word': word(len(trials)),
        # the evaluated 2026 holdout (None while sealed)
        'ho': holdout_derived(evaluated) if evaluated else None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# The numbers the text quotes: key -> format (a key resolves like the publication
# checker's: into the headline JSON, 'study.' into assets/study.json, 'paper.' into
# derived() above). 'str' passes a text value through. Formats follow the site's own
# precision wherever the site prints the same number (tests/test_build_paper.py).
# ──────────────────────────────────────────────────────────────────────────────

_FACTS = {
    # the run and the book
    'trades': '.0', 'days': '.0', 'main_days': '.0', 'oos_days': '.0', 'capital_musd': '.0', 'flat_days': '.0',
    'avg_exposure_pct': '.1%', 'exposure_max_pct': '.2%', 'positions_max': '.0', 'coverage_pct': '.1%',
    'cached_pct': '.1%', 'not_found_pct': '.1%', 'fetch_other_pct': '.1%', 'formations_traded': '.0',
    'gap_heavy_members': '.0', 'wf_last_window_days': '.0',
    'exposure_days_above_cap': '.0', 'position_min_pct': '.1%', 'position_max_pct': '.1%',
    'sched_trades_min': '.0', 'sched_trades_max': '.0', 'sched_gross_negative': '.0',
    'sched_gross_min_pct': '.2%', 'sched_gross_max_pct': '.2%', 'cash_tbill_yield_pct': '.2%',
    **{f'gap_{tag}_{k}_pct': '.2' for tag in ('first', 'last') for k in ('not_found', 'fetch_failed', 'data_checks')},
    **{f'gap_{tag}_{k}': '.0' for tag in ('first', 'last')
       for k in ('heavy_missing', 'heavy_not_found', 'heavy_fetch_failed')},
    'gap_first_heavy_missing_pct': '.2%', 'gap_last_heavy_missing_pct': '.2%',
    'decay_engine_lo': '.1', 'decay_engine_hi': '+.1', 'decay_oos_lo': '.1', 'decay_oos_hi': '+.1',
    'hold_days': '.1', 'adv_participation_pct': '.2%', 'formations': '.0', 'pairs_traded': '.0',
    'oos_overlap_days': '.0', 'wf_common_days': '.0', 'wf_common_corr': '.2', 'wf_common_sharpe_main': '.2',
    'wf_common_sharpe_oos': '.2', 'stitched_pct': '.2%',
    'months': '.0', 'months_positive': '.0', 'best_month_pct': '+.2%',
    'sharpe_2023': '+.2', 'sharpe_2024': '.2', 'sharpe_2025': '.2',
    'rolling_min': '.1', 'rolling_max': '+.1', 'rolling_clear_zero': '.0', 'rolling_windows': '.0',
    'random_p05_end': '.1%', 'random_p25_end': '.1%', 'random_p75_end': '+.1%', 'random_p95_end': '+.1%',
    # gross against costs
    'gross_bp': '+.1', 'gross_t': '.2', 'cost_bp': '.1', 'net_bp': '.1', 'net_t': '.2',
    'gross_usd_k': ',.1', 'cost_usd_k': ',.1', 'net_usd_k': '.1', 'gross_usd_m': '.2', 'cost_usd_m': '.2',
    'impact_share_pct': '.1%', 'break_even_x': '.2×', 'sharpe_break_even_x': '.2×',
    'market_impact_usd_k': ',.1', 'bid_ask_usd_k': '.1', 'commission_usd_k': '.1', 'borrow_usd_k': '.1',
    'gross_bp_capital': '.1', 'cost_bp_capital': '.1', 'net_bp_capital': '.1', 'cost_bp_notional': '.2',
    'sf_paper_usd_k': ',.1', 'sf_entry_delay_gain_usd_k': '.1', 'sf_exit_delay_loss_usd_k': '.1',
    'sf_gross_bp': '.2', 'sf_paper_bp': '.2', 'cash_tbill_pct': '.2%',
    'gross_sharpe': '+.2', 'gross_hac_p': '.3', 'wf_gross_sharpe': '.2', 'wf_gross_hac_p': '.3',
    'cost_0x_sharpe': '+.2', 'cost_2x_sharpe': '.2',
    # the trades
    'stop_loss_usd_m': '.2', 'target_gain_usd_m': '.2', 'long_gain_usd_m': '.2', 'short_loss_usd_m': '.2',
    'wins': '.0', 'win_lo_pct': '.1', 'win_hi_pct': '.1%', 'hedge_mean': '.2', 'hedge_below_1_pct': '.1%',
    'beta_long_per_gross': '+.2', 'beta_short_per_gross': '.2', 'market_usd_k': '.1',
    'gross_ex_market_bp': '.1', 'gross_ex_market_t': '.2', 'long_gross_bp': '+.1', 'long_gross_t': '.2',
    'short_gross_bp': '.1', 'short_gross_t': '.2',
    # the anatomy: persistence, decay, exit race, half-lives
    'pers_pct': '.2%', 'pers_expected_pct': '.2%', 'pers_count': '.0', 'pers_of': ',.0', 'pers_expected': '.1',
    'pers_lo_pct': '.2', 'pers_hi_pct': '.2%', 'pers_z': '.2', 'pers_traded_count': '.0', 'pers_traded_of': '.0',
    'pers_traded_pct': '.1%', 'pers_symbols': '.0',
    'decay_form_bp': '+.1', 'decay_form_t': '.2', 'decay_form_tc': '.2', 'decay_form_n': ',.0',
    'decay_oos_bp': '.1', 'decay_oos_t': '.2', 'decay_oos_tc': '.2', 'decay_oos_n': ',.0',
    'decay_engine_bp': '.1', 'decay_engine_t': '.2', 'decay_engine_n': '.0', 'decay_pairs': '.0',
    'er_targets': '.0', 'er_stops': '.0', 'er_barrier': '.0', 'er_other': '.0', 'er_rw_expected': '.1',
    'er_rw_z': '+.2', 'er_rw_p': '.3', 'er_ou_expected': '.1', 'er_ou_z': '.2', 'er_half_life': '.1',
    'er_share_pct': '.1%', 'er_rw_share_pct': '.1%', 'er_ou_share_pct': '.1%',
    'hl_formation': '.1', 'hl_oos': '.1', 'hl_oos_above_max_pct': '.1%', 'hl_max': '.0',
    # power, the upper bound and the hurdles
    'sharpe_se': '.2', 'sharpe_ucb': '.2', 'sharpe_mde': '.2', 'sharpe_critical': '.2',
    'p_sr_ge_1': '.3', 'p_sr_ge_0_5': '.3', 'min_trl_years_0_5': '.1', 'min_trl_years_1': '.1',
    'oos_ucb': '.2', 'oos_mde': '.2', 'oos_sharpe_se': '.2', 'oos_critical': '.2',
    'hurdle_tests': '.0', 'hurdle_single': '.2', 'hurdle_bonferroni': '.2', 'hurdle_hlz': '.2',
    'hurdle_hlz_t': '.2', 'hurdle_cgs': '.2', 'hurdle_cgs_t': '.2', 'dsr_trials': '.0',
    'ho_days': '.0', 'ho_mde_025': '.2', 'ho_mde_025_normal': '.2', 'ho_mde_05': '.2', 'ho_mde_05_normal': '.2',
    'ho_power_1': '.0%', 'ho_power_2': '.0%', 'ho_power_3': '.0%',
    'ho_power_1_normal': '.0%', 'ho_power_2_normal': '.0%', 'ho_power_3_normal': '.0%',
    # baselines
    'gatev_lo': '.2', 'gatev_hi': '+.2',
    # costs and capacity
    'cap_10m_impact_bp': '.1', 'cap_100m_impact_bp': '.1', 'cap_1b_impact_bp': '.1', 'cap_5b_impact_bp': '.1',
    'cap_10m_net_bp': '.1', 'cap_100m_net_bp': '.1', 'cap_1b_net_bp': '.1', 'cap_5b_net_bp': '.1',
    'rej_cap_signal': ',.0', 'rej_cap_fill': ',.0', 'rej_cooloff': '.0', 'signals_evaluated': ',.0',
    # risk and attribution
    'st_rev_t_main': '.2', 'st_rev_t_oos': '.2', 'st_rev_beta_main': '.3', 'mkt_t_main': '.2', 'mkt_t_oos': '.2',
    'mkt_beta_main': '.3', 'mom_t_main': '.2', 'mom_t_oos': '.2', 'ff_r2_main': '.3', 'ff_r2_oos': '.3',
    'ff_alpha_main_pct': '.2%', 'ff_alpha_main_t': '.2', 'ff_alpha_oos_pct': '.2%', 'ff_alpha_oos_t': '.2',
    'beta_main': '.3', 'beta_main_t': '.2', 'beta_oos': '.3', 'beta_oos_t': '.2', 'kurtosis': '.1', 'skew': '.2',
    # the universe: the survivorship gap and the price anchoring
    'gap_first_pct': '.2%', 'gap_last_pct': '.2%', 'gap_first_members': ',.0', 'gap_first_missing': '.0',
    'gap_last_members': ',.0', 'gap_last_missing': '.0',
    'anchor_moved': '.0', 'anchor_symbols': ',.0', 'anchor_moved_pct': '.1%', 'anchor_max_ratio': '.1',
    'anchor_min_ratio_inv': '.0',
    # the robustness checks (results/v33_dev/robustness.json)
    'start_n': '.0', 'start_step_days': '.0', 'start_headline_rank': '.0', 'start_common_days': '.0',
    'start_sharpe_min': '.2', 'start_sharpe_max': '.2', 'start_sharpe_median': '.2',
    'start_common_sharpe_min': '.2', 'start_common_sharpe_max': '+.2', 'start_ret_min': '.2%', 'start_ret_max': '.2%',
    'start_common_sharpe_median': '.2', 'start_common_rank': '.0', 'start_matched_wins': '.0', 'start_matched_of': '.0',
    'start_matched_gap_median': '.2', 'start_matched_published_min': '.2', 'start_matched_published_max': '.2',
    'half1_sharpe': '+.2', 'half2_sharpe': '.2', 'half1_inside_sharpe': '+.2', 'half2_inside_sharpe': '.2',
    'half1_run_off_days': '.0', 'half1_ret_pct': '+.2%', 'half2_ret_pct': '.2%',
    'vix_low_bp': '.2', 'vix_high_bp': '+.2', 'vix_diff_mean_bp': '+.2', 'vix_diff_t': '.2', 'vix_diff_p': '.2',
    'vix_break_lo': '.2', 'vix_break_hi': '.2', 'disp_diff_mean_bp': '.2', 'disp_diff_t': '.2',
    'pers_s1_count': '.0', 'pers_s1_of': ',.0', 'pers_s1_pct': '.2%', 'pers_s1_lo_pct': '.1', 'pers_s1_hi_pct': '.1%',
    'pers_s1_expected': '.1', 'pers_s1_expected_pct': '.1%', 'pers_s1_z': '.2', 'pers_s1_pairs': ',.0',
    'pers_s1_formations': '.0', 'pers_s1u_count': '.0', 'pers_s1u_of': ',.0', 'pers_s1u_pct': '.1%',
    'pers_s1u_expected': '.1', 'pers_s1u_z': '.2', 'pers_s1u_pairs': ',.0',
    's2c_gross_month_t': '.2', 's2c_gross_month_p': '.2', 's2c_gross_month_clusters': '.0',
    's2c_gross_month_design_effect': '.1', 's2c_gross_date_t': '.2', 's2c_gross_symbol_t': '.2',
    's2c_net_mean_bp': '.2', 's2c_net_month_t': '.2',
}
_RESIDUAL = {
    'sharpe': '.2', 'lo': '.2', 'hi': '+.2', 'p': '.3', 'hac_t': '.2', 'trades': ',.0', 'ret_pct': '.2%',
    'max_dd_pct': '.2%', 'psr_pct': '.1%', 'gross_sharpe': '+.2', 'gross_lo': '.2', 'gross_hi': '+.2',
    'gross_p': '.3', 'gross_bp': '+.2', 'gross_t': '.2', 'cost_bp': '.2', 'net_bp': '.2', 'net_t': '.2',
    'stock_cost_bp': '.2', 'etf_cost_bp': '.2',
    'cost_usd_m': '.2', 'gross_usd_m': '.2', 'etf_cost_usd_m': '.2', 'turnover_x': '.1×', 'avg_positions': '.0',
    'max_positions': '.0', 'universe_size': '.0', 'hold_days': '.1', 'win_rate_pct': '.1%', 'days': '.0',
    'avg_gross_x': '.1×', 'symbols_ever': '.0',
}
_V32 = {
    'main.sharpe': '.2', 'main.lo': '.2', 'main.hi': '+.2', 'main.p': '.3', 'main.ret_pct': '.2%',
    'main.trades': '.0', 'main.max_dd_pct': '.2%', 'main.avg_exposure_pct': '.1%',
    'oos.sharpe': '.2', 'oos.lo': '.2', 'oos.hi': '+.2', 'oos.p': '.3', 'oos.ret_pct': '.2%',
    'oos.windows': '.0', 'oos.windows_positive': '.0',
    'gross_bp': '+.1', 'gross_t': '.2', 'cost_bp': '.1', 'flat_days': '.0', 'gate_blocked_days': '.0', 'days': '.0',
    'gatev_sharpe': '+.2', 'random_percentile': '.0', 'ranker_auc': '.3', 'pairs_tested': ',.0',
    'pairs_selected': ',.0', 'bh_q05': '.0',
}
_SNOOPING = {
    'n': '.0', 'days': '.0', 'positive': '.0', 'sharpe_best': '+.2', 'sharpe_median': '.2', 'sharpe_worst': '.2',
    'best_label': 'str', 'base_rank': '.0', 'base_sharpe': '.2', 'ret_best_pct': '+.2', 'ret_worst_pct': '.2',
    'trades_min': '.0', 'trades_max': '.0',
    'spa_zero.p': '.3', 'spa_zero.p_lower': '.3', 'spa_zero.p_upper': '.3', 'spa_zero.rc_p': '.3',
    'spa_zero.best_t': '.2', 'spa_zero.best_label': 'str',
    'spa_gatev.p': '.3', 'spa_gatev.rc_p': '.3', 'spa_gatev.best_t': '.2', 'spa_gatev.best_label': 'str',
    'spa_gatev_unit_vol.p': '.3', 'spa_gatev_unit_vol.rc_p': '.3', 'spa_gatev_unit_vol.best_t': '.2',
    'spa_gatev.block': '.0', 'spa_gatev_unit_vol.block': '.0',
    'rw_rejected': '.0', 'rw_min_p': '.2', 'mcs_included': '.0', 'mcs_min_p': '.2', 'mcs_size_pct': '.0%',
    'effective_rank': '.1', 'avg_corr': '.2', 'pbo_pct': '.1%', 'pbo_splits': '.0', 'pbo_blocks': '.0',
    'pbo_is_best_oos_sharpe': '.2', 'pbo_is_best_loss_pct': '.1%', 'pbo_base_loss_pct': '.1%',
    'pbo_median_oos_sharpe': '.2', 'dsr_best.dsr_pct': '.1%', 'dsr_best.sharpe': '+.2', 'dsr_best.psr_pct': '.1%',
    'dsr.n_trials': '.0', 'dsr.dsr_pct': '.1%', 'dsr.sd_sr': '.2', 'dsr.sr_star': '.2',
    'reps': ',.0', 'block': '.0',
}
_VALIDATION = {
    'seeds': '.0', 'edge.trades': ',.0', 'edge.mean_bp': '+.1', 'edge.t': '.1', 'edge.median_net_sharpe': '.2',
    'forced_null.trades': ',.0', 'forced_null.mean_bp': '+.1', 'forced_null.t': '.2',
    'hedge_ratio.median_abs_error': '.3', 'hedge_ratio.p90_abs_error': '.3', 'selection.recall': '.3',
    'selection.unrelated_per_planted_market': '.1', 'selection.per_null_market': '.1',
    'selection.worst_fp_rate': '.4',
}

METRICS = {
    # headline JSON (the checker's source)
    'main.total_return_pct': '.2%', 'main.sharpe': '.2', 'main.trades': '.0', 'main.win_rate_pct': '.1%',
    'main.max_drawdown_pct': '.2%', 'main.avg_gross_exposure_pct': '.1%', 'main.annual_turnover_x': '.1×',
    'main.exit_reasons.stop': '.0', 'main.exit_reasons.target': '.0', 'main.exit_reasons.time': '.0',
    'main.exit_reasons.end_of_data': '.0',
    'oos.windows': '.0', 'oos.windows_positive': '.0', 'oos.windows_no_trades': '.0', 'oos.trades': '.0',
    'oos.avg_window_return_pct': '.2%', 'oos.pooled_sharpe': '.2', 'oos.total_return_pct': '.2%',
    'significance.main.ann_sharpe': '.2', 'significance.main.hac_t': '.2', 'significance.main.hac_p': '.3',
    'significance.main.psr_pct': '.1%', 'significance.main.dsr_pct': '.1%',
    'significance.main.boot_lo': '.2', 'significance.main.boot_hi': '+.2',
    'significance.oos_daily.ann_sharpe': '.2', 'significance.oos_daily.hac_t': '.2',
    'significance.oos_daily.hac_p': '.3', 'significance.oos_daily.psr_pct': '.1%',
    'significance.oos_daily.dsr_pct': '.1%', 'significance.oos_daily.boot_lo': '.2',
    'significance.oos_daily.boot_hi': '+.2',
    'significance.oos_windows.ci_lo_pct': '.2%', 'significance.oos_windows.ci_hi_pct': '+.2%',
    'significance.oos_windows.p': '.3', 'significance.oos_windows.t': '.2',
    'benchmarks.gatev.total_return_pct': '.2%', 'benchmarks.gatev.sharpe': '.2',
    'benchmarks.random_control.median_sharpe': '+.2', 'benchmarks.random_control.p5_sharpe': '.2',
    'benchmarks.random_control.p95_sharpe': '+.2', 'benchmarks.random_control.n_draws': '.0',
    'benchmarks.random_control.strategy_percentile': '.0',
    'benchmarks.sharpe_diff_vs_gatev.diff': '+.2', 'benchmarks.sharpe_diff_vs_gatev.p': '.3',
    'fdr.pairs_tested': ',.0', 'fdr.significant_raw_p05': ',.0', 'fdr.survive_bh_fdr_q05': '.0',
    'fdr.survive_bh_fdr_q10': '.0', 'fdr.final_selected_pairs': ',.0',
    'universe.missing_value_weight_pct': '.3%', 'universe.unmapped_value_weight_pct': '.3%',
    # assets/study.json: facts the site quotes, and the other arms
    **{f'study.dev.facts.{k}': v for k, v in _FACTS.items()},
    **{f'study.residual.{k}': v for k, v in _RESIDUAL.items()},
    **{f'study.v32.{k}': v for k, v in _V32.items()},
    **{f'study.validation.{k}': v for k, v in _VALIDATION.items()},
    'study.dev.snooping.grid_points': '.0', 'study.dev.snooping.toggles': '.0',
    'study.dev.funnel.pairs.1.expected': ',.1', 'study.dev.funnel.bh_q10': '.0',
    'study.dev.rolling_sharpe.window': '.0',
    'study.dev.cost_sensitivity.trades_min': '.0', 'study.dev.cost_sensitivity.trades_max': '.0',
    **{f'study.dev.cost_sensitivity.scenarios.{s}.full.{k}': v
       for s in ('headline', 'impact_0_6', 'impact_1_0', 'borrow_1', 'borrow_3', 'capital_10m', 'capital_1b',
                 'capital_5b')
       for k, v in (('sharpe', '.2'), ('ret_pct', '.2%'), ('trades', '.0'), ('adv_pct', '.2%'))},
    'study.dev.cost_sensitivity.scenarios.capital_10m.fixed.ret_pct': '+.2%',
    'study.dev.cost_sensitivity.scenarios.capital_10m.fixed.sharpe': '+.2',
    'study.trials.1.oos_sharpe': '+.2', 'study.trials.1.sharpe': '.2',
    # derived ('paper.')
    **{f'paper.{k}': 'str' for k in (
        'paper_date_long', 'run_date_long', 'run_time', 'design', 'profile_hash', 'calendar_hash', 'commit',
        'commit_short', 'clean', 'years', 'data_years', 'data_first_year', 'formation_year', 'holdout_year',
        'period_start_long', 'period_end_long', 'period_start_month', 'period_end_month', 'oos_start_long',
        'oos_start_month', 'oos_end_month', 'oos_end_long', 'data_start_long', 'data_end_long',
        'formation_cutoff_long', 'formation_cutoff_short', 'holdout_start_long', 'holdout_end_long',
        'declared_long', 'best_month', 'percentile_ordinal', 'v32_percentile_ordinal', 'v32_run_date_long',
        'v32_commit_short', 'v32_universe_as_of_long', 'formations_word', 'first_formation_long',
        'last_formation_long', 'formation_years_word', 'schedules_n_word', 'schedules_lose_word', 'prereg_status',
        'results_path', 'run_dir', 'sched_best_id', 'sched_worst_id', 'iwv_first_year', 'iwv_last_year',
        'iwv.first_long', 'iwv.last_long', 'iwv.sealed_from_long', 'trials_word', 'factor_data_end_long')},
    'paper.versions_count': '.0', 'paper.names_prices': ',.0', 'paper.universe_top': '.0',
    'paper.reselect_every': '.0', 'paper.formation_years': '.0', 'paper.borrow_pct': '.2%',
    'paper.v32_universe_top': '.0', 'paper.v32_reselect_every': '.0', 'paper.v32_formation_years': '.0',
    'paper.v32_borrow_bp': '.0', 'paper.v32_financing_bp': '.0', 'paper.v32_universe_selected': ',.0',
    'paper.edge.gross_bp': '+.1', 'paper.edge.cost_bp': '.1', 'paper.edge.net_bp': '.1', 'paper.edge.gross_t': '.2',
    'paper.lo_sharpe_main': '.2', 'paper.lo_sharpe_oos': '.2',
    'paper.position_min_pct': '.1%', 'paper.position_max_pct': '.1%',
    'paper.wf_window_days': '.0', 'paper.wf_last_days': '.0',
    'paper.gatev_wf_sharpe': '.2', 'paper.wf_common_sharpe': '.2', 'paper.wf_common_days': '.0',
    'paper.chance_share_pct': '.0%', 'paper.trl_power_ratio': '.1',
    'paper.gatev_vol_pct': '.2%', 'paper.main_vol_pct': '.2%',
    'paper.iwv.n': '.0', 'paper.iwv.equity_min': ',.0', 'paper.iwv.equity_max': ',.0', 'paper.iwv.sealed': '.0',
    'paper.iwv_unmapped_first_pct': '.2%', 'paper.iwv_unmapped_last_pct': '.2%',
    'paper.boot_resamples': ',.0', 'paper.boot_block_main': '.0', 'paper.boot_block_oos': '.0',
    'paper.diff_oos': '+.2', 'paper.diff_oos_p': '.3',
    'paper.sched_best_ret': '.2%', 'paper.sched_worst_ret': '.2%',
    'paper.hl_pairs': '.0', 'paper.hl_none_oos': '.0', 'paper.trials_n': '.0',
    'paper.holdout_power.registered_days': '.0', 'paper.holdout_power.rho': '.3', 'paper.holdout_power.skew': '.2',
    'paper.holdout_power.kurtosis': '.2',
    **{f'paper.holdout_power.mde_{n}': '.2' for n in HOLDOUT_DAYS},
    **{f'paper.holdout_power.mde_05_{n}': '.2' for n in HOLDOUT_DAYS},
    **{f'paper.holdout_power.mde_normal_{n}': '.2' for n in HOLDOUT_DAYS},
    'paper.holdout.sharpe': '.2', 'paper.holdout.lo': '.2', 'paper.holdout.hi': '+.2', 'paper.holdout.p': '.3',
    # the declared variant family's data-snooping tests (results/variant_family)
    **{f'study.dev.snooping.results.{k}': v for k, v in _SNOOPING.items()},
    'study.registry.trials': '.0', 'study.registry.recorded_runs': '.0', 'study.registry.rows': '.0',
}

# The evaluated holdout ('paper.ho.', from holdout_derived): in the paper's data only once the
# holdout is complete, in place of the sealed placeholders 'paper.holdout.'; rounded half up
# on the shortest decimal form, as the site rounds the same numbers (fmt). A null prints its
# reason ('not defined' for a flat arm's Sharpe ratio); the text words such an arm by flags.
_HO_ARM = {
    'days': '.0', 'trades': ',.0', 'ret_pct': '+.2%', 'gross_ret_pct': '+.2%', 'sharpe': '+.2', 'lo': '+.2',
    'hi': '+.2', 't': '.2', 'lags': '.0', 'gross_sharpe': '+.2', 'sharpe_lo2002': '+.2', 'psr_pct': '.1%',
    'sharpe_se': '.2', 'ucb': '+.2', 'mde': '.2', 'mde_single': '.2', 'exp_avg': '.1%', 'exp_max': '.1%',
    'days_open': '.0', 'gatev_diff': '+.2', 'gatev_lo': '+.2', 'gatev_hi': '+.2', 'gatev_p': '.3',
    'gatev_sharpe': '+.2', 'gatev_days': '.0', 'rp_pct': '.1', 'rp_median': '+.2', 'rp_draws': '.0',
    'gap_first_pct': '.2%', 'gap_last_pct': '.2%', 'gap_min_pct': '.2%', 'gap_max_pct': '.2%', 'universe_n': '.0',
    **{k: 'str' for k in ('label', 'name', 'p_one_text', 'p_one_rel', 'first_long', 'last_long', 'flat_phrase',
                          'sharpe_or', 'decision')},
}
_HO_TESTED = {'p_holm_text': 'str', 'p_holm_rel': 'str'}
_HO_RUN = {
    'n_attempts': '.0', 'n_failed': '.0', 'n_unfinished': '.0', 'crash_fix_insertions': '.0',
    'crash_fix_deletions': '.0', 'logs': '.0', 'step_logs': '.0', 'environment': '.0', 'diffs': '.0',
    'fetch_symbols': ',.0', 'top_ups': '.0', 'requested': ',.0', 'first_requested': ',.0', 'first_ok': ',.0',
    'top_up_attempted': ',.0', 'top_up_ok': ',.0',
    **{k: 'str' for k in ('commit', 'registered', 'attempts_phrase', 'started', 'completed', 'until',
                          'registered_long', 'crash_fix', 'crash_fix_diff', 'crash_fix_sha', 'crash_fix_files',
                          'fetched', 'logs_phrase', 'top_ups_phrase', 'top_ups_when')},
}
HOLDOUT_METRICS = {
    **{f'paper.ho.{sid}.{k}': v for _, hyp, sid, _ in HOLDOUT_ARMS
       for k, v in {**_HO_ARM, **(_HO_TESTED if hyp else {})}.items()},
    **{f'paper.ho.run.{k}': v for k, v in _HO_RUN.items()},
    'paper.ho.days': '.0',
    **{f'paper.ho.{k}': 'str' for k in ('first_long', 'last_long', 'calendar_start_long', 'calendar_end_long')},
}


def metric_specs(data):
    """The numbers of this build: METRICS, and once the holdout is evaluated its numbers in place
    of the sealed placeholders."""
    if data['paper'].get('ho') is None:
        return METRICS
    return {**{k: v for k, v in METRICS.items() if not k.startswith('paper.holdout.')}, **HOLDOUT_METRICS}


# A null is allowed only for results that do not exist yet; its reason prints in its place.
PENDING = {
    'paper.holdout.': 'pending (sealed until the pre-registration is filed)',
    'study.dev.snooping.results.': "pending (the declared variant family's run)",
    # the robustness checks: absent until robustness.json is committed for the run
    **{f'study.dev.facts.{p}': 'pending (the robustness checks)'
       for p in ('start_', 'half1_', 'half2_', 'vix_', 'disp_', 'pers_s1', 's2c_')},
    'paper.iwv': 'pending (point-in-time universe index)',
    # optional sections of a run: absent until their study is committed
    'study.residual.': 'pending (the residual arm)',
    'study.validation.': 'pending (the committed validation run)',
    'study.dev.cost_sensitivity.': 'pending (the cost-scenario re-runs)',
}


def resolve(data, key):
    """Value at a dotted path (dict keys or list indices). KeyError if a step is absent."""
    cur = data
    for part in key.split('.'):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        elif cur is None:
            return None                # a whole optional section is absent (e.g. paper.iwv)
        else:
            raise KeyError(key)
    return cur


def pending_reason(key):
    return next((why for prefix, why in PENDING.items() if key.startswith(prefix)), None)


def format_metrics(data):
    """{key: formatted text or None}, {key: reason} for the None entries."""
    out, why = {}, {}
    ho = data['paper'].get('ho') or {}
    for key, spec in metric_specs(data).items():
        try:
            value = resolve(data, key)
        except KeyError:
            if pending_reason(key) is None:
                raise
            value = None                   # an optional section the run does not have
        holdout = key.startswith('paper.ho.')
        text = (None if value is None else str(value)) if spec == 'str' else fmt(value, spec, half_up=holdout)
        if text is None:
            reason = (ho['why'].get(key, 'not reported (the evaluation has no value for it)') if holdout
                      else pending_reason(key))
            if reason is None:
                raise PaperDataError(f'{key} is null in the inputs but is not a pending result')
            why[key] = reason
        out[key] = text
    return out, why


# ──────────────────────────────────────────────────────────────────────────────
# Claims: statements of the prose whose truth depends on the data. main.typ asserts
# each one it makes (#claim("name")); a false claim stops the compile.
# ──────────────────────────────────────────────────────────────────────────────

def _sig(t):
    return abs(t) >= 1.96


def claims(data):
    head, study, P = data, data['study'], data['paper']
    dev, facts = study['dev'], study['dev']['facts']
    forest = {r['key']: r for r in dev['forest']}
    ci_rows = [r for r in dev['forest'] if r['kind'] in ('ci', 'diff')]
    groups = {g['label']: g for k in ('by_exit', 'by_side') for g in dev['trades'][k]}
    steps = {s['key']: s['usd'] for s in dev['waterfall']}
    costs = {k: -v for k, v in steps.items() if k not in ('gross', 'net')}
    schedules = dev.get('cost_schedules') or []
    funds = head.get('fund_profiles') or {}
    sched_ret = [_get(funds, s['source_key'], 'total_return_pct', default=s['ret_pct']) for s in schedules]
    rnd = head['benchmarks']['random_control']
    sig = head['significance']
    edge = P['edge']
    res = study.get('residual') or {}
    v32 = study.get('v32') or {}
    val = study.get('validation') or {}
    scen = _get(dev, 'cost_sensitivity', 'scenarios', default={}) or {}
    cap = dev.get('capacity') or []
    hl = [p for p in _get(dev, 'half_lives', 'pairs', default=[]) if p.get('f') is not None]
    curve = dev.get('cost_curve') or []
    alts = {a['sharpe']: a for a in dev['power']['alternatives']}
    U = dev.get('universe_by_formation') or []
    trials = study.get('trials') or []
    sn = (dev.get('snooping') or {}).get('results') or {}
    return {
        # the verdict
        'main_ci_spans_zero': sig['main']['boot_lo'] < 0 < sig['main']['boot_hi'],
        'oos_ci_spans_zero': sig['oos_daily']['boot_lo'] < 0 < sig['oos_daily']['boot_hi'],
        'main_negative': head['main']['total_return_pct'] < 0 and head['main']['sharpe'] < 0,
        'oos_negative': head['oos']['pooled_sharpe'] < 0 and head['oos']['total_return_pct'] < 0,
        'every_interval_spans_zero': all(r['lo'] < 0 < r['hi'] for r in ci_rows)
                                     and (not res or res['lo'] < 0 < res['hi']),
        'not_different_from_gatev': head['benchmarks']['sharpe_diff_vs_gatev']['p'] > 0.05
                                    and all(r['p'] > 0.05 for r in dev['forest'] if r['kind'] == 'diff'),
        'gatev_below_strategy': forest['gatev']['sharpe'] < forest['main']['sharpe'],
        'gatev_ci_spans_zero': facts['gatev_lo'] < 0 < facts['gatev_hi'],
        'inside_random_spread': rnd['p5_sharpe'] < head['main']['sharpe'] < rnd['p95_sharpe']
                                and 5 < rnd['strategy_percentile'] < 95,
        'oos_windows_ci_spans_zero': sig['oos_windows']['ci_lo_pct'] < 0 < sig['oos_windows']['ci_hi_pct'],
        # gross edge against costs, on both bases the text quotes
        'gross_not_significant': not _sig(facts['gross_t']) and not _sig(edge['gross_t']),
        'gross_below_cost': facts['gross_bp'] < facts['cost_bp'] and edge['gross_bp'] < edge['cost_bp'],
        'gross_bp_negative': facts['gross_bp'] < 0 < edge['gross_bp'],
        'break_even_is_edge_over_cost': abs(edge['gross_bp'] / edge['cost_bp'] - facts['break_even_x']) < 0.01,
        'break_even_below_one': facts['break_even_x'] is not None and facts['break_even_x'] < 1,
        'gross_pnl_below_costs': 0 < facts['gross_usd_k'] < facts['cost_usd_k'],
        'gross_sharpe_not_significant': facts['gross_hac_p'] > 0.05 and forest['gross']['lo'] < 0 < forest['gross']['hi'],
        'impact_largest_cost': max(costs, key=costs.get) == 'market_impact',
        'exit_delay_costs_more_than_entry_gains': facts['sf_exit_delay_loss_usd_k'] > facts['sf_entry_delay_gain_usd_k'],
        # the trades
        'stops_offset_targets': abs(groups['Stop']['net_usd'] + groups['Target']['net_usd'])
                                < 0.05 * groups['Target']['net_usd'],
        'long_gained_short_lost': groups['Long spread']['net_usd'] > 0 > groups['Short spread']['net_usd'],
        'most_hedge_ratios_below_one': facts['hedge_below_1_pct'] > 50 and facts['hedge_mean'] < 1,
        'ex_market_gross_negative': facts['gross_ex_market_bp'] < 0 and not _sig(facts['gross_ex_market_t']),
        'win_rate_ci_spans_half': facts['win_lo_pct'] < 50 < facts['win_hi_pct'],
        # the anatomy
        'persistence_at_chance': facts['pers_lo_pct'] <= facts['pers_expected_pct'] <= facts['pers_hi_pct']
                                 and not _sig(facts['pers_z']),
        'persistence_traded_near_chance': _get(dev, 'persistence', 'chance_pct') is not None
                                          and abs(facts['pers_traded_pct'] - dev['persistence']['chance_pct']) < 2.5,
        'decay_in_sample_significant': facts['decay_form_t'] > 1.96 and facts['decay_form_tc'] > 1.96
                                       and facts['decay_form_lo'] > 0,
        'decay_oos_not_significant': facts['decay_oos_bp'] < 0 and not _sig(facts['decay_oos_t'])
                                     and facts['decay_oos_lo'] < 0 < facts['decay_oos_hi'],
        'exit_race_like_random_walk': not _sig(facts['er_rw_z']) and facts['er_rw_p'] > 0.05,
        'exit_race_rejects_selected_reversion': facts['er_ou_z'] < -1.96,
        'half_lives_lengthen': facts['hl_oos'] > facts['hl_formation'] and facts['hl_oos_above_max_pct'] > 50,
        'half_lives_within_rule_at_formation': bool(hl) and all(p['f'] <= facts['hl_max'] + 1e-9 for p in hl),
        # power, the bound and the hurdles
        'ucb_below_one': facts['sharpe_ucb'] < 1.0,
        'sharpe_1_rejected': alts[1.0]['p_ge'] < 0.05 and facts['p_sr_ge_1'] < 0.05,
        'sharpe_half_not_rejected': facts['p_sr_ge_0_5'] > 0.05,
        'sharpe_1_5_and_2_rejected': alts[1.5]['p_ge'] < 0.05 and alts[2.0]['p_ge'] < 0.05,
        'mde_above_bound': facts['sharpe_mde'] > facts['sharpe_ucb'],
        'hurdles_above_bound': all(v > facts['sharpe_ucb'] for v in
                                   (facts['hurdle_bonferroni'], facts['hurdle_hlz'], facts['hurdle_cgs'])),
        'oos_ucb_negative': facts['oos_ucb'] < 0,
        'dsr_low': sig['main']['dsr'] < 0.05 and sig['oos_daily']['dsr'] < 0.05,
        'kurtosis_fat': facts['kurtosis'] > 3,
        # the development period
        'few_flat_days': facts['flat_days'] < 0.01 * facts['days'] and v32.get('flat_days', 0) > 0.25 * facts['days'],
        'cap_close_to_binding': facts['avg_exposure_pct'] > 0.8 * 30 and facts['exposure_max_pct'] >= 30,
        'fewer_than_half_months_positive': facts['months_positive'] < 0.5 * facts['months'],
        'best_month_small': facts['best_month_pct'] < 2.0,
        'no_rolling_window_clears_zero': facts['rolling_clear_zero'] == 0,
        'start_date_changes_path': facts['wf_common_sharpe_oos'] < facts['wf_common_sharpe_main']
                                   and facts['wf_common_corr'] < 0.9,
        'last_window_not_shorter': P['wf_last_days'] >= P['wf_window_days'] - 5,
        # selection
        'excess_cointegration': head['fdr']['significant_raw_p05'] > dev['funnel']['pairs'][1]['expected'],
        'chance_about_half': 0.4 <= dev['funnel']['pairs'][1]['expected'] / head['fdr']['significant_raw_p05'] <= 0.6,
        # the initial selection at the cutoff was replaced before the first trading day
        'initial_formation_governed_no_trade': facts['formations_traded'] == facts['formations'] - 1,
        'bh_none_at_5pct': head['fdr']['survive_bh_fdr_q05'] == 0,
        'v32_tested_more_pairs': v32.get('pairs_tested', 0) > head['fdr']['pairs_tested'],
        # costs, scenarios and capacity
        'every_scenario_loses': bool(scen) and all(s['full']['ret_pct'] < 0 for s in scen.values()),
        'no_scenario_significant': bool(scen) and all(s['full']['sharpe'] < facts['sharpe_critical']
                                                      and (s['fixed']['sharpe'] is None
                                                           or s['fixed']['sharpe'] < facts['sharpe_critical'])
                                                      for s in scen.values()),
        'scenario_trades_differ': bool(scen) and dev['cost_sensitivity']['trades_min'] < dev['cost_sensitivity']['trades_max'],
        'small_book_fixed_positive_full_not': _get(scen, 'capital_10m', 'fixed', 'ret_pct', default=-1) > 0
                                              > _get(scen, 'capital_10m', 'full', 'ret_pct', default=1),
        'capacity_monotone': len(cap) > 1 and all(a['impact_bp'] < b['impact_bp'] and a['net_bp'] > b['net_bp']
                                                  for a, b in zip(cap, cap[1:])),
        'cost_curve_falls': len(curve) > 1 and all(a['sharpe'] > b['sharpe'] for a, b in zip(curve, curve[1:])),
        'sharpe_break_even_below_one': facts['sharpe_break_even_x'] < 1,
        'all_schedules_lose': bool(sched_ret) and all(r < 0 for r in sched_ret),
        'schedules_gross_negative': bool(schedules) and all(s.get('gross_pct') is not None and s['gross_pct'] < 0
                                                            for s in schedules) and facts['gross_usd_k'] > 0,
        'no_schedule_significant': all(s['sharpe'] < facts['sharpe_critical'] for s in schedules),
        'best_schedule_cheapest': bool(schedules) and (
            min(schedules, key=lambda s: s['cost_pct'])['id'] == P['sched_best_id']
            and min(schedules, key=lambda s: s['position_pct'][1])['id'] == P['sched_best_id']),
        # risk and attribution
        'st_reversal_loading': facts['st_rev_t_main'] > 1.96 and facts['st_rev_t_oos'] > 1.96,
        'momentum_against': facts['mom_t_main'] < -1.96 and facts['mom_t_oos'] < -1.96,
        'market_loading': facts['mkt_t_main'] > 1.96 and facts['beta_main_t'] > 1.96
                          and abs(facts['beta_main']) < 0.05,
        'ff_alpha_main_not_significant': facts['ff_alpha_main_pct'] < 0 and not _sig(facts['ff_alpha_main_t']),
        'ff_alpha_oos_negative': facts['ff_alpha_oos_pct'] < 0 and facts['ff_alpha_oos_t'] < -1.96,
        'factors_explain_little': facts['ff_r2_main'] < 0.25,
        # the second family
        'residual_ci_spans_zero': bool(res) and res['lo'] < 0 < res['hi'] and res['gross_lo'] < 0 < res['gross_hi'],
        'residual_gross_below_cost': bool(res) and 0 < res['gross_bp'] < res['cost_bp'] and not _sig(res['gross_t']),
        'residual_net_negative': bool(res) and res['ret_pct'] < 0 and res['sharpe'] < 0,
        # cost a trade = the stock legs' + the ETF hedge's; a trade's net bp is net of the stock legs' only
        'residual_cost_split': bool(res) and res.get('stock_cost_bp') is not None
                               and abs(res['stock_cost_bp'] + res['etf_cost_bp'] - res['cost_bp']) < 0.015
                               and abs(res['gross_bp'] - res['stock_cost_bp'] - facts['s2c_net_mean_bp']) < 0.015,
        # v32 as history
        'v32_ci_spans_zero': bool(v32) and v32['main']['lo'] < 0 < v32['main']['hi']
                             and v32['oos']['lo'] < 0 < v32['oos']['hi'],
        'v32_ranker_no_skill': bool(v32) and v32['ranker_auc'] < 0.55,
        # the universe
        'gap_shrinks': facts['gap_first_pct'] > facts['gap_last_pct'],
        # most of the missing weight is names the vendor answers with 404, at both ends
        'gap_mostly_not_found': all(facts[f'gap_{x}_not_found_pct'] is not None
                                    and facts[f'gap_{x}_not_found_pct'] > 0.5 * U[i]['missing_weight_pct']
                                    for x, i in (('first', 0), ('last', -1))) if U else False,
        'coverage_rule_above_cached': facts['coverage_pct'] > facts['cached_pct'] + facts['not_found_pct'] - 0.2,
        'walk_forward_bound_below_zero_ci_spans': facts['oos_ucb'] < 0 < sig['oos_daily']['boot_hi'],
        'cap_exceeded_marked_to_market': facts['exposure_days_above_cap'] > 0 and facts['exposure_max_pct'] < 31,
        'gap_first_is_first_formation': bool(U) and abs(U[0]['missing_weight_pct'] + U[0]['unmapped_weight_pct']
                                                        - facts['gap_first_pct']) < 0.01,
        'iwv_gap_shrinks': P['iwv'] is not None and P['iwv_unmapped_first_pct'] > P['iwv_unmapped_last_pct'],
        # the validation
        'validation_passes': bool(val) and val['all_pass'] and val['edge']['t'] > 1.96
                             and not _sig(val['forced_null']['t']) and val['selection']['worst_fp_rate'] <= 0.05,
        # the record
        'exploratory_run_on_record': len(trials) > 1 and (trials[1].get('oos_sharpe') or 0) > 0
                                     and trials[1].get('dirty') is True,
        'holdout_sealed': (study.get('holdout') or {}).get('status') == 'sealed',
        # the declared variant family (a claim is false while its results are absent)
        'family_beats_neither_cash_nor_gatev': bool(sn) and all(
            sn[k]['p'] > 0.05 and sn[k]['rc_p'] > 0.05 for k in ('spa_zero', 'spa_gatev', 'spa_gatev_unit_vol'))
            and sn['rw_rejected'] == 0,
        'family_mcs_keeps_all': bool(sn) and sn['mcs_included'] == sn['n'],
        'family_overfits': bool(sn) and sn['pbo_pct'] > 50 and sn['pbo_is_best_loss_pct'] > 50
                           and sn['pbo_is_best_oos_sharpe'] < 0,
        # selection makes it worse than a variant picked without looking, on the same splits
        'family_selection_worse_than_base': bool(sn) and sn.get('pbo_base_loss_pct') is not None
                                            and sn['pbo_is_best_loss_pct'] > sn['pbo_base_loss_pct'] > 50
                                            and sn['pbo_is_best_oos_sharpe'] < sn['pbo_median_oos_sharpe'] < 0,
        # no variant is significant even before the search is allowed for (one-sided 5%)
        # (the snooping table names one best variant for both comparisons with the Gatev series)
        'family_best_not_significant_alone': bool(sn) and all(
            sn[k]['best_t'] < 1.645 for k in ('spa_zero', 'spa_gatev', 'spa_gatev_unit_vol'))
            and sn['spa_gatev']['best'] == sn['spa_gatev_unit_vol']['best'],
        'family_best_dsr_not_significant': bool(sn) and (sn.get('dsr_best') or {}).get('dsr_pct') is not None
                                           and sn['dsr_best']['dsr_pct'] < 50
                                           # the same variant: its Sharpe ratio as the family's 4-decimal file has it
                                           and abs(sn['dsr_best']['sharpe'] - sn['sharpe_best']) <= 5e-5,
        'family_few_positive': bool(sn) and sn['positive'] < 0.5 * sn['n'] and sn['sharpe_median'] < 0,
        'family_dsr_not_significant': bool(sn) and (sn.get('dsr') or {}).get('dsr_pct') is not None
                                      and sn['dsr']['dsr_pct'] < 50,
        'design_not_the_best_variant': bool(sn) and sn['base_rank'] is not None and sn['base_rank'] > 1,
        # the robustness checks
        # unmatched (each start over its own, shorter window) the published start ranks first ...
        'headline_start_first_unmatched': facts.get('start_headline_rank') == 1
                                          and facts['start_sharpe_median'] < facts['start_sharpe_max'],
        # ... and like for like the published path beats most later starts on their own windows,
        # but is not the best on the days all twelve share
        'headline_path_beats_most_later_starts': facts.get('start_matched_wins') is not None
                                                 and 2 * facts['start_matched_wins'] > facts['start_matched_of']
                                                 and facts['start_matched_gap_median'] > 0,
        'headline_not_first_on_shared_days': facts.get('start_common_rank') is not None
                                             and facts['start_common_rank'] > 1
                                             and facts['start_common_sharpe_median'] < 0,
        'start_dates_all_negative': facts.get('start_sharpe_max') is not None and facts['start_sharpe_max'] < 0,
        'start_reproduces_published_run': bool(_get(dev, 'robustness', 'start_dates', 'reproduces')),
        'regimes_not_significant': facts.get('vix_diff_t') is not None and not _sig(facts['vix_diff_t'])
                                   and not _sig(facts['disp_diff_t']),
        'persistence_s1_at_base_rate': facts.get('pers_s1_z') is not None and not _sig(facts['pers_s1_z'])
                                       and facts['pers_s1_lo_pct'] <= facts['pers_s1_expected_pct'] <= facts['pers_s1_hi_pct']
                                       and not _sig(facts['pers_s1u_z']),
        's2_clustered_not_significant': facts.get('s2c_gross_month_t') is not None
                                        and not _sig(facts['s2c_gross_month_t'])
                                        and abs(facts['s2c_gross_month_t']) < abs(res.get('gross_t') or 0),
        # the evaluated holdout (only once it is complete)
        **(holdout_claims(study['holdout']) if P.get('ho') else {}),
    }


def holdout_claims(H):
    """What the text says of the evaluated holdout, each read from the evaluation's decision
    and checked against the arm it concerns: the text words the result by flags (flags()) and
    asserts it here, so a sentence and the decision cannot part."""
    arms = {a['key']: a for a in H['arms']}
    D, R = H['decision'], H['provenance']
    out = {}
    for key, hyp, sid, _ in HOLDOUT_ARMS:
        a = arms[key]
        if hyp:
            d = D['arms'][key]
            out[f'ho_{hyp.lower()}_edge'] = (d['edge'] is True and a['edge'] is True and a['p_holm_below_alpha'] is True
                                             and key in D['rejected'] and a['t'] > 0 and a['sharpe'] > 0)
            out[f'ho_{hyp.lower()}_no_edge'] = (d['edge'] is False and a['edge'] is False
                                                and a['p_holm_below_alpha'] is False and key not in D['rejected'])
        else:
            out[f'ho_{sid}_not_tested'] = (a['role'] == 'descriptive' and a['p_holm'] is None and a['edge'] is None
                                           and key not in D['family'])
        out[f'ho_{sid}_flat'] = a['flat'] is True and a['sharpe'] is None and a['lags'] == 0
        out[f'ho_{sid}_ci_excludes_zero'] = not a['flat'] and a['lo'] is not None and a['lo'] > 0
        out[f'ho_{sid}_ci_includes_zero'] = (not a['flat'] and a['lo'] is not None and a['hi'] is not None
                                            and a['lo'] <= 0 <= a['hi'])
    attempts = R['attempts']
    published = {d['file'].rsplit('/', 1)[-1] for d in R.get('crash_fix_diffs') or []}
    out.update({
        'ho_none_rejected': D['rejected'] == [],
        'ho_runs_one_commit': set(R['run_commits'].values()) == {R['commit']}
                              and all(a['commit'] == R['commit'] for a in H['arms']),
        'ho_runs_at_registered_commit': R['at_registered_commit'] is True and R['commit'] == R['registered_commit']
                                        and R.get('crash_fix') is None,
        'ho_single_attempt': R['n_attempts'] == 1 and R['n_failed'] == 0 and attempts[0]['failed'] is None,
        'ho_crash_fix_published': bool(R.get('crash_fix')) and R['crash_fix']['diff'] in published
                                  and not R['at_registered_commit'],
        'ho_not_at_registered_commit_no_fix': R['commit'] != R['registered_commit'] and R.get('crash_fix') is None,
        # every attempt ran at the registered commit, or (an earlier one at another) only the last
        'ho_all_attempts_at_registered_commit': all(x['at_registered_commit'] is True
                                                    and x['head'] == R['registered_commit'] for x in attempts),
        'ho_last_attempt_at_registered_commit': attempts[-1]['head'] == R['registered_commit']
                                                and not all(x['at_registered_commit'] for x in attempts),
        # the counts the text words the attempts by: an earlier attempt failed or stopped without
        # recording a failure, and the last registered the trial (completed, or not on record)
        'ho_attempts_on_record': (R['n_attempts'] == len(attempts) == attempts[-1]['attempt']
                                  and R['n_failed'] == sum(1 for x in attempts if x['failed'])
                                  and R['n_unfinished'] == sum(1 for x in attempts[:-1] if not x['failed'])
                                  and R['n_failed'] + R['n_unfinished'] == len(attempts) - 1
                                  and not attempts[-1]['failed']),
        'ho_no_completion_line': not R['completed_utc'] and bool(_get(R, 'registry', 'registered_utc'))
                                 and R['attempt_record_lines'] == R['registry']['attempt_lines'],
        'ho_clean': R['clean'] is True,
        'ho_period_matches': H['period_matches_calendar'] is True,
    })
    return out


def flags(data):
    """Which optional results exist: main.typ words its notes by these (no assertion)."""
    study = data['study']
    dev = study['dev']
    return {'random_band': dev.get('random_band') is not None,
            'wf_daily': bool(dev['walk_forward'].get('daily')),
            'cost_split': dev.get('cost_curve') is not None,
            'snooping': (dev.get('snooping') or {}).get('results') is not None,
            'residual': study.get('residual') is not None,
            'validation': study.get('validation') is not None,
            'holdout_complete': (study.get('holdout') or {}).get('status') == 'complete',
            'universe_pit': dev.get('universe_by_formation') is not None,
            'multi_factor': bool(dev['factors'].get('multi_factor')),
            'scenarios': bool(_get(dev, 'cost_sensitivity', 'available')),
            'iwv': data['paper']['iwv'] is not None,
            'preregistered': data['paper']['prereg_status'] == 'filed',
            **(holdout_flags(study['holdout'], data['paper']['ho']) if data['paper'].get('ho') else {})}


def holdout_flags(H, ho):
    """Which wording the evaluated holdout takes (main.typ asserts it with holdout_claims)."""
    D, R = H['decision'], H['provenance']
    arms = {a['key']: a for a in H['arms']}
    out = {'ho_h1_edge': D['arms']['v33_pairs']['edge'], 'ho_h2_edge': D['arms']['avellaneda_lee']['edge'],
           'ho_any_edge': bool(D['rejected']), 'ho_both_edge': len(D['rejected']) == len(D['family']),
           'ho_daily': bool(H.get('daily')) and any(v for v in (H['daily'].get('cum') or {}).values()),
           'ho_period_matches': H['period_matches_calendar'],
           'ho_at_registered_commit': R['at_registered_commit'], 'ho_crash_fix': R.get('crash_fix') is not None,
           'ho_single_attempt': R['n_attempts'] == 1 and R['n_failed'] == 0, 'ho_failed': R['n_failed'] > 0,
           'ho_unfinished': R['n_unfinished'] > 0, 'ho_completed': bool(R['completed_utc']),
           'ho_all_attempts_at_registered_commit': all(x['at_registered_commit'] for x in R['attempts']),
           'ho_clean': R['clean'] is True, 'ho_price_fetch': R.get('price_fetch') is not None,
           'ho_fetch_topped': bool((R.get('price_fetch') or {}).get('top_ups')),
           'ho_unnamed_diffs': any(not d.get('attempts') for d in R.get('crash_fix_diffs') or [])}
    for key, _, sid, _ in HOLDOUT_ARMS:
        a = arms[key]
        out[f'ho_{sid}_flat'] = a['flat']
        out[f'ho_{sid}_ci_excludes_zero'] = not a['flat'] and a['lo'] is not None and a['lo'] > 0
        out[f'ho_{sid}_universe'] = ho[sid]['universe_n'] > 0
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Tables: rows of formatted cells (the same formatter as the text)
# ──────────────────────────────────────────────────────────────────────────────

SCENARIO_LABELS = {'headline': 'Headline: Y = 0.3, borrow {borrow}, $100M', 'impact_0_6': 'Impact Y = 0.6',
                   'impact_1_0': 'Impact Y = 1.0', 'borrow_1': 'Borrow 1% a year', 'borrow_3': 'Borrow 3% a year',
                   'capital_10m': 'Book of $10M', 'capital_1b': 'Book of $1B', 'capital_5b': 'Book of $5B'}


def tables(data, m):
    study, dev = data['study'], data['study']['dev']
    P = data['paper']

    def cell(key):
        return m[key] if m[key] is not None else 'pending'

    def ci(lo, hi):
        return f'[{cell(lo)}, {cell(hi)}]'

    significance = [
        ['Annualised Sharpe ratio, net', cell('significance.main.ann_sharpe'), cell('significance.oos_daily.ann_sharpe')],
        ['Newey–West t (mean ≠ 0)', cell('significance.main.hac_t'), cell('significance.oos_daily.hac_t')],
        ['Newey–West p', cell('significance.main.hac_p'), cell('significance.oos_daily.hac_p')],
        ['Probabilistic Sharpe ratio (one minus the one-sided p of SR ≤ 0)', cell('significance.main.psr_pct'),
         cell('significance.oos_daily.psr_pct')],
        [f"Deflated Sharpe ({m['study.dev.facts.dsr_trials']} trials)", cell('significance.main.dsr_pct'),
         cell('significance.oos_daily.dsr_pct')],
        ['Block-bootstrap 95% interval', ci('significance.main.boot_lo', 'significance.main.boot_hi'),
         ci('significance.oos_daily.boot_lo', 'significance.oos_daily.boot_hi')],
        ['Sharpe ratio before costs (Newey–West p)',
         f"{cell('study.dev.facts.gross_sharpe')} ({cell('study.dev.facts.gross_hac_p')})",
         f"{cell('study.dev.facts.wf_gross_sharpe')} ({cell('study.dev.facts.wf_gross_hac_p')})"],
        ['Minimum detectable Sharpe (80% power, one-sided 5%)', cell('study.dev.facts.sharpe_mde'),
         cell('study.dev.facts.oos_mde')],
        ['One-sided 95% upper bound', cell('study.dev.facts.sharpe_ucb'), cell('study.dev.facts.oos_ucb')],
        ['Gatev distance method, Sharpe [95% interval]',
         f"{cell('benchmarks.gatev.sharpe')} {ci('study.dev.facts.gatev_lo', 'study.dev.facts.gatev_hi')}",
         f"{cell('paper.gatev_wf_sharpe')} (on {cell('paper.wf_common_days')} shared days)"
         if m['paper.gatev_wf_sharpe'] is not None else '—'],
        ['Strategy minus Gatev, Sharpe (Ledoit–Wolf p)',
         f"{cell('benchmarks.sharpe_diff_vs_gatev.diff')} ({cell('benchmarks.sharpe_diff_vs_gatev.p')})",
         f"{cell('paper.diff_oos')} ({cell('paper.diff_oos_p')})" if m['paper.diff_oos'] is not None else '—'],
    ]
    forest = [[r['label'], fmt(r['sharpe'], '+.2'), fmt(r['lo'], '.2'), fmt(r['hi'], '+.2'),
               fmt(r['days'], ',.0') if r['days'] else '—', r['method']] for r in dev['forest']]
    def pval(x):
        return '< 0.001' if x < 0.0005 else fmt(x, '.3')
    alternatives = [[fmt(a['sharpe'], '.1'), pval(a['p_ge']), fmt(a['min_trl_years'], '.1')]
                    for a in dev['power']['alternatives']]
    hz = dev['power'].get('hurdles') or {}
    hurdles = [['One test, one-sided 5%', fmt(_Z95, '.2'), fmt(hz.get('single_test'), '.2')],
               [f"Bonferroni over {m['study.dev.facts.hurdle_tests']} trials, one-sided", '—',
                fmt(hz.get('bonferroni_one_sided'), '.2')],
               ['Harvey, Liu and Zhu (2016), field-wide', m['study.dev.facts.hurdle_hlz_t'], fmt(hz.get('hlz'), '.2')],
               ['Chordia, Goyal and Saretto (2020), field-wide', m['study.dev.facts.hurdle_cgs_t'], fmt(hz.get('cgs'), '.2')]]
    perf = P['performance']

    def interval(v, signed=True):
        spec = '+.2' if signed else '.2'
        if v[1] is None:
            return fmt(v[0], spec) or '—'
        return f"{fmt(v[0], spec)} [{fmt(v[1], spec)}, {fmt(v[2], spec)}]"

    def opt(v, spec):
        return fmt(v, spec) if v is not None else '—'

    def dd_days(v):
        return '—' if v[0] is None else f"{v[0]} / {v[1] if v[1] is not None else 'not regained'}"
    cols = ('main', 'wf', 'gatev')
    performance_rows = [
        ['Trading days', *(fmt(perf['days'][c], '.0') for c in cols)],
        ['Total net return, %', *(fmt(perf[c]['total'], '+.2') for c in cols)],
        ['Annualised net return, % (95% interval)', *(interval(perf[c]['ret']) for c in cols)],
        ['Annualised volatility, % (95% interval)', *(interval(perf[c]['vol'], signed=False) for c in cols)],
        ['Sharpe ratio (95% interval)', interval(perf['sharpe']['main']), interval(perf['sharpe']['wf']),
         f"{cell('benchmarks.gatev.sharpe')} [{cell('study.dev.facts.gatev_lo')}, {cell('study.dev.facts.gatev_hi')}]"],
        ['Maximum drawdown, %', *(fmt(perf[c]['max_dd'], '.2') for c in cols)],
        ['Drawdown length, trading days: to trough / to recovery', *(dd_days(perf[c]['dd_days']) for c in cols)],
        ['Average gross exposure, % of capital', *(opt(perf[c]['gross'], '.1') for c in cols)],
        ['Net return on average gross exposure, % a year', *(opt(perf[c]['ret_gross'], '+.2') for c in cols)],
        ['Trades', *(opt(perf[c]['trades'], '.0') for c in cols)],
        ['Hit rate, % of trades', *(opt(perf[c]['hit'], '.1') for c in cols)],
        ['Average holding period, trading days', *(opt(perf[c]['hold'], '.1') for c in cols)],
        ['Annual turnover, × capital', *(opt(perf[c]['turnover'], '.1') for c in cols)],
    ]
    funds = data.get('fund_profiles') or {}

    def fund(s, key):          # the headline JSON's figure (as the site prints it), else the replay's
        return _get(funds, s['source_key'], key, default=s[{'total_return_pct': 'ret_pct', 'sharpe': 'sharpe',
                                                              'max_drawdown_pct': 'max_dd_pct'}[key]])
    schedules = [[s['id'], fmt(s['commission_bps'], '.1'), fmt(s['half_spread_bps'], '.1'),
                  fmt(s['impact_cap_bps'], '.0'), fmt(s['borrow_pct'], '.2'), fmt(s['financing_pct'], '.2'),
                  f"{fmt(s['position_pct'][0], '.0')}–{fmt(s['position_pct'][1], '.0')}",
                  opt(s.get('gross_pct'), '+.2'), fmt(s['cost_pct'], '.2'),
                  fmt(fund(s, 'total_return_pct'), '.2'), fmt(fund(s, 'sharpe'), '.2'),
                  fmt(fund(s, 'max_drawdown_pct'), '.2'), fmt(s['peak_gross_x'], '.2'),
                  fmt(s['trades'], '.0')]
                 for s in dev.get('cost_schedules') or []]
    cs = dev.get('cost_sensitivity') or {}
    scenarios = []
    for k in cs.get('order') or []:
        s = cs['scenarios'][k]
        full, fixed = s['full'], s['fixed']
        scenarios.append([SCENARIO_LABELS.get(k, s['label']).format(borrow=m['paper.borrow_pct']),
                          fmt(full['trades'], '.0'), fmt(full['ret_pct'], '.2'), fmt(full['sharpe'], '.2'),
                          fmt(full['max_dd_pct'], '.2'), fmt(full['cost_bp'], '.1'), fmt(full['adv_pct'], '.2'),
                          opt(fixed.get('ret_pct'), '.2'), opt(fixed.get('sharpe'), '.2')])
    declaration = data['_declaration'] or {}
    grid = {k: v for k, v in (declaration.get('grid') or {}).items() if isinstance(v, list)}
    variants = [[k, 'grid values ' + ', '.join(fmt(x, '.2') for x in v)] for k, v in grid.items()]
    variants += [[tg['name'], tg.get('why', '').replace('>=', '≥').replace('t+1', 't + 1')]
                 for tg in declaration.get('toggles') or []]
    # Windows are numbered 1..N here (the run numbers them on a grid that starts in 2020);
    # the last one runs to the walk-forward's last day.
    wins = dev['walk_forward']['windows']
    windows = [[str(i), short_date(w['test_start']),
                short_date(dev['run']['oos_period'][1] if i == len(wins) else w['test_end']), str(P['wf_days'][w['n']]),
                fmt(w['ret_pct'], '+.2'), fmt(w['sharpe'], '+.2') if w['sharpe'] is not None and not _flat_window(w) else '—',
                str(w['trades']), fmt(w.get('win_rate_pct'), '.1') or '—', fmt(w.get('max_dd_pct'), '.2') or '—']
               for i, w in enumerate(wins, 1)]
    holdout_power_rows = [[str(r['days']), fmt(r['mde_shape'], '.2'), fmt(r['mde_shape_05'], '.2'),
                           fmt(r['mde_normal'], '.2')] for r in P['holdout_power_rows']]
    design = 'the design of this note' if P['prereg_status'] != 'filed' else 'the design of this note, pre-registered'
    hypotheses = [['H1 · S1', f'{P["design"]} pairs, {design}', 'mean daily net return > 0'],
                  ['H2 · S2', 'Avellaneda–Lee residual reversion', 'mean daily net return > 0'],
                  ['S3', 'v32 as published, frozen', 'reported, not tested']]
    def sn(key):
        return cell(f'study.dev.snooping.results.{key}')
    snooping = [
        ['Hansen SPA against cash, consistent p (lower, upper)',
         f"{sn('spa_zero.p')} ({sn('spa_zero.p_lower')}, {sn('spa_zero.p_upper')})"],
        ['White Reality Check against cash, p', sn('spa_zero.rc_p')],
        ['Best variant against cash: studentized mean', f"t = {sn('spa_zero.best_t')} ({sn('spa_zero.best_label')})"],
        ['Hansen SPA against the Gatev distance method, every series at unit volatility (a Sharpe scale), '
         'p (Reality Check)', f"{sn('spa_gatev_unit_vol.p')} ({sn('spa_gatev_unit_vol.rc_p')})"],
        ['The same on daily returns, whose capital bases differ (not like for like), p (Reality Check)',
         f"{sn('spa_gatev.p')} ({sn('spa_gatev.rc_p')})"],
        [f"Best variant against the Gatev method ({sn('spa_gatev.best_label')}): studentized mean, unit "
         'volatility; daily returns', f"t = {sn('spa_gatev_unit_vol.best_t')}; {sn('spa_gatev.best_t')}"],
        ['Romano–Wolf stepdown against cash: variants rejected at 5% (smallest adjusted p)',
         f"{sn('rw_rejected')} ({sn('rw_min_p')})"],
        ['Model confidence set, 90%: variants kept (smallest p)', f"{sn('mcs_included')} of {sn('n')} ({sn('mcs_min_p')})"],
        ['Effective number of independent trials (entropy effective rank)', sn('effective_rank')],
        [f"Deflated Sharpe ratio of the family's best variant ({sn('dsr_best.sharpe')}), N = "
         f"{sn('dsr.n_trials')}, the variants' Sharpe dispersion", sn('dsr_best.dsr_pct')],
        [f"The same for the {P['design']} design ({sn('base_sharpe')}), which was not selected from the family",
         sn('dsr.dsr_pct')],
        [f"Probability of backtest overfitting ({sn('pbo_splits')} splits; 50% for a ranking without information)",
         sn('pbo_pct')],
        ['Best variant of one half of the days, on the other half: mean Sharpe; splits with a loss',
         f"{sn('pbo_is_best_oos_sharpe')}; {sn('pbo_is_best_loss_pct')}"],
        ['Every variant on the same splits: mean Sharpe of the median variant; variant–splits with a loss',
         f"{sn('pbo_median_oos_sharpe')}; {sn('pbo_base_loss_pct')}"],
        ['Variants with a positive Sharpe ratio (best, median, worst)',
         f"{sn('positive')} of {sn('n')} ({sn('sharpe_best')}, {sn('sharpe_median')}, {sn('sharpe_worst')})"],
        [f"The {P['design']} design: rank by Sharpe ratio (Sharpe)", f"{sn('base_rank')} ({sn('base_sharpe')})"],
    ]
    rob = dev.get('robustness') or {}
    startdates = [[short_date(r['start']) + (' (published)' if r['offset'] == 0 else ''), fmt(r['trades'], '.0'),
                   fmt(r['sharpe'], '.2'), '—' if r['offset'] == 0 else fmt(r['published_sharpe'], '+.2'),
                   fmt(r['ret_pct'], '.2'), fmt(r['common_sharpe'], '+.2')]
                  for r in _get(rob, 'start_dates', 'runs', default=[]) if r.get('sharpe') is not None]
    halves = [[f"{'First' if h['half'] == 'first' else 'Second'} half: entries {short_date(h['entry'][0])} to "
               f"{short_date(h['entry'][1])}", fmt(h['trades'], '.0'), fmt(h['sharpe'], '+.2'),
               fmt(h['inside_sharpe'], '+.2'), fmt(h['ret_pct'], '+.2'), '—']
              for h in rob.get('halves') or [] if h.get('sharpe') is not None]
    tercile = {'low': 'low', 'mid': 'middle', 'high': 'high'}
    regimes = []
    for key, title in (('vix', 'Previous-day VIX'), ('dispersion', 'Previous-day sector dispersion'),
                       ('year', 'Calendar year')):
        blk = _get(rob, 'regimes', key, 'net') or {}
        for b in [b for b in blk.get('rows') or [] if b.get('mean_bp') is not None]:
            label = (f"{title}, {tercile[b['bucket']]} tercile" if key != 'year'
                     else f"{title} {b['bucket']}" + (' (from July)' if b['bucket'] == '2023' else ''))
            regimes.append([label, fmt(b['days'], '.0'), fmt(b['mean_bp'], '+.2'), fmt(b['sharpe'], '+.2'),
                            fmt(b['t'], '+.2')])
        d = blk.get('diff') or {}
        if d.get('mean_bp') is not None:
            label = f"{title}, high minus low" if key != 'year' else f"{d['of'][0]} minus {d['of'][1]}"
            regimes.append([label, '—', fmt(d['mean_bp'], '+.2'), '—', fmt(d['t'], '+.2')])
    pers_s1 = []
    first = _get(rob, 'persistence', 'first') or {}
    for y in [y for y in first.get('years') or [] if y.get('coint') is not None]:
        pers_s1.append([f"{y['year']} → {y['next_year']}", f"{fmt(y['coint'], ',.0')} of {fmt(y['correlated'], ',.0')}",
                        f"{y['still']} of {y['still_of']} ({fmt(y['still_pct'], '.1')})", fmt(y['base_pct'], '.1'),
                        fmt(y['p_vs_base'], '.2')])
    for tag, which in (('Pooled', 'first'), ('Pooled, all formations', 'union')):
        pl = _get(rob, 'persistence', which, 'pooled') or {}
        if pl.get('count') is not None:
            pers_s1.append([tag, '', f"{pl['count']} of {fmt(pl['of'], ',.0')} ({fmt(pl['pct'], '.1')}; "
                                     f"{fmt(pl['lo_pct'], '.1')}–{fmt(pl['hi_pct'], '.1')})",
                            fmt(pl['expected_pct'], '.1'), f"z = {fmt(pl['z'], '.2')}"])
    val = study.get('validation')
    if val:
        e, n, h, s = val['edge'], val['forced_null'], val['hedge_ratio'], val['selection']
        results = [f"{fmt(e['trades'], ',.0')} trades, {fmt(e['mean_bp'], '+.1')} bp gross per trade "
                   f"(t = {fmt(e['t'], '.1')}), median net Sharpe {fmt(e['median_net_sharpe'], '.2')}",
                   f"{fmt(n['trades'], ',.0')} trades, {fmt(n['mean_bp'], '+.1')} bp gross per trade (t = {fmt(n['t'], '.2')})",
                   f"median absolute error {fmt(h['median_abs_error'], '.3')} (90th percentile {fmt(h['p90_abs_error'], '.3')})",
                   f"{fmt(100 * s['recall'], '.0%')} of planted pairs found; "
                   f"{fmt(s['unrelated_per_planted_market'], '.1')} unrelated pairs admitted per market with planted "
                   f"pairs, {fmt(s['per_null_market'], '.1')} per market with none; the worst market admitted "
                   f"{fmt(100 * s['worst_fp_rate'], '.2%')} of its unrelated pairs"]
    else:
        results = ['pending'] * 4
    validation = [['Planted cointegrated pairs (OU spreads, half-life 5–14 days)', 'a large positive gross edge', results[0]],
                  ['Correlated, not cointegrated pairs (random-walk spread), forced into the universe',
                   'no edge; a positive mean would be look-ahead', results[1]],
                  ['Kalman hedge ratio against the true slope', 'recover it', results[2]],
                  ['Pair selection with planted pairs among unrelated names',
                   'find them; admit at most 5% of unrelated pairs', results[3]]]
    run = dev['run']
    v = run['versions'] or {}
    manifest = [['Commit', f"{run['commit'][:12]} ({P['clean']})"],
                ['Run', f"{P['run_time']}; results in {P['run_dir']}/"],
                ['Design', f"profile {P['design']} {P['profile_hash']}, calendar dev {P['calendar_hash']}"],
                ['Price cache', f"sha256 {run['price_cache_sha256']}"],
                ['Headline JSON', f"{data['_headline_path']}, sha256 {study['meta']['headline_sha256']}"],
                ['Site data', f"assets/study.json, sha256 {data['_study_sha256']}"],
                ['Universe', f"IWV N-PORT snapshots (reference/universe/); price history for "
                             f"{m['paper.names_prices']} symbols ({m['study.dev.facts.cached_pct']} of those requested); "
                             f"{m['study.dev.facts.not_found_pct']} no longer served (HTTP 404); fetch-coverage rule "
                             f"met at {m['study.dev.facts.coverage_pct']}"],
                ['Fetch manifest', f"{P['run_dir']}/price_fetch_manifest.json"],
                ['Seed', f"PAIRS_SEED={run['seed']}, PYTHONHASHSEED=0"],
                ['Stack', ' · '.join(f'{k} {v[k]}' for k in ('python', 'numpy', 'pandas', 'scipy', 'statsmodels')
                                     if v.get(k))]]
    sources = [[path, digest] for path, digest in sorted(study['meta']['sources'].items())]
    for path, digest in ((data['_v32_universe_path'], data['_v32_universe_sha256']),
                         ('reference/universe/index.json', data['_universe_index_sha256']),
                         ('index.html', data['_site_sha256'])):
        if digest:
            sources.append([path, digest])
    v32 = study.get('v32') or {}
    pv32, pv33 = PROFILES['v32'], PROFILES[P['design']]
    design_rows = [
        ['Universe', f"The {m['paper.v32_universe_selected']} largest US common stocks by market cap as downloaded on "
                     f"{P['v32_universe_as_of_long']} (the close of 16 October at the latest), back-filled to "
                     f"{P['data_first_year']}",
         'Russell 3000 members as held by the iShares Russell 3000 ETF in its SEC N-PORT filings, the snapshot '
         'in force at each formation',
         "Today's largest names are survivors chosen with hindsight; point-in-time membership removes that "
         'look-ahead and makes the survivorship gap a measured quantity'],
        ['Names searched', f'{pv32.max_universe} most liquid', f'{pv33.max_universe} most liquid',
         'A size at which both strategy families trade the same liquid names'],
        ['Candidate pairs', 'Any two names', 'Two names in the same Fama–French 49 industry',
         f"An economic link is the premise of convergence (Do and Faff 2010); fewer tests raise the power of the "
         f"multiple-testing correction ({m['fdr.pairs_tested']} against {m['study.v32.pairs_tested']})"],
        ['Re-formation', f'The {P["formation_year"]} pool re-tested every {pv32.reselect_every} trading days; '
                         'pairs can drop out, none can enter',
         f'The whole selection re-run every {pv33.reselect_every} trading days on the trailing '
         f'{word(pv33.formation_calendar_days // 365)} years',
         "A pool that can only shrink goes stale, and the 126-calendar-day (about 87-session) check inside v32's re-test "
         "had too little power to tell broken "
         "pairs from healthy ones; re-forming on a schedule is Gatev's formation-and-trading cycle"],
        ['Regime gate', 'VIX and sector-dispersion scaling, with a hard stop on new entries',
         'Off (a declared variant)',
         f"Its thresholds were fitted on windows now inside the test period; in the v32 run it blocked new entries "
         f"on {m['study.v32.gate_blocked_days']} of {m['study.v32.days']} days"],
        ['Ranking', 'A learned classifier orders same-day candidates',
         'Signal strength × pair quality (the learned ranker is a declared variant)',
         f"v32's ranker showed no skill on the trades after its training window (AUC {m['study.v32.ranker_auc']}; "
         "0.5 is none)"],
        ['Borrow and financing', f"{fmt(1e4 * pv32.borrow_rate, '.0')} bp general-collateral borrow plus a "
                                 f"{fmt(1e4 * pv32.pb_financing_spread, '.0')} bp prime-broker spread on the short "
                                 'half of gross',
         f"One {fmt(100 * pv33.borrow_rate, '.2')}% fee a year on the short notional",
         'The two charges double-count the cost of shorting; the fee is a median buy-side indicative fee '
         '(the execution-cost note gives its source)'],
    ]
    compare = []
    if v32:
        compare = [
            ['Main backtest, net Sharpe [95% interval]',
             f"{m['study.v32.main.sharpe']} [{m['study.v32.main.lo']}, {m['study.v32.main.hi']}]",
             f"{m['main.sharpe']} [{m['significance.main.boot_lo']}, {m['significance.main.boot_hi']}]"],
            ['Main backtest, net return', m['study.v32.main.ret_pct'], m['main.total_return_pct']],
            ['Main backtest, maximum drawdown', m['study.v32.main.max_dd_pct'], m['main.max_drawdown_pct']],
            ['Walk-forward, net Sharpe [95% interval]',
             f"{m['study.v32.oos.sharpe']} [{m['study.v32.oos.lo']}, {m['study.v32.oos.hi']}]",
             f"{m['oos.pooled_sharpe']} [{m['significance.oos_daily.boot_lo']}, {m['significance.oos_daily.boot_hi']}]"],
            ['Walk-forward windows positive', f"{m['study.v32.oos.windows_positive']} of {m['study.v32.oos.windows']}",
             f"{m['oos.windows_positive']} of {m['oos.windows']}"],
            ['Trades', m['study.v32.main.trades'], m['main.trades']],
            ['Gross bp per trade, equal-weighted (t)', f"{m['study.v32.gross_bp']} ({m['study.v32.gross_t']})",
             f"{m['study.dev.facts.gross_bp']} ({m['study.dev.facts.gross_t']})"],
            ['Cost bp per trade, equal-weighted', m['study.v32.cost_bp'], m['study.dev.facts.cost_bp']],
            ['Average gross exposure, % of capital', m['study.v32.main.avg_exposure_pct'].rstrip('%'),
             m['main.avg_gross_exposure_pct'].rstrip('%')],
            ['Days with no position', m['study.v32.flat_days'], m['study.dev.facts.flat_days']],
            ['Pairs tested at the first formation', m['study.v32.pairs_tested'], m['fdr.pairs_tested']],
            ['Gatev distance method, Sharpe', m['study.v32.gatev_sharpe'], m['benchmarks.gatev.sharpe']],
            ['Percentile among random-pair portfolios', m['study.v32.random_percentile'],
             m['benchmarks.random_control.strategy_percentile']],
        ]
    trials = []
    family = (dev.get('snooping') or {}).get('results')
    for t in study.get('trials') or []:
        if t.get('sharpe') is None and t['name'] == 'residual_dev' and study.get('residual'):
            r = study['residual']
            row = [t['name'], 'Avellaneda–Lee · dev', (r.get('commit') or '')[:7], fmt(r['sharpe'], '.2'),
                   fmt(r['ret_pct'], '.2'), fmt(r['trades'], ',.0'), '—']
        elif t.get('sharpe') is None and t['name'] == 'variant_family' and family:
            row = [t['name'], f"{family['n']} {P['design']} variants · dev", '—',
                   f"{fmt(family['sharpe_worst'], '.2')} to {fmt(family['sharpe_best'], '+.2')}",
                   f"{fmt(family['ret_worst_pct'], '.2')} to {fmt(family['ret_best_pct'], '+.2')}",
                   f"{family['trades_min']}–{family['trades_max']}", '—']
        elif t.get('sharpe') is None and t.get('profile') is None and t['name'] == 'residual_earlier_rules':
            row = [t['name'], 'Avellaneda–Lee, superseded rules · dev, 2025', '—', '—', '—', '—', '—']
        else:
            design_cal = f"{t.get('profile') or 'v32'} · {t.get('calendar') or 'dev'}".replace(
                'rehearsal2025', '2025').replace('holdout2026', '2026').replace('avellaneda_lee', 'Avellaneda–Lee')
            row = [t['name'], design_cal, (t.get('commit') or '—') + ('*' if t.get('dirty') else ''),
                   opt(t.get('sharpe'), '+.2'), opt(t.get('ret_pct'), '+.2'), opt(t.get('trades'), ',.0'),
                   opt(t.get('oos_sharpe'), '+.2')]
        trials.append(row)
    spec = [
        ['Universe', f"Russell 3000 members as held by the iShares Russell 3000 ETF (IWV), from its quarterly SEC "
                     f"N-PORT filings: the latest snapshot whose period ends on or before each formation date, used "
                     f"from its period date, about two months before the filing was public (IWV's holdings stand in "
                     f"for the index membership FTSE Russell had already published). Holdings mapped to tickers with "
                     f"OpenFIGI and checked against N-PORT's own value per share. Daily prices {P['data_years']}: "
                     f"price history for {m['study.dev.facts.cached_pct']} of the requested symbols; "
                     f"{m['study.dev.facts.not_found_pct']} no longer served by the vendor (HTTP 404) and "
                     f"{m['study.dev.facts.fetch_other_pct']} failed the fetch or the data checks; the fetch-coverage "
                     f"rule, which counts 404s and failed data checks as resolved, is met at "
                     f"{m['study.dev.facts.coverage_pct']}. Screens on the window's length (at least 300 bars), "
                     f"mean point-in-time price (at least $5, anchored to N-PORT) and mean dollar volume (at least $10M a day), "
                     f"volatility and missing data; the {pv33.max_universe} most liquid enter the pair search."],
        ['Selection', f"Pairs within one Fama–French 49 industry (SEC SIC codes); positive return correlation ≥ 0.25; "
                      f"two-direction Engle–Granger p < 0.05 (Bonferroni across directions); half-life 4–25 days on "
                      f"the cointegrating spread; quality score > 0.4. The whole selection re-run every "
                      f"{pv33.reselect_every} trading days on the trailing {word(pv33.formation_calendar_days // 365)} "
                      f"years; open positions run off."],
        ['Spread', 'Two-state Kalman filter (slope and intercept) on log prices centred on their burn-in means, so β '
                   'is a hedge ratio and signals are invariant to vendor back-adjustment.'],
        ['Rule', 'One β-locked z-score against its mean and standard deviation over the last 30–60 bars, frozen at the '
                 'signal. Entry |z| ≥ 1.8; target once z reverts past −0.5 (long) or +0.5 (short); stop 1.5 further '
                 'against; time stop max(10, min(⌊2.5 × half-life⌋, 25)) days. Gates: pair quality ≥ 0.55, 20-day '
                 'correlation ≥ 0.20, β in [0.25, 4], at least 50 bars of pair history, locked-spread standard '
                 "deviation at most 0.30, the smaller leg's 20-day dollar ADV at least $1M, an ex-ante round-trip cost "
                 '(with borrow over the maximum hold) below 1% of equity, a 30-day pause after three consecutive losing '
                 'trades on a pair; no new signal on a day the book lost more than 3%. No regime gate.'],
        ['Book', f"${m['study.dev.facts.capital_musd']}M notional; 3–10% of equity per pair before risk scaling "
                 f"({m['paper.position_min_pct']} to {m['paper.position_max_pct']} as traded), scaled by the win rate "
                 'of the last five closed trades and the volatility of recent daily returns; 30% gross cap on '
                 'exposure at entry; at most 8 entries a day, ordered by signal strength × pair quality; no shared '
                 'legs; daily mark-to-market; a kill switch that flattens the book at a 15% drawdown from peak, a 5% '
                 'daily loss or gross exposure at entry above 30%.'],
        ['Costs', f"Per execution: $0.002 a share (minimum $0.50), half the quoted spread by 20-day dollar ADV, "
                  f"square-root impact (Y = 0.3, cap 50 bp); one {fmt(100 * pv33.borrow_rate, '.2')}% a year borrow "
                  'fee on the short notional, charged over the days held.'],
        ['Walk-forward', f"The same rule on the same formations from {P['oos_start_long']}, one continuous simulation "
                         'cut into 63-day test windows; there is no model to refit.'],
        ['Evidence', 'Probabilistic and deflated Sharpe, Newey–West t, Politis–White block bootstrap, power and upper '
                     f"bounds under a non-normal AR(1) variance, a Bonferroni Sharpe hurdle for "
                     f"{m['study.dev.facts.hurdle_tests']} trials and two field-wide hurdles, Ledoit–Wolf "
                     'Sharpe-difference test; eight-factor attribution; the anatomy of the result (shortfall, exit race, '
                     'decay, persistence, half-lives, capacity, cash); Gatev distance method and '
                     'random pairs under the same costs and t + 1 fills. A declared family of '
                     f"{m['study.dev.snooping.results.n'] or 'pending'} variants with Hansen's SPA, White's Reality Check, the "
                     'Romano–Wolf stepdown, the model confidence set, PBO and a deflated Sharpe ratio at its effective number '
                     'of trials; robustness checks over start dates, regimes, the candidate pairs\' persistence and clustered '
                     'standard errors.'],
    ]
    return {'significance': significance, 'forest': forest, 'alternatives': alternatives, 'hurdles': hurdles,
            'schedules': schedules, 'scenarios': scenarios, 'windows': windows, 'holdout_power': holdout_power_rows,
            'variants': variants, 'hypotheses': hypotheses, 'snooping': snooping, 'validation': validation,
            'manifest': manifest, 'sources': sources, 'design': design_rows, 'compare': compare, 'trials': trials,
            'spec': spec, 'performance': performance_rows, 'startdates': startdates, 'halves': halves,
            'regimes': regimes, 'persistence_s1': pers_s1,
            **(holdout_tables(study['holdout'], P['ho']) if P.get('ho') else {})}


def holdout_tables(H, ho):
    """The evaluated holdout's tables, every number rounded as the site rounds it (half up):
    the test and decision of each arm ('ho_results'), the other statistics the pre-registration
    reports for every arm ('ho_detail', one column per arm), every attempt of the runbook
    ('ho_record') and the survivorship gap of S1 and S2 ('ho_universe')."""
    def f(x, spec):
        return fmt(x, spec, half_up=True) if x is not None else '—'
    arms = [(ho[sid], a) for (_, _, sid, _), a in zip(HOLDOUT_ARMS, H['arms'])]
    results = []
    for h, a in arms:
        results.append([f"{h['hyp']} · {h['label']}" if h['hyp'] else h['label'], h['name'],
                        f(a['days'], '.0'), f(a['trades'], ',.0'), f(a['ret_pct'], '+.2'),
                        f(a['sharpe'], '+.2'),
                        f"{f(a['lo'], '+.2')} to {f(a['hi'], '+.2')}" if a['lo'] is not None and a['hi'] is not None else '—',
                        f(a['t'], '.2'), h['p_one_text'], h.get('p_holm_text') or '—',
                        h['decision'].capitalize(), f(a['ucb'], '+.2'), f(a['mde'], '.2')])

    def row(label, cells):
        return [label, *cells]

    def both(x, y, spec_x, spec_y=None):
        return '—' if x is None and y is None else f"{f(x, spec_x)} / {f(y, spec_y or spec_x)}"

    def gatev(a):
        v = a.get('vs_gatev') or {}
        if v.get('diff') is None:
            return '—'
        return f"{f(v['diff'], '+.2')} [{f(v.get('lo'), '+.2')}, {f(v.get('hi'), '+.2')}]"

    def source(a):
        src = {**(a.get('vs_gatev') or {}), **(a.get('random_pair') or {})}.get('source') or ''
        return 'its own run' if src in ('', 'own run') else 'S1’s run'      # the evaluator's BASELINE_ARM
    detail = [
        row('Gross return, %', [f(a.get('gross_ret_pct'), '+.2') for _, a in arms]),
        row('Sharpe ratio before costs', [f(a.get('gross_sharpe'), '+.2') for _, a in arms]),
        row('Sharpe ratio, Lo (2002) annualisation', [f(a.get('sharpe_lo2002'), '+.2') for _, a in arms]),
        row('Probabilistic Sharpe ratio, %', [f(a.get('psr_pct'), '.1') for _, a in arms]),
        row('Standard error of the Sharpe ratio', [f(a.get('sharpe_se'), '.2') for _, a in arms]),
        row('Minimum detectable Sharpe, one-sided 2.5% / 5%', [both(a.get('mde'), a.get('mde_single'), '.2')
                                                               for _, a in arms]),
        row('Newey–West lags', [f(a.get('lags'), '.0') for _, a in arms]),
        row('Gross exposure, % of equity: average / maximum',
            [both(_get(a, 'exposure', 'avg_pct'), _get(a, 'exposure', 'max_pct'), '.1') for _, a in arms]),
        row('Days with open positions', [f(_get(a, 'exposure', 'days_open'), '.0') for _, a in arms]),
        row('Gatev distance method: Sharpe ratio (common days)',
            [f"{f(_get(a, 'vs_gatev', 'distance_sharpe'), '+.2')} ({f(_get(a, 'vs_gatev', 'days'), '.0')})"
             if _get(a, 'vs_gatev', 'distance_sharpe') is not None else '—' for _, a in arms]),
        row('Arm minus Gatev, Sharpe [95% interval]', [gatev(a) for _, a in arms]),
        row('Ledoit–Wolf p of the difference, two-sided', [_p_text(_get(a, 'vs_gatev', 'p')) or '—' for _, a in arms]),
        row('Percentile among random-pair portfolios (their median Sharpe)',
            [f"{f(_get(a, 'random_pair', 'percentile'), '.1')} ({f(_get(a, 'random_pair', 'median_sharpe'), '+.2')})"
             if _get(a, 'random_pair', 'percentile') is not None else '—' for _, a in arms]),
        row('Baselines from', [source(a) for _, a in arms]),
    ]
    R = H['provenance']

    def steps(names):
        return ', '.join(HOLDOUT_STEPS.get(n, n) for n in names) or '—'
    record = []
    for i, x in enumerate(R['attempts']):
        last = i == len(R['attempts']) - 1
        kind = ('registered' if x['at_registered_commit'] else 'crash fix' if x.get('crash_fix') else
                'later commit')
        failed = x.get('failed')
        # an earlier attempt without a failure line stopped without recording one; the last
        # registered the trial, with its completion line or (if the runbook stopped first) without
        ended = (f"{HOLDOUT_STEPS.get(failed['step'], failed['step'])} ({failed['note']})" if failed and failed.get('note')
                 else HOLDOUT_STEPS.get(failed['step'], failed['step']) if failed
                 else '—' if last else 'stopped; no failure recorded')
        done = (_utc(x['completed_utc'], '') or
                (f"— (registered {_utc(_get(R, 'registry', 'registered_utc'), '')})" if last else '—'))
        record.append([str(x['attempt']), x['head'][:7], kind, _utc(x['started_utc'], ''), steps(x['steps_done']),
                       ended, done])
    universe = []
    for h, a in arms:
        for u in a.get('universe') or []:
            universe.append([h['label'], short_date(u['formation_date']) if u.get('formation_date') else '—',
                             short_date(u['snapshot']) if u.get('snapshot') else '—',
                             short_date(u['snapshot_filed']) if u.get('snapshot_filed') else '—',
                             f(u.get('members'), ',.0'), f(u.get('missing'), ',.0'),
                             f(u.get('missing_weight_pct'), '.2'), f(u.get('unmapped_weight_pct'), '.2'),
                             f"{f(u['no_sector_etf'], ',.0')} ({f(u.get('no_sector_etf_weight_pct'), '.2')})"
                             if u.get('no_sector_etf') is not None else '—'])
    # a comparison the evaluation leaves out says why (its note), in the detail table's notes
    notes = [f"{h['label']}: {_get(a, 'random_pair', 'note')}" for h, a in arms
             if _get(a, 'random_pair', 'percentile') is None and _get(a, 'random_pair', 'note')]
    return {'ho_results': results, 'ho_detail': detail, 'ho_detail_notes': notes, 'ho_record': record,
            'ho_universe': universe}


# ──────────────────────────────────────────────────────────────────────────────
# Figures
# ──────────────────────────────────────────────────────────────────────────────

MM = 1 / 25.4
FULL = EXHIBIT_WIDTH_MM * MM
HALF = (EXHIBIT_WIDTH_MM - COLUMN_GAP_MM) / 2 * MM
PAIR_HEIGHT = 1.6                       # inches: side-by-side exhibits share a height


def _mpl(tokens):
    """matplotlib with IBM Plex from paper/fonts and the site's light-theme colours."""
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import font_manager
    for path in sorted(FONTS.glob('*.ttf')):
        font_manager.fontManager.addfont(str(path))
    matplotlib.rcParams.update({
        'font.family': 'IBM Plex Sans', 'font.size': 7.0, 'axes.titlesize': 7.5, 'axes.labelsize': 7.0,
        'xtick.labelsize': 6.8, 'ytick.labelsize': 6.8, 'legend.fontsize': 7.0,
        'text.color': tokens['ink'], 'axes.labelcolor': tokens['ink-2'], 'xtick.color': tokens['axis'],
        'ytick.color': tokens['axis'], 'xtick.labelcolor': tokens['ink-2'], 'ytick.labelcolor': tokens['ink-2'],
        'axes.edgecolor': tokens['axis'], 'axes.linewidth': 0.6, 'axes.grid': True, 'axes.axisbelow': True,
        'grid.color': tokens['grid'], 'grid.linewidth': 0.5, 'axes.spines.top': False, 'axes.spines.right': False,
        'axes.spines.left': False, 'xtick.major.size': 2.5, 'xtick.major.width': 0.6, 'ytick.major.size': 0,
        'ytick.major.pad': 3, 'xtick.major.pad': 2.5, 'lines.linewidth': 1.1, 'lines.solid_capstyle': 'round',
        'lines.solid_joinstyle': 'round', 'legend.frameon': False, 'axes.unicode_minus': True,
        'figure.facecolor': 'white', 'axes.facecolor': 'white', 'savefig.facecolor': 'white',
        # text stays text (searchable and copyable in the PDF); Typst sets it in the same Plex files
        'svg.fonttype': 'none', 'svg.hashsalt': 'pairs-study', 'svg.image_inline': True, 'path.simplify': False,
        'axes.titlelocation': 'left', 'axes.titlepad': 4, 'axes.titleweight': 'semibold',
        'hatch.linewidth': 0.5, 'hatch.color': tokens['neutral-series'],
    })
    import matplotlib.pyplot as plt
    return plt


def _signed(v, dp=1, suffix=''):
    return fmt(v, f'+.{dp}{suffix}')


# Typst knows the static Plex Medium and SemiBold files by their own family names, so a
# weight that matplotlib writes as 'IBM Plex Sans' + font-weight names that family instead.
_SVG_WEIGHTS = {'500': 'IBM Plex Sans Medm', '600': 'IBM Plex Sans SmBld'}


def _svg_family(match):
    style = match.group(1)
    weight = re.search(r'font-weight: (\d+)', style)
    if weight and weight.group(1) in _SVG_WEIGHTS:
        style = re.sub(r'font-weight: \d+;? ?', '', style)
        style = style.replace("font-family: 'IBM Plex Sans'", f"font-family: '{_SVG_WEIGHTS[weight.group(1)]}'")
    return f'style="{style.rstrip("; ")}"'


def _svg(fig):
    buf = io.StringIO()
    fig.savefig(buf, format='svg', metadata={'Date': None, 'Creator': None, 'Format': None, 'Type': None})
    import matplotlib.pyplot as plt
    plt.close(fig)
    text = re.sub(r'style="([^"]*font-family[^"]*)"', _svg_family, buf.getvalue())
    # ids are salted (svg.hashsalt) and so deterministic; drop trailing spaces
    return '\n'.join(line.rstrip() for line in text.splitlines()) + '\n'


def _dates(xs):
    import matplotlib.dates as mdates
    return mdates.datestr2num(list(xs))


def _year_axis(ax, minor=True):
    import matplotlib.dates as mdates
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    if minor:
        ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=(4, 7, 10)))
        ax.tick_params(axis='x', which='minor', length=1.5, width=0.4, color=ax.spines['bottom'].get_edgecolor())


def _end_label(ax, x, y, text, color, t, label_y=None, weight='semibold'):
    """An end dot on (x, y) and its label to the right, at label_y when labels must be kept apart."""
    from matplotlib.transforms import ScaledTranslation
    ax.plot([x], [y], marker='o', markersize=3.6, color=color, markeredgecolor='white', markeredgewidth=0.9,
            zorder=5, clip_on=False)
    shift = ScaledTranslation(5 / 72, 0, ax.figure.dpi_scale_trans)
    ax.text(x, y if label_y is None else label_y, text, transform=ax.transData + shift, va='center', ha='left',
            fontsize=7, color=t['ink'], fontweight=weight, clip_on=False)


def _legend(ax, handles, t, loc='lower left', ncol=None, anchor=(0, 1.0)):
    """One row of legend entries; by default just above the axes, clear of the data."""
    leg = ax.legend(handles=handles, loc=loc, ncol=ncol or len(handles), handlelength=1.4, handletextpad=0.5,
                    columnspacing=1.4, borderaxespad=0.2, bbox_to_anchor=anchor)
    for txt in leg.get_texts():
        txt.set_color(t['ink-2'])
    return leg


def _zero(ax, t, axis='y'):
    (ax.axhline if axis == 'y' else ax.axvline)(0, color=t['axis'], linewidth=0.8, zorder=1.5)


def fig_equity(dev, t, plt):
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    D, G, B = dev['daily'], dev.get('gatev'), dev.get('random_band')
    x = _dates(D['dates'])
    fig, axes = plt.subplots(3, 1, figsize=(FULL, 3.25), sharex=True,
                             gridspec_kw={'height_ratios': [2.7, 1.05, 1.05], 'hspace': 0.18})
    ax = axes[0]
    handles = [Line2D([], [], color=t['series-1'], lw=1.3, label='Strategy (net)')]
    if B:
        # the middle half of the draws: their 5th percentile ends far below this scale (an
        # unhedged random pair can lose most of its committed capital); the notes give both tails
        xb = _dates(B['dates'])
        ax.fill_between(xb, B['p25'], B['p75'], color=t['neutral-series'], alpha=0.2, lw=0, zorder=1)
        handles.append(Patch(color=t['neutral-series'], alpha=0.35, lw=0,
                             label=f"Random pairs, 25th–75th percentile ({B['n_draws']} draws)"))
    _zero(ax, t)
    if G:
        xg = _dates(G['dates'])
        ax.plot(xg, G['cum'], color=t['series-2'], lw=1.1, zorder=3)
        handles.insert(1, Line2D([], [], color=t['series-2'], lw=1.1, label='Gatev distance method (net)'))
    ax.plot(x, D['cum'], color=t['series-1'], lw=1.3, zorder=4)
    ends = [[x[-1], D['cum'][-1], 'Strategy ' + fmt(D['cum'][-1], '+.2%'), t['series-1'], D['cum'][-1]]]
    if G:
        ends.append([xg[-1], G['cum'][-1], 'Gatev ' + fmt(G['cum'][-1], '+.2%'), t['series-2'], G['cum'][-1]])
    lo_all = [min(D['cum'])] + ([min(G['cum'])] if G else []) + ([min(B['p25'])] if B else [])
    hi_all = [max(D['cum'])] + ([max(G['cum'])] if G else []) + ([max(B['p75'])] if B else [])
    span = max(hi_all) - min(lo_all)
    if len(ends) == 2 and abs(ends[0][1] - ends[1][1]) < 0.1 * span:       # keep the two labels apart
        lo, hi = sorted(ends, key=lambda e: e[1])
        centre = (lo[1] + hi[1]) / 2
        lo[4], hi[4] = centre - 0.05 * span, centre + 0.05 * span
    for e in ends:
        _end_label(ax, e[0], e[1], e[2], e[3], t, label_y=e[4])
    ax.set_ylabel('Cumulative net\nreturn, %')
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 0)))
    _legend(ax, handles, t)
    ax.margins(x=0)
    for a in axes[:2]:
        a.tick_params(axis='x', which='both', length=0)
        a.spines['bottom'].set_visible(False)
    ax2 = axes[1]
    ax2.fill_between(x, D['dd'], 0, color=t['neg'], alpha=0.16, lw=0)
    ax2.plot(x, D['dd'], color=t['neg'], lw=0.8)
    i = int(np.argmin(D['dd']))
    ax2.annotate('max ' + fmt(D['dd'][i], '.2%'), (x[i], D['dd'][i]), xytext=(0, -3), textcoords='offset points',
                 fontsize=6.8, color=t['ink'], ha='center', va='top')
    ax2.set_ylabel('Drawdown, %')
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fmt(v, '.0')))
    ax2.yaxis.set_major_locator(plt.MaxNLocator(3, integer=True))
    ax2.set_ylim(min(D['dd']) * 1.75, 0.15)
    ax3 = axes[2]
    ax3.fill_between(x, D['exposure'], 0, color=t['series-1'], alpha=0.14, lw=0, step='post')
    ax3.plot(x, D['exposure'], color=t['series-1'], lw=0.7, drawstyle='steps-post')
    cap = 30.0
    ax3.axhline(cap, color=t['ink-3'], lw=0.6)
    ax3.annotate('30% gross cap', (x[-1], cap), xytext=(0, 2), textcoords='offset points', ha='right', va='bottom',
                 fontsize=6.6, color=t['ink-2'])
    ax3.set_ylim(0, cap * 1.25)
    ax3.set_yticks([0, 10, 20, 30])
    ax3.set_ylabel('Gross exposure,\n% of capital')
    _year_axis(ax3)
    for a in axes:
        a.yaxis.set_label_coords(-0.075, 0.5)
    fig.subplots_adjust(left=0.1, right=0.86, top=0.93, bottom=0.07)
    return fig


def fig_walkforward(dev, t, plt):
    WF = dev['walk_forward']
    W = WF['windows']
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(FULL, 2.45), sharex=True,
                                  gridspec_kw={'height_ratios': [1.7, 1.0], 'hspace': 0.16})
    a = _dates([w['test_start'] for w in W])
    b = _dates([w['test_end'] for w in W])
    r = [w['ret_pct'] or 0.0 for w in W]
    width = (b - a) * 0.86
    mid = a + (b - a) / 2
    colors = [t['pos'] if v >= 0 else t['neg'] for v in r]
    ax.bar(mid, r, width=width, color=colors, zorder=3)
    _zero(ax, t)
    ext = max(abs(v) for v in r)
    for xm, v, w in zip(mid, r, W):
        ax.annotate(str(w['trades']), (xm, v), xytext=(0, 2.5 if v >= 0 else -2.5), textcoords='offset points', ha='center',
                    va='bottom' if v >= 0 else 'top', fontsize=6.4, color=t['ink-2'])
    ax.set_ylim(-ext * 1.3, ext * 1.3)
    ax.tick_params(axis='x', which='both', length=0)
    ax.spines['bottom'].set_visible(False)
    ax.set_ylabel('Window net\nreturn, %')
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 1)))
    if WF.get('daily'):
        px, py = _dates(WF['daily']['dates']), WF['daily']['cum']
        ax2.plot(px, py, color=t['series-1'], lw=1.2)
    else:
        px = np.concatenate([[a[0]], b])
        py = [0.0] + [s['cum_pct'] for s in WF['stitched']]
        ax2.plot(px, py, color=t['series-1'], lw=1.2, marker='o', markersize=2.6, markeredgecolor='white',
                 markeredgewidth=0.6)
    _zero(ax2, t)
    _end_label(ax2, px[-1], py[-1], fmt(py[-1], '+.2%'), t['series-1'], t)
    lo, hi = min(py), max(py)
    ax2.set_ylim(min(lo, 0) - 0.25 * (hi - lo + 0.1), max(hi, 0) + 0.25 * (hi - lo + 0.1))
    ax2.set_ylabel('Stitched path, %')
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 1)))
    _year_axis(ax2)
    for a_ in (ax, ax2):
        a_.yaxis.set_label_coords(-0.075, 0.5)
    fig.subplots_adjust(left=0.1, right=0.9, top=0.97, bottom=0.09)
    return fig


def _diverging(t):
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list('div', [t['neg'], t['div-mid'], t['pos']])


def _luminance(rgb):
    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2])


def fig_monthly(dev, t, plt):
    from matplotlib.colors import to_rgb
    months, annual = dev['monthly'], dev['annual']
    years = sorted({m['ym'][:4] for m in months})
    cols = [mn[:3] for mn in MONTHS] + ['Year']
    vals = {(m['ym'][:4], int(m['ym'][5:7]) - 1): m['ret_pct'] for m in months}
    for a in annual:
        vals[(a['year'], 12)] = a['ret_pct']
    vmax = max(abs(v) for v in vals.values()) or 1.0
    cmap = _diverging(t)
    fig, ax = plt.subplots(figsize=(FULL, 0.42 + 0.27 * len(years)))
    ink = to_rgb(t['ink'])
    for (y, c), v in vals.items():
        row = years.index(y)
        rgba = cmap(0.5 + 0.5 * v / vmax)
        x0 = c + (0.25 if c == 12 else 0)
        ax.add_patch(plt.Rectangle((x0 + 0.04, row + 0.06), 0.92, 0.88, facecolor=rgba, edgecolor='none'))
        lum = _luminance(rgba[:3])
        light = (1.05) / (lum + 0.05) > (lum + 0.05) / (_luminance(ink) + 0.05)
        ax.text(x0 + 0.5, row + 0.5, fmt(v, '+.2'), ha='center', va='center', fontsize=6.5,
                color='white' if light else t['ink'], fontweight='semibold' if light else 'normal')
    ax.set_xlim(0, 13.25)
    ax.set_ylim(len(years), 0)
    ax.set_xticks([i + 0.5 + (0.25 if i == 12 else 0) for i in range(13)])
    ax.set_xticklabels(cols)
    ax.xaxis.tick_top()
    ax.set_yticks([i + 0.5 for i in range(len(years))])
    ax.set_yticklabels(years)
    ax.tick_params(length=0)
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    fig.subplots_adjust(left=0.06, right=0.995, top=0.8, bottom=0.03)
    return fig


def fig_rolling(dev, t, plt):
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    R = dev['rolling_sharpe']
    x = _dates(R['dates'])
    sr = np.array([np.nan if v is None else v for v in R['sharpe']])
    lo = np.array([np.nan if v is None else v for v in R['lo']])
    hi = np.array([np.nan if v is None else v for v in R['hi']])
    fig, ax = plt.subplots(figsize=(FULL, 1.9))
    ax.fill_between(x, lo, hi, color=t['neutral-series'], alpha=0.2, lw=0)
    _zero(ax, t)
    ax.plot(x, sr, color=t['series-1'], lw=1.2)
    ax.set_ylabel('Sharpe ratio, annualised')
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 0)))
    _year_axis(ax)
    ax.margins(x=0)
    _legend(ax, [Line2D([], [], color=t['series-1'], lw=1.2, label=f"Rolling {R['window']}-day Sharpe"),
                 Patch(color=t['neutral-series'], alpha=0.35, lw=0, label='±1.96 standard errors')], t)
    fig.subplots_adjust(left=0.075, right=0.99, top=0.88, bottom=0.12)
    return fig


# The paper calls the walk-forward "out of sample" only with its qualification (Section
# 3.5), so the site's short labels lose the "OOS".
def _wf_label(label):
    return label.replace('Walk-forward OOS', 'Walk-forward')


def fig_forest(dev, study, power, t, plt):
    """Sharpe ratios with intervals; `power` is the one-sided bound and the 80%-power Sharpe drawn."""
    color = {'main': t['series-1'], 'oos': t['series-1'], 'gatev': t['series-2'], 'diff_main': t['ink-2'],
             'diff_oos': t['ink-2'], 'random': t['neutral-series'], 'gross': t['series-1'],
             'residual': t['series-3'], 'residual_gross': t['series-3']}
    rows = [dict(r, label=_wf_label(r['label'])) for r in dev['forest']]
    res = study.get('residual')
    if res and res.get('sharpe') is not None:
        rows.append({'key': 'residual', 'label': 'Avellaneda–Lee, net', 'kind': 'ci', 'sharpe': res['sharpe'],
                     'lo': res['lo'], 'hi': res['hi']})
        if res.get('gross_sharpe') is not None:
            rows.append({'key': 'residual_gross', 'label': 'Avellaneda–Lee, gross of costs', 'kind': 'ci',
                         'sharpe': res['gross_sharpe'], 'lo': res['gross_lo'], 'hi': res['gross_hi']})
    n = len(rows)
    fig, ax = plt.subplots(figsize=(FULL, 0.62 + 0.215 * n))
    for i, r in enumerate(rows):
        c = color.get(r['key'], t['ink-2'])
        ax.plot([r['lo'], r['hi']], [i, i], color=c, lw=1.4, solid_capstyle='butt', zorder=3)
        gross = r['key'] in ('gross', 'residual_gross')     # open markers: before costs
        ax.plot([r['sharpe']], [i], marker='o', markersize=4.2, color=c, markerfacecolor='white' if gross else c,
                markeredgecolor=c if gross else 'white', markeredgewidth=1.1 if gross else 0.9, zorder=4)
    _zero(ax, t, 'x')
    # the one-sided bound and the 80%-power Sharpe, each a full-height rule labelled at its top
    for v, text, ls, ha, dx in ((power['ucb'], f"one-sided 95% bound {fmt(power['ucb'], '.2')}", (0, (3, 2)), 'right', -3),
                                (power['mde'], f"80% power at {fmt(power['mde'], '.2')}", '-', 'left', 3)):
        ax.plot([v, v], [-0.75, n - 0.5], color=t['ink-2'], lw=0.8, ls=ls, zorder=2)
        ax.annotate(text, (v, -0.75), xytext=(dx, 0), textcoords='offset points', va='center', ha=ha,
                    fontsize=6.6, color=t['ink-2'])
    ax.set_yticks(range(n))
    ax.set_yticklabels([r['label'] for r in rows])
    for lab in ax.get_yticklabels():
        lab.set_color(t['ink'])
    ax.set_ylim(n - 0.5, -1.2)
    lows = [r['lo'] for r in rows] + [0.0]
    highs = [r['hi'] for r in rows] + [power['mde']]
    pad = 0.04 * (max(highs) - min(lows))
    ax.set_xlim(min(lows) - pad, max(highs) + 4 * pad)
    ax.xaxis.set_major_locator(plt.MultipleLocator(0.5))
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 1)))
    ax.set_xlabel('Annualised Sharpe ratio')
    ax.grid(axis='y', visible=False)
    fig.subplots_adjust(left=0.24, right=0.99, top=0.985, bottom=0.4 / (0.62 + 0.215 * n))
    return fig


def fig_randomnull(dev, t, plt, width=FULL):
    R = dev['random_sharpes']
    s, g = dev['strategy_sharpe'], dev['gatev_sharpe']
    lo = math.floor(min(R + [s, g]) * 5) / 5 - 0.2
    hi = math.ceil(max(R + [s, g]) * 5) / 5 + 0.2
    bins = np.arange(lo, hi + 1e-9, 0.2)
    fig, ax = plt.subplots(figsize=(width, PAIR_HEIGHT if width < FULL else 1.95))
    counts, _, _ = ax.hist(R, bins=bins, color=t['neutral-series'], alpha=0.55, rwidth=0.9, zorder=2)
    _zero(ax, t, 'y')
    top = counts.max() * 1.32
    ax.set_ylim(0, top)
    marks = [(s, 'Strategy ' + fmt(s, '+.2'), t['series-1']), (g, 'Gatev ' + fmt(g, '+.2'), t['series-2'])]
    marks.sort(key=lambda m: m[0])
    for k, (xv, text, c) in enumerate(marks):
        ax.axvline(xv, color=c, lw=1.3, zorder=3)
        left = k == 0
        ax.annotate(text, (xv, top), xytext=(-3 if left else 3, -1), textcoords='offset points',
                    ha='right' if left else 'left', va='top', fontsize=6.8, color=t['ink'], fontweight='semibold')
    ax.set_xlim(lo, hi)
    ax.xaxis.set_major_locator(plt.MultipleLocator(0.5 if width >= FULL else 1.0))
    ax.set_ylabel('Draws')
    ax.set_xlabel('Annualised Sharpe ratio of a random-pair draw')
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 1)))
    ax.grid(axis='x', visible=False)
    fig.subplots_adjust(left=0.075 * FULL / width, right=0.975, top=0.97, bottom=0.25 if width < FULL else 0.2)
    return fig


def _dodge(xs, gap):
    """Stack levels for a dot strip: each value (in sorted order) takes the lowest level on which
    no earlier dot lies within `gap` of it."""
    levels, placed = [], []
    for x in xs:
        lvl = 0
        while any(abs(x - px) < gap for px, pl in placed if pl == lvl):
            lvl += 1
        placed.append((x, lvl))
        levels.append(lvl)
    return levels


def fig_dsr(dev, t, plt, width=FULL):
    """The declared variants' Sharpe ratios (a dot strip, the v33 design and the Gatev baseline
    marked) beside the main backtest's deflated Sharpe ratio against N, with the estimator's null
    trial variance and with the variants' own Sharpe dispersion. Without the family's results,
    the deflated Sharpe panel alone."""
    C = dev['dsr_curve']
    sn = (dev.get('snooping') or {}).get('results')
    at = dev['facts']['dsr_trials']
    if sn:
        fig, (axf, ax) = plt.subplots(1, 2, figsize=(width, 1.95), gridspec_kw={'width_ratios': [1.25, 1], 'wspace': 0.16})
        V = sorted(sn['variants'], key=lambda v: v['sharpe'])
        xs = [v['sharpe'] for v in V]
        g = dev.get('gatev_sharpe')
        lo, hi = min(xs + [g or 0]) - 0.12, max(xs + [0]) + 0.12
        levels = _dodge(xs, (hi - lo) * 0.026)
        colors = [t['ink'] if v['base'] else t['series-1'] if v['kind'] == 'grid' else t['series-3'] for v in V]
        axf.scatter(xs, levels, s=17, c=colors, edgecolors='white', linewidths=0.5, zorder=3)
        top = max(levels) + 2.6
        axf.set_ylim(-0.8, top)
        axf.set_xlim(lo, hi)
        axf.axvline(0, color=t['axis'], lw=0.8, zorder=1)
        if g is not None:
            axf.axvline(g, color=t['series-2'], lw=1.0, ls=(0, (3, 2)), zorder=2)
            axf.annotate('Gatev ' + fmt(g, '+.2'), (g, top), xytext=(-3, -1), textcoords='offset points',
                         ha='right', va='top', fontsize=6.4, color=t['series-2'])
        base = [v for v in V if v['base']]
        if base:
            b = base[0]
            axf.axvline(b['sharpe'], color=t['ink'], lw=0.6, alpha=0.45, zorder=1)
            axf.annotate(f"{dev['run']['name'].split('_')[0]} design, rank {b['rank']} of {len(V)}",
                         (b['sharpe'], top), xytext=(-3, -9), textcoords='offset points', ha='right', va='top',
                         fontsize=6.4, color=t['ink'], fontweight='semibold')
        axf.set_yticks([])
        axf.spines['bottom'].set_visible(True)
        axf.grid(axis='y', visible=False)
        axf.xaxis.set_major_locator(plt.MultipleLocator(0.5))
        axf.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 1)))
        axf.set_xlabel('Net Sharpe ratio of each declared variant')
        from matplotlib.lines import Line2D
        axf.legend(handles=[Line2D([], [], lw=0, marker='o', markersize=4, markerfacecolor=c, markeredgecolor='white', label=lab)
                            for c, lab in ((t['series-1'], 'Threshold grid'), (t['series-3'], 'Design toggle'))],
                   loc='upper left', ncol=1, fontsize=6.3, handletextpad=0.2, borderaxespad=0.1, frameon=False)
    else:
        fig, ax = plt.subplots(figsize=(width, PAIR_HEIGHT if width < FULL else 1.95))
    n = [r['n'] for r in C]
    d = [100 * r['dsr'] for r in C]
    ax.plot(n, d, color=t['ink-2'], lw=1.0, ls=(0, (3, 2)), zorder=3)
    for r in C:
        if r['n'] == at:
            ax.plot([r['n']], [100 * r['dsr']], marker='o', markersize=4.5, markerfacecolor='white',
                    markeredgecolor=t['ink-2'], markeredgewidth=1.0, zorder=4)
    if sn and (sn.get('dsr') or {}).get('dsr_pct') is not None:
        F = sorted(sn['dsr']['curve'] + [{'n': sn['dsr']['n_trials'], 'dsr': sn['dsr']['dsr_pct'] / 100}],
                   key=lambda r: r['n'])
        ax.plot([r['n'] for r in F], [100 * r['dsr'] for r in F], color=t['series-1'], lw=1.2, zorder=3)
        ax.plot([sn['dsr']['n_trials']], [sn['dsr']['dsr_pct']], marker='o', markersize=5, markerfacecolor='white',
                markeredgecolor=t['series-1'], markeredgewidth=1.1, zorder=4)
        ax.annotate(f"N = {sn['dsr']['n_trials']}, the family: {fmt(sn['dsr']['dsr_pct'], '.1%')}", (1, 1),
                    xycoords='axes fraction', xytext=(0, -1), textcoords='offset points', ha='right', va='top',
                    fontsize=6.4, color=t['series-1'], fontweight='semibold')
    reported = next((100 * r['dsr'] for r in C if r['n'] == at), None)
    if reported is not None:
        ax.annotate(f"N = {at}, the trials reported: {fmt(reported, '.1%')}", (1, 1), xycoords='axes fraction',
                    xytext=(0, -10), textcoords='offset points', ha='right', va='top', fontsize=6.4, color=t['ink-2'])
    _zero(ax, t)
    ax.set_xscale('log')
    ax.set_xlim(n[0] * 0.8, n[-1] * 1.25)
    ax.set_ylim(0, max(50, d[0] * 1.1))
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fmt(v, ',.0')))
    ax.set_xlabel('Independent trials N (log scale)')
    ax.set_ylabel('Deflated Sharpe, %')
    ax.grid(axis='x', visible=False)
    fig.subplots_adjust(left=0.03 if sn else 0.075 * FULL / width, right=0.985, top=0.97,
                        bottom=0.25 if width < FULL and not sn else 0.2)
    return fig


def fig_waterfall(dev, t, plt):
    steps = dev.get('shortfall') or dev['waterfall']
    # a cost item that is zero by design (v33 folds financing into the borrow fee) is left out
    steps = [s for s in steps if s['key'] in ('gross', 'net', 'paper') or abs(s['usd']) >= 0.5]
    rows = [{'step': _STEP_LABELS.get(s['key'], s['step']), 'a': s['start'] / 1e3, 'b': s['end'] / 1e3,
             'usd': s['usd'], 'total': s['key'] in ('gross', 'net', 'paper')} for s in steps]
    fig, ax = plt.subplots(figsize=(FULL, 0.38 + 0.2 * len(rows)))
    for i, r in enumerate(rows):
        c = t['ink-2'] if r['total'] else (t['pos'] if r['usd'] >= 0 else t['neg'])
        left, w = min(r['a'], r['b']), abs(r['b'] - r['a'])
        ax.barh(i, w, left=left, height=0.62, color=c, zorder=3)
        label = fmt(r['usd'] / 1e3, '+,.1') + 'k'
        if r['b'] >= r['a']:
            ax.annotate(label, (max(r['a'], r['b']), i), xytext=(3, 0), textcoords='offset points', va='center',
                        ha='left', fontsize=6.8, color=t['ink'])
        else:
            ax.annotate(label, (min(r['a'], r['b']), i), xytext=(-3, 0), textcoords='offset points', va='center',
                        ha='right', fontsize=6.8, color=t['ink'])
        if i + 1 < len(rows) and not rows[i + 1]['total']:
            ax.plot([r['b'], r['b']], [i + 0.31, i + 0.69], color=t['rule-2'], lw=0.5, zorder=2)
    _zero(ax, t, 'x')
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r['step'] for r in rows])
    for lab in ax.get_yticklabels():
        lab.set_color(t['ink'])
    ax.set_ylim(len(rows) - 0.4, -0.6)
    vals = [r['a'] for r in rows] + [r['b'] for r in rows] + [0]
    span = max(vals) - min(vals)
    ax.set_xlim(min(vals) - 0.17 * span, max(vals) + 0.17 * span)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fmt(float(v), '+,.0')))
    ax.set_xlabel('$ thousands')
    ax.grid(axis='y', visible=False)
    fig.subplots_adjust(left=0.235, right=0.99, top=0.98, bottom=0.36 / (0.38 + 0.2 * len(rows)))
    return fig


def fig_anatomy(dev, t, plt):
    """Net P&L of the trades by exit, side and |z| at entry; each panel on its own scale."""
    T = dev['trades']
    panels = [('By exit', T['by_exit']), ('By side of the spread', T['by_side']), ('By |z| at entry', T['by_z'])]
    nmax = max(len(gs) for _, gs in panels)
    fig, axes = plt.subplots(1, 3, figsize=(FULL, 0.66 + 0.2 * nmax))
    for ax, (title, gs) in zip(axes, panels):
        vals = [g['net_usd'] / 1e6 for g in gs]
        ext = max(abs(v) for v in vals) or 1.0
        for i, v in enumerate(vals):
            ax.barh(i, v, height=0.6, color=t['pos'] if v >= 0 else t['neg'], zorder=3)
            # right of the bar, or of zero for a loss: never beside the category label
            ax.annotate(f"{fmt(v, '+.2')}M", (max(v, 0.0), i), xytext=(3, 0), textcoords='offset points',
                        va='center', ha='left', fontsize=6.4, color=t['ink-2'])
        _zero(ax, t, 'x')
        ax.set_yticks(range(len(gs)))
        ax.set_yticklabels([f"{g['label']} ({g['n']})" for g in gs])
        for lab in ax.get_yticklabels():
            lab.set_color(t['ink'])
        ax.set_ylim(nmax - 0.5, -0.6)
        neg = max([-v for v in vals if v < 0] + [0.0])
        pos = max([v for v in vals if v > 0] + [0.0])
        ax.set_xlim(-1.08 * neg - 0.02 * ext, pos + 0.95 * ext)
        ax.xaxis.set_major_locator(plt.MaxNLocator(3))
        ax.set_title(title + ' (trades)', fontsize=7, color=t['ink'])
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 0 if abs(v - round(v)) < 1e-9 else 1)))
        ax.set_xlabel('$ millions, net')
        ax.grid(axis='y', visible=False)
    fig.subplots_adjust(left=0.13, right=0.995, top=0.86, bottom=0.25, wspace=0.78)
    return fig


def fig_schedules(dev, t, plt):
    C = dev['cost_schedules']
    dates = dev['daily']['dates']
    allv = [v for s in C for v in s['cum']] + [0.0]
    span = max(allv) - min(allv)
    yl = (min(allv) - 0.08 * span, max(allv) + 0.08 * span)
    fig, axes = plt.subplots(1, len(C), figsize=(FULL, 1.5), sharey=True)
    for ax, s in zip(np.atleast_1d(axes), C):
        x = _dates(s.get('dates') or dates)
        _zero(ax, t)
        ax.plot(x, s['cum'], color=t['series-1'], lw=1.0)
        ax.plot([x[-1]], [s['cum'][-1]], marker='o', markersize=3, color=t['series-1'], markeredgecolor='white',
                markeredgewidth=0.7)
        title = f"Schedule {s['id']}: {fmt(s['ret_pct'], '+.2%')}"
        if s.get('gross_pct') is not None:
            title += f"\ngross {fmt(s['gross_pct'], '+.2%')}"
        ax.set_title(title, fontsize=7, color=t['ink'], linespacing=1.15)
        ax.set_ylim(*yl)
        import matplotlib.dates as mdates
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
        ax.yaxis.set_major_locator(plt.MaxNLocator(4, integer=True))
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 0)))
        ax.margins(x=0.02)
    fig.subplots_adjust(left=0.06, right=0.975, top=0.76, bottom=0.15, wspace=0.14)
    return fig


def _dotplot(ax, rows, t, label_key='label', tlabel=True):
    for i, r in enumerate(rows):
        c = r.get('color', t['series-1'])
        ax.plot([r['lo'], r['hi']], [i, i], color=c, lw=1.4, solid_capstyle='butt', zorder=3)
        ax.plot([r['v']], [i], marker='o', markersize=4.2, color=c, markeredgecolor='white', markeredgewidth=0.9,
                zorder=4)
        if tlabel and r.get('t') is not None:
            ax.annotate(f"t = {fmt(r['t'], '.2')}", (r['hi'], i), xytext=(4, 0), textcoords='offset points',
                        va='center', fontsize=6.6, color=t['ink-2'])
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[label_key] for r in rows])
    for lab in ax.get_yticklabels():
        lab.set_color(t['ink'])
    ax.set_ylim(len(rows) - 0.5, -0.5)
    ax.grid(axis='y', visible=False)


def fig_factors(dev, t, plt):
    """Factor loadings with 95% intervals: one row per factor, main backtest and walk-forward side by side."""
    from matplotlib.lines import Line2D
    F = dev['factors']
    series = list(dict.fromkeys(r['series'] for r in F['rows']))
    names = list(dict.fromkeys(r['name'] for r in F['rows']))
    colors = [t['series-1'], t['series-2']]
    if len(names) == 1:                 # the sector-ETF proxy only: a half-width exhibit
        fig, ax = plt.subplots(figsize=(HALF, PAIR_HEIGHT))
    else:
        fig, ax = plt.subplots(figsize=(FULL, 0.5 + 0.24 * len(names)))
    off = {s: (k - (len(series) - 1) / 2) * 0.26 for k, s in enumerate(series)}
    for r in F['rows']:
        i = names.index(r['name']) + off[r['series']]
        c = colors[series.index(r['series']) % 2]
        ax.plot([r['lo'], r['hi']], [i, i], color=c, lw=1.3, solid_capstyle='butt', zorder=3)
        ax.plot([r['beta']], [i], marker='o', markersize=3.8, color=c, markeredgecolor='white', markeredgewidth=0.8,
                zorder=4)
    _zero(ax, t, 'x')
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names)
    for lab in ax.get_yticklabels():
        lab.set_color(t['ink'])
    ax.set_ylim(len(names) - 0.5, -0.6)
    lo = min([r['lo'] for r in F['rows']] + [0])
    hi = max([r['hi'] for r in F['rows']] + [0])
    pad = 0.22 * (hi - lo)
    ax.set_xlim(lo - pad, hi + pad)
    if len(names) > 1:          # Newey-West t of each loading, main backtest / walk-forward
        for k, name in enumerate(names):
            ts = [next((r['t'] for r in F['rows'] if r['name'] == name and r['series'] == s_), None) for s_ in series]
            ax.annotate(' / '.join(fmt(x, '.2') if x is not None else '—' for x in ts), (1.0, k),
                        xycoords=('axes fraction', 'data'), xytext=(6, 0), textcoords='offset points', va='center',
                        ha='left', fontsize=6.6, color=t['ink-2'])
        ax.annotate('Newey–West t,\nmain / walk-forward', (1.0, -0.62), xycoords=('axes fraction', 'data'),
                    xytext=(6, 0), textcoords='offset points', va='bottom', ha='left', fontsize=6.2,
                    color=t['ink-3'], linespacing=1.0)
    ax.xaxis.set_major_locator(plt.MaxNLocator(6, steps=[1, 2, 2.5, 5, 10]))
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fmt(v, '+.2') if abs(v) > 1e-12 else '0'))
    ax.set_xlabel('Loading on the daily factor return (95% interval, Newey–West)')
    ax.grid(axis='y', visible=False)
    if len(series) > 1:
        _legend(ax, [Line2D([], [], color=colors[k % 2], lw=1.3, marker='o', markersize=3.8,
                            label=_wf_label(s)) for k, s in enumerate(series)], t, anchor=(0, 1.0))
    if len(names) == 1:
        fig.subplots_adjust(left=0.3, right=0.985, top=0.95, bottom=0.25)
    else:
        h = 0.5 + 0.24 * len(names)
        fig.subplots_adjust(left=0.17, right=0.83, top=1 - 0.22 / h, bottom=0.4 / h)
    return fig


def fig_distribution(dev, t, plt):
    bp = np.asarray(dev['daily']['net'], dtype=float) * 100
    lo, hi = math.floor(bp.min() / 5) * 5, math.ceil(bp.max() / 5) * 5
    bins = np.arange(lo - 1.25, hi + 2.5, 2.5)
    fig, ax = plt.subplots(figsize=(FULL, 1.45))
    ax.hist(bp, bins=bins, color=t['series-1'], alpha=0.8, rwidth=0.92, zorder=2)
    _zero(ax, t)
    ax.set_xlabel('Daily net return, bp of capital')
    ax.set_ylabel('Days')
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 0)))
    ax.grid(axis='x', visible=False)
    fig.subplots_adjust(left=0.075, right=0.99, top=0.95, bottom=0.27)
    return fig


def fig_funnel(dev, t, plt):
    F = dev['funnel']
    ramp = [t['ord-1'], t['ord-2'], t['ord-3'], t['ord-4'], t['ord-4']]
    rows = F['pairs']
    fig, ax = plt.subplots(figsize=(FULL, 0.42 + 0.3 * len(rows)))
    # log scale: the last stage (100 pairs) is a hairline on a linear axis to 35,000
    for i, r in enumerate(rows):
        # the pairs traded across all formations are not a share of the first formation's stages
        ax.barh(i, r['n'], height=0.5, color=t['neutral-series'] if r.get('separate') else ramp[min(i, len(ramp) - 1)],
                zorder=3)
        count = fmt(r['n'], ',.0')
        ax.annotate(count, (r['n'], i), xytext=(3, 0), textcoords='offset points', va='center',
                    fontsize=6.8, color=t['ink'], fontweight='semibold')
        if r.get('expected'):
            # the chance tick, labelled directly in the gap below its bar
            ax.plot([r['expected']] * 2, [i - 0.36, i + 0.36], color=t['ink'], lw=1.3, zorder=4)
            ax.annotate(f"{fmt(r['expected'], ',.0')} expected by chance", (r['expected'], i + 0.36),
                        xytext=(0, -0.5), textcoords='offset points', va='top', ha='center', fontsize=6.6,
                        color=t['ink-2'], zorder=5)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r['stage'] for r in rows])
    for lab in ax.get_yticklabels():
        lab.set_color(t['ink'])
    ax.set_ylim(len(rows) - 0.5, -0.5)
    ax.set_xscale('log')
    ax.set_xlim(min(r['n'] for r in rows) / 2.5, max(r['n'] for r in rows) * 2.2)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fmt(v, ',.0')))
    ax.set_xlabel('Pairs (log scale)')
    ax.grid(axis='y', visible=False)
    fig.subplots_adjust(left=0.25, right=0.99, top=0.97, bottom=0.4 / (0.42 + 0.3 * len(rows)) + 0.03)
    return fig


def fig_timeline(dev, study, t, plt, preregistered=False):
    run = dev['run']
    W = dev['walk_forward']['windows']
    cal = CALENDARS['dev']
    hold = study.get('holdout') or {}
    hold_start = hold.get('calendar_start')
    evaluated = hold.get('status') == 'complete'
    forms = _formations(dev)
    fig, ax = plt.subplots(figsize=(FULL, 1.45))
    prereg = 'pre-registered' if preregistered else 'pre-registration to be filed'
    re_forms = forms[1:]
    lanes = [('Formation', f'initial selection on data to {long_date(cal.selection_cutoff)}'
                           + (f'; re-formed at {word(len(re_forms))} dates, every '
                              f"{PROFILES[dev['run'].get('name', 'v33_dev').split('_')[0]].reselect_every} trading days "
                              '(ticks)' if re_forms else '')),
             ('Walk-forward', f"{len(W)} test windows from {long_date(W[0]['test_start'])}, one continuous simulation"),
             ('Main backtest', f"entries {long_date(run['period'][0])} to {long_date(run['period'][1])}"),
             ('Holdout', f"{long_date(hold_start)} to {long_date(hold['calendar_end'])}; pre-registered, then run "
                         'and evaluated' if evaluated else
                         f"from {long_date(hold_start)}; sealed, {prereg}" if hold_start else prereg)]
    h = 0.34
    form = _dates([run['data_span'][0], cal.selection_cutoff])
    ax.barh(0, form[1] - form[0], left=form[0], height=h, color=t['ord-2'])
    for d in _dates(re_forms):
        ax.plot([d, d], [-h * 0.75, h * 0.75], color=t['ink'], lw=1.1, solid_capstyle='butt')
    for w in W:
        a, b = _dates([w['test_start'], w['test_end']])
        ax.barh(1, (b - a) * 0.94, left=a, height=h, color=t['series-1'])
    mb = _dates(run['period'])
    ax.barh(2, mb[1] - mb[0], left=mb[0], height=h, color=t['ord-4'])
    first_year = int(run['data_span'][0][:4])
    last_year = int((hold_start or run['period'][1])[:4])
    x0, x1 = _dates([f'{first_year}-01-01', f'{last_year}-12-31'])
    if evaluated:           # the evaluated holdout's calendar, as the evaluation records it
        hs, he = _dates([hold_start, hold['calendar_end']])
        ax.barh(3, he - hs, left=hs, height=h * 0.8, color=t['series-3'])
    elif hold_start:        # the holdout's last day is fixed by the calendar holdout2026
        hs, he = _dates([hold_start, CALENDARS['holdout2026'].data_end])
        ax.barh(3, he - hs, left=hs, height=h * 0.8, color='white', edgecolor=t['series-3'], hatch='////', lw=0.7)
    for i, (name, desc) in enumerate(lanes):
        ax.annotate(name, (0, i), xycoords=('axes fraction', 'data'), xytext=(0, 7.5), textcoords='offset points',
                    fontsize=7, fontweight='semibold', color=t['ink'], va='bottom')
        ax.annotate(desc, (0, i), xycoords=('axes fraction', 'data'), xytext=(62, 7.5), textcoords='offset points',
                    fontsize=6.7, color=t['ink-2'], va='bottom')
    ax.set_xlim(x0 - 25, x1 + 25)
    ax.set_ylim(3.45, -0.9)
    ax.set_yticks([])
    ax.grid(False)
    ax.set_xticks(_dates([f'{y}-01-01' for y in range(first_year, last_year + 1)]))
    import matplotlib.dates as mdates
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.spines['bottom'].set_color(t['axis'])
    fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.14)
    return fig


def fig_snapshots(snaps, t, plt):
    if not snaps:
        return None
    rows = snaps['rows']
    x = _dates([r['period'] for r in rows])
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(FULL, 1.75))
    w = 55
    ax.bar(x, [r['mapped'] for r in rows], width=w, color=t['series-1'], zorder=3, label='Mapped to a ticker')
    ax.bar(x, [r['equity'] - r['mapped'] for r in rows], bottom=[r['mapped'] for r in rows], width=w,
           color=t['neutral-series'], alpha=0.55, zorder=3, label='No usable ticker')
    ax.set_title('Equity holdings per snapshot', fontsize=7, color=t['ink'], pad=13)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fmt(v, ',.0')))
    _legend(ax, ax.get_legend_handles_labels()[0], t, anchor=(0, 0.99))
    _year_axis(ax, minor=False)
    ax.grid(axis='x', visible=False)
    ax2.bar(x, [r['unmapped_weight_pct'] for r in rows], width=w, color=t['neutral-series'], zorder=3)
    ax2.set_title('Index weight without a usable ticker, %', fontsize=7, color=t['ink'], pad=13)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fmt(v, '.1')))
    _year_axis(ax2, minor=False)
    ax2.grid(axis='x', visible=False)
    fig.subplots_adjust(left=0.065, right=0.99, top=0.8, bottom=0.13, wspace=0.18)
    return fig


def fig_universe(dev, t, plt):
    U = dev.get('universe_by_formation')
    if not U:
        return None
    labels = [short_date(u['formation_date']) for u in U]
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(FULL, 0.62 + 0.21 * len(U)), sharey=True)
    for i, u in enumerate(U):
        ax.barh(i, u['with_prices'], height=0.6, color=t['series-1'], zorder=3)
        ax.barh(i, u['missing'], left=u['with_prices'], height=0.6, color=t['neutral-series'], alpha=0.55, zorder=3)
        ax.annotate(f"{fmt(u['missing'], '.0')} of {fmt(u['members'], ',.0')} without prices", (u['members'], i),
                    xytext=(3, 0), textcoords='offset points', va='center', fontsize=6.3, color=t['ink-2'],
                    bbox={'boxstyle': 'square,pad=0.1', 'fc': 'white', 'ec': 'none'})
        miss, unm = u['missing_weight_pct'] or 0.0, u['unmapped_weight_pct'] or 0.0
        ax2.barh(i, miss, height=0.6, color=t['neutral-series'], zorder=3)
        ax2.barh(i, unm, left=miss, height=0.6, color=t['neutral-series'], alpha=0.45, zorder=3)
        ax2.annotate(fmt(miss + unm, '.2%'), (miss + unm, i), xytext=(3, 0), textcoords='offset points',
                     va='center', fontsize=6.4, color=t['ink-2'])
    ax.set_yticks(range(len(U)))
    ax.set_yticklabels(labels)
    for lab in ax.get_yticklabels():
        lab.set_color(t['ink'])
    ax.set_ylim(len(U) - 0.5, -0.5)
    ax.set_xlim(0, max(u['members'] for u in U) * 1.55)
    ax2.set_xlim(0, max((u['missing_weight_pct'] or 0) + (u['unmapped_weight_pct'] or 0) for u in U) * 1.3)
    ax.set_title('Index members at each formation, with and without price history', fontsize=7, color=t['ink'])
    ax2.set_title('Index weight without price history or a usable ticker, %', fontsize=7, color=t['ink'])
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fmt(v, ',.0')))
    ax.xaxis.set_major_locator(plt.MaxNLocator(4))
    ax2.xaxis.set_major_locator(plt.MultipleLocator(1))
    ax2.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fmt(float(v), '.0')))
    for a in (ax, ax2):
        a.grid(axis='y', visible=False)
    h = 0.62 + 0.21 * len(U)
    fig.subplots_adjust(left=0.1, right=0.98, top=1 - 0.2 / h, bottom=0.25 / h, wspace=0.1)
    return fig


def fig_costcurve(dev, t, plt, width=HALF):
    C = dev.get('cost_curve')
    if not C:
        return None
    fig, ax = plt.subplots(figsize=(width, PAIR_HEIGHT))
    k = [r['k'] for r in C]
    s = [r['sharpe'] for r in C]
    ax.plot(k, s, color=t['series-1'], lw=1.2, marker='o', markersize=3, markeredgecolor='white', markeredgewidth=0.6,
            zorder=3)
    _zero(ax, t)
    ax.axvline(1.0, color=t['ink-3'], lw=0.6)
    lo, hi = min(s + [0]), max(s + [0])
    pad = 0.18 * (hi - lo)
    ax.set_ylim(lo - pad, hi + pad)
    ax.annotate('modelled costs', (1.0, hi + pad), xytext=(3, -2), textcoords='offset points', va='top',
                fontsize=6.4, color=t['ink-2'])
    for i in range(1, len(C)):
        if (s[i - 1] >= 0) != (s[i] >= 0):
            be = k[i - 1] + (k[i] - k[i - 1]) * s[i - 1] / (s[i - 1] - s[i])
            ax.plot([be], [0], marker='o', markersize=4, markerfacecolor='white', markeredgecolor=t['ink'],
                    markeredgewidth=0.9, zorder=4)
            ax.annotate(f"zero at {fmt(be, '.2')}×", (be, 0), xytext=(-4, -4), textcoords='offset points',
                        ha='right', va='top', fontsize=6.4, color=t['ink'])
    ax.annotate(fmt(s[0], '+.2'), (k[0], s[0]), xytext=(4, 2), textcoords='offset points', ha='left', va='bottom',
                fontsize=6.4, color=t['ink'])
    ax.annotate(fmt(s[-1], '+.2'), (k[-1], s[-1]), xytext=(-2, -4), textcoords='offset points', ha='right',
                va='top', fontsize=6.4, color=t['ink'])
    ax.set_xlabel('Multiple of modelled costs, trades held fixed')
    ax.set_ylabel('Net Sharpe ratio')
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fmt(v, '.1') + '×'))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 1)))
    ax.grid(axis='x', visible=False)
    fig.subplots_adjust(left=0.16, right=0.97, top=0.95, bottom=0.25)
    return fig


def fig_exitrace(dev, t, plt, width=HALF):
    E = dev.get('exit_race')
    if not E or not E.get('barrier_exits'):
        return None
    N = E.get('nulls') or {}
    n = E['targets'] + E['stops']
    rw = N.get('random_walk') or {'expected_targets': E['expected_targets']}
    rows = [('Observed', E['targets'], t['series-1']), ('Random-walk spread', rw['expected_targets'], t['neutral-series'])]
    if N.get('ou'):
        rows.append(('Reverting as selected', N['ou']['expected_targets'], t['neutral-series']))
    fig, ax = plt.subplots(figsize=(width, PAIR_HEIGHT))
    for i, (lab, v, c) in enumerate(rows):
        share = 100 * v / n
        ax.barh(i, share, height=0.56, color=c, zorder=3)
        ax.annotate(f"{fmt(share, '.1')}%  ({fmt(v, '.0' if i == 0 else '.1')})", (share, i), xytext=(3, 0),
                    textcoords='offset points', va='center', fontsize=6.4, color=t['ink'])
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows])
    for lab in ax.get_yticklabels():
        lab.set_color(t['ink'])
    ax.set_ylim(len(rows) - 0.45, -0.6)
    ax.set_xlim(0, 125)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel(f'Targets hit first, % of the {n} barrier exits')
    ax.grid(axis='y', visible=False)
    fig.subplots_adjust(left=0.37, right=0.97, top=0.95, bottom=0.25)
    return fig


def fig_decay(dev, t, plt, width=HALF):
    D = dev.get('decay')
    if not D:
        return None
    rows = [{'label': _DECAY_LABELS.get(r['period'], r['period']), 'v': r['bp'], 'lo': r['lo'], 'hi': r['hi'],
             'n': r['n']} for r in D]
    fig, ax = plt.subplots(figsize=(width, PAIR_HEIGHT))
    _dotplot(ax, rows, t, tlabel=False)
    for i, r in enumerate(rows):
        ax.annotate(f"{fmt(r['v'], '+.1')} bp, n = {fmt(r['n'], ',.0')}", (r['v'], i), xytext=(0, 5.5),
                    textcoords='offset points', ha='center', va='bottom', fontsize=6.3, color=t['ink'])
    _zero(ax, t, 'x')
    lo = min([r['lo'] for r in rows] + [0])
    hi = max([r['hi'] for r in rows] + [0])
    pad = 0.08 * (hi - lo)
    ax.set_xlim(lo - pad, hi + pad)
    ax.set_ylim(len(rows) - 0.45, -0.75)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 0)))
    ax.set_xlabel('Gross bp per trade (95% interval)')
    fig.subplots_adjust(left=0.29, right=0.97, top=0.95, bottom=0.25)
    return fig


def fig_persistence(dev, t, plt, width=HALF):
    Pd = dev.get('persistence')
    if not Pd or not Pd.get('windows'):
        return None
    W = Pd['windows']

    def tick(w):
        m_ = re.fullmatch(r'(\d{4})\D+(\d{4})', w['window'])
        return f"’{m_.group(1)[2:]}→’{m_.group(2)[2:]}" if m_ else 'Traded,\nafter'
    fig, ax = plt.subplots(figsize=(width, PAIR_HEIGHT))
    xs = list(range(len(W)))
    ax.bar(xs, [w['pct'] for w in W], width=0.62, color=t['series-1'], zorder=3)
    for x_, w in zip(xs, W):
        if w.get('base_pct') is not None:
            ax.plot([x_ - 0.36, x_ + 0.36], [w['base_pct']] * 2, color=t['ink'], lw=1.4, zorder=4,
                    solid_capstyle='butt')
    ax.axhline(Pd['chance_pct'], color=t['ink-3'], lw=0.8, ls=(0, (3, 2)), zorder=2)
    ymax = max([w['pct'] for w in W] + [w.get('base_pct') or 0 for w in W] + [Pd['chance_pct']]) * 1.25
    ax.set_ylim(0, ymax)
    ax.annotate(f"chance, {fmt(Pd['chance_pct'], '.0')}%", (len(W) - 0.5, Pd['chance_pct']), xytext=(0, 2),
                textcoords='offset points', ha='right', va='bottom', fontsize=6.3, color=t['ink-2'])
    ax.set_xticks(xs)
    ax.set_xticklabels([tick(w) for w in W], fontsize=6.4)
    ax.tick_params(axis='x', length=0)
    ax.set_ylabel('Still cointegrated, %')
    ax.grid(axis='x', visible=False)
    fig.subplots_adjust(left=0.14, right=0.98, top=0.95, bottom=0.25)
    return fig


def fig_capacity(dev, t, plt, width=HALF):
    from matplotlib.lines import Line2D
    C = dev.get('capacity')
    if not C:
        return None
    fig, ax = plt.subplots(figsize=(width, PAIR_HEIGHT))
    a = [r['aum_musd'] for r in C]
    ax.plot(a, [r['net_bp'] for r in C], color=t['series-1'], lw=1.2, marker='o', markersize=3,
            markeredgecolor='white', markeredgewidth=0.6, zorder=3)
    ax.plot(a, [-r['impact_bp'] for r in C], color=t['series-2'], lw=1.2, marker='o', markersize=3,
            markeredgecolor='white', markeredgewidth=0.6, zorder=3)
    _zero(ax, t)
    ax.set_xscale('log')
    ax.set_xlim(a[0] * 0.7, a[-1] * 1.4)
    ax.set_xticks(a)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f'${fmt(v / 1e3, ".0")}B' if v >= 1e3
                                                   else f'${fmt(v, ".0")}M'))
    ax.xaxis.set_minor_locator(plt.NullLocator())
    lo = min(min(r['net_bp'] for r in C), -max(r['impact_bp'] for r in C))
    ax.set_ylim(lo * 1.15, abs(lo) * 0.2)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 0)))
    ax.set_xlabel('Book size (log scale)')
    ax.set_ylabel('bp per trade')
    ax.grid(axis='x', visible=False)
    _legend(ax, [Line2D([], [], color=t['series-1'], lw=1.2, label='Net'),
                 Line2D([], [], color=t['series-2'], lw=1.2, label='Market impact (as a cost)')], t)
    fig.subplots_adjust(left=0.15, right=0.97, top=0.87, bottom=0.25)
    return fig


def fig_residual(dev, study, t, plt):
    """The second family against the pairs strategy: Sharpe intervals, net and gross, and the net paths."""
    R = study.get('residual')
    if not R or R.get('sharpe') is None:
        return None
    F = {r['key']: r for r in dev['forest']}
    arms = [('Avellaneda–Lee, net', R['sharpe'], R['lo'], R['hi'], t['series-3'], False)]
    if R.get('gross_sharpe') is not None:
        arms.append(('Avellaneda–Lee, gross', R['gross_sharpe'], R['gross_lo'], R['gross_hi'], t['series-3'], True))
    arms.append(('Pairs (v33), net', F['main']['sharpe'], F['main']['lo'], F['main']['hi'], t['series-1'], False))
    if 'gross' in F:
        arms.append(('Pairs (v33), gross', F['gross']['sharpe'], F['gross']['lo'], F['gross']['hi'], t['series-1'], True))
    paths = R.get('paths') or {}
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(FULL, 1.75), gridspec_kw={'width_ratios': [1.0, 1.15], 'wspace': 0.42})
    for i, (lab, v, lo, hi, c, gross) in enumerate(arms):
        ax.plot([lo, hi], [i, i], color=c, lw=1.4, solid_capstyle='butt', zorder=3)
        ax.plot([v], [i], marker='o', markersize=4.2, color=c, markerfacecolor='white' if gross else c,
                markeredgecolor=c if gross else 'white', markeredgewidth=1.1 if gross else 0.9, zorder=4)
    _zero(ax, t, 'x')
    ax.set_yticks(range(len(arms)))
    ax.set_yticklabels([a[0] for a in arms])
    for lab in ax.get_yticklabels():
        lab.set_color(t['ink'])
    ax.set_ylim(len(arms) - 0.5, -0.6)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 1)))
    ax.set_xlabel('Annualised Sharpe ratio (95% interval)')
    ax.grid(axis='y', visible=False)
    if paths.get('net'):
        dates = paths.get('dates') or dev['daily']['dates']
        x = _dates(dates)
        _zero(ax2, t)
        ax2.plot(_dates(dev['daily']['dates']), dev['daily']['cum'], color=t['series-1'], lw=1.1, zorder=3)
        ax2.plot(x, paths['net'], color=t['series-3'], lw=1.1, zorder=4)
        ends = sorted([(paths['net'][-1], 'Avellaneda–Lee ' + fmt(paths['net'][-1], '+.2%'), t['series-3']),
                       (dev['daily']['cum'][-1], 'Pairs ' + fmt(dev['daily']['cum'][-1], '+.2%'), t['series-1'])])
        span = max(max(paths['net']), max(dev['daily']['cum'])) - min(min(paths['net']), min(dev['daily']['cum']))
        ys = [e[0] for e in ends]
        if abs(ys[1] - ys[0]) < 0.14 * span:
            mid = (ys[0] + ys[1]) / 2
            ys = [mid - 0.07 * span, mid + 0.07 * span]
        for (y, text, c), ly in zip(ends, ys):
            _end_label(ax2, x[-1], y, text, c, t, label_y=ly)
        ax2.set_ylabel('Cumulative net return, %')
        ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 0)))
        _year_axis(ax2)
        ax2.margins(x=0)
    else:
        ax2.set_visible(False)
    fig.subplots_adjust(left=0.165, right=0.8, top=0.96, bottom=0.25)
    return fig


_HO_COLOURS = {'v33_pairs': 'series-1', 'avellaneda_lee': 'series-3', 'v32_pairs': 'neutral-series'}


def _apart(ys, gap):
    """Label heights for end labels at `ys`, at least `gap` apart, each as near its own value as
    that allows (in the order given)."""
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    out = [float(ys[i]) for i in order]
    for _ in range(100):
        moved = False
        for j in range(1, len(out)):
            if out[j] - out[j - 1] < gap - 1e-12:
                mid = (out[j] + out[j - 1]) / 2
                out[j - 1], out[j] = mid - gap / 2, mid + gap / 2
                moved = True
        if not moved:
            break
    res = [0.0] * len(ys)
    for k, i in enumerate(order):
        res[i] = out[k]
    return res


def _exact_tick(v, _=None):
    """A tick label that is the tick's value: as few decimals (0 to 2) as print it exactly, so a
    tick at 2.5 never prints as '+2' nor one at 0.25 as '+0.2'."""
    dp = next((d for d in (0, 1) if abs(v - round(v, d)) < 1e-9), 2)
    return _signed(v, dp)


def fig_holdout(study, ho, t, plt):
    """The evaluated holdout: each arm's net Sharpe ratio with its 95% interval, labelled with its
    Holm-adjusted p (S3: not tested), and the arms' cumulative net returns; an arm with no
    dispersion in its returns has no Sharpe ratio and is labelled so, not drawn at zero."""
    H = study.get('holdout') or {}
    if H.get('status') != 'complete' or ho is None:
        return None
    import matplotlib.dates as mdates
    arms = H['arms']
    cum = (H.get('daily') or {}).get('cum') or {}
    paths = [(a, ho[sid], cum[a['key']]) for a, (_, _, sid, _) in zip(arms, HOLDOUT_ARMS) if cum.get(a['key'])]
    if paths:
        fig, (ax, ax2) = plt.subplots(1, 2, figsize=(FULL, 1.9), gridspec_kw={'width_ratios': [1.0, 1.1], 'wspace': 0.5})
    else:
        fig, ax = plt.subplots(figsize=(FULL, 1.45))
        ax2 = None
    xs = [0.0]
    for i, (a, (_, _, sid, _)) in enumerate(zip(arms, HOLDOUT_ARMS)):
        c = t[_HO_COLOURS[a['key']]]
        if a['flat']:
            ax.plot([0], [i], marker='o', markersize=4.2, markerfacecolor='white', markeredgecolor=c,
                    markeredgewidth=1.0, zorder=4)
            ax.annotate(ho[sid]['sharpe_or'], (0, i), xytext=(6, 0), textcoords='offset points',
                        va='center', ha='left', fontsize=6.4, color=t['ink-2'])
            continue
        if a['lo'] is not None and a['hi'] is not None:
            ax.plot([a['lo'], a['hi']], [i, i], color=c, lw=1.4, solid_capstyle='butt', zorder=3)
            xs += [a['lo'], a['hi']]
        ax.plot([a['sharpe']], [i], marker='o', markersize=4.2, color=c, markeredgecolor='white', markeredgewidth=0.9,
                zorder=4)
        xs.append(a['sharpe'])
    _zero(ax, t, 'x')
    ax.set_yticks(range(len(arms)))
    ax.set_yticklabels([f"{h['label']} · {h['name']}\n"
                        + (f"Holm-adjusted p {h['p_holm_rel']}" if h['hyp'] else 'descriptive, not tested')
                        for h in (ho[sid] for _, _, sid, _ in HOLDOUT_ARMS)], linespacing=1.25)
    for lab in ax.get_yticklabels():
        lab.set_color(t['ink'])
    ax.set_ylim(len(arms) - 0.45, -0.55)
    lo, hi = min(xs), max(xs)
    if hi - lo < 1.0:                       # every arm flat, or a narrow spread: a readable scale
        lo, hi = min(lo, -1.0), max(hi, 1.0)
    pad = 0.08 * (hi - lo)
    lo, hi = lo - pad, hi + pad
    if any(a['flat'] for a in arms):        # room right of zero for the label of a flat arm
        hi = max(hi, -0.55 * lo)
    ax.set_xlim(lo, hi)
    ax.xaxis.set_major_locator(plt.MaxNLocator(5, steps=[1, 2, 2.5, 5, 10]))
    ax.xaxis.set_major_formatter(plt.FuncFormatter(_exact_tick))
    ax.set_xlabel('Annualised net Sharpe ratio (95% interval)')
    ax.grid(axis='y', visible=False)
    if ax2 is not None:
        x = _dates(H['daily']['dates'])
        _zero(ax2, t)
        allv = [0.0]
        ends = []
        for k, (a, h, v) in enumerate(paths):
            c = t[_HO_COLOURS[a['key']]]
            # S1 on top, as the site draws it: a flat path is not hidden under another arm's
            ax2.plot(x, v, color=c, lw=1.1, zorder=3 + len(paths) - k)
            allv += [min(v), max(v)]
            ends.append((v[-1], f"{h['label']} {fmt(v[-1], '+.2%', half_up=True)}", c))
        span = (max(allv) - min(allv)) or 1.0
        for (y, text, c), ly in zip(ends, _apart([e[0] for e in ends], 0.12 * span)):
            _end_label(ax2, x[-1], y, text, c, t, label_y=ly)
        ax2.set_ylim(min(allv) - 0.1 * span, max(allv) + 0.1 * span)
        ax2.set_ylabel('Cumulative net return, %')
        # decimal steps only, each tick labelled with the decimals it needs (never a rounded value)
        ax2.yaxis.set_major_locator(plt.MaxNLocator(5, steps=[1, 2, 5, 10]))
        ax2.yaxis.set_major_formatter(plt.FuncFormatter(_exact_tick))
        years = {d[:4] for d in H['daily']['dates']}
        ax2.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 3, 5, 7, 9, 11)))
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%b' if len(years) == 1 else '%b %Y'))
        if len(years) == 1:
            ax2.set_xlabel(next(iter(years)))
        ax2.margins(x=0)
        fig.subplots_adjust(left=0.2, right=0.87, top=0.96, bottom=0.24)
    else:
        fig.subplots_adjust(left=0.2, right=0.98, top=0.95, bottom=0.3)
    return fig


def fig_validation(study, t, plt):
    V = study.get('validation')
    if not V:
        return None
    rows = []
    for label, key, c in (('Planted cointegrated pairs', 'edge', t['series-1']),
                          ('Forced non-cointegrated pairs', 'forced_null', t['neutral-series'])):
        m_, se = V[key].get('mean_bp'), V[key].get('se_bp')
        if m_ is not None and se is not None:
            rows.append({'label': label, 'v': m_, 'lo': m_ - 1.96 * se, 'hi': m_ + 1.96 * se, 'color': c,
                         'text': f"{fmt(m_, '+.1')} bp (t = {fmt(V[key]['t'], '.1' if abs(V[key]['t']) >= 10 else '.2')})"})
    if not rows:
        return None
    fig, ax = plt.subplots(figsize=(FULL, 0.55 + 0.27 * len(rows)))
    _dotplot(ax, rows, t, tlabel=False)
    for i, r in enumerate(rows):
        ax.annotate(r['text'], (r['hi'], i), xytext=(5, 0), textcoords='offset points', va='center', fontsize=6.6,
                    color=t['ink'])
    _zero(ax, t, 'x')
    hi = max(r['hi'] for r in rows)
    ax.set_xlim(min(-0.05 * hi, min(r['lo'] for r in rows) - 0.05 * hi), hi * 1.3)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 0)))
    ax.set_xlabel('Pooled gross bp per trade (95% interval)')
    h = 0.55 + 0.27 * len(rows)
    fig.subplots_adjust(left=0.24, right=0.98, top=0.95, bottom=0.42 / h + 0.02)
    return fig


_STEP_LABELS = {'paper': 'Paper P&L at the signal closes', 'entry_delay': 'Entry delay to the fill',
                'exit_delay': 'Exit delay to the fill', 'gross': 'Gross P&L', 'bid_ask': 'Half-spread',
                'market_impact': 'Market impact', 'commission': 'Commission', 'borrow': 'Borrow',
                'financing': 'Financing', 'net': 'Net P&L'}


# The anatomy's labels say "out of sample" for data after formation; the note keeps that
# term for the 2026 holdout.
_DECAY_LABELS = {'Formation (in sample), same rule': 'Formation window', 'Out of sample, same rule': 'After formation',
                 'Engine trades': "The book's trades"}


def fig_halflife(dev, t, plt, width=HALF):
    H = dev.get('half_lives')
    if not H or not H.get('pairs'):
        return None
    cap, floor, mx = 400.0, 2.0, H.get('max_half_life') or 25.0
    pts = [p for p in H['pairs'] if p.get('f') is not None]
    inside = [(p['f'], max(p['o'], floor)) for p in pts if p['o'] is not None and p['o'] <= cap]
    beyond = [(p['f'], cap) for p in pts if p['o'] is None or p['o'] > cap]
    fig, ax = plt.subplots(figsize=(width, PAIR_HEIGHT))
    ax.set_yscale('log')
    diag = np.linspace(floor, mx + 1, 60)
    ax.plot(diag, diag, color=t['ink-3'], lw=0.7, zorder=2)
    ax.axhline(mx, color=t['ink-3'], lw=0.7, ls=(0, (3, 2)), zorder=2)
    if inside:
        ax.scatter(*zip(*inside), s=7, color=t['series-1'], alpha=0.75, lw=0, zorder=3)
    if beyond:
        ax.scatter(*zip(*beyond), s=11, marker='^', color=t['series-1'], lw=0, zorder=3)
    ax.set_xlim(0, mx + 1)
    ax.set_ylim(floor, cap * 1.5)
    ax.set_yticks([2, 5, 10, 25, 50, 100, 400])
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: fmt(float(v), '.0')))
    ax.yaxis.set_minor_locator(plt.NullLocator())
    ax.set_xlabel('Half-life at formation, trading days')
    ax.set_ylabel('After formation, days')
    fig.subplots_adjust(left=0.15, right=0.97, top=0.95, bottom=0.25)
    return fig


def fig_scenarios(dev, t, plt):
    """Net Sharpe under each declared scenario: the full re-run (filled) and the headline trades re-priced (open)."""
    from matplotlib.lines import Line2D
    C = dev.get('cost_sensitivity') or {}
    if not C.get('available'):
        return None
    rows = [(k, C['scenarios'][k]) for k in C['order'] if C['scenarios'][k]['full']['sharpe'] is not None]
    labels = {k: v.split(':')[0] if k == 'headline' else v for k, v in SCENARIO_LABELS.items()}
    labels['headline'] = 'Headline'
    n = len(rows)
    fig, ax = plt.subplots(figsize=(FULL, 0.62 + 0.2 * n))
    vals = [0.0]
    for i, (k, s) in enumerate(rows):
        full, fixed = s['full']['sharpe'], s['fixed'].get('sharpe')
        vals.append(full)
        if fixed is not None:
            vals.append(fixed)
            ax.plot([fixed, full], [i, i], color=t['rule-2'], lw=1.6, zorder=2, solid_capstyle='butt')
            ax.plot([fixed], [i], marker='o', markersize=4.4, markerfacecolor='white', markeredgecolor=t['series-1'],
                    markeredgewidth=1.1, zorder=4)
        ax.plot([full], [i], marker='o', markersize=4.4, color=t['series-1'], markeredgecolor='white',
                markeredgewidth=0.8, zorder=5)
        ax.annotate(str(s['full']['trades']), (1.0, i), xycoords=('axes fraction', 'data'), xytext=(4, 0),
                    textcoords='offset points', va='center', ha='left', fontsize=6.6, color=t['ink-2'])
    ax.annotate('trades,\nre-run', (1.0, -0.62), xycoords=('axes fraction', 'data'), xytext=(4, 0),
                textcoords='offset points', va='bottom', ha='left', fontsize=6.2, color=t['ink-3'], linespacing=1.0)
    _zero(ax, t, 'x')
    ax.set_yticks(range(n))
    ax.set_yticklabels([labels.get(k, s['label']) for k, s in rows])
    for lab in ax.get_yticklabels():
        lab.set_color(t['ink'])
    ax.set_ylim(n - 0.5, -0.7)
    pad = 0.06 * (max(vals) - min(vals))
    ax.set_xlim(min(vals) - pad, max(vals) + pad)
    ax.xaxis.set_major_locator(plt.MultipleLocator(0.25))
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: _signed(v, 2) if abs(v) > 1e-12 else '0'))
    ax.set_xlabel('Net Sharpe ratio, annualised')
    ax.grid(axis='y', visible=False)
    _legend(ax, [Line2D([], [], lw=0, marker='o', markersize=4.4, color=t['series-1'], markeredgecolor='white',
                        label='Full re-run (the trades change)'),
                 Line2D([], [], lw=0, marker='o', markersize=4.4, markerfacecolor='white',
                        markeredgecolor=t['series-1'], label='Headline trades re-priced')], t, anchor=(0, 1.0))
    h = 0.62 + 0.2 * n
    fig.subplots_adjust(left=0.16, right=0.93, top=1 - 0.22 / h, bottom=0.42 / h)
    return fig


def figures(data, tokens):
    """{name: svg text or None}. None: the data for that exhibit do not exist yet."""
    plt = _mpl(tokens)
    study = data['study']
    dev = study['dev']
    power = {'ucb': dev['facts']['sharpe_ucb'], 'mde': dev['facts']['sharpe_mde']}
    makers = {
        'equity': lambda: fig_equity(dev, tokens, plt),
        'walkforward': lambda: fig_walkforward(dev, tokens, plt),
        'monthly': lambda: fig_monthly(dev, tokens, plt),
        'rolling': lambda: fig_rolling(dev, tokens, plt),
        'forest': lambda: fig_forest(dev, study, power, tokens, plt),
        'randomnull': lambda: fig_randomnull(dev, tokens, plt),
        'dsr': lambda: fig_dsr(dev, tokens, plt, width=FULL if (dev.get('snooping') or {}).get('results') else HALF),
        'waterfall': lambda: fig_waterfall(dev, tokens, plt),
        'anatomy': lambda: fig_anatomy(dev, tokens, plt),
        'exitrace': lambda: fig_exitrace(dev, tokens, plt),
        'decay': lambda: fig_decay(dev, tokens, plt),
        'persistence': lambda: fig_persistence(dev, tokens, plt),
        'halflife': lambda: fig_halflife(dev, tokens, plt),
        'scenarios': lambda: fig_scenarios(dev, tokens, plt),
        'costcurve': lambda: fig_costcurve(dev, tokens, plt),
        'capacity': lambda: fig_capacity(dev, tokens, plt),
        'schedules': lambda: fig_schedules(dev, tokens, plt) if dev.get('cost_schedules') else None,
        'factors': lambda: fig_factors(dev, tokens, plt),
        'distribution': lambda: fig_distribution(dev, tokens, plt),
        'funnel': lambda: fig_funnel(dev, tokens, plt),
        'timeline': lambda: fig_timeline(dev, study, tokens, plt, data['paper']['prereg_status'] == 'filed'),
        'snapshots': lambda: fig_snapshots(universe_snapshots(data['_universe_index']), tokens, plt),
        'universe': lambda: fig_universe(dev, tokens, plt),
        'residual': lambda: fig_residual(dev, study, tokens, plt),
        'holdout': lambda: fig_holdout(study, data['paper'].get('ho'), tokens, plt),
        'validation': lambda: fig_validation(study, tokens, plt),
    }
    out = {}
    for name, make in makers.items():
        fig = make()
        out[name] = _svg(fig) if fig is not None else None
    return out


# Why each exhibit without data is pending (printed in its place).
_RUN = 'Pending: the development run.'
_ANATOMY = 'Pending: the evidence layer (anatomy.json).'
FIGURE_PENDING = {
    'universe': _RUN, 'costcurve': _RUN, 'exitrace': _ANATOMY, 'decay': _ANATOMY, 'persistence': _ANATOMY,
    'halflife': _ANATOMY, 'capacity': _ANATOMY, 'scenarios': 'Pending: the cost-scenario re-runs.',
    'residual': 'Pending: the residual arm.', 'holdout': 'Sealed.', 'validation': 'Pending: committed validation run.',
    'snapshots': 'Pending: point-in-time universe index.', 'schedules': 'Pending: cost-schedule replay.',
}

# Results the study will add. While one is absent its exhibit or table is left out of the
# body and the note lists it here instead: (key, analysis, what it will show, what it awaits).
# The key is a figure name, or a flag for results that are not a figure of their own.
_DEV = 'The development run and its evidence layer'
FORTHCOMING = (
    ('validation', 'Known-answer validation',
     'The engine and its full cost model on synthetic markets with a known answer: the gross edge on planted '
     'cointegrated pairs, no edge on forced non-cointegrated pairs, the hedge-ratio error and pair-selection recall',
     'A committed validation run'),
    ('universe', 'Point-in-time universe coverage',
     'Index members with and without price history at each formation date, and the index weight the price data '
     'do not cover: the survivorship gap', _DEV),
    ('snooping', 'Data-snooping tests',
     "White's Reality Check, Hansen's SPA test, the Romano–Wolf stepdown, the model confidence set and the "
     'probability of backtest overfitting over the declared family ({grid}-point grid, {toggles} toggles), '
     'whatever they show; the design is not re-chosen from them',
     "The family's run on the development calendar, in progress"),
    ('scenarios', 'Cost and capacity scenarios',
     'Each declared cost and capacity scenario re-run in full, beside the headline trades re-priced', _DEV),
    ('costcurve', 'Cost sensitivity',
     'Net Sharpe ratio from 0× to 2× modelled costs with the trades held fixed', _DEV),
    ('exitrace', 'Exit race',
     'Targets against stops, compared with the count expected for a spread that does not mean-revert', _DEV),
    ('decay', 'Decay from formation to trading',
     'Gross return per trade of the same rule on the same pairs, formation period against trading period', _DEV),
    ('persistence', 'Persistence of cointegration',
     "The share of cointegrated pairs still cointegrated a year later, against the next year's base rate", _DEV),
    ('halflife', 'Half-lives after formation',
     "Each traded pair's spread half-life on its formation window and after formation", _DEV),
    ('capacity', 'Capacity',
     'Net and impact cost per trade when the same trades are re-priced at other book sizes', _DEV),
    ('multi_factor', 'Multi-factor attribution',
     'Loadings on the five Fama–French factors, momentum and short- and long-term reversal, with Newey–West '
     'errors', _DEV),
    ('random_band', 'Random-pair band',
     "Each day's quantiles of the random-pair draws' cumulative returns, drawn around the equity curve", _DEV),
    ('residual', 'Avellaneda–Lee residual reversion',
     "The second strategy family's development-period net and gross Sharpe ratios, beside the pairs strategy",
     'Its run on the development calendar'),
    ('holdout', 'The 2026 holdout',
     "Each arm's net Sharpe ratio, one-sided upper bound, Holm-adjusted p-value and decision (S1 and S2; S3 "
     'descriptive), and its cumulative return',
     'The pre-registration, filed before any 2026 daily price is fetched, then a single run of each arm on 2026 data'),
)


def forthcoming(figs, flags_, m):
    """[[key, analysis, what it will show, what it awaits]] for every result still absent."""
    present = {k: v is not None for k, v in figs.items()}
    present.update({'snooping': flags_['snooping'], 'multi_factor': flags_['multi_factor'],
                    'random_band': flags_['random_band'], 'validation': flags_['validation']})
    fill = {'grid': m['study.dev.snooping.grid_points'], 'toggles': m['study.dev.snooping.toggles']}
    return [[key, what, shows.format(**fill), awaits] for key, what, shows, awaits in FORTHCOMING
            if not present[key]]


def concordance(site, figs, later):
    """The site's exhibits and where each one is in the paper: [site n, site title, target].

    target: the paper's label ('ex-<name>'), 'forthcoming' for a result the paper lists as
    forthcoming, or None for one it does not show.
    """
    if not site:
        return None
    out = []
    for e in site:
        name = e['name']
        if name in ('pipeline', 'timeline') or figs.get(name) is not None:
            target = 'ex-' + name
        elif name in later:
            target = 'forthcoming'
        else:
            target = None
        out.append([e['n'], e['title'], target])
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Assembly
# ──────────────────────────────────────────────────────────────────────────────

def build_data(inp):
    """(paper_data dict, {figure name: svg or None})."""
    study, head = inp['study'], inp['headline']
    if study.get('schema') != 1:
        raise PaperDataError(f"assets/study.json has schema {study.get('schema')!r}; the paper reads schema 1")
    unknown = sorted((set(study) - KNOWN_STUDY) | (set(study['dev']) - KNOWN_DEV))
    if unknown:
        raise PaperDataError(f'assets/study.json has sections the paper does not print yet: {unknown}')
    if 'study' in head or 'paper' in head:
        raise PaperDataError('the headline JSON has a top-level study/paper key')
    data = {**head, 'study': study, '_universe_index': inp['universe_index'], '_declaration': inp['declaration'],
            '_headline_path': inp['headline_path'], '_study_sha256': inp['study_sha256'],
            '_universe_index_sha256': inp['universe_index_sha256'],
            '_v32_universe_path': inp['v32_universe_path'], '_v32_universe_sha256': inp['v32_universe_sha256'],
            '_site_sha256': inp['site_sha256']}
    data['paper'] = derived(inp)
    m, why = format_metrics(data)
    tokens = site_tokens()
    figs = figures(data, tokens)
    missing = {k: FIGURE_PENDING[k] for k, v in figs.items() if v is None}
    unexplained = [k for k, v in figs.items() if v is None and k not in FIGURE_PENDING]
    if unexplained:
        raise PaperDataError(f'exhibits {unexplained} have no data and no pending reason')
    flags_ = flags(data)
    later = forthcoming(figs, flags_, m)
    paper = {
        'schema': SCHEMA,
        'meta': {'builder': 'scripts/build_paper.py', 'paper_date': data['paper']['paper_date'],
                 'commit': study['meta']['commit'], 'headline': inp['headline_path'],
                 'headline_sha256': study['meta']['headline_sha256'], 'study_sha256': inp['study_sha256'],
                 'universe_index_sha256': inp['universe_index_sha256'], 'run_dir': inp['results_path'].rsplit('/', 1)[0]},
        'layout': {'exhibit_width_mm': EXHIBIT_WIDTH_MM, 'measure_mm': MEASURE_MM, 'column_gap_mm': COLUMN_GAP_MM},
        'colors': tokens,
        'm': m,
        'why': why,
        'claims': {k: bool(v) for k, v in claims(data).items()},     # numpy comparisons give numpy bools
        'flags': flags_,
        'tables': tables(data, m),
        'figures': {k: (f'build/figures/{k}.svg' if v is not None else None) for k, v in sorted(figs.items())},
        'pending': dict(sorted(missing.items())),
        'forthcoming': later,
        'concordance': concordance(inp['site_exhibits'], figs, {row[0] for row in later}),
    }
    return paper, {k: v for k, v in figs.items() if v is not None}


def dumps(paper):
    return json.dumps(paper, ensure_ascii=False, indent=1, sort_keys=True, allow_nan=False) + '\n'


def _rel(path):
    """`path` relative to the repository when it lies inside it (for messages and keys)."""
    try:
        return pathlib.Path(path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return pathlib.Path(path).as_posix()


def compile_inputs(main=None, bib=None, data=None, figures=None):
    """The files the PDF depends on, by repository path (fonts, the Typst source, data, figures).
    A copy built with --out (write_copy) names its own files as the committed ones are named,
    'paper/...' relative to the copy, so its manifest records no path outside the repository."""
    main, bib, data, figures = main or MAIN, bib or BIB, data or DATA, figures or FIGURES
    files = [main, bib, data] + sorted(figures.glob('*.svg')) + sorted(FONTS.glob('*.ttf'))
    base = pathlib.Path(main).resolve().parent

    def name(p):
        p = pathlib.Path(p).resolve()
        if pathlib.Path(main) != MAIN and base in p.parents:
            return 'paper/' + p.relative_to(base).as_posix()
        return _rel(p)
    return {name(p): _sha256(p) for p in files if p.is_file()}


def pdf_timestamp(paper):
    d = dt.date.fromisoformat(paper['meta']['paper_date'])
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp())


def compile_pdf(paper, output=None, fmt_='pdf', ppi=None, main=None):
    """The compiled paper; `main` (default paper/main.typ) is compiled with its own directory's
    parent as the root, so a copy built into --out reads its own build/ directory."""
    import typst
    main = pathlib.Path(main) if main else MAIN
    kwargs = {'root': str(ROOT if main == MAIN else main.parent), 'font_paths': [str(FONTS)],
              'ignore_system_fonts': True, 'timestamp': pdf_timestamp(paper)}
    if fmt_ != 'pdf':
        kwargs.update(format=fmt_, ppi=ppi)
    return typst.compile(str(main), output=str(output) if output else None, **kwargs)


def _typst_version():
    try:
        import importlib.metadata
        return importlib.metadata.version('typst')
    except Exception:
        return None


def _mpl_version():
    import matplotlib
    return matplotlib.__version__


def _write_products(paper, figs, figures, data):
    figures.mkdir(parents=True, exist_ok=True)
    for old in figures.glob('*.svg'):
        if old.stem not in figs:
            old.unlink()
    for name, svg in figs.items():
        (figures / f'{name}.svg').write_text(svg, encoding='utf-8')
    data.write_text(dumps(paper), encoding='utf-8')


def write_copy(paper, figs, out):
    """A copy of the paper's source with these data and figures, in directory `out` outside the
    repository (out/main.typ, out/references.bib, out/build/): the main.typ to compile."""
    base = pathlib.Path(out).resolve()
    if base == ROOT.resolve() or ROOT.resolve() in base.parents or base in ROOT.resolve().parents:
        raise PaperDataError(f'--out {out} is in the repository: a paper from other inputs is built outside it')
    base.mkdir(parents=True, exist_ok=True)
    shutil.copy(MAIN, base / 'main.typ')
    shutil.copy(BIB, base / 'references.bib')
    _write_products(paper, figs, base / 'build' / 'figures', base / 'build' / 'paper_data.json')
    return base / 'main.typ'


def write_all(png_dir=None, out=None, study=None, results=None, holdout_calendar=HOLDOUT_CALENDAR):
    """Build the data, the figures and the PDF: the committed products by default; with `out`, a
    copy of main.typ and its products in that directory (write_copy; out/pairs_study.pdf), from
    the study file `study` and the results tree `results`."""
    inp = load_inputs(ROOT, study, results, holdout_calendar)
    paper, figs = build_data(inp)
    if out is None:
        main, figures, data, pdf_path, manifest_path = MAIN, FIGURES, DATA, PDF, MANIFEST
        _write_products(paper, figs, figures, data)
    else:
        main = write_copy(paper, figs, out)
        figures, data = main.parent / 'build' / 'figures', main.parent / 'build' / 'paper_data.json'
        pdf_path, manifest_path = main.parent / 'pairs_study.pdf', main.parent / 'build' / 'manifest.json'
    if _typst_version() is None:
        print('typst is not installed (pip install -e ".[paper]"): wrote the data and figures, not the PDF',
              file=sys.stderr)
        return 1
    pdf = compile_pdf(paper, main=main)
    pdf_path.write_bytes(pdf)
    manifest = {'inputs': compile_inputs(main, main.parent / 'references.bib', data, figures),
                'pdf_sha256': hashlib.sha256(pdf).hexdigest(),
                'tools': {'typst': _typst_version(), 'matplotlib': _mpl_version()}}
    manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    if png_dir:
        pngs = pathlib.Path(png_dir)
        pngs.mkdir(parents=True, exist_ok=True)
        for old in pngs.glob('page-*.png'):
            old.unlink()
        compile_pdf(paper, pngs / 'page-{p}.png', 'png', 110, main=main)
    print(f'wrote {_rel(data)}, {len(figs)} figures and {_rel(pdf_path)} '
          f'({len(pdf) / 1024:.0f} KB, paper date {paper["meta"]["paper_date"]})')
    return 0


def check():
    """0 if every committed product matches a fresh build of the current inputs, else 1."""
    problems = []
    inp = load_inputs()
    paper, figs = build_data(inp)
    text = dumps(paper)
    if not DATA.is_file() or DATA.read_text(encoding='utf-8') != text:
        problems.append(f'{_rel(DATA)} is stale')
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.is_file() else None
    if manifest is None:
        problems.append(f'{_rel(MANIFEST)} is missing')
    same_mpl = manifest is not None and manifest['tools'].get('matplotlib') == _mpl_version()
    committed = {p.stem for p in FIGURES.glob('*.svg')}
    if committed != set(figs):
        problems.append(f'figures differ: committed {sorted(committed ^ set(figs))} out of step with the data')
    elif same_mpl:
        for name, svg in figs.items():
            if (FIGURES / f'{name}.svg').read_text(encoding='utf-8') != svg:
                problems.append(f'{_rel(FIGURES / f"{name}.svg")} is stale')
    else:
        print('note: matplotlib differs from the one that drew the committed figures; '
              'figures checked against the manifest only')
    if manifest is not None:
        if manifest['inputs'] != compile_inputs():
            changed = sorted(set(manifest['inputs'].items()) ^ set(compile_inputs().items()))
            problems.append(f'the PDF was compiled from other inputs ({", ".join(sorted({c[0] for c in changed}))})')
        if not PDF.is_file() or _sha256(PDF) != manifest.get('pdf_sha256'):
            problems.append(f'{_rel(PDF)} is not the PDF the manifest records')
        elif _typst_version() is not None and _typst_version() == manifest['tools'].get('typst') and not problems:
            if compile_pdf(paper) != PDF.read_bytes():
                problems.append(f'{_rel(PDF)} differs from a fresh compile')
    for p in problems:
        print(f'STALE: {p}', file=sys.stderr)
    if problems:
        print('rebuild with: python scripts/build_paper.py', file=sys.stderr)
        return 1
    print(f'{_rel(DATA)}, {len(figs)} figures and {_rel(PDF)} are up to date')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--check', action='store_true', help='exit 1 if a committed product is stale')
    ap.add_argument('--png', metavar='DIR', help='also render every page to DIR/page-N.png (110 ppi)')
    ap.add_argument('--study', metavar='FILE', help='the site data to print (default assets/study.json); '
                    'needs --out')
    ap.add_argument('--results', metavar='DIR', help="where the study's results/... sources are read "
                    '(default results/); needs --out')
    ap.add_argument('--holdout-calendar', default=HOLDOUT_CALENDAR, metavar='NAME',
                    help=f'the calendar an evaluated holdout must be on (default {HOLDOUT_CALENDAR})')
    ap.add_argument('--out', metavar='DIR', help='build a copy of the paper into DIR instead of the committed '
                    'products (DIR/main.typ, DIR/build/, DIR/pairs_study.pdf)')
    args = ap.parse_args(argv)
    if args.check and (args.study or args.results or args.out or args.holdout_calendar != HOLDOUT_CALENDAR):
        ap.error('--check checks the committed products; it takes no --study, --results, --out or calendar')
    if (args.study or args.results or args.holdout_calendar != HOLDOUT_CALENDAR) and not args.out:
        ap.error('a paper from other inputs is built into --out DIR, never over the committed products')
    try:
        if args.check:
            return check()
        return write_all(args.png, args.out, args.study, args.results, args.holdout_calendar)
    except PaperDataError as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
