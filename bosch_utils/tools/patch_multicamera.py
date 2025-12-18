## Very fast implementation of patching 6 img
"""
Assuming a Standard CARLA vehicles (e.g., Tesla Model 3, Prius, Audi A2):
Length: ~4.5-5.0 meters
Width: ~1.8-2.0 meters
Height: ~1.4-1.6 meters
Wheelbase: ~2.8 meters
patch_multicamera.py - Patch 6 CARLA cameras into geometric bird's-eye layout

Usage:
    python bosch_utils/patch_multicamera.py /workspace/simlingo/recording_japan_xml/autopilot_multicamera_japanese_highway_20251212_150258/rgb/0000
"""

import cv2
import numpy as np
from pathlib import Path
import argparse
import math
from bosch_utils.config import IMAGE_EXT

# Camera configuration 
CAMERA_CONFIG = {
    'F':  {'pos': [2.5, 0.0, 1.5],   'yaw': 0,    'name': 'Front'},
    'B':  {'pos': [-2.5, 0.0, 1.5],  'yaw': 180,  'name': 'Back'},
    'RF': {'pos': [1.0, 1.0, 1.5],   'yaw': 55,   'name': 'Right Front'},
    'LF': {'pos': [1.0, -1.0, 1.5],  'yaw': -55,  'name': 'Left Front'},
    'RB': {'pos': [-1.0, 1.0, 1.5],  'yaw': 125,  'name': 'Right Back'},
    'LB': {'pos': [-1.0, -1.0, 1.5], 'yaw': -125, 'name': 'Left Back'},
}

# Vehicle dimensions (CARLA standard)
VEHICLE_LENGTH = 5.0  # meters
VEHICLE_WIDTH = 2.0   # meters

#######################################
### HARCODED TWEAKS 
# Placement tweaks: allow horizontal stretching (move left/right further out) and vertical compression (bring forward/back cameras closer to center). Adjust these multipliers to tweak the visual layout.
HORIZONTAL_MULT = 3.25  # >1 moves left/right cameras further out (increased per request)
VERTICAL_MULT = 0.6   # <1 brings front/back cameras closer to center
# Per-side vertical spread: values >1 increase separation between the front/back pair on that side (LF vs LB, RF vs RB).
LEFT_VERTICAL_SPREAD = 1.5
RIGHT_VERTICAL_SPREAD = 1.5
IMAGE_SCALE_MULTIPLIER = 1.08
#######################################

def focal_px_from_fov(image_width_px, fov_deg):
    return image_width_px / (2.0 * math.tan(math.radians(fov_deg) / 2.0))

def pixels_per_meter_from_camera(image_width_px, fov_deg, distance_m):
    f_px = focal_px_from_fov(image_width_px, fov_deg)
    return f_px / max(1e-6, distance_m)

def load_camera_images(folder_path):
    """Load all 6 camera images from folder"""
    folder = Path(folder_path)
    
    images = {}
    for cam_key in CAMERA_CONFIG.keys():
        img_path = folder / f"{cam_key}{IMAGE_EXT}"
        if not img_path.exists():
            raise FileNotFoundError(f"Camera image not found: {img_path}")
        
        img = cv2.imread(str(img_path))
        if img is None:
            raise ValueError(f"Failed to load image: {img_path}")
        images[cam_key] = img
    
    return images


def create_geometric_patch(images, output_size=None):
    """
    Create geometric patch maintaining camera positions and orientations
    
    Layout (bird's eye view, Y-axis inverted for image coordinates):
    
        LF        F        RF
         ╲        |        ╱
          ╲       |       ╱
           ╲      |      ╱
            ╲     |     ╱
    LB ──────   [CAR]   ────── RB
              ╱   |   ╲
             ╱    |    ╲
            ╱     |     ╲
           ╱      |      ╲
                  B
    """
    # Get reference image size
    ref_img = images['F']
    img_h, img_w = ref_img.shape[:2]
    
    # Use the reference input image size for the output (as requested)
    output_size = (img_w, img_h)
    
    # Create output canvas (3x larger to accommodate all cameras)
    canvas_w = output_size[0] * 3
    canvas_h = output_size[1] * 3
    # Use white background (user said white parts are fine)
    canvas = np.full((canvas_h, canvas_w, 3), 255, dtype=np.uint8)
    
    # Calculate scaling factor (pixels per meter)
    scale = min(canvas_w / (VEHICLE_WIDTH * 3), canvas_h / (VEHICLE_LENGTH * 3))
    
    # Canvas center (where car is)
    center_x = canvas_w // 2
    center_y = canvas_h // 2
    
    # Scale images so their longer side corresponds to 3 meters on the canvas (pixels_per_meter * 3). 
    # Preserve aspect ratio and paste images without rotation.
    pixels_per_meter = scale

    #######################################
    ### HARCODED TWEAKS 
    #######################################

    # # Placement tweaks: allow horizontal stretching (move left/right further out) and vertical compression (bring forward/back cameras closer to center). Adjust these multipliers to tweak the visual layout.
    # HORIZONTAL_MULT = 3.25  # >1 moves left/right cameras further out (increased per request)
    # VERTICAL_MULT = 0.6   # <1 brings front/back cameras closer to center
    # # Per-side vertical spread: values >1 increase separation between the front/back pair on that side (LF vs LB, RF vs RB).
    # LEFT_VERTICAL_SPREAD = 1.5
    # RIGHT_VERTICAL_SPREAD = 1.5
    # IMAGE_SCALE_MULTIPLIER = 1.08


    target_size_px = max(1, int(round(pixels_per_meter * 3.0 * IMAGE_SCALE_MULTIPLIER)))

    for cam_key, config in CAMERA_CONFIG.items():
        img = images[cam_key]

        # Preserve aspect ratio: scale longer side to target_size_px
        h0, w0 = img.shape[:2]
        if w0 >= h0:
            new_w = target_size_px
            new_h = max(1, int(round(h0 * (target_size_px / float(w0)))))
        else:
            new_h = target_size_px
            new_w = max(1, int(round(w0 * (target_size_px / float(h0)))))

        img_resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # Calculate position on canvas using camera coordinates (meters -> pixels)
        cam_x_meters = config['pos'][0]
        cam_y_meters = config['pos'][1]
        # Apply multipliers: horizontal expands lateral offset.
        canvas_x = int(center_x + cam_y_meters * pixels_per_meter * HORIZONTAL_MULT)

        # Vertical compression typically applies to all cameras; apply a
        # small per-side spread multiplier so LF/LB and RF/RB separate more.
        side_mult = 1.0
        if cam_key in ('LF', 'LB'):
            side_mult = LEFT_VERTICAL_SPREAD
        elif cam_key in ('RF', 'RB'):
            side_mult = RIGHT_VERTICAL_SPREAD

        canvas_y = int(center_y - cam_x_meters * pixels_per_meter * VERTICAL_MULT * side_mult)

        # Paste without rotation
        place_image_on_canvas(canvas, img_resized, canvas_x, canvas_y)
    
    # Vehicle outline and labels removed per request (no arrow, no colored overlays)
    
    # Crop to output size (centered on vehicle)
    crop_x = center_x - output_size[0] // 2
    crop_y = center_y - output_size[1] // 2
    cropped = canvas[crop_y:crop_y+output_size[1], crop_x:crop_x+output_size[0]]
    
    return cropped


def rotate_image(image, angle):
    """Rotate image by angle (degrees)"""
    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    
    # Get rotation matrix
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    
    # Calculate new image size to fit rotated image
    cos = np.abs(M[0, 0])
    sin = np.abs(M[0, 1])
    new_w = int((h * sin) + (w * cos))
    new_h = int((h * cos) + (w * sin))
    
    # Adjust rotation matrix for new size
    M[0, 2] += (new_w / 2) - center[0]
    M[1, 2] += (new_h / 2) - center[1]
    
    # Rotate (use white background for padded areas)
    rotated = cv2.warpAffine(image, M, (new_w, new_h),
                            borderMode=cv2.BORDER_CONSTANT,
                            borderValue=(255, 255, 255))
    return rotated


def place_image_on_canvas(canvas, img, center_x, center_y):
    """Place image on canvas centered at (center_x, center_y)"""
    h, w = img.shape[:2]
    canvas_h, canvas_w = canvas.shape[:2]
    
    # Calculate placement bounds
    y1 = max(0, center_y - h // 2)
    y2 = min(canvas_h, center_y + h // 2)
    x1 = max(0, center_x - w // 2)
    x2 = min(canvas_w, center_x + w // 2)
    
    # Calculate source bounds (in case of clipping)
    src_y1 = max(0, h // 2 - center_y)
    src_y2 = src_y1 + (y2 - y1)
    src_x1 = max(0, w // 2 - center_x)
    src_x2 = src_x1 + (x2 - x1)
    
    # Direct paste: copy the region from the rotated image to the canvas
    img_crop = img[src_y1:src_y2, src_x1:src_x2]
    if img_crop.size == 0:
        return
    canvas[y1:y2, x1:x2] = img_crop


def draw_vehicle_outline(canvas, center_x, center_y, scale):
    """Draw vehicle outline on canvas"""
    # Vehicle dimensions in pixels
    veh_length_px = int(VEHICLE_LENGTH * scale)
    veh_width_px = int(VEHICLE_WIDTH * scale)
    
    # Rectangle corners (centered, forward is up)
    x1 = center_x - veh_width_px // 2
    x2 = center_x + veh_width_px // 2
    y1 = center_y - veh_length_px // 2
    y2 = center_y + veh_length_px // 2
    
    # Draw rectangle
    cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 255, 255), 2)
    
    # Draw front indicator (arrow)
    arrow_start = (center_x, center_y)
    arrow_end = (center_x, y1 - 20)
    cv2.arrowedLine(canvas, arrow_start, arrow_end, (0, 255, 0), 3, tipLength=0.3)
    
    # Label
    cv2.putText(canvas, "FRONT", (center_x - 30, y1 - 30),
               cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)


def create_simple_layout_patch(images, output_size=None):
    """
    Simpler approach: Grid layout preserving geometry
    
    Layout:

              F 
        LF        RF
        
        LB   CAR   RB
        
             B
    """
    ref_img = images['F']
    img_h, img_w = ref_img.shape[:2]
    
    if output_size is None:
        output_size = (img_w, img_h)
    
    # Resize all images to same size
    cell_w = output_size[0] // 3
    cell_h = output_size[1] // 3
    
    resized_images = {
        key: cv2.resize(img, (cell_w, cell_h))
        for key, img in images.items()
    }
    
    # Create canvas (white background)
    canvas = np.full((cell_h * 3, cell_w * 3, 3), 255, dtype=np.uint8)
    
    # Place images in grid
    # Row 0: LF, F, RF
    canvas[0:cell_h, 0:cell_w] = resized_images['LF']
    canvas[0:cell_h, cell_w:cell_w*2] = resized_images['F']
    canvas[0:cell_h, cell_w*2:cell_w*3] = resized_images['RF']
    
    # Row 1: LB, empty center, RB
    canvas[cell_h:cell_h*2, 0:cell_w] = resized_images['LB']
    canvas[cell_h:cell_h*2, cell_w*2:cell_w*3] = resized_images['RB']
    
    # Row 2: Empty, B, Empty
    canvas[cell_h*2:cell_h*3, cell_w:cell_w*2] = resized_images['B']
    
    return canvas


def main():
    parser = argparse.ArgumentParser(description='Patch CARLA multi-camera images')
    parser.add_argument('folder', type=str, 
                       help='Path to folder containing camera images (F.png, B.png, etc.)')
    parser.add_argument('--layout', type=str, default='geometric', 
                       choices=['geometric', 'grid'],
                       help='Patching layout: geometric (rotated cameras) or grid (simple)')
    parser.add_argument('--output-name', type=str, default='patched' + IMAGE_EXT,
                       help='Output filename')
    
    args = parser.parse_args()
    
    # Load images
    print(f"[INFO]: Loading images from: {args.folder}")
    images = load_camera_images(args.folder)
    print(f"[INFO]: Loaded {len(images)} camera images")
    
    # Create patch
    if args.layout == 'geometric':
        print("[INFO]: Creating geometric patch (with rotations)...")
        patched = create_geometric_patch(images)
    else:
        print("[INFO]: Creating grid layout patch...")
        patched = create_simple_layout_patch(images)
    
    # Save output
    output_path = Path(args.folder) / args.output_name
    cv2.imwrite(str(output_path), patched)
    print(f"[INFO]: Saved patched image to: {output_path}")
    print(f"[INFO]: Output size: {patched.shape[1]}x{patched.shape[0]}")


if __name__ == "__main__":
    main()

# image_w = 800          # sensor['image_size_x']
# fov = 90.0             # sensor['fov']
# d = 10.0               # chosen representative distance in metres
# ppx_per_m = pixels_per_meter_from_camera(image_w, fov, d)