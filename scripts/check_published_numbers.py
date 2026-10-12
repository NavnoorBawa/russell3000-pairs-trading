#!/usr/bin/env python3
"""Fail when README.md / index.html publish a number that disagrees with the run.

The source of truth is outputs/headline_metrics.json, written by
pairs_trading.json_export.export_headline_metrics at the end of every run. Each
published headline number is wrapped in a marker that names its key in that file:

    README.md    <!--m:oos.pooled_sharpe-->−1.23<!--/m-->
    index.html   <td data-metric="oos.pooled_sharpe">−1.23</td>

Either syntax is accepted in either file (for data-metric the element's whole text
content is the value). KEY is a dotted path into the JSON; a list element is addressed
by its index, e.g. oos.window_returns_pct.0. For every marker:

  * the key must exist and hold a number (an unknown key, a null or a non-number fails);
  * the marker text must be a number — a Unicode minus (U+2212), a leading '+', a
    trailing '%' and thousands separators are accepted, surrounding whitespace ignored;
  * the JSON value, shown at the marker's own precision, must equal the marker text:
    '−1.23' matches any value within half a unit of the last shown digit of −1.23.

Every file must also carry a marker for each key in REQUIRED_KEYS (disable with
--allow-missing-markers while the docs are being re-marked). Markers inside Markdown
code spans / fenced code blocks are ignored, so the docs can show the syntax itself.

Exit codes: 0 every compared value matches; 1 at least one failure (mismatch, unknown
or non-numeric key, unparseable or unterminated marker, missing required marker); 2 the
JSON is missing (unless --allow-missing), unreadable or of an unsupported schema, or a
published file is missing.

v32: replaces a checker that scraped numbers out of a run log. It could not parse
signed numbers ('+2.780%' never matched `(-?[\\d.]+)`, so the Gatev headline was never
checked), matched integers as substrings (some '1' is on every page, so every count
"passed"), accepted a float found anywhere in either file, exited 0 with 'SKIP' when the
log was missing, and never looked at the significance, fund or benchmark tables.
"""

import argparse
import html
import json
import math
import pathlib
import re
import sys
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_JSON = ROOT / 'outputs' / 'headline_metrics.json'
DEFAULT_FILES = (ROOT / 'README.md', ROOT / 'index.html')
SUPPORTED_SCHEMA = 1

# Every published file must mark at least these headline numbers.
REQUIRED_KEYS = (
    'main.total_return_pct',
    'main.sharpe',
    'main.trades',
    'oos.avg_window_return_pct',
    'oos.pooled_sharpe',
    'oos.windows_positive',
    'oos.windows',
    'benchmarks.gatev.sharpe',
    'significance.oos_windows.p',
)

_COMMENT_MARKER = re.compile(r'<!--\s*m:(?P<key>[\w.\-]+?)\s*-->(?P<body>.*?)<!--\s*/m\s*-->', re.S)
_COMMENT_OPEN = re.compile(r'<!--\s*m:')
_NUMBER = re.compile(r'(?P<sign>[+-]?)(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<frac>\d+))?(?P<pct>%?)')
_FENCE = re.compile(r'^(?P<f>`{3,}|~{3,})[^\n]*\n.*?^(?P=f)[ \t]*$', re.M | re.S)
_INLINE_CODE = re.compile(r'(?P<t>`+)(?!`).+?(?<!`)(?P=t)(?!`)', re.S)
_VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta',
              'source', 'track', 'wbr'}


# ──────────────────────────────────────────────────────────────────────────────
# Parsing
# ──────────────────────────────────────────────────────────────────────────────

def parse_marker_value(text):
    """Marker text -> (value, decimals shown). Raises ValueError if it is not a number."""
    s = re.sub(r'\s', '', html.unescape(text)).replace('−', '-')
    m = _NUMBER.fullmatch(s)
    if not m:
        raise ValueError(f'not a number: {text.strip()!r}')
    frac = m['frac'] or ''
    value = float(f"{m['sign']}{m['int'].replace(',', '')}{'.' + frac if frac else ''}")
    return value, len(frac)


def resolve_key(data, key):
    """Value at a dotted path (dict keys, or list indices). Raises KeyError if absent."""
    cur = data
    for part in key.split('.'):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            raise KeyError(key)
    return cur


def matches(json_value, shown, decimals):
    """True if json_value, displayed with `decimals` places, can read as `shown`."""
    tol = 0.5 * 10.0 ** (-decimals) + 1e-9 * max(1.0, abs(json_value))
    return abs(json_value - shown) <= tol


def _mask(match):
    return re.sub(r'[^\n]', ' ', match.group(0))


def mask_markdown_code(text):
    """Blank out fenced blocks and inline code spans (line numbers are preserved)."""
    return _INLINE_CODE.sub(_mask, _FENCE.sub(_mask, text))


class _MetricParser(HTMLParser):
    """Collects (key, text content, line) for every element carrying data-metric."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.open, self.found, self.errors = [], [], []

    def handle_starttag(self, tag, attrs):
        for m in self.open:
            if m['tag'] == tag:
                m['depth'] += 1
        key = dict(attrs).get('data-metric')
        if key is None:
            return
        line = self.getpos()[0]
        if tag in _VOID_TAGS:
            self.found.append((key, '', line))
        else:
            self.open.append({'key': key, 'tag': tag, 'depth': 1, 'text': [], 'line': line})

    def handle_endtag(self, tag):
        still = []
        for m in self.open:
            if m['tag'] == tag:
                m['depth'] -= 1
                if m['depth'] == 0:
                    self.found.append((m['key'], ''.join(m['text']), m['line']))
                    continue
            still.append(m)
        self.open = still

    def handle_data(self, data):
        for m in self.open:
            m['text'].append(data)

    def close(self):
        super().close()
        for m in self.open:
            self.errors.append((m['line'], f"data-metric=\"{m['key']}\" <{m['tag']}> is never closed"))
        self.open = []


def extract_markers(text, is_markdown=False):
    """Return (markers, errors): markers = [(key, text, line)], errors = [(line, message)]."""
    if is_markdown:
        text = mask_markdown_code(text)
    markers, errors = [], []
    starts = set()
    for m in _COMMENT_MARKER.finditer(text):
        starts.add(m.start())
        markers.append((m['key'], m['body'], text.count('\n', 0, m.start()) + 1))
    for m in _COMMENT_OPEN.finditer(text):
        if m.start() not in starts:
            errors.append((text.count('\n', 0, m.start()) + 1,
                           'marker <!--m:...--> without a matching <!--/m--> (or nested)'))
    parser = _MetricParser()
    parser.feed(text)
    parser.close()
    markers.extend(parser.found)
    errors.extend(parser.errors)
    return sorted(markers, key=lambda x: x[2]), errors


# ──────────────────────────────────────────────────────────────────────────────
# Checking
# ──────────────────────────────────────────────────────────────────────────────

def check_text(data, text, name, required=REQUIRED_KEYS, allow_missing_markers=False,
               is_markdown=False):
    """Check one document. Returns (n_compared, failures, warnings, keys_seen)."""
    markers, errors = extract_markers(text, is_markdown=is_markdown)
    failures = [f'{name}:{line}: {msg}' for line, msg in errors]
    warnings = []
    compared = 0
    seen = set()
    for key, body, line in markers:
        where = f'{name}:{line}: {key}'
        seen.add(key)
        try:
            value = resolve_key(data, key)
        except KeyError:
            failures.append(f'{where}: unknown key (not in the headline JSON)')
            continue
        if value is None:
            failures.append(f'{where}: the JSON value is null (not available in this run); '
                            f'the page shows {body.strip()!r}')
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            failures.append(f'{where}: the JSON value is not a number ({value!r})')
            continue
        try:
            shown, decimals = parse_marker_value(body)
        except ValueError as e:
            failures.append(f'{where}: unparseable marker text — {e}')
            continue
        compared += 1
        if not matches(float(value), shown, decimals):
            failures.append(f'{where}: page shows {body.strip()!r}, JSON has {value!r} '
                            f'(= {float(value):.{decimals}f} at the shown precision)')
    missing = [k for k in required if k not in seen]
    if missing:
        msg = f'{name}: no marker for required key(s): {", ".join(missing)}'
        (warnings if allow_missing_markers else failures).append(msg)
    return compared, failures, warnings, seen


def _is_markdown(path):
    return path.suffix.lower() in ('.md', '.markdown')


def _display(path):
    try:
        return str(pathlib.Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--json', default=None, help='headline metrics JSON '
                    '(default: outputs/headline_metrics.json in the repository)')
    ap.add_argument('--files', nargs='+', default=None,
                    help='published files to check (default: README.md index.html)')
    ap.add_argument('--allow-missing', action='store_true',
                    help='exit 0 instead of 2 when the headline JSON does not exist yet')
    ap.add_argument('--allow-missing-markers', action='store_true',
                    help='report required keys without a marker as warnings, not failures')
    ap.add_argument('-v', '--verbose', action='store_true', help='list every marker found')
    args = ap.parse_args(argv)

    json_path = pathlib.Path(args.json) if args.json else DEFAULT_JSON
    files = [pathlib.Path(f) for f in args.files] if args.files else list(DEFAULT_FILES)

    if not json_path.exists():
        msg = (f'{_display(json_path)} not found — run `python -m pairs_trading.main` '
               f'(it writes the headline metrics) before checking the published numbers.')
        if args.allow_missing:
            print(f'SKIPPED (--allow-missing): {msg}')
            return 0
        print(f'ERROR: {msg}', file=sys.stderr)
        return 2
    try:
        data = json.loads(json_path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        print(f'ERROR: cannot read {_display(json_path)}: {e}', file=sys.stderr)
        return 2
    schema = data.get('schema') if isinstance(data, dict) else None
    if schema != SUPPORTED_SCHEMA:
        print(f'ERROR: {_display(json_path)} has schema {schema!r}; this checker understands '
              f'schema {SUPPORTED_SCHEMA}', file=sys.stderr)
        return 2

    rc = data.get('run_config') or {}
    commit = rc.get('git_commit')
    print(f'Headline metrics: {_display(json_path)} (version {data.get("version")}, run '
          f'{rc.get("run_timestamp_utc", "?")}, commit {commit[:12] if commit else "n/a"})')

    total, per_file, failures, warnings = 0, [], [], []
    for path in files:
        if not path.exists():
            print(f'ERROR: published file {_display(path)} not found', file=sys.stderr)
            return 2
        name = _display(path)
        text = path.read_text(encoding='utf-8', errors='replace')
        n, f, w, _ = check_text(data, text, name, allow_missing_markers=args.allow_missing_markers,
                                is_markdown=_is_markdown(path))
        if args.verbose:
            for key, body, line in extract_markers(text, is_markdown=_is_markdown(path))[0]:
                print(f'  {name}:{line}: {key} = {body.strip()!r}')
        total += n
        per_file.append(f'{name}: {n}')
        failures += f
        warnings += w

    for w in warnings:
        print(f'WARNING: {w}')
    for f in failures:
        print(f'FAIL: {f}')
    print(f'Compared {total} values ({", ".join(per_file)}); {len(failures)} failure(s).')
    if failures:
        print('Refresh the marked numbers in the published files (and og-image.png via '
              'scripts/make_og_image.py) from outputs/headline_metrics.json.')
        return 1
    if total == 0:
        print('WARNING: no marked values were compared.')
    else:
        print('OK: every marked value matches the headline metrics.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
