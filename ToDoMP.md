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

Run (refer to single test for the data collection):

```bash
bash script/run_carla_mp_pilot_script.sh --mode autopilot --duration 15 --route urban --town Town13 --weather SoftRainNight --spawn-index 12 --autopilot-long --fps 20 # running a left hand driving GLOBAL PLANNER using 6 cameras 
bash script/test_data_agent_japanese.sh # running a left hand driving LEADERBOARD AGENT using 6 cameras 
bash script/test_data_agent_multicamera.sh # running a RIGHT hand driving LEADERBOARD AGENT using 6 cameras 
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
Also,  
```bash 
sudo chown pim1yh:pim1yh /workspace/simlingo/.gitignore && sudo chmod 755 /workspace/simlingo/.gitignorethe 
sudo chown pim1yh:pim1yh /workspace/simlingo/team_code/test_japan_streets_simple.py && sudo chmod 755 /workspace/simlingo/team_code/test_japan_streets_simple.py
```
---

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

## How to push / maintain
I did a mess before and we do have some issue since Kohey is not with the Bosch account 

I have two braches 
```bash
git status --porcelain --branch
git branch -vv
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
git checkout feat/michele && git add -A # && git status --porcelain --branch
# git commit -m "feat(michele): init comment Azure ML" || echo "No changes to commit" && git push myfork feat/michele
git commit -m "feat(michele): major changes in the data collection folder" || echo "No changes to commit" && git push myfork feat/michele
```
Check (visually) the relationship between branches
`git log --graph --oneline --all --decorate`

To update also the branch `main` from the `feat/michele` one do
```bash
git fetch myfork --prune # && git rev-list --left-right --count myfork/main...myfork/feat/michele
git checkout main
git merge --no-ff feat/michele -m "merge: bring feat/michele into main"
git push myfork main
```
To switch back again to the feat/michele branch
```bash
git stash push -m "wip: stash before switching to feat/michele" || true && git checkout feat/michele && git status --porcelain --branch && git branch -vv && git stash list -n 5
```
---

**this this this this**
```bash
git checkout feat/michele && git add -A && git commit -m "feat(michele): major changes in the data collection folder" && git push myfork feat/michele ## use this one
```
```bash 
git checkout main && \
git merge --no-ff feat/michele -m "merge: bring feat/michele into main" && \
git push myfork main && \
git checkout feat/michele
```

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

### Commentary

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

**To inspect the single file from simlingo**

`load_and_print_fields('/workspace/simlingo/database/simlingo_v2_2025_01_10/data/simlingo/training_1_scenario/routes_training/random_weather_seed_1_balanced_150/Town12_Rep0_3838_route0_01_11_15_37_20/records.json.gz', max_len=300)`

## About the commentary

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


### The leaderbaord output 

After any COMPLETED run, the leaderboard returs this statics. 

However, we introduce the saving of this statics also in the case of TIMEOUT run. 

```bash
=== [Agent] -- Wallclock = 2026-01-13 00:41:10.795 -- System time = 45034.792 -- Game time = 4518.000 -- Ratio = 0.100x
> Stopping the route

========= Results of RouteScenario_0 (repetition 0) ------ FAILURE =========

╒═══════════════════════╤═════════════════════╕
│ Start Time            │ 2026-01-12 12:10:35 │
├───────────────────────┼─────────────────────┤
│ End Time              │ 2026-01-13 00:41:12 │
├───────────────────────┼─────────────────────┤
│ System Time           │ 45036.39s           │
├───────────────────────┼─────────────────────┤
│ Game Time             │ 4518.0s             │
├───────────────────────┼─────────────────────┤
│ Ratio (Game / System) │ 0.1                 │
╘═══════════════════════╧═════════════════════╛

╒═══════════════════════╤═════════╤══════════╕
│ Criterion             │ Result  │ Value    │
├───────────────────────┼─────────┼──────────┤
│ RouteCompletionTest   │ SUCCESS │ 100 %    │
├───────────────────────┼─────────┼──────────┤
│ OutsideRouteLanesTest │ FAILURE │ 0 %      │
├───────────────────────┼─────────┼──────────┤
│ CollisionTest         │ FAILURE │ 11 times │
├───────────────────────┼─────────┼──────────┤
│ RunningRedLightTest   │ SUCCESS │ 0 times  │
├───────────────────────┼─────────┼──────────┤
│ RunningStopTest       │ FAILURE │ 1 times  │
├───────────────────────┼─────────┼──────────┤
│ MinSpeedTest          │ SUCCESS │ 110.55 % │
├───────────────────────┼─────────┼──────────┤
│ InRouteTest           │ SUCCESS │          │
├───────────────────────┼─────────┼──────────┤
│ AgentBlockedTest      │ SUCCESS │          │
├───────────────────────┼─────────┼──────────┤
│ ScenarioTimeoutTest   │ FAILURE │ 13 times │
├───────────────────────┼─────────┼──────────┤
│ Timeout               │ SUCCESS │          │
╘═══════════════════════╧═════════╧══════════╛
```

### To move data out of this machine to my windows cetricx
`scp -r pim1yh@10.162.163.183:/workspace/simlingo/bosch_utils/ "C:\Users\PIM1YH\Downloads\"`

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

# New start 2026. Last day before new years break -> When to start back

- keep testing the `python /workspace/simlingo/bosch_utils/tools/image_commentary2_todo.py /media/external_ssd/database/simlingo_v4_2026_01_01/auto_long_multicam_jp/training_Town01_scenario/routes_highway_duration_50_training/SoftRainNoon_weather/ego_42/rgb/0000/patched.jpg`. Enforcing the strcture used from simlingo. Enforce the commentary_augmented.json and all the simlingo/data/auguemnted from the simlingo team in a japanese fashion.
Take these tempalte `simlingo/data/augmented_templates/commentary_augmented.json`.
- check the upload on azure ~400 000/20 000 000 with 24 h of uploading 
- check the data collection from CARLA. 30% usage in the external ssd of 4TB

```bash 
(simlingo) pim1yh@YH0V0013:/workspace/simlingo$ tmux ls
azure_upload: 1 windows (created Thu Dec 25 17:26:41 2025) # Too slow .... still running 
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

- Cutting the .log
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

- Check the usage of GPU
```bash
TOT=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits -i 0)
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader,nounits -i 0 \
| while IFS=',' read -r pid name used; do
  used=$(echo "$used" | tr -d ' ')
  pct=$(awk -v u="$used" -v t="$TOT" 'BEGIN{printf "%.1f", u/t*100}')
  printf "%s\t%s\t%4s MiB\t(%s%%)\n" "$pid" "$name" "$used" "$pct"
done
```

- Bash utils
    - When `code` for opening imgs does not work, refresh the terminal
    `export VSCODE_IPC_HOOK_CLI=$(ls -t /run/user/$(id -u)/vscode-ipc-*.sock | head -n 1)`

    - One-liner for opening multiple `.jpg` from the `rgb/` folder
    `for ((i=0;i<=119;i+=10)); do a=$(printf "%04d" "$i"); b=$(printf "%04d" "$((i+10))"); code "$a/F.jpg" && code "$b/F.jpg"; done`

    ```bash
    tot=1000; step=$(( tot / 10 )); [ $step -lt 1 ] && step=1; for ((i=0;i<=tot;i+=step)); do a=$(printf "%04d" "$i"); j=$(( i+step )); if [ $j -gt $tot ]; then j=$tot; fi; b=$(printf "%04d" "$j"); code "${a}/patched2.jpg" && code "${b}/patched2.jpg"; done
    ```

    - One-liner to count the elements inside any folder 
    `find . -mindepth 1 -maxdepth 1 | wc -l`

    - Killing `carla` and `leaderboard`
    ```bash 
    sudo pkill -9 -f leaderboard || true && sudo pkill -9 -f carla || true
    ```


# Starting Migration to 0.9.16
```bash
mkdir /workspace/carla0916
cd /workspace/carla0916
wget https://carla-releases.s3.us-east-005.backblazeb2.com/Linux/CARLA_0.9.16.tar.gz  # run this
tar -xvf CARLA_0.9.16.tar.gz
rm CARLA_0.9.16.tar.gz
cd Import && wget https://carla-releases.s3.us-east-005.backblazeb2.com/Linux/AdditionalMaps_0.9.16.tar.gz
cd .. && bash ImportAssets.sh
```

```bash
# Create base environment
cd  /workspace/simlingo
conda env create -f environment16.yaml
conda activate simlingo16
pip install /workspace/carla0916/PythonAPI/carla/dist/carla-0.9.16-cp310-cp310-manylinux_2_27_x86_64.whl && pip install torch==2.2.0
# pip install flash-attn==2.7.0.post2
```

```bash 
cd /workspace/carla0916/PythonAPI/carla/dist
unzip carla-0.9.16-cp310-cp310-manylinux_2_31_x86_64.whl -d carla_0916_lib
```

```bash
conda activate simlingo16
export CARLA_ROOT=/workspace/carla0916
export WORK_DIR=/workspace/simlingo
# Note: I am excluding SCENARIO_RUNNER and LEADERBOARD for now to avoid 0.15 code conflicts
export SAVE_PATH=export CARLA_WHEEL=$(ls ${CARLA_ROOT}/PythonAPI/carla/dist/carla-0.9.16-cp310*.whl)
export PYTHONPATH="${WORK_DIR}:${CARLA_WHEEL}:${CARLA_ROOT}/PythonAPI/carla"
# export PYTHONPATH="${WORK_DIR}:${CARLA_ROOT}/PythonAPI/carla/dist/carla-0.9.16-cp310-cp310-manylinux_2_27_x86_64.whl:${CARLA_ROOT}/PythonAPI/carla"
echo "Switched to CARLA 0.9.16 environment"
```

## Note

1) Since the topology ahs changed, `simlingo/leaderboard/leaderboard/scenarios/route_scenario.py` we have disabled the following.

```bash
# DISABLED: RunningRedLightTest causes crashes on LHT maps due to waypoint topology issues
# criteria.add_child(RunningRedLightTest(self.ego_vehicles[0]))
```

2) When running both `simlingo/script/test_data_agent_multicamera_timeout_all_carla0916.sh` and `simlingo/script/run_carla_mp_pilot_script_carla0916.sh`, the `.sh`s will create a folder to enable the LHT in carla 0.9.16, i.e., `tmp_carla_0916_config/` 

3) I have installed `leaderboard21` the offivial release of leaderboard for carla 0.9.16. 
Some of the code which I will list here have a shared dependecies, which I will take care of once I have tested stuff. 
`simlingo/team_code/autopilot.py`



```bash
(simlingo) pim1yh@YH0V0013:/workspace$ pip show carla
Name: carla
Version: 0.9.15
Summary: Python API for communicating with the CARLA server.
Home-page: https://github.com/carla-simulator/carla
Author: The CARLA team
Author-email: carla.simulator@gmail.com
License: MIT License
Location: /home/pim1yh/miniconda3/envs/simlingo/lib/python3.8/site-packages
Requires: 
Required-by: 
```


monday fix the opath of town12

```bash
 if LooseVersion(dist.version) < LooseVersion('0.9.10'):
autopilot: using leaderboard21.autoagents (no autonomous_agent_local)
[INFO]: LHT patch ok via scenarioatomics

========= Preparing RouteScenario_0 (repetition 0) =========
> Loading the world
WARNING: No InMemoryMap cache found. Setting up local map. This may take a while... 
> Setting up the agent
[DEBUG][LHT] API Source: /workspace/carla0916/PythonAPI/carla/dist/carla_0916_lib/carla/__init__.py
[DEBUG][LHT] Route requires map: Town12
[INFO][LHT] ✓ Map Town12 already loaded
[DEBUG][LHT] Checking map: Carla/Maps/Town12/Town12
[DEBUG][LHT] OpenDrive header:
<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
    <header revMajor="1" revMinor="4" name="" version="1" date="2022-07-19T16:57:05" north="1.7586998257390694e+3" south="-6.5552663783476373e+3" east="4.1970842115782034e+3" west="-5.2494260710891067e+3" vendor="MathWorks">
        <geoReference><![CDATA[+proj=tmerc +lat_0=0 +lon_0=0 +k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +geoidgrids=egm96_15.gtx +vunits=m +no_defs ]]></geoReference>
        <userData>
            <vectorScene program="RoadRunner" version="R2022a Update 3 (1.4.3.171cebf5cc)"/>
        </userData>
    </header>

[CRITICAL] OpenDrive does not indicate LHT!
[WARN][LHT] Map is RHT - skipping LHT configuration
[INFO][LHT] TM sync mode: True
[DEBUG][LHT] Available TM methods:
  - auto_lane_change
  - collision_detection
  - distance_to_leading_vehicle
  - force_lane_change
  - get_all_actions
  - get_next_action
  - get_port
  - global_lane_offset
  - global_percentage_speed_difference
  - ignore_lights_percentage
  - ignore_signs_percentage
  - ignore_vehicles_percentage
  - ignore_walkers_percentage
  - keep_slow_lane_rule_percentage
  - random_left_lanechange_percentage
  - random_right_lanechange_percentage
  - set_boundaries_respawn_dormant_vehicles
  - set_desired_speed
  - set_global_distance_to_leading_vehicle
  - set_hybrid_physics_mode
  - set_hybrid_physics_radius
  - set_osm_mode
  - set_path
  - set_random_device_seed
  - set_respawn_dormant_vehicles
  - set_route
  - set_synchronous_mode
  - shut_down
  - update_vehicle_lights
  - vehicle_lane_offset
  - vehicle_percentage_speed_difference
  ```




```bash
cd /workspace/carla0916/CarlaUE4/Content/Carla/Maps/OpenDrive
rm -f Town*.xodr

# Restore RHT originals by removing .backup_rht extension
for f in *.backup_rht; do
    mv "$f" "${f%.backup_rht}"
done

# Do the same for Town12, Town13, Town15
for town in Town12 Town13 Town15; do
    cd /workspace/carla0916/CarlaUE4/Content/Carla/Maps/$town/OpenDrive
    rm -f Town*.xodr
    for f in *.backup_rht; do
        [ -f "$f" ] && mv "$f" "${f%.backup_rht}"
    done
done

# Verify restoration
echo "=== OpenDrive folder ==="
ls -lh /workspace/carla0916/CarlaUE4/Content/Carla/Maps/OpenDrive/ | grep -v backup

echo "=== Town12 ==="
ls -lh /workspace/carla0916/CarlaUE4/Content/Carla/Maps/Town12/OpenDrive/

echo "=== Town13 ==="
ls -lh /workspace/carla0916/CarlaUE4/Content/Carla/Maps/Town13/OpenDrive/

echo "=== Town15 ==="
ls -lh /workspace/carla0916/CarlaUE4/Content/Carla/Maps/Town15/OpenDrive/
```


```bash
cd /workspace
sudo rsync -av --progress --exclude='database/' --exclude='japanese_street/' --exclude='data/' --exclude='outputs' --exclude='pretrained/'  simlingo/ simlingo-michele-backup/
```







Now I was able to run the code using the Town form the just created stuff. th agent is running. this is the output of all the debug we have 

```bash
resources.html
  import pkg_resources
WARNING: No InMemoryMap cache found. Setting up local map. This may take a while... 
/workspace/simlingo/leaderboard21/leaderboard21/leaderboard_evaluator.py:83: DeprecationWarning: distutils Version classes are deprecated. Use packaging.version instead.
  if LooseVersion(dist.version) < LooseVersion('0.9.10'):
[DEBUG]: leaderboard21 is the leaderboard
[DEBUG]: leaderboard21 is the leaderboard
autopilot: using leaderboard21.autoagents (no autonomous_agent_local)
[INFO]: LHT patch ok via scenarioatomics

========= Preparing RouteScenario_0 (repetition 0) =========
> Loading the world
[LHT-DETECT] Analyzing Town12 for traffic rules...
[LHT-DETECT] Found XODR file: /workspace/carla0916/CarlaUE4/Content/Carla/Maps/Town12/OpenDrive/Town12.xodr
[LHT-DETECT] ✓✓✓ LEFT-HAND TRAFFIC MAP DETECTED ✓✓✓
[WORLD] Loading map: Town12
WARNING: No InMemoryMap cache found. Setting up local map. This may take a while... 
======================================================================
[LHT-CONFIG] Configuring for Left-Hand Traffic
======================================================================
[LHT-CONFIG] ✓ LHT mode configuration:
  → Environment: CARLA_MAP_IS_LHT=1
  → Current town: Town12
  → TM Port: 8000
  → TM Seed: 0
  → NOTE: CARLA 0.9.16 TM has limited LHT support
  → Agents must handle LHT at waypoint/navigation level
======================================================================
[WORLD] ✓ World ready: Town12
[WORLD] ✓ LHT mode ACTIVE - Agent-level navigation required
[ROUTE_SCENARIO] _get_route called, LHT=True
[INTERPOLATE] Checking interpolated route for LHT compatibility...
[ROUTE_SCENARIO] First route waypoint location: Location(x=983.592773, y=5381.887207, z=371.409302)
[ROUTE_SCENARIO] First waypoint lane_id: -1, road_id: 529
[ROUTE_SCENARIO] Spawning ego vehicle:
  Location: Location(x=983.592773, y=5381.887207, z=371.909302)
  Lane ID: -1
  Road ID: 529
  LHT mode: True
[RunningRedLightTest] Initialized with 1101 traffic lights (LHT=True)
[INFO] ✓ RunningRedLightTest initialized successfully
> Setting up the agent
[AUTOPILOT] set_global_plan called:
  - LHT mode: True
  - GPS plan: 8058 points
  - World plan: 8058 points
[AUTOPILOT] ✓ Populated org_dense_route_world_coord with 8058 waypoints
[DEBUG][LHT] API Source: /workspace/carla0916/PythonAPI/carla/dist/carla_0916_lib/carla/__init__.py
[INFO][LHT] Using FORCE_TOWN: Town12
[DEBUG][LHT] Target map required: Town12
[INFO][LHT] ✓ Map Town12 already loaded
[DEBUG][LHT] Checking loaded map: Town12
[INFO][LHT] Found XODR file: /workspace/carla0916/CarlaUE4/Content/Carla/Maps/Town12/OpenDrive/Town12.xodr
[INFO][LHT] ✓✓✓ XODR FILE VERIFIED AS LEFT-HAND TRAFFIC (rule="LHT") 
[INFO][LHT] Configuring Traffic Manager for LEFT-HAND TRAFFIC...
[INFO][LHT] Applied global_lane_offset(-0.5)
[INFO][LHT] ✓✓✓ All available LHT configurations applied
[INFO][LHT] TM sync mode: True
[INFO][LHT] Configuring Traffic Manager for LEFT-HAND TRAFFIC...
[INFO][LHT] ✓ Applied global_lane_offset(-0.5)
[INFO][LHT] ✓ Set scenario_runner21 CarlaDataProvider._is_lht_map = True
[INFO][LHT] ✓ Set srunner CarlaDataProvider._is_lht_map = True
[INFO] Moved existing run folder /workspace/simlingo/database/simlingo_carla0916_2_/Town12_Rep1_0_route0_01_27_16_11_47 -> /workspace/simlingo/database/simlingo_carla0916_2_/training_3_scenarios/routes_devtest/random_weather_seed_42_balanced_100/Town12_Rep1_0_route0_01_27_16_11_47
================================================================================
[INFO][DATA_AGENT_MULTICAMERAE] Output Configuration:
[INFO] Save Path: /workspace/simlingo/database/simlingo_carla0916_2_/training_3_scenarios/routes_devtest/random_weather_seed_42_balanced_100/Town12_Rep1_route0_01_27_16_11_55
[INFO] Using consolidated default: training_3_scenarios/routes_devtest (override with SAVE_SUBDIR)
[INFO] Data Collection (DATAGEN): True
[INFO] Route Index              : None
[INFO] Scenario                 : 
[INFO][OK] Directory exists but is empty - safe to proceed
================================================================================
[INFO][DATA_AGENT_MULTICAMERA] Created output directories in: /workspace/simlingo/database/simlingo_carla0916_2_/training_3_scenarios/routes_devtest/random_weather_seed_42_balanced_100/Town12_Rep1_route0_01_27_16_11_55
> Running the route
=== [Agent] -- Wallclock = 2026-01-27 16:11:59.292 -- System time = 0.000 -- Game time = 0.050 -- Ratio = 0.000x
[DEBUG][AUTOPILOT] Initializing with LHT mode: True
Sparse Waypoints: 103
Dense Waypoints : 8058
[DEBUG][GLOBAL_PLAN] Checking first item from leaderboard:
  Type: <class 'tuple'>
[DEBUG][DENSE_ROUTE] Checking first dense route waypoint:
[DEBUG][SPAWN] Vehicle spawned at: lane_id=-1, road_id=529
[OK][LHT] Vehicle spawned correctly on LHT lane -1
[DEBUG][SPAWN] Opposite lane: lane_id=1
[DEBUG][SPAWN] Current lane width: 3.0m
[DEBUG][SPAWN] Left lane exists: True, Right lane exists: True
[DEBUG][SPAWN] Left lane ID: 1
[DEBUG][SPAWN] Right lane ID: -2
[INFO][AUTOPILOT] ✓ Set PrivilegedRoutePlanner LHT mode: True
[ROUTE-PLANNER] setup_route called with LHT=True
[ROUTE-PLANNER] Global plan length: 8058
[ROUTE-PLANNER] Extracted 8058 locations from global_plan
[ROUTE-PLANNER] Successfully converted to 8058 waypoints
[ROUTE-PLANNER] Final route has 8109 waypoints
[ROUTE-PLANNER] After interpolation: 81115 waypoints
[DEBUG][ROUTE] Checking first 10 route waypoints:
  [0] road_id=529, lane_id=-1, lane_type=Driving
  [1] road_id=529, lane_id=-1, lane_type=Driving
...
  [8] road_id=529, lane_id=-1, lane_type=Driving
  [9] road_id=529, lane_id=-1, lane_type=Driving
[OK][LHT] Route correctly uses NEGATIVE lane_id -1
[DATA_AGENT_MULTICAMERA] Starting to save /workspace/simlingo/database/simlingo_carla0916_2_/training_3_scenarios/routes_devtest/random_weather_seed_42_balanced_100/Town12_Rep1_route0_01_27_16_11_55/rgb/0000/
[DEBUG][LHT] handle_actor_batch returned 4 actors
[DEBUG][LHT] CarlaDataProvider has _is_lht_map: True
[DEBUG][LHT] _is_lht_map value: True
[DEBUG][LHT] Processing actor 0: vehicle.dodge.charger_2020
[DEBUG][LHT] LHT map detected, checking if vehicle...
[DEBUG][LHT] Actor is a vehicle, checking role_name...
[DEBUG][LHT] Role name: background
[DEBUG][LHT] Applying LHT settings to vehicle.dodge.charger_2020...
[LHT]   ✓ auto_lane_change(False)
[LHT]   ✓ vehicle_lane_offset(-1.0)
[LHT]   ✓ random_left_lanechange_percentage(95.0)
[LHT]   ✓ random_right_lanechange_percentage(5.0)
[LHT]   ✓ keep_slow_lane_rule_percentage(98.0)
[LHT] ✓✓✓ Applied LHT to batch vehicle vehicle.dodge.charger_2020 (offset: -1.0)
[DEBUG][LHT] Processing actor 1: vehicle.mercedes.coupe_2020
[DEBUG][LHT] LHT map detected, checking if vehicle...
[DEBUG][LHT] Actor is a vehicle, checking role_name...
[DEBUG][LHT] Role name: background
[DEBUG][LHT] Applying LHT settings to vehicle.mercedes.coupe_2020...
[LHT]   ✓ auto_lane_change(False)
...
[DEBUG][LHT] Actor is a vehicle, checking role_name...
[DEBUG][LHT] Role name: background
[DEBUG][LHT] Applying LHT settings to vehicle.lincoln.mkz_2017...
[LHT]   ✓ auto_lane_change(False)
[LHT]   ✓ vehicle_lane_offset(-1.0)
[LHT]   ✓ random_left_lanechange_percentage(95.0)
[LHT]   ✓ random_right_lanechange_percentage(5.0)
[LHT]   ✓ keep_slow_lane_rule_percentage(98.0)
[LHT] ✓✓✓ Applied LHT to batch vehicle vehicle.lincoln.mkz_2017 (offset: -1.0)
[DEBUG][LHT] Single actor spawn: vehicle.mini.cooper_s_2021
[DEBUG][LHT] Has _is_lht_map: True
[DEBUG][LHT] _is_lht_map value: True
[DEBUG][LHT] Applying LHT to single actor vehicle.mini.cooper_s_2021...
[DEBUG][LHT] Single actor spawn: vehicle.mini.cooper_s_2021
[DEBUG][LHT] Has _is_lht_map: True
[LHT] ✓ Applied LHT to background vehicle (offset: -1.0)
=== [Agent] -- Wallclock = 2026-01-27 16:12:22.556 -- System time = 23.264 -- Game time = 0.100 -- Ratio = 0.004x
...
=== [Agent] -- Wallclock = 2026-01-2
```

However, checking the images collected the carl runs on  rht and the car are paked on the right of the street so the world is still very right hand traffic based. 
I am using this ```bash export ROUTE_CONFIG="routes_training"      
export ROUTES="/workspace/simlingo/${LEADERBOARD_VERSION}/data/${ROUTE_CONFIG}.xml"
export ROUTES_SUBSET="0"  ``` this is the firsr part of the .xml I am running 
```xml
<routes>
   <route id="0" town="Town12">
      <!-- Urbanization route focused on junction crossing vehicles -->
      <weathers>
         <weather route_percentage="0"
            cloudiness="5.0" precipitation="0.0" precipitation_deposits="0.0" wetness="0.0"
            wind_intensity="10.0" sun_azimuth_angle="-1.0" sun_altitude_angle="90.0" fog_density="2.0"/>
         <weather route_percentage="100"
            cloudiness="5.0" precipitation="0.0" precipitation_deposits="0.0" wetness="0.0"
            wind_intensity="10.0" sun_azimuth_angle="-1.0" sun_altitude_angle="15.0" fog_density="2.0"/>
      </weathers>
      <waypoints>
         <position x="983.5" y="5382.2" z="371"/>
         <position x="824.2" y="5575.3" z="371"/>
         <position x="605.5" y="5575.5" z="370"/>
         <position x="497.5" y="5718.3" z="368"/>
  ...
      
         <position x="-705.4" y="5204.9" z="376"/>
         <position x="-163.9" y="5404.6" z="372"/>
         <position x="75.0" y="5587.0" z="367.2"/>
      </waypoints>
      <scenarios>
         <scenario name="ParkingExit_1" type="ParkingExit">
            <trigger_point x="983.5" y="5382.2" z="371" yaw="90"/>
            <direction value="right"/>
            <front_vehicle_distance value="9"/>
            <behind_vehicle_distance value="9"/>
         </scenario>
         <scenario name="VehicleOpensDoorTwoWays_1" type="VehicleOpensDoorTwoWays">
            <trigger_point x="983.5" y="5442.8" z="371.2" yaw="90.1"/>
            <distance value="50"/>
            <frequency from="40" to="90"/>
         </scenario>
         <scenario name="OppositeVehicleRunningRedLight_1" type="OppositeVehicleRunningRedLight">
            <trigger_point x="830.4" y="5575.5" z="370.8" yaw="180.0"/>
         </scenario>
         <scenario name="HazardAtSideLane_1" type="HazardAtSideLane">
            <trigger_point x="753.9" y="5575.6" z="370.7" yaw="179.9"/>
            <distance value="50"/>
            <bicycle_drive_distance value="80"/>
 ...
```
can you underatad why I see a rht world still ?










