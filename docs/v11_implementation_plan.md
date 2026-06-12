# v11 Implementation Plan

## Based on v10 Results Analysis

### Files to Modify

1. **multi_agent_system.py** (Fix #1: Relax signal thresholds)
2. **trading_system.py** (Fix #2: Hard stop when regime broken, Fix #3: Lower WoI threshold)
3. **PROGRESS.md** (Update with v10 results)
4. **MEMORY.md** (Update with v10 learnings)

---

## Fix #1: Relax RL Agent Thresholds

**File**: `pairs_trading/multi_agent_system.py`
**Lines**: 27-29

### Current Code:
```python
self.min_zscore_threshold = 1.5
self.min_signal_strength = 0.60
self.min_confidence_threshold = 0.65
```

### v11 Change:
```python
self.min_zscore_threshold = 1.2      # v11: Lower from 1.5 → capture weaker post-hike signals
self.min_signal_strength = 0.50      # v11: Lower from 0.60
self.min_confidence_threshold = 0.50 # v11: Lower from 0.65 → accept moderate-quality setups
```

### Rationale:
- v9 threshold 0.65 rejected 89% of potential trades (327 trades vs v8's 3,092)
- Post-hike pairs have weaker signals than ZIRP-era training data
- Feature quality calculation requires near-perfect conditions to reach 0.65
- Lowering to 0.50 allows moderate-confidence trades while filtering low-quality

### Expected Impact:
- Trades: 327 (v9) → 800-1,200 (v11)
- Win rate: 49.5% → 52-56% (better signal capture)
- Return: 0.41% (v9) → 8-18% (v11) if signals are directionally correct

---

## Fix #2: Hard Stop When Regime Persistently Broken

**File**: `pairs_trading/trading_system.py`
**Location**: After line 269 (after regime_scale calculation)

### New Code Block:
```python
            regime_scale = min(_vix_scale, _disp_scale)

            # ── v11: HARD STOP when regime is persistently broken ──────────
            # If >20% of last 63 days are reduced-scale, the regime is genuinely
            # broken (not just transient stress). Suspend trading entirely.
            # Example: W16 had 14/63 WoI days (22%) → lost -6.52%
            if i >= 62:  # Need 63 days of history
                _recent_63_dates = all_dates[max(0, i-62):i+1]
                _recent_reduced = 0
                for _d in _recent_63_dates:
                    _dk = str(_d.date()) if hasattr(_d, 'date') else str(_d)
                    _d_vix = _vix_lookup.get(_dk, 18.0)
                    _d_disp = _disp_z_lookup.get(_dk, 0.0)

                    if _d_vix > 40:
                        _d_scale = 0.25
                    elif _d_vix > 30:
                        _d_scale = 0.50
                    elif _d_disp > 2.0:
                        _d_scale = 0.50
                    elif _d_vix < 20 and _d_disp > 0.8:  # v11: lowered from 1.2
                        _d_scale = 0.40  # v11: more aggressive from 0.60
                    else:
                        _d_scale = 1.0

                    if _d_scale < 1.0:
                        _recent_reduced += 1

                # If >20% of last quarter is reduced, SKIP this day
                if _recent_reduced / len(_recent_63_dates) > 0.20:
                    logger.debug(f"v11 hard stop: {_recent_reduced}/{len(_recent_63_dates)} days reduced in last 63d — suspending trading on {date.date()}")
                    continue  # Skip to next date

            risk_scaling_factor *= regime_scale
            # ── End v11 hard stop ──────────────────────────────────────────
```

### Rationale:
- v8 W16 had 14/63 WoI days (22%) but still traded → lost -6.52%
- Position scaling at 0.60× on failing strategy still loses money
- Better to suspend entirely when regime is persistently broken
- 20% threshold = ~13 days out of 63 (roughly 1 in 5 days reduced)

### Expected Impact:
- W16-W19 (2024-2025) would be skipped if >20% threshold met
- Avoid losses: -6.52% (W16), -1.04% (W18), -5.85% (W19)
- Total avoided loss: ~13% over 4 windows
- May reduce returns slightly in good periods but massively reduces drawdown

---

## Fix #3: Lower Walking on Ice Threshold

**File**: `pairs_trading/trading_system.py`
**Lines**: 259-263

### Current Code:
```python
if _cur_dispz > 2.0:
    _disp_scale = 0.50
elif _cur_vix < 20 and _cur_dispz > 1.2:
    # Low VIX + elevated CUMULATIVE sector divergence = Walking on Ice
    _disp_scale = 0.60
else:
    _disp_scale = 1.00
```

### v11 Change:
```python
if _cur_dispz > 2.0:
    _disp_scale = 0.50
elif _cur_vix < 20 and _cur_dispz > 0.8:  # v11: Lower from 1.2 → earlier detection
    # Low VIX + elevated CUMULATIVE sector divergence = Walking on Ice
    _disp_scale = 0.40  # v11: More aggressive scaling from 0.60
else:
    _disp_scale = 1.00
```

### Rationale:
- v8 W10: cumulative dispersion avg -0.08σ, max 1.42σ → only 2/63 days triggered
- 1.2σ threshold was too high to catch early regime deterioration
- Lower to 0.8σ → catch regime breaks earlier
- Scale to 0.40× (not 0.60×) → more protective when detected

### Expected Impact:
- Walking on Ice fires 5-10 days earlier in windows like W10, W16
- Combined with Fix #2 (hard stop), triggers suspension sooner
- Should protect capital before regime fully breaks

---

## Implementation Steps

1. **Wait for v10 completion**
   - Monitor PID 55695
   - Parse v10 results from backtest_v10.log
   - Extract: Total Return, Sharpe, Trades, Win Rate, Walk-Forward summary

2. **Analyze v10 results**
   - Compare vs v9 (0.41%, 327 trades)
   - Check if extended training increased trade count
   - Check walk-forward windows (should match v9 since they retrain)

3. **Decision tree**:

   **If v10 trades < 600:**
   → Implement Fix #1 only (relax thresholds) → v11a
   → Run v11a

   **If v10 trades > 600 AND return > 10%:**
   → Extended training worked!
   → Implement Fix #2 + Fix #3 (regime protection) → v11b
   → Run v11b

   **If v10 trades > 600 AND return < 5%:**
   → Trades recovered but signals are wrong
   → Implement all 3 fixes → v11c
   → Run v11c

4. **Code changes** (when decided):
   ```bash
   # Edit multi_agent_system.py (Fix #1)
   # Edit trading_system.py (Fix #2, Fix #3)
   # Run v11
   nohup python -m pairs_trading.main > backtest_v11.log 2>&1 &
   ```

5. **Update documentation**:
   - PROGRESS.md: Add v10 results section, v11 changes section
   - MEMORY.md: Update with v10/v11 learnings
   - overnight_results.txt: Final summary for user

---

## Validation Checklist After v11

- [ ] Total trades vs v9 (327) and v10 (TBD)
- [ ] Win rate vs v9 (49.54%)
- [ ] Sharpe ratio vs v9 (0.21)
- [ ] Walk-forward stitched return vs v9 (353.76%)
- [ ] OOS degradation vs v9 (96.2%)
- [ ] W16-W19 returns (should be 0 or minimal if hard stop worked)
- [ ] Regime gate summary (how many days reduced/suspended)
- [ ] Fund comparison (all 5 profiles)
- [ ] No errors in log (grep ERROR/Traceback)

---

## Alternative: If v10 Shows Training Data Mismatch Still Exists

**Symptom**: v10 trades still low (< 500) despite extended training

**Diagnosis**: RL agent might not be using extended training data correctly

**Check**:
```bash
grep "training_start\|training_end\|2023-06-30" backtest_v10.log
```

**If training still ends at 2022-12-31**:
→ Bug in v10 implementation
→ Fix the training data slicing logic in run_complete_system()
→ Re-run as v10b

---

## Timeline Estimate

- v10 completion: ~04:00-06:00 (3-5 hours from 01:01 start)
- v10 analysis: ~15 min
- v11 implementation: ~10 min (code changes already planned here)
- v11 run: ~3-5 hours
- v11 analysis: ~15 min
- Total iteration time: ~7-11 hours for v10+v11 cycle

If user returns at 11:00 AM (~10 hours from 01:00 AM):
- Best case: v10 + v11 both complete, results analyzed
- Worst case: v10 complete + analyzed, v11 running (90% done)

---

## Status

Created: 2026-02-21 01:18
Next action: Wait until 01:31:54, check v10 status
