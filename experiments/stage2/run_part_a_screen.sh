#!/usr/bin/env bash
# Stage 2, part A, gate 1 (experiments/stage2/PROTOCOL_PART_A.md): four candidate students alone on 12 version 1 tasks.
# One job per candidate. Resumable: a run on file is skipped, and a run that ended in an infrastructure error is redone
# at the next repeat number, at most twice. A candidate cut short by a spending stop is out and is not redone.
set -u
cd "$(dirname "$0")/../.."
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1
PY=.venv/Scripts/python.exe
[ -x "$PY" ] || PY=.venv/bin/python
C=experiments/stage2/config_part_a.json
R=stage2a
L="STAGE 2 PART A SCREEN"
LOGD=results/pilot/$R/raw_large
mkdir -p "$LOGD"

TASKS=$($PY experiments/stage2/part_a.py tasks) || { echo "could not list the screen tasks"; exit 2; }
TASKS=$(printf '%s' "$TASKS" | tr -d '\r')
[ -n "$TASKS" ] || { echo "no screen tasks"; exit 2; }
echo "SCREEN START $(date '+%F %T')" >> "$LOGD/console.log"

candidate() {
  S=$1
  GUARD=$2
  O="$LOGD/screen_$S.log"
  RC=0
  $PY -u experiments/pilot/run_arm.py --config $C --run-name $R --condition small_alone --model "$S" \
      --tasks "$TASKS" --label "$L" --max-usd "$GUARD" >> "$O" 2>&1 || RC=$?
  for ROUND in 1 2; do
    RETRY=$($PY experiments/stage2/part_a.py retry --model "$S") || { RC=1; break; }
    RETRY=$(printf '%s' "$RETRY" | tr -d '\r')
    [ -n "$RETRY" ] || break
    while read -r REPEAT LIST; do
      [ -n "${LIST:-}" ] || continue
      $PY -u experiments/pilot/run_arm.py --config $C --run-name $R --condition small_alone --model "$S" \
          --tasks "$LIST" --repeat "$REPEAT" --label "$L" --max-usd 0.3 >> "$O" 2>&1 || RC=$?
    done <<< "$RETRY"
  done
  return $RC
}

WORKERS=()
for PAIR in qwen3-235b-instruct:1.2 nemotron-3-super-120b:1.2 inkling-2-small:1.2 nemotron-3.5-lightning:0.4; do
  candidate "${PAIR%%:*}" "${PAIR#*:}" &
  WORKERS+=("$!:${PAIR%%:*}")
done
FAILED=""
for W in "${WORKERS[@]}"; do
  wait "${W%%:*}" || FAILED="$FAILED ${W#*:}"
done

REASONS=$($PY experiments/stage2/part_a.py check) || REASONS="the screen check did not run"
REASONS=$(printf '%s' "$REASONS" | tr -d '\r')
if [ -z "$REASONS" ]; then
  echo "SCREEN FINISHED $(date '+%F %T')${FAILED:+ (workers that exited with an error:$FAILED)}" >> "$LOGD/console.log"
else
  echo "SCREEN INCOMPLETE $(date '+%F %T'): $REASONS${FAILED:+; workers that exited with an error:$FAILED}" >> "$LOGD/console.log"
  exit 1
fi
