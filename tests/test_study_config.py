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
