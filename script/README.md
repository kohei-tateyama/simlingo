# Scripts (script/)

This folder contains bash entrypoints and helpers used to run CARLA-based data collection, local utilities and small helpers used by maintainers.

The list below gives a short description of each active script, common usage examples and troubleshooting tips.

## Main scripts

- `common.sh`: Shared shell helpers and logging functions (`info()`, `warn()`, `err()`, `sep()`) sourced by other scripts. If you see `sep: command not found`, make sure callers `source ./common.sh` before using helpers.

- `getting_data_training_carla0916.sh`: Helper to prepare environment and mounts for CARLA 0.9.16 data collection. Use when collecting data targeted at Carla 0.9.16 images and containers.

- `getting_data_training.sh`: Generic data collection setup helper (non-CARLA-specific variants).

- `open_imgs_code.sh`: Quick developer helper to open images and related code (local convenience script used by maintainers).

- `run_carla_mp_pilot_script_carla0916.sh`: Wrapper to start CARLA in multiplayer mode and run the pilot/agent inside the same host/container for Carla 0.9.16.

- `run_carla_mp_pilot_script.sh`: Generic multiplayer pilot launcher for other CARLA versions.

## Collection runners

- `test_data_agent_japanese_timeout_all.sh`: Run a set of Japanese routes with timeouts and logging. Designed to iterate many routes and robustly capture failures.

- `test_data_agent_multicamera_carla0916.sh`: Single-run data collection wrapper for CARLA 0.9.16 (non-batch). It starts a CARLA container, pre-loads the target town map, runs the leaderboard/agent and captures logs and outputs.

- `test_data_agent_multicamera_timeout_all_carla0916.sh`: Batch runner for CARLA 0.9.16 that iterates a routes subset with per-route logging, pre-loading of town maps and a longer `client.load_world()` timeout. Useful for collecting many routes in sequence.

- `test_data_agent_multicamera_timeout_all.sh`: Generic batch runner (non-CARLA-specific) used for multi-run experiments.

## Deprecated scripts
- `how_to_run_headless2_script.sh`, `test_data_agent_multicamera.sh`, `run_carla_mp_viz_pilot_script.sh`, `test_data_agent_japanese.sh` — kept for historical reference only.




