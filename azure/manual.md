# Azure ML Project Contributor Guide - data-ai-vla
This guide helps ML engineers access and use Azure resources for the data-ai-vla project.

## 📋 Prerequisites
- Bosch network access (on-site or VPN)
- Azure AD group membership: IdM2BCD_mljp_mlops_contributor
- Azure CLI installed: Installation Guide
- Azure ML CLI extension: az extension add --name ml
- Docker installed for building training images
- To request access: Contact your team lead or infrastructure admin to add you to the contributor group. This grants: - AzureML Data Scientist role on the ML workspace - Storage Blob Data Contributor role on the project storage container - AcrPull and AcrPush roles on ACR (Azure Container Registry) repositories with data-ai-vla/ prefix - ACR stores Docker container images for training environments - AcrPull allows you to download existing images - AcrPush allows you to upload new Docker images you build

## 🏗️ Infrastructure Overview
The data-ai-vla project uses shared infrastructure with project-specific isolation:

### Shared Container Registry
- Name: daip5d5219fe9583105d6a83.azurecr.io
- Resource Group: rg-deveco-jp-common-shared-prd
- Project repository prefix: data-ai-vla/
- Your images: daip5d5219fe9583105d6a83.azurecr.io/data-ai-vla/<image-name>:<tag>
- Shared across all projects in Japan East region

### Shared Storage Account
- Name: daijpepdde0b7efc169e98db
- Resource Group: rg-deveco-jp-datastore-prd
- Your container: data-ai-vla
- Purpose: Datasets, model checkpoints, training outputs
- Shared account, isolated containers per project

### Dedicated ML Workspace
- Name: mlws-vkzvjsr-jpe-p-c515af2
- Resource Group: rg-deveco-jp-mlops-prd
- Subscription: XC_Development_XC-AS/ENG-JP_676317_DataAI
- Compute: gpu-cluster-t4 (NVIDIA T4, auto-scaling 0-4 nodes)
- Direct link: Open in Azure ML Studio
- Dedicated workspace for your project only


## 🔐 Step 1: Authenticate with Azure\
```bash
# Login to Azure
az login

# Set the correct subscription
az account set --subscription "XC_Development_XC-AS/ENG-JP_676317_DataAI"

# Verify your access
az account show

# Set default workspace (optional, saves typing)
az configure --defaults group=rg-deveco-jp-mlops-prd workspace=mlws-vkzvjsr-jpe-p-c515af2
```

Verify your permissions:

These commands will work only AFTER you've been added to the IdM2BCD_mljp_mlops_contributor group:

```bash
# Check workspace access
az ml workspace show --name mlws-vkzvjsr-jpe-p-c515af2 --resource-group rg-deveco-jp-mlops-prd

# Check storage access
az storage container show \
  --account-name daijpepdde0b7efc169e98db \
  --name data-ai-vla \
  --auth-mode login

# Check ACR access (ABAC-scoped roles don't support listing all repositories)
# Instead, check if you can access your project's repositories:
az acr repository show-tags \
  --name daip5d5219fe9583105d6a83 \
  --repository data-ai-vla/simlingo-training \
  --output table 2>&1 || echo "No repositories exist yet - you can create them with 'docker push'"
Expected errors if you don't have access yet: - Storage: This request is not authorized - ACR: authentication required or MANIFEST_UNKNOWN (if no images pushed yet) - ML Workspace: AuthorizationFailed or resource not found

Note about ACR access: Due to ABAC (Attribute-Based Access Control), you have scoped access to repositories with the data-ai-vla/ prefix only. You cannot list all repositories in the registry, but you can push/pull images to/from data-ai-vla/* repositories.
```

## 📦 Step 2: Work with Azure Storage
Important: All storage commands require --auth-mode login because this storage account uses Azure AD authentication only (shared key access is disabled for security). This flag tells Azure CLI to use your az login credentials instead of looking for storage account keys.

Upload Training Data
```bash
# Upload a dataset to your project container
az storage blob upload-batch \
  --account-name daijpepdde0b7efc169e98db \
  --destination data-ai-vla \
  --source ./local/my_dataset/ \
  --destination-path datasets/raw/my_dataset/ \
  --auth-mode login

# Upload a single file
az storage blob upload \
  --account-name daijpepdde0b7efc169e98db \
  --container-name data-ai-vla \
  --name datasets/raw/data.csv \
  --file ./local/data.csv \
  --auth-mode login

```
### Recommended Directory Structure

Organize data in your container (data-ai-vla) following this pattern:
```bash
data-ai-vla/
├── datasets/
│   ├── raw/              # Original unprocessed data
│   ├── processed/        # Preprocessed training-ready data
│   └── external/         # Downloaded datasets (e.g., COCO, ImageNet)
├── models/
│   ├── checkpoints/      # Training checkpoints (.ckpt, .pt files)
│   ├── pretrained/       # Downloaded pretrained models
│   └── final/            # Final trained model artifacts
└── outputs/
    ├── experiments/      # Experiment logs and results
    └── visualizations/   # Generated plots and visualizations
```

## Step 3: Local Project Setup
Clone SimLingo into your project:

SimLingo is NOT included in the container (only dependencies are). You must clone it locally:
```bash
# In your project root
mkdir -p src
cd src
git clone https://github.com/RenzKa/simlingo.git
cd ..

# Add to .gitignore (optional - prevents committing SimLingo changes)
echo "src/simlingo/" >> .gitignore
Your project structure:

your-project/
├── .gitignore              # Optional: src/simlingo/
├── Dockerfile              # SimLingo dependencies only
├── src/
│   ├── simlingo/          # SimLingo repository (required)
│   ├── train.py           # Your training script
│   └── utils.py           # Your utilities
└── job.yml                 # Azure ML job configuration
```

Why this approach: - Smaller container images - Only dependencies, not code (~2GB smaller) - Faster iterations - Change SimLingo code without rebuilding Docker images - Azure ML best practice - Separate environment (container) from code (mount) - Version flexibility - Easy to switch SimLingo versions/branches

## 🐳 Step 4: Build and Push Docker Images
Login to Container Registry
az acr login --name daip5d5219fe9583105d6a83

### Example Dockerfile for Azure ML
Use Azure ML curated base images for best compatibility:

```bash
# Azure ML doesn't have CUDA 12.1 base images, so use Ubuntu 22.04
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    wget \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Miniconda
RUN wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh && \
    bash /tmp/miniconda.sh -b -p /opt/conda && \
    rm /tmp/miniconda.sh
ENV PATH=/opt/conda/bin:$PATH

# Create conda environment from SimLingo's environment.yaml (mounted from local src/simlingo/)
WORKDIR /workspace
RUN --mount=type=bind,source=./src/simlingo,target=/tmp/simlingo \
    conda env create -f /tmp/simlingo/environment.yaml

# Make conda environment available
SHELL ["conda", "run", "-n", "simlingo", "/bin/bash", "-c"]

# Install PyTorch 2.2.0 separately to ensure correct CUDA version (per SimLingo setup)
RUN pip install torch==2.2.0

# Install flash-attn separately (required by SimLingo)
RUN pip install flash-attn==2.7.0.post2

# Activate conda environment on container start
RUN echo "conda activate simlingo" >> ~/.bashrc
ENV PATH=/opt/conda/envs/simlingo/bin:$PATH

# Set entrypoint
ENTRYPOINT ["/bin/bash"]

```

Key Notes: - Dependencies only in container - All SimLingo dependencies installed, but not the code itself - Build requires local clone - SimLingo must be cloned to src/simlingo/ before building (Step 3) - Build-time mount reads environment.yaml without embedding SimLingo in the image - SimLingo code comes from local src/ directory mounted via Azure ML job submission - Smaller image size, faster iterations (no rebuild needed for code changes) - Follows Azure ML best practice: separate environment from code

### Build and Push Image
```bash
# Build your image
docker build -t simlingo-training:v1 .

# Tag with ACR path (use data-ai-vla/ prefix)
docker tag simlingo-training:v1 \
  daip5d5219fe9583105d6a83.azurecr.io/data-ai-vla/simlingo-training:v1

# Push to ACR
docker push daip5d5219fe9583105d6a83.azurecr.io/data-ai-vla/simlingo-training:v1

# Verify upload
az acr repository show-tags \
  --name daip5d5219fe9583105d6a83 \
  --repository data-ai-vla/simlingo-training \
  --output table

```

### Manage ACR Repositories
Important: Due to ABAC-scoped permissions, you cannot list all repositories. You can only interact with repositories that start with data-ai-vla/.

```bash
# List tags for your project's repository (replace with actual repository name)
# Note: This will fail with MANIFEST_UNKNOWN if the repository doesn't exist yet
az acr repository show-tags \
  --name daip5d5219fe9583105d6a83 \
  --repository data-ai-vla/simlingo-training \
  --output table

# Delete old tags
az acr repository delete \
  --name daip5d5219fe9583105d6a83 \
  --image data-ai-vla/simlingo-training:old-tag \
  --yes
```
## 🗂️ Step 5: Create and Manage Datasets
Register a Dataset in Azure ML
Create reusable dataset references for reproducible training:

```bash
# Create dataset definition file
cat > my_dataset.yml <<EOF
\$schema: https://azuremlschemas.azureedge.net/latest/data.schema.json
name: simlingo_driving_v1
description: SimLingo autonomous driving dataset
type: uri_folder
path: azureml://datastores/workspaceblobstore/paths/datasets/processed/simlingo_v1/
tags:
  project: data-ai-vla
  version: "1.0"
  type: driving
EOF

# Register the dataset
az ml data create \
  --file my_dataset.yml \
  --resource-group rg-deveco-jp-mlops-prd \
  --workspace-name mlws-vkzvjsr-jpe-p-c515af2

# List registered datasets
az ml data list --output table

# Show dataset details
az ml data show --name simlingo_driving_v1 --version 1
```


### Reference Datasets in Training Jobs


Option 1: Use registered dataset
```bash
# In your job.yml
inputs:
  training_data:
    type: uri_folder
    path: azureml:simlingo_driving_v1:1  # name:version
```

Option 2: Reference storage path directly

```bash
inputs:
  training_data:
    type: uri_folder
    path: azureml://datastores/workspaceblobstore/paths/datasets/processed/simlingo_v1/
```

### Dataset Versioning Best Practices
```bash
# Version 1: Initial dataset
az ml data create --file dataset_v1.yml

# Version 2: After preprocessing changes
# Update version in YAML, then:
az ml data create --file dataset_v2.yml

# List all versions
az ml data list --name simlingo_driving_v1 --output table
```

## 🚀 Step 6: Submit Training Jobs


Example Training Job Configuration
Create a job YAML file (job.yml):
```bash
$schema: https://azuremlschemas.azureedge.net/latest/commandJob.schema.json

# Job identification
display_name: simlingo_vla_training
experiment_name: data-ai-vla-experiments
description: Train SimLingo VLA model on autonomous driving data

# Code and environment
code: ./src
environment:
  image: daip5d5219fe9583105d6a83.azurecr.io/data-ai-vla/simlingo-training:v1

# Compute configuration
compute: azureml:gpu-cluster-t4
resources:
  instance_count: 2  # Distributed training across 2 nodes

# Training command
command: >-
  python train.py
  --data_path ${{inputs.training_data}}
  --output_path ${{outputs.model_output}}
  --epochs 100
  --batch_size 32
  --learning_rate 1e-4
  --gpus 1

# Inputs and outputs
inputs:
  training_data:
    type: uri_folder
    path: azureml:simlingo_driving_v1:1
    mode: ro_mount  # Read-only mount

outputs:
  model_output:
    type: uri_folder
    mode: rw_mount  # Read-write mount for checkpoints

# Tags for organization
tags:
  project: data-ai-vla
  model: simlingo-vla
  framework: pytorch

```

### Submit the Job
```bash
# Submit training job
az ml job create \
  --file job.yml \
  --resource-group rg-deveco-jp-mlops-prd \
  --workspace-name mlws-vkzvjsr-jpe-p-c515af2

# Alternative: Submit without file (inline)
az ml job create \
  --command "python train.py --epochs 50" \
  --environment daip5d5219fe9583105d6a83.azurecr.io/data-ai-vla/simlingo-training:v1 \
  --compute gpu-cluster-t4 \
  --code ./src
```

### Monitor Job Status
```bash
# List recent jobs
az ml job list \
  --resource-group rg-deveco-jp-mlops-prd \
  --workspace-name mlws-vkzvjsr-jpe-p-c515af2 \
  --output table

# Show specific job details
az ml job show --name <job-name>

# Stream job logs in real-time
az ml job stream --name <job-name>

# Download job outputs
az ml job download --name <job-name> --download-path ./outputs/
```

### Monitor in Azure ML Studio
Direct workspace link: Open data-ai-vla workspace in Azure ML Studio

Once in the workspace: - View Jobs → Monitor metrics, logs, and outputs - View Compute → Check cluster utilization - View Data → Browse registered datasets - View Endpoints → Manage deployed models


## Troubleshooting
Access Denied Errors
```bash
# Error: "AuthorizationPermissionMismatch"
# Solution: Verify group membership
az ad group member list --group "IdM2BCD_mljp_mlops_contributor"

# Check your current permissions
az role assignment list --assignee $(az ad signed-in-user show --query id -o tsv) --all
```

```bash
ACR Authentication Issues
# Error: "unauthorized: authentication required"
# Solution: Re-login to ACR
az acr login --name daip5d5219fe9583105d6a83

# Verify credentials
az acr credential show --name daip5d5219fe9583105d6a83
```

Storage Access Issues
```bash
# Error: "This request is not authorized"
# Solution: Use --auth-mode login
az storage blob list \
  --account-name daijpepdde0b7efc169e98db \
  --container-name data-ai-vla \
  --auth-mode login  # ← Add this flag
```


Compute Cluster Not Available
```bash
# Check cluster status
az ml compute show \
  --name gpu-cluster-t4 \
  --resource-group rg-deveco-jp-mlops-prd \
  --workspace-name mlws-vkzvjsr-jpe-p-c515af2

# List all available compute
az ml compute list --output table
```
Job Failures
```bash
# View detailed error logs
az ml job stream --name <job-name>

# Download all logs for offline analysis
az ml job download --name <job-name> --all --download-path ./debug_logs/

# Common issues:
# 1. Image not found → Verify ACR path and tag
# 2. Out of memory → Reduce batch size or use gradient accumulation
# 3. Data not found → Check dataset paths and mounting modes
```

## 📚 Additional Resources
Azure ML Documentation: https://learn.microsoft.com/en-us/azure/machine-learning/
Azure CLI Reference: https://learn.microsoft.com/en-us/cli/azure/ml
SimLingo VLA Repository: https://github.com/SAP-LAB-FPTU/SimLingo-VLA-model
Azure ML Curated Environments: https://learn.microsoft.com/en-us/azure/machine-learning/resource-curated-environments
💡 Optional: Download Data from Storage
If you need to download datasets from Azure Storage to your local machine for inspection or local development:

```bash
# Download a dataset
az storage blob download-batch \
  --account-name daijpepdde0b7efc169e98db \
  --source data-ai-vla \
  --pattern "datasets/processed/my_dataset/*" \
  --destination ./local/download/ \
  --auth-mode login

# List files in your container
az storage blob list \
  --account-name daijpepdde0b7efc169e98db \
  --container-name data-ai-vla \
  --prefix datasets/ \
  --auth-mode login \
  --output table

# Download a single file
az storage blob download \
  --account-name daijpepdde0b7efc169e98db \
  --container-name data-ai-vla \
  --name datasets/processed/data.csv \
  --file ./local/data.csv \
  --auth-mode login
```