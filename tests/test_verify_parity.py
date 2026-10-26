"""assets/verify.js repeats scripts/check_published_numbers.py in the reader's browser.

The page's "Verify this number" card and its audit mode claim to apply the checker's own
rule, so the two must not drift apart. Read straight out of verify.js, and compared with
the Python module:

  * the number pattern is _NUMBER (named groups aside), matched against the whole text;
  * the whitespace class is exactly the characters Python's \\s matches (str.isspace);
  * the Unicode minus becomes '-' after the whitespace goes, and the text is unescaped first;
  * the tolerance expression, evaluated in Python, agrees with matches() on every vector,
    including boundaries where Math.pow(10, -dp) and Python's 10.0 ** -dp differ;
  * the file names, the 'study' namespace and the schema are the checker's.

Where Node is on the PATH the same vectors also run through verify.js itself (parsing,
rounding, key resolution and a whole marker check), and every marker of index.html is
checked by the JavaScript against the committed data, as CI checks it in Python.
"""

import html
import json
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))
import check_published_numbers as chk  # noqa: E402

JS_PATH = REPO / 'assets' / 'verify.js'
JS = JS_PATH.read_text(encoding='utf-8')


def _js_regex(name):
    m = re.search(rf'^\s*var {name} = /(.+)/(\w*);\s*$', JS, re.M)
    assert m, f'var {name} = /.../ not found in assets/verify.js'
    return m.group(1), m.group(2)


def _js_function(name):
    """(arguments, body) of a top-level function of verify.js, on one line or several."""
    m = (re.search(rf'^  function {name}\(([^)]*)\) \{{ (.*) \}}$', JS, re.M)
         or re.search(rf'^  function {name}\(([^)]*)\) \{{\n(.*?)\n  \}}$', JS, re.M | re.S))
    assert m, f'function {name} not found in assets/verify.js'
    return m.group(1), m.group(2)


def _js_code():
    """verify.js without its comments."""
    return re.sub(r'/\*.*?\*/|//[^\n]*', '', JS, flags=re.S)


def _js_string(name):
    m = re.search(rf"var {name} = '([^']*)';", JS)
    assert m, f'var {name} not found in assets/verify.js'
    return m.group(1)


# ── vectors ─────────────────────────────────────────────────────────────────

PARSE_TEXTS = [
    '\u22121.23', '-1.23', '+1.23', '1.23', '+2.780%', '\u22120.39%', '2.780 %', ' 1,234 ', '1,234',
    '1,234.5', '1,234,567.891', '12,34', '1,23,456', '1234', '0', '007', '\u22120.00', '+0', '-0',
    '1.', '.5', '1e5', '\u2212', '', '   ', 'abc', '%', '+-1', '\u2212\u22121', '1.2.3', '12%%', '%12',
    '1 234', '1\u00a0234', '1\u2009234', '1\u202f234', '\u3000-1.5', '1.5\x1c', '1.5\x85',
    '1.5\ufeff', '1.5\u200b', '\u2212 1.5', '+ 1.5 %', '1\n2', '\t42\r\n', '\u20131.5', '\u20141.5',
    '&minus;1.23', '&#8722;4', '&#x2212;4', '1&nbsp;234', '&amp;minus;1', '10,916', '2,999',
    '0.0000', '99.50', '+11.4', '1,000,000,000,000',
]

MATCH_CASES = [   # (stored value, text shown)
    (-1.2345, '\u22121.23'), (-1.235, '\u22121.24'), (-1.235, '\u22121.23'), (1.005, '1.00'),
    (1.005, '1.01'), (0.125, '0.12'), (0.125, '0.13'), (2.5, '2'), (2.5, '3'), (3.5, '3'),
    (100, '100'), (99.5, '100'), (99.4999, '100'), (1e12, '1,000,000,000,000'),
    (1e12 + 600, '1,000,000,000,000'), (1e12 + 1001, '1,000,000,000,000'), (-0.0, '\u22120.00'),
    (0.004999, '0.00'), (0.005, '0.00'), (0.0050000011, '0.00'), (0.39, '0.39%'),
    (-0.3895628, '\u22120.39%'), (213, '213'), (213, '214'), (7141, '7,141'), (0.0618, '+0.06'),
    (-0.0618, '+0.06'), (16.1317, '16.1'), (16.15, '16.1'), (16.15000002, '16.1'),
]
# boundaries where 0.5 * Math.pow(10, -dp) (V8: 10 ** -4 = 0.00009999999999999999) would
# disagree with Python's 0.5 * 10.0 ** -dp: the stored value sits exactly on Python's tolerance
for _dp in (4, 5, 17):
    _tol = 0.5 * 10.0 ** -_dp + 1e-9
    MATCH_CASES.append((_tol, '0.' + '0' * _dp))
    MATCH_CASES.append((-_tol, '0.' + '0' * _dp))

RESOLVE_DATA = {'a': {'b': [10, {'c': 3}], '0': 5, 'x-y': 1, 'n': None, 't': True, 's': 'str', 'z': 2.5}}
RESOLVE_KEYS = ['a.b.0', 'a.b.1.c', 'a.b.01.c', 'a.0', 'a.b.2', 'a.b.-1', 'a..b', 'a.x-y', 'a', '',
                'a.b.1e0', 'a.constructor', 'a.__proto__', 'a.b.length', 'a.toString', 'a.n', 'a.t',
                'a.s', 'a.z', 'a.z.0', 'a.s.0', 'b', 'a.b.1.c.d']

CHECK_SITE = {'dev': {'x': 1.234, 'list': [0.5, -2.25, None], 'flag': False, 'word': 'n/a', 'big': 10916}}
CHECK_HEADLINE = {'schema': 1, 'main': {'sharpe': -0.0618, 'trades': 213, 'ret_pct': -0.3895628}}
CHECK_MARKERS = [
    ('study.dev.x', '1.23'), ('study.dev.x', '1.2'), ('study.dev.x', '1.24'), ('study.dev.x', '+1.234'),
    ('study.dev.list.0', '0.5'), ('study.dev.list.1', '\u22122.25'), ('study.dev.list.1', '\u22122.3'),
    ('study.dev.list.1', '\u22122.2'), ('study.dev.list.2', '0'), ('study.dev.list.3', '0'),
    ('study.dev.flag', '0'), ('study.dev.word', '0'), ('study.dev.big', '10,916'), ('study.dev.big', '10916'),
    ('study.dev.big', '10,917'), ('study.dev', '1'), ('study', '1'), ('study.nope', '1'),
    ('main.sharpe', '\u22120.06'), ('main.sharpe', '-0.06'), ('main.sharpe', '\u22120.07'),
    ('main.trades', '213'), ('main.trades', '213.0'), ('main.ret_pct', '\u22120.39%'),
    ('main.ret_pct', '\u2014'), ('main.ret_pct', ''), ('main.nope', '1'), ('schema', '1'),
    ('main.sharpe', '&minus;0.06'),
]


def _py_parse(text):
    try:
        return list(chk.parse_marker_value(text))
    except ValueError:
        return None


def _py_resolve(key):
    try:
        return {'v': chk.resolve_key(RESOLVE_DATA, key)}
    except KeyError:
        return None


def _py_statuses(site, headline, markers):
    """ok/fail per marker, from check_text on a page of just those markers."""
    data = chk.with_site_data(headline, site)
    page = '\n'.join(f'<span data-metric="{html.escape(k)}">{html.escape(t)}</span>' for k, t in markers)
    _, failures, _, _ = chk.check_text(data, page, 'p', required=())
    bad = {int(f.split(':')[1]) for f in failures}
    return ['fail' if i + 1 in bad else 'ok' for i in range(len(markers))]


# ── read out of verify.js, compared in Python ───────────────────────────────

def test_number_pattern_is_the_checkers():
    body, flags = _js_regex('NUMBER')
    assert flags == ''
    assert body.startswith('^') and body.endswith('$'), 'the pattern must be anchored at both ends (fullmatch)'
    assert re.sub(r'\(\?<(\w+)>', r'(?P<\1>', body[1:-1]) == chk._NUMBER.pattern


def test_whitespace_class_is_pythons_backslash_s():
    body, flags = _js_regex('SPACE')
    assert flags == 'g' and body.startswith('[') and body.endswith(']')
    js_class = re.compile(body)            # the same escapes mean the same in Python's re
    py_space = re.compile(r'\s')
    differ = [hex(i) for i in range(0x10000)
              if bool(js_class.fullmatch(chr(i))) != bool(py_space.fullmatch(chr(i)))]
    assert not differ, f'verify.js treats these differently from Python\'s \\s: {differ}'
    assert not any(chr(i).isspace() for i in range(0x10000, 0x110000))


def test_text_is_unescaped_then_stripped_then_minus_replaced():
    args, body = _js_function('parseMarkerValue')
    assert args == 'text'
    assert "var s = htmlUnescape(String(text)).replace(SPACE, '').replace(/\\u2212/g, '-');" in body
    assert "Number(g.sign + g.int.replace(/,/g, '') + (frac ? '.' + frac : ''))" in body
    assert 'decimals: frac.length' in body


def _py_tolerance_from_js():
    """matches() as written in verify.js, evaluated in Python."""
    t_args, t_body = _js_function('tenToMinus')
    assert t_args == 'd' and t_body.strip() == "return Number('1e-' + d);", (
        'tenToMinus must parse the decimal 1e-d (correctly rounded, as Python 10.0 ** -d is); '
        'Math.pow(10, -d) is not, e.g. at d = 4')
    m_args, m_body = _js_function('matches')
    assert m_args == 'value, shown, decimals'
    tol = re.search(r'var tol = (.+);', m_body).group(1)
    ret = re.search(r'return (.+);', m_body).group(1)

    def to_py(expr):
        expr = expr.replace('Math.max', 'max').replace('Math.abs', 'abs')
        assert re.fullmatch(r'[\w\s.*+\-<=(),]+', expr), expr
        return expr

    tol_py, ret_py = to_py(tol), to_py(ret)

    def matches(value, shown, decimals):
        env = {'__builtins__': {}, 'max': max, 'abs': abs, 'value': float(value), 'shown': shown,
               'decimals': decimals, 'tenToMinus': lambda d: float(f'1e-{d}')}
        env['tol'] = eval(tol_py, env)      # noqa: S307 - our own file, a checked arithmetic expression
        return eval(ret_py, env)            # noqa: S307
    return matches


def test_tolerance_is_the_checkers():
    js_matches = _py_tolerance_from_js()
    for d in range(0, 40):
        assert float(f'1e-{d}') == 10.0 ** -d
    for value, text in MATCH_CASES:
        shown, dp = chk.parse_marker_value(text)
        assert js_matches(value, shown, dp) == chk.matches(float(value), shown, dp), (value, text)


def test_files_and_namespace_are_the_checkers():
    assert _js_string('HEADLINE_FILE') == chk.DEFAULT_JSON.relative_to(chk.ROOT).as_posix()
    assert _js_string('SITE_FILE') == chk.DEFAULT_SITE_JSON.relative_to(chk.ROOT).as_posix()
    assert _js_string('SITE_NAMESPACE') == chk.SITE_NAMESPACE
    assert re.search(rf'var SUPPORTED_SCHEMA = {chk.SUPPORTED_SCHEMA};', JS)
    assert 'Math.pow' not in _js_code()


def test_the_page_writes_its_numbers_in_ascii_digits():
    """JavaScript's \\d is ASCII; Python's also takes other scripts' digits. Equal on this page."""
    markers, errors = chk.extract_markers((REPO / 'index.html').read_text(encoding='utf-8'))
    assert not errors and markers
    odd = [(k, b) for k, b, _ in markers if any(ch.isdigit() and not ch.isascii() for ch in b)]
    assert not odd


# ── verify.js itself, under Node ────────────────────────────────────────────

NODE = shutil.which('node')
RUNNER = r"""
const core = require(process.argv[2]);
const input = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));
const out = {};
out.parse = input.parse.map(t => { try { const r = core.parseMarkerValue(t); return [r.value, r.decimals]; } catch (e) { return null; } });
out.matches = input.matches.map(([v, s, d]) => core.matches(v, s, d));
out.resolve = input.resolve.keys.map(k => {
  try { return {v: core.resolvePath(input.resolve.data, k.split('.')).value}; }
  catch (e) { if (e instanceof core.KeyMissing) return null; throw e; }
});
out.check = input.check.map(c => c.markers.map(([k, t]) => core.checkMarker(k, t, {site: c.site, headline: c.headline}).status));
process.stdout.write(JSON.stringify(out));
"""


def _run_node(tmp_path, payload):
    runner = tmp_path / 'runner.js'
    runner.write_text(RUNNER, encoding='utf-8')
    data = tmp_path / 'input.json'
    data.write_text(json.dumps(payload), encoding='utf-8')
    res = subprocess.run([NODE, str(runner), str(JS_PATH), str(data)], capture_output=True, text=True,
                         encoding='utf-8', timeout=120, check=False)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


@pytest.mark.skipif(NODE is None, reason='Node is not on the PATH')
def test_verify_js_agrees_with_the_checker_on_every_vector(tmp_path):
    match_in = []
    for value, text in MATCH_CASES:
        shown, dp = chk.parse_marker_value(text)
        match_in.append([value, shown, dp])
    out = _run_node(tmp_path, {
        'parse': PARSE_TEXTS,
        'matches': match_in,
        'resolve': {'data': RESOLVE_DATA, 'keys': RESOLVE_KEYS},
        'check': [{'site': CHECK_SITE, 'headline': CHECK_HEADLINE, 'markers': CHECK_MARKERS}],
    })
    for text, got in zip(PARSE_TEXTS, out['parse']):
        assert got == _py_parse(text), f'parse {text!r}: verify.js {got}, Python {_py_parse(text)}'
    for (value, shown, dp), got in zip(match_in, out['matches']):
        assert got == chk.matches(float(value), shown, dp), (value, shown, dp)
    for key, got in zip(RESOLVE_KEYS, out['resolve']):
        assert got == _py_resolve(key), f'resolve {key!r}: verify.js {got}, Python {_py_resolve(key)}'
    want = _py_statuses(CHECK_SITE, CHECK_HEADLINE, CHECK_MARKERS)
    for marker, got, exp in zip(CHECK_MARKERS, out['check'][0], want):
        assert got == exp, f'{marker}: verify.js {got}, Python {exp}'
    # the vectors exercise both outcomes of each step
    assert None in out['parse'] and any(out['parse'])
    assert True in out['matches'] and False in out['matches']
    assert set(want) == {'ok', 'fail'}


@pytest.mark.skipif(NODE is None, reason='Node is not on the PATH')
def test_verify_js_passes_every_marker_of_the_page(tmp_path):
    """Every marker of index.html, checked by verify.js against the committed data, as CI does."""
    page = (REPO / 'index.html').read_text(encoding='utf-8')
    markers, errors = chk.extract_markers(page)
    assert not errors
    headline = json.loads(chk.DEFAULT_JSON.read_text(encoding='utf-8'))
    site, problem = chk.load_site_data(chk.DEFAULT_SITE_JSON, chk.DEFAULT_JSON)
    assert problem is None, problem
    pairs = [[k, b] for k, b, _ in markers]
    out = _run_node(tmp_path, {'parse': [], 'matches': [], 'resolve': {'data': {}, 'keys': []},
                               'check': [{'site': site, 'headline': headline, 'markers': pairs}]})
    want = _py_statuses(site, headline, [tuple(p) for p in pairs])
    assert out['check'][0] == want
    assert set(want) == {'ok'}
    # and one altered number fails in both
    altered = [list(p) for p in pairs]
    i = next(j for j, (k, b) in enumerate(altered) if k == 'main.total_return_pct')
    altered[i][1] = altered[i][1].replace('0.39', '0.40')
    out = _run_node(tmp_path, {'parse': [], 'matches': [], 'resolve': {'data': {}, 'keys': []},
                               'check': [{'site': site, 'headline': headline, 'markers': altered}]})
    assert out['check'][0][i] == 'fail' and out['check'][0].count('fail') == 1
