import os
from pathlib import Path
import yaml

# Resolve repo root relative to this package
_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
_CFG_PATH = _HERE / 'config_bosch_utils.yaml'


def _load_cfg(path: Path):
    try:
        with path.open('r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


cfg = _load_cfg(_CFG_PATH)

# RECORDING_OUTPUT_DIR: prefer YAML, then env var, then sensible default under repo
RECORDING_OUTPUT_DIR = (
    cfg.get('RECORDING_OUTPUT_DIR')
    or os.environ.get('RECORDING_OUTPUT_DIR')
    or str(_REPO_ROOT / 'recording_japan_xml')
)

SIMLINGO_VERSION_DIR = (
    cfg.get('SIMLINGO_VERSION_DIR')
    or os.environ.get('SIMLINGO_VERSION_DIR')
    or str(_REPO_ROOT / 'simlingo_v5_2026_01_05')
)

NEW_SIMLINGO_MATCH = (
    cfg.get('NEW_SIMLINGO_MATCH')
    or os.environ.get('NEW_SIMLINGO_MATCH')
    or str(_REPO_ROOT / '/workspace/simlingo/database/simlingo_v4_bosch_2025_01_10/data/simlingo/')
)

# Default run/dataset directory (optional). If present in the YAML, use it.
DEFAULT_RUN_DIR = cfg.get('DEFAULT_RUN_DIR') or os.environ.get('DEFAULT_RUN_DIR') or None

# Default comparison folders (optional)
DEFAULT_SIM = cfg.get('DEFAULT_SIM') or os.environ.get('DEFAULT_SIM') or None
DEFAULT_OURS = cfg.get('DEFAULT_OURS') or os.environ.get('DEFAULT_OURS') or None


def get_default_run_rgb():
    """Return a Path to the `rgb` directory inside the default run, or None.

    Example: if DEFAULT_RUN_DIR points to .../ego_43, returns .../ego_43/rgb
    """
    if not DEFAULT_RUN_DIR:
        return None
    p = Path(DEFAULT_RUN_DIR)
    rgb = p / 'rgb'
    return rgb

def get_cfg():
    return cfg

# Image format preferences (can be overridden in config_bosch_utils.yaml)
IMAGE_FORMAT = (cfg.get('IMAGE_FORMAT') or os.environ.get('IMAGE_FORMAT') or 'PNG').upper()
IMAGE_EXT = '.jpg' if IMAGE_FORMAT == 'JPG' else '.png'
JPG_QUALITY = int(cfg.get('JPG_QUALITY') or os.environ.get('JPG_QUALITY') or 85)
PNG_COMPRESS_LEVEL = int(cfg.get('PNG_COMPRESS_LEVEL') or os.environ.get('PNG_COMPRESS_LEVEL') or 9)


# --- Additional typed access for common BOSCH parameters ---
def _get_val(key: str, default=None):
    """Fetch a config value from YAML `cfg` or environment, falling back to default."""
    if key in cfg and cfg.get(key) is not None:
        return cfg.get(key)
    env = os.environ.get(key)
    if env is not None:
        return env
    return default


def _get_float(key: str, default: float) -> float:
    v = _get_val(key, default)
    try:
        return float(v)
    except Exception:
        return default


def _get_int(key: str, default: int) -> int:
    v = _get_val(key, default)
    try:
        return int(float(v))
    except Exception:
        return default


# LEFT HAND TRAFFIC / safety / offsets
SET_GLOBAL_DISTANCE_TO_LEADING_VEHICLE = _get_float('SET_GLOBAL_DISTANCE_TO_LEADING_VEHICLE', 2.5)
MARGIN = _get_float('MARGIN', 0.1)
GLOBAL_LANE_OFFSET = _get_float('GLOBAL_LANE_OFFSET', -0.8)

DEFAULT_LANE_W = _get_float('DEFAULT_LANE_W', 3.5)
DEFAULT_VEHICLE_HALF_W = _get_float('DEFAULT_VEHICLE_HALF_W', 0.9)
MIN_SAFE_DISTANCE_SAFE = _get_float('MIN_SAFE_DISTANCE_SAFE', 0.02)
MAX_SAFE_DISTANCE_SAFE = _get_float('MAX_SAFE_DISTANCE_SAFE', 2.0)
MAX_DISTANCE_SAFE = _get_float('MAX_DISTANCE_SAFE', 2.5)
MIN_DISTANCE_SAFE = _get_float('MIN_DISTANCE_SAFE', -2.5)

MAX_DETECT_INFRASTRUCTURE_OFFSET = _get_float('MAX_DETECT_INFRASTRUCTURE_OFFSET', 50.0)
MIN_NORMALIZATION_SCALE = _get_float('MIN_NORMALIZATION_SCALE', 0.001)
OFFSET_1 = _get_float('OFFSET_1', 0.7)
OFFSET_2 = _get_float('OFFSET_2', 0.3)

# Additional driving parameters
SAMPLING_RESOLUTION = _get_float('SAMPLING_RESOLUTION', 2.0)
AVERAGE_SPEEDS_MPS = _get_float('AVERAGE_SPEEDS_MPS', 11.1)

MIN_DISTANCE_TARGET = _get_float('MIN_DISTANCE_TARGET', 0.7)
MAX_DISTANCE_TARGET = _get_float('MAX_DISTANCE_TARGET', 1.5)
NEARBY_POINTS = _get_float('NEARBY_POINTS', 50.0)


def get_bosch_param(key: str, default=None):
    """Convenience accessor for code that wants dynamic lookup by key."""
    # first check exported top-level variables
    if key in globals():
        return globals()[key]
    return _get_val(key, default)

