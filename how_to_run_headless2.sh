#!/bin/bash

# Set environment variables
export CARLA_ROOT=/workspace/carla0915
export WORK_DIR=/workspace/simlingo
export SCENARIO_RUNNER_ROOT=${WORK_DIR}/Bench2Drive/scenario_runner
export LEADERBOARD_ROOT=${WORK_DIR}/Bench2Drive/leaderboard
export SAVE_PATH=/workspace/simlingo/outputs/test_run/
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

sep
info "Cleaning up existing CARLA instances..."
sep

# Kill all CARLA processes on host
pkill -9 -f CarlaUE4 || true
killall -9 CarlaUE4 2>/dev/null || true

# Kill processes using CARLA ports (skip 2001 - colleague is using it)
info "Freeing ports 2000, 2002-2010 (skipping 2001)..."
# Port 2000
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

# Remove all CARLA Docker containers
info "Removing CARLA Docker containers..."
docker rm -f carla-server 2>/dev/null || true
docker ps -a --filter "name=carla" -q | xargs -r docker rm -f 2>/dev/null || true

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
        err "Still cannot free port 2000. Please reboot."
        exit 1
    fi
fi

info "Port 2000 is free ✓"

mkdir -p ${SAVE_PATH}

echo ""
info "CARLA_ROOT: $CARLA_ROOT"
info "SAVE_PATH: $SAVE_PATH"

# Verify custom CARLA 0.9.15 image with Bench2Drive maps exists
echo ""
info "Checking for custom CARLA image..."
if ! docker images | grep -q "carla-bench2drive.*0.9.15"; then
    err "Custom CARLA image 'carla-bench2drive:0.9.15' not found!"
    warn "Building it now..."
    bash /workspace/simlingo/build_carla_bench2drive_docker.sh
fi

info "Using carla-bench2drive:0.9.15 ✓"
echo ""
sep
info "Starting CARLA 0.9.15 (Bench2Drive) HEADLESS"
sep

# Start CARLA in headless mode
docker run -d \
    --name carla-server \
    --runtime=nvidia \
    --gpus all \
    --net=host \
    --env=NVIDIA_VISIBLE_DEVICES=all \
    --env=NVIDIA_DRIVER_CAPABILITIES=all \
    carla-bench2drive:0.9.15 \
    bash -c "cd /home/carla && ./CarlaUE4.sh -RenderOffScreen -nosound -world-port=2000"

info "Waiting for CARLA to start (60s)..."
sleep 60

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
info "Testing CARLA connection..."
sep
cd /workspace/simlingo
python << 'EOF'
import carla
import sys

try:
    client = carla.Client('localhost', 2000)
    client.set_timeout(10.0)
    world = client.get_world()
    version = client.get_server_version()
    maps = client.get_available_maps()
    
    print(f'✓ CARLA connection successful')
    print(f'  Server version: {version}')
    print(f'  Total maps available: {len(maps)}')
    
    # Verify correct version
    if version != '0.9.15':
        print(f'  ✗ ERROR: Expected CARLA 0.9.15, got {version}')
        sys.exit(1)
    
    # Check for Town13
    town13_maps = [m for m in maps if 'Town13' in m]
    if town13_maps:
        print(f'  ✓ Town13 found: {town13_maps}')
    else:
        print(f'  ✗ WARNING: Town13 NOT found!')
        print(f'  Available maps: {[m.split("/")[-1] for m in maps[:10]]}')
        sys.exit(1)
        
except Exception as e:
    print(f'✗ CARLA connection failed: {e}')
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

info "CARLA connection verified ✓"

# Run evaluation
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

# Cleanup
echo ""
info "Stopping CARLA container..."
docker rm -f carla-server 2>/dev/null || true

if [ $EVAL_EXIT_CODE -eq 0 ]; then
    info "Evaluation completed successfully! ✓"
else
    err "Evaluation encountered errors (exit code: $EVAL_EXIT_CODE)"
fi

exit $EVAL_EXIT_CODE