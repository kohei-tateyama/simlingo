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
echo "Configuration:"
info "Subscription   : $AZ_SUBSCRIPTION_ID"
info "Resource Group : $AZ_RESOURCE_GROUP"
info "Workspace      : $AZ_WORKSPACE"
print_sep 80

echo ""
echo "Run these commands in your shell:"
print_sep 80
echo "export AZ_SUBSCRIPTION_ID=\"$AZ_SUBSCRIPTION_ID\""
echo "export AZ_RESOURCE_GROUP=\"$AZ_RESOURCE_GROUP\""
echo "export AZ_WORKSPACE=\"$AZ_WORKSPACE\""
print_sep 80

echo ""
echo "Then submit training:"
echo "  bash azure_deploy_mp/launch_training.sh"
echo ""
echo "Setup complete!"
