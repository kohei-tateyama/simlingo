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
When `code` for opening imgs does not work, refresh the terminal
`export VSCODE_IPC_HOOK_CLI=$(ls -t /run/user/$(id -u)/vscode-ipc-*.sock | head -n 1)`

One-liner for opening multiple `.jpg` from the `rgb/` folder
`for ((i=0;i<=119;i+=10)); do a=$(printf "%04d" "$i"); b=$(printf "%04d" "$((i+10))"); code "$a/F.jpg" && code "$b/F.jpg"; done`
`for ((i=0;i<=798;i+=30)); do a=$(printf "%04d" "$i"); b=$(printf "%04d" "$((i+30))"); code "$a/patched2.jpg" && code "$b/patched2.jpg"; done`
`for ((i=0;i<=19157;i+=1200)); do a=$(printf "%04d" "$i"); b=$(printf "%04d" "$((i+1200))"); code "$a/patched2.jpg" && code "$b/patched2.jpg"; done`

One-liner to count the elements inside any folder 
`find . -mindepth 1 -maxdepth 1 | wc -l`