export CARLA_ROOT=/workspace/carla0915
export WORK_DIR=/workspace/simlingo
export PYTHONPATH=$PYTHONPATH:${CARLA_ROOT}
export SCENARIO_RUNNER_ROOT=${WORK_DIR}/scenario_runner
export LEADERBOARD_ROOT=${WORK_DIR}/leaderboard
export PYTHONPATH="${CARLA_ROOT}":"${SCENARIO_RUNNER_ROOT}":"${LEADERBOARD_ROOT}":${PYTHONPATH}


# export CARLA_ROOT=~/software/carla0915
# export PYTHONPATH=$PYTHONPATH:${CARLA_ROOT}/PythonAPI/carla
