#!/bin/bash

MODEL="/workspace/vla_data_generation/Qwen3VL-32B-Instruct-Q4_K_M.gguf"
MMPROJ="/workspace/vla_data_generation/mmproj-Qwen3VL-32B-Instruct-F16.gguf"
IMAGE="/workspace/vla_data_generation/inference/example_images/image_0005.png"

# Define the prompt clearly
PROMPT="<|im_start|>user
<|image|>
Analyze this first-person driving scene for a Vision-Language-Action (VLA) dataset.
Provide a concise response following this exact format:

1. Environment: List key objects (pedestrians, traffic lights, vehicles) and their relative positions.
2. Reasoning: Briefly explain the immediate risks or navigation requirements.
3. Action: A single sentence describing exactly what the car should do next.

Target Output Style: \"Reasoning: A pedestrian is entering the crosswalk from the right. Action: Apply brakes firmly and wait for the pedestrian to clear the lane.\"<|im_end|>
<|im_start|>assistant"

./build/bin/llama-cli \
    --model "$MODEL" \
    --mmproj "$MMPROJ" \
    --image "$IMAGE" \
    --threads 16 \
    --ctx-size 8192 \
    --n-gpu-layers 100 \
    --prompt "$PROMPT"