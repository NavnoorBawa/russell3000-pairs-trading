#!/bin/bash
# Overnight monitor for v9 backtest
# Runs every 30 min, writes summary to v9_status.txt when done
# PID: 29523

LOG="/Users/navnoorbawa/Downloads/Transformet Notion/backtest_v9.log"
STATUS="/Users/navnoorbawa/Downloads/Transformet Notion/v9_status.txt"
PID=29523
CHECK_INTERVAL=1800  # 30 minutes

echo "=== v9 OVERNIGHT MONITOR STARTED $(date) ===" | tee "$STATUS"
echo "Monitoring PID $PID, checking every 30 min" | tee -a "$STATUS"
echo "" | tee -a "$STATUS"

ROUND=0
while true; do
    ROUND=$((ROUND + 1))
    NOW=$(date '+%Y-%m-%d %H:%M:%S')

    # Check if process is still alive
    if ! kill -0 $PID 2>/dev/null; then
        echo "[$NOW] v9 PROCESS FINISHED" | tee -a "$STATUS"
        break
    fi

    # Log 30-min checkpoint
    echo "[$NOW] Round $ROUND — process alive" | tee -a "$STATUS"

    # Extract latest meaningful log lines (skip tqdm progress bar noise)
    LATEST=$(grep -v "pair/s\|Backtesting:\|it/s\|▏\|▎\|▍\|▋\|▊\|▉\|█" "$LOG" 2>/dev/null | tail -5)
    echo "$LATEST" | tee -a "$STATUS"
    echo "---" | tee -a "$STATUS"

    sleep $CHECK_INTERVAL
done

echo "" | tee -a "$STATUS"
echo "=== v9 COMPLETE — PARSING RESULTS ===" | tee -a "$STATUS"
echo "" | tee -a "$STATUS"

# Extract main backtest results
echo "--- MAIN BACKTEST ---" | tee -a "$STATUS"
grep -E "Total Return|Sharpe Ratio|Max Drawdown|Total Trades|Win Rate|Profit Factor|Regime gate|SURVIVAL-BIAS" "$LOG" | grep -v "walk\|Window\|ERA\|wf\|fund" | tee -a "$STATUS"

echo "" | tee -a "$STATUS"
echo "--- WALK-FORWARD SUMMARY ---" | tee -a "$STATUS"
grep -E "WALK-FORWARD|Profitable windows|Avg Return|Stitched|degradation|IS.*era|OOS.*era|HARD ERA" "$LOG" | tee -a "$STATUS"

echo "" | tee -a "$STATUS"
echo "--- ALL 19 WINDOWS ---" | tee -a "$STATUS"
grep -E "Window [0-9]|Return:|Test:" "$LOG" | grep -v "pair\|spread\|quality" | head -60 | tee -a "$STATUS"

echo "" | tee -a "$STATUS"
echo "--- FUND COMPARISON ---" | tee -a "$STATUS"
grep -E "fund|Fund|Return.*%|profile" "$LOG" | grep -v "DEBUG\|pair\|spread" | head -20 | tee -a "$STATUS"

echo "" | tee -a "$STATUS"
echo "--- ERRORS (if any) ---" | tee -a "$STATUS"
grep -E "ERROR|Traceback|Exception" "$LOG" | tail -20 | tee -a "$STATUS"

echo "" | tee -a "$STATUS"
echo "=== MONITOR DONE $(date) ===" | tee -a "$STATUS"
