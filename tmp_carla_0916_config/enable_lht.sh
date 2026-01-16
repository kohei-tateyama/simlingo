#!/bin/bash
# Wrapper executed inside the CARLA container to run the Python modifier.
set -e
if command -v python3 >/dev/null 2>&1; then
    python3 /tmp/carla_config/enable_lht.py
elif command -v python >/dev/null 2>&1; then
    python /tmp/carla_config/enable_lht.py
else
    echo "[LHT-CONFIG] No python interpreter found inside container; skipping OpenDrive edits"
    exit 0
fi
