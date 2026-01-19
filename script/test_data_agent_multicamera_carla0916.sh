#!/bin/bash

# Test script for data_agent_multicamera.py targeting CARLA 0.9.16
# Based on test_data_agent_multicamera.sh but adjusted to not touch 0.9.15 workflows.

set -u

# =============================================================================
# ENVIRONMENT SETUP
# =============================================================================
export CARLA_ROOT=/workspace/carla0916
export WORK_DIR=/workspace/simlingo
export SCENARIO_RUNNER_ROOT=${WORK_DIR}/scenario_runner
export LEADERBOARD_ROOT=${WORK_DIR}/leaderboard
export PYTHONPATH="${WORK_DIR}:${CARLA_ROOT}/PythonAPI/carla:${CARLA_ROOT}/PythonAPI:${SCENARIO_RUNNER_ROOT}:${LEADERBOARD_ROOT}"


# Data collection settings
export DATAGEN=1
export TEAM_AGENT=/workspace/simlingo/team_code/data_agent_multicamera_carla0916.py
export TEAM_CONFIG="data_collection"
export SAVE_PATH=/media/external_ssd/workspace/simlingo/database/simlingo_v4_bosch_2025_01_10/data/simlingo_carla0916_2_
export TOWN="Town03"  # Will be overridden by route XML
export REPETITION="1"
export SCENARIO_NAME="training_3_scenarios"
export WEATHER_CONFIG="random_weather_seed_42_balanced_100"

## RHT
# export ROUTE_CONFIG="routes_devtest_LHT" # "routes_training_LHT", "bench2drive220_LHT", routes_validation_LHT", "routes_devtest_LHT"
# # export ROUTES="/workspace/simlingo/leaderboard/data/routes_training.xml"
# # export ROUTES="/workspace/simlingo/leaderboard/data/routes_validation.xml"
# # export ROUTES="/workspace/simlingo/leaderboard/data/routes_devtest.xml"
# export ROUTES="/workspace/simlingo/leaderboard/data/bench2drive220.xml"

## LHT
export ROUTE_CONFIG="bench2drive220_LHT" # "routes_training_LHT", "bench2drive220_LHT", routes_validation_LHT", "routes_devtest_LHT"
# export ROUTES="/workspace/simlingo/leaderboard/data/routes_training_LHT.xml"
# export ROUTES="/workspace/simlingo/leaderboard/data/routes_validation_LHT.xml"
# export ROUTES="/workspace/simlingo/leaderboard/data/routes_devtest_LHT.xml"
export ROUTES="/workspace/simlingo/leaderboard/data/bench2drive220_LHT.xml"

export ROUTES_SUBSET="24206" #"61711"  # "0,1,2,3,4,5,6,7,8,9"
## Running all the routes in the ROUTES massive data collection =========================
# Source common helpers and derive ROUTES_SUBSET from ROUTES if not set
if [ -f "${WORK_DIR}/script/common.sh" ]; then
    # shellcheck source=/dev/null
    . "${WORK_DIR}/script/common.sh"
    # build_routes_subset # export ROUTES_SUBSET
fi
## Running all the routes in the ROUTES massive data collection =========================

# Use consolidated save layout (include scenario/route_config/weather)
export SAVE_FLAT=0

# Activate conda environment
source ~/miniconda3/etc/profile.d/conda.sh
conda activate simlingo16


LEADERBOARD_TIMEOUT="${LEADERBOARD_TIMEOUT:-100}"
# LEADERBOARD_TIMEOUT="${LEADERBOARD_TIMEOUT:-0}" # no timeout  

# CARLA port (can be overridden by environment before running the script)
export PORT_CARLA=${PORT_CARLA:-2000}
# Traffic Manager port (can be overridden)
export TRAFFIC_MANAGER_PORT=${TRAFFIC_MANAGER_PORT:-8000}

# Color and logging helpers provided by script/common.sh (sourced earlier)

# =============================================================================
# CLEANUP FUNCTION
# =============================================================================
cleanup_carla() {
    sep
    info "Cleaning up CARLA and leaderboard (0.9.16) (!!!)..."
    sep

    pkill -9 -f "leaderboard_evaluator.py" 2>/dev/null || true

    pids=$(lsof -ti:${PORT_CARLA} 2>/dev/null)
    if [ ! -z "$pids" ]; then
        warn "Killing processes on port ${PORT_CARLA}: $pids"
        kill -9 $pids 2>/dev/null || true
    fi
    pids=$(lsof -ti:${TRAFFIC_MANAGER_PORT} 2>/dev/null)
    if [ ! -z "$pids" ]; then
        warn "Killing processes on port ${TRAFFIC_MANAGER_PORT}: $pids"
        kill -9 $pids 2>/dev/null || true
    fi

    docker rm -f carla-server 2>/dev/null || true
    sleep 3
}

stop_carla() {
    info "Stopping CARLA container..."
    docker stop carla-server 2>/dev/null || true
    docker rm -f carla-server 2>/dev/null || true
}

# Flag set when user sends SIGINT or SIGTERM
INTERRUPTED=0

on_signal() {
    # Called for SIGINT and SIGTERM. Do not exit here so main() can decide to run post-processing.
    INTERRUPTED=1
    echo ""
    warn "Signal received (SIGINT/SIGTERM) - stopping CARLA and returning to main..."
    # Stop container and also attempt to kill leaderboard process so Ctrl+C reliably stops collection
    stop_carla 2>/dev/null || true
    pkill -TERM -f "leaderboard_evaluator.py" 2>/dev/null || true
    sleep 1
    pkill -9 -f "leaderboard_evaluator.py" 2>/dev/null || true
}

cleanup_on_exit() {
    local exit_code=$?
    echo ""
    warn "Script exiting (code: $exit_code) - final cleanup..."
    stop_carla 2>/dev/null || true
    exit $exit_code
}

# Install traps: on_signal for INT/TERM (stop carla and let main continue), final cleanup on EXIT
trap on_signal INT TERM
trap cleanup_on_exit EXIT

# =============================================================================
# START CARLA
# =============================================================================
start_carla() {
    mkdir -p ${SAVE_PATH}
    mkdir -p ${WORK_DIR}/carla_logs

    sep
    info "CARLA_ROOT: $CARLA_ROOT"
    info "SAVE_PATH : $SAVE_PATH"
    sep

    # Check for custom CARLA image for 0.9.16
    if ! docker images | grep -q "carla-bench2drive.*0.9.16"; then
        warn "Custom CARLA image 'carla-bench2drive:0.9.16' not found locally. Falling back to carlasim/carla:0.9.16"
    fi

    sep
    info "Starting CARLA 0.9.16 HEADLESS on port ${PORT_CARLA}"
    sep

    docker rm -f carla-server 2>/dev/null || true

    docker run -d \
        --name carla-server \
        --runtime=nvidia \
        --gpus all \
        --net=host \
        --shm-size=1g \
        --env=NVIDIA_VISIBLE_DEVICES=all \
        --env=NVIDIA_DRIVER_CAPABILITIES=all \
        -v ${WORK_DIR}/carla_logs:/workspace/CarlaUE4/Saved/Logs \
        -v /workspace/carla0916/CarlaUE4/Content:/workspace/CarlaUE4/Content:ro \
        carla-bench2drive:0.9.16 \
        bash -c "cd /workspace && ./CarlaUE4.sh -opengl -RenderOffScreen -nosound -world-port=${PORT_CARLA} -carla-rpc-port=${PORT_CARLA} -log"

    info "Waiting 80s for CARLA to start..."
    sleep 80

    if ! docker ps | grep -q carla-server; then
        echo ""
        err "CARLA container crashed!"
        sep
        docker logs carla-server 2>&1
        sep
        exit 1
    fi

    info "Testing CARLA connection..."
    sep

    python - <<'PY'
import carla
import sys
import os

try:
    port = int(os.environ.get('PORT_CARLA', '2000'))
    client = carla.Client('localhost', port)
    client.set_timeout(30.0)
    world = client.get_world()
    version = client.get_server_version()
    print(f'✓ CARLA connection successful')
    print(f'✓ Server version: {version}')
    if version != '0.9.16':
        print(f'ERROR: Expected 0.9.16, got {version}')
        sys.exit(1)
except Exception as e:
    print(f'ERROR: Connection failed: {e}')
    sys.exit(1)
PY

    if [ $? -ne 0 ]; then
        err "CARLA verification failed"
        exit 1
    fi

    sep
    info "CARLA ready!"
    sep
    
    # Check available maps and auto-filter routes to available maps
    info "Checking available maps and filtering routes..."
    AUTO_ROUTES_SUBSET=$(python - <<'PY'
import carla
import sys
import os
import xml.etree.ElementTree as ET

try:
    port = int(os.environ.get('PORT_CARLA', '2000'))
    client = carla.Client('localhost', port)
    client.set_timeout(10.0)
    
    available_maps = [m.replace('/Game/Carla/Maps/', '') for m in client.get_available_maps()]
    print(f'Available maps: {", ".join(sorted(available_maps))}', file=sys.stderr)
    
    # Parse routes file to check required towns
    routes_file = os.environ.get('ROUTES', '')
    if routes_file and os.path.exists(routes_file):
        tree = ET.parse(routes_file)
        root = tree.getroot()
        
        # Build list of route indices that use available maps
        available_route_indices = []
        skipped_routes = []
        
        for idx, route in enumerate(root.findall('.//route')):
            town = route.get('town')
            route_id = route.get('id', str(idx))
            if town and town in available_maps:
                available_route_indices.append(route_id)
            elif town:
                skipped_routes.append(f'{route_id} (Town: {town})')
        
        if skipped_routes:
            print(f'\nFiltered out {len(skipped_routes)} routes with missing maps:', file=sys.stderr)
            for route_info in skipped_routes[:5]:  # Show first 5
                print(f'  - {route_info}', file=sys.stderr)
            if len(skipped_routes) > 5:
                print(f'  ... and {len(skipped_routes) - 5} more', file=sys.stderr)
        
        if available_route_indices:
            print(f'\n✓ Found {len(available_route_indices)} routes with available maps', file=sys.stderr)
            # Output comma-separated route indices to stdout
            print(','.join(available_route_indices))
        else:
            print('\nERROR: No routes found with available maps!', file=sys.stderr)
            sys.exit(1)
    else:
        print('', file=sys.stderr)
        sys.exit(0)
    
except Exception as e:
    print(f'Warning: Could not verify map availability: {e}', file=sys.stderr)
    sys.exit(0)
PY
)

    if [ $? -eq 0 ] && [ -n "$AUTO_ROUTES_SUBSET" ]; then
        # Override ROUTES_SUBSET if not manually set
        if [ -z "${ROUTES_SUBSET:-}" ] || [ "${ROUTES_SUBSET}" = "0" ]; then
            export ROUTES_SUBSET="$AUTO_ROUTES_SUBSET"
            info "Auto-filtered ROUTES_SUBSET: ${ROUTES_SUBSET}"
        else
            info "Using manual ROUTES_SUBSET: ${ROUTES_SUBSET}"
        fi
    fi
    # If ROUTES_SUBSET is set to a specific route id (or comma list), set SAVE_SUBDIR
    # so the agent will store outputs under a folder that includes the route id(s).
    if [ -n "${ROUTES_SUBSET:-}" ] && [ "${ROUTES_SUBSET}" != "0" ]; then
        # SAVE_SUBDIR should NOT include the per-route id; keep route ids out of the
        # folder path so the agent can place the route id into the Town folder name.
        ROUTES_SUB_CLEAN=$(echo "${ROUTES_SUBSET}" | tr -d '[:space:]' | tr ',' '_')
        if [ "${SAVE_FLAT:-0}" = "1" ]; then
            export SAVE_SUBDIR="${ROUTES_SUB_CLEAN}"
        else
            export SAVE_SUBDIR="${SCENARIO_NAME}/${ROUTE_CONFIG}"
        fi
        info "Setting SAVE_SUBDIR to: ${SAVE_SUBDIR} (route ids excluded)"
    fi
    
    sep
}

# =============================================================================
# RUN LEADERBOARD EVALUATION (uses same leaderboard but with 0.9.16 CARLA)
# =============================================================================
run_leaderboard() {
    sep
    info "Running data_agent_multicamera.py via leaderboard against CARLA 0.9.16"
    sep

    cd /workspace/simlingo/leaderboard

    info "Agent    : ${TEAM_AGENT}"
    info "Routes   : ${ROUTES}"
    info "Port     : ${PORT_CARLA}"
    info "Output   : ${SAVE_PATH}"
    sep

    LB_ARGS=(--routes=${ROUTES} --repetitions=1 --agent=${TEAM_AGENT} --agent-config=${TEAM_CONFIG} --port=${PORT_CARLA} --traffic-manager-port=${TRAFFIC_MANAGER_PORT})
    if [ -n "${LEADERBOARD_CHECKPOINT:-}" ]; then
        LB_ARGS+=(--checkpoint=${LEADERBOARD_CHECKPOINT})
    fi
    # Validate ROUTES_SUBSET against actual route ids in the routes XML
    if [ -n "${ROUTES_SUBSET:-}" ] && [ "${ROUTES_SUBSET}" != "0" ]; then
        # Build list of valid ids from the routes file
        VALID_IDS=$(python - <<'PY'
import xml.etree.ElementTree as ET, os, sys
routes_file = os.environ.get('ROUTES','')
if not routes_file or not os.path.exists(routes_file):
    print('', end='')
    sys.exit(0)
tree = ET.parse(routes_file)
root = tree.getroot()
ids = [r.get('id') for r in root.findall('.//route') if r.get('id')]
print(','.join(ids), end='')
PY
)

        if [ -n "$VALID_IDS" ]; then
            # Filter requested ROUTES_SUBSET by checking membership in VALID_IDS string
            OLD_SUBSET="$ROUTES_SUBSET"
            NEW_SUBSET=""
            IFS=, read -ra REQ_ARR <<< "$OLD_SUBSET"
            for rid in "${REQ_ARR[@]}"; do
                if [[ ",${VALID_IDS}," == *",${rid},"* ]]; then
                    if [ -z "$NEW_SUBSET" ]; then
                        NEW_SUBSET="$rid"
                    else
                        NEW_SUBSET="$NEW_SUBSET,$rid"
                    fi
                else
                    warn "Requested route id '$rid' not found in ${ROUTES}; it will be ignored"
                fi
            done
            # Normalize commas and remove accidental leading/trailing commas
            NEW_SUBSET=$(echo "$NEW_SUBSET" | sed -e 's/,\+/,/g' -e 's/^,//' -e 's/,$//')
            if [ -n "$NEW_SUBSET" ]; then
                ROUTES_SUBSET="$NEW_SUBSET"
                LB_ARGS+=(--routes-subset=${ROUTES_SUBSET})
                # If the subset resolves to a single id, export it so the agent
                # can include it in the Town folder name (as Route<id>).
                if [[ "$ROUTES_SUBSET" != *,* ]]; then
                    export FORCE_ROUTE_ID="$ROUTES_SUBSET"
                    single_id=$(echo "$ROUTES_SUBSET" | xargs)
                    export ROUTE_ID_TMP="${single_id}"
                    route_town=$(python - <<'PY'
import xml.etree.ElementTree as ET, os, sys
rid = os.environ.get('ROUTE_ID_TMP','')
routes_file = os.environ.get('ROUTES','')
if routes_file and os.path.exists(routes_file) and rid:
    tree = ET.parse(routes_file)
    for r in tree.getroot().findall('.//route'):
        if r.get('id') == rid:
            print(r.get('town') or r.get('map') or '')
            sys.exit(0)
print('', end='')
PY
                    )
                    unset ROUTE_ID_TMP
                    if [ -n "${route_town}" ]; then
                        export FORCE_TOWN="${route_town}"
                        info "Setting FORCE_TOWN=${FORCE_TOWN} for route ${single_id}"
                        # Pre-load the correct town in CARLA to avoid timeout during route start
                        info "Pre-loading ${route_town} in CARLA..."
                        python - <<PY
import carla
import sys
import os
import time
try:
    port = int(os.environ.get('PORT_CARLA', '2000'))
    client = carla.Client('localhost', port)
    client.set_timeout(10.0)
    
    world = client.get_world()
    current_map = world.get_map().name.split('/')[-1]
    target_map_short = '${route_town}'
    
    if current_map != target_map_short:
        print(f'Switching from {current_map} to {target_map_short}...')
        
        # Get the actual full path from CARLA's available maps
        available_maps = client.get_available_maps()
        target_map_full = None
        
        for map_path in available_maps:
            map_name = map_path.split('/')[-1]
            if map_name == target_map_short:
                target_map_full = map_path
                break
        
        if not target_map_full:
            print(f'ERROR: Could not find {target_map_short} in available maps', file=sys.stderr)
            print(f'Available maps with paths:', file=sys.stderr)
            for m in available_maps:
                print(f'  {m}', file=sys.stderr)
            sys.exit(1)
        
        # Use a longer timeout for map loading (Town12 is large)
        client.set_timeout(180.0)
        start = time.time()
        world = client.load_world(target_map_full)
        elapsed = time.time() - start
        print(f'[INFO] ✓ Loaded {target_map_short} in {elapsed:.1f}s')
        # Reset to normal timeout
        client.set_timeout(10.0)
    else:
        print(f'[INFO] ✓ Already on {target_map_short}')
except Exception as e:
    print(f'ERROR: Failed to load ${route_town}: {e}', file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)
PY
                    fi
                fi
            else
                warn "After filtering, no valid route ids remain in ROUTES_SUBSET; not passing --routes-subset"
            fi
        else
            warn "Could not read route ids from ${ROUTES}; skipping subset validation"
            LB_ARGS+=(--routes-subset=${ROUTES_SUBSET})
            if [[ "${ROUTES_SUBSET}" != *,* ]]; then
                export FORCE_ROUTE_ID="${ROUTES_SUBSET}"
                single_id=$(echo "${ROUTES_SUBSET}" | xargs)
                export ROUTE_ID_TMP="${single_id}"
                route_town=$(python - <<'PY'
import xml.etree.ElementTree as ET, os, sys
rid = os.environ.get('ROUTE_ID_TMP','')
routes_file = os.environ.get('ROUTES','')
if routes_file and os.path.exists(routes_file) and rid:
    tree = ET.parse(routes_file)
    for r in tree.getroot().findall('.//route'):
        if r.get('id') == rid:
            print(r.get('town') or r.get('map') or '')
            sys.exit(0)
print('', end='')
PY
                )
                unset ROUTE_ID_TMP
                if [ -n "${route_town}" ]; then
                    export FORCE_TOWN="${route_town}"
                    info "Setting FORCE_TOWN=${FORCE_TOWN} for route ${single_id}"
                fi
            fi
        fi
    fi

    if [ "${LEADERBOARD_TIMEOUT:-0}" -eq 0 ]; then
        python leaderboard/leaderboard_evaluator.py "${LB_ARGS[@]}"
    else
        # Run leaderboard under a small bash wrapper so we can trap SIGTERM and kill the whole
        # process group. This ensures timeout terminates leaderboard and any children it spawned.
        # The wrapper uses: trap "kill 0" SIGTERM ; exec "$@" -- python ...
        timeout -k 10 "${LEADERBOARD_TIMEOUT}" bash -c 'trap "kill 0" SIGTERM; exec "$@"' -- python leaderboard/leaderboard_evaluator.py "${LB_ARGS[@]}"
    fi

    local exit_code=$?

    sep
    if [ $exit_code -eq 0 ]; then
        info "Leaderboard evaluation completed successfully!"
    else
        info "Leaderboard exited with code $exit_code — attempting to display saved results.json.gz (if any)"
        FOUND_RESULTS=0
        for f in $(find "${SAVE_PATH}" -maxdepth 6 -type f -name "results.json.gz" 2>/dev/null); do
            # info "Found results file: $f"
            FOUND_RESULTS=1
        done
        if [ $FOUND_RESULTS -eq 0 ]; then
            info "No results.json.gz found under ${SAVE_PATH}"
        fi
        if find "${SAVE_PATH}" -maxdepth 6 -type f -name "results.json.gz" -print -quit | grep -q .; then
            exit_code=0
        fi
    fi
    sep

    return $exit_code
}

# =============================================================================
# POST-PROCESS: PATCH MULTICAMERA IMAGES
# =============================================================================
patch_multicamera_images() {
    sep
    info "Post-processing: Patching multicamera RGB images..."
    sep

    info "Searching for datasets under: ${SAVE_PATH}"

    # If FORCE_ROUTE_ID is set, search recursively for folders that include the token
    if [ -n "${FORCE_ROUTE_ID:-}" ]; then
        info "Looking for dataset containing route id: ${FORCE_ROUTE_ID} (recursive search)"
        DATASET_PATH=""
        while IFS= read -r dir; do
            if [ -d "$dir/rgb" ] && [ -d "$dir/measurements" ]; then
                DATASET_PATH="$dir"
                break
            fi
        done < <(find "${SAVE_PATH}" -type d -name "*route${FORCE_ROUTE_ID}*" 2>/dev/null | sort -r)

        if [ -z "${DATASET_PATH}" ]; then
            while IFS= read -r dir; do
                if [ -d "$dir/rgb" ] && [ -d "$dir/measurements" ]; then
                    DATASET_PATH="$dir"
                    break
                fi
            done < <(find "${SAVE_PATH}" -type d -path "*${FORCE_ROUTE_ID}*" 2>/dev/null | sort -r)
        fi

        if [ -n "${DATASET_PATH}" ]; then
            info "Found dataset for route ${FORCE_ROUTE_ID}: ${DATASET_PATH}"
        else
            info "No dataset found containing route id ${FORCE_ROUTE_ID}"
        fi
    fi

    # Prefer .last_run sentinel written by the agent during the run (fallback)
    if [ -z "${DATASET_PATH:-}" ] && [ -f "${SAVE_PATH}/.last_run" ]; then
        last_run_path=$(cat "${SAVE_PATH}/.last_run")
        if [ -n "${FORCE_ROUTE_ID:-}" ]; then
            if echo "${last_run_path}" | grep -q "route${FORCE_ROUTE_ID}_"; then
                DATASET_PATH="${last_run_path}"
                info "Found .last_run sentinel matching route ${FORCE_ROUTE_ID}: ${DATASET_PATH}"
            else
                info ".last_run sentinel does not match FORCE_ROUTE_ID=${FORCE_ROUTE_ID}; ignoring: ${last_run_path}"
            fi
        else
            DATASET_PATH="${last_run_path}"
            info "Found .last_run sentinel: ${DATASET_PATH}"
        fi
    fi

    if [ -z "$DATASET_PATH" ]; then
        info "Trying fallback pattern..."
        DATASET_PATH=$(find ${SAVE_PATH} -maxdepth 6 -type d -name "Town*_Rep*" 2>/dev/null | while read dir; do
            if [ -d "$dir/rgb" ]; then
                echo "$dir"
            fi
        done | sort -r | head -1)
    fi

    if [ -z "$DATASET_PATH" ]; then
        err "No dataset path found!"
        warn "Searched under: ${SAVE_PATH}"
        return 1
    fi

    info "Found dataset path: $DATASET_PATH"

    if [ ! -d "${DATASET_PATH}/rgb" ]; then
        err "rgb folder not found in: $DATASET_PATH"
        return 1
    fi

    cd /workspace/simlingo || return 1

    sep
    info "Applying geometric layout (creates patched.jpg)..."
    python bosch_utils/tools/batch_patch_multicamera.py "$DATASET_PATH" --layout geometric
    local patch1_exit=$?

    sep
    info "Applying three-quarter layout (creates patched2*.jpg)..."
    python bosch_utils/tools/batch_patch_multicamera2.py "$DATASET_PATH" --layout three_quarter
    local patch2_exit=$?

    if [ $patch1_exit -eq 0 ] && [ $patch2_exit -eq 0 ]; then
        info "✓ Multicamera patching completed successfully!"
        return 0
    else
        err "Patching encountered errors!"
        return 1
    fi
}

# =============================================================================
# MAIN
# =============================================================================
main() {
    sep
    info "Testing data_agent_multicamera.py (CARLA 0.9.16)"
    sep

    cleanup_carla
    start_carla
    run_leaderboard
    local eval_exit=$?

    # Determine whether to run patching:
    # - run if leaderboard succeeded (eval_exit==0)
    # - OR if the process was interrupted (CTRL+C / SIGTERM)
    # - OR if saved output files (results.json.gz or records.json.gz) exist under SAVE_PATH
    SHOULD_PATCH=0
    if [ $eval_exit -eq 0 ]; then
        SHOULD_PATCH=1
    fi
    if [ "$INTERRUPTED" -eq 1 ]; then
        SHOULD_PATCH=1
    fi

    # Also check for saved output files (agent may have written them on timeout or signal)
    if find "${SAVE_PATH}" -maxdepth 6 -type f -name "results.json.gz" -print -quit | grep -q .; then
        SHOULD_PATCH=1
    elif find "${SAVE_PATH}" -maxdepth 6 -type f -name "records.json.gz" -print -quit | grep -q .; then
        SHOULD_PATCH=1
    fi

    if [ $SHOULD_PATCH -eq 1 ]; then
        info "Running post-processing patch (outputs found or interrupted)."
        patch_multicamera_images
        local patch_exit=$?
    else
        warn "Skipping patching due to data collection failure and no saved outputs"
        patch_exit=1
    fi

    sep
    info "Test complete!"
    sep

    if [ $eval_exit -eq 0 ]; then
        info "Check output at: ${SAVE_PATH}"
    fi

    exit $eval_exit
}


main
