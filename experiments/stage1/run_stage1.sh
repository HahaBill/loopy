#!/usr/bin/env bash
# Stage 1, unattended. Teacher and functions first, then the students in parallel.
# Resumable: finished runs are skipped, so running it again continues where it stopped.
set -u
cd "$(dirname "$0")/../.."
export PYTHONIOENCODING=utf-8 PYTHONUTF8=1
PY=.venv/Scripts/python.exe
[ -x "$PY" ] || PY=.venv/bin/python
C=experiments/stage1/config.json
R=stage1
L="STAGE 1"
T=glm-5.3-flash
SK=results/pilot/$R/raw_large/skills
LOGD=results/pilot/$R/raw_large
mkdir -p "$LOGD"
echo "start $(date '+%F %T')" >> "$LOGD/console.log"

# Rerun, once, any task of this arm that ended in an infrastructure error (recorded as repeat 2).
redo_infra() {  # condition model skills-dir log
  local TASKS
  TASKS=$($PY experiments/stage1/sweep.py infra --condition "$1" --model "$2" | tr -d '\r')
  [ -z "$TASKS" ] && return 0
  echo "rerunning infrastructure errors: $1 $2 $TASKS" >> "$4"
  if [ -n "$3" ]; then
    $PY -u experiments/pilot/run_arm.py --config $C --run-name $R --condition "$1" --model "$2" --tasks "$TASKS" \
        --repeat 2 --skills-dir "$3" --label "$L" --max-usd 1 >> "$4" 2>&1
  else
    $PY -u experiments/pilot/run_arm.py --config $C --run-name $R --condition "$1" --model "$2" --tasks "$TASKS" \
        --repeat 2 --label "$L" --max-usd 1 >> "$4" 2>&1
  fi
}

$PY -u experiments/pilot/run_arm.py --config $C --run-name $R --condition cloud_alone --model $T \
    --label "$L" --max-usd 4 >> "$LOGD/console.log" 2>&1
redo_infra cloud_alone $T "" "$LOGD/console.log"
$PY -u experiments/pilot/build_skills.py --config $C --run-name $R --small-model shared --cloud-model $T \
    --only compile --no-student --skills-dir $SK/shared --label "$L" --max-usd 3 >> "$LOGD/console.log" 2>&1
VOIDED=$($PY experiments/stage1/sweep.py voided | tr -d '\r')
if [ -n "$VOIDED" ]; then
  echo "redoing builds cut off by the output limit: $VOIDED" >> "$LOGD/console.log"
  $PY -u experiments/pilot/build_skills.py --config $C --run-name $R --small-model shared --cloud-model $T \
      --only compile --no-student --retry-compile --retry-only "$VOIDED" --skills-dir $SK/shared \
      --label "$L" --max-usd 3 >> "$LOGD/console.log" 2>&1
fi

student() {
  S=$1
  O="$LOGD/console_$S.log"
  $PY -u experiments/pilot/run_arm.py --config $C --run-name $R --condition small_alone --model $S \
      --label "$L" --max-usd $2 >> "$O" 2>&1
  redo_infra small_alone $S "" "$O"
  $PY -u experiments/pilot/build_coach_checked.py --config $C --run-name $R --small-model $S --cloud-model $T \
      --skills-dir $SK/$S --label "$L" --max-usd $3 >> "$O" 2>&1
  $PY -u experiments/pilot/run_arm.py --config $C --run-name $R --condition coach_checked --model $S \
      --versions 2,3 --skills-dir $SK/$S --label "$L" --max-usd 2 >> "$O" 2>&1
  redo_infra coach_checked $S "$SK/$S" "$O"
  $PY -u experiments/pilot/run_arm.py --config $C --run-name $R --condition compile --model $S \
      --versions 2,3 --skills-dir $SK/shared --label "$L" --max-usd 1 >> "$O" 2>&1
  redo_infra compile $S "$SK/shared" "$O"
  echo "student $S done $(date '+%F %T')" >> "$LOGD/console.log"
}

student gemma-3-27b 1.5 2 &
student gpt-oss-120b 2.5 2 &
student minimax-m3.1-flash 2.5 2 &
student deepseek-v4.1-flash 3.5 2.5 &
student qwen3.8-27b 7 3 &
wait
echo "STAGE1 DONE $(date '+%F %T')" >> "$LOGD/console.log"
