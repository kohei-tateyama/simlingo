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

def get_cfg():
    return cfg
