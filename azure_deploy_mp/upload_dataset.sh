#!/bin/bash
# Upload Simlingo dataset to Azure (Blob Storage)
set -e

source "$(dirname "$0")/common.sh"


info "Simlingo (new) Dataset Upload to Azure"

info "[Step 0]: Preparing Account"
# Check if Azure credentials are set
if [ -z "$AZ_SUBSCRIPTION_ID" ] || [ -z "$AZ_RESOURCE_GROUP" ] || [ -z "$AZ_WORKSPACE" ]; then
    echo "ERROR: Azure credentials not set"
    echo "Run: bash azure_deploy_mp/setup_azure.sh"
    echo "Then export the printed variables before running this script"
    exit 1
fi

# Configuration
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-simlingostorage$(date +%s)}"
CONTAINER_NAME="${CONTAINER_NAME:-simlingo-data}"
DATASET_DIR="/workspace/simlingo/database"
info "PLEASE ADD YOUR DATASET HERE $DATASET_DIR"
info "PLEASE ADD YOUR DATASET HERE $DATASET_DIR"
info "PLEASE ADD YOUR DATASET HERE $DATASET_DIR"

info "Configuration"
echo "Storage Account : $STORAGE_ACCOUNT"
echo "Container       : $CONTAINER_NAME"
echo "Dataset         : $DATASET_DIR"
echo ""

if [ ! -d "$DATASET_DIR/simlingo_v2_2025_01_10" ]; then
    echo "ERROR: Dataset not found at $DATASET_DIR/simlingo_v2_2025_01_10"
    exit 1
fi

# Check sizes
SIZE_DATA=$(du -sh "$DATASET_DIR/simlingo_v2_2025_01_10" | cut -f1)
SIZE_BUCKETS=$(du -sh "$DATASET_DIR/bucketsv2_simlingo" | cut -f1)
echo "Data size: $SIZE_DATA"
echo "Buckets size: $SIZE_BUCKETS"
echo ""

read -p "This will upload. Continue? [y/N]: " confirm
if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Upload cancelled."
    exit 0
fi

#####

info "[Step 1]: Creating Storage Account"
if az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$AZ_RESOURCE_GROUP" &>/dev/null; then
    echo "Storage account $STORAGE_ACCOUNT already exists"
else
    echo "Creating storage account $STORAGE_ACCOUNT..."
    az storage account create \
      --name "$STORAGE_ACCOUNT" \
      --resource-group "$AZ_RESOURCE_GROUP" \
      --location eastus \
      --sku Standard_LRS
fi

# Get connection string
CONN_STR=$(az storage account show-connection-string \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$AZ_RESOURCE_GROUP" \
  --query connectionString -o tsv)

#####

info "[Step 2]: Creating Container"
if az storage container exists --name "$CONTAINER_NAME" --connection-string "$CONN_STR" --query exists -o tsv | grep -q true; then
    echo "Container $CONTAINER_NAME already exists"
else
    az storage container create \
      --name "$CONTAINER_NAME" \
      --connection-string "$CONN_STR"
fi

#####

info "[Step 3]: Installing AzCopy (if needed)" # Microsoft’s high-performance command-line tool for Azure Blob/File/Table storage
if ! command -v azcopy &> /dev/null; then
    echo "Installing azcopy..."
    wget -q https://aka.ms/downloadazcopy-v10-linux
    tar -xf downloadazcopy-v10-linux
    sudo cp azcopy_linux_amd64_*/azcopy /usr/local/bin/
    rm -rf downloadazcopy-v10-linux azcopy_linux_amd64_*
    echo "azcopy installed"
else
    echo "azcopy already installed"
fi

#####
## I will use a Credential-based SAS token for secure upload
info "[Step 4]: Generating SAS (Shared Access Signature) Token" # This is done for uploading data securely
EXPIRY=$(date -u -d "7 days" '+%Y-%m-%dT%H:%MZ')
SAS_TOKEN=$(az storage container generate-sas \
  --account-name "$STORAGE_ACCOUNT" \
  --name "$CONTAINER_NAME" \
  --permissions rwdl \
  --expiry "$EXPIRY" \
  --connection-string "$CONN_STR" \
  -o tsv)

BLOB_URL="https://${STORAGE_ACCOUNT}.blob.core.windows.net/${CONTAINER_NAME}"

#####

info "[Step 5]: Uploading Dataset (this will take hours)"
echo "Starting upload at $(date)"
# echo "TIP: Run this in tmux/screen to avoid interruption"
echo ""

# Upload main dataset
echo "Uploading simlingo_v2_2025_01_10..."
azcopy copy \
  "$DATASET_DIR/simlingo_v2_2025_01_10" \
  "${BLOB_URL}/simlingo_v2_2025_01_10?${SAS_TOKEN}" \
  --recursive \
  --log-level=INFO

# Upload buckets
echo ""
echo "Uploading bucketsv2_simlingo..."
azcopy copy \
  "$DATASET_DIR/bucketsv2_simlingo" \
  "${BLOB_URL}/bucketsv2_simlingo?${SAS_TOKEN}" \
  --recursive \
  --log-level=INFO

# # Upload ours dataset
# echo "Uploading xml_recording_japan (ours)..."
# azcopy copy \
#   "$DATASET_DIR/xml_recording_japan" \
#   "${BLOB_URL}/xml_recording_japan?${SAS_TOKEN}" \
#   --recursive \
#   --log-level=INFO

#####

info "[Step 6]: Registering Datastore in Azure ML"

# Get storage key super important!
STORAGE_KEY=$(az storage account keys list \
  --account-name "$STORAGE_ACCOUNT" \
  --resource-group "$AZ_RESOURCE_GROUP" \
  --query '[0].value' -o tsv)

# Create datastore via Python SDK
# https://learn.microsoft.com/en-us/azure/machine-learning/how-to-datastore?view=azureml-api-2&tabs=sdk-identity-based-access%2Csdk-adls-identity-access%2Csdk-azfiles-accountkey%2Csdk-adlsgen1-identity-access%2Csdk-onelake-identity-access
python3 << EOF
from azure.ai.ml import MLClient
from azure.ai.ml.entities import AzureBlobDatastore
from azure.ai.ml.entities._credentials import AccountKeyConfiguration
from azure.identity import DefaultAzureCredential
import os

try:
    credential = DefaultAzureCredential()
    ml_client = MLClient(
        credential=credential,
        subscription_id="$AZ_SUBSCRIPTION_ID",
        resource_group_name="$AZ_RESOURCE_GROUP",
        workspace_name="$AZ_WORKSPACE",
    )
    
    datastore = AzureBlobDatastore(
        name="simlingo_datastore",
        account_name="$STORAGE_ACCOUNT",
        container_name="$CONTAINER_NAME",
        credentials=AccountKeyConfiguration(account_key="$STORAGE_KEY"),
        description="SimLingo training dataset"
    )
    
    ml_client.datastores.create_or_update(datastore)
    print("[INFO]: Datastore registered successfully!")
except Exception as e:
    print(f"[ERROR]: Failed to register datastore: {e}")
    print("[INFO]: You can register manually in Azure ML Studio")
EOF

echo ""
info "Upload Complete!"
echo "Dataset uploaded to: ${BLOB_URL}"
echo "Datastore name: simlingo_datastore"
echo ""
info "Verify upload: az storage blob list --account-name $STORAGE_ACCOUNT --container-name $CONTAINER_NAME --connection-string '$CONN_STR' --output table | head"
# echo "Storage cost: ~\$15.57/month for 846GB"
