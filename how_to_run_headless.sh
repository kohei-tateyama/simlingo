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

echo "========================================="
echo "Cleaning up existing CARLA instances..."
echo "========================================="

# Kill all CARLA processes on host
pkill -9 -f CarlaUE4 || true
killall -9 CarlaUE4 2>/dev/null || true

# Kill processes using CARLA ports
echo "Freeing ports 2000-2010..."
for port in {2000..2010}; do
    pids=$(lsof -ti:$port 2>/dev/null)
    if [ ! -z "$pids" ]; then
        echo "  Killing processes on port $port: $pids"
        kill -9 $pids 2>/dev/null || true
    fi
done

# Remove all CARLA Docker containers
echo "Removing CARLA Docker containers..."
docker rm -f carla-server 2>/dev/null || true
docker ps -a --filter "name=carla" -q | xargs -r docker rm -f 2>/dev/null || true

# Wait for cleanup to complete
sleep 5

# Verify port 2000 is free
if lsof -ti:2000 &>/dev/null; then
    echo "ERROR: Port 2000 is still in use!"
    echo "Processes using port 2000:"
    lsof -i:2000
    echo ""
    echo "Force killing processes on port 2000..."
    kill -9 $(lsof -ti:2000) 2>/dev/null || true
    sleep 2
    
    # Check again
    if lsof -ti:2000 &>/dev/null; then
        echo "ERROR: Still cannot free port 2000. Please reboot."
        exit 1
    fi
fi

echo "✓ Port 2000 is free"

mkdir -p ${SAVE_PATH}

echo ""
echo "CARLA_ROOT: $CARLA_ROOT"
echo "SAVE_PATH: $SAVE_PATH"

# Verify custom CARLA 0.9.15 image with Bench2Drive maps exists
echo ""
echo "Checking for custom CARLA image..."
if ! docker images | grep -q "carla-bench2drive.*0.9.15"; then
    echo "ERROR: Custom CARLA image 'carla-bench2drive:0.9.15' not found!"
    echo "Building it now..."
    bash /workspace/simlingo/build_carla_bench2drive_docker.sh
fi

echo "✓ Using carla-bench2drive:0.9.15"
echo ""
echo "========================================="
echo "Starting CARLA 0.9.15 (Bench2Drive) HEADLESS"
echo "========================================="

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

echo "Waiting for CARLA to start (60s)..."
sleep 60

# Check container is still running
if ! docker ps | grep -q carla-server; then
    echo ""
    echo "ERROR: CARLA container crashed!"
    echo "========================================="
    echo "Container logs:"
    docker logs carla-server 2>&1
    echo "========================================="
    docker rm -f carla-server
    exit 1
fi

echo "✓ CARLA container is running"

# Test CARLA connection and verify version
echo ""
echo "Testing CARLA connection..."
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
    echo "ERROR: CARLA verification failed"
    echo "========================================="
    echo "Full container logs:"
    docker logs carla-server 2>&1
    echo "========================================="
    docker rm -f carla-server
    exit 1
fi

# Run evaluation
echo ""
echo "========================================="
echo "Starting SimLingo agent evaluation (headless)"
echo "========================================="
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
echo "========================================="
echo "Evaluation complete! Exit code: $EVAL_EXIT_CODE"
echo "Debug outputs: ${SAVE_PATH}"
echo "========================================="

# Cleanup
echo ""
echo "Stopping CARLA container..."
docker rm -f carla-server

if [ $EVAL_EXIT_CODE -eq 0 ]; then
    echo "✓ Evaluation completed successfully!"
else
    echo "✗ Evaluation encountered errors (exit code: $EVAL_EXIT_CODE)"
fi

exit $EVAL_EXIT_CODE