#!/bin/bash

# Use port 2002 to avoid conflicts with other users
CARLA_PORT=2002
TM_PORT=8002

# Set environment variables
export CARLA_ROOT=/workspace/carla0915
export WORK_DIR=/workspace/simlingo
export SCENARIO_RUNNER_ROOT=${WORK_DIR}/Bench2Drive/scenario_runner
export LEADERBOARD_ROOT=${WORK_DIR}/Bench2Drive/leaderboard
export SAVE_PATH=/workspace/simlingo/outputs/test_run_port${CARLA_PORT}/
export PYTHONPATH="${WORK_DIR}:${CARLA_ROOT}/PythonAPI/carla:${CARLA_ROOT}/PythonAPI:${SCENARIO_RUNNER_ROOT}:${LEADERBOARD_ROOT}"

# Telemetry monitoring settings
export TELEMETRY_LOG="${SAVE_PATH}/carla_telemetry.jsonl"
export TELEMETRY_PIDFILE="/tmp/understand_carla_api_${CARLA_PORT}.pid"

# Fix conda activation for non-interactive scripts
source ~/miniconda3/etc/profile.d/conda.sh
conda activate simlingo

echo "========================================="
echo "Using CARLA PORT: ${CARLA_PORT}"
echo "Using TM PORT: ${TM_PORT}"
echo "========================================="

# Cleanup function
cleanup_on_exit() {
    echo ""
    echo "========================================="
    echo "Caught interrupt signal - cleaning up..."
    echo "========================================="
    
    # Kill telemetry monitor
    if [ -f "${TELEMETRY_PIDFILE}" ]; then
        TELEMETRY_PID=$(cat "${TELEMETRY_PIDFILE}" 2>/dev/null)
        if [ -n "${TELEMETRY_PID}" ]; then
            kill -9 "${TELEMETRY_PID}" 2>/dev/null || true
        fi
        rm -f "${TELEMETRY_PIDFILE}"
    fi
    pkill -9 -f "understand_carla_api.py.*${CARLA_PORT}" || true
    
    # Kill agent evaluator
    pkill -9 -f "leaderboard_evaluator.py.*--port ${CARLA_PORT}" || true
    
    # Stop CARLA container
    docker rm -f carla-server-${CARLA_PORT} 2>/dev/null || true
    
    echo "Cleanup complete"
    exit 130
}

trap cleanup_on_exit SIGINT SIGTERM

echo "Cleaning up existing instances on port ${CARLA_PORT}..."

# Kill processes using this port
lsof -ti:${CARLA_PORT} 2>/dev/null | xargs -r kill -9 2>/dev/null || true

# Remove Docker container
docker rm -f carla-server-${CARLA_PORT} 2>/dev/null || true

sleep 3

# Verify ports are free (both CARLA and Traffic Manager)
if lsof -ti:${CARLA_PORT} &>/dev/null; then
    echo "ERROR: Port ${CARLA_PORT} is still in use!"
    lsof -i:${CARLA_PORT}
    exit 1
fi

if lsof -ti:${TM_PORT} &>/dev/null; then
    echo "ERROR: Traffic Manager port ${TM_PORT} is still in use!"
    lsof -i:${TM_PORT}
    exit 1
fi

echo "Ports ${CARLA_PORT} and ${TM_PORT} are free"

mkdir -p ${SAVE_PATH}

echo ""
echo "CARLA_ROOT: $CARLA_ROOT"
echo "SAVE_PATH: $SAVE_PATH"

# Verify custom CARLA image exists
if ! docker images | grep -q "carla-bench2drive.*0.9.15"; then
    echo "ERROR: Custom CARLA image 'carla-bench2drive:0.9.15' not found!"
    exit 1
fi

echo ""
echo "========================================="
echo "Starting CARLA 0.9.15 on port ${CARLA_PORT} (HEADLESS)"
echo "========================================="

# Start CARLA in headless mode
docker run -d \
    --name carla-server-${CARLA_PORT} \
    --runtime=nvidia \
    --gpus all \
    --net=host \
    --shm-size=8g \
    --env=NVIDIA_VISIBLE_DEVICES=all \
    --env=NVIDIA_DRIVER_CAPABILITIES=all \
    carla-bench2drive:0.9.15 \
    bash -c "cd /home/carla && ./CarlaUE4.sh -RenderOffScreen -nosound -world-port=${CARLA_PORT} -prefernvidia -quality-level=Low"

echo "Waiting 30s for CARLA to start..."
sleep 30

# Check container is still running
if ! docker ps | grep -q carla-server-${CARLA_PORT}; then
    echo ""
    echo "ERROR: CARLA container crashed!"
    docker logs carla-server-${CARLA_PORT} 2>&1 | tail -50
    docker rm -f carla-server-${CARLA_PORT}
    exit 1
fi

# Test connection
echo "Testing CARLA connection on port ${CARLA_PORT}..."
python << EOF
import sys
sys.path.insert(0, '${CARLA_ROOT}/PythonAPI/carla')
import carla

try:
    client = carla.Client('localhost', ${CARLA_PORT})
    client.set_timeout(60.0)
    world = client.get_world()
    version = client.get_server_version()
    print(f'✓ Connected to CARLA {version} on port ${CARLA_PORT}')
    print(f'  Current map: {world.get_map().name}')
except Exception as e:
    print(f'✗ Connection failed: {e}')
    sys.exit(1)
EOF

if [ $? -ne 0 ]; then
    echo "ERROR: Cannot connect to CARLA"
    docker logs carla-server-${CARLA_PORT} 2>&1 | tail -50
    docker rm -f carla-server-${CARLA_PORT}
    exit 1
fi

# Start telemetry monitor
echo ""
echo "Starting telemetry monitor..."
stdbuf -oL python -u "${WORK_DIR}/team_code/understand_carla_api.py" \
    --host localhost \
    --port ${CARLA_PORT} \
    --headless \
    --json \
    --steps 999999999 \
    --dt 0.2 \
    --timeout 10 \
    > "${TELEMETRY_LOG}" 2>&1 &

TELEMETRY_PID=$!
echo "${TELEMETRY_PID}" > "${TELEMETRY_PIDFILE}"
echo "Telemetry monitor started (PID: ${TELEMETRY_PID})"
echo "  Log: ${TELEMETRY_LOG}"
sleep 3

# Run evaluation
echo ""
echo "========================================="
echo "Starting SimLingo agent evaluation"
echo "========================================="
cd /workspace/simlingo

python Bench2Drive/leaderboard/leaderboard/leaderboard_evaluator.py \
    --routes Bench2Drive/leaderboard/data/routes_devtest.xml \
    --repetitions 1 \
    --track SENSORS \
    --agent /workspace/simlingo/team_code/agent_simlingo.py \
    --agent-config outputs/simlingo2/checkpoints/epoch=013.ckpt/pytorch_model.pt \
    --checkpoint outputs/test_run_port${CARLA_PORT}/results.json \
    --debug 1 \
    --resume True \
    --port ${CARLA_PORT} \
    --traffic-manager-port ${TM_PORT} \
    --traffic-manager-seed 0 \
    --timeout 7200.0 \
    --gpu-rank 0

EVAL_EXIT_CODE=$?

echo ""
echo "========================================="
echo "Evaluation complete! Exit code: $EVAL_EXIT_CODE"
echo "========================================="

# Cleanup
echo "Stopping telemetry monitor..."
if [ -f "${TELEMETRY_PIDFILE}" ]; then
    TELEMETRY_PID=$(cat "${TELEMETRY_PIDFILE}" 2>/dev/null)
    if [ -n "${TELEMETRY_PID}" ]; then
        kill "${TELEMETRY_PID}" 2>/dev/null || true
    fi
    rm -f "${TELEMETRY_PIDFILE}"
fi

echo "Stopping CARLA container..."
docker rm -f carla-server-${CARLA_PORT}

if [ $EVAL_EXIT_CODE -eq 0 ]; then
    echo "✓ Evaluation completed successfully!"
else
    echo "✗ Evaluation encountered errors (exit code: $EVAL_EXIT_CODE)"
fi

exit $EVAL_EXIT_CODE
