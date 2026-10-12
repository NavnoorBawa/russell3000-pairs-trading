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
