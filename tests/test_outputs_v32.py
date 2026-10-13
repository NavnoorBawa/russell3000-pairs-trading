"""v32 output layer: JSON exports, run provenance, headline metrics, charts, CLI summary.

Most tests use hand-built result dicts shaped like the engine's (so each rule is tested
in isolation with known numbers); `engine_run` exercises the exports end to end on real
engine output from the hermetic synthetic market.
"""
import hashlib
import json
import math
import os
import subprocess
import sys
import warnings

import numpy as np
import pandas as pd
import pytest
import torch
from scipy import stats

from pairs_trading import json_export as je
from pairs_trading import main as cli
from pairs_trading import plotting

TZ = 'America/New_York'
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _strict_load(path):
    """json.load that rejects the bare NaN/Infinity tokens strict parsers reject."""
    def bad(token):
        raise ValueError(f'non-standard JSON token {token}')
    with open(path, encoding='utf-8') as fh:
        return json.load(fh, parse_constant=bad)


def _trade(pair='AAA-BBB', z=2.2, net=0.001, cal=10, td=7, action='LONG', reason='target',
           entry='2023-07-06', exit_='2023-07-18'):
    entry_ts, exit_ts = pd.Timestamp(entry, tz=TZ), pd.Timestamp(exit_, tz=TZ)
    return {
        'date': entry_ts, 'signal_date': entry_ts - pd.Timedelta(days=1),
        'exit_signal_date': exit_ts - pd.Timedelta(days=1), 'exit_date': exit_ts,
        'exit_reason': reason, 'exit_prices_real': np.bool_(True),
        'pair': pair, 'action': action, 'long_symbol': pair.split('-')[0], 'short_symbol': pair.split('-')[1],
        'long_notional': 1.0e6, 'short_notional': 0.9e6, 'hedge_ratio': np.float64(0.9),
        'leg_daily_vol': 0.02, 'leg_adv_dollars': 5e7,
        'position_size': 1.9e6, 'position_pct': 0.019, 'signal_strength': min(abs(z) / 2.5, 1.0),
        'zscore': z, 'pair_quality': 0.8, 'feature_quality': 1.0,
        'spread_return': net * 50, 'gross_pnl_pct': net + 0.0001, 'transaction_costs': 1000.0,
        'transaction_cost_pct': 0.0001, 'net_pnl_pct': net, 'pnl_dollar': net * 1e8,
        'holding_days': cal, 'trading_days_held': np.int64(td),
        'cost_breakdown': {'commission': 100.0, 'bid_ask': 300.0, 'market_impact': 500.0,
                           'borrow': 50.0, 'financing': 50.0, 'total_cost': 1000.0},
        'unit_path': [('2023-07-06', 0.001), ('2023-07-07', -0.002)],
    }


def _results(trades=None, profit_factor=0.62):
    trades = [_trade(net=0.002), _trade(net=-0.001, reason='stop'), _trade(pair='CCC-DDD', net=-0.0005)] \
        if trades is None else trades
    dates = [str(d.date()) for d in pd.bdate_range('2023-07-03', periods=6)]
    rets = [0.0, -0.001, 0.0005, 0.0, -0.002, -0.0004]
    equity = list(1e8 * np.cumprod(1 + np.array(rets)))
    windows = [{'window': 10 + i, 'total_return_pct': r, 'total_trades': t, 'selection_clean': True,
                'sharpe_ratio': s}
               for i, (r, t, s) in enumerate([(-0.46341, 3, -2.1), (0.56749, 2, 1.4), (0.0, 0, 0.0)])]
    return {
        'total_return': equity[-1] / 1e8 - 1, 'annualized_return': -0.15, 'final_portfolio_value': equity[-1],
        'total_trades': len(trades), 'win_rate': 0.28571, 'profit_factor': profit_factor,
        'sharpe_ratio': -0.31494, 'max_drawdown': -0.0081449, 'volatility': 0.0123,
        'avg_trade_return': -0.0002, 'trades_per_day': 0.1, 'total_cost_impact_pct': 0.0004,
        'exit_reasons': {'target': 2, 'stop': 1}, 'signal_rejections': {'cusum_break': 4},
        'trades': trades, 'daily_returns': rets, 'daily_dates': dates, 'equity_curve': equity,
        'halted_on': None, 'halt_reason': '',
        'walk_forward': {
            'windows': windows, 'total_windows': 3, 'skipped_windows': 9, 'selection_clean_windows': 3,
            'profitable_windows': 1, 'avg_window_return_pct': 0.034693, 'median_window_return_pct': 0.0,
            'avg_sharpe': -0.233, 'pooled_sharpe': -1.23456, 'stitched_total_return_pct': 0.0987,
            'max_drawdown_pct': -3.14159, 'total_trades': 5, 'win_rate_pct': 40.0,
            'exit_reasons': {'time': 5}, 'oos_start': '2023-01-05', 'oos_end': '2023-09-29',
            'oos_daily_returns': [0.001] * 5, 'all_window_daily_returns': [0.001] * 5,
        },
        'significance': {
            'main_backtest': {'n_days': 6, 'ann_sharpe': -0.31494, 'hac': {'tstat': -0.4912, 'pvalue': 0.63251},
                              'psr_gt0': {'psr': 0.32549}, 'bootstrap_sharpe_ci': {'lo': -1.7049, 'hi': 0.8012},
                              'deflated_sharpe': {'dsr': 0.00912}},
            'oos_daily': {'n_days': 5, 'ann_sharpe': -1.23456, 'hac': {'tstat': -1.8601, 'pvalue': 0.06288},
                          'psr_gt0': {'psr': 0.02211}, 'bootstrap_sharpe_ci': {'lo': -2.4101, 'hi': 0.0612},
                          'deflated_sharpe': {'dsr': 0.00001}},
            'oos_windows': {'n': 10, 'mean': -0.0028234, 'tstat': -1.9412, 'pvalue': 0.08412, 'positive': 1,
                            'ci_lo': -0.006112, 'ci_hi': 0.000471, 'boot_ci_lo': -0.005481, 'boot_ci_hi': -0.00008},
        },
        'benchmarks': {'distance_method': {'total_return_pct': 2.7801, 'sharpe_ratio': 0.2612},
                       'random_control': {'total_return_pct': -1.74, 'sharpe_ratio': -0.02, 'n_draws': 5}},
        'fdr_diagnostic': {'pairs_tested': 36524, 'significant_raw_p05': 3725, 'survive_bh_fdr_q05': 0,
                           'survive_bh_fdr_q10': 0, 'final_selected_pairs': 40},
        'fund_comparison': {
            'retail': {'profile_name': 'Retail / Small Prop Trader', 'total_return_pct': -0.4412,
                       'sharpe_ratio': -0.9612, 'max_drawdown_pct': -0.6049, 'max_gross_leverage': 0.0913,
                       'profit_factor': float('inf'), 'final_equity': 99_558_800.0, 'stopped_on': None,
                       'equity_curve': [{'date': d, 'value': 1e8} for d in dates]},
        },
    }


@pytest.fixture
def fixed_config():
    return {'run_timestamp_utc': '2026-01-01T00:00:00+00:00', 'git_commit': 'f' * 40, 'package_version': '0'}


# ── _json_safe / atomic writes ─────────────────────────────────────────────────

def test_json_safe_converts_pandas_numpy_and_python_types():
    df = pd.DataFrame({'d': pd.to_datetime(['2023-07-03', None]), 'x': [1.5, np.nan]})
    obj = {
        'ts_tz': pd.Timestamp('2023-07-03', tz=TZ), 'dt': pd.Timestamp('2023-07-03 10:30').to_pydatetime(),
        'date': pd.Timestamp('2023-07-03').date(), 'dt64': np.datetime64('2023-07-03'),
        'nat': pd.NaT, 'nat64': np.datetime64('NaT'), 'set': {'b', 'a', 'c'}, 'fset': frozenset({3, 1, 2}),
        'tuple': (1, np.int64(2)), 'arr_dt': np.array(['2023-07-03'], dtype='datetime64[ns]'),
        'series': pd.Series([1, 2]), 'df': df, 'inf': float('inf'), 'nan': np.float64('nan'),
        'bool': np.bool_(True), 'period': pd.Period('2023-07', 'M'), 'td': pd.Timedelta(days=1),
        ('AAA', 'BBB'): 1, np.int64(7): 'seven', pd.Timestamp('2023-07-03'): 'ts-key',
    }
    out = je._json_safe(obj)
    assert out['ts_tz'] == '2023-07-03T00:00:00-04:00'
    assert out['dt'] == '2023-07-03T10:30:00'
    assert out['date'] == '2023-07-03'
    assert out['dt64'] == '2023-07-03T00:00:00'
    assert out['nat'] is None and out['nat64'] is None
    assert out['set'] == ['a', 'b', 'c'] and out['fset'] == [1, 2, 3]
    assert out['tuple'] == [1, 2]
    assert out['arr_dt'] == ['2023-07-03T00:00:00']            # not raw int64 nanosecond ticks
    assert out['series'] == [1, 2]
    assert out['df'] == [{'d': '2023-07-03T00:00:00', 'x': 1.5}, {'d': None, 'x': None}]
    assert out['inf'] is None and out['nan'] is None
    assert out['bool'] is True and out['period'] == '2023-07' and out['td'] == 'P1DT0H0M0S'
    assert out['AAA-BBB'] == 1 and out['7'] == 'seven' and out['2023-07-03T00:00:00'] == 'ts-key'
    json.dumps(out, allow_nan=False)                           # strictly serialisable


def test_json_safe_rejects_colliding_keys():
    with pytest.raises(ValueError, match='collide'):
        je._json_safe({1: 'a', '1': 'b'})


def test_atomic_write_replaces_and_leaves_no_temp_files(tmp_path):
    path = tmp_path / 'out.json'
    je._atomic_write_json({'a': 1}, path)
    je._atomic_write_json({'a': 2}, path)
    assert _strict_load(path) == {'a': 2}
    assert sorted(p.name for p in tmp_path.iterdir()) == ['out.json']


def test_atomic_write_failure_keeps_the_old_file_and_propagates(tmp_path):
    path = tmp_path / 'out.json'
    je._atomic_write_json({'a': 1}, path)
    with pytest.raises(TypeError):
        je._atomic_write_json({'a': object()}, path)           # unknown type: loud failure
    assert _strict_load(path) == {'a': 1}                      # old content intact, not truncated
    assert sorted(p.name for p in tmp_path.iterdir()) == ['out.json']


def test_atomic_write_uses_normal_file_permissions(tmp_path):
    old = os.umask(0o022)
    try:
        path = je._atomic_write_json({'a': 1}, tmp_path / 'out.json')
    finally:
        os.umask(old)
    assert os.stat(path).st_mode & 0o777 == 0o644


def test_serialisation_is_independent_of_the_hash_seed():
    code = ("import json; from pairs_trading.json_export import _json_safe, calculate_pair_correlations;"
            "print(json.dumps(_json_safe({'s': {'MSFT', 'AAPL', 'XOM', 'CVX', 'GOOG', 'KO'}})));"
            "print(calculate_pair_correlations([{'pair': p} for p in ['X-Y', 'A-B', 'M-N', 'A-B']]))")
    outs = []
    for seed in ('1', '2'):
        env = dict(os.environ, PYTHONHASHSEED=seed, MPLBACKEND='Agg')
        outs.append(subprocess.run([sys.executable, '-c', code], cwd=REPO, env=env, capture_output=True,
                                   text=True, check=True, timeout=120).stdout)
    assert outs[0] == outs[1]
    assert '["AAPL", "CVX", "GOOG", "KO", "MSFT", "XOM"]' in outs[0]


# ── run provenance ─────────────────────────────────────────────────────────────

def test_run_config_records_switches_versions_and_data(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('PAIRS_FILL', 'OPEN')
    monkeypatch.setenv('PAIRS_USE_TRANSFORMER', '0')
    monkeypatch.setenv('PAIRS_RESELECT', 'FULL')
    monkeypatch.delenv('PAIRS_DEMO_UNIVERSE', raising=False)
    os.makedirs('data')
    payload = os.urandom(10_000) + b'end'
    with open(je.DATA_CACHE_FILE, 'wb') as fh:
        fh.write(payload)
    cfg = je.build_run_config({'daily_dates': ['2023-07-03', '2025-06-30']},
                              {'total_symbols_processed': 2542, 'pairs_selected': 40,
                               'data_start': pd.Timestamp('2020-01-02', tz=TZ), 'data_end': '2025-06-30'})
    assert cfg['env']['PAIRS_FILL'] == 'OPEN' and cfg['env']['PAIRS_DEMO_UNIVERSE'] is None
    assert cfg['effective'] == {'fill': 'open', 'use_transformer_ranker': False, 'reselect': 'full'}
    assert cfg['env']['PAIRS_RESELECT'] == 'FULL'
    assert je.non_default_switches(cfg) == ['PAIRS_FILL=open', 'PAIRS_USE_TRANSFORMER=0', 'PAIRS_RESELECT=full']
    data = cfg['data']
    assert (data['data_start'], data['data_end']) == ('2020-01-02', '2025-06-30')
    assert (data['backtest_start'], data['backtest_end']) == ('2023-07-03', '2025-06-30')
    assert (data['n_symbols'], data['n_pairs']) == (2542, 40)
    cache = data['price_cache']
    assert cache['sha256'] == hashlib.sha256(payload).hexdigest()
    assert cache['size_bytes'] == len(payload)
    assert cache['path'] == je.DATA_CACHE_FILE                 # relative: no home directory leaked
    assert cfg['versions']['python'] and cfg['versions']['numpy'] == np.__version__
    assert cfg['versions']['pandas'] == pd.__version__ and cfg['versions']['torch']
    assert cfg['package_version'] == je.package_version()
    assert cfg['git_commit'] is None or len(cfg['git_commit']) == 40
    assert cfg['run_timestamp_utc'].endswith('+00:00')


def test_file_fingerprint_streams_in_chunks_and_handles_absence(tmp_path):
    p = tmp_path / 'blob.bin'
    p.write_bytes(b'x' * 1000 + b'y')
    fp = je.file_fingerprint(str(p), chunk_size=7)
    assert fp['sha256'] == hashlib.sha256(b'x' * 1000 + b'y').hexdigest()
    assert je.file_fingerprint(str(tmp_path / 'missing.pkl')) is None


def test_package_version_falls_back_to_pyproject():
    import tomllib
    with open(os.path.join(REPO, 'pyproject.toml'), 'rb') as fh:
        declared = tomllib.load(fh)['project']['version']
    assert je.package_version() == declared                    # not installed in the test env


def test_run_config_is_built_once_per_run(tmp_path):
    res = _results()
    je.export_testing_results_to_json(res, {}, output_dir=str(tmp_path))
    cfg = res['run_config']
    je.export_headline_metrics(res, {}, path=str(tmp_path / 'h.json'))
    assert _strict_load(tmp_path / 'h.json')['run_config'] == json.loads(json.dumps(cfg))


# ── main results export ────────────────────────────────────────────────────────

def test_export_writes_everything_even_with_zero_trades(tmp_path, fixed_config):
    res = _results(trades=[], profit_factor=0.0)
    res.update(total_trades=0, win_rate=0.0, exit_reasons={}, run_config=fixed_config)
    path = je.export_testing_results_to_json(res, {'total_symbols_processed': 10}, output_dir=str(tmp_path))
    data = _strict_load(path)
    assert data['all_trades'] == [] and data['pair_performance'] == []
    assert data['overall_performance']['profit_factor'] is None   # undefined without trades
    assert data['overall_performance']['win_rate_pct'] is None
    assert data['walk_forward_validation']['total_windows'] == 3     # still published
    assert data['significance']['oos_windows']['n'] == 10
    assert data['benchmarks']['distance_method']['sharpe_ratio'] == 0.2612
    assert (tmp_path / 'pairs_trading_results_2023_2025_unbiased_compact.json').exists()


def test_export_metadata_is_honest(tmp_path, fixed_config):
    res = _results()
    res['run_config'] = fixed_config
    data = _strict_load(je.export_testing_results_to_json(res, {}, output_dir=str(tmp_path)))
    meta = data['metadata']
    assert 'Transformer Encoder Pairs Trading' not in json.dumps(meta)
    assert 'Research Paper' not in json.dumps(data)
    assert meta['backtest_period'] == {'start': '2023-07-03', 'end': '2023-07-10'}
    assert meta['testing_period'] == '2023-07-03 to 2023-07-10'   # from the data, not hard-coded
    desc = meta['strategy_description'].lower()
    assert 'ranks candidate entries' in desc and 'not a transformer trading model' in desc
    assert meta['initial_capital'] == pytest.approx(1e8)
    assert data['run_config'] == fixed_config
    # the bulky continuous OOS series never reach the export
    assert 'oos_daily_returns' not in data['walk_forward_validation']


def test_export_trade_records_are_complete_and_honestly_labelled(tmp_path, fixed_config):
    res = _results()
    res['run_config'] = fixed_config
    path = je.export_testing_results_to_json(res, {}, output_dir=str(tmp_path))
    text = open(path, encoding='utf-8').read()
    assert 'unit_path' not in text
    t = _strict_load(path)['all_trades'][0]
    assert t['signal_date'] == '2023-07-05' and t['entry_date'] == '2023-07-06'
    assert t['exit_signal_date'] == '2023-07-17' and t['exit_date'] == '2023-07-18'
    assert t['exit_reason'] == 'target' and t['hedge_ratio'] == 0.9
    assert (t['long_symbol'], t['short_symbol']) == ('AAA', 'BBB')
    assert t['holding_days_calendar'] == 10 and t['trading_days_held'] == 7
    assert t['net_pnl_pct_of_equity'] == pytest.approx(0.2)        # 0.002 of equity, in %
    assert t['spread_return_pct'] == pytest.approx(10.0)           # per $ of gross notional, in %
    for legacy in ('net_pnl_pct', 'gross_pnl_pct', 'holding_days', 'date'):
        assert legacy not in t


def test_export_profit_factor_infinity_is_null_not_a_sentinel(tmp_path, fixed_config):
    res = _results(trades=[_trade(net=0.001), _trade(net=0.002)], profit_factor=float('inf'))
    res['run_config'] = fixed_config
    data = _strict_load(je.export_testing_results_to_json(res, {}, output_dir=str(tmp_path)))
    assert data['overall_performance']['profit_factor'] is None
    assert data['pair_performance'][0]['profit_factor'] is None
    assert '999' not in json.dumps(data['overall_performance'])


def test_export_serialisation_errors_propagate(tmp_path, fixed_config):
    res = _results()
    res['run_config'] = fixed_config
    res['benchmarks'] = {'weird': object()}
    with pytest.raises(TypeError):
        je.export_testing_results_to_json(res, {}, output_dir=str(tmp_path))
    assert not (tmp_path / je.DEFAULT_RESULTS_FILENAME).exists()   # no bogus/partial file


def test_pair_sharpe_uses_actual_trade_frequency():
    nets = [0.002, -0.001, 0.003, 0.0005, -0.0015]
    trades = [_trade(net=n) for n in nets] + [_trade(pair='CCC-DDD', net=n) for n in nets[:4]]
    perf = je.calculate_pair_performance(trades, span_years=2.0)
    r = np.array(nets)
    per_trade = r.mean() / r.std(ddof=1)
    assert perf['AAA-BBB']['sharpe_per_trade'] == pytest.approx(per_trade)
    assert perf['AAA-BBB']['trades_per_year'] == pytest.approx(2.5)
    assert perf['AAA-BBB']['sharpe_ratio_annualized'] == pytest.approx(per_trade * math.sqrt(2.5))
    # below 5 trades both are noise and are withheld
    assert perf['CCC-DDD']['sharpe_per_trade'] is None
    assert perf['CCC-DDD']['sharpe_ratio_annualized'] is None
    # without a span the frequency is unknown: no annualisation
    assert je.calculate_pair_performance(trades)['AAA-BBB']['sharpe_ratio_annualized'] is None


def test_span_years_from_dates():
    assert je._span_years(['2023-07-03', '2025-07-03']) == pytest.approx(731 / 365.25)
    assert je._span_years(['2023-07-03']) is None


def test_zscore_buckets_are_populated_and_exhaustive():
    zs = [1.8, 1.95, -2.0, 2.49, 2.5, -2.99, 3.0, -4.2]
    trades = [_trade(z=z) for z in zs]
    out = je.calculate_zscore_bucket_statistics(trades)
    assert list(out) == ['<1.8', '1.8-2.0', '2.0-2.5', '2.5-3.0', '>=3.0']
    assert [out[k]['count'] for k in out] == [0, 2, 2, 2, 2]
    assert sum(v['count'] for v in out.values()) == len(trades)


def test_signal_strength_cannot_fill_the_old_weak_bucket():
    # the audit's premise: strength = min(|z|/2.5, 1) with |z| >= ENTRY_Z
    from pairs_trading.trading_system import CompleteFixedRussell3000TradingSystem as S
    assert min(S.ENTRY_Z / 2.5, 1.0) > 0.7


def test_holding_buckets_use_trading_days():
    days = [0, 2, 3, 5, 6, 10, 11, 15, 16, 25, 26, 40]
    out = je.calculate_holding_period_statistics([_trade(td=d, cal=d * 2) for d in days])
    assert list(out) == ['0-2', '3-5', '6-10', '11-15', '16-25', '>25']
    assert [v['count'] for v in out.values()] == [2, 2, 2, 2, 2, 2]


def test_pair_list_is_sorted():
    trades = [{'pair': p} for p in ['X-Y', 'A-B', 'M-N', 'A-B']]
    out = je.calculate_pair_correlations(trades)
    assert out['pairs'] == ['A-B', 'M-N', 'X-Y']
    assert list(out['trades_per_pair'].items()) == [('A-B', 2), ('M-N', 1), ('X-Y', 1)]
    assert out['correlation_matrix'] is None


def test_fund_comparison_export(tmp_path, fixed_config):
    fc = _results()['fund_comparison']
    fc['retail']['cost_components'] = {'commission_pct': 0.01}
    path = je.export_fund_comparison_to_json(fc, run_config=fixed_config, output_dir=str(tmp_path))
    data = _strict_load(path)
    assert data['profiles']['retail']['profit_factor'] is None
    assert 'equity_curve' not in data['profiles']['retail']
    assert data['metadata']['initial_capital_usd']['retail'] == pytest.approx(1e8, rel=1e-6)
    rows = {r['metric']: r for r in data['summary_table']}
    assert rows['Peak Gross Leverage (realised)']['retail'] == 0.0913
    assert 'N/A' not in json.dumps(data['summary_table'])
    assert data['run_config'] == fixed_config
    assert je.export_fund_comparison_to_json({}) == ''


# ── headline metrics ───────────────────────────────────────────────────────────

def test_headline_schema_and_rounding(tmp_path, fixed_config):
    res = _results()
    res['run_config'] = fixed_config
    path = je.export_headline_metrics(res, {}, path=str(tmp_path / 'outputs' / 'headline_metrics.json'))
    h = _strict_load(path)
    assert h['schema'] == 1 and h['version'] == je.package_version() and h['run_config'] == fixed_config
    assert h['main'] == {'period_start': '2023-07-03', 'period_end': '2023-07-10',
                         'total_return_pct': round((res['equity_curve'][-1] / 1e8 - 1) * 100, 2),
                         'sharpe': -0.31, 'trades': 3, 'win_rate_pct': 28.6, 'max_drawdown_pct': -0.81,
                         'exit_reasons': {'stop': 1, 'target': 2},
                         'avg_gross_exposure_pct': None, 'annual_turnover_x': None}
    assert h['ranker'] == {'trained': False, 'train_samples': None, 'oos_signals': None, 'oos_auc': None,
                           'wf_pooled_auc': None, 'wf_windows_trained': None}
    o = h['oos']
    assert {'period_start', 'period_end', 'windows', 'windows_positive', 'windows_no_trades',
            'avg_window_return_pct', 'median_window_return_pct', 'pooled_sharpe', 'total_return_pct',
            'trades', 'max_drawdown_pct', 'window_returns_pct', 'window_trades'} <= set(o)
    assert (o['windows'], o['windows_positive'], o['windows_no_trades']) == (3, 1, 1)
    assert (o['avg_window_return_pct'], o['median_window_return_pct']) == (0.035, 0.0)
    assert (o['pooled_sharpe'], o['total_return_pct'], o['max_drawdown_pct']) == (-1.23, 0.1, -3.14)
    assert o['window_returns_pct'] == [-0.463, 0.567, 0.0] and o['window_trades'] == [3, 2, 0]
    assert o['window_ids'] == [10, 11, 12]
    s = h['significance']
    assert {'ann_sharpe', 'hac_t', 'hac_p', 'psr', 'boot_lo', 'boot_hi', 'dsr'} <= set(s['main'])
    assert s['main']['hac_p'] == 0.633 and s['main']['psr'] == 0.3255 and s['main']['psr_pct'] == 32.5
    assert s['oos_daily']['boot_hi'] == 0.06 and s['oos_daily']['dsr'] == 0.0
    w = s['oos_windows']
    assert set(w) == {'n', 'mean_pct', 't', 'p', 'p_one_sided_negative', 'ci_lo_pct', 'ci_hi_pct',
                      'boot_ci_lo_pct', 'boot_ci_hi_pct', 'positive'}
    assert (w['n'], w['mean_pct'], w['t'], w['p'], w['positive']) == (10, -0.282, -1.94, 0.084, 1)
    assert w['p_one_sided_negative'] == round(stats.t.cdf(-1.9412, 9), 3)
    assert (w['ci_lo_pct'], w['ci_hi_pct'], w['boot_ci_hi_pct']) == (-0.611, 0.047, -0.008)
    b = h['benchmarks']
    assert b['gatev'] == {'total_return_pct': 2.78, 'sharpe': 0.26}
    # the average-of-draws Sharpe is not relabelled as a median
    assert b['random_control'] == {'median_sharpe': None, 'p5_sharpe': None, 'p95_sharpe': None, 'n_draws': 5,
                                   'strategy_percentile': None}
    assert b['sharpe_diff_vs_gatev'] == {'diff': None, 'p': None, 'ci_lo': None, 'ci_hi': None}
    assert h['fdr'] == {'pairs_tested': 36524, 'significant_raw_p05': 3725, 'survive_bh_fdr_q05': 0,
                        'survive_bh_fdr_q10': 0, 'final_selected_pairs': 40}
    assert h['fund_profiles'] == {'retail': {'name': 'Retail / Small Prop Trader', 'total_return_pct': -0.44,
                                             'sharpe': -0.96, 'max_drawdown_pct': -0.6,
                                             'max_gross_leverage': 0.09}}


def test_headline_missing_sections_are_null_not_crashes(fixed_config):
    h = je.build_headline_metrics({'run_config': fixed_config}, {})
    assert h['main']['sharpe'] is None and h['main']['trades'] is None
    assert h['oos']['pooled_sharpe'] is None and h['oos']['window_returns_pct'] == []
    assert h['significance']['oos_windows']['p'] is None
    assert h['benchmarks']['gatev'] == {'total_return_pct': None, 'sharpe': None}
    assert h['fund_profiles'] == {} and set(h['fdr'].values()) == {None}
    json.dumps(h, allow_nan=False)


def _benchmark_block(draws, with_flat_keys=True):
    """benchmarks[...] shaped like pairs_trading.benchmark.run_benchmarks' output."""
    test = {'diff': -0.5712, 'pvalue': 0.41234, 'ci_lo': -1.4, 'ci_hi': 0.31, 'block': 9}
    out = {
        'distance_method': {'total_return_pct': 2.7801, 'sharpe_ratio': 0.2612},
        'random_control': {'n_draws': len(draws), 'sharpe_ratio': float(np.mean(draws)),
                           'sharpe_distribution': {'median': 0.0412, 'p5': -0.4401, 'p95': 1.0391},
                           'draw_sharpes': draws},
        'vs_strategy': {'main_backtest': {'n_common_days': 500, 'sharpe_difference_vs_distance': test,
                                          'strategy_percentile_in_random': 21.5},
                        'oos': {'n_common_days': 400,
                                'sharpe_difference_vs_distance': dict(test, diff=-9.0, pvalue=0.001),
                                'strategy_percentile_in_random': 1.0}},
    }
    if with_flat_keys:
        out['sharpe_diff_vs_gatev'] = dict(test, strategy='main_backtest', n_common_days=500)
        out['random_control']['strategy_percentile'] = 21.5
    return out


@pytest.mark.parametrize('flat', [True, False])
def test_headline_reads_the_benchmark_distribution_and_sharpe_test(fixed_config, flat):
    res = _results()
    res['run_config'] = fixed_config
    res['benchmarks'] = _benchmark_block([-0.45, -0.2, -0.02, 0.3, 1.08], with_flat_keys=flat)
    b = je.build_headline_metrics(res, {})['benchmarks']
    # the benchmark's own distribution wins over re-computing from the rounded draws
    assert b['random_control'] == {'median_sharpe': 0.04, 'p5_sharpe': -0.44, 'p95_sharpe': 1.04,
                                   'n_draws': 5, 'strategy_percentile': 21.5}
    # the headline (first) series' date-aligned Ledoit-Wolf test, not the OOS one
    assert b['sharpe_diff_vs_gatev'] == {'diff': -0.57, 'p': 0.412, 'ci_lo': -1.4, 'ci_hi': 0.31}
    assert je.sharpe_diff_vs_gatev(res['benchmarks'], label='oos')['diff'] == -9.0


def test_random_control_falls_back_to_the_draws():
    draws = [-0.45, -0.2, -0.02, 0.3, 1.08]
    rc = je.random_control_summary({'n_draws': 5, 'draw_sharpes': draws}, strategy_sharpe=-0.31)
    assert rc['median_sharpe'] == pytest.approx(-0.02)
    assert rc['p5_sharpe'] == pytest.approx(np.percentile(draws, 5))
    assert rc['p95_sharpe'] == pytest.approx(np.percentile(draws, 95))
    assert rc['strategy_percentile'] == pytest.approx(20.0)       # 1 of 5 draws below -0.31
    assert je.random_control_summary({})['median_sharpe'] is None


def test_window_test_pvalues_one_sided():
    # reported one-sided values (significance.oos_window_test) are used as-is...
    p = je.window_test_pvalues({'n': 10, 'tstat': -1.94, 'pvalue': 0.085,
                                'pvalue_mean_lt0': 0.0421, 'pvalue_mean_gt0': 0.9579})
    assert (p['p_two_sided'], p['p_less'], p['p_greater']) == (0.085, 0.0421, 0.9579)
    # ...and derived from the same t-test for an older report without them
    p = je.window_test_pvalues({'n': 10, 'tstat': -1.94, 'pvalue': 0.085})
    assert p['p_less'] == pytest.approx(stats.t.cdf(-1.94, 9))
    assert p['p_greater'] == pytest.approx(stats.t.sf(-1.94, 9))
    assert p['p_less'] + p['p_greater'] == pytest.approx(1.0)
    assert je.window_test_pvalues({})['p_less'] is None


# ── charts ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def captured_figures(monkeypatch):
    """Keep figures alive past plotting's plt.close so a test can inspect what was drawn."""
    figs = []
    real_close = plotting.plt.close

    def keep(fig=None):
        figs.append(fig)
    monkeypatch.setattr(plotting.plt, 'close', keep)
    yield figs
    for f in figs:
        real_close(f)


def test_plot_results_draws_real_equity_on_real_dates(tmp_path, monkeypatch, captured_figures):
    monkeypatch.chdir(tmp_path)
    res = _results()
    path = plotting.plot_results(res['daily_returns'], res, initial_capital=1e8, dates=res['daily_dates'])
    assert path == os.path.join(str(tmp_path), 'outputs', 'backtest_results.png') and os.path.exists(path)
    fig = captured_figures[-1]
    ax_eq, ax_dd, ax_tr = fig.axes[:3]
    x, y = ax_eq.lines[0].get_data()
    np.testing.assert_allclose(y, res['equity_curve'])        # dollars of the $100M book
    assert pd.Timestamp(x[0]) == pd.Timestamp('2023-07-03') and pd.Timestamp(x[-1]) == pd.Timestamp('2023-07-10')
    dd = ax_dd.lines[0].get_ydata()
    assert dd[1] == pytest.approx(-0.1)                       # first loss vs the starting capital
    assert ax_tr.get_ylabel().startswith('Net P&L per trade')  # not a daily-return histogram
    text = ' '.join(t.get_text() for ax in fig.axes for t in ax.texts)
    assert 'Annualised volatility' in text and 'Daily Volatility' not in text


def test_plot_results_backward_compatible_call_and_fixed_filename(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    metrics = {'sharpe_ratio': 0.1, 'total_trades': 2, 'profit_factor': float('inf'), 'win_rate': 1.0}
    assert plotting.plot_results([0.01, -0.005, 0.002], metrics)
    assert plotting.plot_results([0.01, -0.005, 0.002], metrics)
    assert os.listdir(tmp_path / 'outputs') == ['backtest_results.png']   # overwritten, no pile-up


def test_plot_results_nothing_to_plot_removes_stale_chart(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    plotting.plot_results([0.01, 0.02], {})
    assert plotting.plot_results([], {}) is None
    assert not (tmp_path / 'outputs' / 'backtest_results.png').exists()


def test_format_profit_factor():
    assert plotting.format_profit_factor(float('inf')) == 'inf (no losing trade)'
    assert plotting.format_profit_factor(None) == 'n/a'
    assert plotting.format_profit_factor(float('nan')) == 'n/a'
    assert plotting.format_profit_factor(1.234) == '1.23'


def test_constant_predictor_bce_matches_brute_force():
    for b, w in [(0.43, 0.57 / 0.43), (0.2, 1.0), (0.3, 2.5)]:
        grid = np.linspace(1e-4, 1 - 1e-4, 200_001)
        brute = np.min(-(w * b * np.log(grid) + (1 - b) * np.log(1 - grid)))
        assert plotting.constant_predictor_bce(b, w) == pytest.approx(brute, rel=1e-6)
    assert plotting.constant_predictor_bce(0.43, 0.57 / 0.43) == pytest.approx(2 * 0.57 * math.log(2))
    assert plotting.constant_predictor_bce(None, 1.0) is None and plotting.constant_predictor_bce(1.0, 1.0) is None


def test_plot_ranker_training(tmp_path, monkeypatch, captured_figures):
    monkeypatch.chdir(tmp_path)
    summary = {'n_samples': 5000, 'base_rate': 0.43, 'epochs': 3, 'epoch_losses': [0.80, 0.79, 0.788],
               'pos_weight': 0.57 / 0.43}
    path = plotting.plot_ranker_training(summary)
    assert path.endswith(os.path.join('outputs', 'ranker_training.png')) and os.path.exists(path)
    ax = captured_figures[-1].axes[0]
    assert list(ax.lines[0].get_ydata()) == [0.80, 0.79, 0.788]
    assert 'RL' not in ax.get_title() and 'Episode' not in ax.get_xlabel()
    # untrained ranker (PAIRS_USE_TRANSFORMER=0 / too few samples): clean no-op, stale chart removed
    assert plotting.plot_ranker_training({'n_samples': 12}) is None
    assert not os.path.exists(path)
    assert plotting.plot_ranker_training(None) is None


def test_plot_training_results_is_a_deprecated_shim(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.warns(DeprecationWarning):
        assert plotting.plot_training_results({'episode_rewards': [1, 2], 'actor_losses': []}) is None
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', DeprecationWarning)
        assert plotting.plot_training_results({'epoch_losses': [0.7, 0.69], 'base_rate': 0.5})


def test_fund_colours_follow_the_profile_key():
    a = plotting._profile_styles(['quant_hf', 'multi_strat', 'fundamental_ls', 'institutional', 'retail'])
    b = plotting._profile_styles(['retail', 'institutional'])
    assert b['retail'] == a['retail'] and b['institutional'] == a['institutional']
    c = plotting._profile_styles(['retail', 'new_profile'])
    assert c['new_profile'][1] not in {s[1] for s in a.values()}


def test_plot_fund_comparison(tmp_path, monkeypatch, captured_figures):
    monkeypatch.chdir(tmp_path)
    dates = [str(d.date()) for d in pd.bdate_range('2023-07-03', periods=30)]
    fc = {}
    for i, key in enumerate(['retail', 'quant_hf']):
        vals = 1e8 * np.cumprod(1 - 0.0005 * (i + 1) * np.ones(30))
        fc[key] = {'profile_name': key, 'total_return_pct': (vals[-1] / 1e8 - 1) * 100, 'final_equity': vals[-1],
                   'sharpe_ratio': -0.5 - i, 'max_drawdown_pct': -1.0, 'win_rate_pct': 40.0,
                   'profit_factor': float('inf'), 'total_trades': 3, 'total_cost_pct_of_capital': 0.2,
                   'annualized_return_pct': -1.0, 'gross_leverage_label': '1x (no leverage)',
                   'max_gross_leverage': 0.1 * (i + 1), 'stopped_on': dates[10] if i else None,
                   'cost_components': {'commission_pct': 0.1},
                   'equity_curve': [{'date': d, 'value': v} for d, v in zip(dates, vals)]}
    path = plotting.plot_fund_comparison(fc)
    assert path.endswith(os.path.join('outputs', 'fund_comparison.png')) and os.path.exists(path)
    ax1 = captured_figures[-1].axes[0]
    curve = ax1.lines[0]
    assert curve.get_color() == plotting.PROFILE_STYLE['retail'][1]
    assert pd.Timestamp(curve.get_xdata()[0]) == pd.Timestamp('2023-07-03')    # real dates, not ordinal
    assert curve.get_ydata()[-1] == pytest.approx(fc['retail']['total_return_pct'])
    legends = [ax.get_legend() for ax in captured_figures[-1].axes if ax.get_legend() is not None]
    labels = [t.get_text() for lg in legends for t in lg.get_texts()]
    assert any('kill-switch' in s for s in labels)            # the quant_hf stop is marked
    assert not any('good' in s or 'excellent' in s for s in labels)
    assert plotting.plot_fund_comparison({}) is None and not os.path.exists(path)


# ── CLI summary and seeding ────────────────────────────────────────────────────

def test_format_summary_reports_the_right_headlines():
    res = _results(profit_factor=float('inf'))
    res['halted_on'], res['halt_reason'] = '2023-07-07', 'daily loss limit'
    text = cli.format_summary(res, ['outputs/headline_metrics.json'])
    assert 'POOLED OOS SHARPE      -1.23' in text
    assert 'Mean of per-window Sharpes -0.23' in text and 'not a portfolio Sharpe' in text
    assert 'inf (no losing trade)' in text
    assert 'Exit reasons           stop 1, target 2' in text
    assert '2023-07-07 — daily loss limit' in text
    assert '1 of 3 made no trade' in text and '9 skipped' in text
    assert 'p=0.084 (two-sided)' in text and 'H1 mean>0' in text and 'H1 mean<0' in text
    assert 'PSR 2.2%' in text and 'DSR 0.9%' in text
    assert 'Gatev (2006) distance   return +2.78%   Sharpe +0.26' in text
    assert 'Sharpe diff vs Gatev    not reported' in text
    assert 'no per-draw distribution reported' in text
    assert '36,524 pairs tested' in text and 'Retail / Small Prop Trader' in text
    assert 'outputs/headline_metrics.json' in text
    for stale in ('W1-W9', 'W10-W19', 'Walking on Ice', 'Root cause', 'in_sample', 'IS→OOS'):
        assert stale not in text


def test_format_summary_survives_an_empty_or_partial_run():
    text = cli.format_summary({})
    assert 'MAIN BACKTEST' in text and 'not available' in text and '(none found)' in text
    text = cli.format_summary({'total_trades': 0, 'profit_factor': 0.0, 'walk_forward': {'windows': []}})
    assert 'Profit factor' not in text                        # undefined without trades


def test_resolve_seed(monkeypatch):
    monkeypatch.delenv('PAIRS_SEED', raising=False)
    assert cli.resolve_seed() == 42
    monkeypatch.setenv('PAIRS_SEED', '7')
    assert cli.resolve_seed() == 7
    monkeypatch.setenv('PAIRS_SEED', 'seven')
    with pytest.raises(ValueError, match='PAIRS_SEED'):
        cli.resolve_seed()


@pytest.fixture
def restore_torch_determinism(monkeypatch):
    monkeypatch.setenv('PAIRS_SEED', os.environ.get('PAIRS_SEED', '42'))
    flag = torch.are_deterministic_algorithms_enabled()
    warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
    yield
    torch.use_deterministic_algorithms(flag, warn_only=warn_only)


def test_seed_everything_is_reproducible(restore_torch_determinism):
    import random

    def draw():
        return random.random(), float(np.random.rand()), float(torch.rand(1))
    cli.seed_everything(123)
    a = draw()
    cli.seed_everything(123)
    assert draw() == a
    assert os.environ['PAIRS_SEED'] == '123'                  # the seed used is what run_config records
    assert torch.are_deterministic_algorithms_enabled()


def test_main_prints_summary_and_reraises_failures(monkeypatch, capsys, restore_torch_determinism):
    class Ok:
        def __init__(self, initial_capital):
            assert initial_capital == 100_000_000

        def run_complete_system(self):
            return _results()

    class Broken(Ok):
        def run_complete_system(self):
            raise RuntimeError('data cache missing')

    monkeypatch.setattr(cli, 'CompleteFixedRussell3000TradingSystem', Ok)
    cli.main()
    assert 'POOLED OOS SHARPE' in capsys.readouterr().out
    monkeypatch.setattr(cli, 'CompleteFixedRussell3000TradingSystem', Broken)
    with pytest.raises(RuntimeError, match='data cache missing'):
        cli.main()


# ── end to end on real engine output ───────────────────────────────────────────

@pytest.fixture(scope='module')
def engine_run():
    from tests.synthetic_market import build_system, make_market
    from pairs_trading.benchmark import run_benchmarks
    from pairs_trading.significance import significance_report
    frames, macro, _ = make_market(n_pairs=3, n_noise=2, seed=7)
    system = build_system(frames, macro)
    res = system.run_comprehensive_backtest(system.spread_data, date_range=('2023-07-01', '2025-12-31'))
    res['fund_comparison'] = system.run_fund_type_comparison(res, main_daily_dates=res['daily_dates'])
    # the real significance and benchmark reports (their structure is the contract under test)
    quarters = [float(np.prod(1 + np.asarray(res['daily_returns'][i:i + 63])) - 1)
                for i in range(0, len(res['daily_returns']) - 62, 63)]
    res['significance'] = significance_report(res['daily_returns'], oos_window_returns=quarters,
                                              oos_daily_returns=res['daily_returns'], n_trials=32)
    res['benchmarks'] = run_benchmarks(system.processed_data, sorted(frames), trade_start='2023-07-01',
                                       trade_end='2025-12-31', n_pairs=2, n_random_draws=20, n_boot=500,
                                       strategy_series={'main_backtest': (res['daily_dates'],
                                                                          res['daily_returns'])})
    res['run_config'] = {'run_timestamp_utc': '2026-01-01T00:00:00+00:00', 'git_commit': None}
    return res


def test_engine_output_exports_cleanly_and_reproducibly(engine_run, tmp_path):
    assert engine_run['total_trades'] >= 10, 'fixture too quiet'
    a = je.export_testing_results_to_json(engine_run, {'pairs_selected': 3}, output_dir=str(tmp_path / 'a'))
    b = je.export_testing_results_to_json(engine_run, {'pairs_selected': 3}, output_dir=str(tmp_path / 'b'))
    assert open(a, 'rb').read() == open(b, 'rb').read()      # byte-reproducible
    data = _strict_load(a)
    assert 'unit_path' not in open(a, encoding='utf-8').read()
    n = engine_run['total_trades']
    assert len(data['all_trades']) == n
    stats_ = data['trade_statistics']
    for key in ('by_abs_zscore', 'by_holding_period_trading_days', 'by_exit_reason'):
        assert sum(v['count'] for v in stats_[key].values()) == n, key
    assert stats_['by_abs_zscore']['<1.8']['count'] == 0
    curve = data['daily_equity_curve']
    assert curve[0]['date'] == engine_run['daily_dates'][0] and all(p['drawdown_pct'] <= 0 for p in curve)
    assert min(p['drawdown_pct'] for p in curve) == pytest.approx(engine_run['max_drawdown'] * 100, abs=1e-4)
    assert curve[-1]['portfolio_value'] == pytest.approx(engine_run['final_portfolio_value'], abs=0.01)
    for t in data['all_trades']:
        assert t['signal_date'] < t['entry_date'] <= t['exit_date']
        assert t['exit_reason'] in ('target', 'stop', 'time', 'end_of_data', 'risk_halt')
    h = _strict_load(je.export_headline_metrics(engine_run, {}, path=str(tmp_path / 'h.json')))
    assert h['main']['trades'] == n and set(h['fund_profiles']) == set(engine_run['fund_comparison'])
    f = je.export_fund_comparison_to_json(engine_run['fund_comparison'], run_config=engine_run['run_config'],
                                          output_dir=str(tmp_path))
    assert set(_strict_load(f)['profiles']) == set(engine_run['fund_comparison'])


def test_real_reports_flow_through_headline_summary_and_checker(engine_run, tmp_path):
    """Contract test: the significance/benchmark modules' real output fills every headline
    field the docs are checked against, and the checker accepts values taken from it."""
    h = je.build_headline_metrics(engine_run, {})
    sig, bm = h['significance'], h['benchmarks']
    for block in ('main', 'oos_daily'):
        assert all(sig[block][k] is not None for k in ('ann_sharpe', 'hac_t', 'hac_p', 'psr', 'boot_lo',
                                                       'boot_hi', 'dsr')), block
    assert all(v is not None for v in sig['oos_windows'].values())
    assert sig['oos_windows']['p_one_sided_negative'] == round(
        engine_run['significance']['oos_windows']['pvalue_mean_lt0'], 3)
    assert all(v is not None for v in bm['gatev'].values())
    assert all(v is not None for v in bm['random_control'].values())
    assert bm['random_control']['n_draws'] == 20
    assert bm['sharpe_diff_vs_gatev']['p'] is not None and bm['sharpe_diff_vs_gatev']['diff'] is not None

    text = cli.format_summary(engine_run)
    assert 'Sharpe diff vs Gatev    ' in text and 'common days' in text and 'not reported' not in text
    assert 'strategy Sharpe at percentile' in text and 'over 20 draws' in text

    # the checker accepts numbers written from this JSON the way the docs write them
    # (this fixture has no walk-forward, so the oos.* keys are null and not marked here)
    chk = _load_checker()
    js = tmp_path / 'h.json'
    js.write_text(json.dumps(h), encoding='utf-8')

    def mark(key, fmt):
        shown = fmt.format(chk.resolve_key(h, key)).replace('-', '\u2212')
        return f'<!--m:{key}-->{shown}<!--/m-->'
    doc = tmp_path / 'README.md'
    doc.write_text(' '.join(mark(k, f) for k, f in [
        ('main.total_return_pct', '{:+.2f}%'), ('main.sharpe', '{:+.2f}'), ('main.trades', '{:d}'),
        ('main.win_rate_pct', '{:.1f}%'), ('benchmarks.gatev.sharpe', '{:+.2f}'),
        ('benchmarks.gatev.total_return_pct', '{:+.2f}%'), ('significance.oos_windows.p', '{:.3f}'),
        ('significance.oos_daily.psr_pct', '{:.1f}%'), ('benchmarks.sharpe_diff_vs_gatev.p', '{:.2f}'),
        ('benchmarks.random_control.median_sharpe', '{:+.2f}'),
        ('benchmarks.random_control.strategy_percentile', '{:.0f}')]), encoding='utf-8')
    assert chk.main(['--json', str(js), '--files', str(doc), '--allow-missing-markers']) == 0


def _load_checker():
    import importlib.util
    spec = importlib.util.spec_from_file_location('_chk', os.path.join(REPO, 'scripts', 'check_published_numbers.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_pairs_switch_the_code_reads_is_recorded():
    """A PAIRS_* variable read anywhere in the package must be in the provenance block, or
    a run that set it could not be told apart from one that did not (v32 review found
    PAIRS_RESELECT missing)."""
    import pathlib
    import re
    pkg = pathlib.Path(je.__file__).resolve().parent
    read = set()
    for path in pkg.glob('*.py'):
        read |= set(re.findall(r"environ(?:\.get)?\(\s*['\"](PAIRS_[A-Z_]+)['\"]", path.read_text()))
        read |= set(re.findall(r"environ\[['\"](PAIRS_[A-Z_]+)['\"]\]", path.read_text()))
    assert read, "pattern found no PAIRS_* reads"
    assert read <= set(je.PROVENANCE_ENV_VARS), read - set(je.PROVENANCE_ENV_VARS)
