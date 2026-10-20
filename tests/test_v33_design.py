"""The v33 design switches on a synthetic market: point-in-time membership at every
formation date, same-industry candidate pairs, and full re-formation on a trailing window.

The universe source is injected (a stand-in for universe.PITUniverse), so these tests need
no reference files; tests/test_universe.py covers the real snapshots.
"""
import pandas as pd
import pytest

from pairs_trading.pair_selector import FixedPrimeFundPairSelector
from tests.synthetic_market import build_system, make_market


class _Membership:
    """Stand-in for universe.PITUniverse: fixed members, and a log of the dates asked."""

    def __init__(self, members):
        self.members = sorted(members)
        self.asked = []

    def members_asof(self, date):
        ts = pd.Timestamp(date)
        self.asked.append(ts.tz_localize(None) if ts.tzinfo is not None else ts)
        return list(self.members)

    def coverage(self, symbols, date):
        have = set(symbols)
        missing = [m for m in self.members if m not in have]
        return {'snapshot': '2022-12-30', 'members': len(self.members),
                'with_prices': len(self.members) - len(missing), 'missing': len(missing),
                'missing_value_weight': 0.01 * len(missing), 'unmapped_value_weight': 0.0,
                'missing_symbols': missing}


def test_candidate_pairs_all_or_same_industry():
    sel = FixedPrimeFundPairSelector()
    syms = ['A', 'B', 'C', 'D', 'E']
    assert len(sel.candidate_pairs(syms)) == 10
    sel.industry_of = {'A': 'Banks', 'B': 'Banks', 'C': 'Chips', 'D': 'Chips', 'E': ''}
    assert sel.candidate_pairs(['D', 'C', 'B', 'A', 'E']) == [('A', 'B'), ('C', 'D')]
    sel.industry_of = {'A': 'Banks'}                     # unclassified names form no pair
    assert sel.candidate_pairs(syms) == []


def _v33_system(monkeypatch, members, industries):
    monkeypatch.setenv('PAIRS_PROFILE', 'v33')
    frames, macro, _ = make_market(n_pairs=4, n_noise=4, seed=11)
    system = build_system(frames, macro)
    system.spread_data, system.selected_pairs = {}, []
    system.pit_universe = _Membership(members)
    system.industries = industries
    system.pair_selector = system._new_pair_selector()
    return system, frames


def test_v33_selects_only_point_in_time_members_of_one_industry(monkeypatch):
    # SA00/SB00 and SA01/SB01 are planted pairs; SA02 is not a member; SB03 is in a
    # different industry from SA03, so neither planted pair 02 nor 03 may be selected.
    members = ['SA00', 'SB00', 'SA01', 'SB01', 'SB02', 'SA03', 'SB03', 'SN00', 'SN01']
    industries = {s: 'Banks' for s in members if s != 'SB03'}
    industries['SB03'] = 'Chips'
    system, frames = _v33_system(monkeypatch, members, industries)
    assert system.profile.name == 'v33' and system.pair_selector.industry_of is industries
    test_spreads, windows, last = system.prepare_study()
    selected = set(system.selected_pairs)
    assert {('SA00', 'SB00'), ('SA01', 'SB01')} <= selected
    for a, b in selected:
        assert a in members and b in members
        assert industries[a] == industries[b]
    for pairs in windows.values():                         # every re-formation obeys both rules
        for a, b in pairs:
            assert a in members and b in members and industries[a] == industries[b]
    # membership is looked up at the cutoff and at each re-formation, never later
    asked = system.pit_universe.asked
    assert asked[0] == pd.Timestamp('2022-12-31')
    assert all(d <= pd.Timestamp(last) for d in asked)                  # last: a naive date string
    log = system.universe_coverage_log
    assert len(log) == len(asked) and log[0]['formation_date'] == '2022-12-31'
    assert log[0]['missing'] == 0 and log[0]['members'] == len(members)


def test_v33_reforms_on_its_trailing_window_every_126_days(monkeypatch):
    members = ['SA00', 'SB00', 'SA01', 'SB01', 'SA02', 'SB02', 'SN00']
    system, _ = _v33_system(monkeypatch, members, {s: 'Banks' for s in members})
    test_spreads, windows, last = system.prepare_study()
    keys = sorted(pd.Timestamp(k).tz_localize(None) for k in windows)
    test_days = sorted({d for s in test_spreads.values() for d in s.index})
    expected = [pd.Timestamp(test_days[i]).tz_localize(None) for i in range(0, len(test_days), 126)]
    assert keys[-len(expected):] == expected
    # re-formation is the full search (new pairs could enter), not a re-test of the pool
    assert set(system.pit_universe.asked[1:]) == set(expected)


def test_v33_full_pipeline_pieces_run_and_trade(monkeypatch):
    members = ['SA00', 'SB00', 'SA01', 'SB01', 'SA02', 'SB02', 'SN00', 'SN01']
    system, _ = _v33_system(monkeypatch, members, {s: 'Banks' for s in members})
    test_spreads, windows, last = system.prepare_study()
    res = system.run_comprehensive_backtest(test_spreads, pair_windows=windows,
                                            date_range=(system.calendar.backtest_start, last))
    assert res['total_trades'] > 0
    assert 'regime_hard_stop_day' not in res['signal_rejections']      # no regime gate in v33
    assert all(t['feature_quality'] == 1.0 for t in res['trades'])      # no learned ranker
    n = len(res['daily_returns'])
    assert len(res['daily_gross_returns']) == len(res['daily_cost_returns']) == n
    for net, gross, cost in zip(res['daily_returns'], res['daily_gross_returns'], res['daily_cost_returns']):
        assert net == pytest.approx(gross - cost, abs=1e-12)
