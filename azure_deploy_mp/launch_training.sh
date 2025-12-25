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
# Use actual compute from manual_sven.md
export AZ_COMPUTE=${AZ_COMPUTE:-gpu-cluster-t4}
export AZ_COMPUTE_SKU=${AZ_COMPUTE_SKU:-Standard_NC24ads_A100_v4}

info "SimLingo Azure ML Training Submission"
info "Workspace : $AZ_WORKSPACE"
info "Compute   : $AZ_COMPUTE ($AZ_COMPUTE_SKU)"
info "Training  : batch_size=$BATCH_SIZE, gpus=$NUM_GPUS"
info "Experiment: $EXPERIMENT_NAME"

# Usage hint
if [ "${1}" = "--help" ] || [ "${1}" = "-h" ]; then
    echo "Usage: $0 [--dry-run]"
    echo "  --dry-run   : Print job spec and do not submit"
    exit 0
fi

# Submit the job (forward any args to the python submit script)
python azure_deploy_mp/submit_to_azure.py "$@"

echo ""
info "Training job submitted (or dry-run printed)!"
