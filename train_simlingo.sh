#!/bin/bash

source ~/.bashrc

pwd
export PYTHONPATH="${CARLA_ROOT}/PythonAPI/carla/":${PYTHONPATH}
export WORK_DIR=~/coding/07_simlingo/simlingo_cleanup
export PYTHONPATH=$PYTHONPATH:${WORK_DIR}

export MASTER_ADDR=localhost
export NCCL_DEBUG=INFO

export OMP_NUM_THREADS=64 # Limits pytorch to spawn at most num cpus cores threads
export OPENBLAS_NUM_THREADS=1  # Shuts off numpy multithreading, to avoid threads spawning other threads.
WANDB__SERVICE_WAIT=10 python simlingo_training/train.py experiment=simlingo_seed1 data_module.batch_size=8 gpus=1 name=simlingo_seed1
