#!/usr/bin/env bash
# The pre-registered 2026 out-of-sample test (docs/PREREGISTRATION.md), exactly as registered.
#
# Run ONCE, from a clean checkout of the commit that added docs/PREREGISTRATION.md. Every
# step is logged; each strategy's run is appended to results/trial_registry.jsonl.
#   bash scripts/run_holdout.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PYTHON:-python}
PREREG_COMMIT=$(git log --diff-filter=A --format=%H -- docs/PREREGISTRATION.md | tail -1)
HEAD_COMMIT=$(git rev-parse HEAD)

# 0. The code must be the pre-registered code: nothing under pairs_trading/ or scripts/ may
#    differ from the pre-registration commit, and the working tree must be clean.
if [ -z "$PREREG_COMMIT" ]; then echo "docs/PREREGISTRATION.md is not committed" >&2; exit 1; fi
#    The one exception (commitment 2): a crash fix in code that cannot change a trading
#    decision, run with HOLDOUT_CRASH_FIX="<what was fixed>"; the diff is recorded with the trial.
NOTE=""
if ! git diff --quiet "$PREREG_COMMIT" HEAD -- pairs_trading scripts reference; then
    if [ -z "${HOLDOUT_CRASH_FIX:-}" ]; then
        echo "code changed since the pre-registration commit $PREREG_COMMIT" >&2; exit 1
    fi
    NOTE="crash fix: $HOLDOUT_CRASH_FIX; changed since $PREREG_COMMIT: $(git diff --stat "$PREREG_COMMIT" HEAD -- pairs_trading scripts reference | tail -1)"
    echo "$NOTE" >&2
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "uncommitted changes: refusing to run the holdout" >&2; exit 1
fi
mkdir -p logs results/holdout2026

# 1. The point-in-time membership snapshots of 2026 (their holdings carry 2026 market
#    values, so they were sealed with the prices). Fetched only now.
$PY scripts/build_pit_universe.py --include-sealed 2>&1 | tee logs/holdout2026_universe.log

# 2. S1 (v33 pairs) and S3 (v32 pairs). The first run creates the holdout price cache
#    (2023-01-01 -> 2026-10-19); the second tops it up with its own universe's symbols.
$PY -m pairs_trading.main --profile v33 --calendar holdout2026 --output-dir outputs/holdout2026_v33 \
    2>&1 | tee logs/holdout2026_v33.log
$PY -m pairs_trading.main --profile v32 --calendar holdout2026 --output-dir outputs/holdout2026_v32 \
    2>&1 | tee logs/holdout2026_v32.log

# 3. S2 (Avellaneda-Lee residual reversion) on the same cache and membership.
$PY scripts/run_residual_statarb.py --calendar holdout2026 \
    --out outputs/holdout2026_residual/residual_statarb.json 2>&1 | tee logs/holdout2026_residual.log

# 4. The registered test: one-sided HAC t per strategy, Holm across the three.
$PY scripts/evaluate_holdout.py \
    --pairs v33_pairs=outputs/holdout2026_v33 --pairs v32_pairs=outputs/holdout2026_v32 \
    --residual outputs/holdout2026_residual/residual_statarb.json \
    --out results/holdout2026/evaluation.json 2>&1 | tee logs/holdout2026_evaluation.log

# 5. Publish every export as committed evidence, and register the runs.
$PY scripts/publish_run.py outputs/holdout2026_v33 holdout2026/v33_pairs --log logs/holdout2026_v33.log
$PY scripts/publish_run.py outputs/holdout2026_v32 holdout2026/v32_pairs --log logs/holdout2026_v32.log
$PY scripts/publish_run.py outputs/holdout2026_residual holdout2026/residual --log logs/holdout2026_residual.log
$PY scripts/register_trial.py --name holdout2026 --prereg-commit "$PREREG_COMMIT" --head "$HEAD_COMMIT" \
    --run results/holdout2026/v33_pairs --run results/holdout2026/v32_pairs \
    --evaluation results/holdout2026/evaluation.json ${NOTE:+--note "$NOTE"}
echo "holdout complete: results/holdout2026/"
