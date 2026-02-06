# Real-World Data Collection Guide for SimLingo

This document outlines the requirements for collecting real-world driving data compatible with SimLingo's training pipeline.

## Overview

SimLingo is currently trained exclusively on CARLA simulation data. To deploy on real-world scenarios (e.g., Japanese street images), you need to understand the data format and collection requirements.

## Camera Requirements

### Hardware Specifications
Based on CARLA training configuration (`team_code/config.py`):

- **Resolution**: 1024 × 512 pixels (width × height)
- **Field of View (FOV)**: 110 degrees
- **Mounting Position**: 
  - x: -1.5m (behind vehicle center)
  - y: 0.0m (centered laterally)
  - z: 2.0m (height above ground)
- **Orientation**: 
  - Roll: 0.0°
  - Pitch: 0.0°
  - Yaw: 0.0° (facing forward)

### Image Format
- **File Format**: JPEG (`.jpg`)
- **Color Space**: RGB (converted from BGR after cv2 loading)
- **Naming Convention**: Sequential 4-digit numbers (e.g., `0000.jpg`, `0001.jpg`, ...)
- **Preprocessing**: Bottom quarter may be cropped during training to remove vehicle hood

**Note**: SimLingo currently uses **single front-facing camera only**. Multi-camera infrastructure exists in code but is disabled (`num_cameras = [0]` with alternatives commented out).

## Data Collection Frequency

- **Frame Rate**: 20 Hz (20 frames per second)
- **Temporal History**: Model uses 1 historical frame (`hist_len = 1` in training config)
- **Prediction Horizon**: 4 future waypoints (`pred_len = 4`)

## Required Data Per Frame

### 1. RGB Image (`rgb/` folder)
Front-facing camera image matching the specifications above.

### 2. Measurements (`measurements/` folder)
Each frame requires a corresponding `.json.gz` file with:

```json
{
  "speed": 5.2,                          // Vehicle speed in m/s
  "x": 123.45,                           // Global x coordinate
  "y": 67.89,                            // Global y coordinate
  "z": 0.5,                              // Global z coordinate
  "theta": 1.57,                         // Yaw angle in radians
  "target_point": [10.0, 2.0, 0.0],      // Next waypoint in local coords (x, y, z)
  "target_point_next": [15.0, 1.5, 0.0], // Subsequent waypoint in local coords
  "command": 2,                          // Navigation command (see below)
  "waypoints": [                         // Future waypoints for trajectory
    [1.5, 0.0, 0.0],
    [3.0, 0.1, 0.0],
    [4.5, 0.2, 0.0],
    [6.0, 0.3, 0.0]
  ],
  "speed_limit": 30.0,                   // Optional: Speed limit in km/h
  "augmentation_rotation": 0.0,          // Camera augmentation (0.0 for real data)
  "augmentation_translation": 0.0        // Camera augmentation (0.0 for real data)
}
```

### 3. Navigation Commands
Commands follow CARLA's high-level navigation system:
- `0`: Follow lane
- `1`: Turn left
- `2`: Turn right  
- `3`: Go straight
- `4`: Lane change left
- `5`: Lane change right

### 4. Language Annotations (Optional)
For commentary/VQA training, create `language.json` files with:
- **Commentary**: Natural language descriptions of driving scenarios
- **VQA Pairs**: Question-answer pairs about the scene
- **Templates**: Follow format in `data/augmented_templates/commentary_augmented.json`

## Data Directory Structure

```
your_dataset/
└── data/
    └── simlingo/
        └── {collection_name}/
            └── {date}/
                └── {run_id}/
                    └── Town01/  # or your location name
                        ├── rgb/
                        │   ├── 0000.jpg
                        │   ├── 0001.jpg
                        │   └── ...
                        ├── measurements/
                        │   ├── 0000.json.gz
                        │   ├── 0001.json.gz
                        │   └── ...
                        ├── language.json  # Optional
                        └── results.json   # Optional route completion info
```

## Coordinate Systems

### Global Coordinates
- World frame position of the vehicle (x, y, z, theta)

### Local Coordinates
- **Origin**: Vehicle's current position
- **X-axis**: Forward direction (aligned with vehicle heading)
- **Y-axis**: Left direction (perpendicular to heading)
- **Z-axis**: Upward direction
- **Waypoints**: All waypoints are in local vehicle frame

### Coordinate Transformation
The model expects waypoints in the vehicle's local frame. To convert from global to local:

```python
# Pseudo-code for transformation
dx = waypoint_global_x - vehicle_x
dy = waypoint_global_y - vehicle_y
waypoint_local_x = dx * cos(vehicle_theta) + dy * sin(vehicle_theta)
waypoint_local_y = -dx * sin(vehicle_theta) + dy * cos(vehicle_theta)
```

## Key Differences: Simulation vs. Real World

| Aspect | CARLA Simulation | Real World |
|--------|-----------------|------------|
| Ground Truth | Perfect sensor data | Noisy, requires calibration |
| Waypoints | From route planner | Need GPS/SLAM + path planning |
| Scene Understanding | Semantic labels available | Must infer from vision |
| Safety | Can crash without consequence | Critical safety requirements |
| Weather/Lighting | Controlled | Variable, challenging conditions |

## Domain Gap Challenges

SimLingo is trained **exclusively on CARLA simulation data**. Deploying on real-world images faces:

1. **Visual Domain Gap**: 
   - Simulation textures vs. real-world appearance
   - Lighting differences (CARLA has simplified lighting)
   - Lack of real-world artifacts (lens distortion, motion blur, etc.)

2. **Behavioral Differences**:
   - CARLA traffic follows scripted patterns
   - Real-world driving is more unpredictable
   - Pedestrian and vehicle behaviors differ

3. **Missing Training Signals**:
   - Model never saw real-world street signs
   - Japanese text/signage not in CARLA training data
   - Different road markings and infrastructure

## Recommendations for Real-World Deployment

### For Inference Only (Current Capability)
- Collect images matching camera specifications
- Provide dummy/estimated measurements if exact ground truth unavailable
- Expect reduced performance due to domain gap
- Use primarily for visualization and qualitative evaluation

### For Fine-Tuning (Recommended Approach)
1. **Collect Real-World Dataset**: Follow this guide's data format
2. **Obtain Ground Truth**: Use GPS, IMU, and calibrated odometry
3. **Add Real Data to Training**: Mix with CARLA data using `data_path` config
4. **Fine-Tune Model**: Continue training from CARLA checkpoint
5. **Iterative Improvement**: Collect failure cases and retrain

### Safety Considerations
⚠️ **DO NOT deploy SimLingo in safety-critical scenarios without**:
- Extensive real-world testing
- Validated safety drivers
- Redundant safety systems
- Domain adaptation training
- Regulatory compliance

## Tools and Scripts

- **Inference on Images**: `team_code/test_japan_streets_simple.py`
- **Trajectory Visualization**: `team_code/inference.py`
- **Dataset Processing**: `dataset_generation/` utilities

## References

- Training configuration: `team_code/config.py`
- Dataset loader: `simlingo_training/dataloader/dataset_base.py`
- Agent implementation: `team_code/agent_simlingo.py`
- CARLA documentation: https://carla.readthedocs.io/
