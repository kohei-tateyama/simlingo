# import os
# import subprocess

# # Set environment variables
# os.environ['PYTHONPATH'] = f"{os.environ.get('CARLA_ROOT', '')}/PythonAPI/carla/:{os.environ.get('PYTHONPATH', '')}"
# os.environ['WORK_DIR'] = os.getcwd()
# os.environ['PYTHONPATH'] = f"{os.environ['PYTHONPATH']}:{os.environ['WORK_DIR']}"
# os.environ['MASTER_ADDR'] = 'localhost'
# os.environ['NCCL_DEBUG'] = 'INFO'
# os.environ['OMP_NUM_THREADS'] = '64'
# os.environ['OPENBLAS_NUM_THREADS'] = '1'
# os.environ['HYDRA_FULL_ERROR'] = '1'
# os.environ['WANDB__SERVICE_WAIT'] = '100'

# # Run training
# cmd = [
#     'python', 'simlingo_training/train.py',
#     'experiment=simlingo_seed1',
#     'data_module.batch_size=1',
#     'gpus=1',
#     'name=simlingo_seed1'
# ]

# subprocess.run(cmd, check=True)

#!/usr/bin/env python
import os
import sys
import subprocess
from pathlib import Path

# Run from project root
proj_root = Path(__file__).resolve().parent.parent
os.chdir(proj_root)

# Set up environment variables
os.environ["WORK_DIR"] = str(proj_root)
os.environ["PYTHONPATH"] = f"{os.environ['WORK_DIR']}:{os.environ.get('PYTHONPATH', '')}"
os.environ.setdefault("MASTER_ADDR", "localhost")
os.environ.setdefault("NCCL_DEBUG", "INFO")
os.environ.setdefault("OMP_NUM_THREADS", "64")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("HYDRA_FULL_ERROR", "1")
os.environ.setdefault("WANDB__SERVICE_WAIT", "300")

print("=" * 60)
print("SimLingo Training on Azure ML")
print("=" * 60)
print(f"Working dir: {os.getcwd()}")
print(f"Python: {sys.version}")
print(f"PYTHONPATH: {os.environ.get('PYTHONPATH')}")

# Check CUDA availability
print("\nCUDA Check:", end=" ")
try:
    import torch
    print(f"Available={torch.cuda.is_available()}, Devices={torch.cuda.device_count()}")
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            print(f"  GPU {i}: {torch.cuda.get_device_name(i)}")
except Exception as e:
    print(f"torch import failed: {e}")
    sys.exit(1)

# Get training parameters from environment or use defaults
batch_size = int(os.environ.get("BATCH_SIZE", "8"))
num_gpus = int(os.environ.get("NUM_GPUS", torch.cuda.device_count() if torch.cuda.is_available() else 1))
experiment_name = os.environ.get("EXPERIMENT_NAME", "simlingo_seed1")
job_name = os.environ.get("JOB_NAME", "simlingo_azure")

print(f"\nTraining Configuration:")
print(f"  Experiment: {experiment_name}")
print(f"  Job Name: {job_name}")
print(f"  Batch Size: {batch_size}")
print(f"  GPUs: {num_gpus}")
print("=" * 60)

# Build training command
cmd = [
    sys.executable, "simlingo_training/train.py",
    f"experiment={experiment_name}",
    f"data_module.batch_size={batch_size}",
    f"gpus={num_gpus}",
    f"name={job_name}",
]

print(f"\nRunning: {' '.join(cmd)}\n")
env = os.environ.copy()
try:
    subprocess.run(cmd, check=True, env=env)
    print("\nTraining completed successfully!")
except subprocess.CalledProcessError as e:
    print(f"\nTraining failed with exit code {e.returncode}")
    sys.exit(e.returncode)