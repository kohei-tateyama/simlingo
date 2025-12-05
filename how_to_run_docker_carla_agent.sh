#!/bin/bash

# Set environment variables
export CARLA_ROOT=/workspace/carla0915
export WORK_DIR=/workspace/simlingo
export SCENARIO_RUNNER_ROOT=${WORK_DIR}/Bench2Drive/scenario_runner
export LEADERBOARD_ROOT=${WORK_DIR}/Bench2Drive/leaderboard
export SAVE_PATH=/workspace/simlingo/outputs/test_run/
export PYTHONPATH="${WORK_DIR}:${CARLA_ROOT}/PythonAPI/carla:${CARLA_ROOT}/PythonAPI:${SCENARIO_RUNNER_ROOT}:${LEADERBOARD_ROOT}"

# Activate conda environment
conda activate simlingo

# Kill any existing CARLA instances - IMPROVED CLEANUP
echo "Cleaning up existing CARLA instances..."
pkill -9 CarlaUE4 || true

# Force remove the container even if stopped
docker rm -f carla-server 2>/dev/null || true

# Also clean up any other carla containers
docker ps -a --filter "name=carla" -q | xargs -r docker rm -f 2>/dev/null || true

sleep 3

# Create output directory
mkdir -p ${SAVE_PATH}

echo "CARLA_ROOT: $CARLA_ROOT"
echo "SAVE_PATH: $SAVE_PATH"

# Verify custom image exists
if ! docker images | grep -q "carla-bench2drive.*0.9.15"; then
    echo "ERROR: Custom CARLA image 'carla-bench2drive:0.9.15' not found!"
    echo "Please run: bash /workspace/simlingo/build_carla_bench2drive_docker.sh"
    exit 1
fi

echo "✓ Custom CARLA image found"
echo "Starting CARLA 0.9.15 (Bench2Drive) in Docker with display..."

# Allow Docker to connect to X11
xhost +local:docker

# Start CARLA with Bench2Drive maps
#with display
docker run -d \
    --name carla-server \
    --runtime=nvidia \
    --net=host \
    --env=DISPLAY=$DISPLAY \
    --env=NVIDIA_VISIBLE_DEVICES=all \
    --env=NVIDIA_DRIVER_CAPABILITIES=all \
    --volume="/tmp/.X11-unix:/tmp/.X11-unix:rw" \
    carla-bench2drive:0.9.15 \
    ./CarlaUE4.sh -nosound -world-port=2000


echo "Waiting for CARLA to start (60s)..."
sleep 60

# Test CARLA connection and verify Town13
echo "Testing CARLA connection and verifying Town13..."
cd /workspace/simlingo
python << 'EOF'
import carla
import sys

try:
    client = carla.Client('localhost', 2000)
    client.set_timeout(10.0)
    world = client.get_world()
    maps = client.get_available_maps()
    
    print(f'✓ CARLA connection successful')
    print(f'  Version: {client.get_server_version()}')
    print(f'  Total maps available: {len(maps)}')
    
    # Check for Bench2Drive maps
    town13_maps = [m for m in maps if 'Town13' in m]
    if town13_maps:
        print(f'  ✓ Town13 found: {town13_maps}')
    else:
        print(f'  ✗ WARNING: Town13 NOT found!')
        print(f'  Available towns: {[m.split("/")[-1] for m in maps[:10]]}...')
        sys.exit(1)
        
except Exception as e:
    print(f'✗ CARLA connection failed: {e}')
    sys.exit(1)
EOF

if [ $? -ne 0 ]; then
    echo "ERROR: CARLA verification failed. Stopping container..."
    docker stop carla-server
    docker rm carla-server
    xhost -local:docker
    exit 1
fi

# Run evaluation with SimLingo agent
echo ""
echo "Starting SimLingo agent evaluation..."
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
echo "Evaluation complete! Exit code: $EVAL_EXIT_CODE"
echo "Debug outputs saved to: ${SAVE_PATH}"

# Cleanup
echo "Stopping CARLA container..."
docker stop carla-server
docker rm carla-server
xhost -local:docker

if [ $EVAL_EXIT_CODE -eq 0 ]; then
    echo "✓ Evaluation completed successfully!"
else
    echo "✗ Evaluation encountered errors (exit code: $EVAL_EXIT_CODE)"
fi

exit $EVAL_EXIT_CODE