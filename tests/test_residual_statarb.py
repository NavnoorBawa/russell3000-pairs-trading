"""Avellaneda-Lee (2010) sector-ETF residual strategy (pairs_trading/residual_statarb.py).

Formulas (A&L Appendix eq. 21, centred s-score eq. 22) against hand-computed values and an
independent statsmodels fit; causality (decisions dated <= t are unchanged when every
price and volume after t changes, with and without the point-in-time gate); t+1 fills;
the universe gate, the run-off after `end` and missing bars; known answers on synthetic
markets (a planted OU residual must give a large positive gross edge, a random-walk
residual none); ETF hedge netting, exposures and cost accounting on hand-built books;
S1's cost model and point-in-time membership rule (a non-member never enters; the
membership changes only where a snapshot takes effect); the run script on a study
calendar laid out from synthetic caches (the calendar's bounds, the export the evaluator
reads, nothing fetched, refusals of incomplete or foreign caches and of other code).
"""
import hashlib
import importlib.util
import json
import os
import pickle
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm

from pairs_trading.json_export import _atomic_write_json
from pairs_trading.residual_statarb import (
    ETF_ASSUMED_ADV_DOLLARS, LiquidityUniverse, ResidualMarket, ResidualSignals, ResidualStatArbParams,
    centred_s_scores, ff49_sector_etf_map, nasdaq_sector_etf_map, ou_from_ar1, ou_residual_fit, rolling_ou_fits,
    run_residual_statarb, s1_cost_model, simulate_residual_book, summarise_residual_book,
)
from pairs_trading.study_config import CALENDARS, PROFILES
from pairs_trading.synthetic import make_residual_market, perturb_after, write_reference
from pairs_trading.transaction_costs import EnhancedPrimeFundTransactionCostModel
from pairs_trading.universe import PITUniverse, sector_etf_map

START, END = '2021-07-01', '2023-12-31'
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, 'scripts', 'run_residual_statarb.py')


def _script():
    spec = importlib.util.spec_from_file_location('_script_run_residual_statarb', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope='module')
def ou_run():
    frames, etfs, smap, _ = make_residual_market(seed=0, residual='ou')
    return frames, etfs, smap, run_residual_statarb(frames, etfs, smap, START, END)


# ── formulas ─────────────────────────────────────────────────────────────────────

def test_ou_parameters_from_a_hand_computed_ar1():
    # X_{n+1} = 0.01 + 0.5 X_n + zeta, Var(zeta) = 0.0003:
    # kappa = -ln(0.5) * 252 = 252 ln 2, m = 0.01 / 0.5 = 0.02, sigma_eq = sqrt(0.0003 / 0.75) = 0.02
    p = ou_from_ar1(0.01, 0.5, 0.0003)
    assert p['kappa'] == pytest.approx(252 * np.log(2), rel=1e-12)
    assert p['m'] == pytest.approx(0.02, rel=1e-12)
    assert p['sigma_eq'] == pytest.approx(0.02, rel=1e-12)
    for b in (0.0, 1.0, -0.3, 1.2):                     # the OU mapping needs 0 < b < 1
        q = ou_from_ar1(0.01, b, 0.0003)
        assert np.isnan(q['kappa']) and np.isnan(q['m']) and np.isnan(q['sigma_eq'])


def test_kappa_threshold_is_b_below_exp_minus_one_thirtieth():
    # A&L: kappa > 252/30  <=>  b < exp(-1/30) = 0.9672
    b_star = np.exp(-1 / 30)
    assert ou_from_ar1(0.0, b_star * (1 - 1e-9), 1e-4)['kappa'] > 252 / 30
    assert ou_from_ar1(0.0, b_star * (1 + 1e-9), 1e-4)['kappa'] < 252 / 30


def test_residual_fit_matches_an_independent_ols():
    rng = np.random.default_rng(7)
    e = rng.normal(0, 0.01, 60)
    r = 0.0004 + 1.3 * e + rng.normal(0, 0.012, 60)
    fit = ou_residual_fit(r, e)

    reg = sm.OLS(r, sm.add_constant(e)).fit()
    x = np.cumsum(reg.resid)
    assert x[-1] == pytest.approx(0.0, abs=1e-12)        # X_60 = 0: an artefact of the regression
    ar = sm.OLS(x[1:], sm.add_constant(x[:-1])).fit()
    a, b = ar.params
    var_zeta = ar.resid.var(ddof=1)
    assert fit['estimable']
    assert fit['beta0'] == pytest.approx(reg.params[0], rel=1e-9)
    assert fit['beta'] == pytest.approx(reg.params[1], rel=1e-9)
    assert fit['a'] == pytest.approx(a, rel=1e-9) and fit['b'] == pytest.approx(b, rel=1e-9)
    assert fit['var_zeta'] == pytest.approx(var_zeta, rel=1e-9)
    assert 0 < b < 1
    assert fit['kappa'] == pytest.approx(-np.log(b) * 252, rel=1e-9)
    assert fit['m'] == pytest.approx(a / (1 - b), rel=1e-9)
    assert fit['sigma_eq'] == pytest.approx(np.sqrt(var_zeta / (1 - b * b)), rel=1e-9)


def test_residual_fit_recovers_a_planted_ou():
    rng = np.random.default_rng(3)
    n, phi = 5000, 0.9
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + rng.normal(0, 0.01)
    e = rng.normal(0, 0.01, n)
    fit = ou_residual_fit(0.8 * e + np.diff(x, prepend=0.0), e)
    assert fit['beta'] == pytest.approx(0.8, abs=0.02)
    assert fit['kappa'] == pytest.approx(-np.log(phi) * 252, rel=0.1)
    assert fit['sigma_eq'] == pytest.approx(0.01 / np.sqrt(1 - phi ** 2), rel=0.1)


def test_missing_return_or_flat_etf_is_not_estimable():
    rng = np.random.default_rng(1)
    e, r = rng.normal(0, 0.01, 60), rng.normal(0, 0.01, 60)
    r_gap = r.copy()
    r_gap[30] = np.nan
    assert not ou_residual_fit(r_gap, e)['estimable']
    assert not ou_residual_fit(r, np.full(60, 0.001))['estimable']
    assert np.isnan(ou_residual_fit(r_gap, e)['kappa'])


def test_rolling_fit_uses_the_trailing_window_ending_at_each_row():
    rng = np.random.default_rng(2)
    R, E = rng.normal(0, 0.01, (120, 3)), rng.normal(0, 0.01, (120, 3))
    fits = rolling_ou_fits(R, E, window=60, rows=range(70, 120), chunk=7)
    for t in (70, 95, 119):
        for i in range(3):
            one = ou_residual_fit(R[t - 59:t + 1, i], E[t - 59:t + 1, i])
            assert fits['m'][t, i] == pytest.approx(one['m'], rel=1e-12)
            assert fits['beta'][t, i] == pytest.approx(one['beta'], rel=1e-12)
    assert np.isnan(fits['m'][69]).all() and not fits['estimable'][69].any()


def test_s_score_is_centred_over_accepted_universe_members():
    # A&L eq. 22: s = -(m - <m>) / sigma_eq, <m> over the universe's accepted models
    m = np.array([[0.02, -0.01, 0.05, 0.30]])
    sigma = np.array([[0.01, 0.02, 0.05, 0.10]])
    accepted = np.array([[True, True, True, False]])
    universe = np.array([[True, True, False, True]])
    s = centred_s_scores(m, sigma, accepted, universe)[0]
    # <m> = (0.02 - 0.01) / 2 = 0.005 (stock 2 is not a member, stock 3 is rejected)
    np.testing.assert_allclose(s[:3], [-1.5, 0.75, -0.9])
    assert np.isnan(s[3])


def test_only_models_with_kappa_above_252_over_30_are_accepted(ou_run):
    # A&L Sec. 4 / Appendix: trade only if kappa > 252/30 (b < 0.9672); s is defined only there
    sig = ou_run[3]['signals']
    with np.errstate(invalid='ignore'):
        slow = sig.estimable & (sig.kappa <= 252 / 30)
        fast = sig.estimable & (sig.kappa > 252 / 30)
    assert slow.sum() > 10 and fast.sum() > 1000
    assert not sig.accepted[slow].any() and sig.accepted[fast].all()
    assert np.array_equal(sig.accepted, fast)
    assert np.isnan(sig.s[~sig.accepted]).all()
    assert all(t['kappa'] > 252 / 30 for t in ou_run[3]['trades'])


# ── universe and sector map ──────────────────────────────────────────────────────

def _frames(close: dict, volume: dict, start='2024-01-02'):
    n = len(next(iter(close.values())))
    idx = pd.bdate_range(start, periods=n, tz='America/New_York')
    return {s: pd.DataFrame({'Close': np.asarray(close[s], float), 'Volume': np.asarray(volume[s], float)},
                            index=idx) for s in close}, idx.tz_localize(None)


def test_liquidity_universe_ranks_on_past_dollar_volume_with_a_price_floor():
    n = 150
    close = {'A': np.full(n, 4.0), 'B': np.full(n, 50.0), 'C': np.full(n, 20.0), 'D': np.full(n, 10.0)}
    vol = {'A': np.full(n, 1e7), 'B': np.full(n, 1e5), 'C': np.full(n, 2e5), 'D': np.full(n, 3e5)}
    vol['D'][100:] = 1e3                           # D dries up from row 100 on
    frames, dates = _frames(close, vol)
    etf = {'XLK': pd.Series(np.full(n, 100.0), index=dates)}
    market = ResidualMarket.from_prices(frames, etf, dict.fromkeys(close, 'XLK'))
    uni = LiquidityUniverse(market, size=2, rebalance_every=21, lookback=30, min_history=10, anchor=dates[70])
    # A ($40M/day) is the most liquid but trades below $5; then D $3M, C $4M, B $5M: B and C
    assert uni(dates[70]) == ['B', 'C']
    assert uni.ranking_day(dates[90]) == 70 and uni.ranking_day(dates[91]) == 91
    assert uni.ranking_day(dates[60]) == 49 and uni(dates[5]) == []
    # D's collapse at row 100 is invisible until a ranking day sees it (no look-ahead)
    vol_d_up = dict(vol, D=np.where(np.arange(n) >= 100, 1e7, 3e5))
    market2 = ResidualMarket.from_prices(_frames(close, vol_d_up)[0], etf, dict.fromkeys(close, 'XLK'))
    uni2 = LiquidityUniverse(market2, size=2, rebalance_every=21, lookback=30, min_history=10, anchor=dates[70])
    for d in dates[70:112]:
        assert uni2(d) == uni(d)
    assert uni2(dates[112]) == ['B', 'D']


def test_liquidity_universe_uses_the_ranking_day_close_and_nothing_after_it():
    # Ranking days 70, 91, 112. E, the most liquid, trades at $4 until it reaches $6 on
    # ranking day 91 itself; D's volume jumps on row 92, the day AFTER that ranking day.
    n = 150
    close = {'B': np.full(n, 50.0), 'C': np.full(n, 20.0), 'D': np.full(n, 10.0), 'E': np.full(n, 4.0)}
    vol = {'B': np.full(n, 1e5), 'C': np.full(n, 2e5), 'D': np.full(n, 3e5), 'E': np.full(n, 1e7)}
    close['E'][91:] = 6.0
    vol['D'][92:] = 1e7
    frames, dates = _frames(close, vol)
    etf = {'XLK': pd.Series(np.full(n, 100.0), index=dates)}
    market = ResidualMarket.from_prices(frames, etf, dict.fromkeys(close, 'XLK'))
    uni = LiquidityUniverse(market, size=2, rebalance_every=21, lookback=30, min_history=10, anchor=dates[70])
    assert uni(dates[70]) == ['B', 'C']            # E below $5; B $5M/day, C $4M/day, D $3M/day
    assert uni(dates[91]) == uni(dates[111]) == ['B', 'E']   # E qualifies on its day-91 close
    assert uni(dates[112]) == ['D', 'E']           # D's jump is seen by the next ranking day


def test_nasdaq_sector_map_normalises_symbols_and_skips_unmapped_sectors(tmp_path):
    path = tmp_path / 'marketcap.csv'
    path.write_text('Symbol,Name,MarketCap,Sector,Industry\n'
                    'AAPL,Apple,1,Technology,x\nbrk.b,Berkshire,1,Finance,x\nT,AT&T,1,Telecommunications,x\n'
                    'IDCC,InterDigital,1,Miscellaneous,x\nOTF,Blue Owl,1,,x\nO,Realty Income,1,Real Estate,x\n')
    assert nasdaq_sector_etf_map(str(path)) == {'AAPL': 'XLK', 'BRK-B': 'XLF', 'T': 'XLC', 'O': 'XLRE'}


_FF49_CSV = ('ticker,cik,sic,ff49,ff49_name,sector_etf,entity_type\n'
             'AAPL,320193,3571,35,Comps,XLK,operating\nBRK.B,1067983,6331,46,Insur,XLF,operating\n'
             'O,726728,6798,47,RlEst,XLRE,operating\nXYZ,,,,,,\nOTH,1,9995,48,Other,,operating\n')


def test_ff49_sector_map_reads_the_sector_etf_column_and_skips_blanks(tmp_path):
    path = tmp_path / 'industry_ff49.csv'
    path.write_text(_FF49_CSV)
    assert ff49_sector_etf_map(str(path)) == {'AAPL': 'XLK', 'BRK-B': 'XLF', 'O': 'XLRE'}
    # 'NA' is a ticker, not a missing value
    path.write_text(_FF49_CSV + 'NA,2,3711,23,Autos,XLY,operating\n')
    assert ff49_sector_etf_map(str(path))['NA'] == 'XLY'


def test_run_script_reads_the_committed_sector_map_and_records_it(tmp_path, monkeypatch):
    """The registered arm reads reference/industry_ff49.csv through universe.sector_etf_map,
    with its sha256; a missing file stops the run (no fallback), and any other map is a
    variant."""
    mod = _script()
    mapping, info = mod.load_sector_map()
    committed = os.path.join(REPO, 'reference', 'industry_ff49.csv')
    assert mapping == sector_etf_map() and info['registered'] is True
    assert info['file']['path'] == 'reference/industry_ff49.csv'
    with open(committed, 'rb') as fh:
        assert info['file']['sha256'] == hashlib.sha256(fh.read()).hexdigest()
    assert info['source'].startswith('ff49_sic') and info['n_symbols'] == len(mapping)
    assert mod.load_sector_map(committed)[1]['registered'] is True
    with pytest.raises(FileNotFoundError, match='industry_ff49.csv'):
        mod.load_sector_map(reference_dir=tmp_path)

    other = tmp_path / 'industry_ff49.csv'
    other.write_text(_FF49_CSV)
    mapping, info = mod.load_sector_map(str(other))
    assert mapping == {'AAPL': 'XLK', 'BRK-B': 'XLF', 'O': 'XLRE'} and info['registered'] is False
    assert info['etf_counts'] == {'XLF': 1, 'XLK': 1, 'XLRE': 1} and info['file']['path'] == 'industry_ff49.csv'
    assert mod.load_sector_map(reference_dir=tmp_path)[1]['registered'] is True    # that directory's own map
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data' / 'marketcap.csv').write_text('Symbol,Name,MarketCap,Sector,Industry\n'
                                                      'AAPL,Apple,1,Technology,x\nO,Realty,1,Finance,x\n')
    monkeypatch.chdir(tmp_path)
    mapping, info = mod.load_sector_map('nasdaq')
    assert mapping == {'AAPL': 'XLK', 'O': 'XLF'} and info['source'].startswith('nasdaq_sector')
    assert info['registered'] is False


def test_run_script_has_a_working_cli():
    r = subprocess.run([sys.executable, SCRIPT, '--help'], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and '--calendar' in r.stdout and '--universe-size' in r.stdout
    assert '--start' not in r.stdout and '--end' not in r.stdout       # the calendar fixes both


def test_run_config_records_the_close_fill_and_the_calendar(ou_run, tmp_path, monkeypatch):
    # PAIRS_FILL switches the pairs engine only; this strategy always fills at the next close
    mod = _script()
    monkeypatch.chdir(tmp_path)                            # no price cache here to fingerprint
    monkeypatch.setenv('PAIRS_FILL', 'open')
    params = ResidualStatArbParams()
    cfg = mod.residual_run_config(ou_run[3], {'study': mod.residual_study(CALENDARS['dev'], params)},
                                  {'source': 'test', 'registered': True})
    assert cfg['effective'] == {'fill': 'close', 'calendar': 'dev'}
    assert cfg['study']['calendar_hash'] == CALENDARS['dev'].config_hash()
    assert cfg['study']['params_hash'] == params.config_hash() and cfg['study']['profile'] is None
    assert cfg['sector_map'] == {'source': 'test', 'registered': True}
    assert cfg['data']['backtest_start'] == ou_run[3]['daily_dates'][0]
    assert mod.residual_switches(cfg, params, cfg['sector_map']) == []
    # what makes a run a variant of the registered arm
    monkeypatch.setenv('PAIRS_SKIP_REPROCESS', '1')
    cfg = mod.residual_run_config(ou_run[3], {'study': mod.residual_study(CALENDARS['dev'], params)},
                                  {'registered': False, 'file': {'path': 'x.csv'}})
    assert mod.residual_switches(cfg, ResidualStatArbParams(universe_size=300), cfg['sector_map'], ['ZZZ']) == [
        'universe_size=300', 'sector_map=x.csv', 'PAIRS_SKIP_REPROCESS=1', 'never_fetched_members=1']


# ── causality and execution timing ───────────────────────────────────────────────

def _decision(t):
    return (t['symbol'], t['side'], t['signal_date'], t['s_entry'], t['kappa'], t['beta'], t['m'],
            t['sigma_eq'], t['notional'], t['shares'], t['etf_shares'])


@pytest.mark.parametrize('cutoff, gated', [('2022-06-15', False), ('2023-03-01', False), ('2022-06-15', True)])
def test_decisions_up_to_t_ignore_all_data_after_t(cutoff, gated, tmp_path):
    frames, etfs, smap, _ = make_residual_market(seed=11, residual='ou')
    members = None
    if gated:                               # the point-in-time gate, with snapshots on both sides of t
        names = sorted(smap)
        snaps = {'2021-03-31': names[2:], '2022-03-31': names[1:], '2022-09-30': names[:-3]}
        members = PITUniverse(write_reference(tmp_path / 'reference', snaps)).members_asof
    base = run_residual_statarb(frames, etfs, smap, START, END, members=members)
    cut = pd.Timestamp(cutoff)
    rng = np.random.default_rng(5)
    etfs_p = {}
    for e, v in etfs.items():
        v = v.copy()
        after = v.index > cut
        v[after] = v[after].to_numpy() * np.exp(np.cumsum(rng.normal(0, 0.03, int(after.sum()))))
        etfs_p[e] = v
    pert = run_residual_statarb(perturb_after(frames, cutoff), etfs_p, smap, START, END, members=members)

    rows = base['market'].dates <= cut
    assert rows.sum() > 300 and (~rows).sum() > 100
    for name in ('s', 'beta', 'kappa', 'accepted', 'estimable', 'in_universe'):
        np.testing.assert_array_equal(getattr(base['signals'], name)[rows], getattr(pert['signals'], name)[rows])
    assert not np.array_equal(np.nan_to_num(base['signals'].s[~rows]), np.nan_to_num(pert['signals'].s[~rows]))

    def upto(res, key):
        return [t for t in res['trades'] if pd.Timestamp(t[key]) <= cut]

    assert [_decision(t) for t in upto(base, 'signal_date')] == [_decision(t) for t in upto(pert, 'signal_date')]
    assert len(upto(base, 'signal_date')) > 100
    exits = [(t['symbol'], t['exit_signal_date'], t['exit_reason'], t['s_exit']) for t in upto(base, 'exit_signal_date')]
    assert exits == [(t['symbol'], t['exit_signal_date'], t['exit_reason'], t['s_exit'])
                     for t in upto(pert, 'exit_signal_date')]
    n = sum(pd.Timestamp(d) <= cut for d in base['daily_dates'])
    assert base['daily_equity'][:n] == pert['daily_equity'][:n]
    assert base['daily_equity'][n:] != pert['daily_equity'][n:]


def test_orders_fill_at_the_next_close_with_shares_fixed_at_the_signal_close(ou_run):
    frames, etfs, smap, res = ou_run
    market, sig = res['market'], res['signals']
    pos = {d: k for k, d in enumerate(market.dates)}
    col = {s: i for i, s in enumerate(market.symbols)}
    p = ResidualStatArbParams()
    equity = dict(zip(res['daily_dates'], res['daily_equity']))
    assert len(res['trades']) > 300
    assert len({t['notional'] for t in res['trades']}) > 100
    for t in res['trades']:
        k_sig, k_in = pos[pd.Timestamp(t['signal_date'])], pos[pd.Timestamp(t['entry_date'])]
        assert t['notional'] == pytest.approx(p.position_frac * equity[t['signal_date']], rel=1e-12)
        k_xs, k_out = pos[pd.Timestamp(t['exit_signal_date'])], pos[pd.Timestamp(t['exit_date'])]
        i, j = col[t['symbol']], market.etfs.index(t['etf'])
        assert k_in == k_sig + 1
        assert t['entry_price'] == market.close[k_in, i]
        assert t['exit_price'] == market.close_ff[k_out, i]
        assert t['etf_entry_price'] == market.etf_close[k_in, j] and t['etf_exit_price'] == market.etf_close[k_out, j]
        direction = 1 if t['side'] == 'long' else -1
        assert t['shares'] * market.close[k_sig, i] == pytest.approx(direction * t['notional'], rel=1e-12)
        assert t['etf_shares'] * market.etf_close[k_sig, j] == pytest.approx(-direction * t['beta'] * t['notional'],
                                                                              rel=1e-12)
        assert t['s_entry'] == sig.s[k_sig, i] and sig.in_universe[k_sig, i] and sig.accepted[k_sig, i]
        assert (t['s_entry'] < -p.s_open) if direction > 0 else (t['s_entry'] > p.s_open)
        if t['exit_reason'] == 'end_of_data':
            assert k_out == k_xs == len(market.dates) - 1
            continue
        assert k_out == k_xs + 1
        if t['exit_reason'] == 'signal':
            assert t['s_exit'] == sig.s[k_xs, i]
            assert (t['s_exit'] > -p.s_close_long) if direction > 0 else (t['s_exit'] < p.s_close_short)
        else:
            assert t['exit_reason'] == 'model_rejected' and not sig.accepted[k_xs, i] and sig.estimable[k_xs, i]
        # no exit rule fired on any earlier day of the holding period
        for k in range(k_sig + 1, k_xs):
            if sig.estimable[k, i]:
                assert sig.accepted[k, i]
                assert not ((sig.s[k, i] > -p.s_close_long) if direction > 0 else (sig.s[k, i] < p.s_close_short))


def test_only_universe_members_open_positions_and_leavers_are_still_managed():
    frames, etfs, smap, _ = make_residual_market(seed=0, residual='ou')
    names = sorted(smap)

    def universe(date):                                   # half the names, alternating monthly
        return [s for n, s in enumerate(names) if (n + date.year * 12 + date.month) % 2 == 0]

    res = run_residual_statarb(frames, etfs, smap, START, END, universe=universe)
    market, sig = res['market'], res['signals']
    pos = {d: k for k, d in enumerate(market.dates)}
    col = {s: i for i, s in enumerate(market.symbols)}
    for d in ('2021-07-01', '2022-02-15', '2023-12-29'):
        k = pos[pd.Timestamp(d)]
        assert sorted(np.array(market.symbols)[sig.in_universe[k]]) == universe(pd.Timestamp(d))
    trades = res['trades']
    assert len(trades) > 200
    assert all(sig.in_universe[pos[pd.Timestamp(t['signal_date'])], col[t['symbol']]] for t in trades)
    # a position whose name has left the universe still exits under the same rule
    left = [t for t in trades if t['exit_reason'] == 'signal'
            and not sig.in_universe[pos[pd.Timestamp(t['exit_signal_date'])], col[t['symbol']]]]
    assert len(left) > 20


def test_no_entries_after_end_and_open_positions_run_off(ou_run):
    frames, etfs, smap, full = ou_run
    end = pd.Timestamp('2022-12-30')
    res = run_residual_statarb(frames, etfs, smap, START, end)
    trades = res['trades']
    assert max(pd.Timestamp(t['signal_date']) for t in trades) <= end
    late = [t for t in trades if pd.Timestamp(t['exit_date']) > end]
    assert late and all(t['exit_reason'] != 'end_of_data' for t in late)
    # the daily series runs until the last position closes, and matches the full run up to `end`
    assert res['daily_dates'][-1] == max(t['exit_date'] for t in trades)
    n = sum(pd.Timestamp(d) <= end for d in res['daily_dates'])
    assert res['daily_equity'][:n] == full['daily_equity'][:n]


# ── known answers ────────────────────────────────────────────────────────────────

def test_planted_ou_residuals_give_a_large_positive_gross_edge(ou_run):
    s = ou_run[3]['summary']
    g = s['gross_bp_per_trade']
    assert g['n'] > 500
    assert g['mean'] > 80 and g['t'] > 8
    assert s['gross_sharpe'] > 3 and s['hac_t_gross'] > 5


def test_random_walk_residuals_give_no_gross_edge():
    # Every price is a martingale, so the expected gross P&L of any non-anticipating rule
    # is zero; over 12 seeds of a 440-name version of this market the per-trade t averaged
    # 0.24 with a standard deviation of 1.1. Pooled over three seeds here.
    bp, hac = [], []
    for seed in (21, 22, 23):
        frames, etfs, smap, _ = make_residual_market(seed=seed, residual='random_walk')
        res = run_residual_statarb(frames, etfs, smap, START, END)
        bp += [t['gross_bp'] for t in res['trades']]
        hac.append(res['summary']['hac_t_gross'])
    bp = np.asarray(bp)
    t = bp.mean() / (bp.std(ddof=1) / np.sqrt(bp.size))
    assert bp.size > 1500
    assert abs(t) < 2.5
    assert all(abs(h) < 2.5 for h in hac)


# ── hedge netting and accounting on a hand-built book ───────────────────────────

def _hand_book():
    """4 stocks (A, B in XLK; C, D in XLF) over 8 days, signals injected by hand.

    Day 1: open A long (beta 1), B short (beta 1), C short (beta 0.5), D long (beta 2).
    A's and B's XLK hedges cancel exactly; C and D leave XLF net short 18,750 shares.
    Day 4: A's s-score is 0 -> close A at day 5. Day 7 (last bar): B, C, D close.
    """
    close = {'A': [100, 100, 100, 101, 102, 103, 103, 104], 'B': [50, 50, 50, 49, 50, 51, 52, 52],
             'C': [20, 20, 20, 20.5, 21, 21, 20, 19], 'D': [30] * 8}
    frames, dates = _frames(close, {s: [1e6] * 8 for s in close}, start='2024-01-03')
    etfs = {'XLK': pd.Series([200, 200, 200, 202, 201, 203, 204, 205], index=dates, dtype=float),
            'XLF': pd.Series([40, 40, 40, 40.4, 40.2, 40, 39, 39.5], index=dates, dtype=float)}
    market = ResidualMarket.from_prices(frames, etfs, {'A': 'XLK', 'B': 'XLK', 'C': 'XLF', 'D': 'XLF'})
    T, N = 8, 4
    s = np.full((T, N), np.nan)
    s[1] = [-2.0, 2.0, 2.0, -3.0]
    s[4, 0] = 0.0
    beta = np.tile([1.0, 1.0, 0.5, 2.0], (T, 1))
    ones = np.ones((T, N), dtype=bool)
    signals = ResidualSignals(s=s, beta=beta, kappa=np.full((T, N), 50.0), m=np.zeros((T, N)),
                              sigma_eq=np.full((T, N), 0.02), estimable=ones, accepted=ones, in_universe=ones)
    return market, signals


def test_etf_hedges_are_netted_and_every_dollar_reconciles():
    market, signals = _hand_book()
    cm = EnhancedPrimeFundTransactionCostModel()
    params = ResidualStatArbParams()
    raw = simulate_residual_book(market, signals, params, cost_model=cm)
    out = summarise_residual_book(raw, market.dates)
    trades = {t['symbol']: t for t in out['trades']}
    N0 = 0.005 * 1e8

    assert [(t['entry_date'], t['exit_date'], t['exit_reason']) for t in (trades['A'], trades['B'])] == [
        ('2024-01-05', '2024-01-10', 'signal'), ('2024-01-05', '2024-01-12', 'end_of_data')]
    assert trades['A']['shares'] == 5000 and trades['A']['etf_shares'] == -2500
    assert trades['B']['shares'] == -10000 and trades['B']['etf_shares'] == 2500
    assert trades['C']['etf_shares'] == 6250 and trades['D']['etf_shares'] == pytest.approx(-25000)
    # gross P&L of each position = stock leg + its own (un-netted) hedge leg
    assert trades['A']['gross_pnl'] == pytest.approx(5000 * 3 - 2500 * 3)
    assert trades['B']['gross_pnl'] == pytest.approx(-10000 * 2 + 2500 * 5)
    assert trades['C']['gross_pnl'] == pytest.approx(-25000 * -1 + 6250 * -0.5)
    assert trades['D']['gross_pnl'] == pytest.approx(-25000 * -0.5)
    assert sum(t['gross_pnl'] for t in trades.values()) == pytest.approx(sum(out['daily_gross_pnl']), abs=1e-9)

    # ETF trades: XLK nets to zero on day 2 (no trade), +2500 on day 5 (A closes), -2500 on day 7;
    # XLF: -18750 on day 2, +18750 on day 7.
    xlk, xlf = market.etf_close[:, market.etfs.index('XLK')], market.etf_close[:, market.etfs.index('XLF')]
    net_traded = 18750 * xlf[2] + 2500 * xlk[5] + 2500 * xlk[7] + 18750 * xlf[7]
    unnetted = (2500 + 2500) * xlk[2] + (6250 + 25000) * xlf[2] + 2500 * xlk[5] + 2500 * xlk[7] \
        + (6250 + 25000) * xlf[7]
    assert out['turnover']['etf_traded_notional'] == pytest.approx(net_traded)
    assert out['turnover']['etf_traded_notional_unnetted'] == pytest.approx(unnetted)

    def etf_cost(shares, price):
        return cm.calculate_leg_cost(shares, price, daily_volume_shares=ETF_ASSUMED_ADV_DOLLARS / price,
                                     daily_volatility=None, point_in_time_price=price)

    legs = [etf_cost(18750, xlf[2]), etf_cost(2500, xlk[5]), etf_cost(2500, xlk[7]), etf_cost(18750, xlf[7])]
    for key in ('commission', 'bid_ask', 'market_impact'):
        assert out['costs']['etf'][key] == pytest.approx(sum(c[key] for c in legs))
    assert out['costs']['etf']['bid_ask'] == pytest.approx(0.75e-4 * net_traded)   # top ADV bucket
    assert out['costs']['etf']['market_impact'] < 0.1e-4 * net_traded                # < 0.1 bp
    # XLF is net short 18,750 shares from the day-2 close (Fri) to the day-7 close: daily
    # borrow over calendar days (3 across the weekend)
    days = market.dates
    borrow = sum(cm.calculate_borrow_cost(18750 * xlf[k - 1], 'XLF', (days[k] - days[k - 1]).days)
                 for k in range(3, 8))
    assert out['costs']['etf']['borrow'] == pytest.approx(borrow)
    assert out['costs']['etf']['borrow'] > 0

    # stock legs: entry + exit through calculate_leg_cost (no ADV history -> model defaults),
    # borrow on the short legs only, over calendar days
    a, b = trades['A'], trades['B']
    ca = [cm.calculate_leg_cost(5000, 100.0, None, None, 100.0), cm.calculate_leg_cost(5000, 103.0, None, None, 103.0)]
    assert a['costs']['commission'] == pytest.approx(sum(c['commission'] for c in ca))
    assert a['costs']['market_impact'] == pytest.approx(sum(c['market_impact'] for c in ca))
    assert a['costs']['borrow'] == 0.0
    assert b['costs']['borrow'] == pytest.approx(cm.calculate_borrow_cost(10000 * 50.0, 'B', 7))
    assert b['calendar_days'] == 7 and b['holding_days'] == 5

    # every dollar: per-trade costs + ETF costs = daily costs = gross - net
    for t in trades.values():
        assert t['costs']['total'] == pytest.approx(sum(t['costs'][k] for k in
                                                        ('commission', 'bid_ask', 'market_impact', 'borrow')))
        assert t['net_pnl'] == pytest.approx(t['gross_pnl'] - t['costs']['total'])
        assert t['gross_bp'] == pytest.approx(t['gross_pnl'] / N0 * 1e4)
    stock_total = sum(t['costs']['total'] for t in trades.values())
    assert out['costs']['stock']['total'] == pytest.approx(stock_total)
    assert out['costs']['total'] == pytest.approx(stock_total + out['costs']['etf']['total'])
    assert sum(out['daily_costs']) == pytest.approx(out['costs']['total'])
    final = out['daily_equity'][-1]
    assert final == pytest.approx(1e8 + sum(out['daily_gross_pnl']) - out['costs']['total'])
    assert out['summary']['total_return'] == pytest.approx(final / 1e8 - 1)
    assert out['daily_open_positions'] == [0, 0, 4, 4, 4, 3, 3, 0]


def test_exposures_turnover_and_summary_metrics_on_the_hand_book():
    market, signals = _hand_book()
    out = summarise_residual_book(simulate_residual_book(market, signals), market.dates)
    eq = np.asarray(out['daily_equity'])
    xlf = market.etf_close[:, market.etfs.index('XLF')]
    # day 2: four $500,000 stock legs; A's and B's XLK hedges cancel, so the ETF book is
    # XLF alone, net short 18,750 shares
    assert out['daily_stock_gross_exposure'][2] == pytest.approx(2e6 / eq[2])
    assert out['daily_etf_gross_exposure'][2] == pytest.approx(18750 * xlf[2] / eq[2])
    assert out['daily_gross_exposure'][2] == pytest.approx((2e6 + 18750 * xlf[2]) / eq[2])
    years = len(eq) / 252
    t = out['turnover']
    assert t['annual_turnover'] == pytest.approx(
        (t['stock_traded_notional'] + t['etf_traded_notional']) / eq.mean() / years)
    s = out['summary']
    peak = np.maximum.accumulate(np.concatenate([[1e8], eq]))[1:]
    assert s['max_drawdown'] < 0 and s['max_drawdown'] == pytest.approx((eq / peak - 1).min())
    assert s['annualized_return'] == pytest.approx((eq[-1] / 1e8) ** (1 / years) - 1)


def test_missing_bars_reject_entries_keep_state_and_exit_at_the_last_real_close():
    close = {'A': [40, 40, 40, 41, 42, 43, 44, 45, 46, 47], 'B': [60, 60, 61, 62, 63, 64, 65, 66, 64, 63],
             'C': [25, 25, 25, 24, 24.5, 24, 23, 23.5, 24, 24]}
    frames, dates = _frames(close, {s: [1e6] * 10 for s in close}, start='2024-03-04')
    frames['A'] = frames['A'].drop(frames['A'].index[2])          # no bar on A's fill day
    frames['B'] = frames['B'].drop(frames['B'].index[[5, 6]])     # B halted on rows 5-6
    etfs = {'XLK': pd.Series(np.linspace(100, 104.5, 10), index=dates),
            'XLF': pd.Series(np.linspace(50, 48.2, 10), index=dates)}
    market = ResidualMarket.from_prices(frames, etfs, {'A': 'XLK', 'B': 'XLK', 'C': 'XLF'})
    # returns only between consecutive real bars: none on the gap or the first bar after it
    ret_b = market.stock_returns()[:, 1]
    assert np.isnan(ret_b[[0, 5, 6, 7]]).all() and np.isfinite(ret_b[[1, 2, 3, 4, 8, 9]]).all()

    T, N = 10, 3
    s = np.full((T, N), np.nan)
    s[1] = [-2.0, -2.0, 2.0]          # open A and B long, C short; fills due on row 2
    s[4, 1] = 0.0                     # close B; its fill row 5 has no bar
    s[3, 2] = 0.0                     # C would close, but row 3 has no estimate: keep state
    s[6, 2] = 0.0                     # close C; fills on row 7
    est = np.ones((T, N), dtype=bool)
    est[3, 2] = False
    signals = ResidualSignals(s=s, beta=np.ones((T, N)), kappa=np.full((T, N), 50.0), m=np.zeros((T, N)),
                              sigma_eq=np.full((T, N), 0.02), estimable=est, accepted=est.copy(),
                              in_universe=np.ones((T, N), dtype=bool))
    out = summarise_residual_book(simulate_residual_book(market, signals), market.dates)
    trades = {t['symbol']: t for t in out['trades']}
    day = [str(d.date()) for d in dates]
    xlk = market.etf_close[:, market.etfs.index('XLK')]

    assert out['rejects'] == {'no_fill_bar': 1} and set(trades) == {'B', 'C'}
    b, c = trades['B'], trades['C']
    assert (b['entry_date'], b['exit_signal_date'], b['exit_date']) == (day[2], day[4], day[5])
    assert b['exit_price'] == 63.0 and not b['exit_price_real']   # B's last real close, row 4
    assert b['gross_pnl'] == pytest.approx(b['shares'] * (63 - 61) + b['etf_shares'] * (xlk[5] - xlk[2]))
    assert (c['exit_signal_date'], c['exit_date'], c['exit_reason']) == (day[6], day[7], 'signal')
    assert c['exit_price_real']
    assert out['daily_open_positions'] == [0, 0, 2, 2, 2, 1, 1, 0, 0, 0]
    assert sum(t['gross_pnl'] for t in trades.values()) == pytest.approx(sum(out['daily_gross_pnl']))
    assert np.isfinite(out['daily_equity']).all()


def test_cost_accounting_sums_on_a_full_run(ou_run):
    res = ou_run[3]
    trades, costs = res['trades'], res['costs']
    assert costs['stock']['total'] == pytest.approx(sum(t['costs']['total'] for t in trades))
    for key in ('commission', 'bid_ask', 'market_impact', 'borrow'):
        assert costs['stock'][key] == pytest.approx(sum(t['costs'][key] for t in trades))
    assert costs['total'] == pytest.approx(costs['stock']['total'] + costs['etf']['total'])
    assert sum(res['daily_costs']) == pytest.approx(costs['total'])
    assert sum(t['gross_pnl'] for t in trades) == pytest.approx(sum(res['daily_gross_pnl']), rel=1e-9)
    assert res['daily_equity'][-1] == pytest.approx(1e8 + sum(res['daily_gross_pnl']) - costs['total'])
    shorts = [t for t in trades if t['side'] == 'short']
    assert shorts and all(t['costs']['borrow'] > 0 for t in shorts)
    assert all(t['costs']['borrow'] == 0 for t in trades if t['side'] == 'long')
    s = res['summary']
    assert s['cost_bp_per_trade'] == pytest.approx(
        np.mean([t['cost_bp'] for t in trades]) + costs['etf']['total'] / sum(t['notional'] for t in trades) * 1e4)
    # netting can only reduce the ETF notional traded
    assert res['turnover']['etf_traded_notional'] < res['turnover']['etf_traded_notional_unnetted']


def test_results_export_as_strict_json(ou_run, tmp_path):
    path = _atomic_write_json(_script().export_payload(ou_run[3], {'git_commit': None}), tmp_path / 'r.json')
    with open(path) as fh:
        doc = json.load(fh, parse_constant=pytest.fail)
    assert {'daily_dates', 'daily_net_returns', 'daily_returns', 'daily_gross_returns', 'daily_gross_exposure',
            'daily_open_positions', 'total_trades', 'trades', 'costs', 'turnover', 'summary', 'significance',
            'params', 'params_hash', 'spec', 'complete', 'non_default_switches', 'run_config'} <= set(doc)
    assert 'signals' not in doc and 'market' not in doc
    assert doc['total_trades'] == len(doc['trades']) == len(ou_run[3]['trades'])
    assert doc['daily_net_returns'] == doc['daily_returns'] and doc['complete'] is True
    sig = doc['significance']
    assert sig['ann_sharpe'] == doc['summary']['sharpe'] and sig['hac_p'] == doc['summary']['hac_p_net']
    assert sig['boot_lo'] < sig['ann_sharpe'] < sig['boot_hi'] and 0.5 < sig['psr'] <= 1


# ── S1's cost model and point-in-time universe ──────────────────────────────────

def test_the_default_cost_model_is_s1s(ou_run, monkeypatch):
    cm = s1_cost_model()
    v33 = PROFILES['v33']
    assert (cm.gc_borrow_rate, cm.pb_financing_spread) == (v33.borrow_rate, v33.pb_financing_spread) == (0.0038, 0.0)
    res = ou_run[3]
    assert (res['spec']['borrow_rate'], res['spec']['pb_financing_spread']) == (0.0038, 0.0)
    short = next(t for t in res['trades'] if t['side'] == 'short')
    assert short['costs']['borrow'] == pytest.approx(
        cm.calculate_borrow_cost(abs(short['shares']) * short['entry_price'], short['symbol'], short['calendar_days']))
    # this book models no financing carry, so it refuses a profile that charges one
    import dataclasses
    from pairs_trading import residual_statarb
    monkeypatch.setitem(residual_statarb.PROFILES, 'v33', dataclasses.replace(v33, pb_financing_spread=0.005))
    with pytest.raises(ValueError, match='prime-broker'):
        s1_cost_model()


SNAP_DATES = ('2021-03-31', '2022-06-30', '2022-12-30')


def _pit_market(tmp_path, seed=0):
    """make_residual_market with three membership snapshots: names[0] is never a member,
    names[1] joins on 2022-06-30, names[2] leaves on 2022-12-30."""
    frames, etfs, smap, _ = make_residual_market(seed=seed, residual='ou')
    names = sorted(smap)
    outsider, joiner, leaver = names[:3]
    snaps = {SNAP_DATES[0]: [n for n in names if n not in (outsider, joiner)],
             SNAP_DATES[1]: [n for n in names if n != outsider],
             SNAP_DATES[2]: [n for n in names if n not in (outsider, leaver)]}
    pit = PITUniverse(write_reference(tmp_path / 'reference', snaps))
    return frames, etfs, smap, pit, (outsider, joiner, leaver)


def test_a_name_outside_the_point_in_time_membership_never_enters(tmp_path):
    frames, etfs, smap, pit, (outsider, _, _) = _pit_market(tmp_path)
    frames[outsider] = frames[outsider].assign(Volume=frames[outsider]['Volume'] * 100)   # by far the most liquid
    params = ResidualStatArbParams(universe_size=10)          # liquidity binds
    gated = run_residual_statarb(frames, etfs, smap, START, END, params=params, members=pit.members_asof)
    free = run_residual_statarb(frames, etfs, smap, START, END, params=params)
    col = gated['market'].symbols.index(outsider)
    first_k = int(gated['market'].dates.searchsorted(pd.Timestamp(START)))
    assert free['signals'].in_universe[first_k:, col].all()          # ungated, it ranks first every day
    assert not gated['signals'].in_universe[:, col].any()
    assert outsider in {t['symbol'] for t in free['trades']}
    assert outsider not in {t['symbol'] for t in gated['trades']}
    assert gated['universe']['point_in_time'] and not free['universe']['point_in_time']
    for row in gated['universe']['rankings']:                       # every ranking: members only, 10 chosen
        assert row['members'] == len(pit.members_asof(row['date'])) and row['selected'] == 10


@pytest.mark.parametrize('every', [1, 21])
def test_point_in_time_membership_changes_only_where_a_snapshot_takes_effect(tmp_path, every):
    """With the size not binding, the universe is the snapshot in force on each ranking day:
    it changes on the first ranking day on or after a snapshot's period date and on no
    other day (with daily ranking, on the snapshot dates themselves)."""
    frames, etfs, smap, pit, (_, joiner, leaver) = _pit_market(tmp_path)
    res = run_residual_statarb(frames, etfs, smap, START, END, members=pit.members_asof,
                               params=ResidualStatArbParams(universe_rebalance_days=every))
    market, inu = res['market'], res['signals'].in_universe
    names = np.array(market.symbols)
    first_k = int(market.dates.searchsorted(pd.Timestamp(START)))
    rows = range(first_k, len(market.dates))
    changes = [k for k in rows[1:] if (inu[k] != inu[k - 1]).any()]
    takes_effect = [next(k for k in rows if (k - first_k) % every == 0 and market.dates[k] >= pd.Timestamp(d))
                    for d in SNAP_DATES[1:]]
    assert changes == takes_effect
    if every == 1:
        assert [str(market.dates[k].date()) for k in changes] == list(SNAP_DATES[1:])
    for k in rows:
        ranking_day = market.dates[first_k + every * ((k - first_k) // every)]
        assert set(names[inu[k]]) == set(pit.members_asof(ranking_day))
    joined, left = market.symbols.index(joiner), market.symbols.index(leaver)
    assert not inu[first_k:takes_effect[0], joined].any() and inu[takes_effect[0]:, joined].all()
    assert inu[first_k:takes_effect[1], left].all() and not inu[takes_effect[1]:, left].any()
    assert all(pd.Timestamp(t['signal_date']) >= market.dates[takes_effect[0]]
               for t in res['trades'] if t['symbol'] == joiner)


# ── the run script on a study calendar (synthetic caches, nothing fetched) ──────

CAL = CALENDARS['rehearsal2025']
COMMIT = 'c' * 40
SNAPSHOTS = ('2024-09-30', '2024-12-31', '2025-03-31', '2025-06-30', '2025-09-30')


def _calendar_layout(root, monkeypatch, extend_past_end=False):
    """A synthetic market laid out as the rehearsal2025 calendar's caches under `root`, with
    point-in-time snapshots in which names[0] is never a member, and the run's environment:
    `root` as the working directory, its reference/ as the committed one, a clean tree at
    COMMIT, and every network fetch an error."""
    from pairs_trading import data_processor, json_export, universe
    from pairs_trading.synthetic import write_calendar_caches
    end = '2025-10-31' if extend_past_end else CAL.data_end
    frames, etfs, smap, _ = make_residual_market(seed=5, residual='ou', start='2022-01-03', end=end)
    names = sorted(smap)
    vix = pd.Series(20.0, index=next(iter(etfs.values())).index)
    write_calendar_caches(root, CAL, frames, {'VIX': vix, 'sectors': etfs})
    write_reference(root / 'reference', {d: names[1:] for d in SNAPSHOTS}, sector_etf=smap)
    monkeypatch.setattr(universe, 'REFERENCE_DIR', root / 'reference')
    monkeypatch.setattr(json_export, '_git_state', lambda: (COMMIT, False))
    monkeypatch.setattr(json_export, '_START_PROVENANCE', {})

    def no_fetch(*args, **kwargs):
        raise AssertionError('the residual arm fetched data')
    monkeypatch.setattr(data_processor.EnhancedRussell3000DataProcessor, '_download_history', no_fetch)
    monkeypatch.setattr(data_processor.EnhancedRussell3000DataProcessor, '_fetch_many', no_fetch)
    monkeypatch.chdir(root)
    return names


def test_a_calendar_run_trades_inside_the_calendar_and_exports_the_registered_record(tmp_path, monkeypatch):
    names = _calendar_layout(tmp_path, monkeypatch)
    out = tmp_path / 'out' / 'residual_statarb.json'
    assert _script().main(['--calendar', 'rehearsal2025', '--out', str(out)]) == 0
    doc = json.loads(out.read_text(), parse_constant=pytest.fail)

    # the calendar's bounds: first signal on backtest_start (a zero-return session), last on data_end
    days = doc['daily_dates']
    assert days[0] == CAL.backtest_start and days[-1] == CAL.data_end
    assert len(days) == len(pd.bdate_range(CAL.backtest_start, CAL.data_end))
    assert doc['daily_net_returns'][0] == doc['daily_gross_returns'][0] == 0.0
    assert doc['daily_gross_exposure'][0] == 0.0 and doc['daily_open_positions'][0] == 0
    trades = doc['trades']
    assert doc['total_trades'] == len(trades) > 50
    assert min(t['signal_date'] for t in trades) >= CAL.backtest_start
    assert all(t['signal_date'] < t['entry_date'] <= t['exit_date'] <= CAL.data_end for t in trades)
    assert {t['exit_date'] for t in trades if t['exit_reason'] == 'end_of_data'} <= {CAL.data_end}
    assert names[0] not in {t['symbol'] for t in trades}                     # never a member
    rankings = doc['universe']['rankings']
    assert rankings[0]['date'] == CAL.backtest_start and len(rankings) == -(-len(days) // 21)
    for row in rankings:                    # the snapshot in force on each ranking day, its members
        assert row['snapshot'] == max(d for d in SNAPSHOTS if d <= row['date'])
        assert row['members'] == row['selected'] == len(names) - 1
    gaps = doc['universe_by_formation']     # one survivorship record per snapshot that governs
    assert [g['snapshot'] for g in gaps] == sorted({row['snapshot'] for row in rankings})
    assert all(g['missing'] == 0 and g['members'] == len(names) - 1 for g in gaps)

    # the record the evaluator and the publisher read
    assert doc['complete'] is True and doc['non_default_switches'] == []
    rc = doc['run_config']
    assert (rc['git_commit'], rc['git_dirty']) == (COMMIT, False)
    assert rc['study']['calendar']['name'] == 'rehearsal2025' and rc['study']['calendar_hash'] == CAL.config_hash()
    assert rc['study']['params_hash'] == ResidualStatArbParams().config_hash() == doc['params_hash']
    assert rc['effective'] == {'fill': 'close', 'calendar': 'rehearsal2025'}
    for key, path in (('price_cache', CAL.price_cache), ('macro_cache', CAL.macro_cache),
                      ('universe_file', 'reference/universe/index.json')):
        with open(tmp_path / path, 'rb') as fh:
            assert rc['data'][key]['sha256'] == hashlib.sha256(fh.read()).hexdigest(), key
    assert rc['sector_map']['registered'] is True and len(rc['sector_map']['file']['sha256']) == 64
    assert rc['universe']['snapshots'][0]['period_date'] == '2024-12-31'
    assert rc['data']['backtest_start'] == CAL.backtest_start and rc['data']['data_end'] == CAL.data_end


def test_the_run_script_fetches_nothing_and_stops_on_what_the_caches_lack(tmp_path, monkeypatch, caplog):
    from pairs_trading import universe
    names = _calendar_layout(tmp_path, monkeypatch)
    mod = _script()
    out = tmp_path / 'r.json'
    args = ['--calendar', 'rehearsal2025', '--out', str(out)]

    # a member the price cache never attempted: the data step has not run for this universe
    smap = universe.sector_etf_map()
    write_reference(tmp_path / 'other', {d: names[1:] + ['NEWCO'] for d in SNAPSHOTS}, sector_etf=smap)
    monkeypatch.setattr(universe, 'REFERENCE_DIR', tmp_path / 'other')
    assert mod.main(args) == 2 and 'never fetched 1' in caplog.text and '--fetch-only' in caplog.text
    assert not out.exists()
    monkeypatch.setenv('PAIRS_ALLOW_PARTIAL_FETCH', '1')                   # a declared, recorded variant
    assert mod.main(args) == 0
    doc = json.loads(out.read_text())
    assert doc['non_default_switches'] == ['PAIRS_ALLOW_PARTIAL_FETCH=1', 'never_fetched_members=1']
    assert doc['run_config']['data']['never_fetched_members'] == ['NEWCO']
    monkeypatch.delenv('PAIRS_ALLOW_PARTIAL_FETCH')
    monkeypatch.setattr(universe, 'REFERENCE_DIR', tmp_path / 'reference')
    out.unlink()

    # a sector ETF that stops before the last price date
    with open(tmp_path / CAL.macro_cache, 'rb') as fh:
        macro = pickle.load(fh)
    macro['sectors']['XLC'] = macro['sectors']['XLC'].iloc[:-5]
    with open(tmp_path / CAL.macro_cache, 'wb') as fh:
        pickle.dump(macro, fh)
    caplog.clear()
    assert mod.main(args) == 2 and 'lacks closes' in caplog.text and "['XLC']" in caplog.text
    # no macro cache at all
    os.remove(tmp_path / CAL.macro_cache)
    caplog.clear()
    assert mod.main(args) == 2 and 'never fetches' in caplog.text
    assert not out.exists()


def test_the_run_script_refuses_a_cache_of_another_period_and_other_code(tmp_path, monkeypatch, caplog):
    _calendar_layout(tmp_path, monkeypatch, extend_past_end=True)        # bars after data_end
    mod = _script()
    args = ['--calendar', 'rehearsal2025', '--out', str(tmp_path / 'r.json')]
    assert mod.main(args) == 2 and 'another period' in caplog.text
    _calendar_layout(tmp_path, monkeypatch)
    monkeypatch.setenv('PAIRS_EXPECTED_COMMIT', 'e' * 40)                # the runbook's commit check
    caplog.clear()
    assert mod.main(args) == 2 and 'PAIRS_EXPECTED_COMMIT' in caplog.text
    assert not (tmp_path / 'r.json').exists()
