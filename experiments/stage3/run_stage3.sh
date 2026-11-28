#!/usr/bin/env bash
# Stage 3 (experiments/stage3/PROTOCOL.md, designed by Alfredo Frontera): part A's pipeline with an OpenAI teacher and
# the same four students. One command, unattended. Resumable: if it stops for any reason, run it again; finished runs
# are skipped. The students' solo runs are reused from stage 1 and part A, so they are not run here.
set -u
cd "$(dirname "$0")/../.."
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1
PY=.venv/Scripts/python.exe
[ -x "$PY" ] || PY=.venv/bin/python
C=experiments/stage3/config.json
H=experiments/stage3/stage3.py
R=stage3
L="STAGE 3 OPENAI TEACHER"
T=gpt-6.2-sol
SK=results/pilot/$R/raw_large/skills
LOGD=results/pilot/$R/raw_large
OUT=results/pilot/$R/analysis_stage3.json
mkdir -p "$LOGD"
trap 'trap - INT TERM; echo "stopping stage 3 and its workers"; kill 0' INT TERM  # Ctrl-C stops every job it started

helper() {  # runs the stage 3 helper; fails when it fails; drops Windows line ends from what it prints
  local TEXT
  TEXT=$($PY $H "$@") || return 1
  printf '%s' "${TEXT//$'\r'/}"
}

stop() {  # message: ends the run, written to the console log and the screen
  echo "STAGE 3 STOPPED $(date '+%F %T'): $1" | tee -a "$LOGD/console.log"
  exit 1
}

$PY $H preflight --ping || { echo "Preflight failed, so nothing was run. Fix what it says and run this again."; exit 2; }
START=$(date '+%Y-%m-%d %H:%M:%S')
echo "STAGE 3 START $START" >> "$LOGD/console.log"

run() {  # log file, then the arguments for run_arm.py
  local O=$1
  shift
  $PY -u experiments/pilot/run_arm.py --config $C --run-name $R --label "$L" "$@" >> "$O" 2>&1
}

arm() {  # log condition model guard [skills-dir]: runs what is missing, then redoes what the provider, the bridge
         # or a spending stop ended, at most twice
  local O=$1 COND=$2 M=$3 G=$4 SKD=${5:-} ROUND RETRY REPEAT LIST
  local EXTRA=()
  [ -n "$SKD" ] && EXTRA=(--skills-dir "$SKD")
  for ROUND in 1 2 3; do
    RETRY=$(helper retry --condition "$COND" --model "$M") || return 1
    [ -n "$RETRY" ] || return 0
    while read -r REPEAT LIST; do
      [ -n "${LIST:-}" ] || continue
      echo "run $COND $M repeat $REPEAT: $LIST" >> "$O"
      run "$O" --condition "$COND" --model "$M" --tasks "$LIST" --repeat "$REPEAT" --max-usd "$G" "${EXTRA[@]}"
    done <<< "$RETRY"
  done
}

# The teacher: 3 calibration runs fixed in advance and a check that the stage fits the money and the output limit (once:
# a passed check is kept), then the rest of its 69 solo runs (renting), then one function per scenario it passed.
O="$LOGD/teacher.log"
if [ ! -f results/pilot/$R/calibration.json ]; then
  for ROUND in 1 2 3; do
    RETRY=$(helper calibration-retry) || stop "the helper did not run"
    [ -n "$RETRY" ] || break
    while read -r REPEAT LIST; do
      [ -n "${LIST:-}" ] || continue
      run "$O" --condition cloud_alone --model $T --tasks "$LIST" --repeat "$REPEAT" --max-usd 6
    done <<< "$RETRY"
  done
fi
if ! PROJECTION=$($PY $H project); then
  PROJECTION=${PROJECTION//$'\r'/}
  stop "after the teacher's calibration runs: ${PROJECTION//$'\n'/ }. Nothing more was spent; tell Alfredo."
fi
echo "projection: ${PROJECTION//$'\r'/}" >> "$LOGD/console.log"
arm "$O" cloud_alone $T 45 || stop "the helper did not run"
NOT_READY=$(helper ready --model $T) || stop "the helper did not run"
[ -z "$NOT_READY" ] || stop "teacher runs not finished: $NOT_READY"
for ROUND in 1 2; do  # a second start resumes a build whose check the bridge or the provider interrupted
  $PY -u experiments/pilot/build_skills.py --config $C --run-name $R --small-model shared --cloud-model $T \
      --only compile --no-student --skills-dir $SK/shared --label "$L" --max-usd 20 >> "$O" 2>&1
done
NOT_READY=$(helper ready --functions) || stop "the helper did not run"
[ -z "$NOT_READY" ] || stop "function builds not finished: $NOT_READY"

student() {  # student guard-builds guard-note guard-function guard-control
  local S=$1 SRC O ROUND
  SRC=$(helper source --model "$S") || return 1
  O="$LOGD/student_$S.log"
  for ROUND in 1 2; do  # a second start resumes a build whose check the provider or the bridge interrupted
    $PY -u experiments/pilot/build_coach_checked.py --config $C --run-name $R --small-model "$S" --cloud-model $T \
        --skills-dir "$SK/$S" --source-run "$SRC" --label "$L" --max-usd "$2" >> "$O" 2>&1
  done
  arm "$O" coach_checked "$S" "$3" "$SK/$S" || return 1
  arm "$O" compile "$S" "$4" "$SK/shared" || return 1
  arm "$O" generic_note "$S" "$5" || return 1
  echo "student $S done $(date '+%F %T')" >> "$LOGD/console.log"
}

WORKERS=()
student gpt-oss-120b 6 1.5 1 2 &
WORKERS+=("$!:gpt-oss-120b")
student gemma-3-27b 5 1.5 1 1.5 &
WORKERS+=("$!:gemma-3-27b")
student minimax-m3.1-flash 12 5 3 6 &
WORKERS+=("$!:minimax-m3.1-flash")
student nemotron-3-super-120b 6 3 1.5 3 &
WORKERS+=("$!:nemotron-3-super-120b")
FAILED=""
for W in "${WORKERS[@]}"; do
  wait "${W%%:*}" || FAILED="$FAILED ${W#*:}"
done

if ! REASONS=$(helper check); then
  STATUS="STAGE 3 INCOMPLETE: the completeness check did not run"
elif [ -n "$REASONS" ]; then
  STATUS="STAGE 3 INCOMPLETE: $REASONS"
elif { [ -f "$OUT" ] && $PY $H verify-result --out "$OUT"; } || { [ ! -f "$OUT" ] && $PY $H analyze --out "$OUT" > /dev/null; }; then
  STATUS="STAGE 3 FINISHED; result written to $OUT, not printed"
else
  STATUS="STAGE 3 INCOMPLETE: every run is on file but the analysis failed"
fi
echo "$STATUS $(date '+%F %T')${FAILED:+ (workers that exited with an error:$FAILED)}" >> "$LOGD/console.log"
$PY $H log-row --status "$STATUS" --start "$START" > /dev/null || echo "the LOG.md row could not be written"
echo "$STATUS"
case "$STATUS" in
  "STAGE 3 FINISHED"*)
    echo "Next: python experiments/stage3/stage3.py privacy (it must print nothing), then commit results/pilot/stage3,"
    echo "LOG.md, results/spend_ledger.jsonl and experiments/stage3/config.json to a branch and push it."
    echo "raw_large stays on your machine."
    exit 0 ;;
  *) exit 1 ;;
esac
