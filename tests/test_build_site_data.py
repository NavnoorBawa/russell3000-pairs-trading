"""scripts/build_site_data.py (assets/study.json) and the checker's study.* markers.

The builder is exercised on the committed v32 run and on copies of it altered to carry
what later exports add (the random-pair quantiles, point-in-time universe coverage, the
daily gross/cost split, a _compact twin), so every optional path runs without new data.
"""
import copy
import hashlib
import importlib.util
import json
import math
import pathlib
import shutil

import numpy as np
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
V32 = REPO / 'results' / 'v32_dev'
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
    """assets/study.json is what the builder makes from results/v32_dev, byte for byte."""
    assert bsd.main(['--check']) == 0


def test_committed_page_passes_the_publication_checker(capsys):
    """Every number in README.md and index.html matches the v32 headline JSON or study.json."""
    assert chk.main(['--json', str(V32 / 'headline_metrics.json')]) == 0
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
    assert rows[0] == {'formation_date': '2022-12-31', 'snapshot': '2022-12-30', 'members': 2283,
                       'with_prices': 2062, 'missing': 221, 'missing_weight_pct': 2.137, 'unmapped_weight_pct': 2.146}
    assert rows[1]['unmapped_weight_pct'] is None
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


def _evaluation():
    """A report in the shape scripts/evaluate_holdout.py writes (strategy ids from run_holdout.sh)."""
    def arm(sharpe, p, p_holm):
        return {'days': 180, 'total_return_pct': 0.4, 'sharpe': sharpe, 'trades': 40, 't': 0.9, 'lags': 4,
                'p_one_sided': p, 'p_holm': p_holm, 'edge_out_of_sample': p_holm < 0.05,
                'bootstrap_ci_95': [sharpe - 1.5, sharpe + 1.5], 'upper_bound_95': sharpe + 1.2,
                'min_detectable_sharpe': 2.6, 'period': ['2026-01-02', '2026-09-30']}
    return {'alpha': 0.05, 'test': 'one-sided Newey-West t (mean daily net return > 0), Holm across strategies',
            'strategies': {'v32_pairs': arm(-0.2, 0.6, 0.9), 'avellaneda_lee': arm(0.4, 0.3, 0.9),
                           'v33_pairs': arm(0.8, 0.15, 0.45)}}


def test_optional_arms_fill_their_sections(tmp_path, v32_res):
    """The holdout evaluation and the residual headline JSON replace the sealed/pending states."""
    root = tmp_path / 'results'
    for arm in ('holdout2026', 'residual_dev'):
        (root / arm).mkdir(parents=True)
    (root / 'holdout2026' / 'evaluation.json').write_text(json.dumps(_evaluation()), encoding='utf-8')
    shutil.copy(V32 / 'headline_metrics.json', root / 'residual_dev' / 'headline_metrics.json')
    study = bsd.build(_run_dir(tmp_path, v32_res), results_root=root)
    holdout = study['holdout']
    assert holdout['status'] == 'complete' and holdout['alpha'] == 0.05
    # the registered order (H1 v33, H2 Avellaneda-Lee, H3 v32), whatever the report's order
    assert [(a['key'], a['hypothesis']) for a in holdout['arms']] == [
        ('v33_pairs', 'H1'), ('avellaneda_lee', 'H2'), ('v32_pairs', 'H3')]
    v33 = holdout['arms'][0]
    assert (v33['sharpe'], v33['lo'], v33['hi'], v33['p_holm'], v33['edge']) == (0.8, -0.7, 2.3, 0.45, False)
    headline = json.loads((V32 / 'headline_metrics.json').read_text(encoding='utf-8'))
    assert study['residual']['sharpe'] == headline['main']['sharpe']
    sealed = bsd.build(V32, results_root=tmp_path / 'nothing')
    assert sealed['holdout'] == {'status': 'sealed', 'calendar_start': '2026-01-02'}
    assert sealed['residual'] is None and sealed['validation'] is None


def test_holdout_strategies_the_runbook_does_not_name_are_kept():
    ev = _evaluation()
    ev['strategies']['extra_arm'] = ev['strategies'].pop('v32_pairs')
    arms = bsd.holdout_section(ev)['arms']
    assert [a['key'] for a in arms] == ['v33_pairs', 'avellaneda_lee', 'extra_arm']
    assert arms[-1]['label'] == 'extra_arm' and arms[-1]['hypothesis'] is None


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
