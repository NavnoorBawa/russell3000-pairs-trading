#!/bin/bash
# Autonomous v10 monitor - checks every 30 min

PID=55695
LOG_FILE="/Users/navnoorbawa/Downloads/Transformet Notion/backtest_v10.log"
STATUS_FILE="/Users/navnoorbawa/Downloads/Transformet Notion/v10_status.txt"

while true; do
    TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")

    if kill -0 $PID 2>/dev/null; then
        # Still running
        LINES=$(wc -l < "$LOG_FILE" 2>/dev/null || echo "0")
        LAST_LOG=$(tail -3 "$LOG_FILE" 2>/dev/null | grep -E "Window|Return:|Complete" | tail -1 || echo "Processing...")

        echo "[$TIMESTAMP] v10 RUNNING | Lines: $LINES | $LAST_LOG" >> "$STATUS_FILE"
        echo "[$TIMESTAMP] v10 still running..."

        # Wait 30 minutes
        sleep 1800
    else
        # Process completed
        echo "[$TIMESTAMP] v10 COMPLETED" >> "$STATUS_FILE"
        echo "[$TIMESTAMP] v10 COMPLETED - analyzing results..."

        # Check for errors
        ERROR_COUNT=$(grep -c "ERROR\|Traceback" "$LOG_FILE" 2>/dev/null || echo "0")
        echo "Error count: $ERROR_COUNT" >> "$STATUS_FILE"

        # Extract key results
        grep -E "Total Return|Sharpe Ratio|Max Drawdown|Total Trades|Win Rate|Stitched|Profitable windows|OOS.*avg|degradation" "$LOG_FILE" | \
            grep -v "pair/s\|▏\|TRADE\|Window\|quality\|spread" | \
            tail -30 >> "$STATUS_FILE"

        echo "Results written to $STATUS_FILE"
        exit 0
    fi
done
