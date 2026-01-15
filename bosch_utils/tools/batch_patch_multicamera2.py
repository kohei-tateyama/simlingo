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
        # Place an image into the canvas slot using a 'cover' strategy:
        # resize the image to fill the slot (no stretching) then center-crop
        # so the slot is fully covered with no padding.
        if img is None:
            return

        # Ensure image has 3 channels
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        elif img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

        ih, iw = img.shape[:2]
        if iw == 0 or ih == 0:
            return

        # Compute scale to fill the slot (cover)
        scale = max(float(w) / float(iw), float(h) / float(ih))
        new_w = max(1, int(round(iw * scale)))
        new_h = max(1, int(round(ih * scale)))

        # Resize while preserving aspect ratio (fills the slot)
        resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # Center-crop to (w,h)
        start_x = max(0, (new_w - w) // 2)
        start_y = max(0, (new_h - h) // 2)
        cropped = resized[start_y:start_y + h, start_x:start_x + w]

        # If crop is smaller than slot (edge cases), pad to fit
        if cropped.shape[0] != h or cropped.shape[1] != w:
            slot = 255 * np.ones((h, w, 3), dtype=base.dtype)
            ch, cw = cropped.shape[:2]
            off_x = (w - cw) // 2
            off_y = (h - ch) // 2
            slot[off_y:off_y+ch, off_x:off_x+cw] = cropped
            canvas[y:y+h, x:x+w] = slot
        else:
            canvas[y:y+h, x:x+w] = cropped

        # Add label (positioned relative to canvas)
        label_bg_h = int(h * 0.1 if increase_height else h * 0.05)
        label_bg_w = int(w * 0.15)
        label_bg_x = x + 5
        label_bg_y = y + 5

        font_scale = max(0.2, label_bg_h / 20.0)
        thickness = 1 if font_scale < 0.6 else 2
        text_color = (0, 255, 255)  # Yellow text
        cv2.putText(canvas, label, (label_bg_x + 5, label_bg_y + label_bg_h - 1),
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


def create_three_quarter_patch_big(images: dict):
    """
    Create a 'big' three-quarter patch that arranges images in the same layout as
    `create_three_quarter_patch` but without enforcing a fixed canvas size. The
    canvas size is dynamically determined based on the spatial dimensions of the
    input images.

    - Left 3/4: split vertically into two halves: F (top) and B (bottom).
    - Right 1/4: stack LF, LR, BF, BR vertically.

    The spatial dimensions of the images are preserved.
    """
    # Determine the maximum dimensions for each section
    def size_of(k):
        img = images.get(k)
        if img is None:
            return 0, 0
        return img.shape[0], img.shape[1]

    fh, fw = size_of('F')
    bh, bw = size_of('B')
    lb_h, lb_w = size_of('LB')
    lf_h, lf_w = size_of('LF')
    rb_h, rb_w = size_of('RB')
    rf_h, rf_w = size_of('RF')

    # For 'big' patch we will place every image at its native size (no crop,
    # no resize) and stack tightly. This removes internal white padding — the
    # canvas will be the minimal bounding box containing all placed images.

    # We want F and B to be displayed at double size. Compute their scaled
    # dimensions first, then compute left/right column sizes and canvas.
    scale_fb = 2.0
    sfh = int(round(fh * scale_fb)) if fh > 0 else 0
    sfw = int(round(fw * scale_fb)) if fw > 0 else 0
    sbh = int(round(bh * scale_fb)) if bh > 0 else 0
    sbw = int(round(bw * scale_fb)) if bw > 0 else 0

    # left column dimensions now based on scaled F/B
    left_w = max(sfw, sbw)
    left_h = sfh + sbh

    # right column dimensions unchanged (native sizes)
    right_w = max(lb_w, lf_w, rb_w, rf_w)
    right_h = lb_h + lf_h + rb_h + rf_h

    canvas_w = left_w + right_w
    canvas_h = max(left_h, right_h)

    base = next((img for img in images.values() if img is not None), None)
    if base is None:
        raise ValueError("No images provided")

    canvas = 255 * np.ones((canvas_h, canvas_w, 3), dtype=base.dtype)

    def ensure_bgr(img):
        if img is None:
            return None
        if img.ndim == 2:
            return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        if img.shape[2] == 4:
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        return img

    def paste_native(img, y, x, label=None, increase_height=False, scale=1.0):
        img = ensure_bgr(img)
        if img is None:
            return
        ih, iw = img.shape[:2]
        if ih <= 0 or iw <= 0:
            return

        # apply scaling (for F/B we will pass scale=2.0)
        if scale != 1.0:
            new_w = max(1, int(round(iw * scale)))
            new_h = max(1, int(round(ih * scale)))
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
            ih, iw = img.shape[:2]

        # horizontally center within its column
        col_w = left_w if x == 0 else right_w
        off_x = x + (col_w - iw) // 2 if col_w > iw else x
        off_y = y

        # place image (clip to canvas bounds if necessary)
        oy0 = off_y
        ox0 = off_x
        oy1 = min(canvas_h, off_y + ih)
        ox1 = min(canvas_w, off_x + iw)
        sy0 = 0
        sx0 = 0
        sy1 = oy1 - oy0
        sx1 = ox1 - ox0
        if oy0 < oy1 and ox0 < ox1:
            canvas[oy0:oy1, ox0:ox1] = img[sy0:sy1, sx0:sx1]

        # draw label
        if label:
            label_bg_h = int(ih * 0.05)
            label_bg_x = x + 5
            label_bg_y = y + 5
            font_scale = max(0.2, label_bg_h / 20.0)
            thickness = 1 if font_scale < 0.6 else 2
            text_color = (0, 255, 255)
            cv2.putText(canvas, label, (label_bg_x + 5, label_bg_y + label_bg_h - 1),
                        cv2.FONT_HERSHEY_SIMPLEX, font_scale, text_color, thickness, lineType=cv2.LINE_AA)

    # Left column: place F then B at 2x scale
    y = 0
    if fh > 0:
        paste_native(images.get('F'), y, 0, label='F', scale=scale_fb)
        y += sfh
    if bh > 0:
        paste_native(images.get('B'), y, 0, label='B', scale=scale_fb)
        y += sbh

    # Right column: place LB, LF, RB, RF stacked tightly (native sizes)
    y = 0
    rx = left_w
    if lb_h > 0:
        paste_native(images.get('LB'), y, rx, label='LB', increase_height=True)
        y += lb_h
    if lf_h > 0:
        paste_native(images.get('LF'), y, rx, label='LF', increase_height=True)
        y += lf_h
    if rb_h > 0:
        paste_native(images.get('RB'), y, rx, label='RB', increase_height=True)
        y += rb_h
    if rf_h > 0:
        paste_native(images.get('RF'), y, rx, label='RF', increase_height=True)
        y += rf_h

    # Downscale final big canvas by 2x to reduce file dimensions (e.g., 3072x2048 -> 1536x1024)
    try:
        target_w = max(1, canvas.shape[1] // 2)
        target_h = max(1, canvas.shape[0] // 2)
        small = cv2.resize(canvas, (target_w, target_h), interpolation=cv2.INTER_AREA)
        return small
    except Exception:
        return canvas


def create_patch_nuscenes(images: dict):
    """
    Create a 2x3 grid patch (nuscenes-style) sized exactly 1024x512.

    - Grid: 2 rows x 3 columns (6 cameras)
    - Each tile will be resized to fit its slot while preserving aspect ratio
      and padded with white to ensure all tiles have identical shape.
    - Expected keys in `images`: F, B, LB, LF, RB, RF (order mapped into grid)
    """
    # Determine camera order (left->right top then bottom)
    cam_order = ['LF', 'F', 'RF', 'LB', 'B', 'RB']

    # Collect native sizes for present images
    widths = []
    heights = []
    for cam in cam_order:
        img = images.get(cam)
        if img is None:
            continue
        h, w = img.shape[:2]
        if h > 0 and w > 0:
            widths.append(w)
            heights.append(h)

    # Fallback defaults
    default_tile_w = 341
    default_tile_h = 256

    if widths and heights:
        # use median native tile size as a starting point
        med_w = int(np.median(widths))
        med_h = int(np.median(heights))
        med_ar = float(med_w) / float(med_h) if med_h > 0 else 1.0

        # clamp tile width to reasonable bounds to avoid huge canvases
        tile_w = int(np.clip(med_w, 160, 512))
        # compute tile_h to roughly respect median aspect ratio
        tile_h = max(120, int(round(tile_w / med_ar)))
    else:
        tile_w = default_tile_w
        tile_h = default_tile_h

    # Build canvas for 2 rows x 3 cols
    canvas_w = tile_w * 3
    canvas_h = tile_h * 2

    # Cap canvas height to at most half the width (2:1 ratio) to avoid excessive vertical white
    max_h = max(120, canvas_w // 2)
    if canvas_h > max_h:
        canvas_h = max_h
        tile_h = max(64, canvas_h // 2)

    canvas = 255 * np.ones((canvas_h, canvas_w, 3), dtype=np.uint8)
    offset_x = 0
    offset_y = 0

    def ensure_bgr(img):
        if img is None:
            return None
        if img.ndim == 2:
            return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        if img.shape[2] == 4:
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        return img

    def fit_and_place(img, top, left, h, w, cam_name=None):
        img = ensure_bgr(img)
        if img is None:
            return
        ih, iw = img.shape[:2]
        if ih == 0 or iw == 0:
            return

        # compute scale to fit within tile (contain)
        scale = min(float(w) / float(iw), float(h) / float(ih))
        new_w = max(1, int(round(iw * scale)))
        new_h = max(1, int(round(ih * scale)))
        resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # create slot and paste centered
        slot = 255 * np.ones((h, w, 3), dtype=canvas.dtype)
        off_x = (w - new_w) // 2
        off_y = (h - new_h) // 2
        slot[off_y:off_y+new_h, off_x:off_x+new_w] = resized

        canvas[top:top+h, left:left+w] = slot

        # Draw camera label at top-left of the tile for clarity
        if cam_name:
            label_text = cam_name
            # estimate label box size
            label_h = max(12, int(h * 0.08))
            font_scale = max(0.2, label_h / 25.0)
            thickness = 1 if font_scale < 0.6 else 2
            (tx_w, tx_h), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
            rect_x0 = left + 4
            rect_y0 = top + 4
            rect_x1 = rect_x0 + tx_w + 8
            rect_y1 = rect_y0 + tx_h + 6
            # black background for readability
            cv2.rectangle(canvas, (rect_x0, rect_y0), (rect_x1, rect_y1), (0, 0, 0), cv2.FILLED)
            # yellow text
            cv2.putText(canvas, label_text, (rect_x0 + 4, rect_y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 255, 255), thickness, lineType=cv2.LINE_AA)

    # place each camera
    for idx, cam in enumerate(cam_order):
        row = 0 if idx < 3 else 1
        col = idx % 3
        top = offset_y + row * tile_h
        left = offset_x + col * tile_w
        fit_and_place(images.get(cam), top, left, tile_h, tile_w, cam_name=cam)

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
            # Save output
            output_path = folder_path / output_name
            cv2.imwrite(str(output_path), patched)
            return True
        elif layout == 'three_quarter':
            # Create standard-sized patch and save as output_name
            # If user requested the nuscenes-style output name, create that instead
            if 'nuscenes' in output_name or 'patched3_nuscenes' in output_name:
                patched = create_patch_nuscenes(images)
            else:
                patched = create_three_quarter_patch(images)
            output_path = folder_path / output_name
            # Downscale patched image by 30% 
            try:
                scale_main = 0.7
                h, w = patched.shape[:2]
                small_main = cv2.resize(patched, (max(1, int(round(w * scale_main))), max(1, int(round(h * scale_main)))), interpolation=cv2.INTER_AREA)
                saved_main = cv2.imwrite(str(output_path), small_main)
            except Exception:
                saved_main = cv2.imwrite(str(output_path), patched)

            # Also create the 'big' patch and save with _big suffix before extension
            name = output_name
            stem, ext = (name.rsplit('.', 1) + [''])[:2]
            if ext == '':
                ext = IMAGE_EXT.lstrip('.')
            big_name = f"{stem}_big.{ext}"
            big_path = folder_path / big_name
            try:
                patched_big = create_three_quarter_patch_big(images)
                try:
                    scale_big = 0.7
                    h, w = patched_big.shape[:2]
                    small_big = cv2.resize(patched_big, (max(1, int(round(w * scale_big))), max(1, int(round(h * scale_big)))), interpolation=cv2.INTER_AREA)
                    saved_big = cv2.imwrite(str(big_path), small_big)
                except Exception:
                    saved_big = cv2.imwrite(str(big_path), patched_big)
            except Exception as e:
                print(f"[WARN]: Failed to create _big patch for {folder_path}: {e}")
                saved_big = False

            # Also always create a nuscenes-style patch (1024x512) and save as <stem>_nuscenes.<ext>
            nus_name = f"{stem}_nuscenes.{ext}"
            nus_path = folder_path / nus_name
            try:
                patched_nus = create_patch_nuscenes(images)
                try:
                    scale_nus = 0.7
                    h, w = patched_nus.shape[:2]
                    small_nus = cv2.resize(patched_nus, (max(1, int(round(w * scale_nus))), max(1, int(round(h * scale_nus)))), interpolation=cv2.INTER_AREA)
                    saved_nus = cv2.imwrite(str(nus_path), small_nus)
                except Exception:
                    saved_nus = cv2.imwrite(str(nus_path), patched_nus)
            except Exception as e:
                print(f"[WARN]: Failed to create nuscenes patch for {folder_path}: {e}")
                saved_nus = False

            return bool(saved_main) or bool(saved_big)
        else:
            patched = create_simple_layout_patch(images)
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
            # print(f"[INFO]: Patching {i+1}/{len(rgb_folders)} ({100*(i+1)/len(rgb_folders):.1f}%) | "
            #       f"Rate: {rate:.1f} frames/s | ETA: {eta:.1f}s")

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

