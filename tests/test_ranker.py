"""The signal-quality ranker: trains only on real, non-degenerate samples; ranking-only."""
import numpy as np
import pandas as pd
import pytest

from pairs_trading.multi_agent_system import FixedTransformerMultiAgentSystem


def _samples(n=450, seed=0, base_rate=0.4):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, FixedTransformerMultiAgentSystem.N_FEATURES)).astype(np.float32)
    y = (rng.random(n) < base_rate).astype(np.float32)
    return X, y


def test_trains_on_enough_nondegenerate_samples(monkeypatch):
    monkeypatch.setenv('PAIRS_USE_TRANSFORMER', '1')
    agent = FixedTransformerMultiAgentSystem()
    X, y = _samples()
    assert agent.train_on_samples(X, y, epochs=1) is True
    assert agent.scaler_fitted
    q = agent.score_signal_quality(agent.scaler.transform(X[:1]).flatten())
    assert 0.0 <= q <= 1.0
    assert len(agent.training_summary['epoch_losses']) == 1


@pytest.mark.parametrize('n, base_rate', [(100, 0.4), (450, 0.0), (450, 1.0)])
def test_does_not_train_on_too_few_or_degenerate_samples(monkeypatch, n, base_rate):
    monkeypatch.setenv('PAIRS_USE_TRANSFORMER', '1')
    agent = FixedTransformerMultiAgentSystem()
    X, y = _samples(n=n, base_rate=base_rate)
    assert agent.train_on_samples(X, y, epochs=1) is False
    assert agent.signal_transformer is None
    assert agent.score_signal_quality(X[0]) == 1.0


def test_ablation_switch_disables_training(monkeypatch):
    monkeypatch.setenv('PAIRS_USE_TRANSFORMER', '0')
    agent = FixedTransformerMultiAgentSystem()
    X, y = _samples()
    assert agent.train_on_samples(X, y, epochs=1) is False
    assert agent.score_signal_quality(X[0]) == 1.0


def test_feature_vector_has_no_padding():
    agent = FixedTransformerMultiAgentSystem()
    idx = pd.bdate_range('2022-01-03', periods=120, tz='America/New_York')
    spread = pd.Series(np.random.default_rng(1).normal(size=120), index=idx)
    f = agent.extract_advanced_features(spread, {'correlation': 0.5, 'half_life': 10, 'quality_score': 0.7},
                                        pd.DataFrame(), pd.DataFrame())
    assert f.shape == (FixedTransformerMultiAgentSystem.N_FEATURES,)
    assert np.isfinite(f).all()


def test_class_weighting_is_undone_at_inference(monkeypatch):
    """pos_weight training shifts the log-odds by +log(w); the score must not inherit it.

    On uninformative features with a 20% base rate, a calibrated scorer predicts about
    0.2 on average. Without the prior correction it predicts about 0.5 (v31 behaviour).
    """
    import torch
    torch.manual_seed(0)
    monkeypatch.setenv('PAIRS_USE_TRANSFORMER', '1')
    agent = FixedTransformerMultiAgentSystem()
    X, y = _samples(n=1200, seed=3, base_rate=0.2)
    assert agent.train_on_samples(X, y, epochs=2)
    w = agent.training_summary['pos_weight']
    assert agent.signal_transformer.logit_offset == pytest.approx(-np.log(w))
    p = agent.predict_raw(X)
    assert abs(float(p.mean()) - float(y.mean())) < 0.1
    skill = agent.evaluate(X, y)
    assert skill['n'] == len(y) and 0.0 <= skill['auc'] <= 1.0
    assert skill['brier_base_rate'] == pytest.approx(np.mean((y.mean() - y) ** 2), rel=1e-6)


def test_scoring_failure_returns_the_prior_not_the_top_score(monkeypatch):
    monkeypatch.setenv('PAIRS_USE_TRANSFORMER', '1')
    agent = FixedTransformerMultiAgentSystem()
    X, y = _samples()
    assert agent.train_on_samples(X, y, epochs=1)

    def boom(_):
        raise RuntimeError('bad vector')
    monkeypatch.setattr(agent.signal_transformer, 'predict_signal_quality', boom)
    assert agent.score_signal_quality(X[0]) == pytest.approx(agent.training_summary['base_rate'])


def test_roc_auc_matches_reference():
    from sklearn.metrics import roc_auc_score
    from pairs_trading.multi_agent_system import roc_auc
    y = np.array([0, 0, 1, 1])
    assert roc_auc(y, np.array([0.1, 0.2, 0.8, 0.9])) == 1.0
    assert roc_auc(y, np.array([0.9, 0.8, 0.2, 0.1])) == 0.0
    assert roc_auc(y, np.full(4, 0.5)) == 0.5                      # ties count half
    assert roc_auc(np.ones(4), np.arange(4.0)) is None             # one class: undefined
    rng = np.random.default_rng(0)
    yy = rng.random(500) < 0.3
    s = rng.normal(size=500) + yy
    assert roc_auc(yy, s) == pytest.approx(roc_auc_score(yy, s))


def test_attention_weights_accept_a_batch(monkeypatch):
    monkeypatch.setenv('PAIRS_USE_TRANSFORMER', '1')
    agent = FixedTransformerMultiAgentSystem()
    X, y = _samples()
    assert agent.train_on_samples(X, y, epochs=1)
    single = agent.signal_transformer.get_attention_weights(X[0])
    batch = agent.signal_transformer.get_attention_weights(X[:5])
    assert single[0].shape[0] == 1 and batch[0].shape[0] == 5


def _cut_macro(obj, as_of):
    """Every series/frame inside the (possibly nested) macro dict, truncated at as_of."""
    if isinstance(obj, dict):
        return {k: _cut_macro(v, as_of) for k, v in obj.items()}
    if hasattr(obj, 'loc'):
        return obj.loc[:as_of]
    return obj


def test_serving_features_are_as_of_the_decision_date():
    """v31 audit fix: per-stock features must come from the decision date, not the last
    day of the study. Extracting with the full frames or with frames cut at the decision
    date must give identical vectors (the macro block reads as-of the same date)."""
    from tests.synthetic_market import build_system, make_market
    frames, macro, _ = make_market(n_pairs=2, n_noise=0, seed=5)
    system = build_system(frames, macro)
    agent = FixedTransformerMultiAgentSystem()
    (s1, s2), = sorted(system.spread_data)[:1]
    state = system.get_pair_state(s1, s2)
    stats = {'correlation': 0.8, 'half_life': 8.0, 'quality_score': 0.8}
    for i in (120, 400, len(state) - 30):
        as_of = state.index[i]
        full = agent.extract_advanced_features(
            state['spread'].iloc[:i + 1], stats, system.processed_data[s1], system.processed_data[s2],
            macro_data=system.macro_data, symbol1=s1, symbol2=s2)
        cut = agent.extract_advanced_features(
            state['spread'].iloc[:i + 1], stats,
            system.processed_data[s1].loc[:as_of], system.processed_data[s2].loc[:as_of],
            macro_data=_cut_macro(system.macro_data, as_of.tz_localize(None).normalize()),
            symbol1=s1, symbol2=s2)
        np.testing.assert_array_equal(full, cut)
        # indices 10-15: [RSI/100, Momentum_5, High_Vol_Regime] for each leg; the neutral
        # fallback (stock data unusable) is [0.5, 0, 0] per leg
        assert not np.allclose(full[10:16], [0.5, 0, 0, 0.5, 0, 0]), "per-stock block must be live"
