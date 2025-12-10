# Telemetry Monitoring - FAQ & Solutions

## Your Questions Answered

### 1. ✅ Running `understand_carla_api.py` Without Arguments

**FIXED!** Now you can just run:
```bash
python team_code/understand_carla_api.py
```

**What I fixed:**
- Removed environment variable parsing that caused errors
- Set sensible defaults:
  - `--steps 999999` (runs indefinitely until Ctrl+C)
  - `--dt 0.1` (10 Hz sampling, faster than before for better resolution)
  - `--host localhost --port 2000` (standard CARLA defaults)

### 2. ✅ Position is Already in Meters

**CLARIFIED:** CARLA uses meters as the default unit for all positions.
- Position `[x, y, z]` is already in meters
- Added comment in code to make this clear
- Display now shows `X=1234.56m` to emphasize units

### 3. ✅ Plot Position Output

**FIXED!** Enhanced plotting with:
- **Trajectory plot** (top-down 2D view with start/end markers)
- **Control inputs plot** (steering and throttle over time)
- Plots saved to: `/workspace/simlingo/team_code/dummy_carla_plot/`
  - `vehicle_trajectory.png` - Your vehicle's path
  - `control_inputs.png` - Steering and throttle timeline

**Plots are saved:**
- When script finishes normally
- When you press Ctrl+C
- After any error

### 4. ⚠️ Why Script Stops While `how_to_run_headless.sh` Runs

**ANSWER:** The script stops when it reaches the `--steps` limit (default was 200, now 999999).

**Two scenarios:**
1. **Script reaches step limit** - Increase with `--steps 999999999`
2. **Vehicle disappears** - Happens when route finishes or scenario ends

**Solution:**
```bash
# Run indefinitely
python team_code/understand_carla_api.py --steps 999999999
```

The script now waits for vehicles to reappear if they despawn between routes.

### 5. 🐌 CARLA Simulation is Slow

**ANSWER:** This is a known issue with CARLA + heavy AI models. Several factors:

**Root causes:**
- **GPU bottleneck**: CARLA rendering + Agent neural network both use GPU
- **Agent inference time**: InternVL2 model is slow (multiple seconds per frame)
- **Synchronous mode**: Agent waits for each frame before continuing

**Solutions to try:**

#### A. Reduce Agent Model Size (Best option)
In your agent config, use a smaller variant:
```python
model.vision_model.variant = "OpenGVLab/InternVL2-1B"  # Currently using this
# Or try even smaller if available
```

#### B. Reduce CARLA Rendering Quality
Add to Docker run command in `how_to_run_headless.sh`:
```bash
./CarlaUE4.sh -RenderOffScreen -nosound -world-port=2000 -quality-level=Low
```

#### C. Reduce Image Resolution
In agent config, reduce camera resolution:
```python
camera_width = 800  # Instead of 1600
camera_height = 600  # Instead of 1200
```

#### D. Increase Time Budget (If simulation is too slow, scenarios timeout)
In leaderboard evaluator arguments, add:
```bash
--timeout 600  # Give more time before timeout
```

**What you can measure:**
- Check agent logs for frame rate (shown as "Ratio = 0.038x" means 38ms per frame)
- Telemetry sampling at 10Hz should show if agent is keeping up

### 6. ❌ Ctrl+C Trap Doesn't Work in `how_to_run_headless.sh`

**ANSWER:** The leaderboard evaluator captures Ctrl+C itself and has a bug in the agent cleanup (`agent_simlingo.py` line 868).

**The problem:**
```python
# In agent_simlingo.py line 868 - destroy() method
if self.cfg.data_module.encoder == 'llavanext':  # ← Missing key 'encoder'
```

**Solutions:**

#### Option A: Fix the agent destroy() method (Recommended)
Add this defensive check to `team_code/agent_simlingo.py` line 868:
```python
# Old (line 868):
if self.cfg.data_module.encoder == 'llavanext':

# New:
if hasattr(self.cfg, 'data_module') and hasattr(self.cfg.data_module, 'encoder') and self.cfg.data_module.encoder == 'llavanext':
```

#### Option B: Force kill from another terminal
While running, from another terminal:
```bash
# Kill agent evaluator
pkill -9 -f leaderboard_evaluator.py

# Stop CARLA
docker rm -f carla-server

# Kill telemetry monitor
pkill -9 -f understand_carla_api.py
```

#### Option C: Use timeout command
Wrap the evaluation in `how_to_run_headless.sh` with timeout:
```bash
timeout 3600 python Bench2Drive/leaderboard/leaderboard/leaderboard_evaluator.py \
    ...
```

**Why it happens:**
The leaderboard evaluator catches SIGINT and tries to cleanup the agent by calling `agent_instance.destroy()`, but the destroy method has a bug accessing a missing config key.

## Quick Reference

### Run Telemetry Monitor (Default - Readable Output)
```bash
cd /workspace/simlingo
conda activate simlingo
python team_code/understand_carla_api.py
```

### Run with JSON Output (For Logging)
```bash
python team_code/understand_carla_api.py --json | tee outputs/test_run/telemetry.jsonl
```

### Run with Faster Sampling
```bash
python team_code/understand_carla_api.py --dt 0.05  # 20 Hz sampling
```


## Telemetry Output

```
================================================================================

[INFO]: EGO VEHICLE STATE @ 2025-12-09 13:44:37
        ID: 4707 | Role: hero
        Position : X=-4201.75m Y= 4329.69m Z=  174.87m
        Control  :
                Steer=-0.001 | Throttle=0.387 | Brake=0.000 | HBrake=False | Rev=False
        Heading  :   0.56°
        Speed    :  10.06 m/s  ( 36.21 km/h)
  Accel:      0.28 m/s²
```

**Run agent and monitor telemetry in parallel:**
   - Terminal 1: `./how_to_run_headless.sh`
   - Terminal 2: `python team_code/understand_carla_api.py`
   - Terminal 2: `pkill -9 -f leaderboard_evaluator.py`

