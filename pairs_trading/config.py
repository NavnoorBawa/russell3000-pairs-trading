"""
TRANSFORMER ENCODER FOR PAIRS TRADING - CONFIGURATION
======================================================
All imports, logging setup, and shared constants.
DO NOT MODIFY ANY PARAMETERS IN THIS FILE.
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
import time
import logging
import random
import pickle
import os
import gc
import json
from typing import Dict, List, Tuple, Optional, Union
from datetime import datetime, timedelta
from scipy.stats import zscore, skew, kurtosis
from scipy import optimize, stats
from sklearn.preprocessing import StandardScaler, RobustScaler
from sklearn.decomposition import PCA
import concurrent.futures
from threading import Lock
import sys
from requests.exceptions import HTTPError
from statsmodels.tsa.stattools import coint, adfuller
from statsmodels.tsa.api import VAR
from tqdm import tqdm
import matplotlib.pyplot as plt
import seaborn as sns

# Deep Learning and RL imports
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from collections import deque, namedtuple
import math
import itertools

# Suppress warnings
warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Sector ETF mapping — ticker → sector ETF symbol (GICS classification)
SECTOR_MAP = {
    # Technology → XLK
    'AAPL': 'XLK', 'MSFT': 'XLK', 'NVDA': 'XLK', 'AVGO': 'XLK', 'ORCL': 'XLK',
    'CRM': 'XLK', 'ADBE': 'XLK', 'NOW': 'XLK', 'INTC': 'XLK', 'AMD': 'XLK',
    'QCOM': 'XLK', 'TXN': 'XLK', 'MU': 'XLK', 'AMAT': 'XLK', 'LRCX': 'XLK',
    'MRVL': 'XLK', 'ADI': 'XLK', 'KLAC': 'XLK', 'CDNS': 'XLK', 'SNPS': 'XLK',
    'FTNT': 'XLK', 'TEAM': 'XLK', 'WDAY': 'XLK', 'DDOG': 'XLK', 'CRWD': 'XLK',
    'ZS': 'XLK', 'NET': 'XLK', 'SNOW': 'XLK', 'PLTR': 'XLK', 'OKTA': 'XLK',
    'ZM': 'XLK', 'DOCU': 'XLK', 'TWLO': 'XLK', 'MCHP': 'XLK', 'HPE': 'XLK',
    'IBM': 'XLK', 'ACN': 'XLK', 'CSCO': 'XLK', 'INTU': 'XLK', 'ADP': 'XLK',
    'TOST': 'XLK', 'GTLB': 'XLK', 'MDB': 'XLK', 'HUBS': 'XLK', 'COUP': 'XLK',
    # Communication Services → XLC
    'GOOGL': 'XLC', 'GOOG': 'XLC', 'META': 'XLC', 'NFLX': 'XLC', 'DIS': 'XLC',
    'CMCSA': 'XLC', 'T': 'XLC', 'VZ': 'XLC', 'CHTR': 'XLC', 'TMUS': 'XLC',
    'TTWO': 'XLC', 'EA': 'XLC', 'MTCH': 'XLC', 'PINS': 'XLC', 'SNAP': 'XLC',
    # Financials → XLF
    'JPM': 'XLF', 'BAC': 'XLF', 'WFC': 'XLF', 'GS': 'XLF', 'MS': 'XLF',
    'C': 'XLF', 'AXP': 'XLF', 'BLK': 'XLF', 'SCHW': 'XLF', 'SPGI': 'XLF',
    'MCO': 'XLF', 'CME': 'XLF', 'ICE': 'XLF', 'NDAQ': 'XLF', 'CBOE': 'XLF',
    'COF': 'XLF', 'DFS': 'XLF', 'SYF': 'XLF', 'TROW': 'XLF', 'BEN': 'XLF',
    'PNC': 'XLF', 'USB': 'XLF', 'TFC': 'XLF', 'MTB': 'XLF', 'FITB': 'XLF',
    'HBAN': 'XLF', 'RF': 'XLF', 'KEY': 'XLF', 'CFG': 'XLF', 'ZION': 'XLF',
    'WRB': 'XLF', 'AON': 'XLF', 'MMC': 'XLF', 'AJG': 'XLF', 'BRO': 'XLF',
    'PGR': 'XLF', 'TRV': 'XLF', 'ALL': 'XLF', 'AIG': 'XLF', 'MET': 'XLF',
    'PRU': 'XLF', 'SFG': 'XLF', 'CINF': 'XLF', 'WTW': 'XLF',
    # Healthcare → XLV
    'UNH': 'XLV', 'JNJ': 'XLV', 'PFE': 'XLV', 'ABT': 'XLV', 'TMO': 'XLV',
    'DHR': 'XLV', 'MRK': 'XLV', 'ABBV': 'XLV', 'LLY': 'XLV', 'BMY': 'XLV',
    'AMGN': 'XLV', 'GILD': 'XLV', 'VRTX': 'XLV', 'REGN': 'XLV', 'BIIB': 'XLV',
    'ILMN': 'XLV', 'MRNA': 'XLV', 'BNTX': 'XLV', 'ZTS': 'XLV', 'ELV': 'XLV',
    'CVS': 'XLV', 'CI': 'XLV', 'HUM': 'XLV', 'VEEV': 'XLV', 'ISRG': 'XLV',
    'SYK': 'XLV', 'BSX': 'XLV', 'MDT': 'XLV', 'EW': 'XLV', 'HOLX': 'XLV',
    'RMD': 'XLV', 'IQV': 'XLV', 'DXCM': 'XLV', 'ALGN': 'XLV', 'IDXX': 'XLV',
    'MTD': 'XLV', 'MOH': 'XLV', 'CNC': 'XLV', 'AAMI': 'XLV',
    # Consumer Discretionary → XLY
    'AMZN': 'XLY', 'TSLA': 'XLY', 'HD': 'XLY', 'MCD': 'XLY', 'NKE': 'XLY',
    'SBUX': 'XLY', 'LOW': 'XLY', 'TJX': 'XLY', 'TGT': 'XLY', 'LULU': 'XLY',
    'EBAY': 'XLY', 'ETSY': 'XLY', 'CHWY': 'XLY', 'BBY': 'XLY', 'MAT': 'XLY',
    'GPS': 'XLY', 'M': 'XLY', 'KSS': 'XLY', 'JWN': 'XLY', 'MGM': 'XLY',
    'WYNN': 'XLY', 'LVS': 'XLY', 'RCL': 'XLY', 'CCL': 'XLY', 'NCLH': 'XLY',
    'UBER': 'XLY', 'LYFT': 'XLY', 'ABNB': 'XLY', 'BKNG': 'XLY', 'EXPE': 'XLY',
    'AAL': 'XLY', 'DAL': 'XLY', 'UAL': 'XLY', 'LUV': 'XLY', 'JBLU': 'XLY',
    'GT': 'XLY', 'F': 'XLY', 'GM': 'XLY', 'RIVN': 'XLY', 'LCID': 'XLY',
    'DRI': 'XLY', 'YUM': 'XLY', 'CMG': 'XLY', 'QSR': 'XLY',
    # Consumer Staples → XLP
    'WMT': 'XLP', 'COST': 'XLP', 'PG': 'XLP', 'KO': 'XLP', 'PEP': 'XLP',
    'PM': 'XLP', 'MO': 'XLP', 'MDLZ': 'XLP', 'KHC': 'XLP', 'GIS': 'XLP',
    'K': 'XLP', 'HRL': 'XLP', 'CPB': 'XLP', 'SJM': 'XLP', 'CAG': 'XLP',
    'CLX': 'XLP', 'CHD': 'XLP', 'CL': 'XLP', 'KR': 'XLP', 'SFM': 'XLP',
    # Energy → XLE
    'XOM': 'XLE', 'CVX': 'XLE', 'COP': 'XLE', 'EOG': 'XLE', 'SLB': 'XLE',
    'MPC': 'XLE', 'PSX': 'XLE', 'VLO': 'XLE', 'OXY': 'XLE', 'DVN': 'XLE',
    'PXD': 'XLE', 'HAL': 'XLE', 'BKR': 'XLE', 'FANG': 'XLE', 'CTRA': 'XLE',
    'APA': 'XLE', 'MRO': 'XLE', 'HES': 'XLE', 'TRGP': 'XLE', 'KMI': 'XLE',
    # Industrials → XLI
    'HON': 'XLI', 'UPS': 'XLI', 'RTX': 'XLI', 'LMT': 'XLI', 'BA': 'XLI',
    'GE': 'XLI', 'CAT': 'XLI', 'DE': 'XLI', 'EMR': 'XLI', 'MMM': 'XLI',
    'TT': 'XLI', 'CARR': 'XLI', 'OTIS': 'XLI', 'PCAR': 'XLI', 'URI': 'XLI',
    'FAST': 'XLI', 'ARMK': 'XLI', 'FDX': 'XLI', 'CSX': 'XLI', 'UNP': 'XLI',
    'NSC': 'XLI', 'JCI': 'XLI', 'GD': 'XLI', 'NOC': 'XLI', 'HII': 'XLI',
    'ETN': 'XLI', 'PH': 'XLI', 'ROK': 'XLI', 'AME': 'XLI', 'VRSK': 'XLI',
    'LDOS': 'XLI', 'SAIC': 'XLI', 'CACI': 'XLI', 'MDU': 'XLI',
    # Materials → XLB
    'LIN': 'XLB', 'APD': 'XLB', 'ECL': 'XLB', 'SHW': 'XLB', 'PPG': 'XLB',
    'NEM': 'XLB', 'FCX': 'XLB', 'NUE': 'XLB', 'STLD': 'XLB', 'RS': 'XLB',
    'CF': 'XLB', 'MOS': 'XLB', 'ALB': 'XLB', 'LYB': 'XLB', 'CE': 'XLB',
    # Utilities → XLU
    'NEE': 'XLU', 'DUK': 'XLU', 'SO': 'XLU', 'D': 'XLU', 'AEP': 'XLU',
    'EXC': 'XLU', 'SRE': 'XLU', 'XEL': 'XLU', 'PCG': 'XLU', 'ED': 'XLU',
    'WEC': 'XLU', 'ES': 'XLU', 'CMS': 'XLU', 'EVRG': 'XLU', 'CNP': 'XLU',
    'AES': 'XLU', 'AWK': 'XLU', 'NI': 'XLU', 'PNW': 'XLU',
    # Real Estate → XLRE
    'AMT': 'XLRE', 'PLD': 'XLRE', 'CCI': 'XLRE', 'EQIX': 'XLRE', 'DLR': 'XLRE',
    'SPG': 'XLRE', 'O': 'XLRE', 'WELL': 'XLRE', 'VTR': 'XLRE', 'EQR': 'XLRE',
    'AVB': 'XLRE', 'MAC': 'XLRE', 'SUI': 'XLRE', 'ELS': 'XLRE', 'UDR': 'XLRE',
    'HST': 'XLRE', 'BXP': 'XLRE', 'KIM': 'XLRE', 'REG': 'XLRE', 'FRT': 'XLRE',
}

SECTOR_ETFS = ['XLK', 'XLC', 'XLF', 'XLV', 'XLY', 'XLP', 'XLE', 'XLI', 'XLB', 'XLU', 'XLRE']
MACRO_TICKERS = ['^VIX'] + SECTOR_ETFS

# Default metrics for plotting
DEFAULT_METRICS = {
    'total_return': 0.0,
    'sharpe_ratio': 0.0,
    'max_drawdown': 0.0,
    'win_rate': 0.0,
    'profit_factor': 0.0,
    'total_trades': 0
}
