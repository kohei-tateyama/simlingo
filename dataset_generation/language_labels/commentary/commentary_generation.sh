#!/bin/bash

# Commentary generation script for simlingo_v4_2026_01_01 dataset
# This processes all data in the new directory structure

# Change to workspace root for proper module imports
cd /workspace/simlingo

# Set paths
DATA_DIR="/media/external_ssd/database/simlingo_v4_2026_01_01/auto_long_multicam_jp"
OUTPUT_DIR="/media/external_ssd/database/simlingo_v4_2026_01_01/commentary_auto_long_multicam_jp"

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

echo "========================================"
echo "Commentary Generator for SimLingo V4"
echo "========================================"
echo "Data directory: $DATA_DIR"
echo "Output directory: $OUTPUT_DIR"
echo ""
echo "Processing FIRST 50 samples as a test..."
echo ""

# Run commentary generator with limited sample count
PYTHONPATH=/workspace/simlingo:$PYTHONPATH python dataset_generation/language_labels/commentary/carla_commentary_generator_main.py \
    --data-directory "$DATA_DIR" \
    --output-directory "$OUTPUT_DIR" \
    --output-examples-directory "${OUTPUT_DIR}/examples" \
    --sample-frame-mode "uniform" \
    --sample-uniform-interval 10 \
    --random-subset-count 50 \
    --save-examples \
    --visualize-projection \
    --skip-existing 

echo ""
echo "========================================"
echo "Commentary generation complete!"
echo "Output saved to: $OUTPUT_DIR"
echo "Example visualizations: ${OUTPUT_DIR}/examples"
echo "Statistics: ${OUTPUT_DIR}/stats.json"
echo "========================================"