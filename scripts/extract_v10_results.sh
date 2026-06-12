#!/bin/bash
# Extract v10 results when complete

LOG="/Users/navnoorbawa/Downloads/Transformet Notion/backtest_v10.log"
OUT="/Users/navnoorbawa/Downloads/Transformet Notion/v10_results.txt"

echo "=== v10 RESULTS EXTRACTION ===" > "$OUT"
echo "Extracted: $(date)" >> "$OUT"
echo "" >> "$OUT"

# Check if completed
if ! grep -q "COMPLETE" "$LOG" 2>/dev/null; then
    echo "v10 NOT YET COMPLETE" >> "$OUT"
    exit 1
fi

# Error check
ERROR_COUNT=$(grep -c "ERROR\|Traceback" "$LOG" 2>/dev/null || echo "0")
echo "Error count: $ERROR_COUNT" >> "$OUT"
echo "" >> "$OUT"

# Main backtest results
echo "=== MAIN BACKTEST ===" >> "$OUT"
grep -E "Total Return:|Sharpe Ratio:|Max Drawdown:|Total Trades:|Win Rate:|Profit Factor:" "$LOG" | \
    grep -v "pair/s\|Window\|quality" | head -10 >> "$OUT"
echo "" >> "$OUT"

# Regime gate summary
echo "=== REGIME GATE ===" >> "$OUT"
grep "Regime gate summary" "$LOG" >> "$OUT"
echo "" >> "$OUT"

# Walk-forward summary
echo "=== WALK-FORWARD SUMMARY ===" >> "$OUT"
grep -A20 "WALK-FORWARD SUMMARY" "$LOG" | head -25 >> "$OUT"
echo "" >> "$OUT"

# Era split
echo "=== ERA SPLIT ===" >> "$OUT"
grep -A5 "HARD ERA SPLIT" "$LOG" >> "$OUT"
echo "" >> "$OUT"

# Individual windows
echo "=== WALK-FORWARD WINDOWS ===" >> "$OUT"
grep -E "^Window [0-9]+:" "$LOG" | while read line; do
    echo "$line" >> "$OUT"
    # Get next 3 lines (Return, Sharpe, etc.)
    WINDOW_NUM=$(echo "$line" | grep -o "Window [0-9]*" | grep -o "[0-9]*")
    grep -A3 "^Window $WINDOW_NUM:" "$LOG" | tail -3 >> "$OUT"
    echo "" >> "$OUT"
done

# Training info
echo "=== TRAINING INFO ===" >> "$OUT"
grep "v10:" "$LOG" | head -10 >> "$OUT"
echo "" >> "$OUT"

# Completion time
echo "=== TIMING ===" >> "$OUT"
START_TIME=$(head -1 "$LOG" | awk '{print $1, $2}')
END_TIME=$(tail -50 "$LOG" | grep -E "COMPLETE|Exported" | tail -1 | awk '{print $1, $2}')
echo "Start: $START_TIME" >> "$OUT"
echo "End: $END_TIME" >> "$OUT"

echo "" >> "$OUT"
echo "Full results in: $LOG" >> "$OUT"

cat "$OUT"
