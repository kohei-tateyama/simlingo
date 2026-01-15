#!/bin/bash
# Enable left-hand traffic for classic CARLA towns via OpenDRIVE XML modification
# Based on: https://github.com/carla-simulator/carla/pull/8951

CARLA_HOME="/workspace"
MAPS_DIR="${CARLA_HOME}/CarlaUE4/Content/Carla/Maps"

# Only modify classic towns (Town01-Town12) - Town13+ may have native LHT
TOWNS_TO_MODIFY="Town01 Town02 Town03 Town04 Town05 Town06 Town07 Town10HD"

echo "[LHT-CONFIG] Checking for OpenDRIVE files to modify..."

for town in $TOWNS_TO_MODIFY; do
    XODR_FILE="${MAPS_DIR}/${town}/OpenDrive/${town}.xodr"
    
    if [ ! -f "$XODR_FILE" ]; then
        echo "[LHT-CONFIG] Skipping ${town} (file not found: $XODR_FILE)"
        continue
    fi
    
    # Check if already modified (avoid duplicate modifications)
    if grep -q 'carla:lane_direction.*left' "$XODR_FILE" 2>/dev/null; then
        echo "[LHT-CONFIG] ${town} already has LHT config, skipping"
        continue
    fi
    
    echo "[LHT-CONFIG] Enabling LHT for ${town}..."
    
    # Backup original
    cp "$XODR_FILE" "${XODR_FILE}.backup_rht" 2>/dev/null || true
    
    # Add left-hand traffic userData to the OpenDRIVE header
    # Insert after <header> tag
    sed -i '/<header/a\        <userData>\n            <vectorLane code="carla:lane_direction" value="left"/>\n        </userData>' "$XODR_FILE"
    
    if [ $? -eq 0 ]; then
        echo "[LHT-CONFIG] ✓ ${town} configured for left-hand traffic"
    else
        echo "[LHT-CONFIG] ✗ Failed to modify ${town}, restoring backup"
        [ -f "${XODR_FILE}.backup_rht" ] && cp "${XODR_FILE}.backup_rht" "$XODR_FILE"
    fi
done

echo "[LHT-CONFIG] Configuration complete"
