"""Leakage-invariant tests — these fail if a look-ahead bug is reintroduced.

Guards two distinct leak vectors:
  1. The transformer's supervised label must use only data inside its own training
     window (forward horizon capped at len-horizon), so no test-period outcome can
     bleed into training.
  2. The engine's t+1 fill contract (default 'close' = next-bar close, never the
     signal bar).
"""
import inspect
import os

import numpy as np
import pandas as pd

from pairs_trading.multi_agent_system import FixedTransformerMultiAgentSystem
from pairs_trading.trading_system import CompleteFixedRussell3000TradingSystem


def _series(n, seed, phi=0.97):
    """Slow AR(1) (near-random-walk) so the exit-band label base rate is moderate
    (avoids the degeneracy guard) while still mean-reverting enough to be realistic."""
    r = np.random.default_rng(seed)
    s = np.zeros(n)
    for t in range(1, n):
        s[t] = phi * s[t - 1] + r.normal(0, 1.0)
    idx = pd.date_range("2021-01-04", periods=n, freq="B")
    return pd.Series(s, index=idx)


def test_outcome_labels_do_not_use_future_beyond_window():
    """Append 'future' data to a spread and rebuild the dataset; the labels for the
    samples that existed before the append MUST be unchanged. If a label ever read past
    its own window (e.g. someone fed test-spanning spreads or dropped the horizon cap),
    the appended future would change early labels and this fails. Single pair, so sample
    order is preserved and `ya` is a prefix of `yb`."""
    agent = FixedTransformerMultiAgentSystem()
    base = _series(1100, seed=1)
    extended = pd.concat([base, _series(200, seed=99)])
    extended.index = pd.date_range("2021-01-04", periods=len(extended), freq="B")

    # entry_z=0.0 -> every bar is a candidate, so one long pair clears the 400 minimum
    Xa, ya = agent._build_outcome_dataset({("A", "B"): base}, entry_z=0.0, max_samples=100_000)
    Xb, yb = agent._build_outcome_dataset({("A", "B"): extended}, entry_z=0.0, max_samples=100_000)
    assert ya is not None and yb is not None, "dataset too small/degenerate to test"
    assert len(yb) >= len(ya)
    assert np.array_equal(ya, yb[:len(ya)]), "future data changed earlier labels -> leak"


def test_outcome_horizon_cap_holds():
    """The labeling loop must stop `horizon` bars before the end of the spread, so the last
    forward window `[t+1 : t+horizon+1]` never runs past the data.

    v31.1 (audit): this test used to assert `max(range(60, n - horizon, 2)) + horizon < n`
    on plain literals — arithmetic about a copy of the loop bounds, which passes even if
    `_build_outcome_dataset` drops the cap entirely. Count the samples the REAL function
    emits instead: with the cap the count is bounded by `len(range(60, n - horizon, 2))`,
    and removing the cap pushes it above that bound."""
    agent = FixedTransformerMultiAgentSystem()
    horizon = 10
    for n_obs in (1100, 1500):
        spread = _series(n_obs, seed=3)
        _X, y = agent._build_outcome_dataset({("A", "B"): spread}, entry_z=0.0,
                                             max_samples=100_000)
        assert y is not None, "dataset too small/degenerate to test"
        cap = len(range(60, n_obs - horizon, 2))
        assert len(y) <= cap, (
            f"{len(y)} labels from {n_obs} observations exceeds the {cap} the forward-horizon "
            "cap allows — the labeler is reading past the end of the spread"
        )


def test_engine_t_plus_1_fill_default():
    """The default t+1 fill is the next bar's CLOSE; only PAIRS_FILL=open switches it.

    v31.1 (audit): this test used to define its own local `fill_col` copy and assert on
    that, so it would have passed even if the engine's fill selection were deleted. It now
    exercises `resolve_fill_column`, the function the engine itself calls."""
    from pairs_trading.trading_system import resolve_fill_column

    assert resolve_fill_column(os.environ.get('PAIRS_FILL', 'close')) == 'Close'
    assert resolve_fill_column('open') == 'Open'
    assert resolve_fill_column('OPEN') == 'Open'
    assert resolve_fill_column('CLOSE') == 'Close'
    assert resolve_fill_column('') == 'Close', "an empty PAIRS_FILL must not enable open fills"
    assert resolve_fill_column('opening') == 'Close', "only an exact 'open' switches the fill"

    src = inspect.getsource(CompleteFixedRussell3000TradingSystem.run_comprehensive_backtest)
    assert 'resolve_fill_column(' in src, (
        "the backtest no longer routes its fill column through resolve_fill_column, so this "
        "test would be asserting on a function the engine does not use"
    )
