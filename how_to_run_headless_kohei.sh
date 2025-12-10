#!/bin/bash


# pkill -9 -f leaderboard_evaluator.py

# Set environment variables
export CARLA_ROOT=/workspace/carla0915
export WORK_DIR=/workspace/simlingo
export SCENARIO_RUNNER_ROOT=${WORK_DIR}/Bench2Drive/scenario_runner
export LEADERBOARD_ROOT=${WORK_DIR}/Bench2Drive/leaderboard
export SAVE_PATH=/workspace/simlingo/outputs/test_run2/
export PYTHONPATH="${WORK_DIR}:${CARLA_ROOT}/PythonAPI/carla:${CARLA_ROOT}/PythonAPI:${SCENARIO_RUNNER_ROOT}:${LEADERBOARD_ROOT}"

# Telemetry monitoring settings
export TELEMETRY_LOG="${SAVE_PATH}/carla_telemetry.jsonl"
export TELEMETRY_PIDFILE="/tmp/understand_carla_api.pid"

# Fix conda activation for non-interactive scripts
source ~/miniconda3/etc/profile.d/conda.sh
conda activate simlingo

# Trap Ctrl+C and cleanup properly
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
    pkill -9 -f understand_carla_api.py || true
    
    # Kill agent evaluator
    pkill -9 -f leaderboard_evaluator.py || true
    
    # Stop CARLA container
    docker rm -f carla-server 2>/dev/null || true
    
    echo "Cleanup complete"
    exit 130
}

trap cleanup_on_exit SIGINT SIGTERM

echo "========================================="
echo "Cleaning up existing CARLA instances..."
echo "========================================="

# Kill all CARLA processes on host
pkill -9 -f CarlaUE4 || true
killall -9 CarlaUE4 2>/dev/null || true

# Kill any existing telemetry monitor
if [ -f "${TELEMETRY_PIDFILE}" ]; then
    OLD_PID=$(cat "${TELEMETRY_PIDFILE}" 2>/dev/null)
    if [ -n "${OLD_PID}" ]; then
        kill -9 "${OLD_PID}" 2>/dev/null || true
    fi
    rm -f "${TELEMETRY_PIDFILE}"
fi
pkill -9 -f understand_carla_api.py || true

# Kill processes using port 2001 only
echo "Freeing port 2001..."
pids=$(lsof -ti:2001 2>/dev/null)
if [ ! -z "$pids" ]; then
    echo "  Killing processes on port 2001: $pids"
    kill -9 $pids 2>/dev/null || true
fi

# Remove all CARLA Docker containers
echo "Removing CARLA Docker containers..."
docker rm -f carla-server 2>/dev/null || true
docker ps -a --filter "name=carla" -q | xargs -r docker rm -f 2>/dev/null || true

# Wait for cleanup to complete
sleep 5

# Verify port 2001 is free
if lsof -ti:2001 &>/dev/null; then
    echo "ERROR: Port 2001 is still in use!"
    echo "Processes using port 2001:"
    lsof -i:2001
    echo ""
    echo "Force killing processes on port 2001..."
    kill -9 $(lsof -ti:2001) 2>/dev/null || true
    sleep 2
    
    # Check again
    if lsof -ti:2001 &>/dev/null; then
        echo "ERROR: Still cannot free port 2001. Please reboot."
        exit 1
    fi
fi

echo "Port 2001 is free"

mkdir -p ${SAVE_PATH}

echo ""
echo "CARLA_ROOT: $CARLA_ROOT"
echo "SAVE_PATH: $SAVE_PATH"
echo "TELEMETRY_LOG: $TELEMETRY_LOG"

# Verify custom CARLA 0.9.15 image with Bench2Drive maps exists
echo ""
echo "Checking for custom CARLA image..."
if ! docker images | grep -q "carla-bench2drive.*0.9.15"; then
    echo "ERROR: Custom CARLA image 'carla-bench2drive:0.9.15' not found!"
    echo "Building it now..."
    bash /workspace/simlingo/build_carla_bench2drive_docker.sh
fi

echo "Using carla-bench2drive:0.9.15"
echo ""
echo "========================================="
echo "Starting CARLA 0.9.15 (Bench2Drive) HEADLESS"
echo "========================================="

# Start CARLA in headless mode with increased memory and performance flags
docker run -d \
    --name carla-server \
    --runtime=nvidia \
    --gpus all \
    --net=host \
    --shm-size=8g \
    --env=NVIDIA_VISIBLE_DEVICES=all \
    --env=NVIDIA_DRIVER_CAPABILITIES=all \
    carla-bench2drive:0.9.15 \
    bash -c "cd /home/carla && ./CarlaUE4.sh -RenderOffScreen -nosound -world-port=2001 -prefernvidia -quality-level=Low"

echo "Waiting for CARLA to start (30s)..."
sleep 30

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

echo "CARLA container is running"

# Test CARLA connection and verify version
echo ""
echo "Testing CARLA connection..."
cd /workspace/simlingo
python << 'EOF'
import carla
import sys

try:
    print("Connecting to CARLA on port 2001...")
    client = carla.Client('localhost', 2001)
    client.set_timeout(60.0)  # Increased timeout for large map operations
    
    world = client.get_world()
    version = client.get_server_version()
    maps = client.get_available_maps()
    
    print(f'CARLA connection successful')
    print(f'  Server version: {version}')
    print(f'  Current map: {world.get_map().name}')
    print(f'  Total maps available: {len(maps)}')
    
    # Verify correct version
    if version != '0.9.15':
        print(f'  ✗ ERROR: Expected CARLA 0.9.15, got {version}')
        sys.exit(1)
    
    # Check for Town13
    town13_maps = [m for m in maps if 'Town13' in m]
    if town13_maps:
        print(f'  Town13 maps found: {len(town13_maps)}')
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

# Start telemetry monitor in background
echo ""
echo "========================================="
echo "Starting telemetry monitor..."
echo "========================================="
echo "Launching understand_carla_api.py -> ${TELEMETRY_LOG}"

# Run the telemetry monitor in background with unbuffered output
# Output JSON to both file and stdout, keep stderr separate for warnings
stdbuf -oL python -u "${WORK_DIR}/team_code/understand_carla_api.py" \
    --host localhost \
    --port 2001 \
    --headless \
    --json \
    --steps 999999999 \
    --dt 0.2 \
    --timeout 10 \
    > "${TELEMETRY_LOG}" 2>&1 &

TELEMETRY_PID=$!
echo "${TELEMETRY_PID}" > "${TELEMETRY_PIDFILE}"
echo "Telemetry monitor started (PID: ${TELEMETRY_PID})"
echo "  Writing telemetry to: ${TELEMETRY_LOG}"
echo ""
echo "  IMPORTANT: To view telemetry in real-time, open another terminal and run:"
echo "     tail -f ${TELEMETRY_LOG}"
echo ""
echo "  To stop at any time: Press Ctrl+C (cleanup runs automatically)"
echo "  If this does not happen enter: pkill -9 -f leaderboard_evaluator.py
"
echo ""

# Give telemetry monitor a moment to connect
sleep 3

# Check if telemetry monitor is still running
if ! kill -0 "${TELEMETRY_PID}" 2>/dev/null; then
    echo "⚠ WARNING: Telemetry monitor exited early (no vehicle spawned yet - this is normal)"
    echo "  It will wait for a vehicle to appear once the agent starts the scenario"
else
    echo "Telemetry monitor is running"
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
    --port 2001 \
    --traffic-manager-port 8001 \
    --traffic-manager-seed 0 \
    --timeout 600.0 \
    --gpu-rank 0

EVAL_EXIT_CODE=$?

echo ""
echo "========================================="
echo "Evaluation complete! Exit code: $EVAL_EXIT_CODE"
echo "Debug outputs: ${SAVE_PATH}"
echo "========================================="

# Stop telemetry monitor
echo ""
echo "Stopping telemetry monitor..."
if [ -f "${TELEMETRY_PIDFILE}" ]; then
    TELEMETRY_PID=$(cat "${TELEMETRY_PIDFILE}" 2>/dev/null)
    if [ -n "${TELEMETRY_PID}" ]; then
        kill "${TELEMETRY_PID}" 2>/dev/null || true
        sleep 1
        kill -9 "${TELEMETRY_PID}" 2>/dev/null || true
        echo "Telemetry monitor stopped"
    fi
    rm -f "${TELEMETRY_PIDFILE}"
fi
pkill -9 -f understand_carla_api.py 2>/dev/null || true

# Show telemetry summary
if [ -f "${TELEMETRY_LOG}" ]; then
    LINE_COUNT=$(wc -l < "${TELEMETRY_LOG}" 2>/dev/null || echo 0)
    FILE_SIZE=$(du -h "${TELEMETRY_LOG}" 2>/dev/null | cut -f1 || echo "0")
    echo ""
    echo "Telemetry Summary:"
    echo "  Total telemetry samples: ${LINE_COUNT}"
    echo "  Log file size: ${FILE_SIZE}"
    echo "  Log file: ${TELEMETRY_LOG}"
    
    if [ ${LINE_COUNT} -gt 0 ]; then
        echo ""
        echo "First telemetry sample:"
        head -n 1 "${TELEMETRY_LOG}"
        echo ""
        echo "Last telemetry sample:"
        tail -n 1 "${TELEMETRY_LOG}"
    else
        echo "  ⚠ No telemetry data captured (vehicle may not have spawned)"
    fi
fi

# Cleanup
echo ""
echo "Stopping CARLA container..."
docker rm -f carla-server

if [ $EVAL_EXIT_CODE -eq 0 ]; then
    echo "Evaluation completed successfully!"
else
    echo "✗ Evaluation encountered errors (exit code: $EVAL_EXIT_CODE)"
fi

exit $EVAL_EXIT_CODE