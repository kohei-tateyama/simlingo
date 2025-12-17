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
- [ ] `.sh` file to run the possible combination of the `japanese_driving_autopilot_cameras.py`

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
### When I do take any picture
N_{shoot} ≈ max(0, floor( (D - Tprim - Toverhead) * fps ) - W - Nlost )
D = desired recording duration in seconds (user --duration)
fps = target frames per second (user --fps)
dt = 1 / fps (sim step / sleep interval)
W = warmup frames skipped (self._warmup_frames)
Tprim = camera priming timeout (seconds) — time spent waiting for initial valid camera images
Tbuffer = buffer flush timeout (seconds) — time the writer will wait for missing cameras before flushing a partial frame
Toverhead = extra per-loop overhead (seconds) — e.g., writer, JSON writes, compression, and Python scheduling jitter (measure empirically or assume small value)
Nlost = number of frames lost because sensors didn't produce images in time (depends on priming/missing callbacks; assume 0 if system primed and synchronous)

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
<!-- https://carla.readthedocs.io/en/latest/adv_agents/ -->

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


### How to push 
I did a mess before and we do have some issue since Kohey is not with the Bosch account 

I have two braches 
```bash
git status --porcelain --branch
git branch -vv
```
This will return
```bash
## feat/michele...myfork/feat/michele
* feat/michele                         3305c34 [myfork/feat/michele] autosave: add fps estimator, CLI forwarding and summary info
  main                                 0f1f70c [myfork/main] chore(bosch_utils): add/update autopilot and patcher scripts
  snapshot/pre-cleanup_20251212_141603 f497701 Snapshot: working tree before cleanup 20251212_141603
``` 

Next (to actual push). **This jsut works for this repo!**
```bash
git fetch myfork
git rebase myfork/feat/michele
git add . && git commit -m "comment here" && git push myfork feat/michele
git checkout main && git pull --ff-only myfork main || true && git merge --no-ff feat/michele -m "merge: bring feat/michele into main" || true && git push myfork main && git status --porcelain --branch
```
Some useful `git` command here:
```bash
git push --force-with-lease myfork feat/michele # removing history, very mean 

git checkout -b feat/michele   # if needed
git push --set-upstream myfork feat/michele # differnt branch
```

Verify after pushing 
```bash
git fetch --all --prune
git branch -vv
git log --oneline --decorate -n 5
```
This is a one only push quite useful right now.
```bash
cd /workspace/simlingo
git checkout feat/michele
git add -A
git commit -m "feat(michele): camera timing fixes, long autopilot, CLI flags, and helper scripts" || echo "No changes to commit"
git push myfork feat/michele
```

To open multiple photo of the `F.png` camera, using visual code and while being isidre the folder itsleft, i.e., `script/open_every50_code.sh`.
You can decide which data to open, which software to use (code default), frquency of opend images, and the name of the `.png` to be open.


## NEW dataset (enriching the simlingo one)

What we can vary `japanese_driving_autopilot_cameras.py` and its _long_ version `japanese_driving_autopilot_cameras_long.py`

```bash
japanese_driving_autopilot_cameras.py [-h] [--autopilot]
                                            [--duration DURATION]
                                            [--route {highway,urban,simple}]
                                            [--fps FPS] 
                                            [--weather WEATHER]
                                            [--spawn-index SPAWN_INDEX]
```

Simlingo strcture of the databased was:
`/database/simlingo_v2_2025_01_10/commentary/simlingo/training_1_scenario/routes_training/random_weather_seed_1_balanced_150$`

In our case, 
`/database/simlingo_v2_2025_01_10/<>/simlingo/training_<>_scenario/routes_training/random_weather_seed_1_balanced_<>$`

---

## Run the I should do now
To run next:
`bash script/run_carla_mp_pilot_script.sh --mode autopilot --duration 10 --route highway --multicamera --fps 20 --agent-long`
`bash script/run_carla_mp_pilot_script.sh --mode autopilot --duration 10 --route highway --agent-long --fps 20`

Short autopilot with spawn point 25
`python bosch_utils/japanese_driving_autopilot_cameras.py --autopilot --duration 10 --route highway --spawn-index 25`
Long autopilot with random spawn for data variety
`python bosch_utils/japanese_driving_autopilot_cameras_long.py --autopilot --duration 30 --route highway --random-spawn`
Long autopilot with specific spawn point 10
`python bosch_utils/japanese_driving_autopilot_cameras_long.py --autopilot --duration 10 --route highway --spawn-index 10`
<!-- Via wrapper script with long agent
`bash script/run_carla_mp_pilot_script.sh --mode autopilot --duration 20 --route highway --agent-long --spawn-index 42` -->

---

I will write here a pseudocode to get an idea of what I can run for the collection of data.
I could also run mutiple .sh file like the following changing the port of carla, e.g., 2000 --> 2001, etc. 
I want to run `bash script/run_carla_mp_pilot_script.sh` iterating within this 

```bash
## This ia pesudo bash!!

# JapaneseStyleAutopilot --> japanese_driving_autopilot_cameras.py (This is managed form the script/run_carla_mp_pilot_script.sh
self.foldername = f"/database/simlingo_v3_2026_01_01/auto_short_multicam_jp/training_{self.town}_scenario/routes_{self.route_type}_duration_{self.duration}_training/{self.weather}_weather/ego_{self.spawn_idx}"
# LongJapaneseStyleAutopilot --> japanese_driving_autopilot_cameras_long.py
self.foldername = f"/database/simlingo_v3_2026_01_01/auto_short_multicam_jp/training_{self.town}_scenario/routes_{self.route_type}_duration_{self.duration}_training/{self.weather}_weather/ego_{self.spawn_idx}"

ROUTER_TYPES=[highway,urban,simple] # note that they usualle come with a predefined time [60,90,30]
TOWN=[Town13,Town12]
SPAWN_INDICES=[42,???]
DURATION=[10,20,30,40,50,120,180,300]
AGENT=[no-agent-long,agent-long]

for agent in AGENT
  for town in TOWN
    for route_type in ROUTER_TYPES
      for weather in WEATHER
        for spawn_idx in SPAWN_INDICES
          for duration in DURATION

bash script/run_carla_mp_pilot_script.sh --mode autopilot --duration $duration --multicamera --route $route_type --agent-long --spawn-index $spawn_idx 

```
    


To use the `config_bosch_utils.yaml`
```python
import os
import yaml

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
cfg_path = os.path.join(repo_root, 'bosch_utils', 'config_bosch_utils.yaml')

with open(cfg_path, 'r') as f:
    cfg = yaml.safe_load(f)

# Example usage:
autosave = cfg.get('AUTOSAVE_SECS', 300)
rotate = cfg.get('ROTATE_SECS', 0)
```



## Future directions and ideas
 
| Component | Choice for Speed & Flexibility | Rationale |
|---|---|---|
| Vision Encoder | SigLIP-2 | Excellent visual features without the overhead of complex, proprietary vision architectures. It provides a flexible feature set. |
| Projector | MLP Projector (specifically a Linear or 2-Layer MLP) | Fastest inference. It applies a simple matrix multiplication to the vision tokens, adding minimal latency compared to Transformer-based alternatives like Q-Former. |
| Language Model (LLM) | Small, Quantized LLM (e.g., Llama 3 3B, Qwen2 0.5B) | The LLM dictates the overall latency. Choosing a small LLM and optimizing it with quantization (e.g., to INT4 or FP8) is essential for real-time edge deployment. |

Vision Encoder (V-Enc) Options (Small Size) | Projector Module Options (Fast & Efficient) | Language Model (LLM) Options (Small & Quantizable)
SigLIP-2 (ViT-B/16 or ViT-L/14) | 2-Layer MLP (LLaVA style) | "Qwen2 (0.5B, 1.5B)"
DINOv2 (ViT-S/16 or ViT-B/14) | LVP (Language-guided Visual Projector) | Gemma 2 (2B)
"CLIP / EVA-CLIP (ViT-B/16, L-14)" | Efficient Dense Connector | "Llama 3 (3B, 8B)"
InternViT-300M (InternVL2 backbone) | Semantic Visual Projector (SVP) | MiniCPM-V (2.4B)
 |  | "Mistral (7B, if resource permits)"