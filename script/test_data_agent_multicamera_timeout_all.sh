#!/bin/bash

# Test script for data_agent_multicamera.py - based on data_agent.py - with leaderboard evaluation
# Based on script/run_carla_mp_pilot_script.sh

set -u

# =============================================================================
# ENVIRONMENT SETUP
# =============================================================================
export CARLA_ROOT=/workspace/carla0915
export WORK_DIR=/workspace/simlingo
export SCENARIO_RUNNER_ROOT=${WORK_DIR}/scenario_runner
export LEADERBOARD_ROOT=${WORK_DIR}/leaderboard
export PYTHONPATH="${WORK_DIR}:${CARLA_ROOT}/PythonAPI/carla:${CARLA_ROOT}/PythonAPI:${SCENARIO_RUNNER_ROOT}:${LEADERBOARD_ROOT}"


# Data collection settings
# export SAVE_PATH=/workspace/simlingo/database/simlingo_v4_bosch_2025_01_10/data/simlingo
export DATAGEN=1
export TEAM_AGENT=/workspace/simlingo/team_code/data_agent_multicamera.py
export TEAM_CONFIG="data_collection"
export SAVE_PATH=/media/external_ssd/workspace/simlingo/database/simlingo_v4_bosch_2025_01_10/data/simlingo_right_drive
# export SAVE_PATH=/workspace/simlingo/database/simlingo_v4_bosch_2025_01_10/data/simlingo
export TOWN="Town03"  # Will be overridden by route XML
export REPETITION="0" # "3"
export SCENARIO_NAME="training_3_scenarios" # (test_town12, validation_1_scenario, training_3_scenarios, training_full)
export WEATHER_CONFIG="random_weather_seed_42_balanced_100" # (random_weather_seed_3_balanced_100, clear_noon, clear_sunset, rainy_night, balanced_weather_variations)

export ROUTES_SUBSET="0,1" 

export ROUTE_CONFIG="bench2drive220" # bench2drive220, routes_training, routes_validation (routes_town12_only, routes_devtest, routes_validation, routes_all)
# export ROUTES="/workspace/simlingo/leaderboard/data/routes_training.xml"
# export ROUTES="/workspace/simlingo/leaderboard/data/routes_validation.xml"
# export ROUTES="/workspace/simlingo/leaderboard/data/routes_devtest.xml"
export ROUTES="/workspace/simlingo/leaderboard/data/bench2drive220.xml"
# export ROUTES="/workspace/simlingo/leaderboard/data/town_maps_t7/Town05.t7" # (similar, check this TODO)

# LEADERBOARD_TIMEOUT="${LEADERBOARD_TIMEOUT:-0}" 
# Checkpoint file for leaderboard (also exported so agents can read it)
CHECKPOINT_FILENAME="results_japanese_test.json"
export LEADERBOARD_CHECKPOINT=${LEADERBOARD_CHECKPOINT:-${LEADERBOARD_ROOT}/${CHECKPOINT_FILENAME}}

LEADERBOARD_TIMEOUT="${LEADERBOARD_TIMEOUT:-120}"

# Activate conda environment
source ~/miniconda3/etc/profile.d/conda.sh
conda activate simlingo

# CARLA port (can be overridden by environment before running the script)
export PORT_CARLA=${PORT_CARLA:-2001}
# Traffic Manager port (can be overridden)
export TRAFFIC_MANAGER_PORT=${TRAFFIC_MANAGER_PORT:-8000}

# Color helpers
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
BLUE="\033[0;34m"
RESET="\033[0m"

info() { echo -e "${GREEN}[INFO]${RESET} $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET} $*"; }
err() { echo -e "${RED}[ERROR]${RESET} $*"; }
sep() { printf "%b\n" "${BLUE}$(printf '=%.0s' {1..80})${RESET}"; }

# =============================================================================
# CLEANUP FUNCTION
# =============================================================================
cleanup_carla() {
    sep
    info "Cleaning up CARLA and leaderboard..."
    sep

    # Kill Python leaderboard processes
    pkill -9 -f "leaderboard_evaluator.py" 2>/dev/null || true

    # Kill processes on CARLA port
    pids=$(lsof -ti:${PORT_CARLA} 2>/dev/null)
    if [ ! -z "$pids" ]; then
        warn "Killing processes on port ${PORT_CARLA}: $pids"
        kill -9 $pids 2>/dev/null || true
    fi
    
    # Kill processes on traffic-manager port
    pids=$(lsof -ti:${TRAFFIC_MANAGER_PORT} 2>/dev/null)
    if [ ! -z "$pids" ]; then
        warn "Killing processes on port ${TRAFFIC_MANAGER_PORT}: $pids"
        kill -9 $pids 2>/dev/null || true
    fi

    # Stop Docker container
    info "Stopping CARLA Docker container..."
    docker rm -f carla-server 2>/dev/null || true

    sleep 3

    # Verify CARLA port is free
    if lsof -ti:${PORT_CARLA} &>/dev/null; then
        err "Port ${PORT_CARLA} still in use!"
        lsof -i:${PORT_CARLA}
    fi
    if lsof -ti:${TRAFFIC_MANAGER_PORT} &>/dev/null; then
        err "Port ${TRAFFIC_MANAGER_PORT} still in use!"
        lsof -i:${TRAFFIC_MANAGER_PORT}
    fi
    
    info "Cleanup complete ✓"
}

stop_carla() {
    info "Stopping CARLA container..."
    docker stop carla-server 2>/dev/null || true
    docker rm -f carla-server 2>/dev/null || true
}

# Trap for cleanup on exit
cleanup_on_exit() {
    local exit_code=$?
    echo ""
    warn "Script exiting (code: $exit_code) - cleaning up..."
    stop_carla 2>/dev/null || true
    exit $exit_code
}

trap cleanup_on_exit EXIT INT TERM

# Ensure SAVE_SUBDIR defaults to SCENARIO_NAME/ROUTE_CONFIG when not provided
if [ -z "${SAVE_SUBDIR:-}" ]; then
    if [ "${SAVE_FLAT:-0}" = "1" ]; then
        export SAVE_SUBDIR="${ROUTE_CONFIG}"
    else
        export SAVE_SUBDIR="${SCENARIO_NAME}/${ROUTE_CONFIG}"
    fi
    info "Default SAVE_SUBDIR set to: ${SAVE_SUBDIR}"
fi

# =============================================================================
# START CARLA
# =============================================================================
start_carla() {
    mkdir -p ${SAVE_PATH}
    mkdir -p ${WORK_DIR}/carla_logs

    sep
    info "CARLA_ROOT: $CARLA_ROOT"
    info "SAVE_PATH : $SAVE_PATH"
    sep

    # Check for custom CARLA image
    if ! docker images | grep -q "carla-bench2drive.*0.9.15"; then
        err "Custom CARLA image 'carla-bench2drive:0.9.15' not found!"
        warn "Please build it first: bash /workspace/simlingo/build_carla_bench2drive_docker.sh"
        exit 1
    fi

    sep
    info "Starting CARLA 0.9.15 HEADLESS on port ${PORT_CARLA}"
    sep

    # Remove any existing container
    docker rm -f carla-server 2>/dev/null || true

    # Start CARLA in headless mode
    docker run -d \
        --name carla-server \
        --runtime=nvidia \
        --gpus all \
        --net=host \
        --shm-size=1g \
        --env=NVIDIA_VISIBLE_DEVICES=all \
        --env=NVIDIA_DRIVER_CAPABILITIES=all \
        -v ${WORK_DIR}/carla_logs:/home/carla/CarlaUE4/Saved/Logs \
        carla-bench2drive:0.9.15 \
        bash -c "cd /home/carla && ./CarlaUE4.sh -opengl -RenderOffScreen -nosound -world-port=${PORT_CARLA} -carla-rpc-port=${PORT_CARLA} -log"

    info "Waiting 80s for CARLA to start..."
    sleep 80

    # Check container is running
    if ! docker ps | grep -q carla-server; then
        echo ""
        err "CARLA container crashed!"
        sep
        docker logs carla-server 2>&1
        sep
        exit 1
    fi

    info "CARLA container is running"
    info "Testing CARLA connection..."
    sep

    python - <<'PY'
import carla
import sys
import os

try:
    port = int(os.environ.get('PORT_CARLA', '${PORT_CARLA}'))
    client = carla.Client('localhost', port)
    client.set_timeout(30.0)
    world = client.get_world()
    version = client.get_server_version()
    
    print(f'✓ CARLA connection successful')
    print(f'✓ Server version: {version}')
    
    if version != '0.9.15':
        print(f'ERROR: Expected 0.9.15, got {version}')
        sys.exit(1)
        
except Exception as e:
    print(f'ERROR: Connection failed: {e}')
    sys.exit(1)
PY

    if [ $? -ne 0 ]; then
        err "CARLA verification failed"
        exit 1
    fi

    sep
    info "CARLA ready!"
    sep
}

# =============================================================================
# RUN LEADERBOARD EVALUATION
# =============================================================================
run_leaderboard() {
    sep
    info "Running data_agent_multicamera.py via leaderboard"
    sep

    cd /workspace/simlingo/leaderboard

    info "Agent    : ${TEAM_AGENT}"
    info "Routes   : ${ROUTES}"
    info "Port     : ${PORT_CARLA}"
    info "Output   : ${SAVE_PATH}"
    sep
    # Build base args (we'll append --routes-subset per route when iterating)
    BASE_ARGS=(--routes=${ROUTES} --repetitions=1 --agent=${TEAM_AGENT} --agent-config=${TEAM_CONFIG} --checkpoint=${LEADERBOARD_CHECKPOINT} --port=${PORT_CARLA} --traffic-manager-port=${TRAFFIC_MANAGER_PORT})

    # If ROUTES_SUBSET is empty or '0', build a default list of all ids from routes file
    if [ -z "${ROUTES_SUBSET:-}" ] || [ "${ROUTES_SUBSET}" = "0" ]; then
        ROUTES_SUBSET=$(python - <<'PY'
import xml.etree.ElementTree as ET, os
routes_file = os.environ.get('ROUTES','')
if not routes_file or not os.path.exists(routes_file):
    print('', end='')
    raise SystemExit(0)
tree = ET.parse(routes_file)
root = tree.getroot()
ids = [r.get('id') for r in root.findall('.//route') if r.get('id')]
print(','.join(ids), end='')
PY
)
    fi

    # Normalize ROUTES_SUBSET by removing whitespace and split into array
    ROUTES_SUBSET=$(echo "${ROUTES_SUBSET}" | tr -d '[:space:]')
    IFS=',' read -ra ROUTE_IDS <<< "${ROUTES_SUBSET}"

    # Ensure SAVE_SUBDIR does not include the per-route id; agent will embed route id
    if [ -n "${ROUTES_SUBSET:-}" ] && [ "${ROUTES_SUBSET}" != "0" ]; then
        ROUTES_SUB_CLEAN=$(echo "${ROUTES_SUBSET}" | tr -d '[:space:]' | tr ',' '_')
        if [ "${SAVE_FLAT:-0}" = "1" ]; then
            export SAVE_SUBDIR="${ROUTES_SUB_CLEAN}"
        else
            export SAVE_SUBDIR="${SCENARIO_NAME}/${ROUTE_CONFIG}"
        fi
        info "Setting SAVE_SUBDIR to: ${SAVE_SUBDIR} (route ids excluded)"
    fi

    total_routes=${#ROUTE_IDS[@]}
    current_route=0
    overall_exit=0

    for route_id in "${ROUTE_IDS[@]}"; do
        current_route=$((current_route + 1))
        sep
        info "Running route ${route_id} (${current_route}/${total_routes})"
        sep

        # Trim whitespace defensively
        route_id=$(echo "${route_id}" | xargs)
        export FORCE_ROUTE_ID="${route_id}"
        ARGS=("${BASE_ARGS[@]}" --routes-subset=${route_id})

        if [ "${LEADERBOARD_TIMEOUT:-0}" -eq 0 ]; then
            python leaderboard/leaderboard_evaluator.py "${ARGS[@]}"
        else
            # Use a wrapper that kills the process group on SIGTERM and allows a short -k grace period
            timeout -k 10 "${LEADERBOARD_TIMEOUT}" bash -c 'trap "kill 0" SIGTERM; exec "$@"' -- python leaderboard/leaderboard_evaluator.py "${ARGS[@]}"
        fi

        exit_code=$?

        sep
        if [ $exit_code -eq 0 ]; then
            info "✓ Route ${route_id} completed successfully!"
            FOUND_OUTPUT=1
        else
            FOUND_OUTPUT=0
            if find "${SAVE_PATH}" -maxdepth 6 -type f -name "results.json.gz" -print -quit | grep -q .; then
                FOUND_OUTPUT=1
            elif find "${SAVE_PATH}" -maxdepth 6 -type f -name "records.json.gz" -print -quit | grep -q .; then
                FOUND_OUTPUT=1
            fi

            if [ $FOUND_OUTPUT -eq 1 ]; then
                warn "Route ${route_id} exited with code ${exit_code} but saved output files — treating as success"
                exit_code=0
            elif [ $exit_code -eq 124 ]; then
                warn "Route ${route_id} timeout reached (${LEADERBOARD_TIMEOUT}s) - checking for partial data..."
                if [ $FOUND_OUTPUT -eq 1 ]; then
                    exit_code=0
                fi
            else
                warn "Route ${route_id} exited with code $exit_code"
            fi
        fi

        if [ $exit_code -ne 0 ]; then
            overall_exit=$exit_code
        fi

        # Patch per-route if data exists
        if [ $exit_code -eq 0 ] || [ $FOUND_OUTPUT -eq 1 ]; then
            info "Patching multicamera images for route ${route_id}..."
            patch_multicamera_images
            patch_exit=$?
            if [ $patch_exit -ne 0 ]; then
                warn "Image patching failed for route ${route_id}"
            fi
            cd /workspace/simlingo/leaderboard
        else
            warn "Skipping patching for route ${route_id} (no data collected)"
        fi

    done

    sep
    if [ $overall_exit -eq 0 ]; then
        info "All ${total_routes} routes completed successfully!"
    else
        warn "Some routes encountered errors (exit code: ${overall_exit})"
    fi
    sep

    return $overall_exit
}

# =============================================================================
# POST-PROCESS: PATCH MULTICAMERA IMAGES
# =============================================================================
patch_multicamera_images() {
    sep
    info "Post-processing: Patching multicamera RGB images..."
    sep
    
    info "Searching for datasets under: ${SAVE_PATH}"
    
    # Prefer .last_run sentinel written by the agent during the run
    if [ -f "${SAVE_PATH}/.last_run" ]; then
        DATASET_PATH=$(cat "${SAVE_PATH}/.last_run")
        info "Found .last_run sentinel: ${DATASET_PATH}"
    else
        # Find the most recent dataset directory. Look for Town*_Rep* folders that contain rgb/ subfolder
        # Use maxdepth 5 to reach: {SAVE_PATH}/{scenario}/{route_config}/{weather}/{Town}_Rep*
        DATASET_PATH=$(find ${SAVE_PATH} -maxdepth 5 -type d -name "Town*_Rep*" 2>/dev/null | while read dir; do
            if [ -d "$dir/rgb" ] && [ -d "$dir/measurements" ]; then
                echo "$dir"
            fi
        done | sort -r | head -1)
    fi
    
    # Fallback: try without measurements check
    if [ -z "$DATASET_PATH" ]; then
        info "Trying fallback pattern..."
        DATASET_PATH=$(find ${SAVE_PATH} -maxdepth 5 -type d -name "Town*_Rep*" 2>/dev/null | while read dir; do
            if [ -d "$dir/rgb" ]; then
                echo "$dir"
            fi
        done | sort -r | head -1)
    fi
    
    # Debug: Show what we found
    if [ -z "$DATASET_PATH" ]; then
        err "No dataset path found!"
        warn "Searched under: ${SAVE_PATH}"
        warn "Pattern: ${SAVE_PATH}/*/*/*/Town*_Rep*"
        
        # List what's actually there
        info "Contents of ${SAVE_PATH}:"
        find ${SAVE_PATH} -maxdepth 6 -type d -name "Town*" 2>/dev/null | head -5
        return 1
    fi
    
    info "Found dataset path: $DATASET_PATH"
    
    # Verify rgb folder exists
    if [ ! -d "${DATASET_PATH}/rgb" ]; then
        err "rgb folder not found in: $DATASET_PATH"
        return 1
    fi
    
    # Count rgb subfolders
    local rgb_count=$(find "${DATASET_PATH}/rgb" -maxdepth 1 -type d -name "[0-9]*" 2>/dev/null | wc -l)
    info "Found ${rgb_count} frame folders in rgb/"
    
    if [ $rgb_count -eq 0 ]; then
        err "No frame folders found in ${DATASET_PATH}/rgb"
        return 1
    fi
    
    cd /workspace/simlingo || return 1
    
    # Apply geometric layout patching
    sep
    info "Applying geometric layout (creates patched.jpg)..."
    python bosch_utils/tools/batch_patch_multicamera.py "$DATASET_PATH" --layout geometric
    local patch1_exit=$?
    
    if [ $patch1_exit -ne 0 ]; then
        err "Geometric patching failed with exit code: $patch1_exit"
    fi
    
    # Apply three-quarter layout patching
    sep
    info "Applying three-quarter layout (creates patched2*.jpg)..."
    python bosch_utils/tools/batch_patch_multicamera2.py "$DATASET_PATH" --layout three_quarter
    local patch2_exit=$?
    
    if [ $patch2_exit -ne 0 ]; then
        err "Three-quarter patching failed with exit code: $patch2_exit"
    fi
    
    # Verify patching worked
    sep
    if [ $patch1_exit -eq 0 ] && [ $patch2_exit -eq 0 ]; then
        info "✓ Multicamera patching completed successfully!"
        
        # Verify files were created
        local patched_count=$(find "${DATASET_PATH}/rgb" -name "patched*.jpg" 2>/dev/null | wc -l)
        info "Created ${patched_count} patched image files"
        
        # Show sample from first and last frame
        local first_frame=$(find "${DATASET_PATH}/rgb" -maxdepth 1 -type d -name "[0-9]*" 2>/dev/null | sort | head -1)
        local last_frame=$(find "${DATASET_PATH}/rgb" -maxdepth 1 -type d -name "[0-9]*" 2>/dev/null | sort | tail -1)
        
        if [ -n "$first_frame" ]; then
            info "First frame ($(basename $first_frame)): $(ls -1 $first_frame/patched* 2>/dev/null | wc -l) patched files"
        fi
        if [ -n "$last_frame" ]; then
            info "Last frame ($(basename $last_frame)) : $(ls -1 $last_frame/patched* 2>/dev/null | wc -l) patched files"
        fi
        
        sep
        info "Patched images location: ${DATASET_PATH}/rgb/*/patched*.jpg"
        return 0
    else
        err "Patching encountered errors!"
        err "  - Geometric layout: exit code $patch1_exit"
        err "  - Three-quarter layout: exit code $patch2_exit"
        return 1
    fi
}

# =============================================================================
# MAIN
# =============================================================================
main() {
    sep
    info "Testing data_agent_multicamera.py"
    info "6-camera multi-view right-hand traffic"
    sep

    # 1. Clean up any existing CARLA
    cleanup_carla

    # 2. Start CARLA headless
    start_carla

    # 3. Run leaderboard with data_agent_multicamera.py
    run_leaderboard
    local eval_exit=$?

    # 4. Post-process: Patch multicamera images if data collection succeeded
    if [ $eval_exit -eq 0 ]; then
        patch_multicamera_images
        local patch_exit=$?
    else
        warn "Skipping patching due to data collection failure"
        patch_exit=1
    fi

    # 5. Cleanup (via trap on exit)
    sep
    info "Test complete!"
    sep
    
    if [ $eval_exit -eq 0 ]; then
        info "Check output at: ${SAVE_PATH}"
    fi

    exit $eval_exit
}

# Run main
main




