#!/bin/bash

# Robust bootstrap so the script works when located in script/
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 1

#!/bin/bash

## This script runs CARLA MP with visualization for manual driving tests.
# It starts CARLA in a Docker container, verifies the connection,
# and launches the manual driving script `japanese_driving_cameras.py`.

# =============================================================================
export CARLA_ROOT=/workspace/carla0915
export WORK_DIR=/workspace/simlingo
export SCENARIO_RUNNER_ROOT=${WORK_DIR}/Bench2Drive/scenario_runner
export LEADERBOARD_ROOT=${WORK_DIR}/Bench2Drive/leaderboard
export SAVE_PATH=/workspace/simlingo/outputs/test_run2/
export PYTHONPATH="${WORK_DIR}:${CARLA_ROOT}/PythonAPI/carla:${CARLA_ROOT}/PythonAPI:${SCENARIO_RUNNER_ROOT}:${LEADERBOARD_ROOT}"

START_WAIT=${START_WAIT:-60}

# Fix conda activation for non-interactive scripts
source ~/miniconda3/etc/profile.d/conda.sh
conda activate simlingo

# Color & logging helpers
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
BLUE="\033[0;34m"
RED="\033[0;31m"
RESET="\033[0m"

info() { echo -e "${GREEN}[INFO]${RESET} $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET} $*"; }
err()  { echo -e "${RED}[ERROR]${RESET} $*"; }
sep()  { printf "%b\n" "${BLUE}$(printf '=%.0s' {1..80})${RESET}"; }

cleanup_carla() {
    sep
    info "Cleaning up existing CARLA instances..."
    sep

    pkill -9 -f CarlaUE4 || true
    killall -9 CarlaUE4 2>/dev/null || true

    info "Freeing ports 2000, 2002-2010 (skip 2001)"
    pids=$(lsof -ti:2000 2>/dev/null)
    if [ ! -z "$pids" ]; then
        warn "Killing processes on port 2000: $pids"
        kill -9 $pids 2>/dev/null || true
    fi
    for port in {2002..2010}; do
        pids=$(lsof -ti:$port 2>/dev/null)
        if [ ! -z "$pids" ]; then
            warn "Killing processes on port $port: $pids"
            kill -9 $pids 2>/dev/null || true
        fi
    done

    info "Stopping any running CARLA Docker containers (will not remove crashed containers)..."
    docker ps --filter "name=carla-server" -q | xargs -r docker stop 2>/dev/null || true
    docker ps -a --filter "name=carla" -q | xargs -r docker stop 2>/dev/null || true

    sleep 2
}

start_carla() {
    mkdir -p ${SAVE_PATH}

    info "CARLA_ROOT: $CARLA_ROOT"
    info "SAVE_PATH : $SAVE_PATH"

    # Verify custom CARLA image exists
    info "Checking for custom CARLA image..."
    if ! docker images | grep -q "carla-bench2drive.*0.9.15"; then
        err "Custom CARLA image 'carla-bench2drive:0.9.15' not found!"
        warn "Build it with: bash /workspace/simlingo/build_carla_bench2drive_docker.sh"
        exit 1
    fi

    sep
    info "Starting CARLA 0.9.15 (Bench2Drive) with display on port 2000"
    sep

    mkdir -p ${WORK_DIR}/carla_logs

    # Allow Docker to connect to X11
    xhost +local:docker || true

    docker run -d \
        --name carla-server \
        --runtime=nvidia \
        --net=host \
        --env=DISPLAY=$DISPLAY \
        --env=NVIDIA_VISIBLE_DEVICES=all \
        --env=NVIDIA_DRIVER_CAPABILITIES=all \
        --volume="/tmp/.X11-unix:/tmp/.X11-unix:rw" \
        carla-bench2drive:0.9.15 \
        ./CarlaUE4.sh -nosound -world-port=2000 \
        info "Waiting for CARLA to start (${START_WAIT}s)..."


    sleep ${START_WAIT}

    # Check container is still running
    if ! docker ps | grep -q carla-server; then
        err "CARLA container crashed!"
        sep
        warn "Container logs:"
        docker logs carla-server 2>&1
        sep
        docker rm -f carla-server
        exit 1
    fi

    info "CARLA container is running ✓"

    # Test CARLA connection and verify version & Town13
    sep
    info "Testing CARLA connection on port 2000..."
    sep
    cd ${WORK_DIR}

    python << 'EOF'
import carla
import sys
try:
    client = carla.Client('localhost', 2000)
    client.set_timeout(30.0)
    version = client.get_server_version()
    maps = client.get_available_maps()
    print(f'[INFO]: CARLA connection successful on port 2000')
    print(f'[INFO]: Server version  : {version}')
    print(f'[INFO]: Total maps      : {len(maps)}')
    if version != '0.9.15':
        print(f'[ERROR]: Expected CARLA 0.9.15, got {version}')
        sys.exit(1)
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
        err "CARLA verification failed"
        sep
        warn "Full container logs:"
        docker logs carla-server 2>&1
        sep
        docker rm -f carla-server
        xhost -local:docker || true
        exit 1
    fi

    info "CARLA connection verified on port 2000"
}

stop_carla() {
    sep
    info "Stopping CARLA container..."
    sep
    docker rm -f carla-server 2>/dev/null || true
    sleep 2
    xhost -local:docker || true
}

# Main flow
cleanup_carla
start_carla

info "Installing python deps (pygame) if needed..."
pip install --upgrade --quiet pygame || true

info "Launching manual driving script (japanese_driving_cameras.py)"
cd ${WORK_DIR}
python bosch_utils/japanese_driving_cameras_2btested.py

EVAL_EXIT_CODE=$?

info "Evaluation complete! Exit code: $EVAL_EXIT_CODE"
info "Debug outputs saved to: ${SAVE_PATH}"

# Cleanup
stop_carla

if [ $EVAL_EXIT_CODE -eq 0 ]; then
    info "Evaluation completed successfully!"
else
    err "Evaluation encountered errors (exit code: $EVAL_EXIT_CODE)"
fi

exit $EVAL_EXIT_CODE
