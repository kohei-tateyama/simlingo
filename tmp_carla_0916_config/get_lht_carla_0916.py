"""Scan CARLA map folders for .xodr files, back them up, and set rule="LHT" on OpenDRIVE root.

Backups are written next to the original file as <stem>.original_rht.xodr.
This script is intentionally small and safe; use --dry-run to preview changes.
"""

from pathlib import Path
import argparse
import xml.etree.ElementTree as ET
import shutil
import sys


def process_file(path: Path, backup_suffix: str = '.original_rht.xodr', dry_run: bool = False) -> bool:
    try:
        tree = ET.parse(path)
    except Exception as e:
        print(f"Skipping {path}: parse error: {e}")
        return False
    
    root = tree.getroot()
    # Find the header element inside the OpenDRIVE file
    header = root.find('header')
    
    # Handle cases with XML namespaces (common in some OpenDRIVE versions)
    if header is None:
        header = root.find('{http://www.opendrive.org/schema}header')

    if header is None:
        print(f"Skipping {path}: No <header> element found.")
        return False

    current_rule = header.get('rule')
    if current_rule == 'LHT':
        print(f"Already LHT: {path}")
        return False

    # Perform Backup before modifying
    backup = path.with_name(path.stem + backup_suffix)
    if not backup.exists() and not dry_run:
        shutil.copy2(path, backup)

    print(f"[INFO]: Setting rule=\"LHT\" in <header> for {path}")
    if not dry_run:
        header.set('rule', 'LHT')
        # Write back to file
        tree.write(path, encoding='utf-8', xml_declaration=True)
    return True


def main():
    parser = argparse.ArgumentParser(description='Add rule="LHT" to CARLA .xodr files (with backups)')
    parser.add_argument('--map-root', type=Path, default=Path('/workspace/carla0916/CarlaUE4/Content/Carla/Maps'), help='Root folder to scan for .xodr files')
    parser.add_argument('--dry-run', action='store_true', help='Show changes without writing files')
    args = parser.parse_args()

    root = args.map_root
    if not root.exists():
        print(f"[ERROR]: Map root does not exist: {root}")
        sys.exit(1)

    files = list(root.rglob('*.xodr'))
    if not files:
        print(f"[WARNING]: No .xodr files found under {root}")
        return

    for f in files:
        try:
            process_file(f, dry_run=args.dry_run)
        except Exception as e:
            print(f"[ERROR]: Error processing {f}: {e}")

    print('[INFO]: Done!')


if __name__ == '__main__':
    main()


# Setting rule="LHT" in <header> for /workspace/carla0916/CarlaUE4/Content/Carla/Maps/OpenDrive/Town02_Opt.xodr
# ...
# Setting rule="LHT" in <header> for /workspace/carla0916/CarlaUE4/Content/Carla/Maps/Town12/OpenDrive/Town12.xod
