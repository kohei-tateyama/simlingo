#!/bin/bash

# Script to flatten image structure while preserving multi-camera data
# Copies rgb/XXXX/F.jpg -> rgb/XXXX.jpg for all routes

DATA_DIR="/media/external_ssd/workspace/simlingo/database/simlingo_v4_bosch_2025_01_10"

echo "Flattening image structure in $DATA_DIR"
echo "This will copy F.jpg files to parent directory as XXXX.jpg"

# Counter for progress
total_routes=0
processed_routes=0

# Find all route directories (they contain rgb folders)
route_dirs=$(find "$DATA_DIR" -type d -name "Town*_Rep*_route*")

# Count total routes
total_routes=$(echo "$route_dirs" | wc -l)
echo "Found $total_routes routes to process"

# Process each route
for route_dir in $route_dirs; do
    # Check if rgb directory exists
    if [ -d "$route_dir/rgb" ]; then
        echo "Processing: $route_dir"
        
        # Find all timestep folders (numeric directories)
        for timestep_dir in "$route_dir/rgb"/[0-9]*; do
            if [ -d "$timestep_dir" ]; then
                timestep=$(basename "$timestep_dir")
                
                # Check if F.jpg exists in this timestep folder
                if [ -f "$timestep_dir/F.jpg" ]; then
                    # Copy F.jpg to parent directory with timestep name
                    cp "$timestep_dir/F.jpg" "$route_dir/rgb/$timestep.jpg"
                else
                    echo "  Warning: F.jpg not found in $timestep_dir"
                fi
            fi
        done
        
        # Also process rgb_augmented if it exists
        if [ -d "$route_dir/rgb_augmented" ]; then
            echo "  Processing rgb_augmented..."
            for timestep_dir in "$route_dir/rgb_augmented"/[0-9]*; do
                if [ -d "$timestep_dir" ]; then
                    timestep=$(basename "$timestep_dir")
                    
                    if [ -f "$timestep_dir/F.jpg" ]; then
                        cp "$timestep_dir/F.jpg" "$route_dir/rgb_augmented/$timestep.jpg"
                    elif [ -f "$timestep_dir/1.jpg" ]; then
                        cp "$timestep_dir/1.jpg" "$route_dir/rgb_augmented/$timestep.jpg"
                    else
                        echo "  Warning: Neither F.jpg nor 1.jpg found in $timestep_dir (augmented)"
                    fi
                fi
            done
        fi
        
        processed_routes=$((processed_routes + 1))
        echo "  Progress: $processed_routes/$total_routes routes"
    fi
done

echo ""
echo "Flattening complete!"
echo "Processed $processed_routes routes"
echo ""
echo "Next steps:"
echo "1. Verify images were copied: ls /media/external_ssd/workspace/simlingo/database/simlingo_v4_bosch_2025_01_10/data/simlingo/training_3_scenarios/routes_training/random_weather_seed_42_balanced_100/Town13_Rep1_route3575_02_10_11_56_29/rgb/"
echo "2. Regenerate buckets: python dataset_generation/data_buckets/carla_get_buckets.py"
echo "3. Resume training: source scripts/train_simlingo_seed4.sh"
