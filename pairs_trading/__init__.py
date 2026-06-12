"""
TRANSFORMER ENCODER FOR PAIRS TRADING
======================================
Research Paper Implementation - Modular Package Structure

This package contains the complete implementation split into logical modules:

- config.py: All imports, logging, and constants
- json_export.py: JSON export functions for website display
- transformer_encoder.py: Transformer architecture classes
- transaction_costs.py: Transaction cost model
- data_processor.py: Russell 3000 data processing
- pair_selector.py: Pair selection and cointegration testing
- transformer_agent.py: Transformer trading agent
- multi_agent_system.py: Multi-agent RL system
- position_sizer.py: Position sizing logic
- risk_manager.py: Risk management
- plotting.py: Visualization functions
- trading_system.py: Main trading system orchestration

DO NOT MODIFY ANY PARAMETERS IN ANY FILE.
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
from pairs_trading.json_export import export_testing_results_to_json
from pairs_trading.plotting import plot_training_results, plot_results

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
    'plot_training_results',
    'plot_results'
]
