#!/usr/bin/env bash
# Stage 2, part A, gate 2 (experiments/stage2/PROTOCOL_PART_A.md): the students the screen kept, through the stage 1
# arms, in stage 1's order: alone, checked note (build, then test), function, generic-note control. One job per student.
# Resumable: a run on file is skipped; a missing run, or one that ended in an infrastructure error or a spending stop,
# is done again at the next repeat number, at most twice. The hard stop is the provider stop in the config (59.63).
set -u
cd "$(dirname "$0")/../.."
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1
PY=.venv/Scripts/python.exe
[ -x "$PY" ] || PY=.venv/bin/python
C=experiments/stage2/config_part_a_gate2.json
H=experiments/stage2/part_a_gate2.py
R=stage2a
L="STAGE 2 PART A GATE 2"
T=glm-5.3-flash
SK=results/pilot/$R/raw_large/skills
FUNCTIONS=results/pilot/stage1/raw_large/skills/shared
LOGD=results/pilot/$R/raw_large
mkdir -p "$LOGD"

ALONE=$($PY $H tasks --arm alone | tr -d '\r') || { echo "could not list the alone tasks"; exit 2; }
TEST=$($PY $H tasks --arm test | tr -d '\r') || { echo "could not list the test tasks"; exit 2; }
STUDENTS=$($PY $H students | tr -d '\r')
[ -n "$STUDENTS" ] || { echo "the screen kept no student"; exit 2; }
echo "GATE 2 START $(date '+%F %T') students: $STUDENTS" >> "$LOGD/console.log"

arm() {  # condition student tasks guard [skills-dir]
  local EXTRA=()
  [ -n "${5:-}" ] && EXTRA=(--skills-dir "$5")
  $PY -u experiments/pilot/run_arm.py --config $C --run-name $R --condition "$1" --model "$2" --tasks "$3" \
      --label "$L" --max-usd "$4" "${EXTRA[@]}" >> "$O" 2>&1
}

redo() {  # condition student [skills-dir]: runs missing or ended by the provider, the bridge or a spending stop
  local ROUND RETRY REPEAT LIST EXTRA=()
  [ -n "${3:-}" ] && EXTRA=(--skills-dir "$3")
  for ROUND in 1 2; do
    RETRY=$($PY $H retry --condition "$1" --model "$2" | tr -d '\r') || return 1
    [ -n "$RETRY" ] || return 0
    while read -r REPEAT LIST; do
      [ -n "${LIST:-}" ] || continue
      echo "redo $1 $2 repeat $REPEAT: $LIST" >> "$O"
      $PY -u experiments/pilot/run_arm.py --config $C --run-name $R --condition "$1" --model "$2" --tasks "$LIST" \
          --repeat "$REPEAT" --label "$L" --max-usd 0.5 "${EXTRA[@]}" >> "$O" 2>&1
    done <<< "$RETRY"
  done
}

student() {  # student guard-alone guard-build guard-note guard-function guard-control
  local S=$1 READY CONTROL
  O="$LOGD/gate2_$S.log"
  arm small_alone "$S" "$ALONE" "$2"
  redo small_alone "$S"
  READY=$($PY $H ready --model "$S" | tr -d '\r')
  if [ -n "$READY" ]; then
    echo "$S stopped before the note builds: $READY" >> "$LOGD/console.log"
    return 1
  fi
  # Twice: a second start resumes a build whose validation the provider or the bridge interrupted (review item 4).
  for ROUND in 1 2; do
    $PY -u experiments/pilot/build_coach_checked.py --config $C --run-name $R --small-model "$S" --cloud-model $T \
        --skills-dir "$SK/$S" --source-run stage1 --label "$L" --max-usd "$3" >> "$O" 2>&1
  done
  arm coach_checked "$S" "$TEST" "$4" "$SK/$S"
  redo coach_checked "$S" "$SK/$S"
  arm compile "$S" "$TEST" "$5" "$FUNCTIONS"
  redo compile "$S" "$FUNCTIONS"
  CONTROL=$($PY $H control --model "$S" | tr -d '\r') || { echo "$S: no control task list" >> "$LOGD/console.log"; return 1; }
  if [ -n "$CONTROL" ]; then
    arm generic_note "$S" "$CONTROL" "$6"
    redo generic_note "$S"
  fi
  echo "student $S done $(date '+%F %T')" >> "$LOGD/console.log"
}

WORKERS=()
for S in $STUDENTS; do
  case $S in
    nemotron-3-super-120b) student "$S" 3.5 1.5 1.0 1.2 1.0 & ;;
    qwen3-235b-instruct)   student "$S" 3.0 1.5 1.0 1.0 1.0 & ;;
    *) echo "no guards set for $S" >> "$LOGD/console.log"; continue ;;
  esac
  WORKERS+=("$!:$S")
done
FAILED=""
for W in "${WORKERS[@]}"; do
  wait "${W%%:*}" || FAILED="$FAILED ${W#*:}"
done

REASONS=$($PY $H check | tr -d '\r') || REASONS="the gate 2 check did not run"
if [ -z "$REASONS" ]; then
  echo "GATE 2 FINISHED $(date '+%F %T')${FAILED:+ (workers that exited with an error:$FAILED)}" >> "$LOGD/console.log"
else
  echo "GATE 2 INCOMPLETE $(date '+%F %T'): $REASONS${FAILED:+; workers that exited with an error:$FAILED}" >> "$LOGD/console.log"
  exit 1
fi
