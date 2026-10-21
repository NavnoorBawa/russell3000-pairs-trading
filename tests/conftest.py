"""Hermetic test environment.

Every run-time switch of the pipeline is a PAIRS_* environment variable (PAIRS_FILL,
PAIRS_USE_TRANSFORMER, PAIRS_RESELECT, PAIRS_SEED, ...). A value exported in the shell
that runs pytest (e.g. `PAIRS_FILL=open pytest`) used to change what the tests
exercised, and a test that set one leaked it into every later test. The session starts
with none of them set, and each test's changes are undone when it finishes.

The engine, leakage and pipeline tests were written against the v32 design (regime gate
on, pool re-selection, transformer ranker), so the session runs with PAIRS_PROFILE=v32;
the v33 profile is exercised by tests that ask for it explicitly (test_study_config.py,
test_v33_*.py). Either way the profile is pinned: a shell's PAIRS_PROFILE cannot leak in.
"""
import os

import pytest


def _pairs_env():
    return {k: v for k, v in os.environ.items() if k.startswith('PAIRS_')}


def _restore(snapshot):
    for k in list(os.environ):
        if k.startswith('PAIRS_') and k not in snapshot:
            del os.environ[k]
    os.environ.update(snapshot)


@pytest.fixture(scope='session', autouse=True)
def _no_inherited_pairs_switches():
    saved = _pairs_env()
    _restore({'PAIRS_PROFILE': 'v32'})
    yield
    _restore(saved)


@pytest.fixture(autouse=True)
def _pairs_switches_do_not_leak_between_tests():
    saved = _pairs_env()
    yield
    _restore(saved)


@pytest.fixture(autouse=True)
def _no_fetch_retry_pause(monkeypatch):
    """The data processor waits before retrying transient fetch failures; tests do not."""
    from pairs_trading.data_processor import EnhancedRussell3000DataProcessor
    monkeypatch.setattr(EnhancedRussell3000DataProcessor, 'TRANSIENT_RETRY_PAUSE', 0.0)
