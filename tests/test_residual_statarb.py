"""Avellaneda-Lee (2010) sector-ETF residual strategy (pairs_trading/residual_statarb.py).

Formulas (A&L Appendix eq. 21, centred s-score eq. 22) against hand-computed values and an
independent statsmodels fit; causality (decisions dated <= t are unchanged when every
price and volume after t changes); t+1 fills; known answers on synthetic markets (a
planted OU residual must give a large positive gross edge, a random-walk residual none);
ETF hedge netting and cost accounting on a hand-built book.
"""
import importlib.util
import json
import os
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
    run_residual_statarb, simulate_residual_book, summarise_residual_book,
)
from pairs_trading.synthetic import make_residual_market, perturb_after
from pairs_trading.transaction_costs import EnhancedPrimeFundTransactionCostModel

START, END = '2021-07-01', '2023-12-31'
SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts',
                      'run_residual_statarb.py')


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


def test_run_script_prefers_the_industry_file_and_records_which_map_it_used(tmp_path, monkeypatch):
    mod = _script()
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data' / 'marketcap.csv').write_text('Symbol,Name,MarketCap,Sector,Industry\n'
                                                      'AAPL,Apple,1,Technology,x\nO,Realty,1,Finance,x\n')
    monkeypatch.chdir(tmp_path)
    mapping, info = mod.load_sector_map()                       # no industry file: Nasdaq sectors
    assert mapping == {'AAPL': 'XLK', 'O': 'XLF'} and info['source'].startswith('nasdaq_sector')
    assert info['file']['path'] == 'marketcap.csv' and len(info['file']['sha256']) == 64

    (tmp_path / 'reference').mkdir()
    (tmp_path / 'reference' / 'industry_ff49.csv').write_text(_FF49_CSV)
    mapping, info = mod.load_sector_map()                       # industry file present: preferred
    assert mapping == {'AAPL': 'XLK', 'BRK-B': 'XLF', 'O': 'XLRE'} and info['source'].startswith('ff49_sic')
    assert info['n_symbols'] == 3 and info['etf_counts'] == {'XLF': 1, 'XLK': 1, 'XLRE': 1}
    assert mod.load_sector_map('nasdaq')[1]['source'].startswith('nasdaq_sector')
    assert mod.load_sector_map(str(tmp_path / 'reference' / 'industry_ff49.csv'))[0] == mapping


def test_run_script_has_a_working_cli():
    r = subprocess.run([sys.executable, SCRIPT, '--help'], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and '--sector-map' in r.stdout and '--universe-size' in r.stdout


# ── causality and execution timing ───────────────────────────────────────────────

def _decision(t):
    return (t['symbol'], t['side'], t['signal_date'], t['s_entry'], t['kappa'], t['beta'], t['m'],
            t['sigma_eq'], t['notional'], t['shares'], t['etf_shares'])


@pytest.mark.parametrize('cutoff', ['2022-06-15', '2023-03-01'])
def test_decisions_up_to_t_ignore_all_data_after_t(cutoff):
    frames, etfs, smap, _ = make_residual_market(seed=11, residual='ou')
    base = run_residual_statarb(frames, etfs, smap, START, END)
    cut = pd.Timestamp(cutoff)
    rng = np.random.default_rng(5)
    etfs_p = {}
    for e, v in etfs.items():
        v = v.copy()
        after = v.index > cut
        v[after] = v[after].to_numpy() * np.exp(np.cumsum(rng.normal(0, 0.03, int(after.sum()))))
        etfs_p[e] = v
    pert = run_residual_statarb(perturb_after(frames, cutoff), etfs_p, smap, START, END)

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
        doc = json.load(fh)
    assert {'daily_dates', 'daily_returns', 'daily_gross_returns', 'daily_gross_exposure', 'daily_open_positions',
            'trades', 'costs', 'turnover', 'summary', 'params', 'spec', 'run_config'} <= set(doc)
    assert 'signals' not in doc and 'market' not in doc
    assert len(doc['trades']) == len(ou_run[3]['trades'])
