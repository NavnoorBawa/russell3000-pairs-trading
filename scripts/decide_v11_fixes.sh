#!/bin/bash
# Decision tree for which v11 fixes to apply based on v10 results

LOG="/Users/navnoorbawa/Downloads/Transformet Notion/backtest_v10.log"

if [ ! -f "$LOG" ]; then
    echo "ERROR: v10 log not found"
    exit 1
fi

# Extract key metrics
TOTAL_TRADES=$(grep "Total Trades:" "$LOG" | grep -v "Window\|quality" | head -1 | awk '{print $3}')
TOTAL_RETURN=$(grep "Total Return:" "$LOG" | grep -v "Window\|quality" | head -1 | awk '{print $3}' | tr -d '%')

echo "=== v10 RESULTS ==="
echo "Total Trades: $TOTAL_TRADES"
echo "Total Return: $TOTAL_RETURN%"
echo ""

# Decision logic
echo "=== v11 FIX RECOMMENDATIONS ==="

if [ -z "$TOTAL_TRADES" ] || [ -z "$TOTAL_RETURN" ]; then
    echo "ERROR: Could not extract metrics from log"
    exit 1
fi

# Convert to integers for comparison (remove decimals)
TRADES_INT=${TOTAL_TRADES%.*}
RETURN_INT=${TOTAL_RETURN%.*}

if [ "$TRADES_INT" -lt 600 ]; then
    echo "✓ Apply Fix #1 (Relax Thresholds)"
    echo "  Reason: Trades < 600 → signal generation still too strict"
    echo ""
    echo "? Consider Fix #2 (Hard Stop)"
    echo "  Check walk-forward W16-W19 for losses"
    echo ""
    FIX1=1
    FIX2=maybe
    FIX3=maybe

elif [ "$TRADES_INT" -ge 600 ] && [ "$RETURN_INT" -lt 10 ]; then
    echo "✓ Apply Fix #1 (Relax Thresholds)"
    echo "  Reason: Trades recovered but return < 10% → need better signal quality"
    echo ""
    echo "✓ Apply Fix #2 (Hard Stop)"
    echo "  Reason: Low return despite trades → likely trading through bad regimes"
    echo ""
    echo "✓ Apply Fix #3 (Lower WoI Threshold)"
    echo "  Reason: Need earlier regime detection"
    echo ""
    FIX1=1
    FIX2=1
    FIX3=1

elif [ "$TRADES_INT" -ge 600 ] && [ "$RETURN_INT" -ge 10 ]; then
    echo "✗ Skip Fix #1 (Thresholds OK)"
    echo "  Reason: Extended training worked! Trades > 600"
    echo ""
    echo "✓ Apply Fix #2 (Hard Stop)"
    echo "  Reason: Protect against future regime breaks"
    echo ""
    echo "✓ Apply Fix #3 (Lower WoI Threshold)"
    echo "  Reason: Earlier regime detection"
    echo ""
    FIX1=0
    FIX2=1
    FIX3=1
else
    echo "? Manual review needed"
    FIX1=maybe
    FIX2=maybe
    FIX3=maybe
fi

echo ""
echo "=== IMPLEMENTATION PLAN ==="

if [ "$FIX1" == "1" ]; then
    echo "1. Edit pairs_trading/multi_agent_system.py (lines 27-29)"
    echo "   Apply: v11_fix1_thresholds.patch"
fi

if [ "$FIX2" == "1" ]; then
    echo "2. Edit pairs_trading/trading_system.py (after line 269)"
    echo "   Apply: v11_fix2_hard_stop.patch"
fi

if [ "$FIX3" == "1" ]; then
    echo "3. Edit pairs_trading/trading_system.py (lines 259-263)"
    echo "   Apply: v11_fix3_woi_threshold.patch"
fi

if [ "$FIX1" == "1" ] || [ "$FIX2" == "1" ] || [ "$FIX3" == "1" ]; then
    echo ""
    echo "4. Run v11:"
    echo "   cd /Users/navnoorbawa/Downloads/Transformet\\ Notion"
    echo "   nohup python -m pairs_trading.main > backtest_v11.log 2>&1 &"
fi

echo ""
echo "=== EXPECTED v11 OUTCOMES ==="

if [ "$FIX1" == "1" ]; then
    echo "Fix #1: Trades increase from $TOTAL_TRADES → 800-1,200"
fi

if [ "$FIX2" == "1" ]; then
    echo "Fix #2: W16-W19 losses avoided (regime suspension)"
fi

if [ "$FIX3" == "1" ]; then
    echo "Fix #3: Walking on Ice fires earlier (more days at 0.40× scale)"
fi
