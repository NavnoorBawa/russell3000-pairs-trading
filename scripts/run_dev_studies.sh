#!/usr/bin/env bash
# The development-period studies behind the published v33 results, in order.
#
# Every number on the site and in the paper for 2020-2025 comes from these runs; the 2026
# holdout has its own runbook (scripts/run_holdout.sh). Run from a clean checkout with
# PYTHON set to the environment pinned in requirements.txt:
#   PYTHON=/path/to/venv/bin/python bash scripts/run_dev_studies.sh [STEP ...]
# STEP is any of: main anatomy costs residual variants validation publish (default: all,
# in that order). Each step logs to logs/dev_<step>.log. The variant family is the long
# one (one main backtest per declared variant, a few hours on four cores).
#
# RUN names the run (default v33_dev, the published development run). Any other name is a
# separate run of the same design and calendar, such as the re-fetch reproduction
# (RUN=v33_dev_refetch): every step writes under outputs/$RUN/ and logs to logs/${RUN}_<step>.log,
# and publish adds results/$RUN/ (with residual/, variant_family/ and validation/ inside it)
# without --replace, so it never touches another run's results and registers no trial; its
# robustness checks are the step "robustness", after publish.
set -euo pipefail
cd "$(dirname "$0")/.."

fail() { echo "run_dev_studies: $*" >&2; exit 1; }
for v in $(compgen -e); do case $v in PAIRS_*) unset "$v";; esac; done
export PYTHONHASHSEED=0
PY=${PYTHON:?set PYTHON to the interpreter of the environment pinned in requirements.txt}
"$PY" scripts/check_pins.py requirements.txt || fail "the environment differs from requirements.txt"
[ -z "$(git status --porcelain --untracked-files=all -- pairs_trading scripts reference)" ] \
    || fail "uncommitted changes under pairs_trading/, scripts/ or reference/"
export PAIRS_EXPECTED_COMMIT=$(git rev-parse HEAD)

RUN=${RUN:-v33_dev}
case $RUN in *[!A-Za-z0-9_]*|'') fail "RUN must be letters, digits and underscores";; esac
OUT=outputs/$RUN
if [ "$RUN" = v33_dev ]; then
    LOG=logs/dev; RESIDUAL_OUT=outputs/residual_dev; FAMILY_OUT=results/variant_family
    VALIDATION_OUT=results/validation
    STEPS=${*:-main anatomy costs residual variants validation publish}
else
    LOG=logs/$RUN; RESIDUAL_OUT=$OUT/residual; FAMILY_OUT=$OUT/variant_family
    VALIDATION_OUT=$OUT/validation
    STEPS=${*:-main anatomy costs residual variants validation publish robustness}
fi
mkdir -p logs

for step in $STEPS; do
    echo "== $step"
    case $step in
        main)        # S1's design on the development calendar (also tops up the price cache)
            "$PY" -m pairs_trading.main --profile v33 --calendar dev --output-dir $OUT 2>&1 | tee ${LOG}_main.log ;;
        anatomy)     # where the edge goes: shortfall, exit race, decay, persistence, capacity
            "$PY" scripts/anatomy_of_the_null.py --results $OUT/pairs_trading_results_2023_2025_unbiased.json \
                2>&1 | tee ${LOG}_anatomy.log ;;             # writes $OUT/anatomy.json
        costs)       # the same trades under the declared cost and capacity scenarios
            "$PY" scripts/cost_sensitivity.py --profile v33 --calendar dev --out $OUT/cost_sensitivity.json \
                2>&1 | tee ${LOG}_costs.log ;;
        residual)    # S2, the Avellaneda-Lee arm, on the same calendar and universe rule
            "$PY" scripts/run_residual_statarb.py --calendar dev --out $RESIDUAL_OUT/residual_statarb.json \
                2>&1 | tee ${LOG}_residual.log ;;
        variants)    # the declared family (results/variant_family/declaration.json) and its tests
            "$PY" scripts/variant_family.py run --out $FAMILY_OUT 2>&1 | tee ${LOG}_variants.log
            "$PY" scripts/variant_family.py analyse --base-run $OUT --out $FAMILY_OUT \
                2>&1 | tee -a ${LOG}_variants.log ;;
        validation)  # known-answer checks of the engine on synthetic markets
            mkdir -p $VALIDATION_OUT
            "$PY" scripts/synthetic_validation.py --seeds 10 --out $VALIDATION_OUT/synthetic_validation.json \
                2>&1 | tee ${LOG}_validation.log ;;
        publish)     # committed evidence, and one registry line per trial
            if [ "$RUN" != v33_dev ]; then       # a reproduction: its own results/$RUN/, no trial
                "$PY" scripts/publish_run.py $OUT $RUN --log ${LOG}_main.log --cache-hashes require
                "$PY" scripts/publish_run.py $RESIDUAL_OUT $RUN/residual --log ${LOG}_residual.log --cache-hashes skip
                "$PY" scripts/publish_run.py $FAMILY_OUT $RUN/variant_family --log ${LOG}_variants.log \
                    --cache-hashes skip --also '*.csv'
                "$PY" scripts/publish_run.py $VALIDATION_OUT $RUN/validation --log ${LOG}_validation.log \
                    --cache-hashes skip
                continue
            fi
            "$PY" scripts/publish_run.py $OUT v33_dev --log logs/dev_main.log --replace
            "$PY" scripts/publish_run.py outputs/residual_dev residual_dev --log logs/dev_residual.log --replace
            "$PY" scripts/register_trial.py --name v33_dev --run results/v33_dev \
                --note "v33 design on the development calendar (pre-registration candidate S1)"
            "$PY" scripts/register_trial.py --name residual_dev --note "Avellaneda-Lee arm (S2), development calendar; results/residual_dev"
            "$PY" scripts/register_trial.py --name variant_family \
                --note "the declared family of results/variant_family/declaration.json; snooping.json" ;;
        robustness)  # start dates, regimes, persistence on the candidate pairs, clustered errors
            "$PY" scripts/robustness_checks.py --run-dir results/$RUN \
                --residual $( [ "$RUN" = v33_dev ] && echo results/residual_dev || echo results/$RUN/residual )/residual_statarb.json \
                2>&1 | tee ${LOG}_robustness.log ;;
        *) fail "unknown step $step" ;;
    esac
done
echo "done: $STEPS"
