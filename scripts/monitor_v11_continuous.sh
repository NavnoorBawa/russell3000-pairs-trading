#!/bin/bash
# Continuous v11 monitor - checks every 30 min until complete

PID=27065
LOG="/Users/navnoorbawa/Downloads/Transformet Notion/backtest_v11.log"
STATUS="/Users/navnoorbawa/Downloads/Transformet Notion/v11_status.txt"

echo "=== v11 MONITORING STARTED ===" > "$STATUS"
echo "Started: $(date)" >> "$STATUS"
echo "PID: $PID" >> "$STATUS"
echo "" >> "$STATUS"

CHECK_COUNT=0
while true; do
    CHECK_COUNT=$((CHECK_COUNT + 1))
    TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")

    if kill -0 $PID 2>/dev/null; then
        # Still running - check progress
        LAST_WINDOW=$(grep "Window.*:" "$LOG" 2>/dev/null | tail -1 || echo "Starting...")
        LAST_RETURN=$(grep "→ Return:" "$LOG" 2>/dev/null | tail -1 || echo "No windows completed yet")

        echo "[$TIMESTAMP] Check #$CHECK_COUNT: RUNNING" >> "$STATUS"
        echo "  Last window: $LAST_WINDOW" >> "$STATUS"
        echo "  Last result: $LAST_RETURN" >> "$STATUS"
        echo "" >> "$STATUS"

        # Wait 30 minutes
        sleep 1800
    else
        # Process completed!
        echo "[$TIMESTAMP] v11 COMPLETED!" >> "$STATUS"
        echo "" >> "$STATUS"

        # Extract results
        echo "=== FINAL RESULTS ===" >> "$STATUS"
        grep -E "Total Return|Sharpe Ratio|Max Drawdown|Total Trades|Win Rate" "$LOG" | \
            grep -v "Window\|quality" | head -6 >> "$STATUS"
        echo "" >> "$STATUS"

        echo "=== HARD STOP ACTIVITY ===" >> "$STATUS"
        HARD_STOPS=$(grep -c "v11 hard stop" "$LOG" 2>/dev/null || echo "0")
        echo "Days suspended: $HARD_STOPS" >> "$STATUS"
        grep "v11 hard stop" "$LOG" | head -10 >> "$STATUS"
        echo "" >> "$STATUS"

        echo "=== WALK-FORWARD SUMMARY ===" >> "$STATUS"
        grep -A10 "WALK-FORWARD SUMMARY" "$LOG" | head -12 >> "$STATUS"
        echo "" >> "$STATUS"

        echo "Full log: $LOG" >> "$STATUS"
        echo "Completed: $(date)" >> "$STATUS"

        cat "$STATUS"
        exit 0
    fi
done
