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

# Quick Start Guide

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

## Quick Run

A compact walkthrough to upload the dataset and submit a training job. Each step includes the exact commands to run and quick notes.

1) Upload dataset (long-running)

Start a `tmux` session so the upload survives SSH disconnects and network blips. Run the upload inside the tmux session so it continues if you detach.

```bash
# create and attach new session
tmux new -s simlingo-upload
# inside tmux, start the upload
bash azure_deploy_mp/upload_dataset.sh
# detach (Ctrl-B then D)
```

Tips:
- If you prefer a detached start: `tmux new -d -s simlingo-upload "bash azure_deploy_mp/upload_dataset.sh"`.
- `azcopy` is resumable: if the connection drops, re-run the same `azcopy copy ...` command (the script prints the full command); azcopy will resume where it left off.
- To re-attach and watch progress: `tmux attach -t simlingo-upload`.

2) Dry-run submit (recommended)

Before submitting a real job, inspect the generated job spec. This prints the job definition (environment, compute, command and env vars) but does not submit it.

```bash
bash azure_deploy_mp/launch_training.sh --dry-run
# or directly
python azure_deploy_mp/submit_to_azure.py --dry-run
```

Review the printed `command` and `environment_variables` for `BATCH_SIZE`, `NUM_GPUS`, and other settings. If anything looks off, export the desired env vars and re-run the dry-run.

3) Submit training

When ready, submit the training job. This will create (or reuse) the configured compute and stream logs to your terminal.

```bash
bash azure_deploy_mp/launch_training.sh
```

Monitor & verify:
- The submit script prints a Studio URL `View in Azure ML Studio: ...` — use that to inspect logs, outputs and metrics.
- To list jobs from the CLI: `az ml job list --workspace-name $AZ_WORKSPACE --resource-group $AZ_RESOURCE_GROUP`.

Quick troubleshooting
- If upload appears incomplete, re-run `upload_dataset.sh` or run the azcopy commands printed in the script; `azcopy` will resume partial uploads.
- If submission fails due to authentication, run `az login` and ensure `AZ_SUBSCRIPTION_ID`, `AZ_RESOURCE_GROUP`, and `AZ_WORKSPACE` are exported in your shell.
- For OOM errors during training, reduce `BATCH_SIZE` or `NUM_GPUS` and re-submit.


