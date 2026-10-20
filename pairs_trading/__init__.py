"""
Russell 3000 statistical-arbitrage research system.

A cointegration / Kalman-filter pairs strategy (Engle-Granger selection, beta-locked
z-score signals, t+1 fills, daily mark-to-market accounting) with walk-forward
validation, significance tests, baseline benchmarks and a fund-cost replay. A
transformer-encoder scorer only ranks candidate entries (v31.1 measured its contribution
at exactly 0; v32 reports its out-of-sample AUC). Entry point: `python -m pairs_trading.main`.

Modules:

- config.py: shared imports, constants and the CLI's runtime setup
- data_processor.py: Russell 3000 price/indicator data and macro series
- pair_selector.py: cointegration pair selection (+ Benjamini-Hochberg FDR diagnostic)
- trading_system.py: backtest engine, walk-forward, fund-cost replay, orchestration
- transaction_costs.py / fund_profiles.py: cost model and the five fund profiles
- position_sizer.py / risk_manager.py: sizing and risk limits
- multi_agent_system.py: feature assembly + transformer ranking (NOT reinforcement
  learning — no policy network or value function exists)
- transformer_encoder.py / transformer_agent.py: the ranking model
- significance.py / benchmark.py: "is the edge real?" tests and baselines
- residual_statarb.py: a second strategy family, Avellaneda-Lee (2010) sector-ETF
  residual mean reversion (scripts/run_residual_statarb.py runs it on the study data)
- json_export.py: JSON exports, run provenance and the headline-metrics snapshot
- plotting.py: charts written to outputs/
- main.py: command-line entry point
"""

import importlib

# v32: names are resolved lazily (PEP 562). Importing any submodule — e.g. the cost model
# or the significance tests — no longer imports torch, matplotlib and yfinance via an
# eager package __init__.
_EXPORTS = {
    'CompleteFixedRussell3000TradingSystem': 'pairs_trading.trading_system',
    'EnhancedRussell3000DataProcessor': 'pairs_trading.data_processor',
    'FixedPrimeFundPairSelector': 'pairs_trading.pair_selector',
    'TransformerEnhancedTradingAgent': 'pairs_trading.transformer_agent',
    'FixedTransformerMultiAgentSystem': 'pairs_trading.multi_agent_system',
    'FixedPrimeFundPositionSizer': 'pairs_trading.position_sizer',
    'FixedPrimeFundRiskManager': 'pairs_trading.risk_manager',
    'EnhancedPrimeFundTransactionCostModel': 'pairs_trading.transaction_costs',
    'PositionalEncoding': 'pairs_trading.transformer_encoder',
    'TransformerEncoderLayer': 'pairs_trading.transformer_encoder',
    'FinancialTransformerEncoder': 'pairs_trading.transformer_encoder',
    'export_testing_results_to_json': 'pairs_trading.json_export',
    'export_fund_comparison_to_json': 'pairs_trading.json_export',
    'export_headline_metrics': 'pairs_trading.json_export',
    'build_run_config': 'pairs_trading.json_export',
    'plot_ranker_training': 'pairs_trading.plotting',
    'plot_results': 'pairs_trading.plotting',
    'plot_fund_comparison': 'pairs_trading.plotting',
    # deprecated alias kept importable (not in __all__): the RL loop it plotted is gone
    'plot_training_results': 'pairs_trading.plotting',
}


def __getattr__(name):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_EXPORTS))


__all__ = [
    'CompleteFixedRussell3000TradingSystem',
    'EnhancedRussell3000DataProcessor',
    'FixedPrimeFundPairSelector',
    'TransformerEnhancedTradingAgent',
    'FixedTransformerMultiAgentSystem',
    'FixedPrimeFundPositionSizer',
    'FixedPrimeFundRiskManager',
    'EnhancedPrimeFundTransactionCostModel',
    'PositionalEncoding',
    'TransformerEncoderLayer',
    'FinancialTransformerEncoder',
    'export_testing_results_to_json',
    'export_fund_comparison_to_json',
    'export_headline_metrics',
    'build_run_config',
    'plot_ranker_training',
    'plot_results',
    'plot_fund_comparison',
]
