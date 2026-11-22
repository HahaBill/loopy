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

$PY -u experiments/pilot/run_arm.py --config $C --run-name $R --condition cloud_alone --model $T \
    --label "$L" --max-usd 4 >> "$LOGD/console.log" 2>&1
$PY -u experiments/pilot/build_skills.py --config $C --run-name $R --small-model shared --cloud-model $T \
    --only compile --no-student --skills-dir $SK/shared --label "$L" --max-usd 3 >> "$LOGD/console.log" 2>&1

student() {
  S=$1
  O="$LOGD/console_$S.log"
  $PY -u experiments/pilot/run_arm.py --config $C --run-name $R --condition small_alone --model $S \
      --label "$L" --max-usd $2 >> "$O" 2>&1
  $PY -u experiments/pilot/build_coach_checked.py --config $C --run-name $R --small-model $S --cloud-model $T \
      --skills-dir $SK/$S --label "$L" --max-usd $3 >> "$O" 2>&1
  $PY -u experiments/pilot/run_arm.py --config $C --run-name $R --condition coach_checked --model $S \
      --versions 2,3 --skills-dir $SK/$S --label "$L" --max-usd 2 >> "$O" 2>&1
  $PY -u experiments/pilot/run_arm.py --config $C --run-name $R --condition compile --model $S \
      --versions 2,3 --skills-dir $SK/shared --label "$L" --max-usd 1 >> "$O" 2>&1
  echo "student $S done $(date '+%F %T')" >> "$LOGD/console.log"
}

student gemma-3-27b 1.5 2 &
student gpt-oss-120b 2.5 2 &
student minimax-m3.1-flash 2.5 2 &
student deepseek-v4.1-flash 3.5 2.5 &
student qwen3.8-27b 7 3 &
wait
echo "STAGE1 DONE $(date '+%F %T')" >> "$LOGD/console.log"
