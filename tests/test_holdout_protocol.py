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
                  complete=True, switches=(), dates=DATES, seed=0, cache='ab' * 32):
    """A run's output directory shaped like export_testing_results_to_json + headline."""
    rng = np.random.default_rng(seed)
    os.makedirs(directory, exist_ok=True)
    study = {'profile': {'name': profile}, 'calendar': {'name': calendar},
             'profile_hash': PROFILES[profile].config_hash(), 'calendar_hash': CALENDARS[calendar].config_hash()}
    rc = {'git_commit': commit, 'git_dirty': dirty, 'run_timestamp_utc': '2026-10-21T00:00:00+00:00',
          'study': study, 'data': {'price_cache': {'sha256': cache}}}
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
    (dict(v32={'cache': 'cd' * 32}), 'different price caches'),
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
if kind == 'residual':
    p = pathlib.Path(args.out); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({'daily_dates': dates, 'daily_net_returns': list(net), 'total_trades': 3,
                             'run_config': {'git_commit': os.environ['PAIRS_EXPECTED_COMMIT'], 'git_dirty': False,
                                            'study': {'calendar': {'name': cal.name}}}}))
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
      'data': {'price_cache': {'sha256': hashlib.sha256(open(cal.price_cache, 'rb').read()).hexdigest()}}}
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
                 'evaluate_holdout.py'):
        shutil.copy(os.path.join(SCRIPTS, name), repo / 'scripts' / name)
    (repo / 'scripts' / 'run_residual_statarb.py').write_text('# S2 (stubbed in this test)\n')
    shutil.copy(os.path.join(REPO, '.gitignore'), repo / '.gitignore')
    shutil.copy(os.path.join(REPO, 'pyproject.toml'), repo / 'pyproject.toml')
    (repo / 'requirements.txt').write_text('# no pins in this test\n')
    (repo / 'reference').mkdir()
    (repo / 'reference' / 'README').write_text('reference data\n')
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
    assert [(a['attempt'], a['event']) for a in reg[0]['attempts'] if a['event'] in ('start', 'failed')] == \
        [(1, 'start'), (1, 'failed'), (2, 'start')]
    evaluation = json.loads((repo / 'results' / 'holdout2026' / 'evaluation.json').read_text())
    assert sorted(evaluation['strategies']) == sorted(ev.REGISTERED)
    assert evaluation['inputs']['expect_commit'] == head
    assert (repo / 'results' / 'holdout2026' / 'logs' / 'holdout2026_a1_v33.log').exists()
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
