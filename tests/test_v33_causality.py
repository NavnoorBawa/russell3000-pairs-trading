"""Look-ahead under the published design: v33's point-in-time membership, same-industry
selection and full re-formation every 126 trading days, with a perturbed future.

tests/test_engine_v32.py, test_properties.py and test_leakage.py perturb every price after a
cutoff and require every decision dated on or before it to be unchanged, but they run under the
v32 profile on fixed pairs (tests/conftest.py pins PAIRS_PROFILE=v32). This test runs the same
check through v33's own path, prepare_study() and a backtest over its pair windows: the
formations, entries and daily returns up to the cutoff must not depend on anything after it.
"""
import pandas as pd

from tests.synthetic_market import build_system, make_market, perturb_after, perturb_macro_after
from tests.test_v33_design import _Membership

CUT = '2024-06-03'


def _run(frames, macro, members):
    system = build_system(frames, macro)
    system.spread_data, system.selected_pairs = {}, []
    system.pit_universe = _Membership(members)
    system.industries = {m: 'Banks' for m in members}
    system.pair_selector = system._new_pair_selector()
    test_spreads, windows, last = system.prepare_study()
    result = system.run_comprehensive_backtest(test_spreads, pair_windows=windows,
                                               date_range=(system.calendar.backtest_start, last))
    return system, result, windows


def _day(x):
    ts = pd.Timestamp(x)
    return ts.tz_localize(None) if ts.tzinfo is not None else ts


def test_v33_decisions_before_a_cutoff_ignore_the_future(monkeypatch):
    monkeypatch.setenv('PAIRS_PROFILE', 'v33')
    frames, macro, _ = make_market(n_pairs=4, n_noise=4, seed=11)
    members = sorted(frames)
    sa, a, wa = _run(frames, macro, members)
    sb, b, wb = _run(perturb_after(frames, CUT), perturb_macro_after(macro, CUT), members)
    assert sa.profile.name == sb.profile.name == 'v33'
    cut = pd.Timestamp(CUT)

    def entries(res):
        return [(t['pair'], str(_day(t['signal_date']).date()), t['action'], round(t['position_size'], 9),
                 round(t['zscore'], 9), round(t['hedge_ratio'], 9))
                for t in res['trades'] if _day(t['signal_date']) <= cut]

    def formations(w):
        return {str(_day(k).date()): sorted(map(str, v)) for k, v in w.items() if _day(k) <= cut}

    def daily(res):
        return [(str(d), r) for d, r in zip(res['daily_dates'], res['daily_returns']) if _day(d) <= cut]

    assert len(formations(wa)) >= 2, 'the check needs at least one re-formation before the cutoff'
    assert entries(a), 'the check needs trades before the cutoff'
    assert formations(wa) == formations(wb)
    assert entries(a) == entries(b)
    assert daily(a) == daily(b)
    # and the perturbation does reach the decisions after the cutoff
    assert [t['signal_date'] for t in a['trades']] != [t['signal_date'] for t in b['trades']] or \
        a['daily_returns'] != b['daily_returns']
