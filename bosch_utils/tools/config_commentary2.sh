# #!/bin/bash
# # config_commentary2.sh
# # Setup script for image_describer2_todo.py in simlingo conda environment
# # 
# # This script:
# # - Activates the simlingo conda environment
# # - Installs required Python packages
# # - Verifies llama.cpp binary and model files
# # - Downloads YOLO model (optional)
# # - Provides example run commands
# #
# # Usage:
# #   bash config_commentary2.sh [--install-all] [--verify-only] [--test-run]

# set -e  # Exit on error

# # Color codes for output
# RED='\033[0;31m'
# GREEN='\033[0;32m'
# YELLOW='\033[1;33m'x
# BLUE='\033[0;34m'
# NC='\033[0m' # No Color

# info() {
#     echo -e "${GREEN}[INFO]${NC} $*"
# }

# warn() {
#     echo -e "${YELLOW}[WARN]${NC} $*"
# }

# error() {
#     echo -e "${RED}[ERROR]${NC} $*"
# }

# success() {
#     echo -e "${GREEN}[✓]${NC} $*"
# }

# # ============================================================================
# # Configuration - Adjust these paths for your system
# # ============================================================================

# CONDA_ENV_NAME="simlingo"
# LLAMA_BIN="/workspace/vla_data_generation/llama.cpp/build/bin/llama-completion"
# MODEL_PATH="/workspace/vla_data_generation/Qwen3VL-32B-Instruct-Q4_K_M.gguf"
# MMPROJ_PATH="/workspace/vla_data_generation/mmproj-Qwen3VL-32B-Instruct-F16.gguf"

# # Example image for testing
# TEST_IMAGE="/workspace/vla_data_generation/inference/example_images/patched_0057.jpg"

# # ============================================================================
# # Parse arguments
# # ============================================================================

# INSTALL_ALL=false
# VERIFY_ONLY=false
# TEST_RUN=false

# while [[ $# -gt 0 ]]; do
#     case $1 in
#         --install-all)
#             INSTALL_ALL=true
#             shift
#             ;;
#         --verify-only)
#             VERIFY_ONLY=true
#             shift
#             ;;
#         --test-run)
#             TEST_RUN=true
#             shift
#             ;;
#         -h|--help)
#             echo "Usage: $0 [--install-all] [--verify-only] [--test-run]"
#             echo ""
#             echo "Options:"
#             echo "  --install-all    Install all dependencies (Pillow, ultralytics)"
#             echo "  --verify-only    Only verify setup, don't install anything"
#             echo "  --test-run       Run a test inference after setup"
#             echo "  -h, --help       Show this help message"
#             exit 0
#             ;;
#         *)
#             error "Unknown option: $1"
#             exit 1
#             ;;
#     esac
# done

# # ============================================================================
# # Step 1: Activate conda environment
# # ============================================================================

# info "Step 1/6: Activating conda environment '${CONDA_ENV_NAME}'..."

# # Source conda
# if [ -f ~/miniconda3/etc/profile.d/conda.sh ]; then
#     source ~/miniconda3/etc/profile.d/conda.sh
# elif [ -f ~/anaconda3/etc/profile.d/conda.sh ]; then
#     source ~/anaconda3/etc/profile.d/conda.sh
# else
#     error "Could not find conda initialization script"
#     error "Please manually activate: conda activate ${CONDA_ENV_NAME}"
#     exit 1
# fi

# # Activate environment
# if conda activate "$CONDA_ENV_NAME" 2>/dev/null; then
#     success "Conda environment '${CONDA_ENV_NAME}' activated"
#     info "Python: $(which python)"
#     info "Python version: $(python --version)"
# else
#     error "Failed to activate conda environment '${CONDA_ENV_NAME}'"
#     error "Available environments:"
#     conda env list
#     exit 1
# fi

# # ============================================================================
# # Step 2: Verify/Install Python packages
# # ============================================================================

# info "Step 2/6: Checking Python dependencies..."

# # Check Pillow (required)
# if python -c "import PIL" 2>/dev/null; then
#     PIL_VERSION=$(python -c "import PIL; print(PIL.__version__)")
#     success "Pillow ${PIL_VERSION} is installed"
# else
#     if [ "$VERIFY_ONLY" = true ]; then
#         error "Pillow is NOT installed (required)"
#     else
#         warn "Pillow not found, installing..."
#         pip install Pillow
#         success "Pillow installed"
#     fi
# fi

# # Check ultralytics (optional, for YOLO)
# if python -c "import ultralytics" 2>/dev/null; then
#     YOLO_VERSION=$(python -c "import ultralytics; print(ultralytics.__version__)")
#     success "ultralytics ${YOLO_VERSION} is installed"
# else
#     if [ "$INSTALL_ALL" = true ]; then
#         warn "ultralytics not found, installing..."
#         pip install ultralytics
#         success "ultralytics installed"
#     else
#         warn "ultralytics not installed (optional for YOLO detection)"
#         info "To install: pip install ultralytics"
#     fi
# fi

# # ============================================================================
# # Step 3: Verify llama.cpp binary
# # ============================================================================

# info "Step 3/6: Verifying llama.cpp setup..."

# if [ -f "$LLAMA_BIN" ]; then
#     success "llama-completion binary found: $LLAMA_BIN"
    
#     # Check if executable
#     if [ -x "$LLAMA_BIN" ]; then
#         success "Binary is executable"
#     else
#         error "Binary is not executable"
#         info "Fix with: chmod +x $LLAMA_BIN"
#         exit 1
#     fi
# else
#     error "llama-completion binary NOT found: $LLAMA_BIN"
#     info "Please build llama.cpp with multimodal support:"
#     info "  cd /workspace/vla_data_generation/llama.cpp"
#     info "  mkdir -p build && cd build"
#     info "  cmake .. -DGGML_CUDA=ON"
#     info "  cmake --build . --config Release"
#     exit 1
# fi

# # ============================================================================
# # Step 4: Verify model files
# # ============================================================================

# info "Step 4/6: Verifying model files..."

# if [ -f "$MODEL_PATH" ]; then
#     MODEL_SIZE=$(du -h "$MODEL_PATH" | cut -f1)
#     success "Model found: $MODEL_PATH (${MODEL_SIZE})"
# else
#     error "Model NOT found: $MODEL_PATH"
#     info "Download from: https://huggingface.co/..."
#     exit 1
# fi

# if [ -f "$MMPROJ_PATH" ]; then
#     MMPROJ_SIZE=$(du -h "$MMPROJ_PATH" | cut -f1)
#     success "MMProj found: $MMPROJ_PATH (${MMPROJ_SIZE})"
# else
#     error "MMProj NOT found: $MMPROJ_PATH"
#     info "Download from: https://huggingface.co/..."
#     exit 1
# fi

# # ============================================================================
# # Step 5: Download YOLO model (optional)
# # ============================================================================

# info "Step 5/6: Checking YOLO model..."

# if python -c "import ultralytics" 2>/dev/null; then
#     # Try to initialize YOLO model (will download if not present)
#     if [ "$INSTALL_ALL" = true ]; then
#         info "Downloading YOLOv8n model (if not cached)..."
#         python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')" 2>/dev/null && \
#             success "YOLO model ready" || \
#             warn "YOLO model download may have failed"
#     else
#         info "Skipping YOLO download (use --install-all to download)"
#     fi
# else
#     warn "ultralytics not installed, skipping YOLO setup"
# fi

# # ============================================================================
# # Step 6: Test GPU availability
# # ============================================================================

# info "Step 6/6: Checking GPU availability..."

# if command -v nvidia-smi &> /dev/null; then
#     GPU_INFO=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || echo "N/A")
#     if [ "$GPU_INFO" != "N/A" ]; then
#         success "GPU detected: $GPU_INFO"
        
#         # Check CUDA support in PyTorch (if installed)
#         if python -c "import torch; assert torch.cuda.is_available()" 2>/dev/null; then
#             CUDA_VERSION=$(python -c "import torch; print(torch.version.cuda)")
#             success "PyTorch CUDA support: ${CUDA_VERSION}"
#         else
#             warn "PyTorch CUDA not available (may affect YOLO performance)"
#         fi
#     else
#         warn "nvidia-smi found but no GPU detected"
#     fi
# else
#     warn "nvidia-smi not found - GPU may not be available"
#     info "Script will use CPU mode (slower)"
# fi

# # ============================================================================
# # Summary and usage examples
# # ============================================================================

# echo ""
# echo "============================================================================"
# success "Setup complete!"
# echo "============================================================================"
# echo ""
# info "Environment: ${CONDA_ENV_NAME}"
# info "Python: $(python --version)"
# info "Pillow: $(python -c "import PIL; print(PIL.__version__)" 2>/dev/null || echo "Not installed")"
# info "ultralytics: $(python -c "import ultralytics; print(ultralytics.__version__)" 2>/dev/null || echo "Not installed")"
# info "llama binary: ${LLAMA_BIN}"
# info "Model: ${MODEL_PATH}"
# echo ""

# # ============================================================================
# # Usage examples
# # ============================================================================

# cat << 'EOF'
# Usage Examples:
# ================

# 1. Process a single image:
#    python news/image_describer2_todo.py /path/to/rgb/0010.jpg

# 2. Process entire directory (recursive):
#    python news/image_describer2_todo.py /path/to/rgb/ --recursive

# 3. Lower GPU usage to avoid OOM (recommended for large models):
#    python news/image_describer2_todo.py image.jpg \
#      --n-gpu-layers 8 \
#      --threads 4 \
#      --ctx-size 2048

# 4. CPU-only mode (no GPU):
#    python news/image_describer2_todo.py image.jpg --n-gpu-layers 0

# 5. Use custom model paths:
#    python news/image_describer2_todo.py image.jpg \
#      --model /path/to/model.gguf \
#      --mmproj /path/to/mmproj.gguf \
#      --llama-bin /path/to/llama-completion

# 6. Process with YOLO detection:
#    python news/image_describer2_todo.py image.jpg --verbose

# 7. Without YOLO (faster):
#    python news/image_describer2_todo.py image.jpg --no-yolo

# 8. Batch process with custom output:
#    python news/image_describer2_todo.py /path/to/rgb/ \
#      --recursive \
#      --output-dir /custom/commentary/path \
#      --n-gpu-layers 16

# Output:
# =======
# - Creates .json.gz files in rgb_commentary/ folder (next to rgb/ folder)
# - JSON format matches simlingo v2 structure
# - Includes driving commentary, detected objects, and scenario classification

# Troubleshooting:
# ================
# - CUDA OOM error → Lower --n-gpu-layers (try 8, 4, or 0)
# - Slow inference → Increase --threads, use GPU layers
# - Missing binary → Rebuild llama.cpp with: cmake .. -DGGML_CUDA=ON
# - Model not found → Check paths in this config script

# For more options:
#    python news/image_describer2_todo.py --help
# EOF

# # ============================================================================
# # Optional: Run test inference
# # ============================================================================

# if [ "$TEST_RUN" = true ]; then
#     echo ""
#     info "Running test inference..."
#     echo ""
    
#     if [ -f "$TEST_IMAGE" ]; then
#         # Run with low GPU usage for testing
#         python news/image_describer2_todo.py "$TEST_IMAGE" \
#             --n-gpu-layers 8 \
#             --threads 4 \
#             --predict 256 \
#             --verbose
        
#         if [ $? -eq 0 ]; then
#             success "Test run completed successfully!"
#         else
#             error "Test run failed"
#             exit 1
#         fi
#     else
#         warn "Test image not found: $TEST_IMAGE"
#         info "Skipping test run"
#     fi
# fi

# echo ""
# success "All checks passed! Ready to generate commentary."
# echo ""






echo "Installing additional dependencies for image_commentary2_todo.py..."
echo "Please be sure to run from (base)"

# Install Pillow (required for image handling)
python -c "import PIL" 2>/dev/null || pip install Pillow

# Install ultralytics (YOLO detection)
read -p "Install ultralytics for YOLO object detection? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    pip install ultralytics
fi

echo "Setup complete!"

