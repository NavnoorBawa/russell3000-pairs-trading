"""
Russell 3000 statistical-arbitrage research system.

A cointegration / Kalman-filter pairs strategy (Engle-Granger selection, beta-locked
z-score signals, t+1 fills, daily mark-to-market accounting) with walk-forward
validation, significance tests, baseline benchmarks and a fund-cost replay. A
transformer-encoder scorer only ranks candidate entries; its measured contribution is
~0. Entry point: `python -m pairs_trading.main`.

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
- json_export.py: JSON exports, run provenance and the headline-metrics snapshot
- plotting.py: charts written to outputs/
- main.py: command-line entry point
"""

from pairs_trading.trading_system import CompleteFixedRussell3000TradingSystem
from pairs_trading.data_processor import EnhancedRussell3000DataProcessor
from pairs_trading.pair_selector import FixedPrimeFundPairSelector
from pairs_trading.transformer_agent import TransformerEnhancedTradingAgent
from pairs_trading.multi_agent_system import FixedTransformerMultiAgentSystem
from pairs_trading.position_sizer import FixedPrimeFundPositionSizer
from pairs_trading.risk_manager import FixedPrimeFundRiskManager
from pairs_trading.transaction_costs import EnhancedPrimeFundTransactionCostModel
from pairs_trading.transformer_encoder import (
    PositionalEncoding,
    TransformerEncoderLayer,
    FinancialTransformerEncoder
)
from pairs_trading.json_export import (
    export_testing_results_to_json,
    export_fund_comparison_to_json,
    export_headline_metrics,
    build_run_config,
)
from pairs_trading.plotting import plot_ranker_training, plot_results, plot_fund_comparison
# Deprecated alias, importable for backward compatibility but no longer advertised in
# __all__: the RL training loop it used to plot does not exist (see plotting.py).
from pairs_trading.plotting import plot_training_results

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
