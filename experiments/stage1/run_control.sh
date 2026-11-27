#!/usr/bin/env bash
# The generic-note control of stage 1 (PROTOCOL.md). Runs only after STAGE1 DONE. Resumable.
# Each student gets the fixed general note on the test tasks of the primary analysis.
set -u
cd "$(dirname "$0")/../.."
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1
PY=.venv/Scripts/python.exe
[ -x "$PY" ] || PY=.venv/bin/python
C=experiments/stage1/config.json
R=stage1
L="STAGE 1 CONTROL"
LOGD=results/pilot/$R/raw_large
grep -aq '^STAGE1 DONE' "$LOGD/console.log" || { echo "stage 1 is not done; the control waits"; exit 2; }
# The DONE line is history. The rows on file now decide whether stage 1 is complete. This check reads stage 1's own
# runs and builds, not the control's runs: a control run that was cut short is repaired below, by control-retry.
NOT_READY=$($PY experiments/stage1/sweep.py check) || { echo "the stage 1 check did not run; the control waits"; exit 2; }
NOT_READY=$(printf '%s' "$NOT_READY" | tr -d '\r')
[ -n "$NOT_READY" ] && { echo "stage 1 is not complete on file; the control waits: $NOT_READY"; exit 2; }

control() {
  S=$1
  O="$LOGD/control_$S.log"
  RC=0
  TASKS=$($PY experiments/stage1/sweep.py control --model "$S") || { echo "could not list control tasks for $S" >> "$O"; return 1; }
  TASKS=$(printf '%s' "$TASKS" | tr -d '\r')
  [ -z "$TASKS" ] && { echo "no control tasks for $S" >> "$O"; return 0; }
  $PY -u experiments/pilot/run_arm.py --config $C --run-name $R --condition generic_note --model "$S" \
      --tasks "$TASKS" --label "$L" --max-usd 4 >> "$O" 2>&1 || RC=$?
  # Once per start, run again the control tasks whose latest run did not count: an infrastructure error or a
  # spend-limit stop, at any repeat. Each is recorded at its latest repeat plus one, so no row is skipped as done.
  RETRY=$($PY experiments/stage1/sweep.py control-retry --model "$S") || RC=$?
  while read -r REPEAT AGAIN; do
    [ -z "$AGAIN" ] && continue
    $PY -u experiments/pilot/run_arm.py --config $C --run-name $R --condition generic_note --model "$S" \
        --tasks "$AGAIN" --repeat "$REPEAT" --label "$L" --max-usd 1 >> "$O" 2>&1 < /dev/null || RC=$?
  done <<< "$(printf '%s' "$RETRY" | tr -d '\r')"
  return $RC
}

WORKERS=()
for S in gemma-3-27b gpt-oss-120b minimax-m3.1-flash deepseek-v4.1-flash qwen3.8-27b; do
  control "$S" &
  WORKERS+=("$!:$S")
done
FAILED=""
for W in "${WORKERS[@]}"; do
  wait "${W%%:*}" || FAILED="$FAILED ${W#*:}"
done

# A worker can exit cleanly with tasks left (a spend limit ends it without an error), so the rows on file decide:
# every control task of every student needs a latest run that is not an infrastructure error or a spend-limit stop.
REASONS=$($PY experiments/stage1/sweep.py control-check) || REASONS="the control check did not run"
REASONS=$(printf '%s' "$REASONS" | tr -d '\r')
if [ -z "$REASONS" ]; then
  echo "CONTROL FINISHED $(date '+%F %T')${FAILED:+ (every control run is on file; workers that exited with an error:$FAILED)}" >> "$LOGD/console.log"
else
  echo "CONTROL INCOMPLETE $(date '+%F %T'): $REASONS${FAILED:+; workers that exited with an error:$FAILED}" >> "$LOGD/console.log"
  exit 1
fi
