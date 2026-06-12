"""Trace a single pair through the entire pipeline"""
import pickle
import pandas as pd
import numpy as np

print("="*80)
print("TRACING PAIR AAL-GT THROUGH ENTIRE PIPELINE")
print("="*80)

# Load raw data
with open('enhanced_russell_3000_data.pkl', 'rb') as f:
    raw_data = pickle.load(f)

symbol1, symbol2 = 'AAL', 'GT'
data1 = raw_data[symbol1]
data2 = raw_data[symbol2]

print(f"\n1. RAW DATA:")
print(f"   {symbol1}: {data1.index.min().strftime('%Y-%m-%d')} to {data1.index.max().strftime('%Y-%m-%d')} ({len(data1)} days)")
print(f"   {symbol2}: {data2.index.min().strftime('%Y-%m-%d')} to {data2.index.max().strftime('%Y-%m-%d')} ({len(data2)} days)")

# Calculate spread
common_dates = data1.index.intersection(data2.index)
print(f"\n2. COMMON DATES:")
print(f"   Count: {len(common_dates)}")
print(f"   Range: {common_dates.min().strftime('%Y-%m-%d')} to {common_dates.max().strftime('%Y-%m-%d')}")

prices1 = data1.loc[common_dates, 'Close']
prices2 = data2.loc[common_dates, 'Close']

# Check for nulls
nulls1_before = prices1.isnull().sum()
nulls2_before = prices2.isnull().sum()
print(f"   Nulls before fillna: {symbol1}={nulls1_before}, {symbol2}={nulls2_before}")

# Fill NaNs
prices1_filled = prices1.fillna(method='ffill').fillna(method='bfill')
prices2_filled = prices2.fillna(method='ffill').fillna(method='bfill')

nulls1_after = prices1_filled.isnull().sum()
nulls2_after = prices2_filled.isnull().sum()
print(f"   Nulls after fillna: {symbol1}={nulls1_after}, {symbol2}={nulls2_after}")

# Calculate spread
spread = np.log(prices1_filled + 1e-8) - np.log(prices2_filled + 1e-8)
print(f"\n3. SPREAD CALCULATION:")
print(f"   Spread length before dropna: {len(spread)}")

spread_clean = spread.dropna()
print(f"   Spread length after dropna: {len(spread_clean)}")
print(f"   Spread range: {spread_clean.index.min().strftime('%Y-%m-%d')} to {spread_clean.index.max().strftime('%Y-%m-%d')}")

# Train/test split
train_end_date = pd.Timestamp('2022-12-31')
test_start_date = pd.Timestamp('2023-01-01')

print(f"\n4. TRAIN/TEST SPLIT:")
print(f"   Train end: {train_end_date.strftime('%Y-%m-%d')}")
print(f"   Test start: {test_start_date.strftime('%Y-%m-%d')}")

# Handle timezone
if hasattr(spread_clean.index, 'tz') and spread_clean.index.tz is not None:
    print(f"   Spread has timezone: {spread_clean.index.tz}")
    train_end_tz = train_end_date.tz_localize(spread_clean.index.tz)
    test_start_tz = test_start_date.tz_localize(spread_clean.index.tz)
    train_mask = spread_clean.index <= train_end_tz
    test_mask = spread_clean.index >= test_start_tz
else:
    print(f"   Spread is timezone-naive")
    train_mask = spread_clean.index <= train_end_date
    test_mask = spread_clean.index >= test_start_date

train_spread = spread_clean[train_mask]
test_spread = spread_clean[test_mask]

print(f"\n5. SPLIT RESULTS:")
print(f"   Train spread: {len(train_spread)} days")
if len(train_spread) > 0:
    print(f"     Range: {train_spread.index.min().strftime('%Y-%m-%d')} to {train_spread.index.max().strftime('%Y-%m-%d')}")

print(f"   Test spread: {len(test_spread)} days")
if len(test_spread) > 0:
    print(f"     Range: {test_spread.index.min().strftime('%Y-%m-%d')} to {test_spread.index.max().strftime('%Y-%m-%d')}")

# Check specific dates
june_2023 = pd.Timestamp('2023-06-01')
dec_2025 = pd.Timestamp('2025-12-01')

if hasattr(test_spread.index, 'tz') and test_spread.index.tz is not None:
    june_2023_tz = june_2023.tz_localize(test_spread.index.tz)
    dec_2025_tz = dec_2025.tz_localize(test_spread.index.tz)
    in_june = june_2023_tz in test_spread.index
    in_dec = dec_2025_tz in test_spread.index
else:
    in_june = june_2023 in test_spread.index
    in_dec = dec_2025 in test_spread.index

print(f"\n6. SPECIFIC DATE CHECKS:")
print(f"   2023-06-01 in test_spread: {in_june}")
print(f"   2025-12-01 in test_spread: {in_dec}")

# Sample some dates from test spread
print(f"\n7. SAMPLE TEST SPREAD DATES:")
sample_dates = test_spread.index[::100]  # Every 100th date
for date in sample_dates[:10]:
    print(f"   {date.strftime('%Y-%m-%d')}: spread = {test_spread.loc[date]:.4f}")

print("\n" + "="*80)
