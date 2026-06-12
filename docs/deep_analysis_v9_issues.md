# Deep Analysis: Why v9 Failed (0.41% return, 327 trades)

## Root Cause Analysis (Completed: 2026-02-21 01:16)

### Issue 1: RL Agent Signal Generation Too Strict

**Location**: `multi_agent_system.py` lines 27-29, 205-223

**Current thresholds:**
```python
min_zscore_threshold = 1.5      # Spread must be > 1.5σ
min_signal_strength = 0.60      # Signal strength > 0.60
min_confidence_threshold = 0.65 # Feature quality > 0.65
```

**Triple gate logic:**
1. If `abs(zscore) < 1.5` → HOLD (no trade)
2. If `signal_strength < 0.60` → HOLD (redundant with #1, since signal_strength = abs_zscore / 2.5)
3. If `feature_quality < 0.65` → HOLD

**Feature quality calculation** (lines 240-281):
- Zscore contribution: 0.0-0.30 (max at z > 2.5)
- Momentum contribution: 0.0-0.25 (if abs(momentum_5) > 0.005)
- RSI contribution: 0.0-0.20 (if RSI divergence > 0.1)
- Correlation + quality: 0.0-0.25 (if corr > 0.2 AND quality > 0.5)

**To reach 0.65 threshold**, you need:
- High zscore (>2.5) → 0.30
- Strong momentum → 0.25
- RSI divergence → 0.20
- Good correlation → 0.25
- **Total**: Nearly perfect conditions required

**Impact**: In post-hike regime (2023-2025):
- Pair correlations are weaker
- Half-lives are longer (slower mean reversion)
- Momentum signals are noisier
- Feature quality rarely exceeds 0.65

**Result**: v9 generated only 327 trades over 751 days (0.44 trades/day) vs v8's 3,092 trades over 1,507 days (2.05 trades/day).

**Why this didn't show in ZIRP-era backtests:**
The agent was trained on 2020-2022 data where pairs were strong (correlation >0.7, half-life <10 days). During training, feature quality routinely exceeded 0.65. When deployed to 2023-2025, the weaker regime caused feature quality to drop below threshold → no trades.

---

### Issue 2: Regime Gate is Position Scaling, Not Trade Suspension

**Location**: `trading_system.py` lines 244-269

**Current logic:**
```python
# VIX gate
if _cur_vix > 40: _vix_scale = 0.25
elif _cur_vix > 30: _vix_scale = 0.50
else: _vix_scale = 1.00

# Dispersion gate (Walking on Ice)
if _cur_dispz > 2.0: _disp_scale = 0.50
elif _cur_vix < 20 and _cur_dispz > 1.2: _disp_scale = 0.60  # Walking on Ice
else: _disp_scale = 1.00

regime_scale = min(_vix_scale, _disp_scale)
risk_scaling_factor *= regime_scale  # Scales position size, NOT trade count
```

**What this does:**
- Reduces position sizes to 25%, 50%, or 60% of normal
- Does NOT stop trading
- Does NOT filter out weak signals

**Evidence from v8 results** (PROGRESS.md lines 432-435):
```
W16 (Oct 2024-Jan 2025): 14 Walking on Ice days (0.6× scale) → return -6.52%
  - 14 days scaled to 60%
  - 49 days at full scale
  - Still traded 438 trades (many on bad pairs)

W17-W19 (2025): 4-8 WoI days each → all negative returns
```

**Problem:**
1. Walking on Ice fires correctly (14 days in W16) but only reduces position size
2. The 49 unfired days still trade at full scale
3. When >22% of window days are reduced-scale, the regime is genuinely broken
4. Position scaling is insufficient — we should SUSPEND trading entirely

**Why VIX gate doesn't help 2024-2025:**
- 2024-2025 VIX was 12-18 (below 20) → VIX gate never fires
- Post-election sector rotation (XLF/XLY surge vs XLK lag) creates dispersion
- Cumulative dispersion z > 1.2 triggers Walking on Ice at 0.60× scale
- But 0.60× position size on a failing strategy still loses money

---

### Issue 3: RL Training Data Mismatch (v9 fixed in v10)

**Location**: `trading_system.py` lines 1403-1410 (v9), lines 1429-1470 (v10)

**v9 training data:**
- Pair selection: 2020-2022 (train_cutoff = 2022-12-31)
- RL training: 2020-2022 spreads
- Main backtest: 2023-07-01 → 2025

**Problem:**
RL agent learned signal patterns from ZIRP era (VIX 15-20, strong correlations, fast mean reversion). When deployed to post-hike era (VIX 12-18 but weak correlations, slow mean reversion), the learned patterns don't apply.

**v10 fix (already applied):**
```python
_ext_cutoff = pd.Timestamp('2023-06-30')
# Build extended training spreads through 2023-06-30
# Main backtest starts 2023-07-01
```

RL agent now trains on 2020-2023-H1 (includes first 6 months of post-hike regime), then tests on 2023-07-01 → 2025.

**Expected impact of v10 fix:**
- Agent learns post-hike signal patterns
- Should generate more signals in 2023-2025 (fix Issue #3)
- BUT Issues #1 and #2 still remain:
  - Feature quality threshold still 0.65 (too strict)
  - Regime gate still only scales positions (doesn't suspend)

---

## Quantitative Evidence

### v9 Results (survival bias fixed):
```
Main Backtest (2023-2025, 751 days):
  Total Return:   0.41%
  Sharpe Ratio:   0.21
  Max Drawdown:  -10.93%
  Total Trades:   327        ← 89% reduction from v8's 3,092
  Win Rate:       49.54%     ← coin flip

Trades per day: 0.44 (v8: 2.05, v6: 15.4)
```

### Walk-forward OOS (already unbiased):
```
W10-W19 (post-regime, 2023-2025):
  Avg return: +0.72%/qtr
  Sharpe: 0.534
  Win rate: 50.4%
  IS→OOS degradation: 96.2%
```

The walk-forward OOS avg (+0.72%/qtr) is consistent with main backtest (0.41% total over ~2 years = 0.14%/qtr) — both show the strategy is barely breakeven post-2023.

---

## Why v8's 499.6% Was Misleading

**v8 survival bias** (PROGRESS.md lines 482-519):
- `pair_windows` stored spreads with full 2020-2025 history
- Main backtest built `all_dates` from spread indices → included 2020-2022
- For pre-2023 dates, used pairs validated on 2021-2023 data (Q1 2023 window)
- Trading 2020-2022 with 2023-validated pairs = backward look-ahead bias

**v8 inflated return breakdown:**
- 2020-2022 (look-ahead): ~3 years of strong ZIRP returns
- 2023-2025 (genuine OOS): weak returns
- Blended result: 499.6%

**v9 fix:**
```python
date_range=('2023-01-01', _max_test_date)
```
Restricted main backtest to true OOS period → 0.41% return (honest).

---

## Proposed Fixes for v11 (After v10 Results)

### Fix 1: Relax RL Agent Thresholds

**File**: `multi_agent_system.py`

**Change:**
```python
# OLD (v9/v10)
self.min_zscore_threshold = 1.5
self.min_signal_strength = 0.60
self.min_confidence_threshold = 0.65

# NEW (v11)
self.min_zscore_threshold = 1.2      # Lower from 1.5 → captures weaker signals
self.min_signal_strength = 0.50      # Lower from 0.60
self.min_confidence_threshold = 0.50 # Lower from 0.65 → accepts moderate-quality setups
```

**Rationale:**
Post-hike pairs have weaker signals. Threshold of 0.65 was calibrated for ZIRP-era training data. Lowering to 0.50 allows trades on moderate-confidence setups while still filtering garbage.

**Expected impact:**
- More trades (327 → 800-1,200)
- May lower win rate slightly (49.5% → 52-55%) but higher trade count compensates
- Should improve total return if signals are directionally correct

---

### Fix 2: Add Hard Stop When Regime Gate Fires Frequently

**File**: `trading_system.py`, in `run_comprehensive_backtest()`

**Change** (after regime gate calculation):
```python
regime_scale = min(_vix_scale, _disp_scale)

# NEW: Check if regime is persistently broken
_recent_dates = list(all_dates[:i+1])[-63:]  # Last 63 days (1 quarter)
_recent_reduced = sum(1 for d in _recent_dates if _regime_scale_counts.get(_get_scale_for_date(d), 1.0) < 1.0)

# If >20% of recent 63 days are reduced-scale, SUSPEND trading
if len(_recent_dates) >= 63 and _recent_reduced / 63 > 0.20:
    continue  # Skip this day entirely (no trades)

risk_scaling_factor *= regime_scale
```

**Rationale:**
- W16 had 14/63 WoI days (22%) → regime is broken
- Position scaling at 0.60× on a failing strategy still loses money
- Better to sit out entirely when >20% of quarter is reduced-scale

**Expected impact:**
- W16-W19 would be skipped → no trades in broken regime
- Avoid -6.52%, -1.04%, -5.85% losses
- May slightly reduce total return in good periods but massively reduces drawdown

---

### Fix 3: Lower Walking on Ice Threshold 1.2σ → 0.8σ

**File**: `trading_system.py`, lines 259-263

**Change:**
```python
# OLD
elif _cur_vix < 20 and _cur_dispz > 1.2:
    _disp_scale = 0.60

# NEW
elif _cur_vix < 20 and _cur_dispz > 0.8:
    _disp_scale = 0.40  # More aggressive scaling
```

**Rationale:**
- W10 cumulative dispersion avg was -0.08σ, max 1.42σ → only 2/63 days triggered
- The 1.2σ threshold was too high to catch early regime deterioration
- Lower to 0.8σ with 0.40× scale (instead of 0.60×) → more protective

**Expected impact:**
- Catch regime breaks earlier
- Combined with Fix #2 (hard stop), would suspend trading sooner
- Should protect capital in 2024-2025 breakdown

---

## v10 Expected Results

**What v10 changed:**
- Extended RL training to 2023-06-30 (from 2022-12-31)
- Main backtest starts 2023-07-01 (from 2023-01-01)

**What v10 did NOT change:**
- Issue #1: Feature quality threshold still 0.65
- Issue #2: Regime gate still only scales positions
- Issue #3: Fixed (this was the v10 change)

**Prediction:**
- More trades than v9 (327 → 600-1,000) because agent sees post-hike training data
- Still fewer than v8 (3,092) because threshold 0.65 is strict
- Walk-forward results unchanged (already retrain per window)
- Main backtest return: 5-15% (vs v9: 0.41%, v8: 499.6%)
- If regime gate fires in 2024-2025 and v10 still trades through it → W16-W19 still lose

---

## Recommended Test Sequence After v10

1. **Verify v10 results** (when PID 55695 completes)
   - Check total trades (expect 600-1,000)
   - Check return (expect 5-15%)
   - Check walk-forward (should match v9: 353.76% stitched, OOS +0.72%)

2. **If v10 < 10% return or trades < 600**: Implement Fix #1 (lower thresholds) → v11

3. **If v10 has W16-W19 losses**: Implement Fix #2 (hard stop) + Fix #3 (lower WoI threshold) → v11 or v12

4. **Compare v11 vs v10**:
   - Expect v11 higher trades, moderate win rate improvement
   - Expect v11 avoids 2024-2025 losses via hard stop

---

## Status: Monitoring v10

PID: 55695
Started: 2026-02-21 01:01:54
Expected completion: 04:00-06:00
Monitor script: `scripts/monitor_v10.sh`

Next check: 01:45 (30 min from start)
