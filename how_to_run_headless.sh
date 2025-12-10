#!/bin/bash

# Set environment variables
export CARLA_ROOT=/workspace/carla0915
export WORK_DIR=/workspace/simlingo
export SCENARIO_RUNNER_ROOT=${WORK_DIR}/Bench2Drive/scenario_runner
export LEADERBOARD_ROOT=${WORK_DIR}/Bench2Drive/leaderboard
export SAVE_PATH=/workspace/simlingo/outputs/test_run2/
export PYTHONPATH="${WORK_DIR}:${CARLA_ROOT}/PythonAPI/carla:${CARLA_ROOT}/PythonAPI:${SCENARIO_RUNNER_ROOT}:${LEADERBOARD_ROOT}"

# Fix conda activation for non-interactive scripts
source ~/miniconda3/etc/profile.d/conda.sh
conda activate simlingo

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
    --checkpoint outputs/test_run2/results.json \
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