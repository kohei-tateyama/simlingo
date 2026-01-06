"""

This script finds all rgb/<frame> folders in a dataset and creates patched
images using patch_multicamera.py. It runs after data collection completes.

Usage:
    # Patch a specific dataset folder
    python bosch_utils/tools/batch_patch_multicamera.py /path/to/dataset/folder
    
    ###
    python /workspace/simlingo/bosch_utils/tools/batch_patch_multicamera2.py /workspace/simlingo/recording_japan_xml/autopilot_multicamera_japanese_highway_20251212_150258/rgb/0000 --layout three_quarter --output-name patched2
    
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
import numpy as np


def create_three_quarter_patch(images: dict):
    """
    Compose images into the requested 3/4 (left) vs 1/4 (right) layout.

    - Left 3/4: split vertically into two halves: F (top) and B (bottom).
    - Right 1/4: stack LF, LR, BF, BR vertically.
    """
    # Determine base image size
    base = images.get('F') if images.get('F') is not None else images.get('B')
    if base is None:
        raise ValueError("No base image available (F or B required)")

    H, W = base.shape[:2]
    left_w = int(W * 0.75)
    right_w = W - left_w

    # Create blank canvas
    canvas = 255 * np.ones((H, W, 3), dtype=base.dtype)

    def place(img, y, x, h, w, label, increase_height=False):
        if img is not None:  # Explicitly check for None
            resized = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
            canvas[y:y+h, x:x+w] = resized

            # Add label
            label_bg_h = int(h * 0.1 if increase_height else h * 0.05)  # Increased height for right-side labels
            label_bg_w = int(w * 0.15)  # Width of the label background
            label_bg_x = x + 5  # Padding from the top-left corner of the image
            label_bg_y = y + 5

            # # Draw white rectangle for label background
            # cv2.rectangle(canvas, (label_bg_x, label_bg_y),
            #               (label_bg_x + label_bg_w, label_bg_y + label_bg_h),
            #               (255, 255, 255), -1)

            # Add text label
            font_scale = 0.5
            thickness = 2
            # text_color = (0, 0, 0)  # Black text
            text_color = (0, 255, 255)  # Yellow text
            cv2.putText(canvas, label, (label_bg_x + 5, label_bg_y + label_bg_h - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, font_scale, text_color, thickness, lineType=cv2.LINE_AA)

    # Left 3/4: F (top) and B (bottom)
    top_h = H // 2
    bottom_h = H - top_h
    place(images.get('F'), 0, 0, top_h, left_w, 'F')
    place(images.get('B'), top_h, 0, bottom_h, left_w, 'B')

    # Right 1/4: stack LF, LR, BF, BR vertically
    stacked_h = H // 4
    place(images.get('LB'), 0, left_w, stacked_h, right_w, 'LB', increase_height=True)
    place(images.get('LF'), stacked_h, left_w, stacked_h, right_w, 'LF', increase_height=True)
    place(images.get('RB'), 2 * stacked_h, left_w, stacked_h, right_w, 'RB', increase_height=True)
    place(images.get('RF'), 3 * stacked_h, left_w, stacked_h, right_w, 'RF', increase_height=True)

    return canvas


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
    p = Path(dataset_path)

    # Accept both JPG and PNG extensions (some recordings use PNG)
    alt_exts = [IMAGE_EXT, '.png'] if IMAGE_EXT != '.png' else ['.png', '.jpg']

    def has_all_cameras(folder: Path) -> bool:
        # detect which extension exists in this folder and validate presence
        for ext in alt_exts:
            cams = [f'F{ext}', f'B{ext}', f'LF{ext}', f'RF{ext}', f'LB{ext}', f'RB{ext}']
            if all((folder / cam).exists() for cam in cams):
                return True
        return False

    # Case 1: dataset_path is a single frame folder that already contains the 6 images
    if p.is_dir() and has_all_cameras(p):
        return [p]

    # Determine the rgb search base: prefer explicit rgb/ subfolder, otherwise use provided path
    rgb_path = (p / 'rgb') if (p / 'rgb').exists() else p

    if not rgb_path.exists() or not rgb_path.is_dir():
        print(f"[ERROR]: rgb folder not found in {dataset_path}")
        return []

    # Find all frame folders (e.g., rgb/0000, rgb/0001, ...)
    frame_folders = []
    for item in sorted(rgb_path.iterdir()):
        if item.is_dir():
            if has_all_cameras(item):
                frame_folders.append(item)

    # If no subfolders are found, check if the current folder itself contains images
    if not frame_folders and has_all_cameras(rgb_path):
        frame_folders.append(rgb_path)

    return frame_folders


def patch_single_folder(folder_path, layout='geometric', output_name='patched'):
    """Patch a single rgb/<frame> folder"""
    try:
        # Ensure output_name has a valid extension
        if not output_name.lower().endswith(('.png', '.jpg', '.jpeg')):
            output_name += IMAGE_EXT

        # Load images
        images = load_camera_images(folder_path)

        # Create patch based on layout
        if layout == 'geometric':
            patched = create_geometric_patch(images)
        elif layout == 'three_quarter':
            patched = create_three_quarter_patch(images)
        else:
            patched = create_simple_layout_patch(images)

        # Save output
        output_path = folder_path / output_name
        cv2.imwrite(str(output_path), patched)
        return True
    except Exception as e:
        print(f"[ERROR]: Failed to patch {folder_path}: {e}")
        return False


def batch_patch(dataset_path, layout='three_quarter', output_name='patched.png', verbose=True):
    """Patch all rgb folders in a dataset"""
    dataset_path = Path(dataset_path)

    if verbose:
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
    parser.add_argument('--layout', type=str, default='three_quarter',
                       choices=['geometric', 'grid', 'three_quarter'],
                       help='Patching layout (default: three_quarter)')
    parser.add_argument('--output-name', type=str, default='patched2' + IMAGE_EXT,
                       help=f'Output filename for patched images (default: patched2{IMAGE_EXT})')
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
