"""Quick diagnosis using existing results"""
import json
import pickle
import pandas as pd

print("="*80)
print("QUICK DIAGNOSIS: WHY DOES BACKTEST STOP ON JUNE 1, 2023?")
print("="*80)

# Load results to see what happened
with open('pairs_trading_results_2023_2025_compact.json', 'r') as f:
    results = json.load(f)

# Check equity curve dates
print("\n1. EQUITY CURVE DATES:")
daily_curve = results['daily_equity_curve']
print(f"   - First date: {daily_curve[0]['date']}")
print(f"   - Last date: {daily_curve[-1]['date']}")
print(f"   - Total days: {len(daily_curve)}")

# Check when trading started
non_zero_days = [d for d in daily_curve if d['daily_return_pct'] != 0]
print(f"\n2. TRADING ACTIVITY:")
print(f"   - Days with trades: {len(non_zero_days)}")
if non_zero_days:
    print(f"   - First trade: {non_zero_days[0]['date']}")
    print(f"   - Last trade: {non_zero_days[-1]['date']}")

# Load raw data and check top pairs
print("\n3. CHECKING TOP PERFORMING PAIRS:")
with open('enhanced_russell_3000_data.pkl', 'rb') as f:
    raw_data = pickle.load(f)

top_pairs = results['top_10_pairs'][:3]
for pair_info in top_pairs:
    pair_str = pair_info['pair']
    symbol1, symbol2 = pair_str.split('-')

    if symbol1 in raw_data and symbol2 in raw_data:
        data1 = raw_data[symbol1]
        data2 = raw_data[symbol2]

        print(f"\n   {pair_str}:")
        print(f"     - {symbol1}: {data1.index.min().strftime('%Y-%m-%d')} to {data1.index.max().strftime('%Y-%m-%d')} ({len(data1)} days)")
        print(f"     - {symbol2}: {data2.index.min().strftime('%Y-%m-%d')} to {data2.index.max().strftime('%Y-%m-%d')} ({len(data2)} days)")

        # Check common dates
        common = data1.index.intersection(data2.index)
        print(f"     - Common dates: {len(common)}, latest: {common.max().strftime('%Y-%m-%d')}")

        # Check for data quality issues after June 2023
        june_2023 = pd.Timestamp('2023-06-01')
        if hasattr(common, 'tz') and common.tz is not None:
            june_2023 = june_2023.tz_localize(common.tz)

        after_june = common[common > june_2023]
        print(f"     - Dates AFTER 2023-06-01: {len(after_june)}")

        if len(after_june) > 0:
            # Check for missing/null prices after June
            after_june_data1 = data1.loc[after_june, 'Close']
            after_june_data2 = data2.loc[after_june, 'Close']
            nulls1 = after_june_data1.isnull().sum()
            nulls2 = after_june_data2.isnull().sum()
            print(f"     - Null prices after June: {symbol1}={nulls1}, {symbol2}={nulls2}")

print("\n" + "="*80)
