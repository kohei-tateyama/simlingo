
"""Centralized defaults for azure_deploy_mp scripts.

Values are read from environment variables when present, otherwise fall back
to these defaults. Import this module from both `submit_to_azure.py` and
`azure_training.py` so they share the same configuration.
"""

import os

# Logging/printing width
PRINT_STUFF = int(os.environ.get("PRINT_STUFF", "80"))

# Azure workspace defaults (can be overridden in the environment)
SUBSCRIPTION_ID = os.environ.get("AZ_SUBSCRIPTION_ID", "YOUR_SUBSCRIPTION_ID")
RESOURCE_GROUP = os.environ.get("AZ_RESOURCE_GROUP", "YOUR_RESOURCE_GROUP")
WORKSPACE_NAME = os.environ.get("AZ_WORKSPACE", "YOUR_WORKSPACE_NAME")

WANDB_API_KEY = os.environ.get("WANDB_API_KEY", "<your-wandb-api-key>")
WANDB_PROJECT = os.environ.get("WANDB_PROJECT", "simlingo-azure")

# Azure ML Environment: use curated environment (no Docker build needed) or custom ACR image
# Curated: "AzureML-pytorch-2.2-cuda12.1-gpu" (PyTorch 2.2, CUDA 12.1, pre-installed)
# Custom:  "daip5d5219fe9583105d6a83.azurecr.io/data-ai-vla/simlingo-training:v1"
ENV_NAME = os.environ.get("AZ_ENV_NAME", "AzureML-pytorch-2.2-cuda12.1-gpu")
DEFAULT_SKU = os.environ.get("AZ_COMPUTE_SKU", "Standard_NC8as_T4_v3")
# Recommended default scale settings (min==max for fixed-size runs)
DEFAULT_MIN_INSTANCES = int(os.environ.get("AZ_MIN_INSTANCES", "2"))
DEFAULT_MAX_INSTANCES = int(os.environ.get("AZ_MAX_INSTANCES", "2"))
DEFAULT_IDLE_TIME = int(os.environ.get("AZ_IDLE_SECONDS", "1800"))

# Default batch size (per GPU) and SKU->GPU mapping
DEFAULT_BATCH = int(os.environ.get("DEFAULT_BATCH", "2"))
SKU_GPU_MAP = {
    "Standard_NC16as_T4_v3": 4,
    "Standard_NC8as_T4_v3": 2,
    "Standard_NC6as_T4_v3": 1,
}

def gpus_for_sku(sku: str) -> int:
    return SKU_GPU_MAP.get(sku, 1)

# Training runtime env defaults
DEFAULT_WORK_DIR = os.environ.get("WORK_DIR", None)
DEFAULT_PYTHONPATH = os.environ.get("PYTHONPATH", None)
DEFAULT_MASTER_ADDR = os.environ.get("MASTER_ADDR", "localhost")
DEFAULT_NCCL_DEBUG = os.environ.get("NCCL_DEBUG", "INFO")
DEFAULT_OMP_NUM_THREADS = os.environ.get("OMP_NUM_THREADS", "64")
DEFAULT_OPENBLAS_NUM_THREADS = os.environ.get("OPENBLAS_NUM_THREADS", "1")
DEFAULT_HYDRA_FULL_ERROR = os.environ.get("HYDRA_FULL_ERROR", "1")
DEFAULT_WANDB__SERVICE_WAIT = os.environ.get("WANDB__SERVICE_WAIT", "300")

