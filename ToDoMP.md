# Michele ToDo lists into the simlingo

This is a `.md` file to I remeber what to do next.

**Compeltely random stuff listed down.**

## Checklist

Use the checklist below to track progress on finishing `japanese_driving_autopilot.py`. Check an item by changing `- [ ]` to `- [x]`.

- [x] Change the per-frame JSON output format to match training dataset (gzipped per-frame files `measurements/0000.json.gz` and `boxes/0000.json.gz`, plus top-level `records.json.gz` and `results.json.gz`).
- [x] Save up to 6 images per timestep into `rgb/` (names `0000.jpg` .. `0007.jpg`), and merge those implement multiple cameras producing those images.
- [x] Move all the `.sh` into a folder `scripts/`
- [x] Create multiple autonomous path to collect data from CARLA. 
- [x] Think of a way to insert a `prompt` or `text` field to per-frame. [2BTESTED]
- [x] Run an end-to-end recording (using keyboard) and validate outputs.
- [x] Write the docs on this part.
- [x] `.sh` file to run the possible combination of the `japanese_driving_autopilot_cameras.py`
- [ ] Test the azure pipeline. 
- [ ] Run the training (one epoch, batch size 1) on Azure.

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
**this this this**
```bash
cd /workspace/simlingo
git checkout feat/michele && git add -A # && git status --porcelain --branch
# git commit -m "feat(michele): init comment Azure ML" || echo "No changes to commit" && git push myfork feat/michele
git commit -m "feat(michele): major changes in the data collection folder" || echo "No changes to commit" && git push myfork feat/michele

git checkout feat/michele && git add -A && git commit -m "feat(michele): major changes in the data collection folder" && git push myfork feat/michele
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
`cd /workspace/simlingo && bash script/run_carla_mp_pilot_script.sh --mode autopilot --duration 40 --route urban --autopilot-long --spawn-index 10 --weather ClearNoon`
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
```


```bash
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


**To inspect the single file from simlingo**

```bash
(simlingo) pim1yh@YH0V0013:/workspace/simlingo$ python - <<'PY'
from bosch_utils.tools.open_gz import load_and_print_fields
const_print = 80
dataset = '/workspace/simlingo/database/simlingo_v2_2025_01_10/data/simlingo/training_1_scenario/routes_training/random_weather_seed_1_balanced_150/Town12_Rep0_1000_route0_01_11_15_39_27'
print('='*const_print)
print('DATASET: records.json.gz')
print('='*const_print)
load_and_print_fields(f'{dataset}/records.json.gz', max_len=300)
print('\n' + '='*const_print)
print('\n' + '='*const_print)
print('\n' + '='*const_print)
print('DATASET: results.json.gz')
print('='*const_print)
load_and_print_fields(f'{dataset}/results.json.gz', max_len=300)
print('\n' + '='*const_print)
print('\n' + '='*const_print)
print('\n' + '='*const_print)
print('DATASET: measurements/0000.json.gz')
print('='*const_print)
load_and_print_fields(f'{dataset}/measurements/0000.json.gz', max_len=300)
print('\n' + '='*const_print)
print('\n' + '='*const_print)
print('\n' + '='*const_print)
PYad_and_print_fields(f'{dataset}/boxes/0000.json.gz', max_len=300)
================================================================================
DATASET: records.json.gz
================================================================================
Loaded dict from /workspace/simlingo/database/simlingo_v2_2025_01_10/data/simlingo/training_1_scenario/routes_training/random_weather_seed_1_balanced_150/Town12_Rep0_1000_route0_01_11_15_39_27/records.json.gz
- adv_actions: list -> []
- ego_actions: list -> []
- lights: list -> []
- meta_data: dict -> {'index': '1000_route0_01_11_15_39_27', 'town': 'Carla/Maps/Town12/Town12'}
- route: list -> []
- states: list -> []
DATASET: results.json.gz
================================================================================
Loaded dict from /workspace/simlingo/database/simlingo_v2_2025_01_10/data/simlingo/training_1_scenario/routes_training/random_weather_seed_1_balanced_150/Town12_Rep0_1000_route0_01_11_15_39_27/results.json.gz
- index: int -> 0
- infractions: dict -> {'collisions_layout': [], 'collisions_pedestrian': [], 'collisions_vehicle': [], 'red_light': [], 'stop_infraction': [], 'outside_route_lanes': [], 'min_speed_infractions': ["Average speed is 97.31% of the surrounding traffic's one"], 'yield_emergency_vehicle_infractions': [], 'scenario_timeouts': [...
- meta: dict -> {'route_length': 439.906, 'duration_game': 39.6, 'duration_system': 141.293}
- num_infractions: int -> 1
- route_id: str -> 'RouteScenario_0_rep0'
- scores: dict -> {'score_route': 100, 'score_penalty': 0.99193, 'score_composed': 99.193}
- status: str -> 'Completed'
- timestamp: str -> '1000_route0_01_11_15_39_27'
DATASET: measurements/0000.json.gz
================================================================================
Loaded dict from /workspace/simlingo/database/simlingo_v2_2025_01_10/data/simlingo/training_1_scenario/routes_training/random_weather_seed_1_balanced_150/Town12_Rep0_1000_route0_01_11_15_39_27/measurements/0000.json.gz
- aim_wp: list -> [7.378705206876038, -0.00012709464747341913]
- angle: float -> -1.096546931563134e-05
- augmentation_rotation: float -> -15.222332437390818
- augmentation_translation: float -> -0.8530971161226294
- brake: bool -> False
- changed_route: bool -> False
- command: int -> 4
- control_brake: bool -> False
- ego_matrix: list -> [[-0.5951623916625977, 0.8035978078842163, 0.0035044122487306595, -2275.373779296875], [-0.8035829067230225, -0.5951727032661438, 0.004898975137621164, 6309.81591796875], [0.0060225361958146095, 9.960005263565108e-05, 0.9999818801879883, 378.3406982421875], [0.0, 0.0, 0.0, 1.0]]
- junction: bool -> False
- light_hazard: bool -> False
- next_command: int -> 4
- pos_global: list -> [-2275.373779296875, 6309.81591796875]
- route: list -> [[7.478716805209619, -0.00012369912461513493], [8.478832788545805, -8.974389348640526e-05], [9.488949931714822, -5.5449110123386955e-05], [10.488802448159113, -6.776019988571185e-05], [11.488644210850916, -8.195971122514634e-05], [12.488760194187103, -4.80044800959726e-05], [13.488876177523291, -1.4...
- route_original: list -> [[7.478716805209619, -0.00012369912461513493], [8.478832788545805, -8.974389348640526e-05], [9.488949931714822, -5.5449110123386955e-05], [10.488802448159113, -6.776019988571185e-05], [11.488644210850916, -8.195971122514634e-05], [12.488760194187103, -4.80044800959726e-05], [13.488876177523291, -1.4...
- speed: float -> 0.1740161031484604
- speed_limit: float -> 33.333333333333336
- speed_reduced_by_obj_distance: NoneType -> None
- speed_reduced_by_obj_id: NoneType -> None
- speed_reduced_by_obj_type: NoneType -> None
- steer: float -> -0.0
- stop_sign_close: bool -> False
- stop_sign_hazard: bool -> False
- target_point: list -> [168.90193579747168, -0.0002916067529178161]
- target_point_next: list -> [243.8184293176737, -0.00041259032663154083]
- target_speed: float -> 20.0
- theta: float -> -2.208277364565303
- throttle: float -> 1.0
- vehicle_affecting_id: NoneType -> None
- vehicle_hazard: bool -> False
- walker_affecting_id: NoneType -> None
- walker_close: bool -> False
- walker_close_id: NoneType -> None
- walker_hazard: bool -> False

================================================================================
DATASET: boxes/0000.json.gz
================================================================================
Loaded list from /workspace/simlingo/database/simlingo_v2_2025_01_10/data/simlingo/training_1_scenario/routes_training/random_weather_seed_1_balanced_150/Town12_Rep0_1000_route0_01_11_15_39_27/boxes/0000.json.gz
List with 3 items. Sample:
 [0] {'class': 'ego_car', 'extent': [2.44619083404541, 0.9183566570281982, 0.7451388239860535], 'position': [0.0, 0.0, 0.0], 'yaw': 0.0, 'num_points': -1, 'distance': -1, 'speed': 0.00012899417989230066, 'brake': 0.0, 'id': 3695, 'matrix': [[-0.5951623916625977, 0.8035978078842163, 0.0035044122487306595,...
 [1] {'class': 'weather', 'cloudiness': 20.0, 'dust_storm': 0.0, 'fog_density': 2.0, 'fog_distance': 0.0, 'fog_falloff': 0.0, 'mie_scattering_scale': 0.0, 'precipitation': 80.0, 'precipitation_deposits': 20.0, 'rayleigh_scattering_scale': 0.03310000151395798, 'scattering_intensity': 0.0, 'sun_altitude_an...
 [2] {'class': 'ego_info', 'scenario': 'random_weather_seed_1_balanced_150', 'traffic_light_state': 'None', 'distance_to_junction': 170.00079345703125, 'ego_lane_number': 2, 'road_id': 625, 'lane_id': 4, 'is_in_junction': False, 'is_intersection': False, 'junction_id': -1, 'next_road_junction': True, 'ne...
(simlingo) pim1yh@YH0V0013:/workspace/simlingo$ 
```


**To compare the same structure** 
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






**About the commentary**

to compare the content of all the `*.json.gz`, we use `open_gz.py`, `compare_structure.py` and `imgs_features.py`. I am investigating this here.
```bash
(simlingo) pim1yh@YH0V0013:/workspace/simlingo$ du -sh /workspace/simlingo/database/simlingo_v2_2025_01_10 /workspace/simlingo/database/bucketsv2_simlingo 2>/dev/null
846G    /workspace/simlingo/database/simlingo_v2_2025_01_10
647M    /workspace/simlingo/database/bucketsv2_simlingo
(simlingo) pim1yh@YH0V0013:/workspace/simlingo$ ls -lh /workspace/simlingo/database/simlingo_v2_2025_01_10/ 2>/dev/null | head -15
total 16K
drwxrwsr-x 3 tko3yh workspace 4.0K Nov 20 11:21 commentary
drwxrwsrwx 3 tko3yh workspace 4.0K Nov 20 11:24 data
drwxrwsr-x 3 tko3yh workspace 4.0K Nov 20 15:41 dreamer
drwxrwsr-x 3 tko3yh workspace 4.0K Nov 20 15:45 drivelm
### OR
(simlingo) pim1yh@YH0V0013:/workspace/simlingo/database/simlingo_v2_2025_01_10/commentary/simlingo/training_1_scenario/routes_training/random_weather_seed_1_balanced_150/Town12_Rep0_4438_route0_01_12_02_15_25/commentary$ zcat ./0010.json.gz
{
    "image": "database/simlingo_v2_2025_01_10/data/simlingo/training_1_scenario/routes_training/random_weather_seed_1_balanced_150/Town12_Rep0_4438_route0_01_12_02_15_25/rgb/0010.jpg",
    "commentary": "Follow the route. Accelerate to follow the black SUV that is to the front.",
    "commentary_template": "Follow the route. Accelerate to follow the <OBJECT>.",
    "cause_object_visible_in_image": true,
    "cause_object": {
        "class": "car",
        "color_rgb": [
            0,
            0,
            0
        ],
        "color_name": "black",
        "next_action": "Straight",
        "vehicle_cuts_in": false,
        "road_id": 363,
        "lane_id": -1,
        "lane_type": 2,
        "lane_type_str": "Driving",
        "is_in_junction": false,
        "junction_id": -1,
        "distance_to_junction": 3.9721195697784424,
        "next_junction_id": 3742,
        "next_road_ids": [
            3750
        ],
        "next_next_road_ids": [
            364
        ],
        "same_road_as_ego": true,
        "same_direction_as_ego": true,
        "lane_relative_to_ego": 0,
        "light_state": [
            1,
            2,
            128
        ],
        "traffic_light_state": "Green",
        "is_at_traffic_light": false,
        "base_type": "car",
        "number_of_wheels": "4",
        "extent": [
            2.782914400100708,
            1.0749834775924683,
            1.0225735902786255
        ],
        "position": [
            11.37559178339336,
            0.41371028731013837,
            0.07765749225703189
        ],
        "yaw": 0.06254087609109393,
        "num_points": 128,
        "distance": 11.383377148734748,
        "speed": 2.6731059512255886,
        "brake": 0.0,
        "steer": 0.006922694388777018,
        "throttle": 0.8500000238418579,
        "id": 3701,
        "role_name": "background",
        "type_id": "vehicle.nissan.patrol_2021",
        "matrix": [
            [
                0.08387532830238342,
                -0.9964762330055237,
                -0.00033479504054412246,
                -3342.4765625
            ],
            [
                0.9964737296104431,
                0.0838758647441864,
                -0.002229610225185752,
                1592.404296875
            ],
            [
                0.0022498348262161016,
                -0.000146605190820992,
                0.9999974966049194,
                350.3906555175781
            ],
            [
                0.0,
                0.0,
                0.0,
                1.0
            ]
        ]
    },
    "cause_object_string": "black SUV that is to the front",
    "scenario_name": "BlockedIntersection",
    "placeholder": {
        "<OBJECT>": "black SUV that is to the front"
    }
```


### To move data out of this machine to my windows cetricx
`scp -r pim1yh@10.162.163.183:/workspace/simlingo/bosch_utils/ "C:\Users\PIM1YH\Downloads\"`
`scp -r pim1yh@10.162.163.183:/workspace/simlingo/script/ "C:\Users\PIM1YH\Downloads\"`

### SSD
Working witht the external ssd.

```bash
sudo umount /media/external_ssd
sudo mount -o uid=$(id -u),gid=$(id -g),dmask=0022,fmask=0133 /dev/sdb2 /media/external_ssd
touch /media/external_ssd/test.txt && rm /media/external_ssd/test.txt && echo "write OK"

sudo chown -R pim1yh:pim1yh /media/external_ssd/database

sudo chown -R pim1yh:pim1yh /bosch_utils/japanese_driving_autopilot_cameras.py

rsync -avP --remove-source-files /workspace/simlingo/recording_japan_xml/database/ /media/external_ssd/database/
```

# New start 
# 2026
# Last day before new years break -> When to start back

- keep testing the `python /workspace/simlingo/bosch_utils/tools/image_commentary2_todo.py /media/external_ssd/database/simlingo_v4_2026_01_01/auto_long_multicam_jp/training_Town01_scenario/routes_highway_duration_50_training/SoftRainNoon_weather/ego_42/rgb/0000/patched.jpg`. Enforcing the strcture used from simlingo. Enforce the commentary_augmented.json and all the simlingo/data/auguemnted from the simlingo team in a japanese fashion.
Take these tempalte `simlingo/data/augmented_templates/commentary_augmented.json`.
- check the upload on azure ~400 000/20 000 000 with 24 h of uploading 
- check the data collection from CARLA. 30% usage in the external ssd of 4TB

```bash 
(simlingo) pim1yh@YH0V0013:/workspace/simlingo$ tmux ls
azure_upload: 1 windows (created Thu Dec 25 17:26:41 2025)
datajob: 1 windows (created Thu Dec 25 15:51:28 2025)
```

```bash
(base) pim1yh@YH0V0013:/workspace$ python /workspace/simlingo/bosch_utils/tools/image_commentary2_todo.py /media/external_ssd/database/simlingo_v4_2026_01_01/auto_long_multicam_jp/training_Town01_scenario/routes_highway_duration_50_training/SoftRainNoon_weather/ego_42/rgb/0000/patched.jpg -v
[INFO] Starting llama-server on port 8081...
[INFO] Server ready after 4s
[INFO] Processing image: patched.jpg
[INFO] Generating commentary with llama.cpp...
====================================================================================================
====================================================================================================
[INFO] Saved commentary to /media/external_ssd/database/simlingo_v4_2026_01_01/commentary/auto_long_multicam_jp/training_Town01_scenario/routes_highway_duration_50_training/SoftRainNoon_weather/ego_42/rgb/0000/patched.json.gz (43.78s)
====================================================================================================
====================================================================================================
[INFO] ✓ Successfully processed: /media/external_ssd/database/simlingo_v4_2026_01_01/commentary/auto_long_multicam_jp/training_Town01_scenario/routes_highway_duration_50_training/SoftRainNoon_weather/ego_42/rgb/0000/patched.json.gz
(base) pim1yh@YH0V0013:/workspace$ zcat /media/external_ssd/database/simlingo_v4_2026_01_01/commentary/auto_long_multicam_jp/training_Town01_scenario/routes_highway_duration_50_training/SoftRainNoon_weather/ego_42/rgb/0000/patched.json.gz
{
  "image": "/media/external_ssd/database/simlingo_v4_2026_01_01/auto_long_multicam_jp/training_Town01_scenario/routes_highway_duration_50_training/SoftRainNoon_weather/ego_42/rgb/0000/patched.jpg",
  "commentary": "The front camera view shows a clear road ahead with no immediate obstacles, while the front-left and front-right cameras indicate open lanes with no vehicles in close proximity. The rear-center and rear-left cameras reveal a white sedan approximately 15 meters behind, maintaining a steady distance. The rear-right camera shows an empty lane. The surrounding environment appears to be a multi-lane highway with no visible pedestrians or cyclists. All camera views confirm a stable, unobstructed driving environment with no signs of traffic congestion or hazards.",
  "commentary_template": "The front camera view shows a clear road ahead with no immediate obstacles, while the front-left and front-right cameras indicate open lanes with no <OBJECT>s in close proximity. The rear-center and rear-left cameras reveal a white sedan approximately 15 meters behind, maintaining a steady distance. The rear-right camera shows an empty lane. The surrounding environment appears to be a multi-lane highway with no visible pedestrians or cyclists. All camera views confirm a stable, unobstructed driving environment with no signs of traffic congestion or hazards.",
  "cause_object_visible_in_image": true,
  "cause_object": {},
  "cause_object_string": "vehicle",
  "scenario_name": "RouteFollowing",
  "placeholder": {
    "<OBJECT>": "vehicle"
  },
  "provenance": {
    "generator": "image_describer2_todo.py",
    "llama_model": "Qwen3VL-32B-Instruct-Q4_K_M.gguf",
    "n_gpu_layers": 16,
    "generated_at": "2025-12-26T07:30:58Z",
    "detections_count": 0
  }
}
```

======================================
## Tools 

Cutting the .log
```bash
TS=$(date +%Y%m%d_%H%M%S)
cp azure_deploy_mp/azure_upload.log azure_deploy_mp/azure_upload.log.$TS

# 2) gzip the copy in background to save space (may take time)
gzip azure_deploy_mp/azure_upload.log.$TS &
# 3) truncate the live log immediately (frees space)
: > azure_deploy_mp/azure_upload.log
du -sh azure_deploy_mp/azure_upload.log*
df -h .
```

Check the usage of GPU

```bash
TOT=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits -i 0)
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader,nounits -i 0 \
| while IFS=',' read -r pid name used; do
  used=$(echo "$used" | tr -d ' ')
  pct=$(awk -v u="$used" -v t="$TOT" 'BEGIN{printf "%.1f", u/t*100}')
  printf "%s\t%s\t%4s MiB\t(%s%%)\n" "$pid" "$name" "$used" "$pct"
done
```
When `code` for opening imgs does not work, refresh the terminal
`export VSCODE_IPC_HOOK_CLI=$(ls -t /run/user/$(id -u)/vscode-ipc-*.sock | head -n 1)`