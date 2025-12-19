#!/usr/bin/env bash
set -uo pipefail

# Script to run many data collection jobs via script/run_carla_mp_pilot_script.sh
# Usage:
#   ./script/getting_data_training.sh [--dry-run]
# Edit arrays below to change the combinations.
# NOTE: This script continues execution even if individual tasks fail.

DRY_RUN=0
if [[ ${1:-} == "--dry-run" || ${1:-} == "-n" ]]; then
  DRY_RUN=1
  echo "DRY RUN: commands will be printed but not executed"
fi

ROUTE_TYPES=(highway urban simple)
TOWNS=(Town01 Town02 Town03 Town04 Town10 Town11 Town12 Town13)
SPAWN_INDICES=(42 10 25)
DURATIONS=(10 20 30 40 50 120 180 300)
WEATHERS=(ClearNoon CloudyNoon WetNoon WetCloudyNoon SoftRainNoon MidRainyNoon HardRainNoon
        ClearSunset CloudySunset WetSunset WetCloudySunset SoftRainSunset MidRainSunset HardRainSunset
        ClearNight CloudyNight WetNight WetCloudyNight SoftRainNight MidRainyNight HardRainNight DustStorm)

# Agent modes: "no-autopilot-long" -> no flag, "autopilot-long" -> --autopilot-long
AGENTS=(no-autopilot-long autopilot-long)

# Path to wrapper script (relative to repo root)
WRAPPER=script/run_carla_mp_pilot_script.sh

if [[ ! -x "$WRAPPER" && ! -f "$WRAPPER" ]]; then
  echo "Warning: wrapper script $WRAPPER not found in repo root. Adjust WRAPPER path if needed."
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

            CMD=(bash "$WRAPPER" --mode autopilot --duration "$duration" --multicamera --route "$route_type" $AGENT_FLAG --fps 20 --spawn-index "$spawn_idx" --weather "$weather" )

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
