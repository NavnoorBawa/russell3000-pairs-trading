"""
Diagnostic script to find where dates get lost in the pipeline
"""
import pickle
import pandas as pd
import numpy as np
from pairs_trading.data_processor import EnhancedRussell3000DataProcessor
from pairs_trading.pair_selector import FixedPrimeFundPairSelector

print("="*80)
print("DIAGNOSING DATE LOSS IN PAIRS TRADING PIPELINE")
print("="*80)

# Step 1: Check raw data
print("\n1. RAW DATA CHECK:")
with open('enhanced_russell_3000_data.pkl', 'rb') as f:
    data = pickle.load(f)

max_dates = []
for df in data.values():
    if len(df) > 0:
        max_dates.append(df.index.max())

overall_max = max(max_dates)
print(f"   - Total symbols: {len(data)}")
print(f"   - Latest date in raw data: {overall_max.strftime('%Y-%m-%d')}")

# Step 2: Check pair selection
print("\n2. PAIR SELECTION CHECK:")
pair_selector = FixedPrimeFundPairSelector()
selected_pairs = pair_selector.find_quality_pairs(data, max_pairs=30)
print(f"   - Pairs selected: {len(selected_pairs)}")

if len(selected_pairs) > 0:
    print(f"   - First 5 pairs: {selected_pairs[:5]}")

# Step 3: Check spreads for selected pairs
print("\n3. SPREAD CALCULATION CHECK:")
spreads = {}

for pair in selected_pairs[:10]:  # Check first 10 pairs
    symbol1, symbol2 = pair
    if symbol1 in data and symbol2 in data:
        data1 = data[symbol1]
        data2 = data[symbol2]

        # Calculate spread (simplified version)
        common_dates = data1.index.intersection(data2.index)
        if len(common_dates) >= 100:
            prices1 = data1.loc[common_dates, 'Close']
            prices2 = data2.loc[common_dates, 'Close']

            # Fill NaNs
            prices1 = prices1.fillna(method='ffill').fillna(method='bfill')
            prices2 = prices2.fillna(method='ffill').fillna(method='bfill')

            spread = np.log(prices1 + 1e-8) - np.log(prices2 + 1e-8)
            spread = spread.dropna()

            spreads[pair] = spread

            print(f"   - {symbol1}-{symbol2}: {len(spread)} days, "
                  f"{spread.index.min().strftime('%Y-%m-%d')} to {spread.index.max().strftime('%Y-%m-%d')}")

# Step 4: Check train/test split
print("\n4. TRAIN/TEST SPLIT CHECK:")
train_end_date = pd.Timestamp('2022-12-31')
test_start_date = pd.Timestamp('2023-01-01')

test_spreads = {}
for pair_key, spread in spreads.items():
    try:
        # Handle timezone
        if hasattr(spread.index, 'tz') and spread.index.tz is not None:
            test_start_tz = test_start_date.tz_localize(spread.index.tz)
            test_mask = spread.index >= test_start_tz
        else:
            test_mask = spread.index >= test_start_date

        test_spread = spread[test_mask]

        if len(test_spread) >= 50:
            test_spreads[pair_key] = test_spread
            symbol1, symbol2 = pair_key
            print(f"   - {symbol1}-{symbol2} test spread: {len(test_spread)} days, "
                  f"{test_spread.index.min().strftime('%Y-%m-%d')} to {test_spread.index.max().strftime('%Y-%m-%d')}")
    except Exception as e:
        symbol1, symbol2 = pair_key
        print(f"   - {symbol1}-{symbol2} ERROR: {str(e)}")

# Step 5: Check backtest date range
print("\n5. BACKTEST DATE RANGE:")
if len(test_spreads) > 0:
    all_dates = set()
    for spread in test_spreads.values():
        all_dates.update(spread.index)
    all_dates = sorted(list(all_dates))

    print(f"   - Total unique dates for backtest: {len(all_dates)}")
    print(f"   - First date: {all_dates[0].strftime('%Y-%m-%d')}")
    print(f"   - Last date: {all_dates[-1].strftime('%Y-%m-%d')}")

    # Check date gaps
    if len(all_dates) > 1:
        gap_days = (all_dates[-1] - all_dates[0]).days
        print(f"   - Calendar days span: {gap_days}")
        print(f"   - Trading days: {len(all_dates)}")
else:
    print("   - ERROR: No test spreads generated!")

print("\n" + "="*80)
print("DIAGNOSIS COMPLETE")
print("="*80)
