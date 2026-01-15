#!/bin/bash

# Exit on unset variable errors, but allow commands to fail
set -u

# Robust bootstrap so the script works when located in script/
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 1

# =============================================================================
# Left hand driving version for run_carla_autopilot_mp_pilot_script.sh via carla 0.9.16
# ============================================================================

# ============================================================================
# CONFIG 
# ============================================================================

export CARLA_ROOT=/workspace/carla0916
export WORK_DIR=/workspace/simlingo
export SAVE_PATH=/workspace/simlingo/outputs/test_run_carla0916/
export PYTHONPATH="${WORK_DIR}:${CARLA_ROOT}/PythonAPI/carla:${CARLA_ROOT}/PythonAPI"

# Make CARLA and Traffic Manager ports configurable (defaults preserved)
export CARLA_PORT=${CARLA_PORT:-2000}
export TRAFFIC_MANAGER_PORT=${TRAFFIC_MANAGER_PORT:-8000}

source ~/miniconda3/etc/profile.d/conda.sh
conda activate simlingo16

MODE="autopilot"  # Only one aviable
AUTOPILOT_DURATION=60
AUTOPILOT_ROUTE="highway"
AUTOPILOT_TOWN="Town13"
MULTICAMERA=true
AUTOPILOT_LONG=false
AUTOPILOT_WEATHER=""
AUTOPILOT_SPAWN_INDEX=""
AUTOPILOT_RANDOM_SPAWN=false
AUTOPILOT_FPS=20


# Color & logging helpers for carla 0.9.16
GREEN="\033[0;92m"
YELLOW="\033[0;93m"
BLUE="\033[0;94m"
RED="\033[0;91m"
RESET="\033[0m"

START_WAIT=${START_WAIT:-80}

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
    warn "Script exiting (code: $exit_code) - ensuring CARLA 0.9.16 cleanup..."
    stop_carla 2>/dev/null || true
    exit $exit_code
}

trap cleanup_on_exit EXIT INT TERM

show_help() {
    cat << EOF
Usage: $0 [OPTIONS]

Run CARLA 0.9.16 simulations with different modes simulating japanese streets.
This is an headless script that starts CARLA 0.9.16 in a Docker container, runs
the specified mode, and then cleans up.

OPTIONS:
    -h, --help              Show this help message
    -m, --mode MODE         Simulation mode (default/only avaiable: autopilot)
                           Options:
                             - autopilot: Japanese-style autopilot driving
    
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
    --autopilot-long        Run the long-version autopilot (overrides AUTOPILOT_LONG env)
    --spawn-index INDEX     Spawn point index (0-based, forwarded to autopilot)
    --random-spawn          Randomize spawn location (only for autopilot-long)

EXAMPLES:
    # Run default autopilot mode
    $0
    
    # Run Japanese autopilot for 120 seconds on highway
    $0 --mode autopilot --duration 120 --route highway

    $0 --mode autopilot --duration 10 --route highway --multicamera --fps 20 --autopilot-long

EOF
    exit 0
}


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
        --multicamera)
            MULTICAMERA=true
            shift
            ;;
        --autopilot-long)
            AUTOPILOT_LONG=true
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
    info "Cleaning up existing CARLA 0.9.16 instances..."
    sep

    # Kill all CARLA processes on host
    pkill -9 -f CarlaUE4 || true
    killall -9 CarlaUE4 2>/dev/null || true

    # Kill processes using CARLA ports (skip CARLA_PORT+1 - reserved)
    info "Freeing CARLA 0.9.16 ports around ${CARLA_PORT} (skipping ${CARLA_PORT}+1)..."

    # Force free CARLA_PORT
    pids=$(lsof -ti:${CARLA_PORT} 2>/dev/null)
    if [ ! -z "$pids" ]; then
        warn "Killing processes on port ${CARLA_PORT}: $pids"
        kill -9 $pids 2>/dev/null || true
    fi

    # Free a small range of nearby ports (CARLA_PORT+2 .. CARLA_PORT+10), skip CARLA_PORT+1
    start_port=$((CARLA_PORT + 2))
    end_port=$((CARLA_PORT + 10))
    for port in $(seq ${start_port} ${end_port}); do
        pids=$(lsof -ti:$port 2>/dev/null)
        if [ ! -z "$pids" ]; then
            warn "Killing processes on port $port: $pids"
            kill -9 $pids 2>/dev/null || true
        fi
    done

    # Do not automatically remove carla-server container here so logs/crash dumps can be inspected.
    info "Stopping any running CARLA 0.9.16 Docker containers (will not remove crashed containers)..."
    docker ps --filter "name=carla-server" -q | xargs -r docker stop 2>/dev/null || true
    docker ps -a --filter "name=carla" -q | xargs -r docker stop 2>/dev/null || true

    # Wait for cleanup to complete
    sleep 5

    # Verify CARLA_PORT is free
    if lsof -ti:${CARLA_PORT} &>/dev/null; then
        err "Port ${CARLA_PORT} is still in use!"
        warn "Processes using port ${CARLA_PORT}:"
        lsof -i:${CARLA_PORT}
        echo ""
        warn "Force killing processes on port ${CARLA_PORT}..."
        kill -9 $(lsof -ti:${CARLA_PORT}) 2>/dev/null || true
        sleep 2
        
        # Check again
        if lsof -ti:${CARLA_PORT} &>/dev/null; then
            err "Still cannot free port ${CARLA_PORT}. Please reboot or contact your colleague."
            exit 1
        fi
    fi

    info "Port ${CARLA_PORT} is free"
}

# ============================================================================
# START CARLA FUNCTION
# ============================================================================
start_carla() {
    mkdir -p ${SAVE_PATH}

    echo ""
    info "CARLA_ROOT: $CARLA_ROOT"
    info "SAVE_PATH : $SAVE_PATH"

    # Verify custom CARLA 0.9.16 image with Bench2Drive maps exists
    echo ""
    info "Checking for CARLA 0.9.16 image..."
    if ! docker images | grep -q "carlasim/carla.*0.9.16\|carla-bench2drive.*0.9.16"; then
        warn "CARLA 0.9.16 image not found locally - pulling from DockerHub..."
        docker pull carlasim/carla:0.9.16
        if [ $? -ne 0 ]; then
            err "Failed to pull carlasim/carla:0.9.16"
            err "Alternative: build locally with 'cd /workspace/carla0916 && docker build -t carla-bench2drive:0.9.16 -f Dockerfile .'"
            exit 1
        fi
        # Tag it for consistency with your naming convention
        docker tag carlasim/carla:0.9.16 carla-bench2drive:0.9.16
        info "Tagged carlasim/carla:0.9.16 as carla-bench2drive:0.9.16"
    fi

    info "Using carla-bench2drive:0.9.16"
    sep
    info "Starting CARLA 0.9.16 (Bench2Drive) HEADLESS on port ${CARLA_PORT}"
    sep

    # Remove any existing carla-server container (running or stopped)
    info "Removing any existing carla-server container..."
    docker rm -f carla-server 2>/dev/null || true

    # Start CARLA in headless mode - FORCE port ${CARLA_PORT}
    mkdir -p ${WORK_DIR}/carla_logs

    # Create left-hand traffic configuration script for 0.9.16
    # This modifies OpenDRIVE XML files to enable LHT via userData tags
    mkdir -p ${WORK_DIR}/tmp_carla_config
    cat > ${WORK_DIR}/tmp_carla_config/enable_lht.sh << 'EOFCONFIG'
#!/bin/bash
# Enable left-hand traffic for classic CARLA towns via OpenDRIVE XML modification
# Based on: https://github.com/carla-simulator/carla/pull/8951

CARLA_HOME="/workspace"
MAPS_DIR="${CARLA_HOME}/CarlaUE4/Content/Carla/Maps"

# Only modify classic towns (Town01-Town12) - Town13+ may have native LHT
TOWNS_TO_MODIFY="Town01 Town02 Town03 Town04 Town05 Town06 Town07 Town10HD"

echo "[LHT-CONFIG] Checking for OpenDRIVE files to modify..."

for town in $TOWNS_TO_MODIFY; do
    XODR_FILE="${MAPS_DIR}/${town}/OpenDrive/${town}.xodr"
    
    if [ ! -f "$XODR_FILE" ]; then
        echo "[LHT-CONFIG] Skipping ${town} (file not found: $XODR_FILE)"
        continue
    fi
    
    # Check if already modified (avoid duplicate modifications)
    if grep -q 'carla:lane_direction.*left' "$XODR_FILE" 2>/dev/null; then
        echo "[LHT-CONFIG] ${town} already has LHT config, skipping"
        continue
    fi
    
    echo "[LHT-CONFIG] Enabling LHT for ${town}..."
    
    # Backup original
    cp "$XODR_FILE" "${XODR_FILE}.backup_rht" 2>/dev/null || true
    
    # Add left-hand traffic userData to the OpenDRIVE header
    # Insert after <header> tag
    sed -i '/<header/a\        <userData>\n            <vectorLane code="carla:lane_direction" value="left"/>\n        </userData>' "$XODR_FILE"
    
    if [ $? -eq 0 ]; then
        echo "[LHT-CONFIG] ✓ ${town} configured for left-hand traffic"
    else
        echo "[LHT-CONFIG] ✗ Failed to modify ${town}, restoring backup"
        [ -f "${XODR_FILE}.backup_rht" ] && cp "${XODR_FILE}.backup_rht" "$XODR_FILE"
    fi
done

echo "[LHT-CONFIG] Configuration complete"
EOFCONFIG

    docker run -d \
        --name carla-server \
        --runtime=nvidia \
        --gpus all \
        --net=host \
        --shm-size=1g \
        --ulimit core=-1 \
        --env=NVIDIA_VISIBLE_DEVICES=all \
        --env=NVIDIA_DRIVER_CAPABILITIES=all \
        --env=ENABLE_LEFT_HAND_TRAFFIC=1 \
        -v ${WORK_DIR}/carla_logs:/workspace/CarlaUE4/Saved/Logs \
        -v ${WORK_DIR}/tmp_carla_config:/tmp/carla_config:ro \
        carla-bench2drive:0.9.16 \
        bash -c "bash /tmp/carla_config/enable_lht.sh && cd /workspace && ./CarlaUE4.sh -opengl -RenderOffScreen -nosound -world-port=${CARLA_PORT} -carla-rpc-port=${CARLA_PORT} -log"

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
    info "Testing CARLA connection on port ${CARLA_PORT}..."
    sep
    cd /workspace/simlingo

    # Use unquoted heredoc so shell variables expand inside the embedded Python
    python << EOF
import carla
import sys

try:
    client = carla.Client('localhost', ${CARLA_PORT})
    client.set_timeout(30.0)  # increase timeout to allow slower startups
    world = client.get_world()
    version = client.get_server_version()
    maps = client.get_available_maps()
    
    print(f'[INFO]: CARLA connection successful on port ${CARLA_PORT}')
    print(f'[INFO]: Server version  : {version}')
    print(f'[INFO]: Total maps      : {len(maps)}')
    
    if version != '0.9.16':
        print(f'[ERROR]: Expected CARLA 0.9.16, got {version}')
        sys.exit(1)
    
    # Check for requested town
    requested_town = '${AUTOPILOT_TOWN}'
    matching_maps = [m for m in maps if requested_town in m]
    if matching_maps:
        print(f'[INFO]: Requested town "{requested_town}" found: {matching_maps[0]}')
    else:
        print(f'[WARNING]: Requested town "{requested_town}" NOT found in available maps')
        print(f'[INFO]: Available maps: {[m.split("/")[-1] for m in maps[:15]]}')
        
except Exception as e:
    print(f'[ERROR]: CARLA 0.9.16 connection failed on port ${CARLA_PORT}: {e}')
    sys.exit(1)
EOF

    if [ $? -ne 0 ]; then
        echo ""
        err "CARLA 0.9.16 verification failed"
        sep
        warn "Full container logs:"
        docker logs carla-server 2>&1
        sep
        docker rm -f carla-server
        exit 1
    fi

    info "CARLA 0.9.16 connection verified on port ${CARLA_PORT}"
}

# ============================================================================
# STOP CARLA 0.9.16 FUNCTION
# ============================================================================
stop_carla() {
    echo ""
    info "Stopping CARLA 0.9.16 container..."
    docker rm -f carla-server 2>/dev/null || true
    sleep 3
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

    # Initialize variables to avoid unbound variable errors with set -u
    AUTOPILOT_OUTPUT=""
    AUTOPILOT_EXIT_CODE=0

    if [ "$MULTICAMERA" = true ]; then
        info "MULTICAMERA mode (6 cameras) and LONG version of the autopilot in this script."
        AUTOPILOT_OUTPUT=$(python bosch_utils/japanese_driving_autopilot_cameras_mp_carla0916.py \
            --autopilot \
            --duration "$duration" \
            --route "$route" \
            --town "$AUTOPILOT_TOWN" \
            --fps "$AUTOPILOT_FPS" \
            $( [ -n "$AUTOPILOT_WEATHER" ] && printf '%s' "--weather $AUTOPILOT_WEATHER" ) \
            $( [ -n "$AUTOPILOT_SPAWN_INDEX" ] && printf '%s' "--spawn-index $AUTOPILOT_SPAWN_INDEX" ) \
            $( [ "$AUTOPILOT_RANDOM_SPAWN" = true ] && printf '%s' "--random-spawn" ) 2>&1 | tee /dev/tty)
        AUTOPILOT_EXIT_CODE=${PIPESTATUS[0]}
    else
        err "MONOCAMERA mode is currently NOT implemented in this script."
    fi
    
    # Capture dataset path from autopilot output (avoids slow auto-discovery)
    DATASET_PATH=$(echo "$AUTOPILOT_OUTPUT" | grep '__DATASET_PATH__=' | sed 's/.*__DATASET_PATH__=//' | tail -1)
    
    echo ""
    sep
    if [ $AUTOPILOT_EXIT_CODE -eq 0 ]; then
        info "Autopilot completed successfully!"
        
        # Post-processing: Patch multicamera images if in multicamera mode
        if [ "$MULTICAMERA" = true ]; then
            echo ""
            info "Starting post-processing: Patching multicamera RGB images..."
            
            if [ -n "$DATASET_PATH" ] && [ -d "$DATASET_PATH" ]; then
                info "Using dataset path: $DATASET_PATH"
                python bosch_utils/tools/batch_patch_multicamera.py "$DATASET_PATH" --layout geometric
                python bosch_utils/tools/batch_patch_multicamera2.py "$DATASET_PATH" --layout three_quarter
            else
                warn "Dataset path not captured, skipping auto-discovery to avoid hang..."
                warn "Run patching manually later: python bosch_utils/tools/batch_patch_multicamera.py <dataset_path> --layout geometric"
                PATCH_EXIT_CODE=0  # Don't fail the whole run
            fi
            
            if [ $PATCH_EXIT_CODE -eq 0 ]; then
                info "Post-processing completed!"
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
# MAIN EXECUTION
# ============================================================================

sep
info "CARLA 0.9.16 (!!)  Simulation Runner - Mode: $MODE"
sep

# Cleanup before starting
cleanup_carla

# Start CARLA
start_carla

# Execute based on mode
EXIT_CODE=0

case $MODE in
    autopilot)
        run_autopilot $AUTOPILOT_DURATION $AUTOPILOT_ROUTE
        EXIT_CODE=$?
        ;;
    both)
        # Run evaluation 
        info "Not implemented here"
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
    info "Note that completion may depend on timing. Check the infractions too!"
else
    err "Some tasks encountered errors (exit code: $EXIT_CODE)"
fi
sep

exit $EXIT_CODE


## bash script/run_carla_mp_pilot_script_carla0916.sh --mode autopilot --duration 10 --route urban --town Town02 --weather ClearNoon --spawn-index 42 --fps 20