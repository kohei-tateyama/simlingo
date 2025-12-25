#!/bin/bash

# Exit on unset variable errors, but allow commands to fail
set -u

# Robust bootstrap so the script works when located in script/
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 1

## sudo chown $(id -u):$(id -g) /media/external_ssd
# =============================================================================
## This script is an updated versionn of the how_to_run_headless.sh and it allows runnning the simlingo agent as well as other code for gathering data in headless mode.
# This script is also a bnetter verison fo run_carla_autopilot.sh
# ============================================================================

## single autopilot
# bash script/run_carla_mp_pilot_script.sh --mode autopilot --duration 10 --route highway 

## add weather 
# bash script/run_carla_mp_pilot_script.sh --mode autopilot --duration 60 --route highway --multicamera --fps 60 --weather ClearNoon


# Set environment variables
export CARLA_ROOT=/workspace/carla0915
export WORK_DIR=/workspace/simlingo
export SCENARIO_RUNNER_ROOT=${WORK_DIR}/Bench2Drive/scenario_runner
export LEADERBOARD_ROOT=${WORK_DIR}/Bench2Drive/leaderboard
export SAVE_PATH="${RECORDING_OUTPUT_DIR:-/workspace/simlingo/outputs/test_run/}"
export PYTHONPATH="${WORK_DIR}:${CARLA_ROOT}/PythonAPI/carla:${CARLA_ROOT}/PythonAPI:${SCENARIO_RUNNER_ROOT}:${LEADERBOARD_ROOT}"

# Fix conda activation for non-interactive scripts
source ~/miniconda3/etc/profile.d/conda.sh
conda activate simlingo

# Color & logging helpers
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
BLUE="\033[0;34m"
RED="\033[0;31m"
RESET="\033[0m"

START_WAIT=${START_WAIT:-120}

info() {
    echo -e "${GREEN}[INFO]${RESET} $*"
}

warn() {
    echo -e "${YELLOW}[WARN]${RESET} $*"
}

err() {
    echo -e "${RED}[ERROR]${RESET} $*"
}

sep() {
    printf "%b\n" "${BLUE}$(printf '=%.0s' {1..80})${RESET}"
}

# ============================================================================
# TRAP HANDLER FOR CLEANUP
# ============================================================================
# Ensures cleanup runs even if script is interrupted or fails
cleanup_on_exit() {
    local exit_code=$?
    echo ""
    warn "Script exiting (code: $exit_code) - ensuring CARLA cleanup..."
    stop_carla 2>/dev/null || true
    exit $exit_code
}

trap cleanup_on_exit EXIT INT TERM

# ============================================================================
# PARSE COMMAND LINE ARGUMENTS
# ============================================================================
MODE="evaluation"  # Default mode
AUTOPILOT_DURATION=60
AUTOPILOT_ROUTE="highway"
AUTOPILOT_TOWN="Town13"
MULTICAMERA=true
AUTOPILOT_LONG=false
AUTOPILOT_WEATHER=""
AUTOPILOT_SPAWN_INDEX=""
AUTOPILOT_RANDOM_SPAWN=false

show_help() {
    cat << EOF
Usage: $0 [OPTIONS]

Run CARLA simulations with different modes simulating japanese streets.
This is an headless script that starts CARLA in a Docker container, runs
the specified mode, and then cleans up.

This script can also run the simlingo agent "evaluation" in headless mode.

OPTIONS:
    -h, --help              Show this help message
    -m, --mode MODE         Simulation mode (default: evaluation)
                           Options:
                             - evaluation: Run Bench2Drive evaluation simlingo agent 
                             - autopilot: Japanese-style autopilot driving
                             - both: Run both modes sequentially
    
    AUTOPILOT MODE OPTIONS:
    -d, --duration SEC      Duration in seconds (default: 60)
    -r, --route ROUTE       Route type (default: highway)
                           Options: highway, urban, simple
    
    AUTOPILOT VARIATIONS:
    --autopilot-all         Run all autopilot variations:
                           - highway (60s)
                           - urban (90s)
                           - simple (30s)
    --multicamera           Force multicamera mode (overrides MULTICAMERA env)
    --no-multicamera        Force monocamera mode (overrides MULTICAMERA env)
    --autopilot-long            Run the long-version autopilot (overrides AUTOPILOT_LONG env)
    --no-autopilot-long         Do not run the long-version autopilot (overrides AUTOPILOT_LONG env)
    --spawn-index INDEX     Spawn point index (0-based, forwarded to autopilot)
    --random-spawn          Randomize spawn location (only for autopilot-long)

EXAMPLES:
    # Run default evaluation simlingo agent
    $0
    # Or evaulation simlingo agent on urban route 120 seconds
    $0 --mode evaluation --duration 120 --route urban
    
    # Run Japanese autopilot for 120 seconds on highway
    $0 --mode autopilot --duration 120 --route highway
    
    # Run all autopilot variations
    $0 --mode autopilot --autopilot-all
    
    # Run evaluation then autopilot
    $0 --mode both --duration 60 --route urban

    # Running the fdifferent class of the autopilot
    $0 --mode autopilot --duration 10 --route highway --multicamera --fps 20 --no-autopilot-long
    $0 --mode autopilot --duration 10 --route highway --multicamera --fps 20 --autopilot-long

EOF
    exit 0
}

RUN_ALL_AUTOPILOT=false
AUTOPILOT_FPS=60

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            ;;
        -m|--mode)
            MODE="$2"
            shift 2
            ;;
        -d|--duration)
            AUTOPILOT_DURATION="$2"
            shift 2
            ;;
        -r|--route)
            AUTOPILOT_ROUTE="$2"
            shift 2
            ;;
        --town)
            AUTOPILOT_TOWN="$2"
            shift 2
            ;;
        --autopilot-all)
            RUN_ALL_AUTOPILOT=true
            shift
            ;;
        --multicamera)
            MULTICAMERA=true
            shift
            ;;
        --no-multicamera)
            MULTICAMERA=false
            shift
            ;;
        --autopilot-long)
            AUTOPILOT_LONG=true
            shift
            ;;
        --no-autopilot-long)
            AUTOPILOT_LONG=false
            shift
            ;;
        --fps)
            AUTOPILOT_FPS="$2"
            shift 2
            ;;
        --weather)
            AUTOPILOT_WEATHER="$2"
            shift 2
            ;;
        --spawn-index)
            AUTOPILOT_SPAWN_INDEX="$2"
            shift 2
            ;;
        --random-spawn)
            AUTOPILOT_RANDOM_SPAWN=true
            shift
            ;;
        *)
            err "Unknown option: $1"
            show_help
            ;;
    esac
done

# ============================================================================
# CLEANUP FUNCTION
# ============================================================================
cleanup_carla() {
    sep
    info "Cleaning up existing CARLA instances..."
    sep

    # Kill all CARLA processes on host
    pkill -9 -f CarlaUE4 || true
    killall -9 CarlaUE4 2>/dev/null || true

    # Kill processes using CARLA ports (skip 2001 - colleague is using it)
    info "Freeing ports 2000, 2002-2010 (skipping 2001)..."
    
    # Port 2000 (force this to be free)
    pids=$(lsof -ti:2000 2>/dev/null)
    if [ ! -z "$pids" ]; then
        warn "Killing processes on port 2000: $pids"
        kill -9 $pids 2>/dev/null || true
    fi

    # Ports 2002-2010 (skip 2001)
    for port in {2002..2010}; do
        pids=$(lsof -ti:$port 2>/dev/null)
        if [ ! -z "$pids" ]; then
            warn "Killing processes on port $port: $pids"
            kill -9 $pids 2>/dev/null || true
        fi
    done

    # Do not automatically remove carla-server container here so logs/crash dumps can be inspected.
    info "Stopping any running CARLA Docker containers (will not remove crashed containers)..."
    docker ps --filter "name=carla-server" -q | xargs -r docker stop 2>/dev/null || true
    docker ps -a --filter "name=carla" -q | xargs -r docker stop 2>/dev/null || true

    # Wait for cleanup to complete
    sleep 5

    # Verify port 2000 is free
    if lsof -ti:2000 &>/dev/null; then
        err "Port 2000 is still in use!"
        warn "Processes using port 2000:"
        lsof -i:2000
        echo ""
        warn "Force killing processes on port 2000..."
        kill -9 $(lsof -ti:2000) 2>/dev/null || true
        sleep 2
        
        # Check again
        if lsof -ti:2000 &>/dev/null; then
            err "Still cannot free port 2000. Please reboot or contact your colleague."
            exit 1
        fi
    fi

    info "Port 2000 is free"
}

# ============================================================================
# START CARLA FUNCTION
# ============================================================================
start_carla() {
    mkdir -p ${SAVE_PATH}

    echo ""
    info "CARLA_ROOT: $CARLA_ROOT"
    info "SAVE_PATH : $SAVE_PATH"

    # Verify custom CARLA 0.9.15 image with Bench2Drive maps exists
    echo ""
    info "Checking for custom CARLA image..."
    if ! docker images | grep -q "carla-bench2drive.*0.9.15"; then
        err "Custom CARLA image 'carla-bench2drive:0.9.15' not found!"
        warn "Building it now..."
        bash /workspace/simlingo/build_carla_bench2drive_docker.sh
    fi

    info "Using carla-bench2drive:0.9.15"
    sep
    info "Starting CARLA 0.9.15 (Bench2Drive) HEADLESS on port 2000"
    sep

    # Remove any existing carla-server container (running or stopped)
    info "Removing any existing carla-server container..."
    docker rm -f carla-server 2>/dev/null || true

    # Start CARLA in headless mode - FORCE port 2000
    mkdir -p ${WORK_DIR}/carla_logs

    docker run -d \
        --name carla-server \
        --runtime=nvidia \
        --gpus all \
        --net=host \
        --shm-size=1g \
        --ulimit core=-1 \
        --env=NVIDIA_VISIBLE_DEVICES=all \
        --env=NVIDIA_DRIVER_CAPABILITIES=all \
        -v ${WORK_DIR}/carla_logs:/home/carla/CarlaUE4/Saved/Logs \
        -v ${SAVE_PATH}:${SAVE_PATH} \
        carla-bench2drive:0.9.15 \
        bash -c "cd /home/carla && mkdir -p CarlaUE4/Saved/Logs && ./CarlaUE4.sh -opengl -RenderOffScreen -nosound -world-port=2000 -carla-rpc-port=2000 -log"

    info "Waiting for CARLA to start (${START_WAIT}s)..."
    sleep ${START_WAIT}

    # Check container is still running
    if ! docker ps | grep -q carla-server; then
        echo ""
        err "CARLA container crashed!"
        sep
        warn "Container logs:"
        docker logs carla-server 2>&1
        sep
        docker rm -f carla-server
        exit 1
    fi

    info "CARLA container is running ✓"

    # Test CARLA connection and verify version
    echo ""
    sep
    info "Testing CARLA connection on port 2000..."
    sep
    cd /workspace/simlingo

    python << 'EOF'
import carla
import sys

try:
    client = carla.Client('localhost', 2000)
    client.set_timeout(30.0)  # increase timeout to allow slower startups
    world = client.get_world()
    version = client.get_server_version()
    maps = client.get_available_maps()
    
    print(f'[INFO]: CARLA connection successful on port 2000')
    print(f'[INFO]: Server version  : {version}')
    print(f'[INFO]: Total maps      : {len(maps)}')
    
    if version != '0.9.15':
        print(f'[ERROR]: Expected CARLA 0.9.15, got {version}')
        sys.exit(1)
    
    # Check for Town13
    town13_maps = [m for m in maps if 'Town13' in m]
    if town13_maps:
        print(f'[INFO]: Town13 found: {town13_maps}')
    else:
        print(f'[WARNING]: Town13 NOT found!')
        print(f'Available maps: {[m.split("/")[-1] for m in maps[:10]]}')
        sys.exit(1)
        
except Exception as e:
    print(f'[ERROR]: CARLA connection failed on port 2000: {e}')
    sys.exit(1)
EOF

    if [ $? -ne 0 ]; then
        echo ""
        err "CARLA verification failed"
        sep
        warn "Full container logs:"
        docker logs carla-server 2>&1
        sep
        docker rm -f carla-server
        exit 1
    fi

    info "CARLA connection verified on port 2000"
}

# ============================================================================
# STOP CARLA FUNCTION
# ============================================================================
stop_carla() {
    echo ""
    info "Stopping CARLA container..."
    docker rm -f carla-server 2>/dev/null || true
    sleep 3
}

# ============================================================================
# RUN EVALUATION
# ============================================================================
run_evaluation() {
    echo ""
    sep
    info "Starting SimLingo agent evaluation (headless)"
    info "Loading agent model (InternVL2-1B) - this may take 30-60 seconds..."
    sep

    cd /workspace/simlingo

    python Bench2Drive/leaderboard/leaderboard/leaderboard_evaluator.py \
        --routes Bench2Drive/leaderboard/data/routes_validation.xml \
        --repetitions 1 \
        --track SENSORS \
        --agent /workspace/simlingo/team_code/agent_simlingo.py \
        --agent-config outputs/simlingo2/checkpoints/epoch=013.ckpt/pytorch_model.pt \
        --checkpoint outputs/test_run/results.json \
        --debug 1 \
        --resume True \
        --port 2000 \
        --traffic-manager-port 8000 \
        --traffic-manager-seed 0 \
        --gpu-rank 0

    EVAL_EXIT_CODE=$?

    echo ""
    sep
    info "Evaluation complete! Exit code: $EVAL_EXIT_CODE"
    info "Debug outputs: ${SAVE_PATH}"
    sep

    return $EVAL_EXIT_CODE
}

# ============================================================================
# RUN JAPANESE AUTOPILOT
# ============================================================================
run_autopilot() {
    local duration=$1
    local route=$2
    
    echo ""
    sep
    info "Starting Japanese-style Autopilot Mode"
    info "Route: $route | Duration: ${duration}s"
    sep

    cd /workspace/simlingo

    if [ "$MULTICAMERA" = true ]; then
        info "MULTICAMERA mode (6 cameras) is currently USED in this script."
        # python bosch_utils/japanese_driving_autopilot_cameras.py \
        #     --autopilot \
        #     --duration "$duration" \
        #     --route "$route" \
        #     --fps "$AUTOPILOT_FPS"

        if [ "$AUTOPILOT_LONG" = false ]; then
            info "Also running SHORT HARDCODED version of the autopilot for extended data collection."
            python bosch_utils/japanese_driving_autopilot_cameras.py \
                --autopilot \
                --duration "$duration" \
                --route "$route" \
                --town "$AUTOPILOT_TOWN" \
                --fps "$AUTOPILOT_FPS" \
                $( [ -n "$AUTOPILOT_WEATHER" ] && printf '%s' "--weather $AUTOPILOT_WEATHER" ) \
                $( [ -n "$AUTOPILOT_SPAWN_INDEX" ] && printf '%s' "--spawn-index $AUTOPILOT_SPAWN_INDEX" )
        fi
        
        if [ "$AUTOPILOT_LONG" = true ]; then
            info "Also running LONG version of the autopilot for extended data collection."
            python bosch_utils/japanese_driving_autopilot_cameras_long.py \
                --autopilot \
                --duration "$duration" \
                --route "$route" \
                --town "$AUTOPILOT_TOWN" \
                --fps "$AUTOPILOT_FPS" \
                $( [ -n "$AUTOPILOT_WEATHER" ] && printf '%s' "--weather $AUTOPILOT_WEATHER" ) \
                $( [ -n "$AUTOPILOT_SPAWN_INDEX" ] && printf '%s' "--spawn-index $AUTOPILOT_SPAWN_INDEX" ) \
                $( [ "$AUTOPILOT_RANDOM_SPAWN" = true ] && printf '%s' "--random-spawn" )
        fi
    else
        info "MONOCAMERA mode is currently USED in this script."
        python bosch_utils/japanese_driving_autopilot.py \
            --autopilot \
            --duration "$duration" \
            --route "$route" \
            --fps "$AUTOPILOT_FPS"
    fi
    AUTOPILOT_EXIT_CODE=$?
    echo ""
    sep
    if [ $AUTOPILOT_EXIT_CODE -eq 0 ]; then
        info "Autopilot completed successfully!"
        
        # Post-processing: Patch multicamera images if in multicamera mode
        if [ "$MULTICAMERA" = true ]; then
            echo ""
            info "Starting post-processing: Patching multicamera RGB images..."
            python bosch_utils/tools/batch_patch_multicamera.py --auto-latest --layout geometric
            PATCH_EXIT_CODE=$?
            if [ $PATCH_EXIT_CODE -eq 0 ]; then
                info "Multicamera patching completed successfully!"
            else
                warn "Patching encountered errors (exit code: $PATCH_EXIT_CODE) - continuing anyway"
            fi
        fi
    else
        err "Autopilot encountered errors (exit code: $AUTOPILOT_EXIT_CODE)"
    fi
    sep

    return $AUTOPILOT_EXIT_CODE
}

# ============================================================================
# RUN ALL AUTOPILOT VARIATIONS
# ============================================================================
run_all_autopilot_variations() {
    sep
    info "Running ALL autopilot variations..."
    sep
    
    # Variation 1: Highway - 60 seconds
    info "Variation 1/3: Highway route (60s)"
    run_autopilot 60 highway
    sleep 5
    
    # Variation 2: Urban - 90 seconds
    info "Variation 2/3: Urban route (90s)"
    run_autopilot 90 urban
    sleep 5
    
    # Variation 3: Simple - 30 seconds
    info "Variation 3/3: Simple route (30s)"
    run_autopilot 30 simple
    
    sep
    info "All autopilot variations completed!"
    sep
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================

sep
sep
info "CARLA Simulation Runner - Mode: $MODE"
sep
sep

# Cleanup before starting
cleanup_carla

# Start CARLA
start_carla

# Execute based on mode
EXIT_CODE=0

case $MODE in
    evaluation)
        run_evaluation
        EXIT_CODE=$?
        ;;
        
    autopilot)
        if [ "$RUN_ALL_AUTOPILOT" = true ]; then
            run_all_autopilot_variations
        else
            run_autopilot $AUTOPILOT_DURATION $AUTOPILOT_ROUTE
        fi
        EXIT_CODE=$?
        ;;
        
    both)
        # Run evaluation first
        run_evaluation
        EVAL_EXIT=$?
        
        # Then run autopilot
        if [ "$RUN_ALL_AUTOPILOT" = true ]; then
            run_all_autopilot_variations
        else
            run_autopilot $AUTOPILOT_DURATION $AUTOPILOT_ROUTE
        fi
        AUTO_EXIT=$?
        
        # Return non-zero if either failed
        if [ $EVAL_EXIT -ne 0 ] || [ $AUTO_EXIT -ne 0 ]; then
            EXIT_CODE=1
        fi
        ;;
        
    *)
        err "Unknown mode: $MODE"
        show_help
        ;;
esac

# Cleanup (also handled by trap, but explicit call for clean exit)
stop_carla

# Disable trap before final exit to avoid double-cleanup
trap - EXIT

# Final status
echo ""
sep
if [ $EXIT_CODE -eq 0 ]; then
    info "All tasks completed successfully!"
else
    err "Some tasks encountered errors (exit code: $EXIT_CODE)"
fi
sep

exit $EXIT_CODE
