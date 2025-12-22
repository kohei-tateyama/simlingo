#!/bin/bash
set -e

cd /workspace/simlingo
source azure_deploy_mp/common.sh

info "SimLingo Azure ML - Complete Setup & Training Launch"

print_sep 80
echo "Step 1: Azure ML Workspace Setup"
print_sep 80
bash azure_deploy_mp/setup_azure.sh

print_sep 80
echo ""
echo "ERROR: Cannot continue automatically!"
echo ""
echo "You must now:"
echo "  1. Export the Azure credentials shown above"
echo "  2. Then run:"
echo "     bash azure_deploy_mp/upload_dataset.sh"
echo "     bash azure_deploy_mp/launch_training.sh"
echo ""
echo "Or manually export the variables and re-run this script:"
echo "  export AZ_SUBSCRIPTION_ID=\"...\""
echo "  export AZ_RESOURCE_GROUP=\"...\""  
echo "  export AZ_WORKSPACE=\"...\""
echo "  bash azure_deploy_mp/one_execution_azure.sh"
echo ""
print_sep 80
exit 1
