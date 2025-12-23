import os
import sys
import subprocess
from pathlib import Path
from azure_deploy_mp.config import (
    PRINT_STUFF,
    DEFAULT_WORK_DIR,
    DEFAULT_PYTHONPATH,
    DEFAULT_MASTER_ADDR,
    DEFAULT_NCCL_DEBUG,
    DEFAULT_OMP_NUM_THREADS,
    DEFAULT_OPENBLAS_NUM_THREADS,
    DEFAULT_HYDRA_FULL_ERROR,
    DEFAULT_WANDB__SERVICE_WAIT,
)

proj_root = Path(__file__).resolve().parent.parent
os.chdir(proj_root)

# Set up environment variables (allow overrides via env)
if DEFAULT_WORK_DIR:
    os.environ.setdefault("WORK_DIR", DEFAULT_WORK_DIR)
else:
    os.environ.setdefault("WORK_DIR", str(proj_root))

if DEFAULT_PYTHONPATH:
    os.environ.setdefault("PYTHONPATH", DEFAULT_PYTHONPATH + ":" + os.environ.get('PYTHONPATH', ''))
else:
    os.environ.setdefault("PYTHONPATH", f"{os.environ['WORK_DIR']}:{os.environ.get('PYTHONPATH', '')}")

os.environ.setdefault("MASTER_ADDR", DEFAULT_MASTER_ADDR)
os.environ.setdefault("NCCL_DEBUG", DEFAULT_NCCL_DEBUG)
os.environ.setdefault("OMP_NUM_THREADS", DEFAULT_OMP_NUM_THREADS)
os.environ.setdefault("OPENBLAS_NUM_THREADS", DEFAULT_OPENBLAS_NUM_THREADS)
os.environ.setdefault("HYDRA_FULL_ERROR", DEFAULT_HYDRA_FULL_ERROR)
os.environ.setdefault("WANDB__SERVICE_WAIT", DEFAULT_WANDB__SERVICE_WAIT)

print("=" * PRINT_STUFF)
print("[INFO]: SimLingo Training on Azure ML")
print("=" * PRINT_STUFF)
print(f"Working dir : {os.getcwd()}")
print(f"Python      : {sys.version}")
print(f"PYTHONPATH  : {os.environ.get('PYTHONPATH')}")
print("=" * PRINT_STUFF)

print("[INFO]: CUDA Check:", end=" ")
try:
    import torch
    print(f"Available={torch.cuda.is_available()}, Devices={torch.cuda.device_count()}")
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            print(f"GPU {i}: {torch.cuda.get_device_name(i)}")
except Exception as e:
    print(f"[WARNING]: torch import failed: {e}")
    sys.exit(1)

# Get training parameters from environment or use defaults; prefer environment variables
from azure_deploy_mp.config import DEFAULT_BATCH, DEFAULT_SKU, gpus_for_sku

batch_size = int(os.environ.get("BATCH_SIZE", str(DEFAULT_BATCH)))
# Resolve NUM_GPUS: explicit env var > detected CUDA devices > SKU mapping
if "NUM_GPUS" in os.environ:
    num_gpus = int(os.environ.get("NUM_GPUS"))
elif torch.cuda.is_available():
    num_gpus = torch.cuda.device_count()
else:
    compute_sku_env = os.environ.get("AZ_COMPUTE_SKU", DEFAULT_SKU)
    num_gpus = gpus_for_sku(compute_sku_env)

experiment_name = os.environ.get("EXPERIMENT_NAME", "simlingo_seed1")
job_name = os.environ.get("JOB_NAME", "simlingo_azure")

print("=" * PRINT_STUFF)
print(f"[INFO]: Training Configuration:")
print(f"Experiment : {experiment_name}")
print(f"Job Name   : {job_name}")
print(f"Batch Size : {batch_size}")
print(f"GPUs       : {num_gpus}")
print("=" * PRINT_STUFF)

# Build training command
cmd = [
    sys.executable, "simlingo_training/train.py",
    f"experiment={experiment_name}",
    f"data_module.batch_size={batch_size}",
    f"gpus={num_gpus}",
    f"name={job_name}",
]

print(f"[INFO]: Running: {' '.join(cmd)}\n")
print("=" * PRINT_STUFF)
env = os.environ.copy()
try:
    subprocess.run(cmd, check=True, env=env)
    print("[INFO]: Training completed successfully!")
except subprocess.CalledProcessError as e:
    print(f"[ERROR]: Training failed with exit code {e.returncode}")
    sys.exit(e.returncode)