#!/usr/bin/env bash
# The pre-registered 2026 out-of-sample test (docs/PREREGISTRATION.md), exactly as registered.
#
# Run from a dedicated, full (not shallow) clone at the commit that added
# docs/PREREGISTRATION.md, pushed, with PYTHON set to the interpreter of the environment
# pinned in requirements.txt and reference/holdout_inputs.sha256 committed at the freeze:
#   PYTHON=/path/to/venv/bin/python bash scripts/run_holdout.sh
# Every attempt is appended to results/trial_attempts.jsonl when it starts, after each step
# and when it fails, so a crash is on record; the completed trial is registered in
# results/trial_registry.jsonl, and a registered name is refused before anything runs. A
# re-run at the same commit skips every step an earlier attempt finished whose inputs and
# outputs are unchanged, so no strategy runs on the holdout twice. A crash fix
# (commitment 2) is a new commit run with HOLDOUT_CRASH_FIX="<what was fixed>": it may not
# touch the design or the decision rule ($NEVER_FIXED), its full diff is published, and
# every step runs again at the new commit.
#
# Dress rehearsal (before the pre-registration): the same steps on the 'rehearsal2025'
# calendar, the holdout shifted one year back inside the development period, under its own
# trial name (default rehearsal2025). The pre-registration checks are skipped, and step 1
# rebuilds that year's committed snapshots offline, which must come out byte-identical.
#   PYTHON=/path/to/venv/bin/python bash scripts/run_holdout.sh --rehearsal [NAME]
set -euo pipefail
cd "$(dirname "$0")/.."

fail() { echo "run_holdout: $*" >&2; exit 1; }

# The environment is pinned: no PAIRS_* switch of the caller's shell reaches a run, str
# hashing is fixed, and the interpreter's packages must be requirements.txt's pins.
for v in $(compgen -e); do case $v in PAIRS_*) unset "$v";; esac; done
export PYTHONHASHSEED=0
PY=${PYTHON:?set PYTHON to the interpreter of the environment pinned in requirements.txt}

FROZEN="pairs_trading scripts reference docs/PREREGISTRATION.md requirements.txt pyproject.toml"
NEVER_FIXED="docs/PREREGISTRATION.md pairs_trading/study_config.py pairs_trading/significance.py scripts/evaluate_holdout.py"
HEAD_COMMIT=$(git rev-parse HEAD)
PREREG_COMMIT=""
NOTE=""

if [ "${1:-}" = "--rehearsal" ]; then
    CAL=rehearsal2025
    NAME=${2:-rehearsal2025}
    NOTE="dress rehearsal of the holdout runbook on development-period data; no decision depends on it"
else
    CAL=holdout2026
    NAME=holdout2026
    # 0. The code must be the pre-registered code. The commit that added the file comes from
    #    study_config.preregistration_commit (exactly one adding commit, renames not
    #    followed, an ancestor of HEAD), which a shallow clone would get wrong; it must be
    #    pushed before any 2026 data is fetched.
    [ "$(git rev-parse --is-shallow-repository)" = false ] || fail "a shallow clone cannot show the pre-registration commit"
    PREREG_COMMIT=$("$PY" -c "from pairs_trading.study_config import preregistration_commit as p; print(p() or '')")
    [ -n "$PREREG_COMMIT" ] || fail "docs/PREREGISTRATION.md is not added by exactly one commit in HEAD's history"
    [ -n "$(git branch -r --contains "$PREREG_COMMIT")" ] || fail "the pre-registration commit $PREREG_COMMIT is on no remote branch: push it first"
    if ! git diff --quiet "$PREREG_COMMIT" HEAD -- $FROZEN; then
        [ -n "${HOLDOUT_CRASH_FIX:-}" ] || fail "code changed since the pre-registration commit $PREREG_COMMIT"
        git diff --quiet "$PREREG_COMMIT" HEAD -- $NEVER_FIXED || fail "a crash fix may not change $NEVER_FIXED"
        mkdir -p logs
        CRASH_DIFF=logs/${NAME}_crash_fix_${HEAD_COMMIT:0:12}.diff
        git diff "$PREREG_COMMIT" HEAD -- $FROZEN > "$CRASH_DIFF"
        NOTE="crash fix: $HOLDOUT_CRASH_FIX; diff since $PREREG_COMMIT: $CRASH_DIFF (sha256 $(sha256sum "$CRASH_DIFF" | cut -c1-64))"
        echo "$NOTE" >&2
    fi
    [ -f reference/holdout_inputs.sha256 ] || fail "reference/holdout_inputs.sha256 (the untracked inputs' hashes) is not committed"
fi
# Untracked inputs pinned at the freeze (data/marketcap.csv, S3's universe).
[ ! -f reference/holdout_inputs.sha256 ] || sha256sum --check --strict --quiet reference/holdout_inputs.sha256 \
    || fail "an input differs from reference/holdout_inputs.sha256"
# Nothing uncommitted or untracked in the code, and S2's script is committed.
[ -z "$(git status --porcelain --untracked-files=all -- $FROZEN)" ] || fail "uncommitted or untracked changes under: $FROZEN"
git ls-files --error-unmatch scripts/run_residual_statarb.py >/dev/null 2>&1 || fail "scripts/run_residual_statarb.py is not committed"
"$PY" scripts/register_trial.py --name "$NAME" --check-new
"$PY" - <<'PINS' || fail "the environment differs from requirements.txt"
import importlib.metadata as md, re, sys
bad = []
for line in open('requirements.txt'):
    m = re.match(r'\s*([A-Za-z0-9_.\-]+)==(\S+)', line)
    if m:
        try:
            have = md.version(m.group(1))
        except md.PackageNotFoundError:
            have = None
        if have != m.group(2):
            bad.append(f'{m.group(1)} {have} (pinned {m.group(2)})')
if bad:
    sys.exit('not as pinned: ' + ', '.join(bad))
PINS

CALENDAR=$("$PY" -c "from pairs_trading.study_config import CALENDARS as C
c = C['$CAL']; print(c.price_cache, c.macro_cache, c.backtest_start, c.data_end)")
read -r PRICE_CACHE MACRO_CACHE BACKTEST_START DATA_END <<< "$CALENDAR"
OUT=outputs/$NAME
RES=results/$NAME
UNIVERSE=data/${NAME}_reference/universe        # the holdout's: universe.reference_root
RESULTS_JSON=pairs_trading_results_2023_2025_unbiased.json

mkdir -p logs
PRIOR=$("$PY" -c "import sys; sys.path.insert(0, 'scripts'); from trial_attempts import current_attempt as a; print(a('$NAME'))")
if [ "$PRIOR" = 0 ]; then
    # A first attempt starts from nothing: no cache of this calendar, no published result.
    for f in "$PRICE_CACHE" "$MACRO_CACHE" "$RES"; do
        [ ! -e "$f" ] || fail "$f exists before the first attempt at $NAME; move it aside"
    done
fi
ENV_LIST=logs/${NAME}_environment_${HEAD_COMMIT:0:12}.txt
"$PY" -c "import importlib.metadata as m, platform; print(platform.python_version())
print('\n'.join(sorted(f\"{d.metadata['Name']}=={d.version}\" for d in m.distributions())))" > "$ENV_LIST"
ATTEMPT=$("$PY" scripts/trial_attempts.py start "$NAME" --head "$HEAD_COMMIT" \
    ${PREREG_COMMIT:+--prereg-commit "$PREREG_COMMIT"} ${NOTE:+--note "$NOTE"} --environment "$ENV_LIST")
LOG=logs/${NAME}_a${ATTEMPT}
echo "$NAME: attempt $ATTEMPT at $HEAD_COMMIT"

STEP=setup
on_exit() {
    rc=$?
    if [ $rc -ne 0 ]; then "$PY" scripts/trial_attempts.py failed "$NAME" "$STEP" --note "exit $rc" || true; fi
}
trap on_exit EXIT

unchanged() {   # the checkout must not move while the attempt runs
    [ "$(git rev-parse HEAD)" = "$HEAD_COMMIT" ] || fail "HEAD moved during the run"
    [ -z "$(git status --porcelain --untracked-files=all -- $FROZEN)" ] || fail "code or reference files changed during the run"
}

run_step() {    # run_step STEP "FILES" COMMAND...: FILES are the step's inputs and outputs;
    # the step is skipped when an earlier attempt at this commit finished it with these files
    STEP=$1; local files=$2; shift 2
    # shellcheck disable=SC2086
    if "$PY" scripts/trial_attempts.py is-done "$NAME" "$STEP" $files --head "$HEAD_COMMIT"; then
        echo "step $STEP: finished by an earlier attempt at this commit, files unchanged; not run again"
    else
        "$@"
        # shellcheck disable=SC2086
        "$PY" scripts/trial_attempts.py done "$NAME" "$STEP" $files --head "$HEAD_COMMIT"
    fi
    unchanged
}

export PAIRS_EXPECTED_COMMIT=$HEAD_COMMIT
[ -z "$PREREG_COMMIT" ] || export PAIRS_UNSEAL=$PREREG_COMMIT

# 1. Point-in-time membership. The holdout: the 2026 snapshots listed as sealed at the
#    freeze (their holdings carry 2026 market values), built into data/, never into the
#    tracked reference/. The rehearsal: its year's committed snapshots, rebuilt offline.
universe() {
    if [ "$CAL" = holdout2026 ]; then
        "$PY" scripts/build_pit_universe.py --include-sealed --sealed-out "$UNIVERSE" 2>&1 | tee "${LOG}_universe.log"
    else
        "$PY" scripts/build_pit_universe.py --offline --include-sealed --sealed-out "$UNIVERSE" \
            --sealed-from "${BACKTEST_START:0:4}-01-01" --through "$DATA_END" 2>&1 | tee "${LOG}_universe.log"
    fi
}
run_step universe "$UNIVERSE/index.json" universe

# 2. One data step for every arm: prices for the union of the universes and the macro
#    series, fetched once; every run then reads the same cache files.
CACHES="$PRICE_CACHE ${PRICE_CACHE%.pkl}_manifest.json $MACRO_CACHE"
data() {
    for profile in v33 v32; do
        "$PY" -m pairs_trading.main --profile $profile --calendar $CAL --fetch-only 2>&1 | tee -a "${LOG}_data.log"
    done
}
run_step data "$UNIVERSE/index.json $CACHES" data

# 3. S1 (v33 pairs), S3 (v32 pairs) and S2 (Avellaneda-Lee residual reversion).
s1() { "$PY" -m pairs_trading.main --profile v33 --calendar $CAL --output-dir ${OUT}_v33 2>&1 | tee "${LOG}_v33.log"; }
s3() { "$PY" -m pairs_trading.main --profile v32 --calendar $CAL --output-dir ${OUT}_v32 2>&1 | tee "${LOG}_v32.log"; }
s2() { "$PY" scripts/run_residual_statarb.py --calendar $CAL --out ${OUT}_residual/residual_statarb.json 2>&1 \
           | tee "${LOG}_residual.log"; }
V33="${OUT}_v33/$RESULTS_JSON ${OUT}_v33/headline_metrics.json"
V32="${OUT}_v32/$RESULTS_JSON ${OUT}_v32/headline_metrics.json"
RESIDUAL="${OUT}_residual/residual_statarb.json"
run_step v33 "$CACHES $V33" s1
run_step v32 "$CACHES $V32" s3
run_step residual "$CACHES $RESIDUAL" s2

# 4. The registered test: one-sided HAC t per strategy, Holm across the three, on inputs
#    checked to be these runs (one commit, one cache, the calendar, the profiles).
evaluate() {
    mkdir -p "$RES"
    "$PY" scripts/evaluate_holdout.py --calendar $CAL --expect-commit "$HEAD_COMMIT" \
        --pairs v33_pairs=${OUT}_v33 --pairs v32_pairs=${OUT}_v32 \
        --residual "$RESIDUAL" --out "$RES/evaluation.json" 2>&1 | tee "${LOG}_evaluation.log"
}
run_step evaluate "$V33 $V32 $RESIDUAL $RES/evaluation.json" evaluate

# 5. Publish every export, the membership built in step 1 and every attempt's logs, then
#    register the trial.
STEP=publish
latest_log() { ls -1 logs/${NAME}_a*_"$1".log | sort -V | tail -1; }
"$PY" scripts/publish_run.py ${OUT}_v33 $NAME/v33_pairs --log "$(latest_log v33)" --replace
"$PY" scripts/publish_run.py ${OUT}_v32 $NAME/v32_pairs --log "$(latest_log v32)" --replace
"$PY" scripts/publish_run.py ${OUT}_residual $NAME/residual --log "$(latest_log residual)" --replace
rm -rf "$RES/universe" "$RES/logs"
mkdir -p "$RES/universe" "$RES/logs"
for f in "$UNIVERSE"/*; do
    cmp -s "$f" "reference/universe/$(basename "$f")" || cp "$f" "$RES/universe/"
done
"$PY" - "$RES/logs" logs/${NAME}_a*.log logs/${NAME}_environment_*.txt logs/${NAME}_crash_fix_*.diff <<'LOGS'
import pathlib, sys
sys.path.insert(0, 'scripts')
from publish_run import clean_log
dest = pathlib.Path(sys.argv[1])
for p in map(pathlib.Path, sys.argv[2:]):
    if p.is_file():
        (dest / p.name).write_text(clean_log(p.read_text(errors='replace')) if p.suffix == '.log' else p.read_text())
LOGS
unchanged
STEP=register
"$PY" scripts/register_trial.py --name $NAME ${PREREG_COMMIT:+--prereg-commit "$PREREG_COMMIT"} \
    --head "$HEAD_COMMIT" --run $RES/v33_pairs --run $RES/v32_pairs \
    --evaluation $RES/evaluation.json ${NOTE:+--note "$NOTE"}
"$PY" scripts/trial_attempts.py completed "$NAME"
echo "complete: $RES/ (commit results/ now)"
