# bosch_utils

This folder contains utility scripts, classes, and method used for dataset inspection, augmentation, and local image description tayloring the SimLingo original repo onto the Japanese streets and Bosch ADAS paradigm.

Overview of important files
- `config_bosch_utils.yaml` / `config.py`: configuration values. Use `config.py` from Python to import the values.
- `tools/open_gz.py`: Helpers for reading and summarizing gzipped JSON artifacts (measurements, boxes, records, results) produced by the CARLA-based collector. Useful for quick structural checks.
- `tools/compare_structure.py`: Utilities to compare the structure of two run folders. Uses defaults from `config.py`.
- `tools/image_describer_todo.py`: Local image describer that writes gzipped per-image commentary JSON sidecars and — optionally — creates a sibling `rgb_augmented` style layout.
  - Default behavior: writes sidecars next to images into `*_commentary/` folders (e.g. `rgb_commentary/0001.json.gz`).
  - Augmented layout: by default the script also creates sibling `<image_folder>_augmented/<frame_stem>/` folders containing both a JPEG copy of the image (`<frame_stem>.jpg`) and a gzipped JSON commentary file (`<frame_stem>.json.gz`). Example: `rgb/0001.png` -> `rgb_augmented/0001/0001.jpg` and `rgb_augmented/0001/0001.json.gz`.
  - CLI flags of interest:
    - `--no-augmented`: only write the `_commentary` sidecars, do not create augmented folders.
    - `--aug-suffix`: change the augmented suffix (default `augmented`, so `rgb_augmented`).
    - `--jpeg-quality`: JPEG quality for saved augmented images (default `85`).
    - `--skip-commentary`: do not write `_commentary` sidecars (only create augmented pairs).
    - `--no-models`: disable BLIP/YOLO (safe mode: prevents large model downloads and uses template captions).

- `japanese_driving_autopilot_cameras.py` (collector): CARLA autopilot agent and writer used to record training-format datasets. Note: this script writes `measurements/`, `boxes/`, `records.json.gz`, and `results.json.gz` used downstream.

Usage examples
- Describe a folder and create augmented layout (safe, no models):

```bash
python simlingo/bosch_utils/tools/image_describer_todo.py /path/to/run/rgb -r \
  --no-models --aug-suffix augmented --jpeg-quality 85
```

- Only create sidecars and skip augmented folders:

```bash
python simlingo/bosch_utils/tools/image_describer_todo.py /path/to/run/rgb -r \
  --no-augmented
```

Notes and recommendations
- Running with BLIP/YOLO enabled may download large model files (several hundred MB to multiple GB). Use `--no-models` if you want a fast, local-only run that uses template captions.
- The augmented layout is non-destructive: it writes sibling folders and does not alter existing `rgb/` or `measurements/` files.
- If you prefer commentary embedded into `measurements/*.json.gz` rather than sidecars, request that change explicitly — it is destructive (in-place edits of measurements) and I will add a separate option for that.

If you want, I can run a safe sample on a directory you point to and report back with exact created file paths.
