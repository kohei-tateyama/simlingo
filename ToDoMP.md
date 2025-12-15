# Michele ToDo lists into the simlingo

This is a `.md` file to I remeber what to do next.

## Checklist

Use the checklist below to track progress on finishing `japanese_driving_autopilot.py`. Check an item by changing `- [ ]` to `- [x]`.

- [x] Change the per-frame JSON output format to match training dataset (gzipped per-frame files `measurements/0000.json.gz` and `boxes/0000.json.gz`, plus top-level `records.json.gz` and `results.json.gz`).
- [x] Save up to 6 images per timestep into `rgb/` (names `0000.jpg` .. `0007.jpg`), and merge those implement multiple cameras producing those images.
- [ ] Move all the `.sh` into a folder `scripts/`
- [ ] Create multiple autonomous path to collect data from CARLA. 
- [ ] Think of a way to insert a `prompt` or `text` field to per-frame measurements and document how to set it.
- [ ] Run an end-to-end recording (using keyboard) and validate outputs.
- [x] Write the docs on this part.

## Quick Commands

Run (refer to the `run_carla_mp_pilot.sh`):

```bash
bash run_carla_mp_pilot.sh --mode autopilot --duration 30 --route highway # autopilot 30 sec onto highway 
bash run_carla_mp_pilot.sh --mode autopilot --autopilot-all  # all autopilot variations
bash run_carla_mp_pilot.sh --mode evaluation --duration 120 --route urban # simlingo agent 
bash run_carla_mp_pilot.sh --mode both --duration 120 --route urban # simlingo agent + autopilot 
```

Change ownership of helper scripts to `pim1yh` (requires sudo):

```bash
sudo chown pim1yh:pim1yh /workspace/simlingo/mp_push_simple.sh \
	/workspace/simlingo/how_to_run_headless.sh \
	/workspace/simlingo/japanese_driving_autopilot.py
sudo chmod 755 /workspace/simlingo/mp_push_simple.sh \
	/workspace/simlingo/how_to_run_headless.sh \
	/workspace/simlingo/japanese_driving_autopilot.py
```
Also, I did 
```bash 
sudo chown pim1yh:pim1yh /workspace/simlingo/.gitignore && sudo chmod 755 /workspace/simlingo/.gitignore
sudo chown pim1yh:pim1yh /workspace/simlingo/team_code/test_japan_streets_simple.py && sudo chmod 755 /workspace/simlingo/team_code/test_japan_streets_simple.py
```

---
  
## Japanese Traffic Management (left-hand driving)

This project configures CARLA's Traffic Manager to emulate Japanese-style (left-hand) traffic. Below explains how it is implemented and how to change it.

- Where it's configured: `japanese_driving_autopilot.py` in the `setup_left_hand_traffic()` and `spawn_npc_vehicles()` functions.
- Key settings used:
  - `traffic_manager.global_lane_offset = -1.5` — applies a global lateral lane offset (negative shifts vehicles left).
  - `traffic_manager.vehicle_lane_offset(vehicle, -1.5)` — applies the same offset per vehicle after spawn.
  - `traffic_manager.set_global_distance_to_leading_vehicle(2.5)` — sets following distance.
  - `traffic_manager.ignore_lights_percentage(vehicle, 0)` — set to `0` to obey traffic lights (set to higher to have NPCs ignore lights sometimes).

- NPC spawning: `spawn_npc_vehicles(num_vehicles=30)` spawns vehicles at map spawn points, sets autopilot linking them to the Traffic Manager, and sets the lane offset. To reduce traffic set `num_vehicles` lower or add a CLI flag `--npc 0` to disable.

- Player vehicle: `spawn_player_vehicle()` sets the player to autopilot via the Traffic Manager, applies the same lane offset, and optionally calls `traffic_manager.set_path()` to follow a route. This enforces left-side driving for the ego vehicle as well.

- How to tweak quickly:
  - Reduce NPCs: change `num_vehicles` or add CLI `--npc 0`.
  - Change lane offset: set `global_lane_offset` and `vehicle_lane_offset` to `+1.5` for right-hand driving, or change magnitude to adjust centering.
  - Traffic behavior: tune `ignore_lights_percentage`, `set_global_distance_to_leading_vehicle`, or per-vehicle speed/behavior attributes via the Traffic Manager API.

- Disable NPCs entirely (example): in `setup_left_hand_traffic()` replace `self.spawn_npc_vehicles(num_vehicles=30)` with `self.spawn_npc_vehicles(num_vehicles=0)` or comment out the call.

## Multi Camera Setup 

The cameras are set here and these are the reported names. 
```bash
Front (F): x=2.5, y=0.0, z=1.5, yaw=0° - centered front, looking forward
Back (B): x=-2.5, y=0.0, z=1.5, yaw=180° - centered back, looking backward
Right Front (RF): x=1.0, y=1.0, z=1.5, yaw=55° - right front corner, angled forward-right
Left Front (LF): x=1.0, y=-1.0, z=1.5, yaw=-55° - left front corner, angled forward-left
Right Back (RB): x=-1.0, y=1.0, z=1.5, yaw=125° - right back corner, angled backward-right
Left Back (LB): x=-1.0, y=-1.0, z=1.5, yaw=-125° - left back corner, angled backward-left
```

Troubleshotting on the images being black (delay in starting the camera sensor)
```bash
python3 - <<'PY'                                               
from PIL import Image
import numpy as np, glob, os
p = glob.glob('recording_japan_xml/autopilot_multicamera_japanese_highway_*/rgb/0000/*')
for f in sorted(p):
    im = np.array(Image.open(f))
    print(os.path.basename(f), 'max=', im.max(), 'shape=', im.shape)
PY
```


## How to manage multiple images?

In out pipeline, we need somethig that takes one imgs as input --> training. 
In other words, the **output** of this processing (before the training) has to be **one img**.

We have two approaches: 
A) Fusing the imgs into one.
B) Threat N-imgs independent. 

These approaches A) and B) have options:

Option A)
A.1) Spatial-Aware Independent Processing + Attention Fusion
A.2) Gaussina splattering to reconstrctut the whole scene 
A.3) Attention Fusion Strategy

Option B): 
B.1) Integrated just one img at time, no matter where it has been shooted, to the model.
B.2) Camera + Posiiton ordering strategy (rule based)