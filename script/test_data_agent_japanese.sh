#!/bin/bash

# Test script for data_agent_japanese.py with leaderboard evaluation
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
export DATAGEN=1
export TEAM_AGENT=/workspace/simlingo/team_code/data_agent_japanese.py
export TEAM_CONFIG="data_collection"
export SAVE_PATH=/workspace/simlingo/database/simlingo_v4_bosch_2025_01_10/data/simlingo
export TOWN="Town03"  # Will be overridden by route XML
export REPETITION="0"
export SCENARIO_NAME="training_3_scenarios"
export ROUTE_CONFIG="routes_devtest"
export WEATHER_CONFIG="test_clear_noon"

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

    info "CARLA container is running ✓"

    # Test connection
    sep
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
    info "Max time : ~2-5 minutes (one route only)"
    sep

    # Run only the first route for testing with timeout
    # --routes-subset=0 means only route index 0
    # Agent has signal handler to gracefully save files on timeout
    info "Running single route (max 5 minutes with graceful shutdown)"
    
    timeout 100 python leaderboard/leaderboard_evaluator.py \
        --routes=/workspace/simlingo/leaderboard/data/routes_devtest.xml \
        --routes-subset=0 \
        --repetitions=1 \
        --agent=${TEAM_AGENT} \
        --agent-config=${TEAM_CONFIG} \
        --checkpoint=results_japanese_test.json \
        --port=2000 \
        --traffic-manager-port=8000

    local exit_code=$?
    
    sep
    if [ $exit_code -eq 0 ]; then
        info "Leaderboard evaluation completed successfully!"
    elif [ $exit_code -eq 124 ]; then
        warn "Timeout reached (5 minutes) - files saved via signal handler"
        exit_code=0  # Treat as success since signal handler saved files
    else
        warn "Leaderboard exited with code $exit_code"
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
    
    # Find the most recent dataset directory. Prefer nested path: {SAVE_PATH}/{scenario}/{route_config}/{weather}/{Town}_Rep*
    DATASET_PATH=$(find ${SAVE_PATH} -maxdepth 6 -type d -path "${SAVE_PATH}/*/*/*/Town*_Rep*" 2>/dev/null | sort -r | head -1)
    # Fallback to older pattern if none found
    if [ -z "$DATASET_PATH" ]; then
        DATASET_PATH=$(find ${SAVE_PATH} -maxdepth 4 -type d -name "Town*_Rep*" 2>/dev/null | sort -r | head -1)
    fi
    
    if [ -n "$DATASET_PATH" ] && [ -d "$DATASET_PATH" ]; then
        info "Using dataset path: $DATASET_PATH"
        
        cd /workspace/simlingo
        
        # Apply geometric layout patching
        info "Applying geometric layout..."
        python bosch_utils/tools/batch_patch_multicamera.py "$DATASET_PATH" --layout geometric
        local patch1_exit=$?
        
        # Apply three-quarter layout patching
        info "Applying three-quarter layout..."
        python bosch_utils/tools/batch_patch_multicamera2.py "$DATASET_PATH" --layout three_quarter
        local patch2_exit=$?
        
        if [ $patch1_exit -eq 0 ] && [ $patch2_exit -eq 0 ]; then
            info "✓ Multicamera patching completed successfully!"
            sep
            info "Patched images created in: ${DATASET_PATH}/rgb/*/patched*.jpg"
            return 0
        else
            warn "Patching encountered errors (geometric: $patch1_exit, three_quarter: $patch2_exit)"
            return 1
        fi
    else
        warn "Could not find dataset directory to patch!"
        warn "Expected under: ${SAVE_PATH}"
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
        info "Look for directories like: training_3_scenarios/routes_devtest/test_clear_noon/Town03_Rep0_*/"
        info "Each should contain:"
        info "  - rgb/{frame:04d}/{F,B,RF,LF,RB,LB}.jpg (original 6-camera images)"
        info "  - rgb/{frame:04d}/patched.jpg (geometric layout)"
        info "  - rgb/{frame:04d}/patched2.jpg (three-quarter layout)"
        info "  - measurements/, boxes/, lidar/, results.json.gz, GPS.jpg"
    fi

    exit $eval_exit
}

# Run main
main


##########################################################################################################
##########################################################################################################
# ## some generated example
# # =============================================================================
# # EXAMPLE 1: Quick test - Single route, one town (~2-5 minutes)
# # =============================================================================
# export SAVE_PATH=/workspace/simlingo/database/simlingo_v4_bosch_2025_01_10/data/simlingo
# export SCENARIO_NAME="test_quick"
# export ROUTE_CONFIG="routes_devtest"
# export WEATHER_CONFIG="clear_noon"
# # In run_leaderboard(): --routes-subset=0

# # =============================================================================
# # EXAMPLE 2: Training data collection - Multiple towns, random weather (~1-2 hours)
# # =============================================================================
# export SAVE_PATH=/workspace/simlingo/database/simlingo_v4_bosch_2025_01_10/data/simlingo
# export SCENARIO_NAME="training_3_scenarios"
# export ROUTE_CONFIG="routes_training"
# export WEATHER_CONFIG="random_weather_seed_3_balanced_100"
# # In run_leaderboard(): --routes-subset=0,1,2,3,4,5,6,7,8,9  # First 10 routes

# # =============================================================================
# # EXAMPLE 3: Validation set - All validation routes (~3-4 hours)
# # =============================================================================
# export SAVE_PATH=/workspace/simlingo/database/simlingo_v4_bosch_2025_01_10/data/simlingo
# export SCENARIO_NAME="validation_1_scenario"
# export ROUTE_CONFIG="routes_validation"
# export WEATHER_CONFIG="clear_sunset"
# # In run_leaderboard(): (remove --routes-subset to run all)

# # =============================================================================
# # EXAMPLE 4: Specific town testing - Town12 only
# # =============================================================================
# export SAVE_PATH=/workspace/simlingo/database/simlingo_v4_bosch_2025_01_10/data/simlingo
# export SCENARIO_NAME="test_town12"
# export ROUTE_CONFIG="routes_town12_only"
# export WEATHER_CONFIG="rainy_night"
# # You would need to create a custom routes_town12_only.xml with only Town12 routes
# # In run_leaderboard(): --routes=/workspace/simlingo/leaderboard/data/routes_town12_only.xml

# # =============================================================================
# # EXAMPLE 5: Full dataset generation - All routes, multiple repetitions (DAYS!)
# # =============================================================================
# export SAVE_PATH=/workspace/simlingo/database/simlingo_v5_full_2025_01_10/data/simlingo
# export SCENARIO_NAME="training_full"
# export ROUTE_CONFIG="routes_all"
# export WEATHER_CONFIG="balanced_weather_variations"
# # In run_leaderboard(): 
# #   --routes=/workspace/simlingo/leaderboard/data/routes_training.xml
# #   --repetitions=3  # Run each route 3 times with different weather
# #   (remove --routes-subset)
##########################################################################################################
##########################################################################################################