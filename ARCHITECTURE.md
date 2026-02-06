# SimLingo: Detailed Architecture Documentation

This document provides comprehensive technical details about the SimLingo model architecture, training pipeline, and inference process.

## Table of Contents
1. [Model Overview](#model-overview)
2. [Vision Processing Pipeline](#vision-processing-pipeline)
3. [Language Model Integration](#language-model-integration)
4. [Training Architecture](#training-architecture)
5. [Waypoint Prediction](#waypoint-prediction)
6. [Data Loading Pipeline](#data-loading-pipeline)
7. [Inference Process](#inference-process)

---

## Model Overview

SimLingo is a **Vision-Language-Action (VLA) model** for autonomous driving that combines:
- **Vision Encoder**: InternVL2 (ViT-based patch embeddings)
- **Language Model**: Qwen2.5-1.5B-Instruct (decoder-only transformer)
- **Fine-Tuning Method**: LoRA (Low-Rank Adaptation) for parameter efficiency
- **Output Head**: MLP for waypoint regression

### Key Statistics
- **Total Parameters**: ~1.5 billion
- **Trainable Parameters**: 2.72% (via LoRA)
- **Input Modalities**: RGB images + text prompts
- **Output**: 4 future waypoints (x, y, z) + speeds

---

## Vision Processing Pipeline

### InternVL2 Image Tokenization

SimLingo uses InternVL2's vision encoder to convert images into token embeddings:

#### 1. Patch Extraction
```
Input Image: [3, H, W] RGB image
↓
Patch Division: 16×16 pixel patches
↓
Patch Grid: [H/16, W/16] patches
Example: 1024×512 image → 64×32 = 2048 patches
```

However, SimLingo uses **dynamic preprocessing** that adaptively splits images into 1-12 sub-images based on aspect ratio, resulting in variable patch counts.

#### 2. Patch Embedding Process

**Per-Patch Processing:**
```python
# Each 16×16 patch has:
16 × 16 pixels × 3 channels = 768 values

# Linear projection:
patch_values: [768] → Linear layer → embedding: [3200]
```

**Typical Configuration** (for standard 1024×512 input):
```
Number of patches: ~784 (after dynamic preprocessing)
Embedding per patch: 3200 dimensions
Total vision tokens: [784, 3200]
```

#### 3. Vision Encoder Architecture
```
Vision Encoder (InternVL2):
  ├─ Patch Embedding: Linear(768 → 3200)
  ├─ Position Encoding: Learnable 2D positional embeddings
  ├─ Transformer Blocks: Multi-head self-attention layers
  └─ Output: Vision token sequence [num_patches, 3200]
```

### Image Preprocessing

**Data Augmentation** (training only):
- Random brightness/contrast adjustment
- Color jittering
- Optional: Camera position/rotation augmentation (commented in current config)

**Bottom Crop**:
```python
# Remove vehicle hood from bottom of image
crop_ratio = 4.8 / 16  # Empirical value
cropped_height = original_height - (original_height × crop_ratio)
# Applied to 1024×512 → 1024×358 effective region
```

**Normalization**:
```python
# ImageNet normalization (if enabled)
mean = [0.485, 0.456, 0.406]
std = [0.229, 0.224, 0.225]
```

---

## Language Model Integration

### Qwen2.5-1.5B-Instruct

SimLingo uses Qwen2.5-1.5B as the language backbone:

#### Model Specifications
- **Architecture**: Decoder-only transformer (GPT-style)
- **Vocabulary Size**: ~151,000 tokens (BPE tokenizer)
- **Context Length**: 32,768 tokens maximum
- **Hidden Dimension**: 3200 (matches vision embedding dimension)

#### Tokenization Process

**Text Input:**
```python
prompt = "Current speed: 5.2 m/s. Command: Turn right. Predict waypoints."
↓
Tokenizer (BPE): [token_id_1, token_id_2, ..., token_id_n]
↓
Embedding Layer: [n, 3200]
```

**Combined Input to LLM:**
```
Sequence: [vision_tokens] + [text_tokens]
Shape: [784 + n, 3200]
Example: [784 vision tokens, 20 text tokens] → [804, 3200]
```

### Prompt Construction

**Template** (from `agent_simlingo.py` lines 550-563):
```python
def create_prompt(speed, command):
    command_text = {
        0: "Follow lane",
        1: "Turn left", 
        2: "Turn right",
        3: "Go straight",
        4: "Change lane left",
        5: "Change lane right"
    }[command]
    
    return f"Current speed: {speed:.1f} m/s. Command: {command_text}. Predict waypoints."
```

**Alternative Prompts** (training variations):
- Commentary mode: "Describe the driving scenario."
- VQA mode: "Question: {question}\nAnswer:"
- DriveVLM commands: Template-based navigational instructions

---

## Training Architecture

### Model Structure

```
SimLingo Model (simlingo_training/models/simlingo_model.py):
│
├─ Vision Encoder (InternVL2)
│  ├─ Frozen base model
│  └─ LoRA adapters on attention layers
│
├─ Language Model (Qwen2.5-1.5B)
│  ├─ Frozen base model  
│  └─ LoRA adapters (r=64, α=16, dropout=0.05)
│
└─ Task Heads
   ├─ Waypoint Head: MLP [3200 → 2048 → 1024 → 3×pred_len]
   └─ Speed Head: MLP [3200 → 2048 → 1024 → pred_len]
```

### LoRA Configuration

**LoRA Hyperparameters:**
```yaml
lora_r: 64              # Rank of low-rank matrices
lora_alpha: 16          # Scaling factor (α/r = 0.25)
lora_dropout: 0.05      # Dropout on LoRA layers
target_modules:         # Which layers to adapt
  - q_proj              # Query projection
  - v_proj              # Value projection
  - k_proj              # Key projection (optional)
  - o_proj              # Output projection (optional)
```

**Memory Efficiency:**
- Full model: ~1.5B parameters
- LoRA only: ~41M trainable parameters (2.72%)
- Allows training on single GPU (24GB+ VRAM)

### Loss Functions

**Multi-Task Learning:**
```python
# Waypoint L1 Loss
loss_wp = L1Loss(predicted_waypoints, ground_truth_waypoints)

# Speed L1 Loss  
loss_speed = L1Loss(predicted_speeds, ground_truth_speeds)

# Language Modeling Loss (optional)
loss_lm = CrossEntropyLoss(token_predictions, token_targets)

# Total Loss
loss = λ_wp * loss_wp + λ_speed * loss_speed + λ_lm * loss_lm
# Default weights: λ_wp=1.0, λ_speed=0.1, λ_lm=1.0
```

### Training Configuration

**Optimizer:**
```yaml
optimizer: AdamW
learning_rate: 1e-4
weight_decay: 0.01
betas: [0.9, 0.999]
```

**Learning Rate Schedule:**
```yaml
scheduler: CosineAnnealingLR
warmup_steps: 500
max_steps: 100000
min_lr: 1e-6
```

**Batch Configuration:**
```yaml
batch_size: 4           # Per GPU
gradient_accumulation: 4
effective_batch_size: 16
num_workers: 8
```

**Hardware:**
- Single NVIDIA GPU (A100/V100 recommended)
- Mixed precision (FP16) training
- Gradient checkpointing for memory efficiency

---

## Waypoint Prediction

### Waypoint Head Architecture

**NOT decoded from language tokens** - uses dedicated MLP head:

```python
class WaypointHead(nn.Module):
    def __init__(self, hidden_dim=3200, pred_len=4):
        super().__init__()
        self.mlp = nn.Sequential(
            nn.Linear(3200, 2048),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(2048, 1024),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(1024, pred_len * 3)  # 4 waypoints × (x,y,z)
        )
    
    def forward(self, hidden_states):
        # Extract last token embedding
        last_hidden = hidden_states[:, -1, :]  # [batch, 3200]
        
        # Predict waypoints
        waypoints_flat = self.mlp(last_hidden)  # [batch, 12]
        waypoints = waypoints_flat.reshape(-1, 4, 3)  # [batch, 4, 3]
        
        return waypoints
```

### Waypoint Format

**Output Shape:** `[batch_size, 4, 3]`

**Interpretation:**
```python
waypoints = [
    [x1, y1, z1],  # 1st future waypoint (0.5s ahead)
    [x2, y2, z2],  # 2nd future waypoint (1.0s ahead)
    [x3, y3, z3],  # 3rd future waypoint (1.5s ahead)
    [x4, y4, z4],  # 4th future waypoint (2.0s ahead)
]
```

**Coordinate System:**
- Origin: Vehicle's current position
- X-axis: Forward (vehicle's heading direction)
- Y-axis: Left (perpendicular to heading)
- Z-axis: Up
- Units: Meters

**Temporal Spacing:**
- At 20 Hz data collection: 0.5 second intervals
- Covers 2 seconds of future trajectory

---

## Data Loading Pipeline

### Dataset Class Hierarchy

```
BaseDataset (dataset_base.py)
├─ Data_Driving (dataset_driving.py) - Waypoint prediction
├─ Data_Dreamer (dataset_dreamer.py) - Alternative trajectories
└─ Data_Eval_* - Evaluation datasets
```

### Loading Process

**Step 1: Route Discovery**
```python
route_dirs = glob.glob(f"{data_path}/data/simlingo/*/*/*/Town*")
# Finds all routes in dataset
# Example: /data/simlingo/v2_2025_01_10/20250110/run_001/Town01/
```

**Step 2: Frame Extraction**
```python
for seq in range(skip_first_n_frames, num_frames - pred_len - hist_len - 1):
    # Load RGB image
    image_path = f"{route_dir}/rgb/{seq:04d}.jpg"
    
    # Load measurements
    measurement_path = f"{route_dir}/measurements/{seq:04d}.json.gz"
    
    # Load language (optional)
    language_path = f"{route_dir}/language.json"
```

**Step 3: Data Augmentation**
```python
# Image augmentation (50% probability)
if random.random() < 0.5:
    image = augment_brightness_contrast(image)
    image = augment_color_jitter(image)

# Camera position augmentation (if enabled)
if use_shifted_camera:
    image = load_from_rgb_augmented_folder(image_path)
    translation = measurement['augmentation_translation']
    rotation = measurement['augmentation_rotation']
    waypoints = adjust_for_camera_shift(waypoints, translation, rotation)
```

### DataLoader Configuration

```yaml
train_dataloader:
  batch_size: 4
  num_workers: 8
  shuffle: True
  pin_memory: True
  persistent_workers: True
  
val_dataloader:
  batch_size: 4
  num_workers: 4
  shuffle: False
```

### Dataset Output Structure

```python
@dataclass
class DatasetOutput:
    rgb: torch.Tensor              # [T, C, H, W] - Image
    waypoints: torch.Tensor        # [pred_len, 3] - Future waypoints
    speed: float                   # Current speed
    target_points: torch.Tensor    # [2, 3] - Navigation targets
    command: int                   # High-level command
    prompt: str                    # Text prompt
    measurement_path: str          # Path to measurement file
```

---

## Inference Process

### Agent Run Step

**Main Loop** (`agent_simlingo.py::run_step()`):
```python
def run_step(self, input_data, timestamp):
    # 1. Initialize on first call
    if not self.initialized:
        self._init()
        return default_control()
    
    # 2. Preprocess sensor data
    rgb = input_data['rgb_0'][1][:, :, :3]  # Extract RGB from BGRA
    
    # 3. Update route planner
    self._route_planner.run_step(gps)
    
    # 4. Create model input
    driving_input = self.tick(rgb, gps, speed, compass)
    
    # 5. Model forward pass
    with torch.no_grad():
        predictions = self.model(
            pixel_values=driving_input.pixel_values,
            input_ids=driving_input.input_ids,
            attention_mask=driving_input.attention_mask
        )
    
    # 6. Extract waypoints
    waypoints = predictions.waypoints[0].cpu().numpy()  # [4, 3]
    
    # 7. PID control
    control = self.control_pid(waypoints, speed)
    
    return control
```

### Preprocessing (`tick()` method)

**Image Processing:**
```python
# Resize to model input size
image = cv2.resize(rgb, (1024, 512))

# Dynamic preprocessing (InternVL2)
pixel_values, num_patches = dynamic_preprocess(
    image,
    min_num=1,
    max_num=12,
    image_size=448  # InternVL2 base resolution
)

# Shape: [num_patches, 3, 448, 448]
```

**Prompt Construction:**
```python
# Get navigation command
command = route_planner.get_command()

# Create prompt
prompt = f"Current speed: {speed:.1f} m/s. Command: {command_text}. Predict waypoints."

# Tokenize
input_ids = tokenizer.encode(prompt)
attention_mask = [1] * len(input_ids)
```

### PID Control (`control_pid()` method)

**Waypoint Following:**
```python
def control_pid(self, waypoints, speed):
    # 1. Select aim point (typically 1-2 meters ahead)
    aim_wp = waypoints[1]  # Second waypoint
    
    # 2. Calculate steering angle
    angle = np.arctan2(aim_wp[1], aim_wp[0])
    steer = self.turn_controller(angle, speed)
    
    # 3. Calculate target speed from waypoint distance
    target_speed = calculate_speed(waypoints)
    
    # 4. Longitudinal control
    if speed < target_speed:
        throttle = self.speed_controller(target_speed - speed)
        brake = 0.0
    else:
        throttle = 0.0
        brake = self.brake_controller(speed - target_speed)
    
    return carla.VehicleControl(
        steer=np.clip(steer, -1.0, 1.0),
        throttle=np.clip(throttle, 0.0, 1.0),
        brake=np.clip(brake, 0.0, 1.0)
    )
```

**PID Parameters:**
```python
# Lateral control (steering)
turn_kp = 1.0
turn_ki = 0.75
turn_kd = 0.3

# Longitudinal control (speed)
speed_kp = 5.0
speed_ki = 0.5
speed_kd = 1.0

# Brake control
brake_kp = 0.5
```

---

## Camera Configuration

### Current Setup

**Single Camera System:**
```yaml
num_cameras: [0]        # Only camera 0 active
                        # Multi-camera commented: [0, 1, 2, 3]

camera_0:
  position: [-1.5, 0.0, 2.0]    # x, y, z in meters
  rotation: [0.0, 0.0, 0.0]      # roll, pitch, yaw in degrees
  width: 1024
  height: 512
  fov: 110                        # degrees
```

**Multi-Camera Infrastructure** (exists but disabled):
```python
# Code supports multiple cameras:
for num_cam in self.config.num_cameras:
    sensors.append({
        'type': 'sensor.camera.rgb',
        'id': f'rgb_{num_cam}',
        # ... camera params from config
    })

# But current config only uses camera 0
# To enable: num_cameras = [0, 1, 2, 3]
```

### Camera Augmentation (Training)

**Positional Augmentation:**
```yaml
camera_translation_augmentation_min: -1.5  # meters left/right
camera_translation_augmentation_max: 1.5
camera_rotation_augmentation_min: -20.0    # degrees yaw
camera_rotation_augmentation_max: 20.0

img_shift_augmentation_prob: 0.5           # 50% chance to use augmented view
```

**Purpose:** Improves robustness to camera placement variations

---

## Training Data Requirements

### Minimum Dataset Size

**For Fine-Tuning:**
- Recommended: 100,000+ frames
- Minimum: 10,000+ frames for basic adaptation
- Per route: ~1000-3000 frames (50-150 seconds at 20Hz)

### Data Quality Checklist

✅ **Image Quality:**
- [ ] Resolution: 1024×512 or higher
- [ ] No motion blur
- [ ] Consistent lighting (no sudden exposure changes)
- [ ] Valid JPEG files

✅ **Measurements:**
- [ ] Synchronized with images (same timestamp)
- [ ] Valid speed readings (m/s)
- [ ] Accurate waypoints in vehicle frame
- [ ] Navigation commands consistent with route

✅ **Route Quality:**
- [ ] No infractions (stay in lane, follow traffic rules)
- [ ] Route completion >95%
- [ ] Diverse scenarios (turns, lanes, speeds)

### Data Distribution

**Recommended Mix:**
```
40% - Straight roads (follow lane)
20% - Left turns
20% - Right turns
10% - Lane changes
10% - Complex intersections
```

**Speed Distribution:**
```
30% - Low speed (0-10 m/s, urban)
40% - Medium speed (10-20 m/s, suburban)
30% - High speed (20-30 m/s, highway)
```

---

## File Locations Reference

### Configuration Files
- Main config: `team_code/config.py`
- SimLingo config: `team_code/config_simlingo.py`
- Base config: `team_code/config_simlingo_base.py`
- Training config: `simlingo_training/config/`

### Model Files
- Model definition: `simlingo_training/models/simlingo_model.py`
- Agent implementation: `team_code/agent_simlingo.py`
- Inference script: `team_code/test_japan_streets_simple.py`
- Visualization: `team_code/inference.py`

### Data Loading
- Base dataset: `simlingo_training/dataloader/dataset_base.py`
- Driving dataset: `simlingo_training/dataloader/dataset_driving.py`
- DataModule: `simlingo_training/dataloader/datamodule.py`

### Training Scripts
- Main training: `simlingo_training/train.py`
- Evaluation: `simlingo_training/eval.py`
- Metrics: `simlingo_training/eval_metrics.py`

### Utilities
- Projection: `simlingo_training/utils/projection.py`
- Types: `simlingo_training/utils/custom_types.py`
- Dataset generation: `dataset_generation/`

---

## Common Misconceptions

❌ **"Waypoints are decoded as text from the language model"**
- ✅ **Correct:** Waypoints come from a dedicated MLP regression head

❌ **"SimLingo uses multi-camera input"**
- ✅ **Correct:** Only single front-facing camera (multi-camera code exists but is disabled)

❌ **"Each image patch has 3200 values"**
- ✅ **Correct:** Each 16×16×3 patch has 768 pixel values, projected to 3200-dim embedding

❌ **"Model was trained on real-world data"**
- ✅ **Correct:** Trained exclusively on CARLA simulation data

---

## Additional Resources

- **InternVL2 Paper:** [arXiv:2405.xxxxx](https://arxiv.org/)
- **Qwen2.5 Docs:** https://github.com/QwenLM/Qwen2.5
- **CARLA Simulator:** https://carla.readthedocs.io/
- **LoRA Paper:** "LoRA: Low-Rank Adaptation of Large Language Models"

---

**Last Updated:** Based on repository state as of conversation
**Verified Against:** `/workspace/simlingo-kohei/` codebase
