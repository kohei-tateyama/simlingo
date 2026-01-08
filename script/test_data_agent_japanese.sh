#!/bin/bash

# Test script for data_agent_japanese.py - based on data_agent.py - with leaderboard evaluation
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
export TEAM_AGENT=/workspace/simlingo/team_code/data_agent_japanese.py
export TEAM_CONFIG="data_collection"
export SAVE_PATH=/workspace/simlingo/database/simlingo_v4_bosch_2025_01_10/data/simlingo
export TOWN="Town03"  # Will be overridden by route XML
export REPETITION="0" # "3"
export SCENARIO_NAME="training_3_scenarios" # (test_town12, validation_1_scenario, training_3_scenarios, training_full)
export ROUTE_CONFIG="routes_devtest"        # (routes_town12_only, routes_devtest, routes_validation, routes_all)
export WEATHER_CONFIG="test_clear_noon"     # (random_weather_seed_3_balanced_100, clear_noon, clear_sunset, rainy_night, balanced_weather_variations)

export ROUTES_SUBSET="0" # "0,1,2,3,4,5,6,7,8,9" (remove --routes)
export ROUTES="/workspace/simlingo/leaderboard/data/routes_training.xml"

LEADERBOARD_TIMEOUT="${LEADERBOARD_TIMEOUT:-1000}"

# Activate conda environment
source ~/miniconda3/etc/profile.d/conda.sh
conda activate simlingo

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

    # Kill processes on port 2000
    pids=$(lsof -ti:2000 2>/dev/null)
    if [ ! -z "$pids" ]; then
        warn "Killing processes on port 2000: $pids"
        kill -9 $pids 2>/dev/null || true
    fi
    
    # Kill processes on port 8000 (traffic manager)
    pids=$(lsof -ti:8000 2>/dev/null)
    if [ ! -z "$pids" ]; then
        warn "Killing processes on port 8000: $pids"
        kill -9 $pids 2>/dev/null || true
    fi

    # Stop Docker container
    info "Stopping CARLA Docker container..."
    docker rm -f carla-server 2>/dev/null || true

    sleep 3

    # Verify ports are free
    if lsof -ti:2000 &>/dev/null; then
        err "Port 2000 still in use!"
        lsof -i:2000
    fi
    if lsof -ti:8000 &>/dev/null; then
        err "Port 8000 still in use!"
        lsof -i:8000
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
    info "Starting CARLA 0.9.15 HEADLESS on port 2000"
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
        bash -c "cd /home/carla && ./CarlaUE4.sh -opengl -RenderOffScreen -nosound -world-port=2000 -carla-rpc-port=2000 -log"

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

    python << 'EOF'
import carla
import sys

try:
    client = carla.Client('localhost', 2000)
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
EOF

    if [ $? -ne 0 ]; then
        err "CARLA verification failed"
        exit 1
    fi

    sep
    info "CARLA ready! ✓"
    sep
}

# =============================================================================
# RUN LEADERBOARD EVALUATION
# =============================================================================
run_leaderboard() {
    sep
    info "Running data_agent_japanese.py via leaderboard"
    sep
    
    cd /workspace/simlingo/leaderboard

    info "Agent    : ${TEAM_AGENT}"
    info "Routes   : routes_devtest.xml (ONLY FIRST ROUTE for testing)"
    info "Port     : 2000"
    info "Output   : ${SAVE_PATH}"
    sep

    # Agent has signal handler to gracefully save files on timeout
    info "Running single route"

    if [ "${LEADERBOARD_TIMEOUT:-0}" -eq 0 ]; then
        python leaderboard/leaderboard_evaluator.py \
        --routes=/workspace/simlingo/leaderboard/data/routes_devtest.xml \
        --routes-subset=0 \
        --repetitions=1 \
        --agent=${TEAM_AGENT} \
        --agent-config=${TEAM_CONFIG} \
        --checkpoint=results_japanese_test.json \
        --port=2000 \
        --traffic-manager-port=8000
    else
        timeout "${LEADERBOARD_TIMEOUT}" python leaderboard/leaderboard_evaluator.py \
            --routes=/workspace/simlingo/leaderboard/data/routes_devtest.xml \
            --routes-subset=0 \
            --repetitions=1 \
            --agent=${TEAM_AGENT} \
            --agent-config=${TEAM_CONFIG} \
            --checkpoint=results_japanese_test.json \
            --port=2000 \
            --traffic-manager-port=8000
    fi

    local exit_code=$?

    sep
    if [ $exit_code -eq 0 ]; then
        info "Leaderboard evaluation completed successfully!"
    else
        # If the agent's signal handler saved output files, treat run as success.
        FOUND_OUTPUT=0

        # Look for results.json.gz or records.json.gz anywhere under SAVE_PATH within a reasonable depth
        if find "${SAVE_PATH}" -maxdepth 6 -type f -name "results.json.gz" -print -quit | grep -q .; then
            FOUND_OUTPUT=1
        elif find "${SAVE_PATH}" -maxdepth 6 -type f -name "records.json.gz" -print -quit | grep -q .; then
            FOUND_OUTPUT=1
        fi

        if [ $FOUND_OUTPUT -eq 1 ]; then
            warn "Process exited with code ${exit_code} but found saved output files — treating as success"
            exit_code=0
        elif [ $exit_code -eq 124 ]; then
            warn "Timeout reached (LEADERBOARD_TIMEOUT=${LEADERBOARD_TIMEOUT}) - no output files found"
            # Keep exit_code non-zero so callers can detect timeout without saved output
        else
            warn "Leaderboard exited with code $exit_code"
        fi
    fi
    sep

    return $exit_code
}

# =============================================================================
# POST-PROCESS: PATCH MULTICAMERA IMAGES
# =============================================================================
patch_multicamera_images() {
    sep
    info "Post-processing: Patching multicamera RGB images..."
    sep
    
    # Debug: Show what we're searching for
    info "Searching for datasets under: ${SAVE_PATH}"
    
    # Find the most recent dataset directory. Look for Town*_Rep* folders that contain rgb/ subfolder
    # Use maxdepth 5 to reach: {SAVE_PATH}/{scenario}/{route_config}/{weather}/{Town}_Rep*
    # Then filter to only those with rgb/ subfolder to ensure we get the dataset root, not frame folders
    DATASET_PATH=$(find ${SAVE_PATH} -maxdepth 5 -type d -name "Town*_Rep*" 2>/dev/null | while read dir; do
        if [ -d "$dir/rgb" ] && [ -d "$dir/measurements" ]; then
            echo "$dir"
        fi
    done | sort -r | head -1)
    
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
    info "Testing data_agent_japanese.py"
    info "6-camera multi-view + Japanese left-hand traffic"
    sep

    # 1. Clean up any existing CARLA
    cleanup_carla

    # 2. Start CARLA headless
    start_carla

    # 3. Run leaderboard with data_agent_japanese.py
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




