"""Check why the backtest stopped on June 1, 2023"""
import json

with open('pairs_trading_results_2023_2025_compact.json', 'r') as f:
    results = json.load(f)

daily_curve = results['daily_equity_curve']

print("="*80)
print("CHECKING BACKTEST STOP REASON")
print("="*80)

# Find last 10 days of trading
print("\nLAST 15 DAYS OF BACKTEST:")
print(f"{'Date':<12} {'Daily Ret %':>12} {'Cumul Ret %':>12} {'Drawdown %':>12}")
print("-"*52)

last_days = daily_curve[-15:]
for day in last_days:
    print(f"{day['date']:<12} {day['daily_return_pct']:>12.4f} "
          f"{day['cumulative_return_pct']:>12.2f} {day['drawdown_pct']:>12.2f}")

# Count consecutive losing days before June 1
print("\n" + "="*80)
print("CONSECUTIVE LOSING DAY ANALYSIS:")
print("="*80)

losing_threshold = -0.008  # -0.8% from risk_manager.py line 95
consecutive_count = 0
max_consecutive = 0

for i in range(len(daily_curve) - 1, -1, -1):
    day = daily_curve[i]
    daily_pnl = day['daily_return_pct'] / 100  # Convert to decimal

    if daily_pnl < losing_threshold:
        consecutive_count += 1
        max_consecutive = max(max_consecutive, consecutive_count)
        if consecutive_count <= 10:  # Show first 10
            print(f"{day['date']}: PnL={daily_pnl:.4f} (losing day #{consecutive_count})")
    else:
        if consecutive_count > 0:
            print(f"{day['date']}: PnL={daily_pnl:.4f} (BREAK)")
            break
        consecutive_count = 0

print(f"\nConsecutive losing days at end: {consecutive_count}")
print(f"Risk manager threshold: 5 days")
print(f"Would stop trading: {consecutive_count >= 5}")

# Also check the drawdown
print("\n" + "="*80)
print("DRAWDOWN ANALYSIS:")
print("="*80)
final_drawdown = daily_curve[-1]['drawdown_pct']
print(f"Final drawdown: {final_drawdown:.2f}%")
print(f"Max allowed: -10.0% (from risk_manager.py line 23)")
print(f"Would stop trading: {final_drawdown <= -10.0}")

print("\n" + "="*80)
