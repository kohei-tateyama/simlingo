#!/bin/bash

set -e

# source shared helpers
source "$(dirname "$0")/common.sh"

info "SimLingo Azure ML Setup"

# Check if Azure CLI is installed
if ! command -v az &> /dev/null; then
    echo "Azure CLI not found. Installing..."

    # Attempt to fix common apt GPG key issues that block 'apt update'
    info "Checking common APT GPG keys (NVIDIA, ROS) — adding if missing"

    # NVIDIA GPG key (NO_PUBKEY DDCAE044F796ECB0)
    if ! sudo apt-key list 2>/dev/null | grep -qi "DDCAE044F796ECB0"; then
        echo "Adding NVIDIA GPG key..."
        if command -v apt-key &>/dev/null; then
            curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo apt-key add - || true
        else
            curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-archive-keyring.gpg || true
        fi
    fi

    # ROS GPG key (NO_PUBKEY F42ED6FBAB17C654)
    if ! sudo apt-key list 2>/dev/null | grep -qi "F42ED6FBAB17C654"; then
        echo "Adding ROS GPG key..."
        if command -v apt-key &>/dev/null; then
            curl -fsSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key | sudo apt-key add - || true
        else
            curl -fsSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key | sudo gpg --dearmor -o /usr/share/keyrings/ros-archive-keyring.gpg || true
        fi
    fi

    # Try apt update to refresh repos; ignore non-fatal failures here and continue
    echo "Updating apt package lists (may request sudo password)..."
    sudo apt-get update || echo "Warning: 'apt-get update' failed — key problems may remain"

    curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
fi

info "Checking Azure login status..."
if ! az account show &> /dev/null; then
    echo "Please log in to Azure:"
    az login
fi

echo "Installing Python dependencies..."
# Use the active Python interpreter to avoid pip shebang problems
PYTHON_BIN=$(command -v python3 || command -v python || true)
if [ -z "$PYTHON_BIN" ]; then
    echo "ERROR: python not found in PATH. Please install Python 3 or activate your conda env." >&2
    exit 1
fi

echo "Using Python at: $PYTHON_BIN"
# Verify the python binary is runnable (some conda envs copied from other users contain broken shebangs)
if ! "$PYTHON_BIN" -c "import sys; print(sys.executable)" >/dev/null 2>&1; then
    echo "Warning: detected Python interpreter at $PYTHON_BIN is not runnable (permission denied or missing)." >&2
    # Try fallback to system python
    if [ -x "/usr/bin/python3" ]; then
        echo "Falling back to /usr/bin/python3"
        PYTHON_BIN=/usr/bin/python3
    else
        echo "No usable python found. Please fix your Python installation or recreate the conda env." >&2
        echo "Diagnostic: which python3=$(command -v python3) ; which python=$(command -v python)" >&2
        exit 1
    fi
fi

echo "Using Python at: $PYTHON_BIN"
"$PYTHON_BIN" -m pip install --upgrade pip setuptools wheel >/dev/null 2>&1 || true
if ! "$PYTHON_BIN" -m pip install -q azure-ai-ml azure-identity; then
    echo "Warning: pip install failed without --user, retrying with --user flag"
    if ! "$PYTHON_BIN" -m pip install --user azure-ai-ml azure-identity; then
    # Suggested defaults (uncomment or export in your shell to skip prompts)
    # export AZ_ENV_NAME="daip5d5219fe9583105d6a83.azurecr.io/data-ai-vla/simlingo-training:v1"
        echo "ERROR: failed to install azure packages via pip. You can try these commands manually:" >&2
        echo "  $PYTHON_BIN -m pip install --user azure-ai-ml azure-identity" >&2
        echo "Or recreate the conda env: conda env remove -n simlingo && conda env create -f environment.yaml" >&2
        exit 1
    fi
fi

# Prompt for Azure ML configuration if not set
if [ -z "$AZ_SUBSCRIPTION_ID" ]; then
    echo "Please provide your Azure ML workspace details:"
    read -p "Subscription ID: " AZ_SUBSCRIPTION_ID
    export AZ_SUBSCRIPTION_ID
fi

if [ -z "$AZ_RESOURCE_GROUP" ]; then
    read -p "Resource Group : " AZ_RESOURCE_GROUP
    export AZ_RESOURCE_GROUP
fi

if [ -z "$AZ_WORKSPACE" ]; then
    read -p "Workspace Name : " AZ_WORKSPACE
    export AZ_WORKSPACE
fi

echo "export DEFAULT_BATCH=\"${DEFAULT_BATCH}\""
echo "Configuration:"
info "Subscription   : $AZ_SUBSCRIPTION_ID"
info "Resource Group : $AZ_RESOURCE_GROUP"
info "Workspace      : $AZ_WORKSPACE"
print_sep 80

echo ""
# Fetch defaults from python config
read AZ_ENV_NAME_DEFAULT AZ_COMPUTE_SKU_DEFAULT AZ_MIN_DEFAULT AZ_MAX_DEFAULT AZ_IDLE_DEFAULT DEFAULT_BATCH_DEFAULT < <(python3 - <<'PY'
from azure_deploy_mp import config
print(config.ENV_NAME)
print(config.DEFAULT_SKU)
print(config.DEFAULT_MIN_INSTANCES)
print(config.DEFAULT_MAX_INSTANCES)
print(config.DEFAULT_IDLE_TIME)
print(config.DEFAULT_BATCH)
PY
)

echo "Run these commands in your shell (you can edit values below if needed):"
print_sep 80
echo "export AZ_SUBSCRIPTION_ID=\"$AZ_SUBSCRIPTION_ID\""
echo "export AZ_RESOURCE_GROUP=\"$AZ_RESOURCE_GROUP\""
echo "export AZ_WORKSPACE=\"$AZ_WORKSPACE\""

# Prompt for compute/env settings with sensible defaults from config.py
# Prompt: use the fetched default in the bracket and apply default if empty
read -p "Azure ML environment name [${AZ_ENV_NAME_DEFAULT}]: " AZ_ENV_NAME
AZ_ENV_NAME=${AZ_ENV_NAME:-$AZ_ENV_NAME_DEFAULT}
echo "export AZ_ENV_NAME=\"$AZ_ENV_NAME\""
# export AZ_ENV_NAME="daip5d5219fe9583105d6a83.azurecr.io/data-ai-vla/simlingo-training:v1"

read -p "Azure Compute SKU [${AZ_COMPUTE_SKU_DEFAULT}]: " AZ_COMPUTE_SKU
AZ_COMPUTE_SKU=${AZ_COMPUTE_SKU:-$AZ_COMPUTE_SKU_DEFAULT}
echo "export AZ_COMPUTE_SKU=\"$AZ_COMPUTE_SKU\""

# Derive NUM_GPUS from the SKU->GPU map in config.py when not already set
if [ -z "${NUM_GPUS:-}" ]; then
    NUM_GPUS=$(python3 - <<PY
from azure_deploy_mp import config
print(config.SKU_GPU_MAP.get("%s", "") )
PY
    )
    # If the map lookup returned empty or invalid, fall back to common defaults
    if ! [[ "$NUM_GPUS" =~ ^[0-9]+$ ]]; then
        case "$AZ_COMPUTE_SKU" in
            *NC16*|*NC16as*|*ND96*) NUM_GPUS=4 ;;
            *NC8*|*NC8as*|*ND48*) NUM_GPUS=2 ;;
            *) NUM_GPUS=1 ;;
        esac
    fi
fi
export NUM_GPUS

read -p "Compute min instances [${AZ_MIN_DEFAULT}]: " AZ_MIN_INSTANCES
AZ_MIN_INSTANCES=${AZ_MIN_INSTANCES:-$AZ_MIN_DEFAULT}
echo "export AZ_MIN_INSTANCES=\"$AZ_MIN_INSTANCES\""

# export AZ_COMPUTE_SKU="Standard_NC8as_T4_v3"
# export NUM_GPUS=2
# export BATCH_SIZE=4
# export AZ_IDLE_SECONDS=1800

read -p "Compute max instances [${AZ_MAX_DEFAULT}]: " AZ_MAX_INSTANCES
AZ_MAX_INSTANCES=${AZ_MAX_INSTANCES:-$AZ_MAX_DEFAULT}
echo "export AZ_MAX_INSTANCES=\"$AZ_MAX_INSTANCES\""

read -p "Compute idle seconds before scale-down [${AZ_IDLE_DEFAULT}]: " AZ_IDLE_SECONDS
AZ_IDLE_SECONDS=${AZ_IDLE_SECONDS:-$AZ_IDLE_DEFAULT}
echo "export AZ_IDLE_SECONDS=\"$AZ_IDLE_SECONDS\""

read -p "Default batch size [${DEFAULT_BATCH_DEFAULT}]: " DEFAULT_BATCH
DEFAULT_BATCH=${DEFAULT_BATCH:-$DEFAULT_BATCH_DEFAULT}
echo "export DEFAULT_BATCH=\"$DEFAULT_BATCH\""

print_sep 80

echo ""
echo "Then submit training:"
echo "  bash azure_deploy_mp/launch_training.sh"
echo ""
echo "Setup complete!"
echo "Suggested exports (you can copy/paste to avoid prompts):"
echo "# Example: use curated PyTorch environment and 2xT4 compute"
echo "export AZ_ENV_NAME=\"${AZ_ENV_NAME:-AzureML-pytorch-2.2-cuda12.1-gpu}\""
echo "export AZ_COMPUTE_SKU=\"${AZ_COMPUTE_SKU:-${AZ_COMPUTE_SKU_DEFAULT}}\""
echo "export NUM_GPUS=${NUM_GPUS:-${NUM_GPUS:-2}}"
echo "export BATCH_SIZE=${BATCH_SIZE:-${DEFAULT_BATCH_DEFAULT}}  # batch per GPU"
echo "export AZ_IDLE_SECONDS=${AZ_IDLE_SECONDS:-${AZ_IDLE_DEFAULT}}  # seconds before scale-down"
