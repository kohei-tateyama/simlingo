#!/bin/bash

# Test script for data_agent_multicamera.py targeting CARLA 0.9.16
# Based on test_data_agent_multicamera.sh but adjusted to not touch 0.9.15 workflows.

set -u

LEADERBOARD_VERSION="leaderboard21" # "leaderboard"

# =============================================================================
# ENVIRONMENT SETUP (CARLA 0.9.16 / Leaderboard 2.1)
# =============================================================================
unset PYTHONPATH
export PYTHONNOUSERSITE=1
export WORK_DIR="/workspace/simlingo"
export CARLA_ROOT="/workspace/carla0916"
export LEADERBOARD_ROOT="${WORK_DIR}/leaderboard21"
export SCENARIO_RUNNER_ROOT="${WORK_DIR}/scenario_runner21"
# export LD_LIBRARY_PATH="${CARLA_API_BASE}/carla.libs:${LD_LIBRARY_PATH:-}"
# export PYTHONPATH="${CARLA_API_BASE}:${CARLA_SRC}:${LEADERBOARD_ROOT}:${SCENARIO_RUNNER_ROOT}:${WORK_DIR}"

export CARLA_API_BASE="/workspace/carla0916/PythonAPI/carla/dist/carla_0916_lib"
export CARLA_SRC="/workspace/carla0916/PythonAPI/carla"
export CARLA_AGENTS="${CARLA_SRC}"
export LD_LIBRARY_PATH="${CARLA_API_BASE}/carla.libs:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="${CARLA_API_BASE}:${CARLA_AGENTS}:${LEADERBOARD_ROOT}:${SCENARIO_RUNNER_ROOT}:${WORK_DIR}"

echo "[DEBUG] Verifying CARLA 0.9.16 Python API is importable..."
python3 - <<'PY'
import sys, os

# Force the CARLA API base path to the front of sys.path to avoid importing other versions
carla_base = os.environ.get('CARLA_API_BASE', '')
if carla_base:
    # remove obvious site-packages carla entries
    sys.path = [p for p in sys.path if not (('site-packages' in p and 'carla' in p.lower()))]
    if carla_base not in sys.path:
        sys.path.insert(0, carla_base)

try:
    import carla
    # Try to get the client-reported version if possible
    client_version = None
    try:
        client_version = carla.Client('localhost', 2000).get_client_version()
    except Exception:
        # ignore connection errors; fall back to API inspection below
        client_version = None

    # Heuristic: 0.9.16 exposes Map.get_driving_side and other helpers
    api_ok = hasattr(carla, 'Map') and hasattr(carla.Map, 'get_driving_side')

    print(f'Active Path: {getattr(carla, "__file__", "<unknown>")}')
    print(f'Detected client version: {client_version}')
    print(f'API heuristic (Map.get_driving_side present): {api_ok}')

    verified = False
    if client_version:
        verified = str(client_version).startswith('0.9.16')
    else:
        verified = api_ok

    print(f'0.9.16 Verified: {verified}')
    if not verified:
        print('FATAL: Imported CARLA PythonAPI does not appear to be 0.9.16')
        sys.exit(1)
    else:
        print('\033[92m[PROCEEDING] 0.9.16 Python API confirmed. Launching simulation...\033[0m')
except Exception as e:
    print(f'FATAL ERROR: Could not import CARLA PythonAPI: {e}')
    sys.exit(1)
PY

#####

# Data collection settings
export DATAGEN=1
export TEAM_AGENT=/workspace/simlingo/team_code/data_agent_multicamera_carla0916.py
# export TEAM_AGENT=/workspace/simlingo/team_code/data_agent_multicamera_carla0916_back.py
export TEAM_CONFIG="data_collection"
# export SAVE_PATH=/media/external_ssd/workspace/simlingo/database/simlingo_v4_bosch_2025_01_10/data/simlingo_carla0916_2_
export SAVE_PATH=/workspace/simlingo/database/simlingo_carla0916_2_
export TOWN="Town03"  # Will be overridden by route XML
export REPETITION="1" # minimum 1
export SCENARIO_NAME="training_3_scenarios"
export WEATHER_CONFIG="random_weather_seed_42_balanced_100"

## LHT
export ROUTE_CONFIG="routes_training"      
export ROUTES="/workspace/simlingo/${LEADERBOARD_VERSION}/data/${ROUTE_CONFIG}.xml"
export ROUTES_SUBSET="0" 

## Running all the routes in the ROUTES massive data collection =========================
if [ -f "${WORK_DIR}/script/common.sh" ]; then
#     # shellcheck source=/dev/null
    . "${WORK_DIR}/script/common.sh"
    # build_routes_subset # export ROUTES_SUBSET
fi
## Running all the routes in the ROUTES massive data collection =========================

export SAVE_FLAT=0
source ~/miniconda3/etc/profile.d/conda.sh
conda activate simlingo16

LEADERBOARD_TIMEOUT="${LEADERBOARD_TIMEOUT:-200}"
# LEADERBOARD_TIMEOUT="${LEADERBOARD_TIMEOUT:-0}" # no timeout - allow full route collection

export PORT_CARLA=${PORT_CARLA:-2000}
export TRAFFIC_MANAGER_PORT=${TRAFFIC_MANAGER_PORT:-8000}

# =============================================================================
# CLEANUP FUNCTION
# =============================================================================
cleanup_carla() {
    sep
    info "Cleaning up CARLA and ${LEADERBOARD_VERSION} (0.9.16) (!!!)..."
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

    info "Starting CARLA 0.9.16 HEADLESS on port ${PORT_CARLA}"
    sep

    docker rm -f carla-server 2>/dev/null || true

#################################################################################

#     # Create left-hand traffic configuration scripts for 0.9.16
#     # I did have abandoned the following fodler:
#     # TMP_CONFIG_DIR=${WORK_DIR}/tmp_carla_0916_config
#     # I used - already run - the /workspace/simlingo/tmp_carla_0916_config/get_lht_carla_0916.py script.
#     warn "Did you rn : cd /workspace/simlingo && python tmp_carla_0916_config/get_lht_carla_0916.py script ?"

##################################################################################

    docker run -d \
        --name carla-server \
        --runtime=nvidia \
        --gpus all \
        --net=host \
        --shm-size=8g \
        --env=NVIDIA_VISIBLE_DEVICES=all \
        --env=NVIDIA_DRIVER_CAPABILITIES=all \
        --env=ENABLE_LEFT_HAND_TRAFFIC=1 \
        -v ${WORK_DIR}/carla_logs:/workspace/CarlaUE4/Saved/Logs \
        -v /workspace/carla0916/CarlaUE4/Content:/workspace/CarlaUE4/Content:ro \
        carla-bench2drive:0.9.16 \
        bash -c "cd /workspace && ./CarlaUE4.sh -opengl -RenderOffScreen -nosound -world-port=${PORT_CARLA} -carla-rpc-port=${PORT_CARLA} -log"

    # docker run -d \
    #     --rm \ ---> this would been nice to have 
    #     --name carla-server-$(date +%s) \ ---> this would been nice to have 
    #     --runtime=nvidia \
    #     --gpus all \
    #     --net=host \
    #     --shm-size=1g \ --> hold run 8 is better 
    #     --env=NVIDIA_VISIBLE_DEVICES=all \
    #     --env=NVIDIA_DRIVER_CAPABILITIES=compute,graphics,utility,display,video \
    #     --env=ENABLE_LEFT_HAND_TRAFFIC=1 \
    #     -v ${WORK_DIR}/carla_logs:/workspace/CarlaUE4/Saved/Logs \
    #     -v /workspace/carla0916/CarlaUE4/Content:/workspace/CarlaUE4/Content:ro \
    #     carla-bench2drive:0.9.16 \
    #     bash -c "cd /workspace && ./CarlaUE4.sh -opengl -RenderOffScreen -nosound -world-port=${PORT_CARLA} -carla-rpc-port=${PORT_CARLA} -log -force-opengl"

    info "Waiting 60s for CARLA to start..."
    sleep 60

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
    port = int(os.environ.get('PORT_CARLA', os.environ.get('PORT', '2000')))
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
    port = int(os.environ.get('PORT_CARLA', os.environ.get('PORT', '2000')))
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
        # Override ROUTES_SUBSET if not manually set (treat only empty/unset as 'not set')
        if [ -z "${ROUTES_SUBSET:-}" ]; then
            export ROUTES_SUBSET="$AUTO_ROUTES_SUBSET"
            info "Auto-filtered ROUTES_SUBSET: ${ROUTES_SUBSET}"
        else
            info "Using manual ROUTES_SUBSET: ${ROUTES_SUBSET}"
        fi
    fi
}


# Ensure a target map is loaded in CARLA, retrying and restarting the container if necessary
ensure_map_loaded() {
    local target_map_short="$1"
    local max_retries=${MAP_LOAD_RETRIES:-3}
    local backoff=${MAP_LOAD_BACKOFF:-5}
    local attempt=0

    if [ -z "${target_map_short}" ]; then
        return 0
    fi

    while [ $attempt -lt $max_retries ]; do
        attempt=$((attempt + 1))
        info "[map-load] Attempt ${attempt}/${max_retries} to pre-load ${target_map_short}"

        python - <<PY
import carla,sys,os,time,xml.etree.ElementTree as ET
try:
    port = int(os.environ.get('PORT_CARLA', os.environ.get('PORT', '2000')))
    client = carla.Client('localhost', port)
    client.set_timeout(10.0)
    available_maps = [m for m in client.get_available_maps()]
    target_full = None
    for mp in available_maps:
        if mp.split('/')[-1] == '${target_map_short}':
            target_full = mp
            break

    if not target_full:
        # try case-insensitive match or substring
        for mp in available_maps:
            name = mp.split('/')[-1]
            if '${target_map_short}'.lower() in name.lower():
                target_full = mp
                break

    if not target_full:
        # fallback to local content folder heuristic
        local_maps_root = '/workspace/carla0916/CarlaUE4/Content/Carla/Maps'
        local_candidate = os.path.join(local_maps_root, '${target_map_short}')
        if os.path.exists(local_candidate):
            target_full = f'/Game/Carla/Maps/${target_map_short}'

    if not target_full:
        print(f'ERROR_NO_MAP', end='')
        sys.exit(2)

    # attempt to load
    client.set_timeout(180.0)
    start = time.time()
    world = client.load_world(target_full)
    elapsed = time.time() - start
    print(f'[INFO] OK_LOADED: {target_full} : {elapsed:.1f}\n', end='')
    sys.exit(0)
except Exception as e:
    print(f'ERROR:{e}', end='')
    sys.exit(1)
PY
        rc=$?
        if [ $rc -eq 0 ]; then
            info "[map-load] ✓ Loaded ${target_map_short}"
            return 0
        fi

        # If the python returned code 2 -> map not found; no point in restarting container
        if [ $rc -eq 2 ]; then
            warn "[map-load] Map ${target_map_short} not present in CARLA available maps or local content"
            return 1
        fi

        # Otherwise, try to recover by restarting the CARLA container
        warn "[map-load] Failed to load ${target_map_short} (attempt ${attempt}). Restarting CARLA container and retrying..."
        sep
        docker logs --tail 200 carla-server 2>/dev/null || true
        stop_carla || true
        start_carla || true
        info "[map-load] Waiting ${backoff}s before retry..."
        sleep ${backoff}
    done

    err "[map-load] Exhausted ${max_retries} attempts to load ${target_map_short}"
    return 1
}

# =============================================================================
# RUN LEADERBOARD EVALUATION (uses same leaderboard but with 0.9.16 CARLA)
# =============================================================================
run_leaderboard() {

    cd /workspace/simlingo/${LEADERBOARD_VERSION}

    info "Agent    : ${TEAM_AGENT}"
    info "Routes   : ${ROUTES}"
    info "Port     : ${PORT_CARLA}"
    info "Output   : ${SAVE_PATH}"

    BASE_ARGS=(--routes=${ROUTES} --repetitions=${REPETITION} --agent=${TEAM_AGENT} --agent-config=${TEAM_CONFIG} --port=${PORT_CARLA} --traffic-manager-port=${TRAFFIC_MANAGER_PORT})
    if [ -n "${LEADERBOARD_CHECKPOINT:-}" ]; then
        BASE_ARGS+=(--checkpoint=${LEADERBOARD_CHECKPOINT})
    fi

    if [ -z "${ROUTES_SUBSET:-}" ]; then
        # Build default subset from routes file (all ids)
        ROUTES_SUBSET=$(python - <<'PY'
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
    fi

    # Normalize ROUTES_SUBSET by removing whitespace around commas and ids
    ROUTES_SUBSET=$(echo "${ROUTES_SUBSET}" | tr -d '[:space:]')
    IFS=',' read -ra ROUTE_IDS <<< "${ROUTES_SUBSET}"

    # Set SAVE_SUBDIR based on ROUTES_SUBSET and SAVE_FLAT
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

    total_routes=${#ROUTE_IDS[@]}
    current_route=0
    overall_exit=0

    for route_id in "${ROUTE_IDS[@]}"; do
        current_route=$((current_route + 1))
        sep
        info "Running route ${route_id} (${current_route}/${total_routes})"
        sep

        # Trim route_id whitespace (defensive) and compose args for this route
        route_id=$(echo "${route_id}" | xargs)
        # Derive town for this route and export FORCE_TOWN so agent uses correct Town
        export ROUTE_ID_TMP="${route_id}"
        route_town=$(python - <<'PY'
import xml.etree.ElementTree as ET, os, sys
rid = os.environ.get('ROUTE_ID_TMP','')
routes_file = os.environ.get('ROUTES','')
if routes_file and os.path.exists(routes_file) and rid:
    tree = ET.parse(routes_file)
    root = tree.getroot()
    for r in root.findall('.//route'):
        if r.get('id') == rid:
            town = r.get('town') or r.get('map') or ''
            print(town)
            sys.exit(0)
print('', end='')
PY
    )
    unset ROUTE_ID_TMP
        if [ -n "${route_town}" ]; then
            export FORCE_TOWN="${route_town}"
            info "Setting FORCE_TOWN=${FORCE_TOWN} for route ${route_id}"
        else
            unset FORCE_TOWN
        fi
        export FORCE_ROUTE_ID="${route_id}"
        ARGS=("${BASE_ARGS[@]}" "--routes-subset=${route_id}")

        # Pre-load the correct town in CARLA to avoid timeout during route start
        if [ -n "${route_town}" ]; then
            info "Pre-loading ${route_town} in CARLA..."
            if ! ensure_map_loaded "${route_town}"; then
                err "Failed to pre-load ${route_town}"
                continue
            fi
        fi

        # info "Launching leaderboard for route ${route_id} with FORCE_TOWN=${FORCE_TOWN:-<none>} FORCE_ROUTE_ID=${FORCE_ROUTE_ID:-<none>} SAVE_SUBDIR=${SAVE_SUBDIR:-<none>}"

        # Create per-route logging dir
        mkdir -p "${WORK_DIR}/leaderboard_logs"
        env | sort > "${WORK_DIR}/leaderboard_logs/env_route_${route_id}.txt"

        # Run leaderboard and capture stdout/stderr to per-route log for inspection
        LB_LOG="${WORK_DIR}/leaderboard_logs/route_${route_id}.log"
        if [ "${LEADERBOARD_TIMEOUT:-0}" -eq 0 ]; then
            python -u ${LEADERBOARD_VERSION}/leaderboard_evaluator.py "${ARGS[@]}" 2>&1 | tee "${LB_LOG}" &
            LB_PID=$!
            wait $LB_PID
            exit_code=$?
        else
            timeout -k 10 "${LEADERBOARD_TIMEOUT}" bash -c 'trap "kill 0" SIGTERM; exec "$@"' -- python -u ${LEADERBOARD_VERSION}/leaderboard_evaluator.py "${ARGS[@]}" 2>&1 | tee "${LB_LOG}"
            exit_code=$?
        fi

        info "Leaderboard log for route ${route_id}: ${LB_LOG}"

        sep
        if [ $exit_code -eq 0 ]; then
            info "✓ Route ${route_id} completed successfully!"
            FOUND_OUTPUT=1
        else
            FOUND_OUTPUT=0
            if find "${SAVE_PATH}" -maxdepth 6 -type f -name "results.json.gz" -print -quit | grep -q .; then
                FOUND_OUTPUT=1
            elif find "${SAVE_PATH}" -maxdepth 6 -type f -name "records.json.gz" -print -quit | grep -q .; then
                FOUND_OUTPUT=1
            fi

            if [ $FOUND_OUTPUT -eq 1 ]; then
                warn "Route ${route_id} exited with code ${exit_code} but saved output files — treating as success"
                exit_code=0
            elif [ $exit_code -eq 124 ]; then
                warn "Route ${route_id} timeout reached (${LEADERBOARD_TIMEOUT}s) - checking for partial data..."
                if [ $FOUND_OUTPUT -eq 1 ]; then
                    exit_code=0
                fi
            else
                warn "Route ${route_id} exited with code $exit_code"
            fi
        fi

        if [ $exit_code -ne 0 ]; then
            overall_exit=$exit_code
        fi

        # Run patching immediately after each route if data exists
        if [ $exit_code -eq 0 ] || [ $FOUND_OUTPUT -eq 1 ]; then
            info "Patching multicamera images for route ${route_id}..."
            patch_multicamera_images
            patch_exit=$?
            if [ $patch_exit -ne 0 ]; then
                warn "Image patching failed for route ${route_id}"
            fi
            # ensure we are back in leaderboard dir for next iteration
            cd /workspace/simlingo/${LEADERBOARD_VERSION}
        else
            warn "Skipping patching for route ${route_id} (no data collected)"
        fi

    done

    sep
    if [ $overall_exit -eq 0 ]; then
        info "All ${total_routes} routes completed successfully!"
    else
        warn "Some routes encountered errors (exit code: ${overall_exit})"
    fi
    sep

    return $overall_exit
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
        # Find candidate directories whose name contains the route token
        DATASET_PATH=""
        while IFS= read -r dir; do
            # verify required subfolders
            if [ -d "$dir/rgb" ] && [ -d "$dir/measurements" ]; then
                DATASET_PATH="$dir"
                break
            fi
        done < <(find "${SAVE_PATH}" -type d -name "*route${FORCE_ROUTE_ID}*" 2>/dev/null | sort -r)

        # If none found by explicit 'route{ID}' token, broaden search to any path containing the ID
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
        # If FORCE_ROUTE_ID is set, ensure the .last_run path corresponds to that route
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

    # If still empty, fall back to most recent Town*_Rep* with rgb/measurements
    if [ -z "${DATASET_PATH:-}" ]; then
        DATASET_PATH=$(find ${SAVE_PATH} -maxdepth 6 -type d -name "Town*_Rep*" 2>/dev/null | while read dir; do
            if [ -d "$dir/rgb" ] && [ -d "$dir/measurements" ]; then
                echo "$dir"
            fi
        done | sort -r | head -1)
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

    # sep
    # info "Applying geometric layout (creates patched.jpg)..."
    # python bosch_utils/tools/batch_patch_multicamera.py "$DATASET_PATH" --layout geometric
    local patch1_exit=$?

    sep
    info "Applying three-quarter layout (creates patched2*.jpg)..."
    python bosch_utils/tools/batch_patch_multicamera2.py "$DATASET_PATH" --layout three_quarter
    # python bosch_utils/tools/batch_patch_multicamera2.py "$DATASET_PATH" --layout three_quarter --output-name 1
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
