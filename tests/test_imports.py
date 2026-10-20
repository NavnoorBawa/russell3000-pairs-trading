"""Smoke tests: every module imports, and the core classes instantiate.

Catches the class of breakage that matters most in a research codebase — an import
error or a broken __init__ that takes the whole pipeline down.
"""
import importlib
import pytest

MODULES = [
    "pairs_trading",
    "pairs_trading.config",
    "pairs_trading.data_processor",
    "pairs_trading.pair_selector",
    "pairs_trading.transformer_encoder",
    "pairs_trading.transformer_agent",
    "pairs_trading.multi_agent_system",
    "pairs_trading.position_sizer",
    "pairs_trading.risk_manager",
    "pairs_trading.transaction_costs",
    "pairs_trading.fund_profiles",
    "pairs_trading.significance",
    "pairs_trading.benchmark",
    "pairs_trading.json_export",
    "pairs_trading.plotting",
    "pairs_trading.trading_system",
    "pairs_trading.residual_statarb",
    "pairs_trading.main",
]


@pytest.mark.parametrize("mod", MODULES)
def test_module_imports(mod):
    importlib.import_module(mod)


def test_package_exports_resolve():
    pkg = importlib.import_module("pairs_trading")
    for name in pkg.__all__:
        assert getattr(pkg, name) is not None, name
    # v32: the ranker plot and the headline export are public; the RL-era plot is not
    assert "plot_ranker_training" in pkg.__all__
    assert "export_headline_metrics" in pkg.__all__
    assert "plot_training_results" not in pkg.__all__
    # ...but stays importable so old callers do not break
    from pairs_trading import plot_training_results  # noqa: F401


def test_dead_duplicate_metrics_helper_removed():
    plotting = importlib.import_module("pairs_trading.plotting")
    assert not hasattr(plotting, "calculate_performance_metrics")


def test_core_classes_instantiate():
    from pairs_trading.pair_selector import FixedPrimeFundPairSelector
    from pairs_trading.position_sizer import FixedPrimeFundPositionSizer
    from pairs_trading.risk_manager import FixedPrimeFundRiskManager
    from pairs_trading.transaction_costs import EnhancedPrimeFundTransactionCostModel
    from pairs_trading.multi_agent_system import FixedTransformerMultiAgentSystem

    assert FixedPrimeFundPairSelector() is not None
    assert FixedPrimeFundPositionSizer() is not None
    assert FixedPrimeFundRiskManager() is not None
    assert EnhancedPrimeFundTransactionCostModel() is not None
    agent = FixedTransformerMultiAgentSystem()
    # the feature vector length is owned by the class (it changed in v32); the default
    # model width must follow it rather than a number copied into this test
    assert agent.state_dim == FixedTransformerMultiAgentSystem.N_FEATURES


def test_fund_profiles_well_formed():
    from pairs_trading.fund_profiles import FUND_PROFILES
    assert len(FUND_PROFILES) == 5
    for p in FUND_PROFILES.values():
        assert p.base_position_pct > 0
        assert p.max_position_pct >= p.base_position_pct
        assert p.max_drawdown_limit > 0
