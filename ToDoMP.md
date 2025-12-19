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
sudo chown pim1yh:pim1yh /workspace/simlingo/.gitignore && sudo chmod 755 /workspace/simlingo/.gitignorethe 
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




## How to push / maintain
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

**This is a one only push quite useful right now.**
```bash
cd /workspace/simlingo
git checkout feat/michele
git add -A && git status --porcelain --branch
git commit -m "feat(michele): japanese/uk driving (sligly more) stable" || echo "No changes to commit"
git push myfork feat/michele
```
To update also the branch `main` from the `feat/michele` one do
```bash
git fetch myfork --prune # && git rev-list --left-right --count myfork/main...myfork/feat/michele
git checkout main
git merge --no-ff feat/michele -m "merge: bring feat/michele into main"
# git push --dry-run myfork feat/michele:main # safrer vesion
# git fetch myfork && git branch -r --verbose --sort=-committerdate | sed -n '1,20p' # checking 
git push myfork main
```
To switch back again to the feat/michele branch
```bash
git stash push -m "wip: stash before switching to feat/michele" || true && git checkout feat/michele && git status --porcelain --branch && git branch -vv && git stash list -n 5
```
---

## NEW dataset (enriching the simlingo one)

What we can vary `japanese_driving_autopilot_cameras.py` and its _long_ version `japanese_driving_autopilot_cameras_long.py`

Via wrapper script with long agent
`bash script/run_carla_mp_pilot_script.sh --mode autopilot --duration 20 --route highway --autopilot-long --spawn-index 42`

---

## Future directions and ideas

### Pipeline and VLA
 
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

 <!-- https://carla.readthedocs.io/en/latest/adv_agents/ -->

### How to manage multiple images?

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

## Useless stuff

`ls -1 | head -n 5` # print he first 5 element in a folder 
`ls -1A . | wc -l`  # Number of element in a fodler 

`/workspace/simlingo/database/simlingo_v2_2025_01_10/data/simlingo/training_1_scenario/routes_training/random_weather_seed_1_balanced_150/Town12_Rep0_1000_route0_01_11_15_39_27`
From the windows bash (52 MB of data)
`scp -r pim1yh@10.162.163.183:/workspace/simlingo/database/simlingo_v2_2025_01_10/data/simlingo/training_1_scenario/routes_training/random_weather_seed_1_balanced_150/Town12_Rep0_1000_route0_01_11_15_39_27 "C:\Users\PIM1YH\Downloads\"`
```bash
(simlingo) pim1yh@YH0V0013:/workspace/simlingo/database/simlingo_v2_2025_01_10/data/simlingo/training_1_scenario/routes_training/random_weather_seed_1_balanced_150/Town12_Rep0_1000_route0_01_11_15_39_27$ ll
total 428
drwxr-sr-x    7 tko3yh workspace   4096 Jan 11  2025 ./
drwxrwsr-x 5700 tko3yh workspace 405504 Nov 20 12:36 ../
drwxr-sr-x    2 tko3yh workspace   4096 Jan 11  2025 boxes/
drwxr-sr-x    2 tko3yh workspace   4096 Jan 11  2025 lidar/
drwxr-sr-x    2 tko3yh workspace   4096 Jan 11  2025 measurements/
-rw-r--r--    1 tko3yh workspace    159 Jan 11  2025 records.json.gz
-rw-r--r--    1 tko3yh workspace    410 Jan 11  2025 results.json.gz
drwxr-sr-x    2 tko3yh workspace   4096 Jan 11  2025 rgb/
drwxr-sr-x    2 tko3yh workspace   4096 Jan 11  2025 rgb_augmented/
```
We reached the same lavel of precision now 
```bash
(simlingo) pim1yh@YH0V0013:/workspace/simlingo/recording_japan_xml/database/simlingo_v3_2026_01_01/auto_long_multicam_jp/training_Town13_scenario/routes_highway_duration_20_training/SoftRainNight_weather/ego_42$ du -sh ./rgb/0008/*
56K     ./rgb/0008/B.jpg
64K     ./rgb/0008/F.jpg
64K     ./rgb/0008/LB.jpg
64K     ./rgb/0008/LF.jpg
108K    ./rgb/0008/patched.jpg
60K     ./rgb/0008/RB.jpg
64K     ./rgb/0008/RF.jpg
(simlingo) pim1yh@YH0V0013:/workspace/simlingo/recording_japan_xml/database/simlingo_v3_2026_01_01/auto_long_multicam_jp/training_Town13_scenario/routes_highway_duration_20_training/SoftRainNight_weather/ego_42$
```


```bash
(simlingo) pim1yh@YH0V0013:/workspace/simlingo/database/simlingo_v2_2025_01_10/data/simlingo/training_1_scenario/routes_training/random_weather_seed_1_balanced_150/Town12_Rep0_3838_route0_01_11_15_37_20$ ll
total 428
drwxr-sr-x    7 tko3yh workspace   4096 Jan 11  2025 ./
drwxrwsr-x 5700 tko3yh workspace 405504 Nov 20 12:36 ../
drwxr-sr-x    2 tko3yh workspace   4096 Jan 11  2025 boxes/
drwxr-sr-x    2 tko3yh workspace   4096 Jan 11  2025 lidar/
drwxr-sr-x    2 tko3yh workspace   4096 Jan 11  2025 measurements/
-rw-r--r--    1 tko3yh workspace    159 Jan 11  2025 records.json.gz
-rw-r--r--    1 tko3yh workspace    414 Jan 11  2025 results.json.gz
drwxr-sr-x    2 tko3yh workspace   4096 Jan 11  2025 rgb/

(simlingo) pim1yh@YH0V0013:/workspace/simlingo/recording_japan_xml/database/simlingo_v3_2026_01_01/auto_long_multicam_jp/training_Town13_scenario/routes_highway_duration_20_training/SoftRainNight_weather/ego_43$ ll
total 52
drwxrwsr-x   5 pim1yh workspace  4096 Dec 18 11:50 ./
drwxrwsr-x   3 pim1yh workspace  4096 Dec 18 11:53 ../
drwxrwsr-x   2 pim1yh workspace 12288 Dec 18 11:50 boxes/
drwxrwsr-x   2 pim1yh workspace 12288 Dec 18 11:50 measurements/
-rw-rw-r--   1 pim1yh workspace   226 Dec 18 11:50 records.json.gz
-rw-rw-r--   1 pim1yh workspace   408 Dec 18 11:50 results.json.gz
drwxrwsr-x 403 pim1yh workspace 12288 Dec 18 11:50 rgb/
```

To check the same strcture, we use 
```bash
python - <<'PY'
from bosch_utils.tools.open_gz import load_and_print_fields
print('='*60)
print('DATASET: records.json.gz')
print('='*60)
load_and_print_fields('/workspace/simlingo/database/simlingo_v2_2025_01_10/data/simlingo/training_1_scenario/routes_training/random_weather_seed_1_balanced_150/Town12_Rep0_3838_route0_01_11_15_37_20/records.json.gz', max_len=300)
print('\n' + '='*60)
print('OUR RECORDING: records.json.gz')
print('='*60)
load_and_print_fields('/workspace/simlingo/recording_japan_xml/database/simlingo_v3_2026_01_01/auto_long_multicam_jp/training_Town13_scenario/routes_highway_duration_20_training/SoftRainNight_weather/ego_43/records.json.gz', max_len=300)
print('\n' + '='*60)
print('DATASET: results.json.gz')
print('='*60)
load_and_print_fields('/workspace/simlingo/database/simlingo_v2_2025_01_10/data/simlingo/training_1_scenario/routes_training/random_weather_seed_1_balanced_150/Town12_Rep0_3838_route0_01_11_15_37_20/results.json.gz', max_len=300)
print('\n' + '='*60)
print('OUR RECORDING: results.json.gz')
print('='*60)
load_and_print_fields('/workspace/simlingo/recording_japan_xml/database/simlingo_v3_2026_01_01/auto_long_multicam_jp/training_Town13_scenario/routes_highway_duration_20_training/SoftRainNight_weather/ego_43/results.json.gz', max_len=300)
PY
```

to compare the content of all the *.json.gz, we use `open_gz.py`, `compare_structure.py` and `imgs_features.py`.



