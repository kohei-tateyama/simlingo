#!/usr/bin/env bash
set -uo pipefail

# Script to run many data collection jobs via script/run_carla_mp_pilot_script.sh
# Usage:
#   ./script/getting_data_training.sh [--dry-run]
# Edit arrays below to change the combinations.
# NOTE: This script continues execution even if individual tasks fail.

# External SSD mount point and minimum free space threshold
EXTERNAL_SSD="/media/external_ssd"
MIN_FREE_GB=10  # Stop if less than 10GB free

# Function to check disk space
check_disk_space() {
    if [ ! -d "$EXTERNAL_SSD" ]; then
        echo "[WARNING] External SSD not mounted at $EXTERNAL_SSD"
        return 0  # Continue if not using external SSD
    fi
    
    local available_gb=$(df -BG "$EXTERNAL_SSD" | awk 'NR==2 {print $4}' | sed 's/G//')
    local used_percent=$(df "$EXTERNAL_SSD" | awk 'NR==2 {print $5}' | sed 's/%//')
    
    echo "[DISK] External SSD: ${available_gb}GB available (${used_percent}% used)"
    
    if [ "$available_gb" -lt "$MIN_FREE_GB" ]; then
        echo ""
        echo "========================================"
        echo "[ERROR] DISK SPACE CRITICAL!"
        echo "========================================"
        echo "External SSD at $EXTERNAL_SSD has only ${available_gb}GB free"
        echo "Minimum required: ${MIN_FREE_GB}GB"
        echo "Stopping execution to prevent data loss."
        echo "========================================"
        return 1
    fi
    
    return 0
}

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
            # Check disk space before each task
            if ! check_disk_space; then
              echo ""
              echo "[INFO] Stopping batch job due to insufficient disk space."
              echo "[INFO] Completed $SUCCESS_COUNT/$TOTAL_TASKS tasks before stopping."
              exit 2
            fi
            
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

# Final disk space check
check_disk_space || true

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
