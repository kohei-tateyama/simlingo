#!/bin/bash

# Test script for commentary generator
# Processes a small subset of data without overwriting existing commentary

# Change to workspace root for proper module imports
cd /workspace/simlingo
conda activate simlingo
# Set paths
# DATA_DIR="/workspace/simlingo/database/simlingo_v2_2025_01_10"
# OUTPUT_DIR="/workspace/simlingo/database/simlingo_v2_2025_01_10/commentary_test"
DATA_DIR="/media/external_ssd/database/simlingo_v4_2026_01_01/auto_long_multicam_jp"
OUTPUT_DIR="/media/external_ssd/database/simlingo_v4_2026_01_01/commentary_auto_long_multicam_jp"


# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

echo "Testing Commentary Generator"
echo "============================="
echo "Data directory: $DATA_DIR"
echo "Output directory: $OUTPUT_DIR"
echo ""
echo "Processing a small subset of data..."
echo ""

# Run commentary generator with test settings
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
echo "============================="
echo "Test complete! Check output at: $OUTPUT_DIR"
echo "Example visualizations at: ${OUTPUT_DIR}/examples"


# cd /workspace/simlingo/dataset_generation/language_labels/commentary
# ./test_commentary_generator.sh