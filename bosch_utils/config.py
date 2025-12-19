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
