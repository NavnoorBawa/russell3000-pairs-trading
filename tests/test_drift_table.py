"""The re-fetch drift table (index.html Section 13, README "Reproduce"): current, complete, and
the prose around it true for the data.

scripts/build_drift_table.py writes the table from assets/study.json's 'refetch' section, whose
rows are scripts/build_site_data.py's DRIFT_ROWS plus every declared variant whose Sharpe ratio
moved. These tests keep the row list complete: every headline key the page quotes has a row
(or a stated reason to have none), and so does every value the page or the README quotes that
the re-fetch moved at the precision shown, recomputed here from results/v33_dev_refetch/.
"""
import copy
import datetime as dt
import json
import pathlib
import re
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import build_drift_table as bdt  # noqa: E402
import build_site_data as bsd  # noqa: E402
import check_published_numbers as cpn  # noqa: E402

PAGE = ROOT / 'index.html'
README = ROOT / 'README.md'
STUDY = ROOT / 'assets' / 'study.json'
REFETCH = ROOT / 'results' / bsd.REFETCH_RUN
HEADLINE = ROOT / 'results' / 'v33_dev' / 'headline_metrics.json'

pytestmark = pytest.mark.skipif(not (REFETCH / 'headline_metrics.json').is_file(),
                                reason='no re-fetch reproduction in results/')


def _outside_table(text):
    return re.sub(r'<!-- drift-table:begin -->.*?<!-- drift-table:end -->', '', text, flags=re.S)


def _markers(path):
    text = _outside_table(path.read_text(encoding='utf-8'))
    markers, errors = cpn.extract_markers(text, is_markdown=path.suffix == '.md')
    assert not errors, errors
    return [(key, shown) for key, shown, _line in markers if not key.startswith('study.refetch.')]


@pytest.fixture(scope='module')
def study():
    return json.loads(STUDY.read_text(encoding='utf-8'))


@pytest.fixture(scope='module')
def refetched():
    """The study built from the re-fetch's own directory, as refetch_section builds it."""
    return bsd.build(REFETCH, refetch=None, family_root=REFETCH, residual_dir=REFETCH / 'residual',
                     validation_dir=REFETCH / 'validation')


def test_table_is_current():
    assert bdt.main(['--check']) == 0


def test_every_quoted_headline_key_has_a_row_or_a_reason():
    rows = {k for _g, k, _l, _d in bsd.DRIFT_ROWS}
    quoted = {k for k, _ in _markers(PAGE) if not k.startswith('study.')}
    missing = quoted - rows - set(bsd.DRIFT_SAME) - set(bsd.DRIFT_CONSTANT)
    assert not missing, f'headline keys the page quotes with no drift row: {sorted(missing)}'


def test_every_row_is_quoted_on_the_page():
    quoted = {k for k, _ in _markers(PAGE)}
    unquoted = [k for _g, k, _l, _d in bsd.DRIFT_ROWS if k not in quoted]
    assert not unquoted, f'drift rows the page does not quote: {unquoted}'


def test_every_quoted_value_the_refetch_moved_has_a_row(study, refetched):
    published = cpn.with_site_data(json.loads(HEADLINE.read_text()), study)
    again = cpn.with_site_data(json.loads((REFETCH / 'headline_metrics.json').read_text()), refetched)
    rows = {k for _g, k, _l, _d in bsd.DRIFT_ROWS}
    moved = set()
    for path in (PAGE, README):
        for key, shown in _markers(path):
            value, dp = cpn.parse_marker_value(shown)
            new = cpn.resolve_key(again, key)
            assert cpn.matches(cpn.resolve_key(published, key), value, dp), key
            if new is None or not cpn.matches(new, value, dp):
                moved.add(key)
    missing = moved - rows - set(bsd.DRIFT_SAME)
    assert not missing, f'values the re-fetch moved that the drift table leaves out: {sorted(missing)}'
    # a second marker that moved is listed through its twin
    assert {bsd.DRIFT_SAME[k] for k in moved & set(bsd.DRIFT_SAME)} <= rows


def test_left_out_keys_are_twins_or_constants(study, refetched):
    dp = {k: d for _g, k, _l, d in bsd.DRIFT_ROWS}
    published = json.loads(HEADLINE.read_text())
    again = json.loads((REFETCH / 'headline_metrics.json').read_text())
    for head, data in ((published, study), (again, refetched)):
        for key, twin in bsd.DRIFT_SAME.items():
            a, b = bsd._drift_value(key, head, data), bsd._drift_value(twin, head, data)
            assert a is not None and bsd._shown(a, dp[twin]) == bsd._shown(b, dp[twin]), (key, twin)
    for key in bsd.DRIFT_CONSTANT:
        assert bsd._drift_value(key, published, study) == bsd._drift_value(key, again, refetched), key


def test_moved_variants_are_rows(study, refetched):
    old = study['dev']['snooping']['results']['variants']
    new = refetched['dev']['snooping']['results']['variants']
    moved = {f'study.dev.snooping.results.variants.{i}.sharpe' for i, (a, b) in enumerate(zip(old, new))
             if round(a['sharpe'], 2) != round(b['sharpe'], 2)}
    listed = {r['key'] for r in study['refetch']['rows'] if r['group'] == bsd.DRIFT_VARIANTS}
    assert moved == listed
    assert study['refetch']['variants_moved'] == len(moved)


def test_counts_add_up(study):
    r = study['refetch']
    assert r['rows_n'] == len(r['rows']) == r['rows_same'] + r['rows_moved']
    assert r['moved'] == [x['key'] for x in r['rows'] if not x['same_as_shown']]


def test_the_prose_is_true_for_the_data(study):
    """The sentences of the page, the README and the paper about the re-fetch, against the data."""
    r = study['refetch']
    v = r['values']['dev']
    sn, facts, rows = v['snooping']['results'], v['facts'], {x['key']: x for x in r['rows']}
    page, readme = PAGE.read_text(encoding='utf-8'), README.read_text(encoding='utf-8')
    for text in (page, ' '.join(readme.split())):
        assert 'Every headline number of the main backtest, the walk-forward and the baselines agrees' in text
        assert 'No conclusion about the strategy changes' in text
    # every headline number of the main backtest, the walk-forward and the baselines agrees
    assert r['headline_same']
    assert all(rows[k]['same_as_shown'] for k in ('main.sharpe', 'oos.pooled_sharpe', 'benchmarks.gatev.sharpe'))
    # the learned ranker becomes the best variant; the published best was the 300-name universe
    assert "the learned ranker, becomes the family's best variant" in page
    assert r['best'] == {'published': "300 names, v32's size", 'refetch': 'Learned ranker on'}
    ranker = next(i for i, x in enumerate(study['dev']['snooping']['results']['variants'])
                  if x['name'] == 'ranker_gbm')
    assert f'study.dev.snooping.results.variants.{ranker}.sharpe' in rows
    # no variant beats cash or the distance method once the search is allowed for; choosing one overfits
    assert sn['spa_zero']['p'] > 0.05 and sn['rw_rejected'] == 0 and sn['spa_gatev_unit_vol']['p'] > 0.05
    assert sn['pbo_pct'] > 50 and sn['dsr_best']['dsr_pct'] < 95
    # persistence on the 300 names falls below the base rate at 5%; published, it did not
    assert 'persist less often than the base rate at the 5% level' in page
    assert facts['pers_z'] <= -1.96 < study['dev']['facts']['pers_z']
    # on the strategy's own candidate pairs it is unchanged, and at the base rate
    assert rows['study.dev.facts.pers_s1_z']['same_as_shown'] and abs(facts['pers_s1_z']) < 1.96
    # the main backtest's Sharpe ratio is unchanged as shown while variants moved by tenths
    assert r['variants_move_min'] >= 0.1


def test_byline_and_json_ld_carry_the_revision_date(study):
    page = PAGE.read_text(encoding='utf-8')
    d = dt.date.fromisoformat(study['meta']['revised'])
    assert f'Note updated {d.day} {d.strftime("%B %Y")}' in page
    assert f'"dateModified": "{d.isoformat()}"' in page


def test_refetch_section_is_none_without_the_run(tmp_path, study):
    src = bsd.Sources(bsd.ROOT, bsd.ROOT / 'results')
    assert bsd.refetch_section(src, tmp_path / 'absent', json.loads(HEADLINE.read_text()), study,
                               bsd.ROOT, bsd.ROOT / 'results', bsd.HOLDOUT_CALENDAR) is None


def test_refetch_section_reports_a_moved_headline_value(tmp_path):
    """A re-fetch whose main Sharpe ratio differs by 0.50 shows that difference and one row fewer
    that agrees; the headline rows no longer all agree."""
    copy_dir = tmp_path / bsd.REFETCH_RUN
    shutil.copytree(REFETCH, copy_dir)
    head = json.loads((copy_dir / 'headline_metrics.json').read_text())
    head['main']['sharpe'] += 0.5
    (copy_dir / 'headline_metrics.json').write_text(json.dumps(head))
    published = json.loads(HEADLINE.read_text())
    base = bsd.build(bsd.DEFAULT_DEV, refetch=None)
    src = bsd.Sources(bsd.ROOT, bsd.ROOT / 'results')
    ref = bsd.refetch_section(src, REFETCH, published, copy.deepcopy(base), bsd.ROOT, bsd.ROOT / 'results',
                              bsd.HOLDOUT_CALENDAR)
    bent = bsd.refetch_section(src, copy_dir, published, copy.deepcopy(base), bsd.ROOT, bsd.ROOT / 'results',
                               bsd.HOLDOUT_CALENDAR)
    assert bent['diff']['main']['sharpe'] == pytest.approx(ref['diff']['main']['sharpe'] + 0.5)
    assert bent['rows_same'] == ref['rows_same'] - 1
    assert ref['headline_same'] and not bent['headline_same']
