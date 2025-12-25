
import os
import sys
import subprocess
from pathlib import Path

# Make workspace identifiers configurable via environment variables
# Use actual values from manual_sven.md
SUBSCRIPTION_ID = os.environ.get("AZ_SUBSCRIPTION_ID", "2378c487-e6cc-41e8-9251-2d62a3135b3f")
RESOURCE_GROUP = os.environ.get("AZ_RESOURCE_GROUP", "rg-deveco-jp-mlops-prd")
WORKSPACE_NAME = os.environ.get("AZ_WORKSPACE", "mlws-vkzvjsr-jpe-p-c515af2")

# Run from project root (parent of azure_deploy/)
proj_root = Path(__file__).resolve().parent.parent
os.chdir(proj_root)

# Optional CARLA path wiring, only if CARLA_ROOT is set
carla_root = os.environ.get("CARLA_ROOT", "")
if carla_root:
    os.environ["PYTHONPATH"] = f"{carla_root}/PythonAPI/carla/:" + os.environ.get("PYTHONPATH", "")

# Runtime env vars (defaulted if not present)
os.environ["WORK_DIR"] = str(proj_root)
os.environ["PYTHONPATH"] = os.environ.get("PYTHONPATH", "") + f":{os.environ['WORK_DIR']}"
os.environ.setdefault("MASTER_ADDR", "localhost")
os.environ.setdefault("NCCL_DEBUG", "INFO")
os.environ.setdefault("OMP_NUM_THREADS", "64")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("HYDRA_FULL_ERROR", "1")
os.environ.setdefault("WANDB__SERVICE_WAIT", "100")

print("Working dir:", os.getcwd())
print("Python:", sys.version)

print("Checking CUDA:", end=" ")
try:
    import torch
    print(torch.cuda.is_available(), "devices:", torch.cuda.device_count())
except Exception as e:
    print("torch import failed:", e)

# If USE_ACR_IMAGE is set, use that prebuilt image name (full ACR path)
use_acr = os.environ.get("USE_ACR_IMAGE", "")
if use_acr:
    print("Using prebuilt ACR image:", use_acr)
    # Build a simple job spec that references the existing image instead of building
    try:
        from azure.ai.ml import MLClient, command
        from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential
    except Exception as ex:
        print("azure.ai.ml SDK not available:", ex)
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

    # Create or reuse compute (use actual compute from manual_sven.md)
    compute_name = os.environ.get("AZ_COMPUTE", "gpu-cluster-t4")
    try:
        _ = ml_client.compute.get(compute_name)
        print(f"Compute '{compute_name}' exists")
    except Exception:
        from azure.ai.ml.entities import AmlCompute
        print(f"Creating compute '{compute_name}'...")
        compute_cluster = AmlCompute(
            name=compute_name,
            type="amlcompute",
            size=os.environ.get("AZ_COMPUTE_SKU", "Standard_NC24ads_A100_v4"),
            min_instances=0,
            max_instances=4,  # manual says 0-4 nodes
            idle_time_before_scale_down=300,
        )
        ml_client.compute.begin_create_or_update(compute_cluster).result()

    # Command job referencing the image
    print("Submitting command job using image", use_acr)
    job = command(
        code="./",
        command="python azure_training.py",
        environment={'image': use_acr},
        compute=compute_name,
        display_name="simlingo_training_seed1",
        experiment_name="simlingo",
    )

    returned_job = ml_client.jobs.create_or_update(job)
    print("Job submitted!", returned_job.name)
    print("Studio:", returned_job.studio_url)
    ml_client.jobs.stream(returned_job.name)
else:
    # Use Azure ML curated CUDA 12 image instead of building from Dockerfile
    # This is faster and recommended per manual_sven.md commentary
    try:
        from azure.ai.ml import MLClient, command
        from azure.ai.ml.entities import Environment, AmlCompute
        from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential
    except Exception as ex:
        print("azure.ai.ml SDK not available:", ex)
        raise

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

    # Use Azure ML curated image with CUDA 12 (recommended approach)
    # Options: mcr.microsoft.com/azureml/curated/acft-hf-nlp-gpu:latest (CUDA 12.1 + PyTorch 2.1+)
    #          mcr.microsoft.com/azureml/openmpi4.1.0-cuda12.1-cudnn8-ubuntu22.04:latest
    curated_image = os.environ.get(
        "CURATED_IMAGE",
        "mcr.microsoft.com/azureml/curated/acft-hf-nlp-gpu:59"  # CUDA 12.1 + PyTorch 2.1
    )
    print(f"Using curated image: {curated_image}")

    compute_name = os.environ.get("AZ_COMPUTE", "gpu-cluster-t4")
    try:
        _ = ml_client.compute.get(compute_name)
        print(f"Compute '{compute_name}' exists")
    except Exception:
        print(f"Creating compute '{compute_name}'...")
        compute_cluster = AmlCompute(
            name=compute_name,
            type="amlcompute",
            size=os.environ.get("AZ_COMPUTE_SKU", "Standard_NC24ads_A100_v4"),
            min_instances=0,
            max_instances=4,
            idle_time_before_scale_down=300,
        )
        ml_client.compute.begin_create_or_update(compute_cluster).result()

    # Mount the uploaded dataset
    # Path should match what was uploaded in upload_dataset.sh
    from azure.ai.ml import Input
    from azure.ai.ml.constants import AssetTypes
    
    dataset_path = os.environ.get(
        "DATASET_PATH",
        "azureml://datastores/workspaceblobstore/paths/datasets/processed/simlingo_v2_2025_01_10/"
    )
    print(f"Mounting dataset from: {dataset_path}")
    
    # Submit job using curated image with runtime pip install for SimLingo deps
    job = command(
        code="./",
        command=(
            "pip install -q torch==2.2.0 flash-attn==2.7.0.post2 && "
            "pip install -q -r requirements.txt && "
            "python azure_training.py"
        ),
        inputs={
            "training_data": Input(
                type=AssetTypes.URI_FOLDER,
                path=dataset_path,
                mode="ro_mount"
            )
        },
        environment={'image': curated_image},
        compute=compute_name,
        display_name=os.environ.get("EXPERIMENT_NAME", "simlingo_training_seed1"),
        experiment_name="data-ai-vla-experiments",
    )

    print("Submitting job...")
    returned_job = ml_client.jobs.create_or_update(job)
    print(f"Job submitted! Job name: {returned_job.name}")
    print(f"View job in Azure ML Studio: {returned_job.studio_url}")
    ml_client.jobs.stream(returned_job.name)