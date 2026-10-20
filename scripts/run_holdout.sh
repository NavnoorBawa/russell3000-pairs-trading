#!/usr/bin/env bash
# The pre-registered 2026 out-of-sample test (docs/PREREGISTRATION.md), exactly as registered.
#
# Run ONCE, from a clean checkout of the commit that added docs/PREREGISTRATION.md. Every
# step is logged; the trial is appended to results/trial_registry.jsonl.
#   bash scripts/run_holdout.sh
#
# Dress rehearsal (before the pre-registration): the same steps on the 'rehearsal2025'
# calendar, the holdout shifted one year back inside the development period. No commit
# checks, no sealed data; results go to results/rehearsal2025/.
#   bash scripts/run_holdout.sh --rehearsal
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PYTHON:-python}
HEAD_COMMIT=$(git rev-parse HEAD)
NOTE=""

if [ "${1:-}" = "--rehearsal" ]; then
    CAL=rehearsal2025
    NOTE="dress rehearsal of the holdout runbook on development-period data; no decision depends on it"
else
    CAL=holdout2026
    PREREG_COMMIT=$(git log --diff-filter=A --format=%H -- docs/PREREGISTRATION.md | tail -1)
    # 0. The code must be the pre-registered code: nothing under pairs_trading/, scripts/ or
    #    reference/ may differ from the pre-registration commit, and the tree must be clean.
    #    The one exception (commitment 2): a crash fix in code that cannot change a trading
    #    decision, run with HOLDOUT_CRASH_FIX="<what was fixed>"; the diff is recorded.
    if [ -z "$PREREG_COMMIT" ]; then echo "docs/PREREGISTRATION.md is not committed" >&2; exit 1; fi
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
fi
OUT=outputs/$CAL
RES=results/$CAL
mkdir -p logs "$RES"

# 1. The point-in-time membership snapshots of 2026 (their holdings carry 2026 market
#    values, so they were sealed with the prices). Fetched only now.
if [ "$CAL" = holdout2026 ]; then
    $PY scripts/build_pit_universe.py --include-sealed 2>&1 | tee logs/${CAL}_universe.log
fi

# 2. S1 (v33 pairs) and S3 (v32 pairs). The first run creates the calendar's price cache;
#    the second tops it up with its own universe's symbols.
$PY -m pairs_trading.main --profile v33 --calendar $CAL --output-dir ${OUT}_v33 2>&1 | tee logs/${CAL}_v33.log
$PY -m pairs_trading.main --profile v32 --calendar $CAL --output-dir ${OUT}_v32 2>&1 | tee logs/${CAL}_v32.log

# 3. S2 (Avellaneda-Lee residual reversion) on the same cache and membership.
$PY scripts/run_residual_statarb.py --calendar $CAL \
    --out ${OUT}_residual/residual_statarb.json 2>&1 | tee logs/${CAL}_residual.log

# 4. The registered test: one-sided HAC t per strategy, Holm across the three.
$PY scripts/evaluate_holdout.py --pairs v33_pairs=${OUT}_v33 --pairs v32_pairs=${OUT}_v32 \
    --residual ${OUT}_residual/residual_statarb.json \
    --out $RES/evaluation.json 2>&1 | tee logs/${CAL}_evaluation.log

# 5. Publish every export as committed evidence, and register the trial.
$PY scripts/publish_run.py ${OUT}_v33 $CAL/v33_pairs --log logs/${CAL}_v33.log
$PY scripts/publish_run.py ${OUT}_v32 $CAL/v32_pairs --log logs/${CAL}_v32.log
$PY scripts/publish_run.py ${OUT}_residual $CAL/residual --log logs/${CAL}_residual.log
$PY scripts/register_trial.py --name $CAL ${PREREG_COMMIT:+--prereg-commit "$PREREG_COMMIT"} \
    --head "$HEAD_COMMIT" --run $RES/v33_pairs --run $RES/v32_pairs \
    --evaluation $RES/evaluation.json ${NOTE:+--note "$NOTE"}
echo "complete: $RES/"
