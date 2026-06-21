"""Smoke tests: every module imports, and the core classes instantiate.

Catches the class of breakage that matters most in a research codebase — an import
error or a broken __init__ that takes the whole pipeline down.
"""
import importlib
import pytest

MODULES = [
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
    "pairs_trading.main",
]


@pytest.mark.parametrize("mod", MODULES)
def test_module_imports(mod):
    importlib.import_module(mod)


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
    assert agent.state_dim == 38                 # documented feature count


def test_fund_profiles_well_formed():
    from pairs_trading.fund_profiles import FUND_PROFILES
    assert len(FUND_PROFILES) == 5
    for p in FUND_PROFILES.values():
        assert p.base_position_pct > 0
        assert p.max_position_pct >= p.base_position_pct
        assert p.max_drawdown_limit > 0
