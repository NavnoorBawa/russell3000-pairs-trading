"""scripts/stats_battery.py on small synthetic exports shaped like the study's JSON."""
import importlib.util
import json
import os

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location('_script_stats_battery',
                                               os.path.join(REPO, 'scripts', 'stats_battery.py'))
battery = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(battery)


def _exports(tmp_path, T=260):
    rng = np.random.default_rng(0)
    dates = [d.strftime('%Y-%m-%d') for d in pd.bdate_range('2024-01-02', periods=T)]
    strat = rng.normal(0.0, 0.004, T)
    results = {
        'daily_equity_curve': [{'date': d, 'daily_return_pct': float(100 * r)} for d, r in zip(dates, strat)],
        'benchmarks': {
            'distance_method': {'daily_returns': list(rng.normal(0.0, 0.003, T)),
                                'daily_dates': [d + 'T00:00:00' for d in dates]},
            'random_control': {'mean_daily_returns': list(rng.normal(0.0, 0.002, T - 5)),
                               'daily_dates': dates[5:]},
        },
    }
    funds = {'equity_curves': {
        name: {'curve': [{'date': d, 'value': float(v)} for d, v in
                         zip(dates, 1e8 * np.cumprod(1 + strat - cost))]}
        for name, cost in (('institutional', 1e-5), ('retail', 2e-4))}}
    res_path, funds_path = tmp_path / 'results.json', tmp_path / 'funds.json'
    res_path.write_text(json.dumps(results))
    funds_path.write_text(json.dumps(funds))
    return res_path, funds_path, dates


def test_battery_on_published_style_exports(tmp_path, capsys):
    res_path, funds_path, dates = _exports(tmp_path)
    out_path = tmp_path / 'stats.json'
    assert battery.main(['--results', str(res_path), '--funds', str(funds_path), '--reps', '200',
                         '--out', str(out_path)]) == 0
    text = out_path.read_text()
    assert 'NaN' not in text and 'Infinity' not in text      # strict JSON (inf MinTRL -> null)
    out = json.loads(text)
    assert out['power']['n'] == len(dates)
    assert {'hurdles', 'hurdles_ar1', 'dsr_curve', 'family'} <= set(out)
    fam = out['family']
    assert fam['members'] == ['strategy', 'gatev', 'random_mean', 'fund_institutional', 'fund_retail']
    assert fam['n_days'] == len(dates) - 5                   # common dates; first fund return is NaN
    assert fam['spa_vs_gatev']['k'] == 4 and fam['spa_vs_zero']['k'] == 5
    assert fam['spa_vs_gatev_unit_vol']['k'] == 4
    assert len(fam['romano_wolf_vs_zero']['table']) == 5
    assert set(fam['mcs']['pvalues']) == set(fam['members'])
    assert 'SPA vs gatev' in capsys.readouterr().out


def test_battery_on_a_declared_family_csv(tmp_path):
    res_path, _, dates = _exports(tmp_path)
    rng = np.random.default_rng(1)
    fam = pd.DataFrame(rng.normal(0.0, 0.01, (len(dates), 4)), index=dates, columns=list('abcd'))
    fam.to_csv(tmp_path / 'family.csv')
    out_path = tmp_path / 'stats.json'
    battery.main(['--results', str(res_path), '--funds', str(tmp_path / 'missing.json'),
                  '--family', str(tmp_path / 'family.csv'), '--benchmark', 'a', '--reps', '150',
                  '--out', str(out_path)])
    out = json.loads(out_path.read_text())
    assert out['family']['members'] == list('abcd')
    assert out['family']['spa_vs_a']['k'] == 3
    # a declared family without the Gatev column is tested against the exported series
    battery.main(['--results', str(res_path), '--family', str(tmp_path / 'family.csv'),
                  '--reps', '150', '--out', str(out_path)])
    fam = json.loads(out_path.read_text())['family']
    assert fam['spa_vs_gatev']['k'] == 4 and fam['spa_vs_gatev']['n'] == len(dates)


def test_unit_volatility_spa_compares_sharpe_ratios():
    """The benchmark run at 1.7x its size: the raw-return SPA sees a larger mean, the
    unit-volatility SPA the same Sharpe ratio. After rescaling, the differential is pure
    rounding noise (|d| <= 4e-16) and must not count as evidence: judged against its own
    scale it had t = 2.0 and p = 0.045 here."""
    rng = np.random.default_rng(2)
    dates = [d.strftime('%Y-%m-%d') for d in pd.bdate_range('2024-01-02', periods=750)]
    base = pd.Series(rng.normal(1.5e-3, 0.01, 750), index=dates)
    fam = pd.DataFrame({'gatev': base, 'levered': 1.7 * base})
    out = battery.run_battery(base, fam, reps=1000)['family']
    assert out['spa_vs_gatev']['pvalues']['consistent'] < 0.01
    assert out['spa_vs_gatev_unit_vol']['best_tstat'] == 0.0
    assert out['spa_vs_gatev_unit_vol']['pvalues']['consistent'] == 1.0


def test_battery_on_a_flat_strategy(tmp_path):
    """No trades, no dispersion: the power report is NaN and the AR(1) hurdles are
    skipped instead of failing the run."""
    dates = [d.strftime('%Y-%m-%d') for d in pd.bdate_range('2026-01-02', periods=60)]
    flat = pd.Series(0.0, index=dates)
    fam = pd.DataFrame({'strategy': flat, 'other': np.random.default_rng(3).normal(0.0, 0.01, 60)},
                       index=dates)
    out = battery.run_battery(flat, fam, reps=100)
    assert out['hurdles_ar1'] is None and np.isnan(out['power']['upper_bound_ann'])
    assert 'hurdles (AR(1))' not in battery._summary(out)
