"""
TRANSFORMER ENCODER FOR PAIRS TRADING
======================================
Root-level runner script.

Usage:
    python run_trading_system.py

This script adds the current directory to the Python path and runs the trading system.
"""

import sys
import os

# Add current directory to path so pairs_trading package can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pairs_trading.main import main

if __name__ == "__main__":
    main()
