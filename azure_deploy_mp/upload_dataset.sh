# #!/bin/bash
# # Upload Simlingo dataset to Azure (Blob Storage)
# set -e

# source "$(dirname "$0")/common.sh"


# info "Simlingo (new) Dataset Upload to Azure"

# info "[Step 0]: Preparing Account"
# # Check if Azure credentials are set
# if [ -z "$AZ_SUBSCRIPTION_ID" ] || [ -z "$AZ_RESOURCE_GROUP" ] || [ -z "$AZ_WORKSPACE" ]; then
#     echo "ERROR: Azure credentials not set"
#     echo "Run: bash azure_deploy_mp/setup_azure.sh"
#     echo "Then export the printed variables before running this script"
#     exit 1
# fi

# # Configuration
# STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-daijpepdde0b7efc169e98db}"
# STORAGE_RESOURCE_GROUP="${STORAGE_RESOURCE_GROUP:-rg-deveco-jp-datastore-prd}"
# CONTAINER_NAME="${CONTAINER_NAME:-data-ai-vla}"
# DATASET_DIR="${DATASET_DIR:-/workspace/simlingo/database}"

# info "Configuration"
# echo "Storage Account : $STORAGE_ACCOUNT"
# echo "Storage RG      : $STORAGE_RESOURCE_GROUP"
# echo "Container       : $CONTAINER_NAME"
# echo "Dataset dir     : $DATASET_DIR"
# echo ""


# if [ ! -d "$DATASET_DIR/simlingo_v2_2025_01_10" ]; then
#   echo "ERROR: Dataset not found at $DATASET_DIR/simlingo_v2_2025_01_10"
#   exit 1
# fi

# # Check sizes
# SIZE_DATA=$(du -sh "$DATASET_DIR/simlingo_v2_2025_01_10" | cut -f1)
# SIZE_BUCKETS=$(du -sh "$DATASET_DIR/bucketsv2_simlingo" | cut -f1)
# echo "Data size: $SIZE_DATA"
# echo "Buckets size: $SIZE_BUCKETS"
# echo ""

# read -p "This will upload. Continue? [y/N]: " confirm
# if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
#     echo "Upload cancelled."
#     exit 0
# fi

# #####

# info "[Step 1]: Ensure Storage Account exists"
# if az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$STORAGE_RESOURCE_GROUP" &>/dev/null; then
#     echo "Storage account $STORAGE_ACCOUNT exists"
# else
#     echo "Storage account $STORAGE_ACCOUNT not found in resource group $STORAGE_RESOURCE_GROUP"
#     echo "Creating storage account $STORAGE_ACCOUNT..."
#     az storage account create \
#       --name "$STORAGE_ACCOUNT" \
#       --resource-group "$STORAGE_RESOURCE_GROUP" \
#       --location eastus \
#       --sku Standard_LRS
# fi

# # Try to use Azure AD auth for storage operations (preferred for this project)
# CONN_STR=""

# #####

# info "[Step 2]: Creating Container (using Azure AD auth if possible)"
# if az storage container exists --account-name "$STORAGE_ACCOUNT" --name "$CONTAINER_NAME" --auth-mode login --query exists -o tsv 2>/dev/null | grep -q true; then
#   echo "Container $CONTAINER_NAME already exists"
# else
#   echo "Creating container $CONTAINER_NAME (auth-mode login)"
#   az storage container create \
#     --account-name "$STORAGE_ACCOUNT" \
#     --name "$CONTAINER_NAME" \
#     --auth-mode login || {
#     echo "Falling back to connection-string based container creation"
#     if [ -n "$CONN_STR" ]; then
#       az storage container create --name "$CONTAINER_NAME" --connection-string "$CONN_STR"
#     else
#       echo "ERROR: unable to create container with AD auth and no connection string available" >&2
#       exit 1
#     fi
#   }
# fi

# #####

# info "[Step 3]: Installing AzCopy (if needed)" # Microsoft’s high-performance command-line tool for Azure Blob/File/Table storage
# if ! command -v azcopy &> /dev/null; then
#     echo "Installing azcopy..."
#     wget -q https://aka.ms/downloadazcopy-v10-linux
#     tar -xf downloadazcopy-v10-linux
#     sudo cp azcopy_linux_amd64_*/azcopy /usr/local/bin/
#     rm -rf downloadazcopy-v10-linux azcopy_linux_amd64_*
#     echo "azcopy installed"
# else
#     echo "azcopy already installed"
# fi

# #####
# ## I will use a Credential-based SAS token for secure upload
# info "[Step 4]: Prepare upload method (prefer AD auth; fall back to SAS/azcopy)"
# EXPIRY=$(date -u -d "7 days" '+%Y-%m-%dT%H:%MZ')
# SAS_TOKEN=""
# BLOB_URL="https://${STORAGE_ACCOUNT}.blob.core.windows.net/${CONTAINER_NAME}"

# ## Try to generate SAS using AD credentials (may require permission)
# if SAS_TOKEN=$(az storage container generate-sas \
#     --account-name "$STORAGE_ACCOUNT" \
#     --name "$CONTAINER_NAME" \
#     --permissions rwdl \
#     --expiry "$EXPIRY" \
#     --auth-mode login -o tsv 2>/dev/null); then
#   echo "Generated SAS token via AD auth (for azcopy fallback)"
# else
#   echo "Could not generate SAS token via AD auth. Trying account key to create SAS..."
#   # Try to obtain account key and generate SAS using it (fallback)
#   if STORAGE_KEY=$(az storage account keys list --account-name "$STORAGE_ACCOUNT" --resource-group "$STORAGE_RESOURCE_GROUP" --query '[0].value' -o tsv 2>/dev/null); then
#     echo "Obtained storage account key; generating SAS from account key"
#     if SAS_TOKEN=$(az storage container generate-sas \
#         --account-name "$STORAGE_ACCOUNT" \
#         --name "$CONTAINER_NAME" \
#         --permissions rwdl \
#         --expiry "$EXPIRY" \
#         --account-key "$STORAGE_KEY" -o tsv 2>/dev/null); then
#       echo "Generated SAS token via account key"
#     else
#       echo "Failed to generate SAS via account key; will proceed with az storage upload (AD auth) and --overwrite false fallback"
#       SAS_TOKEN=""
#     fi
#   else
#     echo "Unable to obtain storage account key; will proceed with az storage upload (AD auth) and --overwrite false fallback"
#     SAS_TOKEN=""
#   fi
# fi

# #####

# info "[Step 5]: Uploading Dataset (this will take hours)"
# echo "Starting upload at $(date)"
# echo "TIP: Run this in tmux/screen to avoid interruption"
# echo ""

# # target paths in container follow manual_sven.md: datasets/processed/<dataset>
# # Use processed/ since this is training-ready data (already collected/formatted)
# MAIN_DST_PATH="datasets/processed/simlingo_v2_2025_01_10"
# BUCKETS_DST_PATH="datasets/processed/bucketsv2_simlingo"

# echo "Uploading simlingo_v2_2025_01_10 to ${BLOB_URL}/${MAIN_DST_PATH}"

# ## Prefer resumable azcopy sync when possible (fast, skips existing files)
# if command -v azcopy &>/dev/null; then
#   if [ -n "$SAS_TOKEN" ]; then
#     echo "Using azcopy sync (resumable) with SAS token"
#     AZCOPY_DEST="${BLOB_URL}/${MAIN_DST_PATH}?${SAS_TOKEN}"
#     if azcopy sync "$DATASET_DIR/simlingo_v2_2025_01_10" "$AZCOPY_DEST" --recursive --log-level INFO; then
#       echo "Main dataset synced via azcopy (resumable)"
#     else
#       echo "azcopy sync failed; will attempt az CLI upload-batch as fallback" >&2
#     fi
#   else
#     # No SAS token but azcopy present: try to create a short-lived SAS using account key (if available)
#     if [ -z "$STORAGE_KEY" ]; then
#       STORAGE_KEY=$(az storage account keys list --account-name "$STORAGE_ACCOUNT" --resource-group "$STORAGE_RESOURCE_GROUP" --query '[0].value' -o tsv 2>/dev/null || true)
#     fi
#     if [ -n "$STORAGE_KEY" ]; then
#       echo "Creating SAS token from account key for azcopy (short expiry)"
#       if SAS_TOKEN=$(az storage container generate-sas --account-name "$STORAGE_ACCOUNT" --name "$CONTAINER_NAME" --permissions rwdl --expiry "$EXPIRY" --account-key "$STORAGE_KEY" -o tsv 2>/dev/null); then
#         AZCOPY_DEST="${BLOB_URL}/${MAIN_DST_PATH}?${SAS_TOKEN}"
#         echo "Using azcopy sync (resumable) with account-key-derived SAS"
#         if azcopy sync "$DATASET_DIR/simlingo_v2_2025_01_10" "$AZCOPY_DEST" --recursive --log-level INFO; then
#           echo "Main dataset synced via azcopy (resumable)"
#         else
#           echo "azcopy sync with account-key SAS failed; will attempt az CLI upload-batch as fallback" >&2
#         fi
#       else
#         echo "Failed to create SAS via account key; will proceed with az CLI upload-batch (AD auth)" >&2
#       fi
#     else
#       echo "No SAS and no account key available; will proceed with az CLI upload-batch (AD auth)" >&2
#     fi
#   fi
# fi

# # If azcopy sync wasn't used or failed, try az CLI upload-batch but do NOT overwrite existing blobs
# if az storage blob upload-batch \
#    --account-name "$STORAGE_ACCOUNT" \
#    --destination "$CONTAINER_NAME" \
#    --source "$DATASET_DIR/simlingo_v2_2025_01_10" \
#    --destination-path "$MAIN_DST_PATH" \
#    --auth-mode login \
#    --overwrite false; then
#   echo "Main dataset uploaded/updated via az storage (AD auth) - existing blobs were not overwritten"
# else
#   # If upload-batch failed and azcopy+SAS exists, try azcopy copy as a last resort
#   if [ -n "$SAS_TOKEN" ] && command -v azcopy &>/dev/null; then
#     echo "Falling back to azcopy copy using SAS token"
#     azcopy copy "$DATASET_DIR/simlingo_v2_2025_01_10" "${BLOB_URL}/${MAIN_DST_PATH}?${SAS_TOKEN}" --recursive --log-level=INFO
#   else
#     echo "ERROR: Failed to upload main dataset via az CLI and no azcopy+SAS available" >&2
#     exit 1
#   fi
# fi

# echo "Uploading bucketsv2_simlingo to ${BLOB_URL}/${BUCKETS_DST_PATH}"

# if command -v azcopy &>/dev/null; then
#   if [ -n "$SAS_TOKEN" ]; then
#     echo "Using azcopy sync for buckets (resumable)"
#     AZCOPY_DEST_B="${BLOB_URL}/${BUCKETS_DST_PATH}?${SAS_TOKEN}"
#     if azcopy sync "$DATASET_DIR/bucketsv2_simlingo" "$AZCOPY_DEST_B" --recursive --log-level INFO; then
#       echo "Buckets synced via azcopy (resumable)"
#     else
#       echo "azcopy sync for buckets failed; will attempt az CLI upload-batch as fallback" >&2
#     fi
#   else
#     if [ -z "$STORAGE_KEY" ]; then
#       STORAGE_KEY=$(az storage account keys list --account-name "$STORAGE_ACCOUNT" --resource-group "$STORAGE_RESOURCE_GROUP" --query '[0].value' -o tsv 2>/dev/null || true)
#     fi
#     if [ -n "$STORAGE_KEY" ]; then
#       if SAS_TOKEN=$(az storage container generate-sas --account-name "$STORAGE_ACCOUNT" --name "$CONTAINER_NAME" --permissions rwdl --expiry "$EXPIRY" --account-key "$STORAGE_KEY" -o tsv 2>/dev/null); then
#         AZCOPY_DEST_B="${BLOB_URL}/${BUCKETS_DST_PATH}?${SAS_TOKEN}"
#         echo "Using azcopy sync for buckets with account-key-derived SAS"
#         if azcopy sync "$DATASET_DIR/bucketsv2_simlingo" "$AZCOPY_DEST_B" --recursive --log-level INFO; then
#           echo "Buckets synced via azcopy (resumable)"
#         else
#           echo "azcopy sync for buckets failed; will attempt az CLI upload-batch as fallback" >&2
#         fi
#       else
#         echo "Failed to create SAS for buckets; will proceed with az CLI upload-batch (AD auth)" >&2
#       fi
#     else
#       echo "No SAS and no account key available; will proceed with az CLI upload-batch (AD auth) for buckets" >&2
#     fi
#   fi
# fi

# if az storage blob upload-batch \
#    --account-name "$STORAGE_ACCOUNT" \
#    --destination "$CONTAINER_NAME" \
#    --source "$DATASET_DIR/bucketsv2_simlingo" \
#    --destination-path "$BUCKETS_DST_PATH" \
#    --auth-mode login \
#    --overwrite false; then
#   echo "Buckets uploaded/updated via az storage (AD auth) - existing blobs were not overwritten"
# else
#   if [ -n "$SAS_TOKEN" ] && command -v azcopy &>/dev/null; then
#     echo "Falling back to azcopy copy using SAS token for buckets"
#     azcopy copy "$DATASET_DIR/bucketsv2_simlingo" "${BLOB_URL}/${BUCKETS_DST_PATH}?${SAS_TOKEN}" --recursive --log-level=INFO
#   else
#     echo "ERROR: Failed to upload buckets via az CLI and no azcopy+SAS available" >&2
#     exit 1
#   fi
# fi

# # # Upload ours dataset
# # echo "Uploading xml_recording_japan (ours)..."
# # azcopy copy \
# #   "$DATASET_DIR/xml_recording_japan" \
# #   "${BLOB_URL}/xml_recording_japan?${SAS_TOKEN}" \
# #   --recursive \
# #   --log-level=INFO

# #####

# info "[Step 6]: Registering Datastore in Azure ML"

# # Get storage key super important!
# STORAGE_KEY=$(az storage account keys list \
#   --account-name "$STORAGE_ACCOUNT" \
#   --resource-group "$STORAGE_RESOURCE_GROUP" \
#   --query '[0].value' -o tsv)

# # Create datastore via Python SDK
# # https://learn.microsoft.com/en-us/azure/machine-learning/how-to-datastore?view=azureml-api-2&tabs=sdk-identity-based-access%2Csdk-adls-identity-access%2Csdk-azfiles-accountkey%2Csdk-adlsgen1-identity-access%2Csdk-onelake-identity-access
# python3 << EOF
# from azure.ai.ml import MLClient
# from azure.ai.ml.entities import AzureBlobDatastore
# from azure.ai.ml.entities._credentials import AccountKeyConfiguration
# from azure.identity import DefaultAzureCredential
# import os

# try:
#     credential = DefaultAzureCredential()
#     ml_client = MLClient(
#         credential=credential,
#         subscription_id="$AZ_SUBSCRIPTION_ID",
#         resource_group_name="$AZ_RESOURCE_GROUP",
#         workspace_name="$AZ_WORKSPACE",
#     )
    
#     datastore = AzureBlobDatastore(
#         name="simlingo_datastore",
#         account_name="$STORAGE_ACCOUNT",
#         container_name="$CONTAINER_NAME",
#         credentials=AccountKeyConfiguration(account_key="$STORAGE_KEY"),
#         description="SimLingo training dataset"
#     )
    
#     ml_client.datastores.create_or_update(datastore)
#     print("[INFO]: Datastore registered successfully!")
# except Exception as e:
#     print(f"[ERROR]: Failed to register datastore: {e}")
#     print("[INFO]: You can register manually in Azure ML Studio")
# EOF

# echo ""
# info "Upload Complete!"
# echo "Dataset uploaded to: ${BLOB_URL}"
# echo "Datastore name: simlingo_datastore"
# echo ""
# info "Verify upload: az storage blob list --account-name $STORAGE_ACCOUNT --container-name $CONTAINER_NAME --connection-string '$CONN_STR' --output table | head"
# # echo "Storage cost: ~\$15.57/month for 846GB"


###################################### zipping the dataset uploading and unzipping them.
#!/bin/bash
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
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-daijpepdde0b7efc169e98db}"
STORAGE_RESOURCE_GROUP="${STORAGE_RESOURCE_GROUP:-rg-deveco-jp-datastore-prd}"
CONTAINER_NAME="${CONTAINER_NAME:-data-ai-vla}"
DATASET_DIR="${DATASET_DIR:-/workspace/simlingo/database}"

info "Configuration"
echo "Storage Account : $STORAGE_ACCOUNT"
echo "Storage RG      : $STORAGE_RESOURCE_GROUP"
echo "Container       : $CONTAINER_NAME"
echo "Dataset dir     : $DATASET_DIR"
echo ""

AZCOPY_PARALLEL_LEVEL="${AZCOPY_PARALLEL_LEVEL:-32}"
AZCOPY_CAP_MBPS="${AZCOPY_CAP_MBPS:-0}"
AZCOPY_EXTRA_FLAGS="${AZCOPY_EXTRA_FLAGS:-}"


TAR_AND_UPLOAD="${TAR_AND_UPLOAD:-true}"
EXTRACT_TARBALL="${EXTRACT_TARBALL:-true}"
TMP_WORKDIR="${TMP_WORKDIR:-/tmp}"
REMOVE_TARBALL_AFTER_UPLOAD="${REMOVE_TARBALL_AFTER_UPLOAD:-true}"


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

info "[Step 1]: Ensure Storage Account exists"
if az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$STORAGE_RESOURCE_GROUP" &>/dev/null; then
    echo "Storage account $STORAGE_ACCOUNT exists"
else
    echo "Storage account $STORAGE_ACCOUNT not found in resource group $STORAGE_RESOURCE_GROUP"
    echo "Creating storage account $STORAGE_ACCOUNT..."
    az storage account create \
      --name "$STORAGE_ACCOUNT" \
      --resource-group "$STORAGE_RESOURCE_GROUP" \
      --location eastus \
      --sku Standard_LRS
fi

# Try to use Azure AD auth for storage operations (preferred for this project)
CONN_STR=""

#####

info "[Step 2]: Creating Container (using Azure AD auth if possible)"
if az storage container exists --account-name "$STORAGE_ACCOUNT" --name "$CONTAINER_NAME" --auth-mode login --query exists -o tsv 2>/dev/null | grep -q true; then
  echo "Container $CONTAINER_NAME already exists"
else
  echo "Creating container $CONTAINER_NAME (auth-mode login)"
  az storage container create \
    --account-name "$STORAGE_ACCOUNT" \
    --name "$CONTAINER_NAME" \
    --auth-mode login || {
    echo "Falling back to connection-string based container creation"
    if [ -n "$CONN_STR" ]; then
      az storage container create --name "$CONTAINER_NAME" --connection-string "$CONN_STR"
    else
      echo "ERROR: unable to create container with AD auth and no connection string available" >&2
      exit 1
    fi
  }
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
info "[Step 4]: Prepare upload method (prefer AD auth; fall back to SAS/azcopy)"
EXPIRY=$(date -u -d "7 days" '+%Y-%m-%dT%H:%MZ')
SAS_TOKEN=""
BLOB_URL="https://${STORAGE_ACCOUNT}.blob.core.windows.net/${CONTAINER_NAME}"

## Try to generate SAS using AD credentials (may require permission)
if SAS_TOKEN=$(az storage container generate-sas \
    --account-name "$STORAGE_ACCOUNT" \
    --name "$CONTAINER_NAME" \
    --permissions rwdl \
    --expiry "$EXPIRY" \
    --auth-mode login -o tsv 2>/dev/null); then
  echo "Generated SAS token via AD auth (for azcopy fallback)"
else
  echo "Could not generate SAS token via AD auth. Trying account key to create SAS..."
  # Try to obtain account key and generate SAS using it (fallback)
  if STORAGE_KEY=$(az storage account keys list --account-name "$STORAGE_ACCOUNT" --resource-group "$STORAGE_RESOURCE_GROUP" --query '[0].value' -o tsv 2>/dev/null); then
    echo "Obtained storage account key; generating SAS from account key"
    if SAS_TOKEN=$(az storage container generate-sas \
        --account-name "$STORAGE_ACCOUNT" \
        --name "$CONTAINER_NAME" \
        --permissions rwdl \
        --expiry "$EXPIRY" \
        --account-key "$STORAGE_KEY" -o tsv 2>/dev/null); then
      echo "Generated SAS token via account key"
    else
      echo "Failed to generate SAS via account key; will proceed with az storage upload (AD auth) and --overwrite false fallback"
      SAS_TOKEN=""
    fi
  else
    echo "Unable to obtain storage account key; will proceed with az storage upload (AD auth) and --overwrite false fallback"
    SAS_TOKEN=""
  fi
fi

#####

info "[Step 5]: Uploading Dataset (this will take hours)"
echo "Starting upload at $(date)"
echo "TIP: Run this in tmux/screen to avoid interruption"
echo ""

# target paths in container follow manual_sven.md: datasets/processed/<dataset>
# Use processed/ since this is training-ready data (already collected/formatted)
MAIN_DST_PATH="datasets/processed/simlingo_v2_2025_01_10"
BUCKETS_DST_PATH="datasets/processed/bucketsv2_simlingo"

echo "Uploading simlingo_v2_2025_01_10 to ${BLOB_URL}/${MAIN_DST_PATH}"

# If TAR_AND_UPLOAD is enabled, create tarball and upload single blob for faster transfer
if [ "$TAR_AND_UPLOAD" = "true" ]; then
  MAIN_TAR="$TMP_WORKDIR/simlingo_v2_2025_01_10.tar.gz"
  echo "Creating tarball: $MAIN_TAR (this may take time)"
  tar -C "$DATASET_DIR" -czf "$MAIN_TAR" "simlingo_v2_2025_01_10"

  # Prefer az storage blob upload (uses AD auth) if SAS not available
  if [ -n "$SAS_TOKEN" ]; then
    echo "Uploading tarball via azcopy with SAS token"
    azcopy copy "$MAIN_TAR" "${BLOB_URL}/${MAIN_DST_PATH}/simlingo_v2_2025_01_10.tar.gz?${SAS_TOKEN}" \
      --log-level=INFO --parallel-level "${AZCOPY_PARALLEL_LEVEL}" --cap-mbps "${AZCOPY_CAP_MBPS}" ${AZCOPY_EXTRA_FLAGS}
  else
    # Try az storage blob upload (AD auth)
    echo "Uploading tarball via az storage blob upload (AD auth)"
    if az storage blob upload \
         --account-name "$STORAGE_ACCOUNT" \
         --container-name "$CONTAINER_NAME" \
         --file "$MAIN_TAR" \
         --name "$MAIN_DST_PATH/simlingo_v2_2025_01_10.tar.gz" \
         --auth-mode login; then
      echo "Tarball uploaded via az storage blob upload"
    else
      echo "az storage blob upload failed; attempting azcopy fallback (if available)" >&2
      if command -v azcopy &>/dev/null && [ -n "$STORAGE_KEY" ]; then
        azcopy copy "$MAIN_TAR" "${BLOB_URL}/${MAIN_DST_PATH}/simlingo_v2_2025_01_10.tar.gz?${SAS_TOKEN}" \
          --log-level=INFO --parallel-level "${AZCOPY_PARALLEL_LEVEL}" --cap-mbps "${AZCOPY_CAP_MBPS}" ${AZCOPY_EXTRA_FLAGS}
      else
        echo "ERROR: Could not upload tarball (no azcopy/SAS fallback)" >&2
        exit 1
      fi
    fi
  fi

  # Optionally extract tarball locally and upload individual files afterwards
  if [ "$EXTRACT_TARBALL" = "true" ]; then
    echo "Extracting tarball locally to upload individual files (may be slower but preserves object layout)"
    EXTRACT_DIR="$TMP_WORKDIR/simlingo_v2_2025_01_10_extracted"
    rm -rf "$EXTRACT_DIR"
    mkdir -p "$EXTRACT_DIR"
    tar -C "$EXTRACT_DIR" -xzf "$MAIN_TAR"

    # Upload extracted files using azcopy if available (fast for large files)
    if command -v azcopy &>/dev/null && [ -n "$SAS_TOKEN" ]; then
      echo "Uploading extracted files via azcopy sync"
      azcopy sync "$EXTRACT_DIR/simlingo_v2_2025_01_10" "${BLOB_URL}/${MAIN_DST_PATH}?${SAS_TOKEN}" --recursive --log-level INFO \
        --parallel-level "${AZCOPY_PARALLEL_LEVEL}" --cap-mbps "${AZCOPY_CAP_MBPS}" ${AZCOPY_EXTRA_FLAGS}
    else
      echo "azcopy not available or no SAS; using az storage upload-batch (may be slower)"
      az storage blob upload-batch \
         --account-name "$STORAGE_ACCOUNT" \
         --destination "$CONTAINER_NAME" \
         --source "$EXTRACT_DIR/simlingo_v2_2025_01_10" \
         --destination-path "$MAIN_DST_PATH" \
         --auth-mode login --overwrite false
    fi

    # Clean up extracted dir
    rm -rf "$EXTRACT_DIR"
  fi

  # Optionally remove tarball
  if [ "$REMOVE_TARBALL_AFTER_UPLOAD" = "true" ]; then
    rm -f "$MAIN_TAR"
  fi

else
  echo "TAR_AND_UPLOAD disabled — falling back to directory upload logic"
  # (leave existing upload logic in place below)
fi

echo "Uploading bucketsv2_simlingo to ${BLOB_URL}/${BUCKETS_DST_PATH}"

if [ "$TAR_AND_UPLOAD" = "true" ]; then
  BUCKETS_TAR="$TMP_WORKDIR/bucketsv2_simlingo.tar.gz"
  echo "Creating tarball: $BUCKETS_TAR"
  tar -C "$DATASET_DIR" -czf "$BUCKETS_TAR" "bucketsv2_simlingo"

  if [ -n "$SAS_TOKEN" ]; then
    echo "Uploading buckets tarball via azcopy with SAS token"
    azcopy copy "$BUCKETS_TAR" "${BLOB_URL}/${BUCKETS_DST_PATH}/bucketsv2_simlingo.tar.gz?${SAS_TOKEN}" \
      --log-level=INFO --parallel-level "${AZCOPY_PARALLEL_LEVEL}" --cap-mbps "${AZCOPY_CAP_MBPS}" ${AZCOPY_EXTRA_FLAGS}
  else
    echo "Uploading buckets tarball via az storage blob upload (AD auth)"
    if az storage blob upload \
         --account-name "$STORAGE_ACCOUNT" \
         --container-name "$CONTAINER_NAME" \
         --file "$BUCKETS_TAR" \
         --name "$BUCKETS_DST_PATH/bucketsv2_simlingo.tar.gz" \
         --auth-mode login; then
      echo "Buckets tarball uploaded"
    else
      echo "az storage upload failed for buckets; attempting azcopy fallback" >&2
      if command -v azcopy &>/dev/null && [ -n "$STORAGE_KEY" ]; then
        azcopy copy "$BUCKETS_TAR" "${BLOB_URL}/${BUCKETS_DST_PATH}/bucketsv2_simlingo.tar.gz?${SAS_TOKEN}" \
          --log-level=INFO --parallel-level "${AZCOPY_PARALLEL_LEVEL}" --cap-mbps "${AZCOPY_CAP_MBPS}" ${AZCOPY_EXTRA_FLAGS}
      else
        echo "ERROR: Could not upload buckets tarball (no azcopy/SAS fallback)" >&2
        exit 1
      fi
    fi
  fi

  if [ "$EXTRACT_TARBALL" = "true" ]; then
    echo "Extracting buckets tarball locally and uploading extracted files"
    EXTRACT_DIR_B="$TMP_WORKDIR/bucketsv2_simlingo_extracted"
    rm -rf "$EXTRACT_DIR_B"
    mkdir -p "$EXTRACT_DIR_B"
    tar -C "$EXTRACT_DIR_B" -xzf "$BUCKETS_TAR"

    if command -v azcopy &>/dev/null && [ -n "$SAS_TOKEN" ]; then
      azcopy sync "$EXTRACT_DIR_B/bucketsv2_simlingo" "${BLOB_URL}/${BUCKETS_DST_PATH}?${SAS_TOKEN}" --recursive --log-level INFO \
        --parallel-level "${AZCOPY_PARALLEL_LEVEL}" --cap-mbps "${AZCOPY_CAP_MBPS}" ${AZCOPY_EXTRA_FLAGS}
    else
      az storage blob upload-batch \
         --account-name "$STORAGE_ACCOUNT" \
         --destination "$CONTAINER_NAME" \
         --source "$EXTRACT_DIR_B/bucketsv2_simlingo" \
         --destination-path "$BUCKETS_DST_PATH" \
         --auth-mode login --overwrite false
    fi

    rm -rf "$EXTRACT_DIR_B"
  fi

  if [ "$REMOVE_TARBALL_AFTER_UPLOAD" = "true" ]; then
    rm -f "$BUCKETS_TAR"
  fi
else
  echo "TAR_AND_UPLOAD disabled for buckets — falling back to directory upload logic"
fi

# # Upload ours dataset
# echo "Uploading xml_recording_japan (ours)..."
# azcopy copy \
#   "$DATASET_DIR/xml_recording_japan" \
#   "${BLOB_URL}/xml_recording_japan?${SAS_TOKEN}" \
#   --recursive \
#   --log-level=INFO

#####

info "[Step 6]: Registering Datastore in Azure ML"

STORAGE_KEY=$(az storage account keys list \
  --account-name "$STORAGE_ACCOUNT" \
  --resource-group "$STORAGE_RESOURCE_GROUP" \
  --query '[0].value' -o tsv)

# Create datastore via Python SDK
# https://learn.microsoft.com/en-us/azure/machine-learning/how-to-datastore?view=azureml-api-2&tabs=sdk-identity-based-access%2Csdk-adls-identity-access%2Csdk-azfiles-accountkey%2Csdk-adlsgen1-identity-access%2Csdk-onelake-identity-access


info "Verify upload: az storage blob list --account-name $STORAGE_ACCOUNT --container-name $CONTAINER_NAME --connection-string '$CONN_STR' --output table | head"

# 1676260/19119761 friday 18:40git log -n 5