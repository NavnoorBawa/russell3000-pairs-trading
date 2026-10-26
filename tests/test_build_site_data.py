"""scripts/build_site_data.py (assets/study.json) and the checker's study.* markers.

The page is built from the committed v33 development run (results/v33_dev), whose
artefacts the builder reads in full: the export's evidence block, anatomy.json,
cost_sensitivity.json, the residual arm, the validation, the published v32 run and the
trial registry. The code paths of older exports are exercised on the committed v32 run and
on copies of it altered to carry what later exports add (the random-pair quantiles,
point-in-time universe coverage, the daily gross/cost split, a _compact twin). The evaluated
holdout is exercised on results trees whose holdout2026/ is the 2025 dress rehearsal
(results/rehearsal2025b, calendar rehearsal2025) under the holdout's trial name, with a
registry line and attempt lines modelled on the rehearsal's, altered for each outcome.
"""
import copy
import hashlib
import importlib.util
import json
import math
import pathlib
import re
import shutil

import numpy as np
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
V32 = REPO / 'results' / 'v32_dev'
V33 = REPO / 'results' / 'v33_dev'
RESULTS_NAME = 'pairs_trading_results_2023_2025_unbiased.json'


def _load(name):
    spec = importlib.util.spec_from_file_location(f'_script_{name}', REPO / 'scripts' / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bsd = _load('build_site_data')
chk = _load('check_published_numbers')


@pytest.fixture(scope='module')
def v32_res():
    return json.loads((V32 / RESULTS_NAME).read_text(encoding='utf-8'))


@pytest.fixture(scope='module')
def v32_study():
    return bsd.build(V32)


@pytest.fixture(scope='module')
def v33_study():
    """The committed page data: assets/study.json, as the page reads it."""
    return json.loads((REPO / 'assets' / 'study.json').read_text(encoding='utf-8'))


def _json(path):
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))


def _run_dir(tmp_path, res, name='run'):
    """A run directory holding the v32 headline JSON and the export `res`."""
    d = tmp_path / name
    d.mkdir()
    shutil.copy(V32 / 'headline_metrics.json', d / 'headline_metrics.json')
    (d / RESULTS_NAME).write_text(json.dumps(res), encoding='utf-8')
    return d


def _quantiles(n):
    """Monotone per-day quantile paths (p05 <= ... <= p95), widening with time."""
    z = {'p05': -1.645, 'p25': -0.674, 'p50': 0.0, 'p75': 0.674, 'p95': 1.645}
    return {k: [round(v * 0.1 * math.sqrt(i + 1), 4) for i in range(n)] for k, v in z.items()}


# ── the committed file ─────────────────────────────────────────────────────────

def test_committed_study_json_is_current():
    """assets/study.json is what the builder makes from results/v33_dev, byte for byte."""
    assert bsd.DEFAULT_DEV == V33
    assert bsd.main(['--check']) == 0


def test_committed_page_passes_the_publication_checker(capsys):
    """Every number in README.md and index.html matches the v33 headline JSON or study.json,
    and the checker's default JSON is the one the committed study.json was built from."""
    assert chk.DEFAULT_JSON == V33 / 'headline_metrics.json'
    meta = _json(REPO / 'assets' / 'study.json')['meta']
    assert meta['headline_sha256'] == hashlib.sha256(chk.DEFAULT_JSON.read_bytes()).hexdigest()
    assert chk.main([]) == 0
    assert '0 failure(s)' in capsys.readouterr().out


def test_build_is_deterministic_compact_and_tied_to_its_headline(v32_study):
    text = bsd.dumps(v32_study)
    assert text == bsd.dumps(bsd.build(V32))                   # no wall-clock time, no set order
    assert len(text.encode()) < 400 * 1024
    data = json.loads(text)
    assert data['meta']['headline_sha256'] == hashlib.sha256((V32 / 'headline_metrics.json').read_bytes()).hexdigest()
    assert data['meta']['commit'] == data['dev']['run']['commit']
    assert 'results/v32_dev/' + RESULTS_NAME in data['meta']['sources']
    assert 'NaN' not in text and 'Infinity' not in text


# ── series ─────────────────────────────────────────────────────────────────────

def test_rebuilt_exposure_reproduces_the_runs_published_figures(v32_res, v32_study):
    daily = v32_study['dev']['daily']
    perf = v32_res['overall_performance']
    assert max(daily['exposure']) == pytest.approx(perf['max_gross_exposure_pct_of_equity'], abs=0.01)
    assert np.mean(daily['exposure']) == pytest.approx(perf['avg_gross_exposure_pct_of_equity'], abs=0.01)
    assert daily['gross'] is None and daily['cost'] is None    # v32 does not split them per day
    assert v32_study['dev']['cost_curve'] is None


def test_exported_daily_split_is_used_and_drives_the_cost_curve(v32_res):
    res = copy.deepcopy(v32_res)
    for i, d in enumerate(res['daily_equity_curve']):
        d['cost_pct'] = 0.002 if i % 3 == 0 else 0.0
        d['gross_return_pct'] = d['daily_return_pct'] + d['cost_pct']
        d['gross_exposure_pct'] = 10.0
        d['open_positions'] = 2
    daily = bsd.daily_series(res)
    assert daily['exposure'] == [10.0] * len(daily['dates']) and set(daily['positions']) == {2}
    curve = bsd.cost_curve(daily)
    assert [row['k'] for row in curve] == list(bsd.COST_MULTIPLIERS)
    at_one = next(row for row in curve if row['k'] == 1.0)
    net = np.asarray(daily['gross']) / 100 - np.asarray(daily['cost']) / 100
    assert at_one['sharpe'] == pytest.approx(bsd._sharpe(net), abs=1e-4)
    sharpes = [row['sharpe'] for row in curve]
    assert sharpes == sorted(sharpes, reverse=True)           # more cost, lower Sharpe


def test_random_band_passes_the_exported_quantiles_through(v32_res):
    assert bsd.random_band(v32_res) is None                   # the v32 export predates them
    res = copy.deepcopy(v32_res)
    rc = res['benchmarks']['random_control']
    rc['cumulative_return_pct_quantiles'] = _quantiles(len(rc['daily_dates']))
    band = bsd.random_band(res)
    assert band['dates'] == [str(d)[:10] for d in rc['daily_dates']]
    assert band['n_draws'] == rc['n_draws']
    for k in ('p05', 'p25', 'p50', 'p75', 'p95'):
        assert band[k] == rc['cumulative_return_pct_quantiles'][k]


def test_misaligned_random_quantiles_are_an_error(v32_res):
    res = copy.deepcopy(v32_res)
    rc = res['benchmarks']['random_control']
    rc['cumulative_return_pct_quantiles'] = _quantiles(len(rc['daily_dates']) - 1)
    with pytest.raises(ValueError, match='not aligned'):
        bsd.random_band(res)


def test_universe_coverage_by_formation():
    res = {'universe_by_formation': [
        {'formation_date': '2022-12-31', 'snapshot': '2022-12-30', 'members': 2283, 'with_prices': 2062,
         'missing': 221, 'missing_value_weight': 0.02137353739399, 'unmapped_value_weight': 0.0214601},
        {'formation_date': '2023-07-06', 'snapshot': '2023-06-30', 'members': 2391, 'with_prices': 2180,
         'missing': 211, 'missing_value_weight': 0.0182047, 'unmapped_value_weight': None}]}
    rows = bsd.universe_coverage(res)
    assert rows[0] == {'formation_date': '2022-12-31', 'snapshot': '2022-12-30', 'snapshot_filed': None, 'members': 2283,
                       'with_prices': 2062, 'missing': 221, 'missing_weight_pct': 2.137, 'unmapped_weight_pct': 2.146,
                       'missing_heaviest': [], 'unmapped_heaviest': []}
    assert rows[1]['unmapped_weight_pct'] is None
    res['universe_by_formation'][0].update({'snapshot_filed': '2023-02-24',
                                            'missing_heaviest': [['ATVI', 0.0015687], ['PXD', 0.0014391], ['HES', 0.00106], ['EA', 0.0009]]})
    row = bsd.universe_coverage(res)[0]
    assert row['snapshot_filed'] == '2023-02-24'
    assert row['missing_heaviest'] == [['ATVI', 0.157], ['PXD', 0.144], ['HES', 0.106]]     # the three heaviest, in %
    assert bsd.universe_coverage({}) is None and bsd.universe_coverage({'universe_by_formation': []}) is None


# ── trades, costs, statistics ──────────────────────────────────────────────────

def test_waterfall_closes_exactly_on_the_change_in_the_book(v32_res, v32_study):
    steps = v32_study['dev']['waterfall']
    capital = v32_res['metadata']['initial_capital']
    net = v32_res['overall_performance']['final_portfolio_value'] - capital
    assert [s['key'] for s in steps] == ['gross'] + [k for k, _ in bsd.COST_STEPS] + ['net']
    assert steps[-1]['usd'] == pytest.approx(round(net, 2), abs=0.005)
    cents = round(steps[0]['usd'] * 100) + sum(round(s['usd'] * 100) for s in steps[1:-1])
    assert cents == round(steps[-1]['usd'] * 100)
    for prev, s in zip(steps[:-2], steps[1:-1]):              # each cost bar starts where the last ended
        assert s['start'] == pytest.approx(prev['end'], abs=1e-9)
    # the per-component costs are the trades' own breakdowns
    for key, _ in bsd.COST_STEPS:
        total = sum(t['cost_breakdown_dollars'][key] for t in v32_res['all_trades'])
        assert -next(s['usd'] for s in steps if s['key'] == key) == pytest.approx(total, abs=0.01)


def test_trade_groups_partition_the_trades(v32_res, v32_study):
    groups = v32_study['dev']['trades']
    n, net = len(v32_res['all_trades']), sum(t['net_pnl_dollars'] for t in v32_res['all_trades'])
    for key in ('by_exit', 'by_side', 'by_z'):
        assert sum(g['n'] for g in groups[key]) == n
        assert sum(g['net_usd'] for g in groups[key]) == pytest.approx(net, abs=0.05)


def test_facts_are_consistent_with_the_sections(v32_res, v32_study):
    f, dev = v32_study['dev']['facts'], v32_study['dev']
    assert f['trades'] == len(v32_res['all_trades'])
    assert f['break_even_x'] == pytest.approx(dev['waterfall'][0]['usd'] / -sum(s['usd'] for s in dev['waterfall'][1:-1]), abs=1e-3)
    assert f['gross_usd_k'] == pytest.approx(dev['waterfall'][0]['usd'] / 1e3, abs=0.05)
    assert f['sharpe_ucb'] == dev['power']['ucb'] and f['sharpe_mde'] == dev['power']['mde']
    assert f['sharpe_critical'] < f['sharpe_mde']              # detectable needs more than significant
    assert 0 < f['win_lo_pct'] < 100 * f['wins'] / f['trades'] < f['win_hi_pct'] < 100


def test_no_break_even_multiple_without_a_gross_edge(tmp_path, v32_res):
    """When gross P&L is negative, no cost level breaks even: the fact is null, not negative."""
    res = copy.deepcopy(v32_res)
    for t in res['all_trades']:                               # every trade loses before costs
        t['net_pnl_dollars'] = -abs(t['net_pnl_dollars']) - t['transaction_costs_dollars']
    res['overall_performance']['final_portfolio_value'] = (
        res['metadata']['initial_capital'] + sum(t['net_pnl_dollars'] for t in res['all_trades']))
    study = bsd.build(_run_dir(tmp_path, res), results_root=tmp_path / 'results')
    assert study['dev']['waterfall'][0]['usd'] < 0
    assert study['dev']['facts']['break_even_x'] is None


def test_power_numbers_are_ordered(v32_study):
    p = v32_study['dev']['power']
    assert p['critical'] > 0 and p['mde'] > p['critical']
    assert p['ucb'] == pytest.approx(p['sharpe'] + bsd.Z_95_ONE_SIDED * p['se'], abs=1e-3)
    p_ge = [a['p_ge'] for a in p['alternatives']]
    assert p_ge == sorted(p_ge, reverse=True)                 # larger claimed Sharpe, smaller p


def test_rolling_sharpe_band_contains_the_estimate(v32_study):
    r = v32_study['dev']['rolling_sharpe']
    assert len(r['dates']) == len(v32_study['dev']['daily']['dates']) - r['window'] + 1
    for sr, lo, hi in zip(r['sharpe'], r['lo'], r['hi']):
        assert (sr is None and lo is None and hi is None) or lo < sr < hi


def test_cost_schedules_are_labelled_by_letter_only(v32_study):
    """Schedules are parameter sets: the page sees a letter, never a descriptive name."""
    schedules = v32_study['dev']['cost_schedules']
    assert [s['id'] for s in schedules] == list('ABCDE')
    costs = [s['cost_pct'] for s in schedules]
    assert costs == sorted(costs)
    for s in schedules:
        text_fields = {k for k, v in s.items() if isinstance(v, str)}
        assert text_fields == {'id', 'source_key'}            # source_key: the replay's internal key


# ── run directories ────────────────────────────────────────────────────────────

def test_any_run_directory_and_the_compact_twin(tmp_path, v32_res):
    """A run's output directory works as --dev; its _compact export is never read."""
    res = copy.deepcopy(v32_res)
    rc = res['benchmarks']['random_control']
    rc['cumulative_return_pct_quantiles'] = _quantiles(len(rc['daily_dates']))
    res['universe_by_formation'] = [{'formation_date': '2023-07-06', 'snapshot': '2023-06-30', 'members': 10,
                                     'with_prices': 9, 'missing': 1, 'missing_value_weight': 0.01,
                                     'unmapped_value_weight': 0.002}]
    d = _run_dir(tmp_path, res, 'outputs_like')
    compact = {k: res[k] for k in ('metadata', 'run_config', 'overall_performance', 'daily_equity_curve')}
    (d / RESULTS_NAME.replace('.json', '_compact.json')).write_text(json.dumps(compact), encoding='utf-8')
    assert bsd._results_file(d).name == RESULTS_NAME
    out = tmp_path / 'preview' / 'study.json'
    assert bsd.main(['--dev', str(d), '--out', str(out)]) == 0
    study = json.loads(out.read_text(encoding='utf-8'))
    assert study['dev']['facts']['trades'] == len(res['all_trades'])     # trades came from the full export
    assert study['dev']['random_band']['p95'][-1] == rc['cumulative_return_pct_quantiles']['p95'][-1]
    assert study['dev']['universe_by_formation'][0]['missing_weight_pct'] == 1.0
    assert bsd.main(['--dev', str(d), '--out', str(out), '--check']) == 0
    out.write_text(out.read_text(encoding='utf-8') + ' ', encoding='utf-8')
    assert bsd.main(['--dev', str(d), '--out', str(out), '--check']) == 1


def test_run_directory_errors(tmp_path, v32_res):
    empty = tmp_path / 'empty'
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        bsd._results_file(empty)
    d = _run_dir(tmp_path, v32_res)
    (d / 'pairs_trading_results_2024_2026_unbiased.json').write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='several full exports'):
        bsd._results_file(d)


# ── the evaluated holdout: results trees built from the 2025 dress rehearsal ───

REHEARSAL = REPO / 'results' / 'rehearsal2025b'
REHEARSAL_CALENDAR = 'rehearsal2025'
RUN_COMMIT = '6aaf7efb1eb074cdb4e2137f961112ba62234c51'     # the rehearsal's runs
REGISTERED = '7c7d3f904ec643b9a9dc658c2aa46bad506cc3a5'      # a registered commit before a crash fix
eh = _load('evaluate_holdout')
rt = _load('register_trial')
CRASH_DIFF = """diff --git a/pairs_trading/json_export.py b/pairs_trading/json_export.py
index 3b1c2d4..8e9f0a1 100644
--- a/pairs_trading/json_export.py
+++ b/pairs_trading/json_export.py
@@ -41,7 +41,9 @@ def _to_jsonable(obj):
     if isinstance(obj, np.integer):
         return int(obj)
-    if isinstance(obj, np.floating):
+    if isinstance(obj, (np.floating, float)):
+        if not np.isfinite(obj):
+            return None
         return float(obj)
"""


def _rehearsal_entry():
    lines = (REPO / 'results' / 'trial_registry.jsonl').read_text(encoding='utf-8').splitlines()
    return next(e for e in map(json.loads, filter(None, lines)) if e['name'] == 'rehearsal2025b')


def _attempt_lines(attempt=1, head=RUN_COMMIT, prereg=RUN_COMMIT, note=None, steps=None):
    """One attempt modelled on rehearsal2025b's: its start line, then the steps it finished."""
    out = []
    for x in copy.deepcopy(_rehearsal_entry()['attempts']):
        x.pop('note', None)
        x.update(name='holdout2026', attempt=attempt, head=head)
        if x['event'] == 'start':
            x.update({k: v for k, v in (('prereg_commit', prereg), ('note', note)) if v})
        elif steps is not None and x['step'] not in steps:
            continue
        out.append(x)
    return out


def _register(root, attempts=None, prereg=RUN_COMMIT, note=None, completed=True):
    """The trial's line of results/trial_registry.jsonl (register_trial.py's fields, modelled on
    rehearsal2025b's) and its lines of results/trial_attempts.jsonl, with the completion line."""
    attempts = attempts if attempts is not None else _attempt_lines(prereg=prereg)
    entry = dict(_rehearsal_entry(), name='holdout2026', prereg_commit=prereg, note=note, attempts=attempts,
                 head=attempts[-1]['head'], evaluation=rt.evaluation_summary(root / 'holdout2026' / 'evaluation.json'))
    (root / 'trial_registry.jsonl').write_text(json.dumps(entry, sort_keys=True) + '\n', encoding='utf-8')
    done = [{'attempt': attempts[-1]['attempt'], 'event': 'completed', 'name': 'holdout2026',
             'utc': '2026-10-21T14:03:09+00:00'}] if completed else []
    (root / 'trial_attempts.jsonl').write_text(''.join(json.dumps(x, sort_keys=True) + '\n' for x in attempts + done),
                                                encoding='utf-8')


def _holdout_root(tmp_path, **register):
    """A results tree whose holdout2026/ is the published dress rehearsal, registered as the holdout."""
    root = tmp_path / 'results'
    root.mkdir(exist_ok=True)
    shutil.copytree(REHEARSAL, root / 'holdout2026')
    _register(root, **register)
    return root


def _section(root, calendar=REHEARSAL_CALENDAR):
    """The holdout section of `root` as build() makes it, and the sources it read."""
    src = bsd.Sources(REPO, root)
    return bsd.holdout_section(src.load(root / 'holdout2026' / 'evaluation.json'), src, root,
                               src.load_lines(root / 'trial_registry.jsonl'), calendar), src


def _edit_evaluation(root, edit, register=True):
    """Change evaluation.json; then (unless not) its registry line's copy of it, as if the
    trial had been registered with the changed file, so that only the edit is tested."""
    path = root / 'holdout2026' / 'evaluation.json'
    ev = _json(path)
    edit(ev)
    path.write_text(json.dumps(ev, indent=1), encoding='utf-8')
    if register:
        reg = root / 'trial_registry.jsonl'
        entry = json.loads(reg.read_text(encoding='utf-8'))
        entry['evaluation'] = rt.evaluation_summary(path)
        reg.write_text(json.dumps(entry, sort_keys=True) + '\n', encoding='utf-8')


def _flatten(root, key):
    """`key`'s pairs run made one that never opened a position, as the evaluator reports it: a
    zero net and gross return every day in its export (re-listed in MANIFEST.json and under the
    evaluation's sha256), its row from evaluate_holdout.describe, and Holm's adjustment again."""
    d = root / 'holdout2026' / bsd.HOLDOUT_EXPORTS[key][0]
    path = d / RESULTS_NAME
    res = _json(path)
    for day in res['daily_equity_curve']:
        day.update(daily_return_pct=0.0, gross_return_pct=0.0, cost_pct=0.0, open_positions=0)
    res['overall_performance']['total_trades'] = 0
    path.write_text(json.dumps(res), encoding='utf-8')
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = _json(d / 'MANIFEST.json')
    manifest['files'][RESULTS_NAME]['sha256'] = sha
    (d / 'MANIFEST.json').write_text(json.dumps(manifest), encoding='utf-8')
    zeros = np.zeros(len(res['daily_equity_curve']))

    def edit(ev):
        ev['strategies'][key].update(eh.describe(zeros, zeros, 0, n_tests=len(ev['family'])))
        ev['inputs']['runs'][key]['sha256'][RESULTS_NAME] = sha
        adj = eh.holm({k: ev['strategies'][k]['p_one_sided'] for k in ev['family']})
        for k in ev['family']:
            ev['strategies'][k].update(p_holm=adj[k], edge_out_of_sample=bool(adj[k] < eh.ALPHA))
    _edit_evaluation(root, edit)


@pytest.fixture(scope='module')
def residual_export(tmp_path_factory):
    """A real export of the residual arm (scripts/run_residual_statarb.py's payload) on a
    synthetic market, in an output directory of its own."""
    from pairs_trading.json_export import _atomic_write_json
    from pairs_trading.residual_statarb import run_residual_statarb
    from pairs_trading.synthetic import make_residual_market
    frames, etfs, smap, _ = make_residual_market(seed=0)
    res = run_residual_statarb(frames, etfs, smap, '2021-07-01', '2023-12-31')
    out = tmp_path_factory.mktemp('out_residual')
    rc = {'git_commit': 'f' * 40, 'git_dirty': False, 'run_timestamp_utc': '2026-10-20T00:00:00+00:00',
          'study': {'strategy': 'avellaneda_lee', 'calendar': {'name': 'dev'}}}
    _atomic_write_json(_load('run_residual_statarb').export_payload(res, rc), out / 'residual_statarb.json')
    return out


def _publish_residual(tmp_path, out):
    """results/residual_dev/ under tmp_path, as scripts/publish_run.py writes it."""
    pr = _load('publish_run')
    pr.ROOT = tmp_path
    return pr.publish(out, 'residual_dev')


def test_optional_arms_fill_their_sections(tmp_path, v32_res, residual_export):
    """The holdout evaluation and the published residual export replace the sealed/pending states."""
    root = _holdout_root(tmp_path)
    published = _publish_residual(tmp_path, residual_export)
    study = bsd.build(_run_dir(tmp_path, v32_res), results_root=root, holdout_calendar=REHEARSAL_CALENDAR)
    holdout = study['holdout']
    assert holdout['status'] == 'complete' and holdout['alpha'] == 0.05
    # the registered order (H1 v33, H2 Avellaneda-Lee, then the descriptive v32 arm), whatever
    # the report's order
    assert [(a['key'], a['hypothesis']) for a in holdout['arms']] == [
        ('v33_pairs', 'H1'), ('avellaneda_lee', 'H2'), ('v32_pairs', None)]
    v33, ev = holdout['arms'][0], _json(root / 'holdout2026' / 'evaluation.json')['strategies']['v33_pairs']
    assert (v33['sharpe'], v33['lo'], v33['hi'], v33['p_holm'], v33['edge']) == (
        round(ev['sharpe'], 4), round(ev['bootstrap_ci_95'][0], 4), round(ev['bootstrap_ci_95'][1], 4), 1.0, False)
    doc = json.loads((published / 'residual_statarb.json').read_text(encoding='utf-8'))
    s, sig = doc['summary'], doc['significance']
    r = study['residual']
    assert {k: r[k] for k in ('sharpe', 'ret_pct', 'trades', 'lo', 'hi', 'p', 'period', 'commit')} == {
        'sharpe': round(s['sharpe'], 2), 'ret_pct': round(100 * s['total_return'], 2), 'trades': doc['total_trades'],
        'lo': round(sig['boot_lo'], 2), 'hi': round(sig['boot_hi'], 2), 'p': round(sig['hac_p'], 3),
        'period': [s['start'], s['end']], 'commit': 'f' * 40}
    assert r['gross_sharpe'] == round(s['gross_sharpe'], 2) and r['gross_lo'] < r['gross_sharpe'] < r['gross_hi']
    assert (r['gross_bp'], r['net_bp']) == (round(s['gross_bp_per_trade']['mean'], 2), round(s['net_bp_per_trade']['mean'], 2))
    assert len(r['paths']['net']) == len(doc['daily_net_returns']) and 'dates' in r['paths']   # its own calendar
    assert {p.split('/')[-1] for p in study['meta']['sources'] if 'residual_dev' in p} == {
        'residual_statarb.json', 'MANIFEST.json'}
    sealed = bsd.build(V32, results_root=tmp_path / 'nothing')
    assert sealed['holdout'] == {'status': 'sealed', 'calendar_start': '2026-01-02'}
    assert sealed['residual'] is None and sealed['validation'] is None


def test_the_residual_arm_is_read_only_as_published(tmp_path, v32_res, residual_export):
    """Pending until results/residual_dev/ holds the export and its MANIFEST.json; an export
    that is not the file the manifest lists stops the build."""
    root = tmp_path / 'results'
    (root / 'residual_dev').mkdir(parents=True)
    shutil.copy(residual_export / 'residual_statarb.json', root / 'residual_dev' / 'residual_statarb.json')
    run = _run_dir(tmp_path, v32_res)
    assert bsd.build(run, results_root=root)['residual'] is None                   # no manifest: unpublished
    shutil.rmtree(root / 'residual_dev')
    published = _publish_residual(tmp_path, residual_export)
    doc = json.loads((published / 'residual_statarb.json').read_text(encoding='utf-8'))
    doc['summary']['sharpe'] = 9.9
    (published / 'residual_statarb.json').write_text(json.dumps(doc), encoding='utf-8')
    with pytest.raises(ValueError, match='is not the file'):
        bsd.build(run, results_root=root)
    # the page labels the arm a development-period run of the registered design
    for key, value in (('run_config', {'study': {'calendar': {'name': 'rehearsal2025'}}}),
                       ('non_default_switches', ['position_frac=0.01'])):
        shutil.rmtree(root / 'residual_dev')
        doc = json.loads((residual_export / 'residual_statarb.json').read_text(encoding='utf-8'))
        doc[key] = value
        other = tmp_path / f'out_{key}'
        other.mkdir()
        (other / 'residual_statarb.json').write_text(json.dumps(doc), encoding='utf-8')
        pr = _load('publish_run')
        pr.ROOT = tmp_path
        pr.publish(other, 'residual_dev', variant=True)
        with pytest.raises(ValueError, match='dev calendar'):
            bsd.build(run, results_root=root)


def test_holdout_strategies_the_runbook_does_not_name_are_kept(tmp_path):
    """A rehearsal's evaluation may hold other, descriptive strategies: they follow the three
    registered ones under their own key, with no export the page knows."""
    root = _holdout_root(tmp_path)

    def extra(ev):
        ev['strategies']['extra_arm'] = copy.deepcopy(ev['strategies']['v32_pairs'])
        ev['inputs']['runs']['extra_arm'] = copy.deepcopy(ev['inputs']['runs']['v32_pairs'])
    _edit_evaluation(root, extra)
    hold, _ = _section(root)
    arms = hold['arms']
    assert [a['key'] for a in arms] == ['v33_pairs', 'avellaneda_lee', 'v32_pairs', 'extra_arm']
    assert arms[-1]['label'] == 'extra_arm' and arms[-1]['hypothesis'] is None and arms[-1]['role'] == 'descriptive'
    assert hold['daily']['cum']['extra_arm'] is None and hold['decision']['family'] == ['v33_pairs', 'avellaneda_lee']


def test_gross_series_gets_its_own_forest_row(v32_res):
    """With the daily gross/cost split (v33 exports) the forest shows the gross-of-cost Sharpe."""
    res = copy.deepcopy(v32_res)
    for d in res['daily_equity_curve']:
        d['cost_pct'] = 0.001
        d['gross_return_pct'] = d['daily_return_pct'] + d['cost_pct']
    daily = bsd.daily_series(res)
    rows = bsd.forest(res, None, daily['gross'])
    assert [r['key'] for r in rows][:3] == ['main', 'gross', 'oos']
    gross = rows[1]
    assert gross['lo'] < gross['sharpe'] < gross['hi'] and gross['days'] == len(daily['dates'])
    assert gross['sharpe'] == pytest.approx(bsd._sharpe(np.asarray(daily['gross']) / 100), abs=1e-3)
    assert gross['sharpe'] > rows[0]['sharpe']                 # costs only ever lower the Sharpe
    assert 'gross' not in [r['key'] for r in bsd.forest(v32_res, None)]


def _evidence_factors(n=600):
    load = {name: {'beta': 0.01 * (i + 1), 'tstat': 1.0 + i, 'variance_share': 0.1}
            for i, name in enumerate(('ST_Rev', 'Mkt-RF', 'SMB', 'HML', 'RMW', 'CMA', 'Mom', 'LT_Rev'))}
    block = {'n': n, 'lags': 6, 'alpha_ann': -0.012, 'alpha_tstat': -0.4, 'r2': 0.08, 'factors': load}
    return {'source': {'truncated_at': '2025-12-31'}, 'main': block, 'walk_forward_oos': copy.deepcopy(block)}


def test_multi_factor_attribution_from_the_evidence_block(v32_res):
    """v33 exports put FF5 + momentum + reversal loadings in evidence.factors; the exhibit shows
    them, while the text's market-proxy beta and alpha keep coming from factor_attribution."""
    plain = bsd.factor_rows(v32_res)
    assert not plain['multi_factor'] and [r['name'] for r in plain['rows']] == ['Market proxy'] * 2
    res = copy.deepcopy(v32_res)
    res['evidence'] = {'factors': _evidence_factors()}
    fac = bsd.factor_rows(res)
    assert fac['multi_factor'] and fac['market'] == plain['market']
    main = [r for r in fac['rows'] if r['series'] == 'Main backtest']
    assert [r['name'] for r in main] == list(bsd.FACTOR_LABELS.values())        # fixed order, readable names
    st_rev = next(r for r in main if r['name'] == 'Short-term reversal')
    assert (st_rev['beta'], st_rev['t']) == (0.01, 1.0)
    assert st_rev['lo'] == pytest.approx(0.01 - 1.96 * 0.01, abs=1e-5)
    assert fac['alpha'][0]['alpha_ann_pct'] == -1.2
    # an unavailable attribution (no factor files) leaves the market-proxy view
    res['evidence'] = {'factors': {'unavailable': 'factor data not loaded'}}
    assert bsd.factor_rows(res)['rows'] == plain['rows']


def test_power_from_the_evidence_block(tmp_path, v32_res):
    """The run's own AR(1)-aware power report is used when no stats battery is committed."""
    res = copy.deepcopy(v32_res)
    res['evidence'] = {'main': {'n': 628, 'sr_ann': -0.07, 'se_ann': 0.66, 'critical_sr_ann': 1.1,
                                'min_detectable_sr_ann': 1.7, 'upper_bound_ann': 1.02, 'skew': 0.17,
                                'kurtosis': 6.7, 'rho': 0.05,
                                'alternatives': [{'sr_ann': x, 'p_sr_at_least': 0.5 / (1 + x), 'min_trl_years': 3 / x}
                                                 for x in (0.5, 1.0, 1.5, 2.0)]}}
    study = bsd.build(_run_dir(tmp_path, res), results_root=tmp_path / 'results')
    power, facts = study['dev']['power'], study['dev']['facts']
    assert power['method'].startswith("the run's evidence block")
    assert (power['mde'], power['ucb'], power['se']) == (1.7, 1.02, 0.66)
    assert (facts['sharpe_mde'], facts['p_sr_ge_1'], facts['min_trl_years_0_5']) == (1.7, 0.25, 6.0)


# ── the checker's study.* markers ──────────────────────────────────────────────

def _checker_site(tmp_path, page_body, site_meta_sha=None):
    headline = tmp_path / 'headline_metrics.json'
    shutil.copy(V32 / 'headline_metrics.json', headline)
    site = {'meta': {'headline_sha256': site_meta_sha or hashlib.sha256(headline.read_bytes()).hexdigest()},
            'dev': {'facts': {'gross_bp': 11.37, 'break_even_x': 0.688}}}
    site_path = tmp_path / 'study.json'
    site_path.write_text(json.dumps(site), encoding='utf-8')
    page = tmp_path / 'index.html'
    page.write_text(f'<html><body><p>{page_body}</p></body></html>', encoding='utf-8')
    return ['--json', str(headline), '--files', str(page), '--site-json', str(site_path), '--allow-missing-markers']


def test_study_markers_resolve_into_the_site_data(tmp_path, capsys):
    body = ('<span data-metric="study.dev.facts.gross_bp">+11.4</span> bp, '
            '<span data-metric="study.dev.facts.break_even_x">0.69</span>x')
    assert chk.main(_checker_site(tmp_path, body)) == 0
    assert 'built from this headline JSON' in capsys.readouterr().out


def test_wrong_study_value_fails(tmp_path, capsys):
    body = '<span data-metric="study.dev.facts.gross_bp">+12.4</span>'
    assert chk.main(_checker_site(tmp_path, body)) == 1
    assert 'study.dev.facts.gross_bp' in capsys.readouterr().out


def test_site_data_from_another_run_fails_every_study_marker(tmp_path, capsys):
    body = ('<span data-metric="study.dev.facts.gross_bp">+11.4</span> '
            '<span data-metric="study.dev.facts.break_even_x">0.69</span> '
            '<span data-metric="main.trades">161</span>')
    assert chk.main(_checker_site(tmp_path, body, site_meta_sha='0' * 64)) == 1
    out = capsys.readouterr().out
    assert '2 study.* marker(s) cannot be checked' in out and 'another headline JSON' in out


def test_missing_site_data_only_matters_to_study_markers(tmp_path, capsys):
    args = _checker_site(tmp_path, '<span data-metric="main.trades">161</span>')
    args[args.index('--site-json') + 1] = str(tmp_path / 'absent.json')
    assert chk.main(args) == 0
    args = _checker_site(tmp_path, '<span data-metric="study.dev.facts.gross_bp">+11.4</span>')
    args[args.index('--site-json') + 1] = str(tmp_path / 'absent.json')
    assert chk.main(args) == 1
    assert 'not found' in capsys.readouterr().out


def test_write_refreshes_study_markers_from_the_site_data(tmp_path):
    body = 'Edge <span data-metric="study.dev.facts.gross_bp">+9.9</span> bp'
    args = _checker_site(tmp_path, body)
    assert chk.main(args) == 1
    assert chk.main(args + ['--write']) == 0
    assert '+11.4' in (tmp_path / 'index.html').read_text(encoding='utf-8')


# ── the v33 run: every committed artefact is read ──────────────────────────────

def test_v33_page_data_comes_from_every_committed_artefact(v33_study):
    sources = v33_study['meta']['sources']
    for name in ('results/v33_dev/headline_metrics.json', 'results/v33_dev/' + RESULTS_NAME,
                 'results/v33_dev/anatomy.json', 'results/v33_dev/cost_sensitivity.json',
                 'results/v33_dev/fund_type_comparison.json', 'results/residual_dev/residual_statarb.json',
                 'results/validation/synthetic_validation.json', 'results/variant_family/declaration.json',
                 'results/v32_dev/headline_metrics.json', 'results/trial_registry.jsonl',
                 'results/variant_family/snooping.json', 'results/variant_family/runs.json',
                 'results/variant_family/daily_returns.csv', 'results/v33_dev/robustness.json'):
        assert name in sources, name
        assert sources[name] == hashlib.sha256((REPO / name).read_bytes()).hexdigest(), name
    dev = v33_study['dev']
    for key in ('shortfall', 'exit_race', 'decay', 'persistence', 'capacity', 'half_lives', 'cost_sensitivity',
                'universe_by_formation', 'random_band', 'cost_curve'):
        assert dev.get(key), key
    assert dev['factors']['multi_factor'] and 'Short-term reversal' in {r['name'] for r in dev['factors']['rows']}
    assert v33_study['residual'] and v33_study['validation'] and v33_study['v32'] and v33_study['trials']
    assert dev['snooping']['results'] and dev['robustness']


def test_facts_have_one_shape_whatever_the_run(v32_study, v33_study):
    """Every fact key exists in every build (null when its source is missing), so a page
    marker names a key that a run without that source still has."""
    assert set(v32_study['dev']['facts']) == set(v33_study['dev']['facts'])
    f32 = v32_study['dev']['facts']
    assert f32['er_targets'] is None and f32['decay_form_bp'] is None and f32['cash_tbill_pct'] is None
    assert v32_study['dev']['cost_sensitivity']['available'] is False
    assert set(v32_study['dev']['cost_sensitivity']['scenarios']) == {k for k, _, _ in bsd.COST_SCENARIOS}


def test_cost_scenarios_are_the_report_and_the_anatomy_side_by_side(v33_study):
    report, anatomy = _json(V33 / 'cost_sensitivity.json'), _json(V33 / 'anatomy.json')
    res = _json(V33 / RESULTS_NAME)
    cs = v33_study['dev']['cost_sensitivity']
    by_label = {s['label']: s for s in report['scenarios']}
    assert cs['available'] and cs['order'] == [k for k, _, _ in bsd.COST_SCENARIOS]
    for key, label, (group, value) in bsd.COST_SCENARIOS:
        row, src = cs['scenarios'][key], by_label[label]
        assert (row['full']['trades'], row['full']['sharpe']) == (src['trades'], round(src['sharpe'], 4)), key
    # the headline row is the run itself; the full re-runs change the trades, the re-pricing does not
    assert cs['scenarios']['headline']['full']['trades'] == res['overall_performance']['total_trades']
    assert cs['trades_min'] == min(s['trades'] for s in report['scenarios'])
    assert cs['trades_max'] == max(s['trades'] for s in report['scenarios']) > cs['trades_min']
    impact = {s['coefficient']: s for s in anatomy['gross_vs_net']['impact_sensitivity']['scenarios']}
    assert cs['scenarios']['impact_1_0']['fixed']['sharpe'] == round(impact[1.0]['sharpe'], 4)
    cap = {r['aum_musd']: r for r in anatomy['capacity']}
    assert cs['scenarios']['capital_5b']['fixed']['net_bp'] == round(cap[5000.0]['net_bp'], 2)


def test_a_cost_report_of_another_run_stops_the_build():
    report, res = _json(V33 / 'cost_sensitivity.json'), _json(V33 / RESULTS_NAME)
    other = copy.deepcopy(report)
    other['scenarios'][0]['trades'] += 1
    with pytest.raises(ValueError, match='not a scenario report of this run'):
        bsd.cost_scenarios(other, res, {})
    other = copy.deepcopy(report)
    other['calendar'] = 'rehearsal2025'
    with pytest.raises(ValueError, match='not a scenario report of this run'):
        bsd.cost_scenarios(other, res, {})
    absent = bsd.cost_scenarios(None, res, {})
    assert not absent['available'] and absent['scenarios']['impact_0_6']['full']['sharpe'] is None
    # without a re-pricing the headline row still carries the run's own numbers
    assert absent['scenarios']['headline']['fixed']['sharpe'] == round(res['overall_performance']['sharpe_ratio'], 4)


def test_anatomy_facts_are_the_anatomy_numbers(v33_study):
    a, f = _json(V33 / 'anatomy.json'), v33_study['dev']['facts']
    er = a['exit_race']
    assert (f['er_targets'], f['er_stops']) == (er['targets'], er['stops'])
    assert f['er_rw_expected'] == round(er['nulls']['random_walk']['expected_targets'], 1)
    assert f['er_ou_expected'] == round(er['nulls']['ou']['expected_targets'], 1)
    form, oos = a['decay'][0], a['decay'][1]
    assert (f['decay_form_bp'], f['decay_form_n']) == (round(form['bp'], 2), form['n'])
    assert (f['decay_oos_bp'], f['decay_oos_t']) == (round(oos['bp'], 2), round(oos['t'], 2))
    pooled = a['persistence_detail']['clegg']['pooled_still_cointegrated']
    assert (f['pers_count'], f['pers_of']) == (pooled['count'], pooled['of'])
    assert f['pers_expected_pct'] == round(100 * pooled['expected_at_next_year_base_rates'] / pooled['of'], 2)
    sf = a['shortfall_detail']['totals']
    assert f['sf_paper_usd_k'] == round(sf['paper']['usd'] / 1e3, 1)
    assert f['sf_exit_delay_loss_usd_k'] == round(sf['exit_delay']['usd'] / 1e3, 1)
    # the shortfall closes: paper + delays = gross; gross - costs = net
    steps = {s['key']: s['usd'] for s in v33_study['dev']['shortfall']}
    assert steps['paper'] + steps['entry_delay'] + steps['exit_delay'] == pytest.approx(steps['gross'], abs=0.02)
    assert f['cash_tbill_pct'] == round(a['cash']['tbill_return_pct'], 2)
    assert f['gross_usd_k'] == pytest.approx(a['gross_vs_net']['totals']['gross_usd'] / 1e3, abs=0.05)


def test_evidence_facts_and_the_holdout_power(v33_study):
    ev, f = _json(V33 / RESULTS_NAME)['evidence'], v33_study['dev']['facts']
    assert f['hurdle_hlz'] == round(ev['hurdles']['hurdles']['hlz']['sr_ann'], 4)
    assert f['st_rev_t_main'] == round(ev['factors']['main']['factors']['ST_Rev']['tstat'], 2)
    assert f['tbill_rf_pct'] == round(ev['factors']['cash']['tbill_return_pct'], 2)
    assert f['oos_ucb'] == round(ev['walk_forward_oos']['upper_bound_ann'], 4)
    assert v33_study['dev']['power']['hurdles']['hlz'] == f['hurdle_hlz']
    # what the holdout can detect, from the development returns' shape: more power at a
    # larger true Sharpe, and a stricter level needs a larger Sharpe
    assert f['ho_days'] == bsd.HOLDOUT_SESSIONS
    assert f['ho_power_1'] < f['ho_power_2'] < f['ho_power_3']
    assert f['ho_mde_05'] < f['ho_mde_025'] and f['ho_mde_05_normal'] < f['ho_mde_025_normal']
    m = ev['main']
    assert f['ho_mde_025'] == round(bsd.pw.minimum_detectable_sharpe(
        0.0, bsd.HOLDOUT_SESSIONS, m['skew'], m['kurtosis'], m['rho'], alpha=0.025) * math.sqrt(252), 2)
    assert all(v is None for k, v in bsd.holdout_power_facts({}).items() if k != 'ho_days')


def test_path_facts_compare_the_two_series_on_their_common_days():
    res = _json(V33 / RESULTS_NAME)
    pf = bsd.path_facts(res)
    main = {d['date']: d['daily_return_pct'] for d in res['daily_equity_curve']}
    wf = {d['date']: d['daily_return_pct'] for d in res['walk_forward_daily']}
    common = sorted(set(main) & set(wf))
    assert pf['common_days'] == len(common)
    a, b = np.array([main[d] for d in common]), np.array([wf[d] for d in common])
    assert pf['common_corr'] == round(float(np.corrcoef(a, b)[0, 1]), 2)
    assert pf['common_sharpe_oos'] == round(bsd._sharpe(b / 100), 2)
    assert bsd.path_facts({})['common_days'] is None


def test_v32_section_is_the_published_run(v33_study):
    v32, head = v33_study['v32'], _json(V32 / 'headline_metrics.json')
    res = _json(V32 / RESULTS_NAME)
    assert v32['run']['commit'] == head['run_config']['git_commit']
    assert (v32['main']['sharpe'], v32['main']['trades'], v32['oos']['sharpe']) == (
        head['main']['sharpe'], head['main']['trades'], head['oos']['pooled_sharpe'])
    assert v32['gate_blocked_days'] == res['overall_performance']['signal_rejections']['regime_hard_stop_day']
    assert v32['flat_days'] == sum(1 for p in bsd.daily_series(res)['positions'] if p == 0)


def test_trials_list_every_registered_run_in_order(v33_study):
    lines = [json.loads(x) for x in (REPO / 'results' / bsd.REGISTRY).read_text().splitlines() if x.strip()]
    rows = v33_study['trials']
    assert len(rows) == sum(max(1, len(e['runs'])) for e in lines)
    assert [r['name'] for r in rows] == [e['name'] for e in lines for _ in range(max(1, len(e['runs'])))]
    head = _json(V33 / 'headline_metrics.json')
    v33 = next(r for r in rows if r['name'] == 'v33_dev')
    assert (v33['sharpe'], v33['trades'], v33['oos_sharpe']) == (head['main']['sharpe'], head['main']['trades'],
                                                                  head['oos']['pooled_sharpe'])
    # a trial registered without a run record keeps one row, with its run fields null
    empty = bsd.trials([{'name': 'x', 'registered_utc': '2026-10-21T00:00:00+00:00', 'runs': []}])
    assert len(empty) == 1 and empty[0]['sharpe'] is None and empty[0]['registered'] == '2026-10-21'
    assert bsd.trials(None) is None
    # trials (lines), the run records they hold, and the table's rows (a trial without a run
    # record keeps one row): the rows are not runs
    assert v33_study['registry'] == {'trials': len(lines), 'recorded_runs': sum(len(e['runs']) for e in lines),
                                     'rows': len(rows)}


# ── the declared variant family ────────────────────────────────────────────────

def test_snooping_results_are_the_family_files(v33_study):
    """Every number of the family's section is snooping.json's or runs.json's; the v33 design
    is the variant whose daily returns are the main backtest's."""
    sn = v33_study['dev']['snooping']['results']
    rep = _json(REPO / 'results' / 'variant_family' / 'snooping.json')
    runs = _json(REPO / 'results' / 'variant_family' / 'runs.json')['variants']
    fam = rep['family']
    assert sn['n'] == len(runs) == len(fam['members']) == v33_study['dev']['snooping']['grid_points'] + \
        v33_study['dev']['snooping']['toggles']
    assert sn['spa_zero']['p'] == round(fam['spa_vs_zero']['pvalues']['consistent'], 4)
    assert sn['spa_zero']['rc_p'] == round(fam['spa_vs_zero']['reality_check']['pvalue'], 4)
    assert sn['spa_gatev']['p'] == round(fam['spa_vs_gatev']['pvalues']['consistent'], 4)
    assert sn['rw_rejected'] == len(fam['romano_wolf_vs_zero']['rejected'])
    assert sn['mcs_included'] == len(fam['mcs']['included'])
    assert sn['pbo_pct'] == round(100 * rep['pbo']['pbo'], 2)
    assert sn['effective_rank'] == round(fam['effective_trials']['effective_rank'], 2)
    sharpes = sorted(v['sharpe'] for v in runs)
    assert sn['positive'] == sum(x > 0 for x in sharpes) and sn['sharpe_best'] == round(sharpes[-1], 4)
    assert sn['sharpe_median'] == round(float(np.median(sharpes)), 4)
    head = _json(V33 / 'headline_metrics.json')
    base = [v for v in sn['variants'] if v['base']]
    assert len(base) == 1 and round(base[0]['sharpe'], 2) == head['main']['sharpe']
    assert sn['base_rank'] == 1 + sum(x > base[0]['sharpe'] for x in sharpes)
    # the declared deflation: N = the effective rank rounded up, the variants' Sharpe dispersion
    assert sn['dsr']['n_trials'] == math.ceil(fam['effective_trials']['effective_rank'])
    assert 0 < sn['dsr']['dsr_pct'] < 100 * sn['dsr']['curve'][0]['dsr']
    # the deflation the DSR is defined for: the family's best variant, same N and variance
    assert sn['dsr_best']['n_trials'] == sn['dsr']['n_trials'] and sn['dsr_best']['sharpe'] == sn['sharpe_best']
    assert sn['dsr']['dsr_pct'] < sn['dsr_best']['dsr_pct'] < sn['dsr_best']['psr_pct']
    # PBO's loss rate beside the same splits' rate for every variant: selection makes it worse
    assert 50 < sn['pbo_base_loss_pct'] < sn['pbo_is_best_loss_pct']
    assert sn['pbo_is_best_oos_sharpe'] < sn['pbo_median_oos_sharpe'] < 0


def test_cscv_baseline_rebuilds_the_pbo_splits():
    """The baseline uses pbo_cscv's splits: it reproduces the in-sample best's numbers, and a
    PBO computed on other splits stops the build."""
    from pairs_trading.significance import pbo_cscv
    rng = np.random.default_rng(3)
    M = rng.normal(0.0, 0.01, size=(400, 12)) + np.linspace(-2e-4, 2e-4, 12)
    pbo = pbo_cscv(M, n_splits=8)
    base = bsd.cscv_baseline(M, pbo, 8)
    assert 0.0 < base['loss_pct'] < 100.0
    # a variant picked without looking: the median variant's out-of-sample Sharpe, split by split
    assert abs(base['median_oos_sharpe']) < 5.0
    with pytest.raises(ValueError, match='do not reproduce'):
        bsd.cscv_baseline(M, pbo_cscv(M, n_splits=6), 8)


def test_snooping_files_that_disagree_stop_the_build(v33_study):
    decl = _json(REPO / 'results' / 'variant_family' / 'declaration.json')
    rep = _json(REPO / 'results' / 'variant_family' / 'snooping.json')
    runs = _json(REPO / 'results' / 'variant_family' / 'runs.json')
    rows = [{'date': '2023-07-03', **{v['name']: '0.001' for v in runs['variants']}},
            {'date': '2023-07-05', **{v['name']: '-0.001' for v in runs['variants']}}]
    other = copy.deepcopy(runs)
    other['variants'] = other['variants'][::-1]
    with pytest.raises(ValueError, match='same declared variants'):
        bsd.snooping(decl, rep, other, rows)
    absent = bsd.snooping(decl, None, runs, rows)
    assert absent['results'] is None and absent['grid_points'] == 27


# ── the robustness checks ──────────────────────────────────────────────────────

def test_robustness_section_is_the_runs_robustness_json(v33_study):
    rob = _json(V33 / 'robustness.json')
    r, f = v33_study['dev']['robustness'], v33_study['dev']['facts']
    sharpes = [x['sharpe'] for x in rob['start_dates']['runs']]
    assert [x['sharpe'] for x in r['start_dates']['runs']] == [round(x, 4) for x in sharpes]
    assert r['start_dates']['headline_rank'] == 1 + sum(x > sharpes[0] for x in sharpes)
    assert f['start_sharpe_median'] == round(float(np.median(sharpes)), 4)
    assert f['vix_diff_t'] == round(rob['regimes']['vix']['net']['last_minus_first']['nw_t'], 4)
    pooled = rob['persistence']['first_formation']['pooled_still_cointegrated']
    assert (f['pers_s1_count'], f['pers_s1_of']) == (pooled['count'], pooled['of'])
    assert f['s2c_gross_month_t'] == round(rob['s2_trade_edge']['gross_bp']['entry_month']['t_clustered'], 4)
    # the independent-trades t is the export's, which the residual section also quotes
    assert round(f['s2c_gross_t'], 2) == v33_study['residual']['gross_t']
    # like for like: each later start against the published path on that start's own days
    curve = _json(V33 / RESULTS_NAME)['daily_equity_curve']
    dates = [c['date'] for c in curve]
    r_pub = np.array([c['daily_return_pct'] / 100.0 for c in curve])
    m = r['start_dates']['matched']
    gaps = []
    for run, row in zip(rob['start_dates']['runs'], r['start_dates']['runs']):
        sub = r_pub[[run['first_day'] <= d <= run['last_day'] for d in dates]]
        assert sub.size == run['days']
        pub = sub.mean() / sub.std(ddof=1) * math.sqrt(252)
        assert row['published_sharpe'] == round(pub, 4)
        if run['offset_trading_days'] > 0:
            gaps.append(pub - run['sharpe'])
    assert (m['of'], m['wins']) == (len(gaps), sum(g > 0 for g in gaps))
    assert m['gap_median'] == round(float(np.median(gaps)), 4)
    # the published start's own row: its window is the published run's, so the two agree
    assert r['start_dates']['runs'][0]['published_sharpe'] == r['start_dates']['runs'][0]['sharpe']
    common = [x['common_window']['sharpe'] for x in rob['start_dates']['runs']]
    assert r['start_dates']['common_rank'] == f['start_common_rank'] == 1 + sum(c > common[0] for c in common)


def _shape(x):
    """Keys and list lengths of a nested structure, leaves dropped."""
    if isinstance(x, dict):
        return {k: _shape(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_shape(v) for v in x] if x and isinstance(x[0], (dict, list)) else 'list'
    return None


def test_a_robustness_report_of_another_export_or_shape_stops_the_build(v33_study):
    rob = _json(V33 / 'robustness.json')
    with pytest.raises(ValueError, match='another results export'):
        bsd.robustness(rob, '0' * 64)
    sha = hashlib.sha256((V33 / RESULTS_NAME).read_bytes()).hexdigest()
    short = copy.deepcopy(rob)
    short['start_dates']['runs'] = short['start_dates']['runs'][:-1]
    with pytest.raises(ValueError, match='expects'):
        bsd.robustness(short, sha)
    # without robustness.json: the same keys and list lengths with null values, so that every
    # page marker names a key that every build has
    skeleton = bsd.robustness(None, sha)
    real = v33_study['dev']['robustness']
    assert skeleton['available'] is False and real['available'] is True
    assert _shape(skeleton) == _shape(real)
    assert all(v is None for v in bsd.robustness_facts(skeleton).values())
    assert all(v is None for v in bsd.robustness_facts(None).values())


# ── the evaluated holdout ──────────────────────────────────────────────────────

def test_the_sealed_holdout_is_unchanged(tmp_path):
    """Until results/holdout2026/evaluation.json exists the section is the sealed stub, and the
    attempt record is not read (the sealed build has no new source). The committed file is the
    stub while no evaluation is committed, and the evaluated holdout once one is."""
    assert bsd.holdout_section(None) == {'status': 'sealed', 'calendar_start': '2026-01-02'}
    committed = _json(REPO / 'assets' / 'study.json')['holdout']
    if (REPO / 'results' / 'holdout2026' / 'evaluation.json').is_file():
        assert committed['status'] == 'complete' and committed['trial'] == 'holdout2026'
    else:
        assert committed == bsd.holdout_section(None)
    root = tmp_path / 'results'
    root.mkdir()
    (root / 'trial_attempts.jsonl').write_text('{"name": "holdout2026", "event": "start"}\n', encoding='utf-8')
    src = bsd.Sources(REPO, root)
    assert bsd.holdout_section(None, src, root, None)['status'] == 'sealed' and src.hashes == {}


def _strings(x):
    if isinstance(x, dict):
        return {s for v in x.values() for s in _strings(v)}
    if isinstance(x, list):
        return {s for v in x for s in _strings(v)}
    return {x} if isinstance(x, str) else set()


def test_the_evaluated_holdout_is_the_evaluation(tmp_path):
    """Every arm's numbers are the evaluation's, rounded; the decision is its own; the daily
    paths compound the published exports; the run record is the registry's and the attempts'."""
    root = _holdout_root(tmp_path)
    hold, src = _section(root)
    ev = _json(root / 'holdout2026' / 'evaluation.json')
    assert {k: hold[k] for k in ('status', 'trial', 'alpha', 'test', 'calendar', 'calendar_hash', 'calendar_start',
                                 'calendar_end', 'period_matches_calendar', 'family')} == {
        'status': 'complete', 'trial': 'holdout2026', 'alpha': 0.05, 'test': ev['test'], 'calendar': 'rehearsal2025',
        'calendar_hash': ev['inputs']['calendar_hash'], 'calendar_start': '2025-01-02', 'calendar_end': '2025-10-17',
        'period_matches_calendar': True, 'family': ['v33_pairs', 'avellaneda_lee']}
    assert hold['decision'] == {'alpha': 0.05, 'family': ['v33_pairs', 'avellaneda_lee'], 'rejected': [], 'arms': {
        'v33_pairs': {'hypothesis': 'H1', 'edge': False, 'p_holm': 1.0, 'p_holm_below_alpha': False},
        'avellaneda_lee': {'hypothesis': 'H2', 'edge': False, 'p_holm': 1.0, 'p_holm_below_alpha': False}}}
    for arm in hold['arms']:
        s = ev['strategies'][arm['key']]
        assert arm['role'] == s['role'] and arm['flat'] is False and arm['lags'] == s['lags'] == 4
        ci = s['bootstrap_ci_95']
        expect = {'sharpe': s['sharpe'], 'lo': ci[0], 'hi': ci[1], 'ret_pct': s['total_return_pct'],
                  'gross_ret_pct': s['gross_total_return_pct'], 'gross_sharpe': s['gross_sharpe'],
                  'sharpe_se': s['sharpe_se'], 'ucb': s['upper_bound_95'], 'sharpe_lo2002': s['sharpe_lo2002'],
                  'mde': s['min_detectable_sharpe'], 'mde_single': s['min_detectable_sharpe_single_test'],
                  'mde_alpha': s['min_detectable_sharpe_alpha']}
        assert {k: arm[k] for k in expect} == {k: round(v, 4) for k, v in expect.items()}
        assert (arm['t'], arm['p_one_sided'], arm['psr_pct']) == (round(s['t'], 3), round(s['p_one_sided'], 4),
                                                                  round(100 * s['psr'], 2))
        assert (arm['days'], arm['trades'], arm['period'], arm['commit']) == (s['days'], s['trades'], s['period'], RUN_COMMIT)
        assert arm['run_utc'] == ev['inputs']['runs'][arm['key']]['provenance']['run_timestamp_utc']
        assert arm['exposure'] == {'avg_pct': round(s['exposure']['avg_gross_pct_of_equity'], 3),
                                   'max_pct': round(s['exposure']['max_gross_pct_of_equity'], 3),
                                   'days_open': s['exposure']['days_with_open_positions']}
        assert (arm['vs_gatev']['p'], arm['vs_gatev']['days']) == (round(s['vs_gatev']['pvalue'], 4),
                                                                   s['vs_gatev']['n_common_days'])
        assert arm['random_pair']['percentile'] == s['random_pair']['percentile']
        # the survivorship gap, without the security names the report lists
        rows = s['universe_by_formation']
        assert len(arm['universe']) == len(rows)
        assert [u['missing_weight_pct'] for u in arm['universe']] == [round(100 * u['missing_value_weight'], 3) for u in rows]
        names = {n for u in rows for k in ('missing_heaviest', 'unmapped_heaviest', 'no_sector_etf_heaviest')
                 for n, _ in u.get(k) or []}
        assert not names & _strings(arm['universe'])
    v33, s2, s3 = hold['arms']
    assert s3['universe'] == [] and s3['p_holm'] is None and s3['edge'] is None and s3['p_holm_below_alpha'] is None
    assert all(u['no_sector_etf'] is not None for u in s2['universe']) and v33['universe'][0]['no_sector_etf'] is None
    curve = _json(REHEARSAL / 'v33_pairs' / RESULTS_NAME)['daily_equity_curve']
    assert hold['daily']['dates'] == [d['date'] for d in curve]
    assert hold['daily']['cum']['v33_pairs'][:2] == [0.0, round(curve[1]['daily_return_pct'], 4)]
    for arm in hold['arms']:
        assert hold['daily']['cum'][arm['key']][-1] == pytest.approx(arm['ret_pct'], abs=1e-4)
    p = hold['provenance']
    assert (p['commit'], p['expect_commit'], p['registered_commit'], p['at_registered_commit'], p['clean'],
            p['crash_fix'], p['crash_fix_diffs']) == (RUN_COMMIT, RUN_COMMIT, RUN_COMMIT, True, True, None, [])
    assert p['run_commits'] == dict.fromkeys(['v33_pairs', 'avellaneda_lee', 'v32_pairs'], RUN_COMMIT)
    assert (p['n_attempts'], p['n_failed'], p['completed_utc']) == (1, 0, '2026-10-21T14:03:09+00:00')
    # the registry line copies the 7 attempt lines; the file adds the completion line
    assert (p['n_unfinished'], p['attempt_record_lines']) == (0, 8)
    steps = ['universe', 'data', 'v33', 'v32', 'residual', 'evaluate']
    assert p['attempts'][0]['steps_done'] == steps and p['step_attempts'] == dict.fromkeys(steps, 1)
    assert p['registry'] == {'name': 'holdout2026', 'head': RUN_COMMIT, 'prereg_commit': RUN_COMMIT,
                             'registered_utc': '2026-10-21T14:03:09+00:00', 'attempt_lines': 7, 'note': None}
    assert p['logs'] == {'count': 7, 'step_logs': 6, 'environment': 1, 'diffs': 0, 'by_attempt': [
        {'attempt': 1, 'steps': ['data', 'evaluation', 'residual', 'universe', 'v32', 'v33']}]}
    assert (p['price_fetch']['end'], p['price_fetch']['symbols'], p['price_fetch']['top_ups']) == ('2025-10-17', 3000, 1)
    assert {f'results/holdout2026/{f}' for f in ('evaluation.json', 'price_fetch_manifest.json',
                                                 'v33_pairs/headline_metrics.json', 'residual/residual_statarb.json',
                                                 f'v32_pairs/{RESULTS_NAME}', 'v32_pairs/MANIFEST.json')} | {
        'results/trial_attempts.jsonl', 'results/trial_registry.jsonl'} <= set(src.hashes)
    json.dumps(hold, allow_nan=False)


def test_the_holdout_in_a_full_build_and_from_the_command_line(tmp_path, v32_res):
    """--results points the builder at another results tree (its sources keep their results/
    names); the evaluation must be on --holdout-calendar (default holdout2026)."""
    root = _holdout_root(tmp_path)
    run = _run_dir(tmp_path, v32_res)
    study = bsd.build(run, results_root=root, holdout_calendar=REHEARSAL_CALENDAR)
    hold = study['holdout']
    assert hold['status'] == 'complete' and 'results/holdout2026/evaluation.json' in study['meta']['sources']
    # the holdout's runs are the newest dated input
    assert study['meta']['generated_utc'] == max(hold['provenance']['run_utc'].values())
    assert [r['name'] for r in study['trials']] == ['holdout2026'] * 3 and study['registry']['trials'] == 1
    out = tmp_path / 'study.json'
    assert bsd.main(['--dev', str(run), '--results', str(root), '--holdout-calendar', REHEARSAL_CALENDAR,
                     '--out', str(out)]) == 0
    assert out.read_text(encoding='utf-8') == bsd.dumps(study)
    with pytest.raises(bsd.HoldoutRecordError, match='calendar'):
        bsd.build(run, results_root=root)


@pytest.mark.parametrize('p_holm, edge', [(0.0496, True), (0.049996, True), (0.05, False), (0.0504, False)])
def test_the_decision_is_the_evaluations(tmp_path, p_holm, edge):
    """Not recomputed: edge_out_of_sample as the report states it, which must be p_holm < alpha.
    p_holm_below_alpha compares the unrounded p, so a p below alpha that the file rounds to it
    (0.049996 -> 0.05) is still below it, and a p at alpha is not."""
    root = _holdout_root(tmp_path)
    _edit_evaluation(root, lambda ev: ev['strategies']['v33_pairs'].update(p_holm=p_holm, edge_out_of_sample=edge))
    hold, _ = _section(root)
    v33 = hold['arms'][0]
    assert hold['decision']['rejected'] == (['v33_pairs'] if edge else [])
    assert v33['edge'] is edge and v33['p_holm_below_alpha'] is edge
    assert hold['decision']['arms']['v33_pairs'] == {'hypothesis': 'H1', 'edge': edge, 'p_holm': round(p_holm, 4),
                                                     'p_holm_below_alpha': edge}


def test_both_hypotheses_rejected(tmp_path):
    root = _holdout_root(tmp_path)

    def edit(ev):
        ev['strategies']['v33_pairs'].update(p_holm=0.012, edge_out_of_sample=True)
        ev['strategies']['avellaneda_lee'].update(p_holm=0.031, edge_out_of_sample=True)
    _edit_evaluation(root, edit)
    hold, _ = _section(root)
    assert hold['decision']['rejected'] == ['v33_pairs', 'avellaneda_lee']
    assert [a['p_holm_below_alpha'] for a in hold['arms']] == [True, True, None]


def _set(key, **fields):
    return lambda ev: ev['strategies'][key].update(fields)


def _drop(*path):
    def edit(ev):
        for part in ('strategies', 'inputs'):
            (ev[part]['runs'] if part == 'inputs' else ev[part]).pop(path[0], None)
    return edit


@pytest.mark.parametrize('edit, match', [
    (_set('v33_pairs', edge_out_of_sample=True), 'edge_out_of_sample is True'),
    (_set('v33_pairs', p_holm=0.01), 'edge_out_of_sample is False'),
    (_set('v33_pairs', p_holm=0.05, edge_out_of_sample=True), 'not below alpha'),
    (_set('avellaneda_lee', p_holm=None), 'confirmatory but has p_holm None'),
    (_set('avellaneda_lee', edge_out_of_sample=None), 'confirmatory but'),
    (_set('v32_pairs', p_holm=0.3), 'descriptive but carries'),
    (_set('v32_pairs', edge_out_of_sample=False), 'descriptive but carries'),
    (_set('v32_pairs', role='confirmatory'), "v32_pairs: role 'confirmatory'"),
    (_set('v33_pairs', role='descriptive'), "v33_pairs: role 'descriptive'"),
    (lambda ev: ev.update(family=['v33_pairs']), 'family'),
    (lambda ev: ev.update(family=['v33_pairs', 'avellaneda_lee', 'v32_pairs']), 'family'),
    (lambda ev: ev.update(alpha=0.1), 'alpha'),
    (_drop('avellaneda_lee'), 'lacks the registered'),
])
def test_a_decision_that_contradicts_the_registration_stops_the_build(tmp_path, edit, match):
    root = _holdout_root(tmp_path)
    _edit_evaluation(root, edit)
    with pytest.raises(bsd.HoldoutRecordError, match=match):
        _section(root)


@pytest.mark.parametrize('key', ['v32_pairs', 'v33_pairs'])
def test_an_arm_that_never_trades(tmp_path, key):
    """A pairs run that opens no position is a result, not a crash: t = 0 and p = 0.5 (S1 tested,
    S3 not); its Sharpe ratio is undefined (null, not the report's convention 0.0), and so are
    the statistics the report leaves null for a series without dispersion."""
    root = _holdout_root(tmp_path)
    _flatten(root, key)
    hold, _ = _section(root)
    arm = next(a for a in hold['arms'] if a['key'] == key)
    assert arm['flat'] is True and arm['trades'] == 0 and (arm['t'], arm['lags'], arm['p_one_sided']) == (0.0, 0, 0.5)
    assert all(arm[k] is None for k in ('sharpe', 'lo', 'hi', 'sharpe_se', 'ucb', 'psr_pct', 'sharpe_lo2002', 'mde',
                                        'mde_single', 'gross_sharpe'))
    assert (arm['ret_pct'], arm['gross_ret_pct']) == (0.0, 0.0) and set(hold['daily']['cum'][key]) == {0.0}
    assert hold['decision']['rejected'] == [] and not any(a['flat'] for a in hold['arms'] if a['key'] != key)
    if key == 'v33_pairs':
        assert (arm['p_holm'], arm['edge'], arm['p_holm_below_alpha']) == (1.0, False, False)
    else:
        assert (arm['role'], arm['p_holm'], arm['edge'], arm['p_holm_below_alpha']) == ('descriptive', None, None, None)
    json.dumps(hold, allow_nan=False)


def test_optional_fields_the_evaluation_lacks_are_null(tmp_path):
    root = _holdout_root(tmp_path)

    def edit(ev):
        for s in ev['strategies'].values():
            for k in ('psr', 'sharpe_lo2002', 'gross_sharpe', 'gross_total_return_pct', 'exposure', 'vs_gatev',
                      'random_pair', 'universe_by_formation', 'min_detectable_sharpe_single_test'):
                s.pop(k, None)
    _edit_evaluation(root, edit)
    for arm in _section(root)[0]['arms']:
        assert all(arm[k] is None for k in ('psr_pct', 'sharpe_lo2002', 'gross_sharpe', 'gross_ret_pct', 'exposure',
                                            'vs_gatev', 'random_pair', 'universe', 'mde_single'))
        assert arm['sharpe'] is not None


def test_the_attempt_record_must_be_the_registry_lines(tmp_path):
    """results/trial_attempts.jsonl's lines for the trial are the registry line's attempts, then
    at most the completion line; a stale, extended or edited copy stops the build."""
    root = _holdout_root(tmp_path)
    path = root / 'trial_attempts.jsonl'
    lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
    for bad in (lines[:-2], lines + [lines[0]], [lines[0].replace('"attempt": 1', '"attempt": 2')] + lines[1:]):
        path.write_text(''.join(bad), encoding='utf-8')
        with pytest.raises(bsd.HoldoutRecordError, match='disagree'):
            _section(root)
    other = json.dumps({'attempt': 1, 'event': 'start', 'head': RUN_COMMIT, 'name': 'another_trial', 'utc': 'x'})
    path.write_text(other + '\n' + ''.join(lines), encoding='utf-8')
    assert _section(root)[0]['provenance']['n_attempts'] == 1          # another trial's lines are not this one's
    path.write_text(''.join(lines[:-1]), encoding='utf-8')
    p = _section(root)[0]['provenance']                                # no completion line: nothing said of it
    assert p['completed_utc'] is None and p['attempt_record_lines'] == p['registry']['attempt_lines'] == 7
    path.unlink()
    with pytest.raises(bsd.HoldoutRecordError, match='missing'):
        _section(root)


def test_the_registry_line_must_be_this_evaluations(tmp_path):
    root = _holdout_root(tmp_path)
    reg = root / 'trial_registry.jsonl'
    line = reg.read_text(encoding='utf-8')
    entry = json.loads(line)
    for text, match in (('', 'not one'), (line + line, 'not one'),
                        (json.dumps(dict(entry, prereg_commit=None)) + '\n', 'no registered commit'),
                        (json.dumps(dict(entry, head='0' * 40)) + '\n', 'not the evaluated runs'),
                        (json.dumps(dict(entry, runs=[])) + '\n', 'not the evaluated runs')):
        reg.write_text(text, encoding='utf-8')
        with pytest.raises(bsd.HoldoutRecordError, match=match):
            _section(root)
    reg.write_text(line, encoding='utf-8')
    _edit_evaluation(root, _set('v32_pairs', sharpe=0.5), register=False)       # edited after registration
    with pytest.raises(bsd.HoldoutRecordError, match='another evaluation'):
        _section(root)


@pytest.mark.parametrize('edit, match', [
    (lambda ev: ev['inputs']['runs']['v32_pairs']['provenance'].update(git_commit='0' * 40), 'not from one commit'),
    (lambda ev: ev['inputs'].update(expect_commit='0' * 40), 'expected commit'),
    (lambda ev: ev['inputs'].update(calendar='holdout2026'), 'calendar'),
    (lambda ev: ev['inputs'].update(calendar_hash='0' * 12), 'calendar'),
    (lambda ev: ev['inputs'].update(period_matches_calendar=False), 'period_matches_calendar'),
    (lambda ev: ev['inputs']['runs'].pop('v32_pairs'), 'inputs list the runs'),
])
def test_runs_and_calendar_that_are_not_the_evaluations_stop_the_build(tmp_path, edit, match):
    root = _holdout_root(tmp_path)
    _edit_evaluation(root, edit)
    with pytest.raises(bsd.HoldoutRecordError, match=match):
        _section(root)


def test_a_period_shorter_than_the_calendar_and_no_published_exports(tmp_path):
    """Days inside the calendar that do not span it are reported, not refused; without the
    published exports there is no daily series."""
    root = _holdout_root(tmp_path)
    for sub in ('v33_pairs', 'v32_pairs', 'residual'):
        shutil.rmtree(root / 'holdout2026' / sub)

    def edit(ev):
        for s in ev['strategies'].values():
            s['period'][0] = '2025-01-03'
        ev['inputs']['period_matches_calendar'] = False
    _edit_evaluation(root, edit)
    hold, _ = _section(root)
    assert hold['period_matches_calendar'] is False and hold['daily'] is None


def test_the_daily_series_are_the_evaluated_exports(tmp_path):
    root = _holdout_root(tmp_path)
    hold = root / 'holdout2026'
    shutil.rmtree(hold / 'v32_pairs')                     # not published: that arm alone has no series
    cum = _section(root)[0]['daily']['cum']
    assert cum['v32_pairs'] is None and cum['v33_pairs'] and cum['avellaneda_lee']
    path = hold / 'v33_pairs' / RESULTS_NAME
    original = path.read_bytes()
    path.write_bytes(original + b' ')                     # not the file the evaluation read
    with pytest.raises(bsd.HoldoutRecordError, match='not the ones the evaluation read'):
        _section(root)
    path.write_bytes(original)
    (hold / 'v33_pairs' / 'MANIFEST.json').unlink()       # published without its manifest
    with pytest.raises(bsd.HoldoutRecordError, match='MANIFEST'):
        _section(root)
    shutil.copy(REHEARSAL / 'v33_pairs' / 'MANIFEST.json', hold / 'v33_pairs' / 'MANIFEST.json')
    _edit_evaluation(root, _set('v33_pairs', total_return_pct=-2.0))   # not what the export compounds to
    with pytest.raises(bsd.HoldoutRecordError, match='the evaluation reports'):
        _section(root)


def test_a_failed_attempt_run_again_at_the_same_commit(tmp_path):
    """Commitment 1: a failure outside the code is run again at the registered commit; a step an
    earlier attempt finished is skipped and keeps that attempt's number."""
    failed = {'attempt': 1, 'event': 'failed', 'name': 'holdout2026', 'note': 'exit 1', 'step': 'data',
              'utc': '2026-10-21T11:30:02+00:00'}
    root = _holdout_root(tmp_path, attempts=_attempt_lines(steps=('universe',)) + [failed] + _attempt_lines(
        attempt=2, steps=('data', 'v33', 'v32', 'residual', 'evaluate')))
    p = _section(root)[0]['provenance']
    assert (p['at_registered_commit'], p['crash_fix'], p['n_attempts'], p['n_failed'], p['n_unfinished']) == (
        True, None, 2, 1, 0)
    assert [a['at_registered_commit'] for a in p['attempts']] == [True, True]
    assert p['attempts'][0]['failed'] == {'step': 'data', 'note': 'exit 1', 'utc': '2026-10-21T11:30:02+00:00'}
    assert p['step_attempts'] == {'universe': 1, 'data': 2, 'v33': 2, 'v32': 2, 'residual': 2, 'evaluate': 2}


def _crash_fix_root(tmp_path):
    """Attempt 1 at the registered commit fails in S1's step; attempt 2 at a crash-fix commit
    (the runs' commit) runs every step again; the diff is published with every attempt's logs."""
    root = tmp_path / 'results'
    root.mkdir()
    shutil.copytree(REHEARSAL, root / 'holdout2026')
    diff = root / 'holdout2026' / 'logs' / f'holdout2026_crash_fix_{RUN_COMMIT[:12]}.diff'
    diff.write_text(CRASH_DIFF, encoding='utf-8')
    note = (f'crash fix: write a non-finite float as null; diff since {REGISTERED}: logs/{diff.name} '
            f'(sha256 {hashlib.sha256(diff.read_bytes()).hexdigest()})')
    failed = {'attempt': 1, 'event': 'failed', 'name': 'holdout2026', 'note': 'exit 1', 'step': 'v33',
              'utc': '2026-10-21T12:40:31+00:00'}
    attempts = (_attempt_lines(head=REGISTERED, prereg=REGISTERED, steps=('universe', 'data')) + [failed]
                + _attempt_lines(attempt=2, prereg=REGISTERED, note=note))
    _register(root, attempts, prereg=REGISTERED, note=note)
    return root, diff, note


def test_a_crash_fix_is_on_the_record(tmp_path):
    root, diff, note = _crash_fix_root(tmp_path)
    p = _section(root)[0]['provenance']
    assert (p['commit'], p['registered_commit'], p['at_registered_commit']) == (RUN_COMMIT, REGISTERED, False)
    assert (p['n_attempts'], p['n_failed'], p['registry']['note']) == (2, 1, note)
    first, second = p['attempts']
    assert (first['head'], first['at_registered_commit'], first['steps_done'], first['failed']['step']) == (
        REGISTERED, True, ['universe', 'data'], 'v33')
    assert (second['head'], second['at_registered_commit'], second['crash_fix']['fix'], second['crash_fix']['diff']) == (
        RUN_COMMIT, False, 'write a non-finite float as null', diff.name)
    assert p['crash_fix'] == second['crash_fix'] and set(p['step_attempts'].values()) == {2}
    sha = hashlib.sha256(diff.read_bytes()).hexdigest()
    assert p['crash_fix_diffs'] == [{'file': f'logs/{diff.name}', 'commit': RUN_COMMIT[:12], 'sha256': sha,
                                     'bytes': len(CRASH_DIFF.encode()), 'files': ['pairs_trading/json_export.py'],
                                     'insertions': 3, 'deletions': 1, 'attempts': [2]}]
    assert p['logs']['diffs'] == 1
    # a diff no attempt names was written by a step-0 check that then refused to start one
    orphan = diff.with_name('holdout2026_crash_fix_0123456789ab.diff')
    orphan.write_text(CRASH_DIFF, encoding='utf-8')
    assert [d['attempts'] for d in _section(root)[0]['provenance']['crash_fix_diffs']] == [[], [2]]
    orphan.unlink()
    diff.write_text(CRASH_DIFF + '+    pass\n', encoding='utf-8')        # not the diff the note records
    with pytest.raises(bsd.HoldoutRecordError, match='sha256'):
        _section(root)
    diff.unlink()
    with pytest.raises(bsd.HoldoutRecordError, match='not in results/holdout2026/logs'):
        _section(root)


@pytest.mark.parametrize('lines, match', [
    (_attempt_lines(note=f'crash fix: x; diff since {"0" * 40}: logs/a.diff (sha256 {"0" * 64})'), 'since the registered'),
    (_attempt_lines(note='crash fix: a fix without its diff'), 'crash-fix note'),
    (_attempt_lines(note=f'crash fix: x; diff since {RUN_COMMIT}: logs/a.diff (sha256 {"0" * 64})'), 'at the registered'),
    (_attempt_lines(attempt=2), 'numbered'),
    (_attempt_lines()[1:], 'no start line'),
    (_attempt_lines()[:1] + [dict(_attempt_lines()[1], head='0' * 40)], 'recorded at'),
])
def test_an_attempt_record_that_contradicts_itself_stops_the_build(lines, match):
    with pytest.raises(bsd.HoldoutRecordError, match=match):
        bsd.holdout_attempts(lines, RUN_COMMIT)


def test_an_attempt_that_stopped_without_a_failure_line(tmp_path):
    """Killed (the runbook's EXIT trap never ran), or its failure line not written: an earlier
    attempt with neither a failure nor a completion line stopped without recording a failure."""
    root = _holdout_root(tmp_path, attempts=_attempt_lines(steps=('universe', 'data')) + _attempt_lines(
        attempt=2, steps=('v33', 'v32', 'residual', 'evaluate')))
    p = _section(root)[0]['provenance']
    assert (p['n_attempts'], p['n_failed'], p['n_unfinished']) == (2, 0, 1)
    assert p['attempts'][0]['failed'] is None and p['attempts'][0]['completed_utc'] is None


def test_the_price_manifest_must_be_the_holdouts(tmp_path):
    """The published price manifest is the calendar's cache's: its date range is the calendar's,
    and it is the file the attempt record last recorded for it at the evaluated commit."""
    root = _holdout_root(tmp_path)
    path = root / 'holdout2026' / 'price_fetch_manifest.json'
    original = path.read_bytes()
    fetch = _section(root)[0]['provenance']['price_fetch']
    assert (fetch['start'], fetch['end']) == ('2022-01-01', '2025-10-17')
    shutil.copy(REPO / 'results' / 'rehearsal2025' / 'price_fetch_manifest.json', path)     # the other rehearsal's
    with pytest.raises(bsd.HoldoutRecordError, match='not the price manifest'):
        _section(root)
    doc = json.loads(original)
    path.write_text(json.dumps(dict(doc, start='2023-01-01')), encoding='utf-8')          # another calendar's range
    with pytest.raises(bsd.HoldoutRecordError, match='not the calendar'):
        _section(root)
    path.unlink()                                                                           # not published: none
    assert _section(root)[0]['provenance']['price_fetch'] is None


def test_another_results_tree_is_never_written_over_the_committed_study(tmp_path):
    """--results and --holdout-calendar build a preview into --out; without it (or with --check)
    the command stops before reading anything, and assets/study.json is unchanged."""
    committed = (REPO / 'assets' / 'study.json').read_bytes()
    for argv in (['--results', str(tmp_path)], ['--holdout-calendar', REHEARSAL_CALENDAR],
                 ['--results', str(tmp_path), '--out', str(REPO / 'assets' / 'study.json')],
                 ['--results', str(tmp_path), '--check', '--out', str(tmp_path / 'study.json')]):
        with pytest.raises(SystemExit):
            bsd.main(argv)
    assert (REPO / 'assets' / 'study.json').read_bytes() == committed


def _holdout_text():
    """The sealed sentences of index.html and their complete-state wording, from exhibits.js."""
    js = (REPO / 'assets' / 'exhibits.js').read_text(encoding='utf-8')
    block = js.split('/* holdout-text-begin */', 1)[1].split('/* holdout-text-end */', 1)[0].strip()
    assert block.startswith('var HOLDOUT_TEXT = ') and block.endswith(';')
    return json.loads(block[len('var HOLDOUT_TEXT = '):-1])


SEALED_PHRASES = ('runs once', 'will be added as one trial', 'pre-registered, sealed', 'the sealed holdout',
                  'the sealed 2026 holdout', 'test on 2026 data is sealed', '2026 test is sealed.')


def test_every_sealed_sentence_of_the_page_has_its_complete_wording():
    """While the holdout is sealed, exhibits.js replaces each sentence of index.html that is true
    only while the test is sealed: each sealed text it names is on the page as often as it says,
    and no replacement says the test is still to run. Once the test has run, the page carries
    the complete wording itself (data-holdout="complete", which exhibits.js then leaves alone):
    no sealed text of the table and no sealed phrase is left on it."""
    page = (REPO / 'index.html').read_text(encoding='utf-8')
    entries = _holdout_text()
    assert len(entries) >= 15
    if 'data-holdout="complete"' in page:
        js = (REPO / 'assets' / 'exhibits.js').read_text(encoding='utf-8')
        assert "getAttribute('data-holdout') === 'complete'" in js
        for e in entries:
            assert page.count(e['sealed']) == 0, e['sealed']
        for phrase in SEALED_PHRASES:
            assert phrase not in page, phrase
        assert 'Sealed</span>' not in page and '(sealed)' not in page
        return
    for e in entries:
        assert set(e) <= {'in', 'attr', 'sealed', 'done', 'cut', 'count'}, e
        assert page.count(e['sealed']) == e.get('count', 1), e['sealed']
        parts = e['done'] if isinstance(e['done'], list) else [e['done']]
        done = ''.join(x if isinstance(x, str) else x['text'] for x in parts)
        assert not re.search(r'runs once|will be added|is sealed\b|, sealed\b|refuses|is seen\b|is fetched\b', done), done
    # every sentence on the page that speaks of the test in the future or as sealed is listed
    # (a cut sentence runs to the end of its paragraph)
    spans = [(m.start(), page.index('</p>', m.end()) if e.get('cut') else m.end())
             for e in entries for m in re.finditer(re.escape(e['sealed']), page)]
    for phrase in SEALED_PHRASES:
        for m in re.finditer(re.escape(phrase), page):
            assert any(a <= m.start() and m.end() <= b for a, b in spans), (phrase, page[m.start() - 60:m.end() + 60])
