"""
Batch patch multicamera RGB folders in a dataset directory.

This script finds all rgb/<frame> folders in a dataset and creates patched
images using patch_multicamera.py. It runs after data collection completes.

Usage:
    # Patch a specific dataset folder
    python bosch_utils/tools/batch_patch_multicamera.py /path/to/dataset/folder
    
    # Auto-discover latest dataset in recording_japan_xml
    python bosch_utils/tools/batch_patch_multicamera.py --auto-latest
    
    # Specify layout (geometric or grid)
    python bosch_utils/tools/batch_patch_multicamera.py /path/to/dataset --layout grid
"""

import sys
import argparse
from pathlib import Path
import subprocess
import time

# Import the patching functions from patch_multicamera
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from bosch_utils.tools.patch_multicamera import load_camera_images, create_geometric_patch, create_simple_layout_patch
from bosch_utils.config import cfg, RECORDING_OUTPUT_DIR, SIMLINGO_VERSION_DIR
import cv2
from bosch_utils.config import IMAGE_EXT


# def find_latest_dataset(base_dir="/workspace/simlingo/recording_japan_xml/database"):
def find_latest_dataset(base_dir=RECORDING_OUTPUT_DIR):
    """Find the most recently modified dataset folder"""
    base_path = Path(base_dir)
    if not base_path.exists():
        return None
    
    # Find all dataset folders (they should contain rgb/ and measurements/)
    dataset_folders = []
    for path in base_path.rglob("*"):
        if path.is_dir() and (path / "rgb").exists() and (path / "measurements").exists():
            dataset_folders.append(path)
    
    if not dataset_folders:
        return None
    
    # Return the most recently modified
    latest = max(dataset_folders, key=lambda p: p.stat().st_mtime)
    return latest


def find_rgb_folders(dataset_path):
    """Find all rgb/<frame> folders containing multicamera images"""
    rgb_path = Path(dataset_path) / "rgb"
    if not rgb_path.exists():
        print(f"[ERROR]: rgb folder not found in {dataset_path}")
        return []
    
    # Find all frame folders (e.g., rgb/0000, rgb/0001, ...)
    frame_folders = []
    for item in sorted(rgb_path.iterdir()):
        if item.is_dir():
            # Check if it contains the 6 camera images
            required_cameras = [f'F{IMAGE_EXT}', f'B{IMAGE_EXT}', f'LF{IMAGE_EXT}', f'RF{IMAGE_EXT}', f'LB{IMAGE_EXT}', f'RB{IMAGE_EXT}']
            if all((item / cam).exists() for cam in required_cameras):
                frame_folders.append(item)
    
    return frame_folders


def patch_single_folder(folder_path, layout='geometric', output_name='patched.png'):
    """Patch a single rgb/<frame> folder"""
    try:
        # Load images
        images = load_camera_images(folder_path)
        
        # Create patch based on layout
        if layout == 'geometric':
            patched = create_geometric_patch(images)
        else:
            patched = create_simple_layout_patch(images)
        
        # Save output
        output_path = folder_path / output_name
        cv2.imwrite(str(output_path), patched)
        return True
    except Exception as e:
        print(f"[ERROR]: Failed to patch {folder_path}: {e}")
        return False


def batch_patch(dataset_path, layout='geometric', output_name='patched.png', verbose=True):
    """Patch all rgb folders in a dataset"""
    dataset_path = Path(dataset_path)
    
    if verbose:
        # print(f"[INFO]: Scanning dataset    : {dataset_path}")
        print(f"[INFO]: Scanning dataset: {dataset_path}")
    
    # Find all rgb folders
    rgb_folders = find_rgb_folders(dataset_path)
    
    if not rgb_folders:
        print(f"[ERROR]: No multicamera rgb folders found in {dataset_path}")
        return False
    
    if verbose:
        print(f"[INFO]: Found {len(rgb_folders)} rgb folders to patch")
        print(f"[INFO]: Layout          : {layout}")
        print(f"[INFO]: Output filename : {output_name}")
    
    # Patch each folder
    success_count = 0
    start_time = time.time()
    
    for i, folder in enumerate(rgb_folders):
        if verbose and (i % 20 == 0 or i == len(rgb_folders) - 1):
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (len(rgb_folders) - i - 1) / rate if rate > 0 else 0
            print(f"[INFO]: Patching {i+1}/{len(rgb_folders)} ({100*(i+1)/len(rgb_folders):.1f}%) | "
                  f"Rate: {rate:.1f} frames/s | ETA: {eta:.1f}s")
        
        if patch_single_folder(folder, layout=layout, output_name=output_name):
            success_count += 1
    
    elapsed = time.time() - start_time
    
    if verbose:
        print(f"[INFO]: Patching complete!")
        print(f"[INFO]: Successfully patched : {success_count}/{len(rgb_folders)} folders")
        print(f"[INFO]: Total time           : {elapsed:.1f}s ({success_count/elapsed:.1f} frames/s)")
    
    return success_count == len(rgb_folders)


def main():
    parser = argparse.ArgumentParser(
        description='Batch patch multicamera RGB folders in a dataset',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Patch a specific dataset
  python batch_patch_multicamera.py /workspace/simlingo/recording_japan_xml/database/.../ego_42
  
  # Auto-discover and patch latest dataset
  python batch_patch_multicamera.py --auto-latest
  
  # Use grid layout instead of geometric
  python batch_patch_multicamera.py --auto-latest --layout grid
        """
    )
    
    parser.add_argument('dataset_path', type=str, nargs='?',
                       help='Path to dataset folder containing rgb/ subfolder')
    parser.add_argument('--auto-latest', action='store_true',
                       help='Automatically find and patch the latest dataset')
    parser.add_argument('--layout', type=str, default='geometric',
                       choices=['geometric', 'grid'],
                       help='Patching layout (default: geometric)')
    parser.add_argument('--output-name', type=str, default='patched' + IMAGE_EXT,
                       help=f'Output filename for patched images (default: patched{IMAGE_EXT})')
    parser.add_argument('--quiet', action='store_true',
                       help='Suppress progress messages')
    
    args = parser.parse_args()
    
    # Determine dataset path
    if args.auto_latest:
        print("[INFO]: Auto-discovering latest dataset...")
        dataset_path = find_latest_dataset()
        if dataset_path is None:
            print("[ERROR]: Could not find any dataset folders")
            sys.exit(1)
        print(f"[INFO]: Found latest dataset: {dataset_path}")
    elif args.dataset_path:
        dataset_path = args.dataset_path
    else:
        parser.print_help()
        print("\n[ERROR]: Please provide dataset_path or use --auto-latest")
        sys.exit(1)
    
    # Run batch patching
    success = batch_patch(
        dataset_path,
        layout=args.layout,
        output_name=args.output_name,
        verbose=not args.quiet
    )
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

