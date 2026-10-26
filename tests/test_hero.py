"""The hero figure of index.html ("the answer at a glance") and scripts/build_hero.py.

The hero draws every interval with CSS from inline custom properties that the generator
computes. These tests read the block as published, recompute every drawn position from the
number the same row prints (its data-metric text) and the table's axis, and fail on any
drift; they also run the generator's own --check, the publication checker on the block, and
the generator's refusals (an interval that excludes zero, a rejected 2026 null, arms out of
order), so the title cannot become false and the drawing cannot disagree with the text.
"""
import copy
import importlib.util
import json
import pathlib
import re
from html.parser import HTMLParser

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
PAGE = REPO / 'index.html'


def _load(name):
    spec = importlib.util.spec_from_file_location(f'_script_{name}', REPO / 'scripts' / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hero = _load('build_hero')
chk = _load('check_published_numbers')

ROLES = ('x', 'lo', 'hi', 'ub')
# keys the hero marks that no other part of the page marks (the other hero keys must be
# the keys the page already uses for the same numbers)
HERO_ONLY_KEYS = {'study.dev.forest.1.lo', 'study.dev.forest.1.hi',
                  'study.holdout.arms.1.lo', 'study.holdout.arms.1.hi',
                  'study.holdout.arms.2.lo', 'study.holdout.arms.2.hi'}


class HeroBlock(HTMLParser):
    """The parts of the hero block the tests need, as the browser would read them."""

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.table = None
        self.ticks = []                     # [(style, text)]
        self.rows = []                      # [{'style', 'classes', 'roles': {role: (key, text)}, 'hrefs'}]
        self.hrefs = []
        self.figure = None
        self._stack = []                    # open elements: (tag, attrs)
        self._tick = None
        self._role = None
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get('class') or '').split()
        if tag == 'figure' and self.figure is None:
            self.figure = a
        if tag == 'table' and 'hz' in cls:
            self.table = a
        if tag == 'tr' and 'hz-r' in cls:
            self.rows.append({'style': a.get('style', ''), 'classes': cls, 'roles': {}, 'hrefs': []})
        if tag == 'a' and 'href' in a:
            self.hrefs.append(a['href'])
            if self.rows and self._in('tr'):
                self.rows[-1]['hrefs'].append(a['href'])
        if 'hz-t' in cls:
            self._tick = [a.get('style', ''), '']
        if a.get('data-hz'):
            self._role = [a['data-hz'], a.get('data-metric'), '']
        if tag not in chk._VOID_TAGS:
            self._stack.append((tag, a))

    def _in(self, tag):
        return any(t == tag for t, _ in self._stack)

    def handle_endtag(self, tag):
        while self._stack:
            t, a = self._stack.pop()
            if 'hz-t' in (a.get('class') or '').split() and self._tick:
                self.ticks.append(tuple(self._tick))
                self._tick = None
            if a.get('data-hz') and self._role:
                role, key, text = self._role
                assert role not in self.rows[-1]['roles'], f'two {role} markers in one row'
                self.rows[-1]['roles'][role] = (key, text)
                self._role = None
            if t == tag:
                break

    def handle_data(self, data):
        if self._tick is not None:
            self._tick[1] += data
        if self._role is not None:
            self._role[2] += data


def props(style):
    """{name: percent} for the custom properties of an inline style ('--x:48.8%;...')."""
    out = {}
    for part in filter(None, (p.strip() for p in style.split(';'))):
        name, _, val = part.partition(':')
        assert name.startswith('--') and val.endswith('%'), part
        out[name[2:]] = float(val[:-1])
    return out


def number(text):
    return chk.parse_marker_value(text)[0]


def recompute(block):
    """Assert that every drawn position is where the printed number and the axis put it.
    Returns the parsed block."""
    h = HeroBlock(block)
    assert h.table is not None, 'no table.hz in the hero block'
    lo_axis, hi_axis = (float(v) for v in h.table['data-axis'].split())
    assert lo_axis == -hi_axis and hi_axis > 0, 'the axis is symmetric about zero'
    assert (2 * hi_axis) % (2 * hero.AXIS_STEP) == 0 and hi_axis >= hero.AXIS_HALF

    def pos(v):
        return (v - lo_axis) / (hi_axis - lo_axis) * 100

    assert props(h.table['style']) == {'zero': pytest.approx(pos(0), abs=1e-3)}
    # one tick at every whole number of the axis, labelled with its signed value
    want = list(range(-int(hi_axis), int(hi_axis) + 1))
    assert [number(t) for _, t in h.ticks] == want
    for (style, text), k in zip(h.ticks, want):
        assert props(style) == {'t': pytest.approx(pos(k), abs=1e-3)}, text
        assert text == ('0' if k == 0 else ('+' if k > 0 else '−') + str(abs(k)))
    assert h.rows, 'no rows'
    for row in h.rows:
        p = props(row['style'])
        roles = row['roles']
        assert {'x', 'lo', 'hi'} <= set(roles) and set(roles) <= set(ROLES), roles
        assert set(p) == set(roles), (row['style'], roles)          # a drawn mark for each number, no more
        for role, (key, text) in roles.items():
            v = number(text)
            assert lo_axis <= v <= hi_axis, f'{key} = {text} is off the axis'
            assert p[role] == pytest.approx(pos(v), abs=1e-3), f'{key}: drawn at {p[role]}%, prints {text}'
    return h


@pytest.fixture(scope='module')
def page():
    return PAGE.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def block(page):
    return hero.split_page(page)[1]


@pytest.fixture(scope='module')
def data():
    return hero.load_data()


# ── the published block ───────────────────────────────────────────────────────

def test_the_block_is_what_the_generator_builds(capsys):
    assert hero.main(['--check']) == 0, capsys.readouterr().err


def test_every_drawn_position_is_the_printed_number(block):
    h = recompute(block)
    assert len(h.rows) == 8
    assert sum('ub' in r['roles'] for r in h.rows) == 5           # every bound the note reports


def test_every_interval_spans_zero_as_the_title_says(block):
    h = HeroBlock(block)
    assert 'Every 95% interval spans zero' in block
    for row in h.rows:
        lo, hi = number(row['roles']['lo'][1]), number(row['roles']['hi'][1])
        assert lo < 0 < hi, row


def test_every_number_is_a_checked_marker(block, data):
    n, failures, _, seen = chk.check_text(data, block, 'hero', required=())
    assert not failures, failures
    # 8 rows × 3, 5 bounds, 2 Holm p-values, the test's length and its 80%-power Sharpe ratio
    assert n == 8 * 3 + 5 + 2 + 2
    text = re.sub(r'<span[^>]*\sdata-metric="[^"]+"[^>]*>[^<]*</span>', '', block)
    text = re.sub(r'<span class="hz-t"[^>]*>[^<]*</span>', '', text)            # the axis labels
    text = re.sub(r'<!--.*?-->|<[^>]+>', ' ', text, flags=re.S)
    text = re.sub(r'\b(?:H[12]|S[123]|v3[23])\b|\b(?:19|20)\d\d\b|95%|80%|Section&nbsp;1|Section 1', '', text)
    assert not re.search(r'\d', text), f'an unmarked number in the hero: {text!r}'


def test_the_hero_uses_the_pages_own_keys(page, block):
    rest = page.replace(block, '')
    elsewhere = set(re.findall(r'data-metric="([^"]+)"', rest))
    for key in set(re.findall(r'data-metric="([^"]+)"', block)):
        assert key in elsewhere or key in HERO_ONLY_KEYS, f'{key}: the page marks this number with another key'


def test_the_hero_is_not_a_numbered_exhibit(block):
    h = HeroBlock(block)
    assert h.figure['class'] == 'hero' and h.figure['id'] == 'answer'
    assert h.figure['aria-labelledby'] == 'answer-h' and 'id="answer-h"' in block
    assert 'class="exhibit' not in block and not re.search(r'id="ex-\d', block)
    assert '<script' not in block and not re.search(r'<[^>]*\son[a-z]+\s*=', block)      # no script: CSP


def test_every_link_resolves_on_the_page(page, block):
    h = HeroBlock(block)
    ids = set(re.findall(r'\sid="([^"]+)"', page))
    assert h.hrefs and all(href.startswith('#') and href[1:] in ids for href in h.hrefs), h.hrefs
    assert all(len(r['hrefs']) == 1 for r in h.rows)              # each label links to its exhibit
    assert [r['hrefs'][0] for r in h.rows] == ['#ex-6', '#ex-6', '#ex-3', '#ex-22', '#ex-6',
                                               '#ex-1', '#ex-1', '#ex-1']


def test_the_track_is_hidden_from_assistive_technology_and_the_numbers_are_not(block):
    assert block.count('class="hz-tr" aria-hidden="true"') == 8
    assert block.count('class="hz-legend" aria-hidden="true"') == 1
    # the bounds the ticks draw are read out with the values
    assert block.count('<span class="vh">; one-sided 95% upper bound <span data-metric=') == 5


# ── the generator ─────────────────────────────────────────────────────────────

def _render(data, edit):
    d = copy.deepcopy(data)
    edit(d)
    return hero.render(d)


def test_an_interval_that_excludes_zero_stops_the_build(data):
    def edit(d):
        d['study']['residual']['hi'] = -0.004            # prints as 0.00: excluded by the raw value too
    with pytest.raises(hero.HeroError, match='does not span zero'):
        _render(data, edit)
    with pytest.raises(hero.HeroError, match='does not span zero'):
        _render(data, lambda d: d['significance']['oos_daily'].update(boot_hi=-0.01))


def test_a_rejected_null_or_arms_out_of_order_stop_the_build(data):
    with pytest.raises(hero.HeroError, match='rejected'):
        _render(data, lambda d: d['study']['holdout']['decision'].update(rejected=['v33_pairs']))
    with pytest.raises(hero.HeroError, match='arms.0.key'):
        _render(data, lambda d: d['study']['holdout']['arms'].reverse())
    with pytest.raises(hero.HeroError, match='forest.1.key'):
        _render(data, lambda d: d['study']['dev']['forest'].reverse())


def test_the_axis_widens_symmetrically_until_every_value_fits(data):
    def edit(d):
        d['study']['holdout']['arms'][1]['lo'] = -2.71
    block = _render(data, edit)
    h = recompute(block)
    assert h.table['data-axis'] == '-3 3' and [t for _, t in h.ticks] == ['−3', '−2', '−1', '0', '+1', '+2', '+3']
    assert hero.axis_half([2.5, -2.5]) == 2.5 and hero.axis_half([2.51]) == 3.0 and hero.axis_half([-3.2]) == 3.5


def test_a_drawn_position_that_drifts_is_caught(tmp_path, page, block, capsys):
    h = HeroBlock(block)
    style = h.rows[0]['style']
    moved = style.replace('--x:', '--x:1', 1)
    assert moved != style
    with pytest.raises(AssertionError):
        recompute(block.replace(style, moved, 1))
    p = tmp_path / 'index.html'
    p.write_text(page.replace(style, moved, 1), encoding='utf-8')
    assert hero.main(['--check', '--page', str(p)]) == 1
    assert hero.main(['--write', '--page', str(p)]) == 0
    assert hero.main(['--check', '--page', str(p)]) == 0
    assert p.read_text(encoding='utf-8') == page
    capsys.readouterr()


def test_markers_must_be_there_once(tmp_path, page, capsys):
    p = tmp_path / 'index.html'
    p.write_text(page.replace(hero.END, '', 1), encoding='utf-8')
    assert hero.main(['--check', '--page', str(p)]) == 2
    p.write_text(page + hero.BEGIN, encoding='utf-8')
    assert hero.main(['--write', '--page', str(p)]) == 2
    assert 'once each' in capsys.readouterr().err


def test_site_data_from_another_run_stops_the_build(tmp_path, capsys):
    study = json.loads((REPO / 'assets' / 'study.json').read_text(encoding='utf-8'))
    study['meta']['headline_sha256'] = '0' * 64
    other = tmp_path / 'study.json'
    other.write_text(json.dumps(study), encoding='utf-8')
    assert hero.main(['--study', str(other)]) == 2
    assert 'another headline JSON' in capsys.readouterr().err
