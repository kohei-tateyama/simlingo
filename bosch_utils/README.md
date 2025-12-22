# bosch_utils

This folder contains utility scripts, classes, and method used for dataset inspection, augmentation, and local image description tayloring the simLingo original repo onto the Japanese streets and Bosch ADAS paradigm.

The classes and files here can be run as stand-alone or trought the `script/run_carla_mp_pilot_script.sh`. Right now, we can run also the simlingo agent. I am pretty sure that we could use it to gather data, we would need to adopt method form the `(Long)JapaneseStyleAutopilot` class methods and enforce the Japanese driving rule. NOTE THAT this will most likely perform (very) bad.

The folder contains an subone, namely `/tools/`, that contains keys task for collection our own dataset.

## Overview of important files `bosch_utils/tools`
- `tools/open_gz.py`: Helpers for reading and summarizing json.gz file used from simlingo collected from the CARLA-based collector. 
- `tools/compare_structure.py`: Utilities to compare the structure of our data collection and the one from similingo.
- `tools/imgs_features.py`: Lists the imgs features exposing the difference between the imgs we recorded and the one from simlingo. 
- `tools/patch_multicamera.py`: Patched on a canvas rthe 6 images.
- `tools/augment_rgb_dataset.py`: [UNUSED] Function to augument the images from `rgb` creating the `rgb_augmented` folder. This function uses classic methods for changing the colors on the img. 
- `tool/gaussian_spatter_todo.py`: [UNUSED] Impleents a wannabe guassian splatter method but the imgs are way too rare at the moment. Thsi just compact the 6 imgs onto the cavas similarly as the `tools/patch_multicamera.py`.
- `tools/image_describer_todo.py`: [UNUSED] Local describer that writes json.gz per-image commentary and creates a sibling `rgb_augmented`.
  - Default behavior: writes sidecars next to images into `*_commentary/` folders (e.g. `rgb_commentary/0001.json.gz`).
    - Augmented layout: by default the script also creates sibling `*/rgb_augmented/<frame_stem>/` folders containing both a .jpg copy of the image (`<frame_stem>.jpg`) and a json.gz commentary file (`<frame_stem>.json.gz`).
    - Example: `rgb/0001.png` -> `rgb_augmented/0001/0001.jpg` and `rgb_augmented/0001/0001.json.gz`.
    - CLI flags of interest:
        - `--no-augmented`: only write the `_commentary` sidecars, do not create augmented folders.
        - `--aug-suffix`: change the augmented suffix (default `augmented`, so `rgb_augmented`).
        - `--jpeg-quality`: JPEG quality for saved augmented images (default `85`).
        - `--skip-commentary`: do not write `_commentary` sidecars (only create augmented pairs).
        - `--no-models`: disable BLIP/YOLO (safe mode: prevents large model downloads and uses template captions).
    - Notes and recommendations
        - Running with BLIP/YOLO enabled may download large model files (MB to multiple GB). Use `--no-models` For fast, local run that uses template captions.
        - The augmented layout is non-destructive: itr adds `rgb_augumented/`.
        - Not 100% where is best to implement the _commentary_. Now it is into `rgb_augumented/*.json.gz` rather than `mesurements/`.

## Overview of important files `bosch_utils/`
- `config_bosch_utils.yaml` / `config.py`: configuration values. Use `config.py` from Python to import the values.
- `japanese_driving_autopilot_cameras.py` (collector): CARLA autopilot using predfined waypoints and writer used to record training-format datasets. Note: this script writes `measurements/`, `boxes/`, `records.json.gz`, and `results.json.gz` used downstream. Note that this class enable the possibility to have semantics and segmentation from CARLA.
- `japanese_driving_autopilot_cameras_long.py` build upon the `japanese_driving_autopilot_cameras.py` (collector) CARLA autopilot using agent, namely `agents.navigation.global_route_planner import GlobalRoutePlanner` to have long run in any city. It returns the same files of the `japanese_driving_autopilot_cameras.py`. Scaling the time, the agent CARLA agent finds new paths and we have enforce the waypoint collection.
- `japanese_driving_autopilot.py`: Similar collector as `japanese_driving_autopilot_cameras.py`, but it only uses one camera.
- `japanese_driving_cameras_2btested.py`: [UNUSED] Similar collector as `japanese_driving_autopilot_cameras.py`, run not in an *headless* mode but spawn the CARLA city setup. Right now it needs to be tested.

## Overview of important files `bash/`

- `script/run_carla_mp_pilot_script.sh` most important one. PLEASE CHECK THE DOCUMENTATION, WE CAN VARY MANY MANY PARAM.
- `script/open_imgs_code.sh` givin the path, open, using an application (VS code default) the pictures. Check the helper for multple options.
- `script/getting_data_training.sh` [TOBETESTED] bash filed aimed at recording nall the new data. Run mutliple times the `script/run_carla_mp_pilot_script.sh` varying inputs. 
- `script/how_to_run_headless2_script.sh` run the simlingo agent headless. 
- `script/run_carla_mp_viz_pilot_script.sh` [UNUSED] similar to `script/run_carla_mp_pilot_script.sh` but spawn the city and the car.

[Example]: 
```bash
bash script/run_carla_mp_pilot_script.sh --mode autopilot --duration 40 --route urban --autopilot-long --spawn-index 10 --weather ClearNoon
code /workspace/simlingo/recording_japan_xml/database/simlingo_v3_2026_01_01/auto_long_multicam_jp/training_Town13_scenario/routes_urban_duration_40_training/ClearNoon_weather/ego_10/GPS.jps
bash ./script/open_imgs_code.sh /workspace/simlingo/recording_japan_xml/database/simlingo_v3_2026_01_01/auto_long_multicam_jp/training_Town13_scenario/routes_urban_duration_40_training/ClearNoon_weather/ego_10/  
```