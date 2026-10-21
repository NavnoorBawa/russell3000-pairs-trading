"""The pre-registered holdout's machinery: scripts/evaluate_holdout.py on synthetic run
exports (no market data), its input checks, and the reports it promises."""
import hashlib
import importlib.util
import json
import os

import numpy as np
import pandas as pd
import pytest

from pairs_trading.residual_statarb import ResidualStatArbParams
from pairs_trading.study_config import CALENDARS, PROFILES, RESIDUAL_PARAMS_HASH

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
INDEX, MACRO = 'e1' * 32, 'f1' * 32          # the membership index and macro cache the arms read
with open(os.path.join(REPO, 'reference', 'industry_ff49.csv'), 'rb') as _fh:
    SECTOR_MAP = hashlib.sha256(_fh.read()).hexdigest()          # the committed sector map


def _pairs_export(directory, net, profile='v33', calendar='holdout2026', commit=COMMIT, dirty=False,
                  complete=True, switches=(), dates=DATES, seed=0, cache='ab' * 32, macro=MACRO, index=INDEX):
    """A run's output directory shaped like export_testing_results_to_json + headline."""
    rng = np.random.default_rng(seed)
    os.makedirs(directory, exist_ok=True)
    study = {'profile': {'name': profile}, 'calendar': {'name': calendar},
             'profile_hash': PROFILES[profile].config_hash(), 'calendar_hash': CALENDARS[calendar].config_hash()}
    rc = {'git_commit': commit, 'git_dirty': dirty, 'run_timestamp_utc': '2026-10-21T00:00:00+00:00',
          'study': study, 'data': {'price_cache': {'sha256': cache}, 'macro_cache': {'sha256': macro},
                                   'universe_file': {'sha256': index if profile == 'v33' else 'aa' * 32}}}
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


def _residual_export(path, net, commit=COMMIT, dates=DATES, calendar='holdout2026', cache='ab' * 32,
                     params=ResidualStatArbParams(), switches=(), macro=MACRO, index=INDEX, sector_map=SECTOR_MAP,
                     registered=True, root=None, trades=40, selected=500, filed='2026-08-25'):
    """The fields of scripts/run_residual_statarb.py's export that the evaluator reads."""
    study = {'strategy': 'avellaneda_lee', 'profile': None, 'calendar': {'name': calendar},
             'calendar_hash': CALENDARS[calendar].config_hash(), 'params_hash': params.config_hash()}
    root = root or ('data/holdout2026_reference' if calendar == 'holdout2026' else 'reference')
    rankings = [{'date': d, 'members': 2500, 'with_prices': 2400, 'screened': 1500, 'eligible': 1490,
                 'selected': 500, 's1_without_sector_etf': 0} for d in dates[::21]]
    rankings[-1]['selected'] = selected
    with open(path, 'w') as f:
        json.dump({'daily_dates': list(dates), 'daily_net_returns': [float(x) for x in net], 'total_trades': trades,
                   'daily_open_positions': [0] * len(dates),
                   'summary': {'avg_gross_exposure': 0.25, 'max_gross_exposure': 0.5},
                   'universe': {'rankings': rankings}, 'params': {'universe_size': params.universe_size},
                   'universe_by_formation': [{'formation_date': dates[0], 'snapshot': '2026-06-30',
                                              'snapshot_filed': filed}],
                   'complete': True, 'non_default_switches': list(switches),
                   'run_config': {'git_commit': commit, 'git_dirty': False, 'study': study,
                                  'data': {'price_cache': {'sha256': cache}, 'macro_cache': {'sha256': macro},
                                           'universe_file': {'sha256': index}},
                                  'universe': {'reference_root': root},
                                  'sector_map': {'registered': registered, 'file': {'sha256': sector_map}}}}, f)
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
    assert flat['t'] == 0.0 and flat['p_one_sided'] == 0.5
    # S3 is reported but tested in no family (its universe is ranked inside the test period)
    assert flat['role'] == 'descriptive' and flat['p_holm'] is None and flat['edge_out_of_sample'] is None
    assert rep['family'] == ['v33_pairs', 'avellaneda_lee']
    for k in rep['family']:
        s = rep['strategies'][k]
        assert s['role'] == 'confirmatory' and s['p_holm'] == pytest.approx(min(1.0, 2 * s['p_one_sided'])) \
            or s['p_holm'] >= s['p_one_sided']
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
        assert row['min_detectable_sharpe_alpha'] == pytest.approx(0.05 / 2)    # Holm's first step, H1 and H2
        assert row['min_detectable_sharpe'] > row['min_detectable_sharpe_single_test'] > 0
    assert s['v33_pairs']['exposure'] == {'avg_gross_pct_of_equity': 20.0, 'max_gross_pct_of_equity': 30.0,
                                          'days_with_open_positions': 200}
    assert s['v33_pairs']['random_pair']['percentile'] == 40.0
    assert s['avellaneda_lee']['vs_gatev']['source'] == 'v33 run'
    assert s['avellaneda_lee']['vs_gatev']['n_common_days'] == 200
    assert s['avellaneda_lee']['exposure'] == {'avg_gross_pct_of_equity': 25.0, 'max_gross_pct_of_equity': 50.0,
                                               'days_with_open_positions': 0}


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
    (dict(v32={'cache': 'cd' * 32}), 'one price cache'),
    (dict(residual=False), 'registered'),
    (dict(nan=True), 'not all finite'),
    (dict(res={'calendar': 'rehearsal2025'}), 'avellaneda_lee: calendar rehearsal2025'),
    (dict(res={'commit': 'd' * 40}), 'one commit'),
    (dict(res={'cache': 'cd' * 32}), 'one price cache'),
    (dict(res={'params': ResidualStatArbParams(position_frac=0.01)}), 'avellaneda_lee: parameter hash'),
    (dict(res={'switches': ['PAIRS_ALLOW_PARTIAL_FETCH=1']}), 'avellaneda_lee: complete True, non-default'),
    (dict(v32={'macro': 'cd' * 32}), 'one macro cache'),
    (dict(res={'macro': 'cd' * 32}), 'one macro cache'),
    (dict(res={'index': 'cd' * 32}), 'one membership index'),
    (dict(res={'root': 'reference'}), 'avellaneda_lee: membership read from reference'),
    (dict(res={'sector_map': '1' * 64}), 'avellaneda_lee: sector map'),
    (dict(res={'registered': False}), 'avellaneda_lee: sector map'),
    (dict(res={'trades': 0}), 'avellaneda_lee: no trades'),
    (dict(res={'selected': 0}), 'avellaneda_lee: ranking days'),
    (dict(res={'selected': 497}), "fewer than S1's rule"),
    (dict(res={'filed': '2026-11-25'}), 'avellaneda_lee: snapshots'),
    (dict(swap=True), 'v32_pairs: a pairs run of v33, not the registered pairs run of v32'),
])
def test_inputs_that_are_not_the_registered_runs_are_refused(tmp_path, capsys, change, needle):
    rng = np.random.default_rng(4)
    v33 = _pairs_export(tmp_path / 'v33', rng.normal(0, 0.004, 200))
    net32 = rng.normal(0, 0.004, 200)
    if change.get('nan'):
        net32[17] = np.nan
    v32 = _pairs_export(tmp_path / 'v32', net32, profile='v32', **change.get('v32', {}))
    res = _residual_export(tmp_path / 'res.json', rng.normal(0, 0.004, 200), **change.get('res', {}))
    args = _args(tmp_path, v33, v32, res)
    if change.get('swap'):
        args = _args(tmp_path, v33, v33, res)
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


# ── scripts/run_holdout.sh, end to end with the data-touching commands stubbed ──────

import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402

STUB = '''#!/usr/bin/env bash
# PYTHON for the runbook test: fakes the commands that touch market data, runs the rest.
echo "$*" >> "$STUB_LOG"
case "${1:-} ${2:-}" in "-m pairs_trading.main") shift 2; exec "$REAL_PY" "$STUB_DIR/fake.py" main "$@";; esac
case "${1:-}" in
  scripts/build_pit_universe.py) shift; exec "$REAL_PY" "$STUB_DIR/fake.py" universe "$@";;
  scripts/run_residual_statarb.py) shift; exec "$REAL_PY" "$STUB_DIR/fake.py" residual "$@";;
esac
exec "$REAL_PY" "$@"
'''

FAKE = '''import argparse, hashlib, json, os, pathlib, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.getcwd())
from pairs_trading.study_config import CALENDARS, PROFILES, describe
kind, argv = sys.argv[1], sys.argv[2:]
ap = argparse.ArgumentParser()
for a in ('--profile', '--calendar', '--output-dir', '--sealed-out', '--sealed-from', '--through', '--out'):
    ap.add_argument(a)
for a in ('--fetch-only', '--include-sealed', '--offline'):
    ap.add_argument(a, action='store_true')
args = ap.parse_args(argv)
with open(os.environ['STUB_ENV_LOG'], 'a') as f:
    f.write(json.dumps({k: v for k, v in os.environ.items() if k.startswith('PAIRS_') or k == 'PYTHONHASHSEED'}) + '\\n')
if kind == 'universe':
    d = pathlib.Path(args.sealed_out); d.mkdir(parents=True, exist_ok=True)
    (d / 'index.json').write_text('{"snapshots": []}')
    sys.exit(0)
cal = CALENDARS[args.calendar or 'holdout2026']
dates = [str(x.date()) for x in pd.bdate_range(cal.backtest_start, cal.data_end)]
rng = np.random.default_rng(len(args.profile or 'r'))
net = rng.normal(0, 0.004, len(dates))
sha = lambda path: {'sha256': hashlib.sha256(open(path, 'rb').read()).hexdigest()}
index = f'data/{cal.name}_reference/universe/index.json'
if kind == 'residual':
    from pairs_trading.residual_statarb import ResidualStatArbParams
    p = pathlib.Path(args.out); p.parent.mkdir(parents=True, exist_ok=True)
    study = {'strategy': 'avellaneda_lee', 'profile': None, 'calendar': {'name': cal.name},
             'calendar_hash': cal.config_hash(), 'params_hash': ResidualStatArbParams().config_hash()}
    rankings = [{'date': d, 'screened': 1500, 'eligible': 1490, 'selected': 500} for d in dates[::21]]
    p.write_text(json.dumps({'daily_dates': dates, 'daily_net_returns': list(net), 'total_trades': 3,
                             'summary': {'sharpe': 0.1, 'total_return': 0.01}, 'complete': True,
                             'non_default_switches': [], 'universe': {'rankings': rankings},
                             'params': {'universe_size': 500},
                             'run_config': {'git_commit': os.environ['PAIRS_EXPECTED_COMMIT'], 'git_dirty': False,
                                            'study': study, 'universe': {'reference_root': f'data/{cal.name}_reference'},
                                            'sector_map': {'registered': True, 'file': sha('reference/industry_ff49.csv')},
                                            'data': {'price_cache': sha(cal.price_cache), 'macro_cache': sha(cal.macro_cache),
                                                     'universe_file': sha(index)}}}))
    sys.exit(0)
if args.fetch_only:
    with open(cal.price_cache, 'a') as f:
        f.write(args.profile + '\\n')
    pathlib.Path(cal.price_cache.replace('.pkl', '_manifest.json')).write_text('{}')
    pathlib.Path(cal.macro_cache).write_text('macro')
    sys.exit(0)
if os.environ.get('STUB_FAIL') == args.profile:
    sys.exit('stub: this run fails')
out = pathlib.Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
rc = {'git_commit': os.environ['PAIRS_EXPECTED_COMMIT'], 'git_dirty': False,
      'study': describe(PROFILES[args.profile], cal),
      'data': {'price_cache': sha(cal.price_cache), 'macro_cache': sha(cal.macro_cache),
               'universe_file': sha(index if args.profile == 'v33' else 'data/marketcap.csv')}}
days = [{'date': d, 'daily_return_pct': float(r) * 100, 'gross_return_pct': float(r) * 100, 'open_positions': 1}
        for d, r in zip(dates, net)]
(out / 'pairs_trading_results_2023_2025_unbiased.json').write_text(json.dumps(
    {'run_config': rc, 'daily_equity_curve': days, 'overall_performance': {'total_trades': 5},
     'benchmarks': {'distance_method': {'daily_dates': dates, 'daily_returns': list(net * 0.5)},
                    'random_control': {'daily_dates': dates, 'draw_sharpes': [0.1, -0.2, 0.3]}}}))
(out / 'headline_metrics.json').write_text(json.dumps({'complete': True, 'non_default_switches': [],
                                                       'run_config': rc}))
'''


def _git(repo, *args):
    return subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def frozen_repo(tmp_path):
    """A clone-like repository at a pushed pre-registration commit, the package and the
    holdout scripts copied in, S2's script a stub, requirements without pins."""
    repo, remote = tmp_path / 'repo', tmp_path / 'remote.git'
    repo.mkdir()
    shutil.copytree(os.path.join(REPO, 'pairs_trading'), repo / 'pairs_trading',
                    ignore=shutil.ignore_patterns('__pycache__'))
    (repo / 'scripts').mkdir()
    for name in ('run_holdout.sh', 'trial_attempts.py', 'register_trial.py', 'publish_run.py',
                 'evaluate_holdout.py', 'check_pins.py'):
        shutil.copy(os.path.join(SCRIPTS, name), repo / 'scripts' / name)
    (repo / 'scripts' / 'run_residual_statarb.py').write_text('# S2 (stubbed in this test)\n')
    shutil.copy(os.path.join(REPO, '.gitignore'), repo / '.gitignore')
    shutil.copy(os.path.join(REPO, 'pyproject.toml'), repo / 'pyproject.toml')
    (repo / 'requirements.txt').write_text('# no pins in this test\n')
    (repo / 'reference').mkdir()
    (repo / 'reference' / 'README').write_text('reference data\n')
    (repo / 'reference' / 'industry_ff49.csv').write_text('ticker,cik,sic,ff49,ff49_name,sector_etf,entity_type\n')
    (repo / 'data').mkdir()
    (repo / 'data' / 'marketcap.csv').write_text('Symbol\nAAA\n')
    _git(repo, 'init', '-q', '-b', 'main')
    _git(repo, 'config', 'user.name', 't')
    _git(repo, 'config', 'user.email', 't@example.invalid')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-qm', 'code')
    (repo / 'docs').mkdir()
    (repo / 'docs' / 'PREREGISTRATION.md').write_text('# Pre-registration\n')
    import hashlib
    sha = hashlib.sha256((repo / 'data' / 'marketcap.csv').read_bytes()).hexdigest()
    (repo / 'reference' / 'holdout_inputs.sha256').write_text(f'{sha}  data/marketcap.csv\n')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-qm', 'freeze')
    subprocess.run(['git', 'init', '-q', '--bare', str(remote)], check=True)
    _git(repo, 'remote', 'add', 'origin', str(remote))
    _git(repo, 'push', '-q', 'origin', 'main')
    stub = tmp_path / 'stub'
    stub.mkdir()
    (stub / 'python').write_text(STUB)
    (stub / 'python').chmod(0o755)
    (stub / 'fake.py').write_text(FAKE)
    return repo, stub


def _run(repo, stub, **env):
    e = {k: v for k, v in os.environ.items() if not k.startswith('PAIRS_')}
    e.update(PYTHON=str(stub / 'python'), REAL_PY=sys.executable, STUB_DIR=str(stub),
             STUB_LOG=str(stub / 'calls.log'), STUB_ENV_LOG=str(stub / 'env.log'), **env)
    return subprocess.run(['bash', 'scripts/run_holdout.sh'], cwd=repo, env=e, capture_output=True, text=True,
                          timeout=600)


def _calls(stub):
    p = stub / 'calls.log'
    return p.read_text().splitlines() if p.exists() else []


def _attempts(repo):
    p = repo / 'results' / 'trial_attempts.jsonl'
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_the_runbook_records_a_crash_resumes_and_runs_once(frozen_repo):
    repo, stub = frozen_repo
    head = _git(repo, 'rev-parse', 'HEAD')
    # attempt 1: S3 crashes after S1 finished; a stray switch in the shell does not reach the runs
    r = _run(repo, stub, STUB_FAIL='v32', PAIRS_RANKER='gbm')
    assert r.returncode != 0, r.stderr
    events = [(a['attempt'], a['event'], a.get('step')) for a in _attempts(repo)]
    assert events == [(1, 'start', None), (1, 'done', 'universe'), (1, 'done', 'data'), (1, 'done', 'v33'),
                      (1, 'failed', 'v32')]
    assert not (repo / 'results' / 'trial_registry.jsonl').exists()
    envs = [json.loads(x) for x in (stub / 'env.log').read_text().splitlines()]
    assert all('PAIRS_RANKER' not in e and e['PYTHONHASHSEED'] == '0' and e['PAIRS_EXPECTED_COMMIT'] == head
               for e in envs)
    assert all(e['PAIRS_UNSEAL'] == head for e in envs)       # the freeze commit is HEAD here
    # attempt 2 at the same commit: finished steps are not run again
    n = len(_calls(stub))
    r = _run(repo, stub)
    assert r.returncode == 0, r.stdout + r.stderr
    again = [c for c in _calls(stub)[n:] if 'pairs_trading.main' in c or 'build_pit_universe' in c]
    assert again == ['-m pairs_trading.main --profile v32 --calendar holdout2026 --output-dir outputs/holdout2026_v32']
    reg = [json.loads(x) for x in (repo / 'results' / 'trial_registry.jsonl').read_text().splitlines()]
    assert [x['name'] for x in reg] == ['holdout2026'] and reg[0]['prereg_commit'] == head
    assert [r.get('profile') or r.get('strategy') for r in reg[0]['runs']] == ['v33', 'v32', 'avellaneda_lee']
    assert all(r['git_commit'] == head and r['calendar'] == 'holdout2026' for r in reg[0]['runs'])
    assert [(a['attempt'], a['event']) for a in reg[0]['attempts'] if a['event'] in ('start', 'failed')] == \
        [(1, 'start'), (1, 'failed'), (2, 'start')]
    evaluation = json.loads((repo / 'results' / 'holdout2026' / 'evaluation.json').read_text())
    assert sorted(evaluation['strategies']) == sorted(ev.REGISTERED)
    assert evaluation['inputs']['expect_commit'] == head
    assert (repo / 'results' / 'holdout2026' / 'logs' / 'holdout2026_a1_v33.log').exists()
    assert (repo / 'results' / 'holdout2026' / 'price_fetch_manifest.json').exists()
    # a third run is refused before anything runs
    n = len(_calls(stub))
    r = _run(repo, stub)
    assert r.returncode != 0 and 'already registered' in r.stderr
    assert not [c for c in _calls(stub)[n:] if 'pairs_trading.main' in c]


@pytest.mark.parametrize('change, needle', [
    ('untracked', 'untracked changes'),
    ('code', 'code changed since the pre-registration'),
    ('crash_fix_decision', 'may not change'),
    ('input', 'differs from reference/holdout_inputs.sha256'),
])
def test_the_runbook_refuses_before_any_data_step(frozen_repo, change, needle):
    repo, stub = frozen_repo
    env = {}
    if change == 'untracked':
        (repo / 'pairs_trading' / 'extra.py').write_text('x = 1\n')
    elif change in ('code', 'crash_fix_decision'):
        target = 'scripts/evaluate_holdout.py' if change == 'crash_fix_decision' else 'scripts/publish_run.py'
        with open(repo / target, 'a') as f:
            f.write('# changed\n')
        _git(repo, 'commit', '-qam', 'change')
        env = {'HOLDOUT_CRASH_FIX': 'x'} if change == 'crash_fix_decision' else {}
    else:
        (repo / 'data' / 'marketcap.csv').write_text('Symbol\nBBB\n')
    r = _run(repo, stub, **env)
    assert r.returncode != 0 and needle in r.stderr, r.stderr
    assert not _attempts(repo) and not [c for c in _calls(stub) if 'pairs_trading.main' in c]


def test_the_runbook_refuses_a_shallow_clone(frozen_repo, tmp_path):
    repo, stub = frozen_repo
    shallow = tmp_path / 'shallow'
    subprocess.run(['git', 'clone', '-q', '--depth', '1', f'file://{repo}', str(shallow)], check=True)
    r = _run(shallow, stub)
    assert r.returncode != 0 and 'shallow' in r.stderr


def test_publishing_never_mixes_runs_and_refuses_variants(tmp_path):
    pr = _load('publish_run')
    pr.ROOT = tmp_path
    src = tmp_path / 'out'
    src.mkdir()
    (src / 'headline_metrics.json').write_text(json.dumps({'complete': True, 'non_default_switches': []}))
    (src / 'a.json').write_text('{}')
    dest = pr.publish(src, 'x')
    with pytest.raises(SystemExit, match='already holds'):
        pr.publish(src, 'x')
    (dest / 'stale.json').write_text('{}')
    pr.publish(src, 'x', replace=True)
    assert not (dest / 'stale.json').exists()
    (src / 'headline_metrics.json').write_text(json.dumps({'complete': True, 'non_default_switches': ['PAIRS_RANKER=gbm']}))
    with pytest.raises(SystemExit, match='variant'):
        pr.publish(src, 'y')
    pr.publish(src, 'y', variant=True)


def test_a_holdout_trial_is_registered_only_with_its_own_runs_and_files(tmp_path):
    rt = _load('register_trial')
    run = tmp_path / 'res' / 'v33_pairs'
    run.mkdir(parents=True)
    rc = {'git_commit': 'a' * 40, 'git_dirty': False}
    (run / 'headline_metrics.json').write_text(json.dumps({'run_config': rc}))
    (run / 'MANIFEST.json').write_text(json.dumps({'files': {ev.RESULTS_FILE: {'sha256': 'f' * 64}}}))
    evaluation = tmp_path / 'res' / 'evaluation.json'
    evaluation.write_text(json.dumps({'strategies': {}, 'inputs': {'runs': {'v33_pairs': {
        'sha256': {ev.RESULTS_FILE: 'e' * 64}}}}}))
    reg, att = tmp_path / 'reg.jsonl', tmp_path / 'att.jsonl'
    with pytest.raises(SystemExit, match='not from a clean tree'):
        rt.register('holdout2026', [run], prereg_commit='p', head='b' * 40, path=reg, attempts=att)
    with pytest.raises(SystemExit, match='differ from the evaluated'):
        rt.register('holdout2026', [run], evaluation, prereg_commit='p', head='a' * 40, path=reg, attempts=att)
    (run / 'MANIFEST.json').write_text(json.dumps({'files': {ev.RESULTS_FILE: {'sha256': 'e' * 64}}}))
    ta = _load('trial_attempts')
    ta.append('holdout2026', 'start', path=att, head='a' * 40)
    ta.append('holdout2026', 'failed', path=att, step='v32')
    e = rt.register('holdout2026', [run], evaluation, prereg_commit='p', head='a' * 40, path=reg, attempts=att)
    assert [(a['attempt'], a['event']) for a in e['attempts']] == [(1, 'start'), (1, 'failed')]
    assert e['evaluation']['inputs']['runs']['v33_pairs']['sha256'][ev.RESULTS_FILE] == 'e' * 64


def test_pin_check_follows_pep440_local_labels():
    """The registered run's environment check: a local build satisfies an unlabelled pin
    (the CPU wheel 2.13.0+cpu is torch==2.13.0), a different version or a missing package
    does not, and a labelled pin needs that label."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('check_pins', os.path.join(REPO, 'scripts', 'check_pins.py'))
    cp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cp)
    have = {'torch': '2.13.0+cpu', 'numpy': '1.26.4', 'pandas': '2.2.2'}.get
    lines = ['torch==2.13.0', 'numpy==1.26.4  # pinned', 'pandas==2.2.3', 'scipy==1.15.2',
             '# a comment', 'requests>=2', '']
    assert cp.mismatches(lines, have) == ['pandas 2.2.2 (pinned 2.2.3)', 'scipy None (pinned 1.15.2)']
    assert cp.mismatches(['torch==2.13.0+cu121'], have) == ['torch 2.13.0+cpu (pinned 2.13.0+cu121)']
    assert cp.mismatches(['torch==2.13.0+cpu'], have) == []


# ── the three arms for real, on a synthetic market laid out as a calendar's caches ──

CAL = CALENDARS['rehearsal2025']


@pytest.fixture(scope='module')
def three_arms(tmp_path_factory):
    """S1 (v33) and S3 (v32) through run_complete_system and S2 through its script, each the
    code the runbook runs, on one synthetic market written as the rehearsal2025 calendar's
    price and macro caches: planted cointegrated pairs and sector-ETF residuals, point-in-time
    snapshots and an industry map in a stand-in reference/ directory, a clean tree at COMMIT.
    Returns the directory holding out_v33/, out_v32/ and out_residual/."""
    from pairs_trading import json_export, universe
    from pairs_trading.synthetic import make_market, make_residual_market, write_calendar_caches, write_reference
    from pairs_trading.trading_system import CompleteFixedRussell3000TradingSystem
    root = tmp_path_factory.mktemp('arms')
    frames, macro, _ = make_market(n_pairs=6, n_noise=4, seed=21, start='2022-01-03', end=CAL.data_end)
    rframes, rsectors, rmap, _ = make_residual_market(seed=3, start='2022-01-03', end=CAL.data_end)
    frames.update(rframes)
    macro['sectors'].update({e: c.reindex(macro['VIX'].index) for e, c in rsectors.items()})
    write_calendar_caches(root, CAL, frames, macro)
    names = sorted(frames)
    pd.DataFrame({'Symbol': names}).to_csv(root / 'data' / 'marketcap.csv', index=False)      # S3's universe
    write_reference(root / 'reference', {d: names for d in ('2024-09-30', '2024-12-31', '2025-03-31', '2025-06-30')},
                    sector_etf={**{n: 'XLI' for n in names if n.startswith('S')}, **rmap},
                    industry={n: 'Banks' if n.startswith('S') else 'Chips' for n in names})
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(universe, 'REFERENCE_DIR', root / 'reference')
        mp.setattr(json_export, '_git_state', lambda: (COMMIT, False))
        mp.chdir(root)
        mp.setenv('MPLBACKEND', 'Agg')
        mp.setenv('PAIRS_CALENDAR', CAL.name)
        for profile in ('v33', 'v32'):
            mp.setenv('PAIRS_PROFILE', profile)
            mp.setenv('PAIRS_OUTPUT_DIR', str(root / f'out_{profile}'))
            json_export.record_start_provenance()
            results = CompleteFixedRussell3000TradingSystem(initial_capital=100_000_000).run_complete_system()
            assert not results.get('pipeline_errors')
        mp.delenv('PAIRS_PROFILE')
        mp.delenv('PAIRS_OUTPUT_DIR')
        assert _load('run_residual_statarb').main(
            ['--calendar', CAL.name, '--out', str(root / 'out_residual' / 'residual_statarb.json')]) == 0
    finally:
        json_export._START_PROVENANCE.clear()
        mp.undo()
    return root


@pytest.fixture
def arms(three_arms, monkeypatch):
    """three_arms, with its stand-in reference/ as the committed one while the evaluator runs
    (the residual run's sector map and membership root are checked against it)."""
    from pairs_trading import universe
    monkeypatch.setattr(universe, 'REFERENCE_DIR', three_arms / 'reference')
    return three_arms


def _three_args(root, residual=None, commit=COMMIT):
    return ['--calendar', CAL.name, '--expect-commit', commit, '--pairs', f'v33_pairs={root / "out_v33"}',
            '--pairs', f'v32_pairs={root / "out_v32"}',
            '--residual', str(residual or root / 'out_residual' / 'residual_statarb.json'),
            '--out', str(root / 'evaluation.json')]


def test_the_evaluator_accepts_real_exports_of_all_three_arms(arms):
    root = arms
    assert ev.main(_three_args(root)) == 0
    rep = json.loads((root / 'evaluation.json').read_text(), parse_constant=pytest.fail)
    assert sorted(rep['strategies']) == sorted(ev.REGISTERED) and rep['family'] == ['v33_pairs', 'avellaneda_lee']
    assert rep['inputs']['period_matches_calendar'] is True
    doc = json.loads((root / 'out_residual' / 'residual_statarb.json').read_text())
    al = rep['strategies']['avellaneda_lee']
    assert al['period'] == [CAL.backtest_start, CAL.data_end] and al['days'] == len(doc['daily_dates'])
    assert al['trades'] == doc['total_trades'] > 50
    assert al['exposure']['avg_gross_pct_of_equity'] == pytest.approx(100 * doc['summary']['avg_gross_exposure'])
    assert al['exposure']['days_with_open_positions'] == sum(1 for n in doc['daily_open_positions'] if n)
    assert al['vs_gatev']['source'] == 'out_v33 run' and al['vs_gatev']['n_common_days'] == al['days']
    assert al['random_pair']['percentile'] is not None
    assert [g['snapshot'] for g in al['universe_by_formation']][0] == '2024-12-31'
    prov = rep['inputs']['runs']['avellaneda_lee']['provenance']
    assert (prov['git_commit'], prov['calendar'], prov['params_hash']) == (COMMIT, CAL.name, RESIDUAL_PARAMS_HASH)
    assert prov['sector_map_registered'] is True and prov['reference_root'] == 'reference'
    runs = rep['inputs']['runs']
    for key in ('price_cache_sha256', 'macro_cache_sha256'):   # one data step: every arm read the same caches
        assert len({r['provenance'][key] for r in runs.values()}) == 1
    assert prov['universe_file_sha256'] == runs['v33_pairs']['provenance']['universe_file_sha256']
    days = {k: v['period'] for k, v in rep['strategies'].items()}
    assert len({tuple(p) for p in days.values()}) == 1


@pytest.mark.parametrize('edit, needle', [
    (lambda d: d['run_config']['study']['calendar'].update(name='dev'), 'avellaneda_lee: calendar dev'),
    (lambda d: d['run_config']['study'].update(calendar_hash='0' * 12), 'avellaneda_lee: calendar hash'),
    (lambda d: d['run_config'].update(git_commit='d' * 40), 'one commit'),
    (lambda d: d['run_config'].update(git_dirty=True), 'avellaneda_lee: git_dirty'),
    (lambda d: d['run_config']['study'].update(params_hash='0' * 12), 'avellaneda_lee: parameter hash'),
    (lambda d: d.update(non_default_switches=['universe_size=300']), 'avellaneda_lee: complete'),
    (lambda d: d['run_config']['data']['price_cache'].update(sha256='0' * 64), 'one price cache'),
    (lambda d: d.update(daily_dates=d['daily_dates'][1:] + ['2025-10-20']), 'avellaneda_lee: trading dates'),
    (lambda d: d['run_config']['data']['macro_cache'].update(sha256='0' * 64), 'one macro cache'),
    (lambda d: d['run_config']['data']['universe_file'].update(sha256='0' * 64), 'one membership index'),
    (lambda d: d['run_config']['universe'].update(reference_root='data/somewhere_else'),
     'avellaneda_lee: membership read from data/somewhere_else'),
    (lambda d: d['run_config']['sector_map']['file'].update(sha256='1' * 64), 'avellaneda_lee: sector map'),
    (lambda d: d['run_config']['sector_map'].update(registered=False), 'avellaneda_lee: sector map'),
    (lambda d: d['universe']['rankings'][3].update(selected=d['universe']['rankings'][3]['selected'] - 1),
     "fewer than S1's rule"),
    (lambda d: d.update(total_trades=0), 'avellaneda_lee: no trades'),
    (lambda d: d['universe_by_formation'][-1].update(snapshot_filed='2025-11-25'), 'filed after'),
    (lambda d: d['run_config']['study'].update(strategy='other'), 'avellaneda_lee: a residual run of other'),
])
def test_the_evaluator_refuses_a_residual_export_that_is_not_the_registered_run(arms, tmp_path, capsys,
                                                                                 edit, needle):
    doc = json.loads((arms / 'out_residual' / 'residual_statarb.json').read_text())
    edit(doc)
    altered = tmp_path / 'residual_statarb.json'
    altered.write_text(json.dumps(doc))
    args = _three_args(arms, residual=altered)
    args[args.index('--out') + 1] = str(tmp_path / 'evaluation.json')
    assert ev.main(args) == 2
    assert needle in capsys.readouterr().err
    assert not (tmp_path / 'evaluation.json').exists()


def test_the_real_residual_export_is_refused_at_another_commit(arms, tmp_path, capsys):
    args = _three_args(arms, commit='e' * 40)
    args[args.index('--out') + 1] = str(tmp_path / 'evaluation.json')
    assert ev.main(args) == 2 and 'expected commit' in capsys.readouterr().err


def test_each_strategy_id_must_be_its_registered_run(arms, tmp_path, capsys):
    out = ['--out', str(tmp_path / 'evaluation.json')]
    base = ['--calendar', CAL.name, '--expect-commit', COMMIT]
    swapped = base + ['--pairs', f'v33_pairs={arms / "out_v32"}', '--pairs', f'v32_pairs={arms / "out_v33"}',
                      '--residual', str(arms / 'out_residual' / 'residual_statarb.json')] + out
    assert ev.main(swapped) == 2
    err = capsys.readouterr().err
    assert 'v33_pairs: a pairs run of v32, not the registered pairs run of v33' in err
    assert 'v32_pairs: a pairs run of v33, not the registered pairs run of v32' in err
    pairs_as_residual = base + ['--pairs', f'v33_pairs={arms / "out_v33"}', '--pairs',
                                f'avellaneda_lee={arms / "out_v32"}'] + out
    assert ev.main(pairs_as_residual) == 2
    assert 'avellaneda_lee: a pairs run of v32, not the registered residual run of avellaneda_lee' in \
        capsys.readouterr().err
    assert not (tmp_path / 'evaluation.json').exists()
    # on the registered IDs, the real exports pass
    assert ev.main(_three_args(arms)[:-1] + [str(tmp_path / 'evaluation.json')]) == 0


def test_the_residual_export_is_published_and_registered_like_a_pairs_run(three_arms, tmp_path):
    pr, rt = _load('publish_run'), _load('register_trial')
    pr.ROOT = rt.ROOT = tmp_path
    dest = pr.publish(three_arms / 'out_residual', 'holdout/residual')
    manifest = json.loads((dest / 'MANIFEST.json').read_text())
    assert manifest['run_config']['git_commit'] == COMMIT and manifest['study']['strategy'] == 'avellaneda_lee'
    assert manifest['study']['calendar']['name'] == CAL.name
    assert manifest['price_cache']['sha256'] == json.loads(
        (three_arms / 'out_residual' / 'residual_statarb.json').read_text())['run_config']['data']['price_cache']['sha256']
    summary = rt.run_summary(dest)
    assert (summary['strategy'], summary['calendar'], summary['git_commit'], summary['complete']) == (
        'avellaneda_lee', CAL.name, COMMIT, True)
    assert summary['main']['period_start'] == CAL.backtest_start and summary['main']['trades'] > 50
    variant = tmp_path / 'variant'
    variant.mkdir()
    doc = json.loads((three_arms / 'out_residual' / 'residual_statarb.json').read_text())
    doc['non_default_switches'] = ['position_frac=0.01']
    (variant / 'residual_statarb.json').write_text(json.dumps(doc))
    with pytest.raises(SystemExit, match='variant'):
        pr.publish(variant, 'holdout/variant')
