"""The pre-registered holdout's machinery: scripts/evaluate_holdout.py on synthetic run
exports (no market data), its input checks, and the reports it promises."""
import importlib.util
import json
import os

import numpy as np
import pandas as pd
import pytest

from pairs_trading.study_config import CALENDARS, PROFILES

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, 'scripts')


def _load(name):
    spec = importlib.util.spec_from_file_location(f'_script_{name}', os.path.join(SCRIPTS, f'{name}.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ev = _load('evaluate_holdout')
COMMIT = 'c' * 40
DATES = [str(d.date()) for d in pd.bdate_range('2026-01-02', periods=200)]


def _pairs_export(directory, net, profile='v33', calendar='holdout2026', commit=COMMIT, dirty=False,
                  complete=True, switches=(), dates=DATES, seed=0):
    """A run's output directory shaped like export_testing_results_to_json + headline."""
    rng = np.random.default_rng(seed)
    os.makedirs(directory, exist_ok=True)
    study = {'profile': {'name': profile}, 'calendar': {'name': calendar},
             'profile_hash': PROFILES[profile].config_hash(), 'calendar_hash': CALENDARS[calendar].config_hash()}
    rc = {'git_commit': commit, 'git_dirty': dirty, 'run_timestamp_utc': '2026-10-21T00:00:00+00:00',
          'study': study}
    days = [{'date': d, 'daily_return_pct': float(r) * 100, 'gross_return_pct': float(r) * 100,
             'open_positions': int(r != 0)} for d, r in zip(dates, net)]
    dist = list(rng.normal(0, 0.005, len(dates)))
    draws = list(rng.normal(0, 1, 200))
    doc = {'run_config': rc, 'daily_equity_curve': days,
           'overall_performance': {'total_trades': 7, 'avg_gross_exposure_pct_of_equity': 20.0,
                                   'max_gross_exposure_pct_of_equity': 30.0},
           'universe_by_formation': [{'formation_date': '2025-12-31', 'missing_value_weight': 0.007}],
           'benchmarks': {'config': {'universe_size': 500},
                          'distance_method': {'daily_dates': list(dates), 'daily_returns': dist},
                          'random_control': {'n_draws': 200, 'draw_sharpes': draws, 'daily_dates': list(dates)},
                          'vs_strategy': {'main_backtest': {
                              'n_common_days': len(dates), 'distance_sharpe': 0.1,
                              'strategy_percentile_in_random': 40.0,
                              'random_sharpe_distribution': {'median': 0.0},
                              'sharpe_difference_vs_distance': {'diff': 0.2, 'ci_lo': -1.0, 'ci_hi': 1.4,
                                                                'pvalue': 0.7}}}}}
    with open(os.path.join(directory, ev.RESULTS_FILE), 'w') as f:
        json.dump(doc, f)
    with open(os.path.join(directory, 'headline_metrics.json'), 'w') as f:
        json.dump({'complete': complete, 'non_default_switches': list(switches), 'run_config': rc}, f)
    return directory


def _residual_export(path, net, commit=COMMIT, dates=DATES):
    with open(path, 'w') as f:
        json.dump({'daily_dates': list(dates), 'daily_net_returns': [float(x) for x in net], 'total_trades': 0,
                   'run_config': {'git_commit': commit, 'git_dirty': False,
                                  'study': {'calendar': {'name': 'holdout2026'}}}}, f)
    return path


def _args(tmp_path, v33, v32, residual):
    return ['--pairs', f'v33_pairs={v33}', '--pairs', f'v32_pairs={v32}', '--residual', str(residual),
            '--expect-commit', COMMIT, '--out', str(tmp_path / 'evaluation.json')]


def test_a_strategy_that_never_trades_is_not_rejected_and_the_report_is_written(tmp_path):
    """An all-zero arm: t = 0, p = 1/2, no edge; the statistics it has no value for are null
    (the strict JSON write used to raise on NaN, so the runbook aborted before registering)."""
    rng = np.random.default_rng(1)
    v33 = _pairs_export(tmp_path / 'v33', rng.normal(0.0004, 0.004, 200))
    v32 = _pairs_export(tmp_path / 'v32', np.zeros(200), profile='v32')
    res = _residual_export(tmp_path / 'res.json', rng.normal(0, 0.004, 200))
    assert ev.main(_args(tmp_path, v33, v32, res)) == 0
    rep = json.loads((tmp_path / 'evaluation.json').read_text(), parse_constant=pytest.fail)
    flat = rep['strategies']['v32_pairs']
    assert flat['t'] == 0.0 and flat['p_one_sided'] == 0.5 and flat['edge_out_of_sample'] is False
    assert flat['psr'] is None and flat['sharpe_se'] is None and flat['bootstrap_ci_95'] == [None, None]
    assert rep['inputs']['runs']['v32_pairs']['sha256'][ev.RESULTS_FILE]


def test_every_strategy_gets_the_promised_report(tmp_path):
    """Exposure, the Gatev comparison and the random-pair percentile for every arm (the
    residual arm against S1's baselines), and the detectable Sharpe at Holm's first step."""
    rng = np.random.default_rng(2)
    v33 = _pairs_export(tmp_path / 'v33', rng.normal(0.0003, 0.004, 200))
    v32 = _pairs_export(tmp_path / 'v32', rng.normal(0.0, 0.004, 200), profile='v32', seed=1)
    res = _residual_export(tmp_path / 'res.json', rng.normal(0.0002, 0.004, 200))
    assert ev.main(_args(tmp_path, v33, v32, res)) == 0
    s = json.loads((tmp_path / 'evaluation.json').read_text())['strategies']
    assert set(s) == set(ev.REGISTERED)
    for row in s.values():
        assert row['vs_gatev']['diff'] is not None and row['random_pair']['percentile'] is not None
        assert row['min_detectable_sharpe_alpha'] == pytest.approx(0.05 / 3)
        assert row['min_detectable_sharpe'] > row['min_detectable_sharpe_single_test'] > 0
    assert s['v33_pairs']['exposure'] == {'avg_gross_pct_of_equity': 20.0, 'max_gross_pct_of_equity': 30.0,
                                          'days_with_open_positions': 200}
    assert s['v33_pairs']['random_pair']['percentile'] == 40.0
    assert s['avellaneda_lee']['vs_gatev']['source'] == 'v33 run'
    assert s['avellaneda_lee']['vs_gatev']['n_common_days'] == 200


def test_the_baseline_comparison_reproduces_the_in_run_test():
    """compare_with_baselines on exported series gives run_benchmarks' own numbers."""
    from pairs_trading.benchmark import _compare_to_strategy
    from pairs_trading.significance import annualized_sharpe
    rng = np.random.default_rng(3)
    r, dist = rng.normal(0.0002, 0.004, 200), rng.normal(0, 0.004, 200)
    rand = rng.normal(0, 0.004, (200, 50))
    ref = _compare_to_strategy(DATES, r, DATES, dist, rand, n_boot=5000, seed=42)
    draws = [annualized_sharpe(rand[:, j]) for j in range(50)]
    got = ev.compare_with_baselines(DATES, r, {'source': 's', 'distance_dates': DATES, 'distance_returns': dist,
                                               'random_dates': DATES, 'draw_sharpes': draws})
    assert got['vs_gatev']['diff'] == pytest.approx(ref['sharpe_difference_vs_distance']['diff'])
    assert got['vs_gatev']['pvalue'] == pytest.approx(ref['sharpe_difference_vs_distance']['pvalue'])
    assert got['random_pair']['percentile'] == pytest.approx(ref['strategy_percentile_in_random'])


@pytest.mark.parametrize('change, needle', [
    (dict(v32={'commit': 'd' * 40}), 'one commit'),
    (dict(v32={'dirty': True}), 'git_dirty'),
    (dict(v32={'calendar': 'rehearsal2025'}), 'calendar'),
    (dict(v32={'complete': False}), 'complete'),
    (dict(v32={'switches': ['PAIRS_RANKER=gbm']}), 'non-default'),
    (dict(v32={'dates': DATES[1:] + ['2026-10-19']}), 'trading dates differ'),
    (dict(residual=False), 'registered'),
    (dict(nan=True), 'not all finite'),
])
def test_inputs_that_are_not_the_registered_runs_are_refused(tmp_path, capsys, change, needle):
    rng = np.random.default_rng(4)
    v33 = _pairs_export(tmp_path / 'v33', rng.normal(0, 0.004, 200))
    net32 = rng.normal(0, 0.004, 200)
    if change.get('nan'):
        net32[17] = np.nan
    v32 = _pairs_export(tmp_path / 'v32', net32, profile='v32', **change.get('v32', {}))
    res = _residual_export(tmp_path / 'res.json', rng.normal(0, 0.004, 200))
    args = _args(tmp_path, v33, v32, res)
    if change.get('residual') is False:
        args = args[:4] + args[6:]
    assert ev.main(args) == 2
    assert needle in capsys.readouterr().err
    assert not (tmp_path / 'evaluation.json').exists()


def test_the_expected_commit_is_enforced(tmp_path, capsys):
    rng = np.random.default_rng(5)
    v33 = _pairs_export(tmp_path / 'v33', rng.normal(0, 0.004, 200))
    v32 = _pairs_export(tmp_path / 'v32', rng.normal(0, 0.004, 200), profile='v32')
    res = _residual_export(tmp_path / 'res.json', rng.normal(0, 0.004, 200))
    args = _args(tmp_path, v33, v32, res)
    args[args.index('--expect-commit') + 1] = 'e' * 40
    assert ev.main(args) == 2 and 'expected commit' in capsys.readouterr().err
