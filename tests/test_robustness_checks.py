"""scripts/robustness_checks.py on synthetic data: each section's computation against a
known answer or an independent implementation, and the read-only guard on the caches."""
import dataclasses
import importlib.util
import json
import pathlib

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm

from pairs_trading import anatomy as A
from pairs_trading.pair_selector import FixedPrimeFundPairSelector
from pairs_trading.significance import hac_tstat_mean
from tests.synthetic_market import SECTOR_ETFS, build_system, make_market

REPO = pathlib.Path(__file__).resolve().parents[1]


def _load_script():
    spec = importlib.util.spec_from_file_location('_script_robustness_checks',
                                                  REPO / 'scripts' / 'robustness_checks.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rc = _load_script()


# ── (a) start-date sensitivity ────────────────────────────────────────────────

@pytest.fixture(scope='module')
def market():
    return make_market(n_pairs=5, n_noise=2, seed=7)


@pytest.fixture(scope='module')
def start_runs(market):
    frames, macro, _ = market
    system = build_system(frames, macro)
    section, base = rc.start_date_sensitivity(system, system.spread_data, None, '2023-07-01', '2024-12-31',
                                              n_starts=3, step=21)
    return system, section, base


def test_starts_are_every_step_th_trading_day_and_offset_0_is_the_plain_run(start_runs):
    system, section, base = start_runs
    plain = system.run_comprehensive_backtest(system.spread_data, date_range=('2023-07-01', '2024-12-31'))
    assert base['daily_returns'] == plain['daily_returns'] and base['total_trades'] == plain['total_trades']
    window = [d for d in plain['daily_dates'] if d <= '2024-12-31']
    runs = section['runs']
    assert [r['start'] for r in runs] == [window[0], window[21], window[42]]
    assert [r['offset_trading_days'] for r in runs] == [0, 21, 42]
    assert all(r['first_day'] == r['start'] for r in runs)              # each book starts on its start day
    assert runs[0]['sharpe'] == pytest.approx(plain['sharpe_ratio'])
    assert runs[0]['trades'] == plain['total_trades'] > 0
    assert section['design']['window'] == [window[0], window[-1]]
    assert section['design']['window_trading_days'] == len(window)


def test_each_later_start_is_its_own_run_to_the_same_end(start_runs, market):
    system, section, _ = start_runs
    run = system.run_comprehensive_backtest(system.spread_data, date_range=(section['runs'][2]['start'], '2024-12-31'))
    row = section['runs'][2]
    assert row['sharpe'] == pytest.approx(run['sharpe_ratio'])
    assert row['trades'] == run['total_trades']
    assert row['total_return_pct'] == pytest.approx(run['total_return'] * 100)
    assert row['last_day'] == run['daily_dates'][-1]


def test_common_window_is_the_days_every_run_holds(start_runs):
    system, section, _ = start_runs
    cw = section['common_window']
    assert cw['first'] == section['runs'][-1]['start'] and cw['last'] == section['design']['window'][1]
    for row in section['runs']:
        res = system.run_comprehensive_backtest(system.spread_data, date_range=(row['start'], '2024-12-31'))
        r = pd.Series(res['daily_returns'], index=res['daily_dates'])
        sub = r[(r.index >= cw['first']) & (r.index <= cw['last'])].to_numpy()
        assert row['common_window']['days'] == cw['days'] == sub.size
        assert row['common_window']['sharpe'] == pytest.approx(rc.annualized_sharpe(sub))
        assert row['common_window']['total_return_pct'] == pytest.approx((np.prod(1 + sub) - 1) * 100)
    sharpes = [r['sharpe'] for r in section['runs']]
    assert section['spread']['sharpe']['range'] == pytest.approx(max(sharpes) - min(sharpes))
    assert section['spread']['sharpe']['sd'] == pytest.approx(np.std(sharpes, ddof=1))


def test_halves_split_the_window_and_are_separate_runs(start_runs):
    system, section, base = start_runs
    window = [d for d in base['daily_dates'] if d <= '2024-12-31']
    first, second = section['halves']
    assert first['entry_window'][0] == window[0] and second['entry_window'][1] == window[-1]
    assert window.index(second['entry_window'][0]) == window.index(first['entry_window'][1]) + 1
    assert first['entry_days'] + second['entry_days'] == len(window)
    res = system.run_comprehensive_backtest(system.spread_data, date_range=tuple(first['entry_window']))
    assert first['sharpe'] == pytest.approx(res['sharpe_ratio']) and first['trades'] == res['total_trades']
    # positions open at the first half's end run off on later days (no new entries)
    assert first['run_off_days'] == sum(d > first['entry_window'][1] for d in res['daily_dates'])
    same = pd.Series(base['daily_returns'], index=base['daily_dates'])
    same = same[(same.index >= first['entry_window'][0]) & (same.index <= first['entry_window'][1])]
    assert first['main_run_same_days']['days'] == len(same) == first['entry_days']


def test_too_few_days_for_the_starts_is_an_error(market):
    frames, macro, _ = market
    system = build_system(frames, macro)
    with pytest.raises(ValueError, match='need more than'):
        rc.start_date_sensitivity(system, system.spread_data, None, '2024-11-01', '2024-12-31', n_starts=12, step=21)


def test_reproduction_check_against_the_published_export(start_runs):
    _, _, base = start_runs
    published = {'daily_equity_curve': [{'date': d, 'portfolio_value': round(v, 2)}
                                        for d, v in zip(base['daily_dates'], base['equity_curve'])],
                 'all_trades': [{}] * base['total_trades']}
    ok = rc.reproduces_published(base, published)
    assert ok['verified'] and ok['same_days'] and ok['max_abs_equity_diff_usd'] <= 0.005 + 1e-9
    published['daily_equity_curve'][5]['portfolio_value'] += 1.0
    assert not rc.reproduces_published(base, published)['verified']
    published['daily_equity_curve'] = published['daily_equity_curve'][1:]
    assert not rc.reproduces_published(base, published)['same_days']


# ── (b) regimes ───────────────────────────────────────────────────────────────

def test_previous_value_is_the_last_observation_strictly_before_the_date():
    s = pd.Series([10.0, 11.0, 12.0], index=pd.to_datetime(['2024-01-02', '2024-01-03', '2024-01-05']))
    got = rc.previous_value(s, pd.to_datetime(['2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05', '2024-01-08']))
    assert np.isnan(got[0])
    assert got[1:].tolist() == [10.0, 11.0, 11.0, 12.0]
    tz = pd.Series(s.to_numpy(), index=s.index.tz_localize('America/New_York'))
    assert rc.previous_value(tz, pd.to_datetime(['2024-01-04']))[0] == 11.0


def test_sector_dispersion_is_the_cross_sectional_sample_sd_of_returns():
    idx = pd.bdate_range('2024-01-01', periods=4)
    sectors = {'XLA': pd.Series([100.0, 101.0, 99.0, 99.0], index=idx),
               'XLB': pd.Series([50.0, 50.0, 51.0, 52.0], index=idx),
               'XLC': pd.Series([20.0, 19.0, 19.0, 19.5], index=idx)}
    d = rc.sector_dispersion(sectors)
    assert list(d.index) == list(idx[1:])                       # day 1 has no return
    day2 = np.array([0.01, 0.0, -0.05])
    assert d.iloc[0] == pytest.approx(day2.std(ddof=1))
    sectors['XLC'] = sectors['XLC'].drop(idx[2])                 # a missing close: that day is dropped
    assert idx[2] not in rc.sector_dispersion(sectors).index


def test_terciles_split_at_the_sample_thirds():
    v = np.arange(1, 10, dtype=float)
    labels, (q1, q2) = rc.terciles(v)
    assert labels.tolist() == ['low'] * 3 + ['mid'] * 3 + ['high'] * 3
    assert (q1, q2) == pytest.approx(tuple(np.quantile(v, [1 / 3, 2 / 3])))


def test_hac_bucket_means_with_one_bucket_is_hac_tstat_mean():
    r = np.random.default_rng(3).normal(0.0002, 0.01, 400)
    out = rc.hac_bucket_means(r, np.array(['all'] * 400), ['all'])
    ref = hac_tstat_mean(r)
    assert out['buckets'][0]['nw_t'] == pytest.approx(ref['tstat'], rel=1e-12)
    assert out['nw_lags'] == ref['lags']
    assert out['buckets'][0]['mean_daily_bp'] == pytest.approx(r.mean() * 1e4)


def test_hac_bucket_means_are_the_dummy_regression_with_newey_west_errors():
    rng = np.random.default_rng(5)
    n = 500
    e = rng.normal(0, 0.01, n)
    r = e + 0.5 * np.concatenate([[0], e[:-1]])                  # MA(1): autocorrelated
    labels = rng.choice(['low', 'mid', 'high'], n)
    order = ['low', 'mid', 'high']
    out = rc.hac_bucket_means(r, labels, order, lags=6)
    X = np.column_stack([(labels == g).astype(float) for g in order])
    fit = sm.OLS(r, X).fit(cov_type='HAC', cov_kwds={'maxlags': 6, 'use_correction': False})
    for j, row in enumerate(out['buckets']):
        assert row['days'] == int((labels == order[j]).sum())
        assert row['mean_daily_bp'] == pytest.approx(fit.params[j] * 1e4)
        assert row['nw_t'] == pytest.approx(fit.tvalues[j], rel=1e-10)
        assert row['sharpe'] == pytest.approx(rc.annualized_sharpe(r[labels == order[j]]))
    contrast = fit.t_test(np.array([[-1.0, 0.0, 1.0]]))
    assert out['last_minus_first']['nw_t'] == pytest.approx(float(np.asarray(contrast.tvalue).ravel()[0]), rel=1e-10)
    assert out['last_minus_first']['mean_daily_bp'] == pytest.approx((fit.params[2] - fit.params[0]) * 1e4)


def _results_and_macro(n=300, seed=9):
    """A results export whose day-t net return is 1 bp per VIX point of day t-1 above 20,
    and a macro cache whose VIX and sector ETFs start two business days before it."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range('2023-07-03', periods=n)
    macro_days = pd.bdate_range(days[0] - pd.offsets.BDay(2), periods=n + 2)
    vix = pd.Series(20 + 5 * rng.normal(size=n + 2), index=macro_days)
    prev_vix = vix.to_numpy()[1:-1]                                # the value of the business day before each day
    r = (prev_vix - 20) * 1e-4 + rng.normal(0, 1e-5, n)
    equity = 1e8 * np.cumprod(1 + r)
    curve = [{'date': str(d.date()), 'portfolio_value': float(v), 'gross_return_pct': float(x * 100 + 0.01),
              'cost_pct': 0.01} for d, v, x in zip(days, equity, r)]
    sectors = {e: pd.Series(50 * np.exp(np.cumsum(rng.normal(0, 0.01, n + 2))), index=macro_days)
               for e in SECTOR_ETFS}
    return {'daily_equity_curve': curve}, {'VIX': vix, 'sectors': sectors}, prev_vix, r


def test_regime_breakdown_conditions_on_the_previous_days_vix():
    results, macro, prev_vix, r = _results_and_macro()
    out = rc.regime_breakdown(results, macro)
    assert out['days'] == len(r)
    v = out['vix']
    assert v['breakpoints'] == pytest.approx(list(np.quantile(prev_vix, [1 / 3, 2 / 3])))
    rows = {b['bucket']: b for b in v['net']['buckets']}
    assert sum(b['days'] for b in rows.values()) == len(r)
    assert rows['low']['mean_daily_bp'] < rows['mid']['mean_daily_bp'] < rows['high']['mean_daily_bp']
    labels, _ = rc.terciles(prev_vix)
    assert rows['high']['mean_daily_bp'] == pytest.approx(r[labels == 'high'].mean() * 1e4, rel=1e-6)
    assert v['net']['last_minus_first']['nw_t'] > 10
    assert {b['bucket'] for b in v['gross']['buckets']} == {'low', 'mid', 'high'}
    d = out['sector_dispersion']
    assert sum(b['days'] for b in d['net']['buckets']) == len(r)
    years = out['calendar_year']['net']['buckets']
    assert [y['bucket'] for y in years] == [2023, 2024] and sum(y['days'] for y in years) == len(r)


def test_regime_breakdown_refuses_a_day_without_an_earlier_observation():
    results, macro, _, _ = _results_and_macro()
    macro['VIX'] = macro['VIX'].iloc[3:]
    with pytest.raises(ValueError, match='no observation before'):
        rc.regime_breakdown(results, macro)


# ── (c) cointegration persistence on a given set of pairs ─────────────────────

def _three_year_market():
    """Y a random walk; X = Y + OU spread through 2021, a random-walk spread in 2022; V = Y +
    its own OU spread; W = V + noise from 2021; Z unrelated."""
    rng = np.random.default_rng(11)
    idx = pd.bdate_range('2020-01-01', '2022-12-31')
    n, split = len(idx), int((idx < '2022-01-01').sum())
    ly = np.cumsum(rng.normal(0, 0.015, n))
    s = np.zeros(n)
    for t in range(1, n):
        s[t] = (0.6 * s[t - 1] if t < split else s[t - 1]) + rng.normal(0, 0.01)
    v = np.zeros(n)
    for t in range(1, n):
        v[t] = 0.7 * v[t - 1] + rng.normal(0, 0.01)

    def frame(logp):
        close = pd.Series(np.exp(4 + logp), index=idx)
        return pd.DataFrame({'Close': close, 'Returns': close.pct_change(fill_method=None)})

    return {'X': frame(ly + s), 'Y': frame(ly), 'V': frame(ly + v), 'W': frame(ly + v + rng.normal(0, 0.004, n)),
            'Z': frame(np.cumsum(rng.normal(0, 0.015, n)))}


def test_persistence_on_every_pair_is_the_anatomys_table():
    prices = _three_year_market()
    symbols = sorted(prices)
    pairs = [(a, b) for i, a in enumerate(symbols) for b in symbols[i + 1:]]
    mine = rc.persistence_on_pairs(prices, pairs, years=(2020, 2021))
    assert mine == A.cointegration_persistence(prices, symbols, years=(2020, 2021))
    # pair orientation and duplicates do not matter
    flipped = [(b, a) for a, b in pairs] + pairs[:2]
    assert rc.persistence_on_pairs(prices, flipped, years=(2020, 2021)) == mine


def test_persistence_tests_only_the_given_pairs():
    prices = _three_year_market()
    out = rc.persistence_on_pairs(prices, [('X', 'Y'), ('Y', 'Z')], years=(2020, 2021))
    assert out['pairs'] == 2 and out['symbols'] == 3
    for row in out['years']:
        assert row['cointegrated']['of'] <= 2 and row['correlated_pairs'] <= 2
    by_year = {r['year']: r for r in out['years']}
    assert by_year[2020]['cointegrated']['count'] == 1                # X-Y; Z is screened out
    assert by_year[2021]['still_cointegrated_next_year']['of'] == 1
    assert by_year[2021]['still_cointegrated_next_year']['count'] == 0  # its 2022 spread is a walk
    assert rc.persistence_on_pairs(prices, [('X', 'Y'), ('Y', 'Z')], years=(2020, 2021), n_jobs=2) == out


def test_formation_candidates_are_the_selectors_universe_and_same_industry_pairs():
    frames, macro, _ = make_market(n_pairs=3, n_noise=4, seed=8)
    system = build_system(frames, macro)
    system.profile = dataclasses.replace(system.profile, max_universe=6, same_industry=True)
    names = sorted(frames)
    system.industries = {s: ('Banks' if i % 2 else 'Chips') for i, s in enumerate(names) if s != names[-1]}
    cutoff = '2022-12-31'
    symbols, pairs = rc.formation_candidates(system, cutoff, initial=True)
    sel = system._new_pair_selector()
    tz_cut = pd.Timestamp(cutoff, tz='America/New_York')
    sel.find_quality_pairs({s: df[df.index <= tz_cut] for s, df in system.processed_data.items()})
    assert symbols == sel.last_quality_symbols and len(symbols) == 6
    ind = system.industries
    assert pairs == [(a, b) for i, a in enumerate(symbols) for b in symbols[i + 1:]
                     if ind.get(a) and ind.get(a) == ind.get(b)]
    # a later formation reads only its trailing window
    later, _ = rc.formation_candidates(system, '2024-06-28', initial=False)
    assert len(later) == 6


# ── (d) S2's per-trade edge, clustered ────────────────────────────────────────

def test_clustered_mean_is_cr1_and_matches_statsmodels():
    rng = np.random.default_rng(2)
    groups = np.repeat(np.arange(30), 40)
    x = rng.normal(0, 1, 30)[groups] + rng.normal(0.1, 1, groups.size)   # a common shock per cluster
    out = rc.clustered_mean(x, groups)
    assert out['t_clustered'] == pytest.approx(A._clustered_t(x, groups), rel=1e-12)
    fit = sm.OLS(x, np.ones_like(x)).fit(cov_type='cluster', cov_kwds={'groups': groups})
    assert out['se_clustered'] == pytest.approx(float(fit.bse[0]), rel=1e-10)
    assert out['se_independent'] == pytest.approx(x.std(ddof=1) / np.sqrt(x.size))
    assert out['clusters'] == 30 and out['largest_cluster'] == 40
    assert out['design_effect'] > 5 and out['effective_n'] == pytest.approx(x.size / out['design_effect'])
    assert out['p_clustered'] > out['p_independent']


def test_clustered_mean_with_singleton_clusters_is_the_independent_se_up_to_n_over_n_minus_1():
    x = np.random.default_rng(4).normal(0, 1, 200)
    out = rc.clustered_mean(x, np.arange(200))
    # CR1 with one observation per cluster: sum (x - mean)^2 / n^2 * n / (n - 1) = s^2 / n
    assert out['se_clustered'] == pytest.approx(out['se_independent'], rel=1e-12)


def _residual_export(n=600, seed=6):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range('2023-07-03', periods=120)
    shock = {d: rng.normal(0, 30) for d in dates.to_period('M').unique()}
    trades = []
    for i in range(n):
        d = dates[rng.integers(0, len(dates))]
        g = 5 + shock[d.to_period('M')] + rng.normal(0, 40)
        trades.append({'symbol': f'S{i % 25:02d}', 'entry_date': str(d.date()), 'gross_bp': g, 'net_bp': g - 11})
    gross = np.array([t['gross_bp'] for t in trades])
    se = gross.std(ddof=1) / np.sqrt(n)
    return {'trades': trades, 'summary': {'gross_bp_per_trade': {'mean': gross.mean(), 'se': se,
                                                                 't': gross.mean() / se, 'n': n},
                                          'hac_t_gross': 0.5, 'hac_t_net': -0.5}}


def test_s2_trade_edge_clusters_by_entry_month_and_reproduces_the_export():
    export = _residual_export()
    out = rc.s2_trade_edge(export)
    m = out['gross_bp']['entry_month']
    months = {t['entry_date'][:7] for t in export['trades']}
    assert m['clusters'] == len(months) and m['n'] == len(export['trades'])
    assert out['export_check']['reproduced']
    assert m['t_independent'] == pytest.approx(export['summary']['gross_bp_per_trade']['t'])
    assert abs(m['t_clustered']) < abs(m['t_independent'])            # the monthly shock inflates the SE
    assert out['net_bp']['entry_month']['mean'] == pytest.approx(m['mean'] - 11)
    assert set(out['gross_bp']) == {'entry_month', 'entry_date', 'symbol'}
    export['summary']['gross_bp_per_trade']['mean'] += 0.1
    assert not rc.s2_trade_edge(export)['export_check']['reproduced']


# ── inputs, output ────────────────────────────────────────────────────────────

def test_never_attempted_is_what_the_top_up_would_fetch():
    manifest = {'outcomes': {'A': 'ok', 'B': 'not_found', 'C': 'error:HTTPError'}, 'cached_symbols': ['A', 'D']}
    assert rc.never_attempted(['A', 'B', 'C', 'D', 'E', 'F'], manifest) == ['E', 'F']
    assert rc.never_attempted(['A', 'B'], manifest) == []


def test_the_guard_disables_every_fetch_and_cache_write(tmp_path):
    from pairs_trading.data_processor import EnhancedRussell3000DataProcessor
    proc = EnhancedRussell3000DataProcessor(data_file=str(tmp_path / 'p.pkl'), macro_file=str(tmp_path / 'm.pkl'))
    rc.disable_fetch_and_cache_writes(proc)
    for call in (lambda: proc._download_history('A'), lambda: proc.fetch_stock_data('A'),
                 lambda: proc._fetch_many(['A'], 1), lambda: proc._atomic_pickle({}, str(tmp_path / 'x.pkl'))):
        with pytest.raises(RuntimeError, match='only reads the caches'):
            call()
    with pytest.raises(FileNotFoundError, match='never fetches'):        # the macro loader reads its cache only
        proc.load_macro_data()
    with pytest.raises(FileNotFoundError, match='never fetches'):
        proc.load_macro_data(fetch=True)
    assert not (tmp_path / 'x.pkl').exists() and not (tmp_path / 'm.pkl').exists()
    macro = {'VIX': pd.Series([20.0], index=pd.to_datetime(['2024-01-02'])), 'sectors': {}}
    pd.to_pickle(macro, tmp_path / 'm.pkl')
    assert proc.load_macro_data()['VIX'].iloc[0] == 20.0                   # an existing cache is read


def test_record_in_manifest_keeps_publish_runs_format(tmp_path):
    manifest = {'files': {'b.json': {'bytes': 1, 'sha256': 'f' * 64}, 'a.json': {'bytes': 2, 'sha256': 'e' * 64}},
                'name': 'v33_dev', 'run_config': {'git_commit': 'abc'}, 'study': None, 'price_cache': None}
    (tmp_path / 'MANIFEST.json').write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n')
    out = tmp_path / 'robustness.json'
    out.write_text('{"x": 1}\n')
    assert rc.record_in_manifest(out) == tmp_path / 'MANIFEST.json'
    got = json.loads((tmp_path / 'MANIFEST.json').read_text())
    assert got['files']['robustness.json'] == {'sha256': rc.fingerprint(out)['sha256'], 'bytes': out.stat().st_size}
    assert {k: v for k, v in got.items() if k != 'files'} == {k: v for k, v in manifest.items() if k != 'files'}
    assert (tmp_path / 'MANIFEST.json').read_text() == json.dumps(got, indent=1, sort_keys=True) + '\n'
    assert rc.record_in_manifest(tmp_path / 'none' / 'x.json') is None


def test_sections_b_and_d_are_deterministic():
    results, macro, _, _ = _results_and_macro()
    export = _residual_export()
    once = json.dumps({'b': rc.regime_breakdown(results, macro), 'd': rc.s2_trade_edge(export)}, sort_keys=False)
    again = json.dumps({'b': rc.regime_breakdown(results, macro), 'd': rc.s2_trade_edge(export)}, sort_keys=False)
    assert once == again


def test_main_refuses_without_pythonhashseed_0(monkeypatch):
    monkeypatch.setenv('PYTHONHASHSEED', 'random')
    with pytest.raises(SystemExit, match='PYTHONHASHSEED=0'):
        rc.main(['--sections', 'd', '--out', '/nonexistent/x.json'])


def test_the_selector_screen_is_the_one_formation_candidates_uses():
    # formation_candidates relies on screen_symbols being find_quality_pairs' screen
    frames, macro, _ = make_market(n_pairs=2, n_noise=3, seed=12)
    system = build_system(frames, macro)
    sel = FixedPrimeFundPairSelector()
    sel.max_universe = 3
    cut = pd.Timestamp('2022-12-31', tz='America/New_York')
    data = {s: df[df.index <= cut] for s, df in system.processed_data.items()}
    sel.find_quality_pairs(data)
    assert sel.last_quality_symbols == sorted(s for s, _ in rc.screen_symbols(data, sel.min_dollar_volume)[:3])
