"""Submit SimLingo training job to Azure ML."""
import os
from pathlib import Path
from azure_deploy_mp.config import (
    PRINT_STUFF,
    SUBSCRIPTION_ID as DEFAULT_SUBSCRIPTION_ID,
    RESOURCE_GROUP as DEFAULT_RESOURCE_GROUP,
    WORKSPACE_NAME as DEFAULT_WORKSPACE_NAME,
    ENV_NAME,
    DEFAULT_SKU,
    DEFAULT_MIN_INSTANCES,
    DEFAULT_MAX_INSTANCES,
    DEFAULT_IDLE_TIME,
)

SUBSCRIPTION_ID = os.environ.get("AZ_SUBSCRIPTION_ID", "YOUR_SUBSCRIPTION_ID")
RESOURCE_GROUP = os.environ.get("AZ_RESOURCE_GROUP", "YOUR_RESOURCE_GROUP")
WORKSPACE_NAME = os.environ.get("AZ_WORKSPACE", "YOUR_WORKSPACE_NAME")

# Run from project root
proj_root = Path(__file__).resolve().parent.parent
os.chdir(proj_root)

# Get workspace variables from environment
SUBSCRIPTION_ID = os.environ.get("AZ_SUBSCRIPTION_ID", DEFAULT_SUBSCRIPTION_ID)
RESOURCE_GROUP = os.environ.get("AZ_RESOURCE_GROUP", DEFAULT_RESOURCE_GROUP)
WORKSPACE_NAME = os.environ.get("AZ_WORKSPACE", DEFAULT_WORKSPACE_NAME)

print("=" * PRINT_STUFF)
print("[INFO]: SimLingo Azure ML Job Submission")
print("=" * PRINT_STUFF)
print(f"Working directory : {os.getcwd()}")
print(f"Subscription ID   : {SUBSCRIPTION_ID}")
print(f"Resource Group    : {RESOURCE_GROUP}")
print(f"Workspace         : {WORKSPACE_NAME}")
print("=" * PRINT_STUFF)

try:
    from azure.ai.ml import MLClient, command
    from azure.ai.ml.entities import AmlCompute
    from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential
except Exception as ex:
    print("[ERROR]: azure.ai.ml SDK not available:", ex)
    raise

# Authenticate
try:
    credential = DefaultAzureCredential()
    credential.get_token("https://management.azure.com/.default")
except Exception:
    credential = InteractiveBrowserCredential()

ml_client = MLClient(
    credential=credential,
    subscription_id=SUBSCRIPTION_ID,
    resource_group_name=RESOURCE_GROUP,
    workspace_name=WORKSPACE_NAME,
)

# Create or reuse compute cluster
compute_name = os.environ.get("AZ_COMPUTE", "simlingo-gpu-cluster")
compute_sku = os.environ.get("AZ_COMPUTE_SKU", DEFAULT_SKU)

try:
    compute = ml_client.compute.get(compute_name)
    print(f"[INFO]: Using existing compute '{compute_name}' ({compute.size})")
except Exception:
    print(f"[INFO]: Creating compute '{compute_name}' with SKU '{compute_sku}'...")
    compute_cluster = AmlCompute(
        name=compute_name,
        type="amlcompute",
        size=compute_sku,
        min_instances=DEFAULT_MIN_INSTANCES,
        max_instances=DEFAULT_MAX_INSTANCES,
        idle_time_before_scale_down=DEFAULT_IDLE_TIME,
    )
    ml_client.compute.begin_create_or_update(compute_cluster).result()
    print(f"[INFO]: Compute '{compute_name}' created successfully")

# Use Azure curated PyTorch GPU environment (includes torch 2.2, cuda 12.1)
env_name = os.environ.get("AZ_ENV_NAME", ENV_NAME)
print(f"[INFO]: Using curated environment: {env_name}")
from azure_deploy_mp.config import DEFAULT_BATCH, DEFAULT_SKU, gpus_for_sku

# Training configuration (centralized defaults)
batch_size = int(os.environ.get("BATCH_SIZE", str(DEFAULT_BATCH)))
# Resolve default GPUs based on compute SKU unless explicitly set
compute_sku_env = os.environ.get("AZ_COMPUTE_SKU", DEFAULT_SKU)
default_gpus = gpus_for_sku(compute_sku_env)
num_gpus = int(os.environ.get("NUM_GPUS", str(default_gpus)))
experiment_name = os.environ.get("EXPERIMENT_NAME", "simlingo_seed1")

print(f"[INFO]: Configuration: batch_size={batch_size}, num_gpus={num_gpus}")

# Install dependencies and run training
setup_cmd = """
pip install pytorch-lightning==2.1.0 hydra-core==1.3.2 wandb opencv-python-headless timm transformers einops peft sentencepiece protobuf flash-attn==2.5.6 && \
python azure_deploy_mp/azure_training.py
"""

job = command(
    code="./",
    command=setup_cmd,
    environment=env_name,
    compute=compute_name,
    display_name=f"simlingo_{experiment_name}",
    experiment_name="simlingo",
    environment_variables={
        "BATCH_SIZE": str(batch_size),
        "NUM_GPUS": str(num_gpus),
        "EXPERIMENT_NAME": experiment_name,
        "WANDB_PROJECT": "simlingo-azure",
    },
)

print("\n" + "=" * PRINT_STUFF)
print(f"Submitting job...")
returned_job = ml_client.jobs.create_or_update(job)
print(f"Job submitted successfully!")
print(f"Job Name: {returned_job.name}")
print(f"View in Azure ML Studio: {returned_job.studio_url}")
print("=" * PRINT_STUFF)

# Stream logs
print("\nStreaming job logs (Ctrl+C to stop)...\n")
try:
    ml_client.jobs.stream(returned_job.name)
except KeyboardInterrupt:
    print("\nLog streaming stopped. Job continues running.")
    print(f"View status at: {returned_job.studio_url}")
