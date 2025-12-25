#!/bin/bash

source ~/.bashrc
conda activate simlingo

pwd
export WANDB_MODE=offline
export PYTHONPATH="${CARLA_ROOT}/PythonAPI/carla/":${PYTHONPATH}
export WORK_DIR=~/coding/07_simlingo/simlingo_cleanup
export PYTHONPATH=$PYTHONPATH:${WORK_DIR}

export MASTER_ADDR=localhost
export NCCL_DEBUG=INFO

export OMP_NUM_THREADS=64 # Limits pytorch to spawn at most num cpus cores threads
export OPENBLAS_NUM_THREADS=1  # Shuts off numpy multithreading, to avoid threads spawning other threads.
export HYDRA_FULL_ERROR=1  # To get full stack traces on hydra errors
WANDB__SERVICE_WAIT=100 python simlingo_training/train.py experiment=simlingo_seed1 data_module.batch_size=1 gpus=1 name=simlingo_seed1



# source train_simlingo.sh > training_log_wandb_offline.log 2>&1