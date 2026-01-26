#!/bin/bash
# remove_broken_lht.sh - Remove incorrectly generated LHT .xodr files, due to the use of the enable_lht.sh

MAPS_DIR="/workspace/carla0916/CarlaUE4/Content/Carla/Maps"

TOWNS=(
    "Town01" "Town01_Opt" "Town02" "Town02_Opt" "Town03" "Town03_Opt"
    "Town04" "Town04_Opt" "Town05" "Town05_Opt" "Town06" "Town06_Opt"
    "Town07" "Town07_Opt" "Town10HD" "Town10HD_Opt" "Town12" "Town13" "Town15"
)

echo "Removing broken LHT .xodr files..."

for town in "${TOWNS[@]}"; do
    # Check Maps/OpenDrive/{town}.xodr
    xodr="${MAPS_DIR}/OpenDrive/${town}.xodr"
    if [ -f "$xodr" ]; then
        echo "Removing: $xodr"
        rm -f "$xodr"
    fi
    
    # Check Maps/{town}/OpenDrive/{town}.xodr
    xodr="${MAPS_DIR}/${town}/OpenDrive/${town}.xodr"
    if [ -f "$xodr" ]; then
        echo "Removing: $xodr"
        rm -f "$xodr"
    fi
done

echo "Done. Now restore from backups or .original_rht files..."

# Restore from backups
for town in "${TOWNS[@]}"; do
    # Try Maps/OpenDrive/
    backup="${MAPS_DIR}/OpenDrive/${town}.xodr.backup_rht"
    original="${MAPS_DIR}/OpenDrive/${town}.original_rht.xodr"
    target="${MAPS_DIR}/OpenDrive/${town}.xodr"
    
    if [ -f "$backup" ]; then
        echo "Restoring from backup: $backup -> $target"
        cp "$backup" "$target"
    elif [ -f "$original" ]; then
        echo "Restoring from original: $original -> $target"
        cp "$original" "$target"
    fi
    
    # Try Maps/{town}/OpenDrive/
    backup="${MAPS_DIR}/${town}/OpenDrive/${town}.xodr.backup_rht"
    original="${MAPS_DIR}/${town}/OpenDrive/${town}.original_rht.xodr"
    target="${MAPS_DIR}/${town}/OpenDrive/${town}.xodr"
    
    if [ -f "$backup" ]; then
        echo "Restoring from backup: $backup -> $target"
        cp "$backup" "$target"
    elif [ -f "$original" ]; then
        echo "Restoring from original: $original -> $target"
        cp "$original" "$target"
    fi
done

echo "Restoration complete!"