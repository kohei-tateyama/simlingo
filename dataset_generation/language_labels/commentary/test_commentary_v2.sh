#!/bin/bash

# Commentary generation test script for simlingo_v2_2025_01_10 dataset
# This processes a small subset as a test

# Change to workspace root for proper module imports
cd /workspace/simlingo
conda activate simlingo

# Set paths for v2 dataset
DATA_DIR="/media/external_ssd/database/simlingo_v5_2026_01_05/auto_long_multicam_jp"
OUTPUT_DIR="/media/external_ssd/database/simlingo_v5_2026_01_05/auto_long_multicam_jp/commentary_test"

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

echo "========================================"
echo "Commentary Generator Test for V2 Dataset"
echo "========================================"
echo "Data directory: $DATA_DIR"
echo "Output directory: $OUTPUT_DIR"
echo ""
echo "Processing a small subset of data..."
echo ""

# Run commentary generator with limited sample count
PYTHONPATH=/workspace/simlingo:$PYTHONPATH python dataset_generation/language_labels/commentary/carla_commentary_generator_main.py \
    --data-directory "$DATA_DIR" \
    --output-directory "$OUTPUT_DIR" \
    --output-examples-directory "${OUTPUT_DIR}/examples" \
    --sample-frame-mode "all" \
    --random-subset-count 50 \
    --save-examples \
    --visualize-projection 

echo ""
echo "========================================"
echo "Test complete! Check output at: $OUTPUT_DIR"
echo "Example visualizations at: ${OUTPUT_DIR}/examples"
echo "========================================"
