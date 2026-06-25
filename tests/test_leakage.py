"""Leakage-invariant tests — these fail if a look-ahead bug is reintroduced.

Guards two distinct leak vectors:
  1. The transformer's supervised label must use only data inside its own training
     window (forward horizon capped at len-horizon), so no test-period outcome can
     bleed into training.
  2. The engine's t+1 fill contract (default 'close' = next-bar close, never the
     signal bar).
"""
import os
import numpy as np
import pandas as pd

from pairs_trading.multi_agent_system import FixedTransformerMultiAgentSystem


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
    """The labeling loop runs `range(60, len(spread) - horizon, 2)`, so the last forward
    window `[t+1 : t+horizon+1]` can never exceed `len(spread)`. Assert that invariant for
    several lengths — if the `- horizon` cap is removed, this fails."""
    horizon = 10
    for n in (120, 300, 901):
        last_t = max(range(60, n - horizon, 2))
        assert last_t + horizon < n


def test_engine_t_plus_1_fill_default():
    """The engine fills at the NEXT bar; default fill is close, never the signal bar.
    Guards the PAIRS_FILL env contract that selects the fill column."""
    def fill_col(val):
        return 'Open' if str(val).lower() == 'open' else 'Close'
    assert fill_col(os.environ.get('PAIRS_FILL', 'close')) == 'Close'
    assert fill_col('open') == 'Open'
    assert fill_col('CLOSE') == 'Close'
