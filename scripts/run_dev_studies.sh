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

OUT=outputs/v33_dev
STEPS=${*:-main anatomy costs residual variants validation publish}
mkdir -p logs

for step in $STEPS; do
    echo "== $step"
    case $step in
        main)        # S1's design on the development calendar (also tops up the price cache)
            "$PY" -m pairs_trading.main --profile v33 --calendar dev --output-dir $OUT 2>&1 | tee logs/dev_main.log ;;
        anatomy)     # where the edge goes: shortfall, exit race, decay, persistence, capacity
            "$PY" scripts/anatomy_of_the_null.py --results $OUT/pairs_trading_results_2023_2025_unbiased.json \
                2>&1 | tee logs/dev_anatomy.log ;;           # writes $OUT/anatomy.json
        costs)       # the same trades under the declared cost and capacity scenarios
            "$PY" scripts/cost_sensitivity.py --profile v33 --calendar dev --out $OUT/cost_sensitivity.json \
                2>&1 | tee logs/dev_costs.log ;;
        residual)    # S2, the Avellaneda-Lee arm, on the same calendar and universe rule
            "$PY" scripts/run_residual_statarb.py --calendar dev --out outputs/residual_dev/residual_statarb.json \
                2>&1 | tee logs/dev_residual.log ;;
        variants)    # the declared family (results/variant_family/declaration.json) and its tests
            "$PY" scripts/variant_family.py run --out results/variant_family 2>&1 | tee logs/dev_variants.log
            "$PY" scripts/variant_family.py analyse --base-run $OUT --out results/variant_family \
                2>&1 | tee -a logs/dev_variants.log ;;
        validation)  # known-answer checks of the engine on synthetic markets
            mkdir -p results/validation
            "$PY" scripts/synthetic_validation.py --seeds 10 --out results/validation/synthetic_validation.json \
                2>&1 | tee logs/dev_validation.log ;;
        publish)     # committed evidence, and one registry line per trial
            "$PY" scripts/publish_run.py $OUT v33_dev --log logs/dev_main.log --replace
            "$PY" scripts/publish_run.py outputs/residual_dev residual_dev --log logs/dev_residual.log --replace
            "$PY" scripts/register_trial.py --name v33_dev --run results/v33_dev \
                --note "v33 design on the development calendar (pre-registration candidate S1)"
            "$PY" scripts/register_trial.py --name residual_dev --note "Avellaneda-Lee arm (S2), development calendar; results/residual_dev"
            "$PY" scripts/register_trial.py --name variant_family \
                --note "the declared family of results/variant_family/declaration.json; snooping.json" ;;
        *) fail "unknown step $step" ;;
    esac
done
echo "done: $STEPS"
