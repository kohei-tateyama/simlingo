#!/bin/bash

set -e

# source shared helpers
source "$(dirname "$0")/common.sh"

info "SimLingo Azure ML Setup"

# Check if Azure CLI is installed
if ! command -v az &> /dev/null; then
    echo "Azure CLI not found. Installing..."
    curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
fi

info "Checking Azure login status..."
if ! az account show &> /dev/null; then
    echo "Please log in to Azure:"
    az login
fi

echo "Installing Python dependencies..."
pip install -q azure-ai-ml azure-identity

# Prompt for Azure ML configuration if not set
if [ -z "$AZ_SUBSCRIPTION_ID" ]; then
    echo "Please provide your Azure ML workspace details:"
    read -p "Subscription ID: " AZ_SUBSCRIPTION_ID
    export AZ_SUBSCRIPTION_ID
fi

if [ -z "$AZ_RESOURCE_GROUP" ]; then
    read -p "Resource Group: " AZ_RESOURCE_GROUP
    export AZ_RESOURCE_GROUP
fi

if [ -z "$AZ_WORKSPACE" ]; then
    read -p "Workspace Name: " AZ_WORKSPACE
    export AZ_WORKSPACE
fi

print_sep 80
echo "A convenience helper was written to: azure_deploy_mp/quick_run.sh"
echo "Run: bash azure_deploy_mp/quick_run.sh --dry-run   # to inspect job spec"
echo "Or:  bash azure_deploy_mp/quick_run.sh            # to run interactive submit"
print_sep 80
echo "Configuration:"
info "Subscription   : $AZ_SUBSCRIPTION_ID"
info "Resource Group : $AZ_RESOURCE_GROUP"
info "Workspace      : $AZ_WORKSPACE"
print_sep 80

echo ""
# Fetch defaults from python config
read AZ_ENV_NAME_DEFAULT AZ_COMPUTE_SKU_DEFAULT AZ_MIN_DEFAULT AZ_MAX_DEFAULT AZ_IDLE_DEFAULT DEFAULT_BATCH_DEFAULT <<EOF
$(python3 - <<'PY'
from azure_deploy_mp import config
print(config.ENV_NAME)
print(config.DEFAULT_SKU)
print(config.DEFAULT_MIN_INSTANCES)
print(config.DEFAULT_MAX_INSTANCES)
print(config.DEFAULT_IDLE_TIME)
print(config.DEFAULT_BATCH)
PY
EOF

echo "Run these commands in your shell (you can edit values below if needed):"
print_sep 80
echo "export AZ_SUBSCRIPTION_ID=\"$AZ_SUBSCRIPTION_ID\""
echo "export AZ_RESOURCE_GROUP=\"$AZ_RESOURCE_GROUP\""
echo "export AZ_WORKSPACE=\"$AZ_WORKSPACE\""

# Prompt for compute/env settings with sensible defaults from config.py
read -p "Azure ML environment name [${AZ_ENV_NAME_DEFAULT}]: " AZ_ENV_NAME
AZ_ENV_NAME=${AZ_ENV_NAME:-$AZ_ENV_NAME_DEFAULT}
echo "export AZ_ENV_NAME=\"$AZ_ENV_NAME\""

read -p "Azure Compute SKU [${AZ_COMPUTE_SKU_DEFAULT}]: " AZ_COMPUTE_SKU
AZ_COMPUTE_SKU=${AZ_COMPUTE_SKU:-$AZ_COMPUTE_SKU_DEFAULT}
echo "export AZ_COMPUTE_SKU=\"$AZ_COMPUTE_SKU\""

read -p "Compute min instances [${AZ_MIN_DEFAULT}]: " AZ_MIN_INSTANCES
AZ_MIN_INSTANCES=${AZ_MIN_INSTANCES:-$AZ_MIN_DEFAULT}
echo "export AZ_MIN_INSTANCES=\"$AZ_MIN_INSTANCES\""

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
