#!/usr/bin/env bash
set -euo pipefail

# Script to run many data collection jobs via script/run_carla_mp_pilot_script.sh
# Usage:
#   ./script/getting_data_training.sh [--dry-run]
# Edit arrays below to change the combinations.

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

# Agent modes: "no-agent-long" -> no flag, "agent-long" -> --agent-long
AGENTS=(no-agent-long agent-long)

# Path to wrapper script (relative to repo root)
WRAPPER=script/run_carla_mp_pilot_script.sh

if [[ ! -x "$WRAPPER" && ! -f "$WRAPPER" ]]; then
  echo "Warning: wrapper script $WRAPPER not found in repo root. Adjust WRAPPER path if needed."
fi

# Small pause between launches to avoid accidental overload
PAUSE_SECS=2

for agent in "${AGENTS[@]}"; do
  for town in "${TOWNS[@]}"; do
    for route_type in "${ROUTE_TYPES[@]}"; do
      for weather in "${WEATHERS[@]}"; do
        for spawn_idx in "${SPAWN_INDICES[@]}"; do
          for duration in "${DURATIONS[@]}"; do
            AGENT_FLAG=""
            if [[ "$agent" == "agent-long" ]]; then
              AGENT_FLAG="--agent-long"
            fi

            CMD=(bash "$WRAPPER" --mode autopilot --duration "$duration" --multicamera --route "$route_type" $AGENT_FLAG --fps 20 --spawn-index "$spawn_idx" --weather "$weather" )

            # Print command for logging / review
            echo "[RUN] town=$town route=$route_type weather=$weather spawn=$spawn_idx duration=${duration}s agent=$agent"
            echo "      ${CMD[*]}"

            if [[ $DRY_RUN -eq 0 ]]; then
              # Execute
              "${CMD[@]}"
              sleep $PAUSE_SECS
            fi

          done
        done
      done
    done
  done
done

echo "All jobs processed."
