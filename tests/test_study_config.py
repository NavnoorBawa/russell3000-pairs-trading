"""Study profiles and calendars (pairs_trading/study_config.py).

The v32 profile is pinned against the v32 code by a golden master in
test_pipeline_e2e.py; these tests cover the configuration object itself and that each
v33 switch reaches the component it is meant to change.
"""
import dataclasses

import numpy as np
import pandas as pd
import pytest

from pairs_trading import study_config as sc
from pairs_trading.multi_agent_system import FixedTransformerMultiAgentSystem
from pairs_trading.trading_system import (
    MAIN_BACKTEST_START, MAIN_MODEL_TRAIN_END, PAIR_SELECTION_CUTOFF,
    CompleteFixedRussell3000TradingSystem,
)
from tests.synthetic_market import build_system, make_market


def test_dev_calendar_is_the_published_study_calendar():
    dev = sc.CALENDARS['dev']
    assert (dev.selection_cutoff, dev.model_train_end, dev.backtest_start) == \
        (PAIR_SELECTION_CUTOFF, MAIN_MODEL_TRAIN_END, MAIN_BACKTEST_START) == \
        ('2022-12-31', '2023-06-30', '2023-07-01')
    assert (dev.data_start, dev.data_end) == ('2020-01-01', '2025-12-31')


def test_holdout_calendar_is_disjoint_from_the_development_period():
    dev, hold = sc.CALENDARS['dev'], sc.CALENDARS['holdout2026']
    assert hold.backtest_start > dev.data_end            # no holdout day was ever traded
    assert hold.selection_cutoff == dev.data_end         # formation ends where dev ends
    assert hold.price_cache != dev.price_cache           # the dev cache is never extended
    assert not hold.walk_forward


def test_rehearsal_calendar_is_the_holdout_shifted_back_one_year():
    dev, hold, reh = sc.CALENDARS['dev'], sc.CALENDARS['holdout2026'], sc.CALENDARS['rehearsal2025']
    assert reh.data_end <= dev.data_end                  # inside the development period
    assert reh.price_cache not in (dev.price_cache, hold.price_cache)
    shift = lambda d: pd.Timestamp(d) - pd.DateOffset(years=1)   # noqa: E731
    assert pd.Timestamp(reh.data_start) == shift(hold.data_start)
    assert pd.Timestamp(reh.selection_cutoff) == shift(hold.selection_cutoff)
    assert pd.Timestamp(reh.backtest_start) == shift(hold.backtest_start)
    assert reh.walk_forward == hold.walk_forward
    # the holdout's last close (Mon 2026-10-19) one year back falls on a Sunday: last Friday
    assert pd.Timestamp(reh.data_end) == shift(hold.data_end) - pd.Timedelta(days=2)


def test_v32_profile_is_the_v32_design():
    v32 = sc.PROFILES['v32']
    assert (v32.universe, v32.max_universe, v32.same_industry) == ('marketcap', 300, False)
    assert (v32.reselect, v32.reselect_every, v32.formation_calendar_days) == ('pool', 90, 730)
    assert v32.regime_gate and v32.ranker == 'transformer'
    assert (v32.borrow_rate, v32.pb_financing_spread) == (0.0025, 0.005)


def test_v33_profile_is_the_preregistered_design():
    v33 = sc.PROFILES['v33']
    assert (v33.universe, v33.max_universe, v33.same_industry) == ('pit_iwv', 500, True)
    assert (v33.reselect, v33.reselect_every, v33.formation_calendar_days) == ('full', 126, 1095)
    assert not v33.regime_gate and v33.ranker == 'none'
    assert (v33.borrow_rate, v33.pb_financing_spread) == (0.0038, 0.0)


def test_profile_and_calendar_resolution(monkeypatch):
    monkeypatch.delenv('PAIRS_PROFILE', raising=False)
    assert sc.get_profile() == sc.PROFILES[sc.DEFAULT_PROFILE]
    assert sc.get_calendar().name == sc.DEFAULT_CALENDAR
    monkeypatch.setenv('PAIRS_PROFILE', 'v32')
    monkeypatch.setenv('PAIRS_CALENDAR', 'holdout2026')
    assert sc.get_profile().name == 'v32' and sc.get_calendar().name == 'holdout2026'
    assert sc.get_profile('v33').name == 'v33'          # an explicit name beats the environment
    with pytest.raises(ValueError):
        sc.get_profile('v99')
    with pytest.raises(ValueError):
        sc.get_calendar('2027')


def test_legacy_switches_override_the_profile(monkeypatch):
    monkeypatch.setenv('PAIRS_RESELECT', 'FULL')
    monkeypatch.setenv('PAIRS_USE_TRANSFORMER', '0')
    p = sc.get_profile('v32')
    assert (p.reselect, p.ranker) == ('full', 'none')
    monkeypatch.setenv('PAIRS_RANKER', 'gbm')
    assert sc.get_profile('v32').ranker == 'gbm'
    monkeypatch.setenv('PAIRS_RESELECT', 'sometimes')
    with pytest.raises(ValueError):
        sc.get_profile('v32')


def test_config_hash_identifies_the_design():
    v32, v33 = sc.PROFILES['v32'], sc.PROFILES['v33']
    assert v32.config_hash() == sc.PROFILES['v32'].config_hash()
    assert v32.config_hash() != v33.config_hash()
    assert dataclasses.replace(v33, max_universe=300).config_hash() != v33.config_hash()
    rec = sc.describe(v33, sc.CALENDARS['dev'])
    assert rec['profile']['name'] == 'v33' and rec['calendar']['name'] == 'dev'


def test_profile_reaches_the_components():
    for name in ('v32', 'v33'):
        p = sc.PROFILES[name]
        system = CompleteFixedRussell3000TradingSystem(profile=name, calendar='holdout2026')
        assert system.profile is p and system.calendar.name == 'holdout2026'
        assert system.pair_selector.max_universe == p.max_universe
        assert system.rl_agent.ranker == p.ranker
        assert system.cost_model.gc_borrow_rate == p.borrow_rate
        assert system.cost_model.pb_financing_spread == p.pb_financing_spread
        assert system.data_processor.data_file == 'data/holdout2026_prices.pkl'
        assert (system.data_processor.start_date, system.data_processor.end_date) == \
            ('2023-01-01', '2026-10-19')


def test_v33_holding_costs_charge_borrow_once():
    v32 = CompleteFixedRussell3000TradingSystem(profile='v32').cost_model
    v33 = CompleteFixedRussell3000TradingSystem(profile='v33').cost_model
    # $1M short leg of a $2M position held a year
    assert v32.calculate_borrow_cost(1e6, 'X', 365) + v32.calculate_financing_cost(2e6, 365) == \
        pytest.approx(2_500 + 5_000)
    assert v33.calculate_borrow_cost(1e6, 'X', 365) + v33.calculate_financing_cost(2e6, 365) == \
        pytest.approx(3_800)


def _stressed_market():
    """A market whose VIX sits above 40 for the whole test period: the v32 gate cuts every
    position to a quarter and then blocks all entries (hard stop)."""
    frames, macro, _ = make_market(n_pairs=4, n_noise=0, seed=5)
    vix = macro['VIX'].copy()
    vix[vix.index >= pd.Timestamp('2023-01-01')] = 45.0
    return frames, {**macro, 'VIX': vix}


def test_regime_gate_is_off_in_v33(monkeypatch):
    frames, macro = _stressed_market()
    runs = {}
    for name in ('v32', 'v33'):
        monkeypatch.setenv('PAIRS_PROFILE', name)
        system = build_system(frames, macro)
        assert system.profile.name == name
        runs[name] = system.run_comprehensive_backtest(system.spread_data,
                                                       date_range=('2023-07-01', '2025-12-31'))
    assert runs['v32']['signal_rejections'].get('regime_hard_stop_day', 0) > 0
    assert runs['v33']['signal_rejections'].get('regime_hard_stop_day', 0) == 0
    assert runs['v33']['total_trades'] > runs['v32']['total_trades']


def test_gbm_ranker_trains_and_scores_probabilities():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(2000, FixedTransformerMultiAgentSystem.N_FEATURES)).astype(np.float32)
    y = (X[:, 0] + 0.5 * X[:, 1] * X[:, 2] + rng.normal(0, 1, 2000) > 0).astype(np.float32)
    agent = FixedTransformerMultiAgentSystem(ranker='gbm')
    assert agent.train_on_samples(X[:1500], y[:1500])
    assert agent.training_summary['model'] == 'gbm'
    p = agent.predict_raw(X[1500:])
    assert p.shape == (500,) and np.all((p > 0) & (p < 1))
    skill = agent.evaluate(X[1500:], y[1500:])
    assert skill['auc'] > 0.7                       # learns a real signal, incl. an interaction
    scaled = agent.scaler.transform(X[1500:1501])
    assert 0 < agent.score_signal_quality(scaled.flatten()) < 1


def test_ranker_none_never_trains():
    agent = FixedTransformerMultiAgentSystem(ranker='none')
    X = np.zeros((1000, agent.N_FEATURES), dtype=np.float32)
    y = np.r_[np.ones(500), np.zeros(500)].astype(np.float32)
    assert not agent.train_on_samples(X, y)
    assert agent.signal_transformer is None and agent.score_signal_quality(X[0]) == 1.0
    with pytest.raises(ValueError):
        FixedTransformerMultiAgentSystem(ranker='lstm')


# ── the holdout seal ───────────────────────────────────────────────────────────

def _git_repo(path, *steps):
    """A repository whose history is `steps`: ('add'|'rm'|'edit', file) each one commit."""
    import subprocess

    def git(*a):
        return subprocess.run(['git', *a], cwd=path, check=True, capture_output=True, text=True).stdout.strip()
    git('init', '-q')
    git('config', 'user.name', 't')
    git('config', 'user.email', 't@example.invalid')
    (path / 'README').write_text('x\n')
    git('add', 'README')
    git('commit', '-qm', 'root')
    commits = []
    for n, (op, name) in enumerate(steps):
        f = path / name
        if op == 'rm':
            git('rm', '-q', name)
        else:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(f'{n}\n')
            git('add', name)
        git('commit', '-qm', f'{op} {name}')
        commits.append(git('rev-parse', 'HEAD'))
    return commits


def test_the_holdout_is_unsealed_only_by_the_preregistration_commit(tmp_path, monkeypatch):
    prereg = sc.PREREGISTRATION
    added, edited = _git_repo(tmp_path, ('add', prereg), ('edit', prereg))
    assert sc.preregistration_commit(tmp_path) == added
    sc.assert_unsealed('2025-12-31', tmp_path)                  # before the seal: always allowed
    monkeypatch.delenv('PAIRS_UNSEAL', raising=False)
    with pytest.raises(sc.SealedError):
        sc.assert_unsealed('2026-10-19', tmp_path)
    monkeypatch.setenv('PAIRS_UNSEAL', edited)                  # a later commit does not unseal
    with pytest.raises(sc.SealedError):
        sc.assert_unsealed('2026-10-19', tmp_path)
    monkeypatch.setenv('PAIRS_UNSEAL', added)
    sc.assert_unsealed('2026-10-19', tmp_path)


def test_an_ambiguous_preregistration_history_unseals_nothing(tmp_path, monkeypatch):
    """Deleted and re-added: two adding commits, no unambiguous freeze. Not committed: none."""
    prereg = sc.PREREGISTRATION
    first, _, again = _git_repo(tmp_path, ('add', prereg), ('rm', prereg), ('add', prereg))
    assert sc.preregistration_commit(tmp_path) is None
    monkeypatch.setenv('PAIRS_UNSEAL', first)
    with pytest.raises(sc.SealedError):
        sc.assert_unsealed('2026-10-19', tmp_path)
    other = tmp_path / 'other'
    other.mkdir()
    _git_repo(other, ('add', 'docs/NOTES.md'))
    assert sc.preregistration_commit(other) is None


def test_sealed_calendars_read_their_membership_outside_the_tracked_tree():
    from pairs_trading.universe import REFERENCE_DIR, REPO_ROOT, reference_root
    assert reference_root(sc.CALENDARS['dev']) == REFERENCE_DIR
    assert reference_root(sc.CALENDARS['rehearsal2025']) == REFERENCE_DIR
    assert reference_root(sc.CALENDARS['holdout2026']) == REPO_ROOT / 'data' / 'holdout2026_reference'


def test_the_regime_gate_refuses_incomplete_macro_data():
    """A gated (v32) run whose VIX or a sector ETF is missing or stops before the last price
    date would read those days as calm; it stops instead."""
    frames, macro, _ = make_market(n_pairs=1, n_noise=0, seed=3, end='2021-06-30')
    system = CompleteFixedRussell3000TradingSystem(profile='v32', calendar='dev')
    system.processed_data = frames
    system.macro_data = macro
    system._check_macro_coverage()
    system.macro_data = {'VIX': macro['VIX'], 'sectors': {k: v for k, v in macro['sectors'].items() if k != 'XLRE'}}
    with pytest.raises(RuntimeError, match='XLRE'):
        system._check_macro_coverage()
    system.macro_data = {'VIX': macro['VIX'].iloc[:-3], 'sectors': macro['sectors']}
    with pytest.raises(RuntimeError, match='VIX'):
        system._check_macro_coverage()


def test_provenance_is_the_code_the_run_started_from(monkeypatch):
    """A commit or edit during a run makes its exports dirty, with both commits recorded;
    PAIRS_EXPECTED_COMMIT stops a run of other code before it loads anything."""
    from pairs_trading import json_export as je
    state = {'now': ('a' * 40, False)}
    monkeypatch.setattr(je, '_git_state', lambda: state['now'])
    monkeypatch.setattr(je, '_START_PROVENANCE', {})
    monkeypatch.delenv('PAIRS_EXPECTED_COMMIT', raising=False)
    je.record_start_provenance()
    rc = je.build_run_config()
    assert rc['git_commit'] == 'a' * 40 and rc['git_dirty'] is False and rc['git_changed_during_run'] is False
    state['now'] = ('b' * 40, False)
    rc = je.build_run_config()
    assert rc['git_commit'] == 'a' * 40 and rc['git_commit_at_export'] == 'b' * 40
    assert rc['git_dirty'] is True and rc['git_changed_during_run'] is True
    monkeypatch.setenv('PAIRS_EXPECTED_COMMIT', 'c' * 40)
    with pytest.raises(RuntimeError, match='PAIRS_EXPECTED_COMMIT'):
        je.record_start_provenance()
