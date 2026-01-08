Streaming Hugging Face -> Azure
=================================

This folder contains a small streaming uploader that lists files in a Hugging Face dataset
repo and streams each file directly into an Azure Blob container without keeping a full
local copy.

Quick start

1. Install requirements (prefer inside a venv):

```bash
pip install -r azure_deploy_mp/requirements-stream.txt
```

2. Run the streamer (example):

```bash
python azure_deploy_mp/stream_hf_to_azure.py \
  --hf-repo RenzKa/simlingo \
  --storage-account daijpepdde0b7efc169e98db \
  --container data-ai-vla \
  --dest-prefix datasets/processing_incoming/simlingo_stream_test \
  --workers 8
```

Notes
- For private repos pass `--hf-token`.
- The script uses the Azure Blob SDK; authenticate with environment credentials or managed identity.
- This is intended for large datasets where a full local clone is impractical.
# Simlingo Training on Azure ML

Quick guide to run the Simlingo training `simlingo/simlingo_training.sh` on Azure ML using Standard_NC16as_T4_v3 (4x T4 GPUs, 64 vCPUs, 440GB RAM).

---

## Pre

1. **Azure ML Workspace**: Have your `subscription_id`, `resource_group`, and `workspace` name ready
```bash
echo $AZ_SUBSCRIPTION_ID $AZ_RESOURCE_GROUP $AZ_WORKSPACE
az account show 
```
2. **Azure CLI** (`setup_azure.sh`):
   ```bash
   curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
   az login
   ```
3. **Python Dependencies** (`setup_azure.sh`):
   ```bash
   pip install azure-ai-ml azure-identity
   ```
---

## Setup

### 1. Configure Azure Credentials

Run the setup script and export the credentials it prints:
```bash
bash azure_deploy_mp/setup_azure.sh
export AZ_SUBSCRIPTION_ID="your-subscription-id"
export AZ_RESOURCE_GROUP="your-resource-group"
export AZ_WORKSPACE="your-workspace-name"

echo $AZ_SUBSCRIPTION_ID $AZ_RESOURCE_GROUP $AZ_WORKSPACE
unset AZ_SUBSCRIPTION_ID AZ_RESOURCE_GROUP AZ_WORKSPACE

```
This script `setup_azure.sh` will run the prerequisistes. 

### 2. Upload Your Dataset

Training requires **~847GB** from `database/` (~847GB) (not ours):
- `simlingo_v2_2025_01_10/` (846GB)
- `bucketsv2_simlingo/` (647MB)
- `recording_japan_xml/` (?) [optional] (ours)

**Upload to Azure Blob Storage**:
```bash
tmux new -s upload # run this so it will not dosconnect
bash azure_deploy_mp/upload_dataset.sh
```
This script:
- Creates Azure storage account + container
- Uploads dataset using `azcopy` (resumable)
- Registers datastore in Azure ML
- Cost: ~$15/month for storage

**Example `tmux` workflow.**
Start a new tmux session named 'simlingo-upload' and run the upload inside it:
```bash
tmux new -s simlingo-upload
bash azure_deploy_mp/upload_dataset.sh
```
Detach the session without stopping the upload: press Ctrl-B then D
Re-attach later to check progress:
```bash
tmux attach -t simlingo-upload
```
Or run the whole command in one line (nosn-interactive session):
```bash
tmux new -d -s simlingo-upload "bash azure_deploy_mp/upload_dataset.sh"
```

### 3. Configure Training Param (Optional)

Set environment variables to customize training:

```bash
export BATCH_SIZE=4                             # Batch size per GPU (default: 4, up to 4). 
export NUM_GPUS=4                               # Number of GPUs (default: 4 for NC16as_T4_v3)
export EXPERIMENT_NAME=simlingo_seed1           # Experiment name (default: simlingo_seed1)
export AZ_COMPUTE=simlingo-gpu-cluster          # Compute cluster name
export AZ_COMPUTE_SKU=Standard_NC16as_T4_v3     # VM SKU
```

---

## Launch Training

**Important**: You must export **Azure credentials** first (see, Setup step 1)

Then run step-by-step:
```bash
bash azure_deploy_mp/setup_azure.sh      # Configure credentials (prints export commands)
# Export the printed variables refer to line 29-21 on this doc.
bash azure_deploy_mp/upload_dataset.sh   # Upload ~850GB dataset
bash azure_deploy_mp/launch_training.sh  # Submit training job
```

---

## Monitor Training

### In Terminal `bash`
The script automatically streams logs. Press `Ctrl+C` to stop streaming (job continues).

### In Azure ML Studio
1. The script prints a studio URL: `View in Azure ML Studio: https://ml.azure.com/...`
2. Click the link to view metrics, logs, and outputs

### Check Job Status
```bash
az ml job list --workspace-name YOUR_WORKSPACE --resource-group YOUR_RESOURCE_GROUP
```

---

## Training Outputs

- **Checkpoints**: Saved in Azure ML's outputs folder
- **Logs**: Available in Azure ML Studio under "Outputs + logs" tab
- **WandB**: Metrics logged to WandB project `simlingo-azure`

---

## File Structure

```
azure_deploy_mp/
├── common.sh               # Shared helper functions
├── setup_azure.sh          # Configure Azure credentials
├── upload_dataset.sh       # Upload dataset to Azure Blob
├── launch_training.sh      # Submit training job
├── azure_training.py       # Training entrypoint on Azure
├── submit_to_azure.py      # Job submission logic
└── README.md               # This file
```

---

<!-- ## Cost Estimation

Standard_NC16as_T4_v3 pricing (pay-as-you-go, East US):
- **~$1.50-2.00/hour** depending on region
- Training typically takes **24-72 hours** for full convergence
- **Estimated cost**: $36-$144 per full training run

**Cost-saving tips**:
- Use lower `idle_time_before_scale_down` (set in submit_to_azure.py)
- Start with smaller batch sizes to test
- Use spot instances if available (add `tier="Spot"` to AmlCompute) -->

## Troubleshooting

### "Subscription not found"
Ensure you're logged in: `az login` and have correct subscription ID.

### "Compute creation failed"
- Check quota limits: `az vm list-usage --location eastus`
- Request quota increase in Azure Portal

### "Out of memory during training"
- Reduce `BATCH_SIZE`: `export BATCH_SIZE=4`. This will not work when > 2.
- Reduce number of GPUs: `export NUM_GPUS=2`

### "Dataset not found"
Run `bash azure_deploy_mp/upload_dataset.sh` to upload the 846GB dataset to Azure Blob Storage.

<!-- ## Advanced Configuration

### Multi-GPU Training
The script automatically uses all 4 GPUs on Standard_NC16as_T4_v3:
```bash
export NUM_GPUS=4
export BATCH_SIZE=8  # Effective batch size = 4 GPUs × 8 = 32
```

### Use Different VM SKU
```bash
export AZ_COMPUTE_SKU=Standard_NC24ads_A100_v4  # 1x A100
python azure_deploy_mp/submit_to_azure.py
``` -->

### Custom Hydra Config
Edit [azure_training.py](azure_training.py) line 48-53 to pass additional Hydra parameters.

---

# Start Guide (Kind of verbose)

Operative procedure to run simlingo training.

## Launch

### Setup (One-time)

On Azure ML, we have:

**Log in**: (`azure_deploy_mp/setup_azure.sh`)
```bash 
az login --use-device-code
# A code <YOUR_SUBSCRIPTION_ID> (e.g., G4D7K2P9, 676317)
# A URL: https://microsoft.com/devicelogin
# Enter the code
az account set --subscription <YOUR_SUBSCRIPTION_ID>
```
**Compute**: 
Standard_NC16as_T4_v3
- 4x NVIDIA T4 GPUs (16GB each)
- 64 vCPUs
- 440GB RAM
- **Cost**: ~$1.50-2.00/hour

```bash
cd /workspace/simlingo && bash azure_deploy_mp/setup_azure.sh
```
This will:
- Install Azure CLI (if needed)
- Log you into Azure
- Ask for your workspace details
- Save configuration to `.env`

### Launch Training
```bash
bash azure_deploy_mp/launch_training.sh
```
This will:
- Build the Docker environment (first time only, ~20 min)
- Create GPU compute cluster if needed
- Submit training job
- Stream logs to your terminal

#### Note

Before running `launch_training.sh`, set these environment variables:

```bash
export WANDB_API_KEY="your_wandb_api_key_here"
export USE_ACR_IMAGE="myregistry.azurecr.io/simlingo:latest"   # optional
export BATCH_SIZE=4              # Lower if OOM errors
export NUM_GPUS=2                # Use fewer GPUs
export EXPERIMENT_NAME=my_test   # Custom name
```

---

## Files

- [README.md](README.md) - Full documentation
- [setup_azure.sh](setup_azure.sh) - One-time setup
- [launch_training.sh](launch_training.sh) - Launch training
- [submit_to_azure.py](submit_to_azure.py) - Job submission script
- [azure_training.py](azure_training.py) - Training entrypoint

---
---

## Quick Run

0. Run interactive setup (once per shell/session)

```bash
bash azure_deploy_mp/setup_azure.sh

az login
az account set --subscription "XC_Development_XC-AS/ENG-JP_676317_DataAI"
az account show
az configure --defaults group=rg-deveco-jp-mlops-prd workspace=mlws-vkzvjsr-jpe-p-c515af2

export AZ_SUBSCRIPTION_ID="your-subscription-id"
export AZ_RESOURCE_GROUP="your-resource-group"
export AZ_WORKSPACE="your-workspace-name"

echo $AZ_SUBSCRIPTION_ID $AZ_RESOURCE_GROUP $AZ_WORKSPACE
# unset AZ_SUBSCRIPTION_ID AZ_RESOURCE_GROUP AZ_WORKSPACE
```
Veryfy the permission here.

```bash
# Check workspace access
az ml workspace show --name mlws-vkzvjsr-jpe-p-c515af2 --resource-group rg-deveco-jp-mlops-prd

# Check storage access
az storage container show \
  --account-name daijpepdde0b7efc169e98db \
  --name data-ai-vla \
  --auth-mode login

# Check ACR access (ABAC-scoped roles don't support listing all repositories)
az acr repository show-tags \
  --name daip5d5219fe9583105d6a83 \
  --repository data-ai-vla/simlingo-training \
  --output table 2>&1 || echo "No repositories exist yet - you can create them with 'docker push'"
```

From here, we can run the actual simlingo task. 

1) Upload dataset (long-running)

Start a `tmux` session so the upload survives SSH disconnects and network blips. 
Run the upload inside the `tmux` session so it continues if you detach.

```bash
# create and attach new session
tmux new -s simlingo-upload
# inside tmux, start the upload
bash azure_deploy_mp/upload_dataset.sh # detach (Ctrl-B then D)

tmux new -s azure_upload -d 'bash -lc "source ~/miniconda3/etc/profile.d/conda.sh && conda activate simlingo && cd /workspace/simlingo && export AZ_SUBSCRIPTION_ID=\"2378c487-e6cc-41e8-9251-2d62a3135b3f\" && export AZ_RESOURCE_GROUP=\"rg-deveco-jp-mlops-prd\" && export AZ_WORKSPACE=\"mlws-vkzvjsr-jpe-p-c515af2\" && export STORAGE_ACCOUNT=\"daijpepdde0b7efc169e98db\" && export STORAGE_RESOURCE_GROUP=\"rg-deveco-jp-datastore-prd\" && export CONTAINER_NAME=\"data-ai-vla\" && export DATASET_DIR=\"/workspace/simlingo/database\" && bash azure_deploy_mp/upload_dataset.sh > /workspace/simlingo/azure_deploy_mp/azure_upload.log 2>&1"' 

tail -f /workspace/simlingo/azure_deploy_mp/azure_upload.log

```
<!-- Tips:
- If you prefer a detached start: `tmux new -d -s simlingo-upload "bash azure_deploy_mp/upload_dataset.sh"`.
- `azcopy` is resumable: if the connection drops, re-run the same `azcopy copy ...` command; `azcopy` will resume where it left off.
- To re-attach and watch progress: `tmux attach -t simlingo-upload`. -->

2) Dry-run submit

Before submitting a real job, inspect the generated job spec. This prints the job definition (environment, compute, command and env vars) but does not submit it.

```bash
bash azure_deploy_mp/launch_training.sh --dry-run
# or directly
python azure_deploy_mp/submit_to_azure.py --dry-run
```

Review the printed `command` and `environment_variables` for `BATCH_SIZE`, `NUM_GPUS`, and other settings. 
If anything looks off, export the desired env vars and re-run the dry-run.

3) Submit

Once ready, submit the training job. This will create (or reuse) the configured compute and stream logs to your terminal.

```bash
bash azure_deploy_mp/launch_training.sh
```

Monitor & verify:
- The submit script prints a Studio URL `View in Azure ML Studio: ...` — use that to inspect logs, outputs and metrics.
- To list jobs from the CLI: `az ml job list --workspace-name $AZ_WORKSPACE --resource-group $AZ_RESOURCE_GROUP`.
- Open https://wandb.ai and sign in with your account and navigate to the `simlingo-azure` project 

## Weights & Biases (W&B)

This project logs metrics to Weights & Biases. By default the job sets `WANDB_PROJECT=simlingo-azure`.

```bash
export WANDB_API_KEY="<your-wandb-api-key>"
# optional: set project name (job also sets this automatically)
export WANDB_PROJECT=simlingo-azure
# run training locally or submit the job — W&B logs will appear under your account
python azure_deploy_mp/azure_training.py
```

### Docker / Custom Environment (conda)
#### [NOT IMPLEMENTED]

- The repo uses Azure's curated PyTorch environment by default (`ENV_NAME` in `config.py`). At the time, we **do not need** to build or register a Docker image to run the supplied workflow.
- Use a custom Docker image only if you need **reproducible startup times or preinstalled packages**. 
  Build & push the image to a registry (ACR or Docker Hub), then register it or reference the image URI in your job environment. Example (register once, optional):

```python
from azure.ai.ml import MLClient, Environment
from azure.identity import DefaultAzureCredential

ml = MLClient(DefaultAzureCredential(), subscription_id, resource_group, workspace_name)
env = Environment(name="simlingo-custom", image="myregistry.azurecr.io/simlingo:latest")
ml.environments.create_or_update(env)
```

Use the registered name or full image URI in `AZ_ENV_NAME` to have jobs use your custom image.





<!-- ```bash
bash azure_deploy_mp/setup_azure.sh
az login
az account set --subscription "XC_Development_XC-AS/ENG-JP_676317_DataAI"
az account show
az configure --defaults group=rg-deveco-jp-mlops-prd workspace=mlws-vkzvjsr-jpe-p-c515af2
``` -->

