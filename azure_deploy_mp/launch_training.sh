#!/bin/bash
# Quick launch script for SimLingo training on Azure ML
set -e

cd /workspace/simlingo
source "$(dirname "$0")/common.sh"

# Check if Azure credentials are set
if [ -z "$AZ_SUBSCRIPTION_ID" ] || [ -z "$AZ_RESOURCE_GROUP" ] || [ -z "$AZ_WORKSPACE" ]; then
    echo "ERROR: Azure credentials not set"
    echo "Run: bash azure_deploy_mp/setup_azure.sh"
    echo "Then export the printed variables before running this script"
    exit 1
fi

info "Using Azure workspace: $AZ_WORKSPACE"

# Set default training parameters (can be overridden)
export BATCH_SIZE=${BATCH_SIZE:-8}
export NUM_GPUS=${NUM_GPUS:-4}
export EXPERIMENT_NAME=${EXPERIMENT_NAME:-simlingo_seed1}
export AZ_COMPUTE=${AZ_COMPUTE:-simlingo-gpu-cluster}
export AZ_COMPUTE_SKU=${AZ_COMPUTE_SKU:-Standard_NC16as_T4_v3}

info "SimLingo Azure ML Training Submission"
info "Workspace : $AZ_WORKSPACE"
info "Compute   : $AZ_COMPUTE ($AZ_COMPUTE_SKU)"
info "Training  : batch_size=$BATCH_SIZE, gpus=$NUM_GPUS"
info "Experiment: $EXPERIMENT_NAME"

# Submit the job
python azure_deploy_mp/submit_to_azure.py

echo ""
info "Training job submitted!"
