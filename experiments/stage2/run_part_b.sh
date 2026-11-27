#!/usr/bin/env bash
# Stage 2, part B (experiments/stage2/PROTOCOL.md): the compile arm's function handed over as text in a note.
# One job per lower-tier student. Resumable: a run on file is skipped, and a run that the provider, the bridge or a
# spending stop ended is redone at the next repeat number.
set -u
cd "$(dirname "$0")/../.."
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1
PY=.venv/Scripts/python.exe
[ -x "$PY" ] || PY=.venv/bin/python
C=experiments/stage2/config.json
R=stage2b
L="STAGE 2 PART B"
SK=results/pilot/stage1/raw_large/skills/shared
LOGD=results/pilot/$R/raw_large
mkdir -p "$LOGD"

TASKS=$($PY experiments/stage2/part_b.py tasks) || { echo "could not list the part B tasks"; exit 2; }
TASKS=$(printf '%s' "$TASKS" | tr -d '\r')
[ -n "$TASKS" ] || { echo "no part B tasks"; exit 2; }

student() {
  S=$1
  GUARD=$2
  O="$LOGD/part_b_$S.log"
  RC=0
  $PY -u experiments/pilot/run_arm.py --config $C --run-name $R --condition code_note --model "$S" \
      --tasks "$TASKS" --skills-dir $SK --label "$L" --max-usd "$GUARD" >> "$O" 2>&1 || RC=$?
  for ROUND in 1 2; do
    RETRY=$($PY experiments/stage2/part_b.py retry --model "$S") || { RC=1; break; }
    RETRY=$(printf '%s' "$RETRY" | tr -d '\r')
    [ -n "$RETRY" ] || break
    while read -r REPEAT LIST; do
      [ -n "${LIST:-}" ] || continue
      $PY -u experiments/pilot/run_arm.py --config $C --run-name $R --condition code_note --model "$S" \
          --tasks "$LIST" --repeat "$REPEAT" --skills-dir $SK --label "$L" --max-usd 1 >> "$O" 2>&1 || RC=$?
    done <<< "$RETRY"
  done
  return $RC
}

WORKERS=()
for PAIR in gemma-3-27b:2 gpt-oss-120b:2 minimax-m3.1-flash:5; do
  student "${PAIR%%:*}" "${PAIR#*:}" &
  WORKERS+=("$!:${PAIR%%:*}")
done
FAILED=""
for W in "${WORKERS[@]}"; do
  wait "${W%%:*}" || FAILED="$FAILED ${W#*:}"
done

REASONS=$($PY experiments/stage2/part_b.py check) || REASONS="the part B check did not run"
REASONS=$(printf '%s' "$REASONS" | tr -d '\r')
if [ -z "$REASONS" ]; then
  echo "PART B FINISHED $(date '+%F %T')${FAILED:+ (every run is on file; workers that exited with an error:$FAILED)}" >> "$LOGD/console.log"
else
  echo "PART B INCOMPLETE $(date '+%F %T'): $REASONS${FAILED:+; workers that exited with an error:$FAILED}" >> "$LOGD/console.log"
  exit 1
fi
