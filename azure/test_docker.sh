#!/bin/bash
docker run --rm --gpus all --entrypoint /bin/bash simlingo-training:v1 -c "
source /opt/conda/etc/profile.d/conda.sh && \
conda activate simlingo && \
python -c \"
import sys
errors = []

try:
    import torch
    print('✓ PyTorch:', torch.__version__)
    print('  CUDA available:', torch.cuda.is_available())
except Exception as e:
    errors.append(f'✗ PyTorch: {e}')

try:
    import pytorch_lightning as pl
    print('✓ PyTorch Lightning:', pl.__version__)
except Exception as e:
    errors.append(f'✗ PyTorch Lightning: {e}')

try:
    import transformers
    print('✓ Transformers:', transformers.__version__)
except Exception as e:
    errors.append(f'✗ Transformers: {e}')

try:
    import deepspeed
    print('✓ DeepSpeed:', deepspeed.__version__)
except Exception as e:
    errors.append(f'✗ DeepSpeed: {e}')

try:
    import flash_attn
    print('✓ Flash Attention installed')
except Exception as e:
    errors.append(f'✗ Flash Attention: {e}')

try:
    import hydra
    print('✓ Hydra:', hydra.__version__)
except Exception as e:
    errors.append(f'✗ Hydra: {e}')

try:
    import wandb
    print('✓ Wandb:', wandb.__version__)
except Exception as e:
    errors.append(f'✗ Wandb: {e}')

if errors:
    print('\n--- ERRORS ---')
    for err in errors:
        print(err)
    sys.exit(1)
else:
    print('\n✓ All dependencies installed successfully!')
    print('\nNote: Code (simlingo_base_training) will be mounted at runtime via Azure ML')
\"
"