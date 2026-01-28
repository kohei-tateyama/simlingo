# Set environment variables
export CARLA_ROOT=/workspace/carla0915
export WORK_DIR=/workspace/simlingo
export SCENARIO_RUNNER_ROOT=${WORK_DIR}/Bench2Drive/scenario_runner
export LEADERBOARD_ROOT=${WORK_DIR}/Bench2Drive/leaderboard

# CRITICAL: Agent expects SAVE_PATH for debug outputs
export SAVE_PATH=/workspace/simlingo/outputs/test_run/

# CRITICAL: Add paths in correct order - /workspace/simlingo FIRST
export PYTHONPATH="${WORK_DIR}:${CARLA_ROOT}/PythonAPI/carla:${CARLA_ROOT}/PythonAPI:${SCENARIO_RUNNER_ROOT}:${LEADERBOARD_ROOT}"

# Activate conda environment
conda activate simlingo

# Kill any existing CARLA instances
pkill -9 CarlaUE4 || true
sleep 2

# Create output directory
mkdir -p ${SAVE_PATH}

echo "CARLA_ROOT: $CARLA_ROOT"
echo "SCENARIO_RUNNER_ROOT: $SCENARIO_RUNNER_ROOT"
echo "LEADERBOARD_ROOT: $LEADERBOARD_ROOT"
echo "SAVE_PATH: $SAVE_PATH"
echo "PYTHONPATH: $PYTHONPATH"

# Test import works
echo "Testing import..."
cd /workspace/simlingo
python -c "from team_code.config_simlingo import GlobalConfig; print('✓ Import successful')"

# CRITICAL: Run from /workspace/simlingo directory
cd /workspace/simlingo

# Run evaluation - CARLA will spawn with display automatically
# The agent will load your trained model and drive autonomously
python Bench2Drive/leaderboard/leaderboard/leaderboard_evaluator.py \
    --routes Bench2Drive/leaderboard/data/routes_validation.xml \
    --repetitions 1 \
    --track SENSORS \
    --agent /workspace/simlingo/team_code/agent_simlingo.py \
    --agent-config outputs/simlingo2/checkpoints/epoch=013.ckpt/pytorch_model.pt \
    --checkpoint outputs/test_run/results.json \
    --debug 1 \
    --resume False \
    --port 2000 \
    --traffic-manager-port 8000 \
    --traffic-manager-seed 0 \
    --gpu-rank 0

echo "Evaluation complete! Check ${SAVE_PATH} for debug outputs and videos."