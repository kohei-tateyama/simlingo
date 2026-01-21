# Scripts (script/)

This folder contains bash entrypoints and helpers used to run carla-based data collection, local utilities and small helpers used by maintainers.

The list below gives a short description of each active script, common usage examples and troubleshooting tips.

## Utils scripts

- `common.sh`: Shared shell helpers and logging functions (`info()`, `warn()`, `err()`, `sep()`) sourced by other scripts. If you see `sep: command not found`, make sure callers `source ./common.sh` before using helpers. I will also add multiple shared fucntion across this project in the folllowing days.

- `open_imgs_code.sh`: Quick helper to open images and related code. Used for checking the simlingo and our database consistency.


## carla 0.9.15

The **LHT** here is the results of ours hardcoding effort.

- `getting_data_training.sh`: <mark>[OURS]</mark> Generic data collection in carla 0.9.15 via `script/run_carla_mp_pilot_script.sh` that calls, depending on the `MODE` one of the following code `bosch_utils/japanese_driving_autopilot_cameras.py`, `bosch_utils/japanese_driving_autopilot_cameras_mp.py`, `bosch_utils/japanese_driving_autopilot.py`, `bosch_utils/japanese_driving_autopilot_cameraa_long.py`. The main software ones used for massive data collection are `bosch_utils/japanese_driving_autopilot_cameras_mp.py` and `bosch_utils/japanese_driving_autopilot_cameras_long.py`, and they run carla 0.9.15, our **LHT**, and `GlobalPlanner`.

- `run_carla_mp_pilot_script.sh`: <mark>[OURS]</mark> Wrapper to start carla in multiplayer mode and run the pilot/agent inside the same host/container for carla 0.9.15. The main software ones used for massive data collection are `bosch_utils/japanese_driving_autopilot_cameras_mp.py` and `bosch_utils/japanese_driving_autopilot_cameras_long.py`, and they run carla 0.9.15, our **LHT**, and `GlobalPlanner`. Multicamera.

- `test_data_agent_multicamera_timeout_all.sh`: <mark>[FROM SIMLINGO]</mark> Generic batch runner carla 0.9.15 used for multi-run experiments. Mullticamera. **RHT**, this call the `team_code/data_agent_multicamera.py` which implement a multicamera version of the classic simlingo data collection.

- `test_data_agent_japanese_timeout_all.sh`: <mark>[FROM SIMLINGO]</mark> Run a set of Japanese routes with timeouts carla 0.9.15. **LHT**. Designed to iterate many routes and robustly capture failures calling the leaderboard/agent calling `team_code/data_agent_japanese.py`. This deprecates `script/test_data_agent_japanese.sh` allowing multiple runs. 

## carla 0.9.16

The **RHT** here is the provided by the official release of carla 0.9.16.

- `getting_data_training_carla0916.sh`: <mark>[OURS]</mark> Generic data collection in carla 0.9.16 data collection via `run_carla_mp_pilot_script_carla0916` that calls `bosch_utils/japanese_driving_autopilot_cameras_mp_carla0916.py`, which runs carla 0.9.16, carla 0.9.16 **LHT**, and `GlobalPlanner`.

- `run_carla_mp_pilot_script_carla0916.sh`: <mark>[OURS]</mark> Wrapper to start carla in multiplayer mode and run the pilot/agent inside the same host/container for carla 0.9.16. It runs carla 0.9.16, carla 0.9.16 **LHT**, and `GlobalPlanner`. Multicamera.

- `test_data_agent_multicamera_timeout_all_carla0916.sh`: <mark>[FROM SIMLINGO]</mark> Batch runner Single-run data collection wrapper for carla 0.9.16. It starts a carla container, pre-loads the target town map, runs the leaderboard/agent via `team_code/data_agent_multicamera_carla0916.py`. **LHT**. The leaderbaord agent runs _games_ and to kill any of these we set a timeout. Useful for collecting many routes in sequenc. This script deprecated `script/test_data_agent_multicamera_carla0916.sh` since it allows multiple run of it.


## Deprecated scripts
- `how_to_run_headless2_script.sh`, `test_data_agent_multicamera.sh`, `run_carla_mp_viz_pilot_script.sh`, `test_data_agent_japanese.sh`, `test_data_agent_multicamera_carla0916.sh`. They are kept for historical reference only.



