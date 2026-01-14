#!/bin/bash
set -e

source "$(dirname "$0")/common.sh"

info "THIS SCRIPT WORKS"

info "[Step 0]: Preparing Account"
# Check if Azure credentials are set
if [ -z "$AZ_SUBSCRIPTION_ID" ] || [ -z "$AZ_RESOURCE_GROUP" ] || [ -z "$AZ_WORKSPACE" ]; then
    echo "ERROR: Azure credentials not set"
    echo "Run: bash azure_deploy_mp/setup_azure.sh"
    exit 1
fi

STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-daijpepdde0b7efc169e98db}"
STORAGE_RESOURCE_GROUP="${STORAGE_RESOURCE_GROUP:-rg-deveco-jp-datastore-prd}"
CONTAINER_NAME="${CONTAINER_NAME:-data-ai-vla}"
DATASET_DIR="${DATASET_DIR:-/workspace/simlingo/database}"
AZCOPY_PARALLEL_LEVEL="${AZCOPY_PARALLEL_LEVEL:-32}"
AZCOPY_CAP_MBPS="${AZCOPY_CAP_MBPS:-0}"
AZCOPY_EXTRA_FLAGS="${AZCOPY_EXTRA_FLAGS:-}"
TAR_AND_UPLOAD="${TAR_AND_UPLOAD:-true}"
EXTRACT_TARBALL="${EXTRACT_TARBALL:-true}"
TMP_WORKDIR="${TMP_WORKDIR:-/tmp}"
REMOVE_TARBALL_AFTER_UPLOAD="${REMOVE_TARBALL_AFTER_UPLOAD:-false}"
DELETE_REMOTE_AFTER_UPLOAD="${DELETE_REMOTE_AFTER_UPLOAD:-false}"
OVERWRITE="${OVERWRITE:-false}"

info "Configuration"
echo "Storage Account : $STORAGE_ACCOUNT"
echo "Storage RG      : $STORAGE_RESOURCE_GROUP"
echo "Container       : $CONTAINER_NAME"
echo "Dataset dir     : $DATASET_DIR"
echo "Loading via zip : $TAR_AND_UPLOAD"
echo "Extract         : $EXTRACT_TARBALL"
echo "Removing local  : $REMOVE_TARBALL_AFTER_UPLOAD"
echo "Delete azure    : $DELETE_REMOTE_AFTER_UPLOAD"
echo ""

# echo $AZ_SUBSCRIPTION_ID, $AZ_RESOURCE_GROUP, $AZ_WORKSPACE, $STORAGE_ACCOUNT, $STORAGE_RESOURCE_GROUP, $DELETE_REMOTE_AFTER_UPLOAD, $DELETE_REMOTE_AFTER_UPLOAD

read -p "Continue? [Y/n]: " confirm
if [ "$confirm" = "n" ] || [ "$confirm" = "N" ]; then
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

info "[Step 4]: Prepare upload (prefer AD auth; fall back to SAS/azcopy)"
EXPIRY=$(date -u -d "7 days" '+%Y-%m-%dT%H:%MZ')
SAS_TOKEN=""
BLOB_URL="https://${STORAGE_ACCOUNT}.blob.core.windows.net/${CONTAINER_NAME}"

# Check whether the storage account allows shared-key access (account-key / key-based SAS)
ALLOW_SHARED_KEY=$(az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$STORAGE_RESOURCE_GROUP" --query "allowSharedKeyAccess" -o tsv 2>/dev/null || echo "")
echo "Storage account allowSharedKeyAccess=$ALLOW_SHARED_KEY"

## Try to generate SAS using AD credentials (may require permission)
if SAS_TOKEN=$(az storage container generate-sas \
    --account-name "$STORAGE_ACCOUNT" \
    --name "$CONTAINER_NAME" \
    --permissions rwdl \
    --expiry "$EXPIRY" \
    --auth-mode login -o tsv 2>/dev/null); then
  echo "Generated SAS token via AD auth (for azcopy fallback)"
else
  echo "Could not generate SAS token via AD auth."
  if [ "$ALLOW_SHARED_KEY" = "false" ]; then
    echo "Storage account forbids key-based auth; skipping account-key SAS generation and will prefer AD-login uploads"
    SAS_TOKEN=""
  else
    echo "Trying account key to create SAS..."
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
fi

#####

if [ "${TAR_AND_UPLOAD:-true}" = "true" ]; then
  info "[Step 5]: Uploading Dataset (this will take hours)"
  echo "Starting upload at $(date)"
  echo ""
fi

# Example: NAME="bucketsv2_simlingo" or NAME="simlingo_v2_2025_01_10"
NAME=${NAME:-simlingo_v2_2025_01_10}

# NAME_TAR=${NAME_TAR:-/media/external_ssd/${NAME}.tar.gz}
# NAME_DST_PATH=${NAME_DST_PATH:-${NAME}.tar.gz}
NAME_TAR=${NAME_TAR:-/media/external_ssd/${NAME}.tar}
NAME_DST_PATH=${NAME_DST_PATH:-${NAME}.tar}

# if [ "$NAME" = "simlingo_v2_2025_01_10" ]; then
#   NAME_TAR=${NAME_TAR:-/media/external_ssd/${NAME}.tar}
#   NAME_DST_PATH=${NAME_DST_PATH:-${NAME}.tar}
# else
#   NAME_TAR=${NAME_TAR:-/media/external_ssd/${NAME}.tar.gz}
#   NAME_DST_PATH=${NAME_DST_PATH:-${NAME}.tar.gz}
# fi

if [ "${TAR_AND_UPLOAD:-true}" = "true" ]; then
  echo "Uploading tarball ${NAME_TAR} -> container ${CONTAINER_NAME} as ${NAME_DST_PATH}"
  
  ALLOW_SHARED_KEY=$(az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$STORAGE_RESOURCE_GROUP" --query "allowSharedKeyAccess" -o tsv 2>/dev/null || echo "")
  echo "Storage account allowSharedKeyAccess=$ALLOW_SHARED_KEY"

  if [ -n "$SAS_TOKEN" ] && command -v azcopy &>/dev/null; then
  # If blob already exists, respect OVERWRITE env var (default: false)
  BLOB_EXISTS="false"
  if az storage blob exists --account-name "$STORAGE_ACCOUNT" --container-name "$CONTAINER_NAME" --name "$NAME_DST_PATH" --auth-mode login -o tsv 2>/dev/null | grep -q true; then
    BLOB_EXISTS="true"
  fi
  if [ "$BLOB_EXISTS" = "true" ] && [ "${OVERWRITE:-false}" != "true" ]; then
    echo "ERROR: target blob already exists: ${NAME_DST_PATH}. Rerun with OVERWRITE=true to replace it, or delete the blob manually." >&2
    exit 1
  fi
  if [ "$BLOB_EXISTS" = "true" ] && [ "${OVERWRITE:-false}" = "true" ]; then
    echo "OVERWRITE=true: deleting existing blob before upload"
    az storage blob delete --account-name "$STORAGE_ACCOUNT" --container-name "$CONTAINER_NAME" --name "$NAME_DST_PATH" --auth-mode login || true
  fi
  azcopy cp "$NAME_TAR" "${BLOB_URL}/${NAME_DST_PATH}?${SAS_TOKEN}" --log-level=INFO ${AZCOPY_EXTRA_FLAGS}
else
  if [ "$ALLOW_SHARED_KEY" = "false" ]; then
    # Storage account forbids key-based auth; use explicit blob URL with AD login
    echo "Shared-key auth disabled; uploading via explicit blob-url with AD login"
    BLOB_URL_EXPLICIT="https://${STORAGE_ACCOUNT}.blob.core.windows.net/${CONTAINER_NAME}/${NAME_DST_PATH}"
    # Check if blob already exists (AD login path)
    if az storage blob exists --account-name "$STORAGE_ACCOUNT" --container-name "$CONTAINER_NAME" --name "$NAME_DST_PATH" --auth-mode login -o tsv 2>/dev/null | grep -q true; then
      if [ "${OVERWRITE:-false}" = "true" ]; then
        echo "OVERWRITE=true: deleting existing blob before upload"
        az storage blob delete --account-name "$STORAGE_ACCOUNT" --container-name "$CONTAINER_NAME" --name "$NAME_DST_PATH" --auth-mode login || true
      else
        echo "ERROR: target blob already exists: ${NAME_DST_PATH}. Rerun with OVERWRITE=true to replace it, or delete the blob manually." >&2
        exit 1
      fi
    fi
    az storage blob upload --file "$NAME_TAR" --blob-url "$BLOB_URL_EXPLICIT" --auth-mode login || {
      echo "ERROR: Failed uploading tarball via explicit blob-url with AD login" >&2
      exit 1
    }
  else
    # Try az CLI upload using AD auth (or connection string if available)
    az storage blob upload --account-name "$STORAGE_ACCOUNT" --container-name "$CONTAINER_NAME" \
      --file "$NAME_TAR" --name "$NAME_DST_PATH" --auth-mode login || {
        echo "ERROR: Failed uploading tarball via az storage (and no azcopy+SAS available)" >&2
        exit 1
      }
  fi
fi
else
  echo "TAR_AND_UPLOAD=false: skipping upload, will extract from existing blob"
fi  # End TAR_AND_UPLOAD conditional

# Optionally extract and upload extracted files
if [ "$EXTRACT_TARBALL" = "true" ]; then
  # If TAR_AND_UPLOAD=false, download the tar from blob first
  if [ "${TAR_AND_UPLOAD:-true}" = "false" ]; then
    echo "Downloading ${NAME_DST_PATH} from Azure blob storage to extract locally..."
    NAME_TAR="$TMP_WORKDIR/${NAME}.tar"
    az storage blob download --account-name "$STORAGE_ACCOUNT" --container-name "$CONTAINER_NAME" --name "$NAME_DST_PATH" --file "$NAME_TAR" --auth-mode login
    echo "Downloaded to $NAME_TAR"
  fi
  
  echo "Extracting $NAME_TAR locally and uploading contents to ${NAME}_extracted/"
  EXTRACT_DIR="$TMP_WORKDIR/${NAME}_extracted"
  rm -rf "$EXTRACT_DIR" && mkdir -p "$EXTRACT_DIR"
  
  # Detect archive type and use appropriate tar flags
  if [[ "$NAME_TAR" == *.tar.gz ]] || [[ "$NAME_TAR" == *.tgz ]]; then
    tar -C "$EXTRACT_DIR" -xzf "$NAME_TAR"
  else
    tar -C "$EXTRACT_DIR" -xf "$NAME_TAR"
  fi

  # Upload extracted files
  if [ -n "$SAS_TOKEN" ] && command -v azcopy &>/dev/null; then
    azcopy cp "$EXTRACT_DIR" "${BLOB_URL}/${NAME}_extracted/?${SAS_TOKEN}" --recursive=true --log-level=INFO ${AZCOPY_EXTRA_FLAGS}
  else
    az storage blob upload-batch --account-name "$STORAGE_ACCOUNT" --destination "$CONTAINER_NAME" \
      --source "$EXTRACT_DIR" --destination-path "${NAME}_extracted" --auth-mode login --overwrite
  fi

  rm -rf "$EXTRACT_DIR"
  if [ "${TAR_AND_UPLOAD:-true}" = "false" ]; then
    rm -f "$NAME_TAR"  # Clean up downloaded tar
  fi
fi

# Optionally remove local tarball after upload
if [ "$REMOVE_TARBALL_AFTER_UPLOAD" = "true" ]; then
  rm -f "$NAME_TAR"
fi

# Optionally delete the remote tarball blob after successful upload (useful if you want only extracted files stored)
if [ "$DELETE_REMOTE_AFTER_UPLOAD" = "true" ]; then
  echo "DELETE_REMOTE_AFTER_UPLOAD=true: deleting remote tarball blob ${NAME_DST_PATH} from container ${CONTAINER_NAME}"
  az storage blob delete --account-name "$STORAGE_ACCOUNT" --container-name "$CONTAINER_NAME" --name "$NAME_DST_PATH" --auth-mode login || {
    echo "Warning: failed to delete remote tarball blob; please check permissions or delete manually." >&2
  }
fi


info "[Step 6]: Registering Datastore in Azure ML"

STORAGE_KEY=$(az storage account keys list \
  --account-name "$STORAGE_ACCOUNT" \
  --resource-group "$STORAGE_RESOURCE_GROUP" \
  --query '[0].value' -o tsv)


info "Verify upload: az storage blob list --account-name $STORAGE_ACCOUNT --container-name $CONTAINER_NAME --connection-string '$CONN_STR' --output table | head"

### Upload summary (concrete URLs and small listing)
echo
info "Upload Summary"
TAR_BLOB_URL="https://${STORAGE_ACCOUNT}.blob.core.windows.net/${CONTAINER_NAME}/${NAME_DST_PATH}"
echo "Tarball uploaded to: ${TAR_BLOB_URL}"

echo
echo "Checking tarball metadata (may require AD login)..."
TAR_BLOB_URL="https://${STORAGE_ACCOUNT}.blob.core.windows.net/${CONTAINER_NAME}/${NAME_DST_PATH}"
if az storage blob show --blob-url "$TAR_BLOB_URL" --auth-mode login -o json >/dev/null 2>&1; then
  az storage blob show --blob-url "$TAR_BLOB_URL" --auth-mode login -o table
else
  echo "Tarball metadata: not found or insufficient permissions to read metadata"
fi

echo
echo "Listing a sample of extracted blobs under prefix '${NAME}_extracted/'"
if az storage blob list --account-name "$STORAGE_ACCOUNT" --container-name "$CONTAINER_NAME" --prefix "${NAME}_extracted/" --auth-mode login -o table | head -n 40; then
  :
else
  echo "No extracted blobs found or insufficient permissions to list blobs"
fi
print_sep 

# az storage blob delete --account-name "$STORAGE_ACCOUNT" --container-name "$CONTAINER_NAME" --name "$BLOB_NAME" --auth-mode login



