"""Find when consecutive_losing_days actually hit 5"""
import json

with open('pairs_trading_results_2023_2025_compact.json', 'r') as f:
    results = json.load(f)

daily_curve = results['daily_equity_curve']

print("="*80)
print("FINDING ACTUAL STOP CONDITION")
print("="*80)
print("\nRisk Manager Logic:")
print("  - Increment counter if daily_pnl < -0.008 (-0.8%)")
print("  - Reset counter if daily_pnl > 0.003 (+0.3%)")
print("  - Otherwise: counter stays the same")
print("  - Stop trading if counter >= 5")
print("="*80)

consecutive_losing_days = 0
stop_day = None

for i, day in enumerate(daily_curve):
    daily_pnl = day['daily_return_pct'] / 100  # Convert to decimal
    prev_count = consecutive_losing_days

    if daily_pnl < -0.008:
        consecutive_losing_days += 1
        status = "LOSING"
    elif daily_pnl > 0.003:
        consecutive_losing_days = 0
        status = "RESET"
    else:
        status = "NEUTRAL"

    # Show days where counter is elevated or changes
    if consecutive_losing_days > 0 or prev_count > 0:
        print(f"Day {i+1:3d} {day['date']}: PnL={daily_pnl:>8.4f} | "
              f"Counter: {prev_count} → {consecutive_losing_days} | {status}")

    if consecutive_losing_days >= 5 and stop_day is None:
        stop_day = i + 1
        print(f"\n{'='*80}")
        print(f"🚨 STOP CONDITION TRIGGERED ON DAY {stop_day} ({day['date']})")
        print(f"{'='*80}\n")
        # Show a few more days to confirm
        continue

    if stop_day and i >= stop_day + 3:
        break

if stop_day:
    print(f"\nBacktest should have stopped on day {stop_day}")
    print(f"Actual last day in equity curve: day {len(daily_curve)} ({daily_curve[-1]['date']})")
else:
    print("\n⚠️  Stop condition was NEVER triggered!")
    print(f"Final consecutive_losing_days count: {consecutive_losing_days}")
    print(f"This suggests the backtest ended for another reason.")

print("\n" + "="*80)
