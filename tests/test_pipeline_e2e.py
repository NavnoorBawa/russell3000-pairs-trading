"""Full-pipeline smoke test: run_complete_system end to end on a synthetic market.

Hermetic: the synthetic universe is written to a temp directory in exactly the on-disk
format the pipeline reads (price cache, macro cache, universe CSV), so selection,
re-selection, the main backtest, the continuous walk-forward, significance, benchmarks,
the fund replay, plots and JSON exports all run without network access. Through v31 no
test executed the pipeline at all; the published results were the only integration test.
"""
import json
import os
import pickle

import numpy as np
import pandas as pd
import pytest

from tests.synthetic_market import make_market


@pytest.fixture(scope='module')
def pipeline_run(tmp_path_factory):
    root = tmp_path_factory.mktemp('e2e')
    frames, macro, _ = make_market(n_pairs=6, n_noise=6, seed=21)
    os.makedirs(root / 'data')
    with open(root / 'data' / 'enhanced_russell_3000_data.pkl', 'wb') as f:
        pickle.dump(frames, f)
    with open(root / 'data' / 'macro_data.pkl', 'wb') as f:
        pickle.dump(macro, f)
    pd.DataFrame({'Symbol': sorted(frames)}).to_csv(root / 'data' / 'marketcap.csv', index=False)

    old_cwd = os.getcwd()
    old_env = {k: os.environ.get(k) for k in ('PAIRS_USE_TRANSFORMER', 'MPLBACKEND')}
    os.environ['PAIRS_USE_TRANSFORMER'] = '0'       # ranker training is unit-tested separately
    os.environ['MPLBACKEND'] = 'Agg'
    os.chdir(root)
    try:
        from pairs_trading.trading_system import CompleteFixedRussell3000TradingSystem
        system = CompleteFixedRussell3000TradingSystem(initial_capital=100_000_000)
        results = system.run_complete_system()
    finally:
        os.chdir(old_cwd)
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return root, system, results


def test_pipeline_produces_a_complete_result(pipeline_run):
    _, system, res = pipeline_run
    for key in ('total_return', 'sharpe_ratio', 'max_drawdown', 'trades', 'daily_returns',
                'daily_dates', 'walk_forward', 'fdr_diagnostic', 'significance',
                'benchmarks', 'fund_comparison'):
        assert key in res, f"missing {key}"
    assert len(system.selected_pairs) >= 3
    assert res['total_trades'] > 0
    assert np.isfinite(res['sharpe_ratio'])
    assert len(res['daily_returns']) == len(res['daily_dates'])


def test_walk_forward_is_one_continuous_series(pipeline_run):
    _, _, res = pipeline_run
    wf = res['walk_forward']
    assert wf['total_windows'] >= 5
    assert wf['selection_clean_windows'] == wf['total_windows']
    days = [w['n_days'] for w in wf['windows']]
    assert all(d > 0 for d in days)
    starts = [pd.Timestamp(w['test_start']) for w in wf['windows']]
    assert starts == sorted(starts)
    assert wf['pooled_sharpe'] is not None and np.isfinite(wf['pooled_sharpe'])
    assert 'oos_daily_returns' not in wf, "bulky series must be dropped before export"


def test_exports_are_strict_json(pipeline_run):
    root, _, _ = pipeline_run
    exported = sorted((root / 'outputs').glob('*.json'))
    assert exported, "no JSON exported"

    def _reject(token):
        raise AssertionError(f"bare {token} in export")

    for path in exported:
        with open(path) as fh:
            json.loads(fh.read(), parse_constant=_reject)


def test_published_markers_resolve_against_a_real_run(pipeline_run):
    """Every number marked in the real README.md / index.html names a key that a real run
    writes to headline_metrics.json (or, for study.* markers, that scripts/build_site_data.py
    derives from the same run), every required headline is marked, and --write can fill them
    (values that are null in this synthetic run — e.g. ranker AUC with the ranker disabled —
    are the only acceptable gaps)."""
    import importlib.util
    import pathlib
    repo = pathlib.Path(__file__).resolve().parents[1]

    def load(name):
        spec = importlib.util.spec_from_file_location(f'_{name}_e2e', repo / 'scripts' / f'{name}.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    chk, bsd = load('check_published_numbers'), load('build_site_data')
    root, _, _ = pipeline_run
    data = json.loads((root / 'outputs' / 'headline_metrics.json').read_text(encoding='utf-8'))
    # the site data of this run, as the page reads it (strict JSON, nulls for unknowns); the
    # study-level sources (variant-family declaration, other arms) come from the repository
    study = json.loads(bsd.dumps(bsd.build(root / 'outputs', results_root=repo / 'results', root=root)))
    data = chk.with_site_data(data, study)
    for name in ('README.md', 'index.html'):
        text = (repo / name).read_text(encoding='utf-8')
        is_md = name.endswith('.md')
        markers, errors = chk.extract_markers(text, is_markdown=is_md)
        assert not errors, errors
        keys = {k for k, _, _ in markers}
        assert set(chk.REQUIRED_KEYS) <= keys, f"{name} lacks markers for {set(chk.REQUIRED_KEYS) - keys}"
        filled, n, problems = chk.write_text(data, text, is_markdown=is_md)
        assert n > 0
        assert not [p for p in problems if 'unknown key' in p or 'nested markup' in p], problems
        _, failures, _, _ = chk.check_text(data, filled, name, is_markdown=is_md)
        assert all('null' in f for f in failures), failures


def test_every_export_carries_the_same_provenance(pipeline_run):
    """One run, one provenance block: the results, the fund table and the headline snapshot
    must carry an identical run_config with the data span filled in."""
    root, _, _ = pipeline_run
    configs = {}
    for path in sorted((root / 'outputs').glob('*.json')):
        doc = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(doc, dict) and 'run_config' in doc:
            configs[path.name] = doc['run_config']
    assert len(configs) >= 3, sorted(configs)
    first = next(iter(configs.values()))
    assert all(c == first for c in configs.values()), "exports disagree on run_config"
    assert first['data']['data_start'] and first['data']['data_end']
    headline = json.loads((root / 'outputs' / 'headline_metrics.json').read_text(encoding='utf-8'))
    assert headline['non_default_switches'] == ['ranker=none']   # PAIRS_USE_TRANSFORMER=0 on the v32 profile
    assert headline['complete'] is True


def test_v32_profile_reproduces_the_v32_code_exactly(pipeline_run):
    """Golden master: the session runs the v32 profile (tests/conftest.py), and on this
    synthetic market it must make exactly the decisions the v32 code (commit fa4c02b) made —
    same pairs, same trades on the same dates for the same reasons, same P&L. Introducing
    study profiles (study_config.py) must not change what a v32 run computes."""
    with open(os.path.join(os.path.dirname(__file__), 'fixtures', 'v32_synthetic_golden.json')) as f:
        gold = json.load(f)
    _, system, res = pipeline_run
    assert system.profile.name == 'v32'
    assert sorted(map(list, system.selected_pairs)) == gold['selected_pairs']
    got = [[t['pair'], str(t['signal_date'])[:10], str(t['date'])[:10], str(t['exit_date'])[:10],
            t['exit_reason']] for t in res['trades']]
    assert got == [t[:5] for t in gold['trades']]
    assert [t['net_pnl_pct'] for t in res['trades']] == pytest.approx([t[5] for t in gold['trades']],
                                                                      rel=1e-9, abs=1e-12)
    assert res['total_return'] == pytest.approx(gold['total_return'], rel=1e-9)
    assert res['sharpe_ratio'] == pytest.approx(gold['sharpe_ratio'], rel=1e-9)
    wf = res['walk_forward']
    assert wf['total_trades'] == gold['walk_forward']['total_trades']
    assert [w['total_return_pct'] for w in wf['windows']] == pytest.approx(
        gold['walk_forward']['window_returns_pct'], abs=1e-4)
    assert res['fdr_diagnostic'] == gold['fdr_diagnostic']
