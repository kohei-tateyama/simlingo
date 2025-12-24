#!/usr/bin/env bash
set -u -o pipefail

## sudo chown $(id -u):$(id -g) /media/external_ssd
# Script to run many data collection jobs via script/run_carla_mp_pilot_script.sh
# Usage:
#   ./script/getting_data_training.sh [--dry-run]


## For a quick test 
# bash script/getting_data_training_test.sh --dry-run # not running

# export SPAWN_INDICES=(42)
# export DURATIONS=(10)
# bash script/getting_data_training_test.sh

DRY_RUN=0
if [[ ${1:-} == "--dry-run" || ${1:-} == "-n" ]]; then
  DRY_RUN=1
  echo "DRY RUN: commands will be printed but not executed"
fi

ROUTE_TYPES=(highway)
TOWNS=(Town12 Town13)
SPAWN_INDICES=(42)
DURATIONS=(10)
WEATHERS=(ClearNoon CloudyNoon)

# Agent modes: "no-autopilot-long" -> no flag, "autopilot-long" -> --autopilot-long
AGENTS=(no-autopilot-long autopilot-long)

WRAPPER=script/run_carla_mp_pilot_script.sh

if [[ ! -f "$WRAPPER" ]]; then
  echo "Warning: wrapper script $WRAPPER not found. Adjust WRAPPER path if needed."
elif [[ ! -x "$WRAPPER" ]]; then
  echo "Note: wrapper script $WRAPPER exists but is not executable. It will be invoked via 'bash'."
fi

# Small pause between launches to avoid accidental overload
PAUSE_SECS=2

# Track successes and failures
TOTAL_TASKS=0
SUCCESS_COUNT=0
FAILURE_COUNT=0
FAILED_TASKS=()

for agent in "${AGENTS[@]}"; do
  for town in "${TOWNS[@]}"; do
    for route_type in "${ROUTE_TYPES[@]}"; do
      for weather in "${WEATHERS[@]}"; do
        for spawn_idx in "${SPAWN_INDICES[@]}"; do
          for duration in "${DURATIONS[@]}"; do
            AGENT_FLAG=""
            if [[ "$agent" == "autopilot-long" ]]; then
              AGENT_FLAG="--autopilot-long"
            fi

            # Build command array; append AGENT_FLAG only when non-empty to avoid word-splitting
            CMD=(bash "$WRAPPER" --mode autopilot --duration "$duration" --multicamera --route "$route_type" --fps 20 --spawn-index "$spawn_idx" --weather "$weather")
            if [[ -n "$AGENT_FLAG" ]]; then
              CMD+=("$AGENT_FLAG")
            fi

            # Print command for logging / review
            TASK_ID="town=$town route=$route_type weather=$weather spawn=$spawn_idx duration=${duration}s agent=$agent"
            echo "[RUN] $TASK_ID"
            echo "      ${CMD[*]}"

            TOTAL_TASKS=$((TOTAL_TASKS + 1))

            if [[ $DRY_RUN -eq 0 ]]; then
              # Execute with error handling - continue even if this task fails
              if "${CMD[@]}"; then
                SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
                echo "[SUCCESS] Task completed: $TASK_ID"
              else
                EXIT_CODE=$?
                FAILURE_COUNT=$((FAILURE_COUNT + 1))
                FAILED_TASKS+=("$TASK_ID (exit code: $EXIT_CODE)")
                echo "[FAILED] Task failed with exit code $EXIT_CODE: $TASK_ID"
                echo "[INFO] Continuing with remaining tasks..."
              fi
              sleep $PAUSE_SECS
            fi

          done
        done
      done
    done
  done
done

echo ""
echo "========================================"
echo "All jobs processed."
echo "========================================"
echo "Total tasks: $TOTAL_TASKS"
echo "Successful:  $SUCCESS_COUNT"
echo "Failed:      $FAILURE_COUNT"

if [[ $FAILURE_COUNT -gt 0 ]]; then
  echo ""
  echo "Failed tasks:"
  for failed_task in "${FAILED_TASKS[@]}"; do
    echo "  - $failed_task"
  done
  echo ""
  echo "NOTE: Script completed with $FAILURE_COUNT failure(s)"
  exit 1
else
  echo ""
  echo "All tasks completed successfully!"
  exit 0
fi
