#!/usr/bin/env python3
"""
Gaussian Spatter compositor for 6 CARLA cameras

Reads the same input folder format as `patch_multicamera.py` (F.png, B.png, RF.png, LF.png, RB.png, LB.png)
and produces a single patched top-down-like image by placing each camera image on a canvas
and blending overlaps using per-camera Gaussian weight maps (a simple 'spatter' strategy).

Usage:
    python gaussian_spatter.py /path/to/frame_folder --output patched_spatter.png

This is intentionally a single-file, one-class-like implementation (class `GaussianSpatter`).

python3 /Users/pim1yh/Desktop/from_pc_fixed/gaussian_spatter.py \
    /workspace/simlingo/recording_japan_xml/<run>/rgb/0000 \
    --output patched_spatter.png \
    --sigma 1.2 \
    --scale 3.0
    
"""

import cv2
import numpy as np
from pathlib import Path
import argparse

# Camera configuration (same layout used by patch_multicamera)
CAMERA_KEYS = ['F', 'B', 'RF', 'LF', 'RB', 'LB']
CAMERA_CONFIG = {
    'F':  {'pos': [2.5, 0.0],   'yaw': 0},
    'B':  {'pos': [-2.5, 0.0],  'yaw': 180},
    'RF': {'pos': [1.0, 1.0],   'yaw': 55},
    'LF': {'pos': [1.0, -1.0],  'yaw': -55},
    'RB': {'pos': [-1.0, 1.0],  'yaw': 125},
    'LB': {'pos': [-1.0, -1.0], 'yaw': -125},
}

VEHICLE_LENGTH = 5.0
VEHICLE_WIDTH = 2.0


class GaussianSpatter:
    """One-class implementation of Gaussian spatter compositor."""
    def __init__(self, canvas_scale=3.0, sigma_meters=1.0, bg_color=(255,255,255)):
        # canvas_scale: how many reference image widths/heights to allocate around center
        self.canvas_scale = canvas_scale
        # sigma for gaussian weight in meters (controls blending radius)
        self.sigma_m = float(sigma_meters)
        self.bg_color = tuple(int(c) for c in bg_color)

    def load_images(self, folder_path: Path):
        imgs = {}
        for k in CAMERA_KEYS:
            p = folder_path / f"{k}.png"
            if not p.exists():
                raise FileNotFoundError(f"Missing camera image: {p}")
            img = cv2.imread(str(p))
            if img is None:
                raise ValueError(f"Failed to read image: {p}")
            imgs[k] = img
        return imgs

    def _rotate_image(self, image: np.ndarray, angle_deg: float):
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
        cos = np.abs(M[0, 0])
        sin = np.abs(M[0, 1])
        nW = int((h * sin) + (w * cos))
        nH = int((h * cos) + (w * sin))
        M[0, 2] += (nW / 2) - center[0]
        M[1, 2] += (nH / 2) - center[1]
        rotated = cv2.warpAffine(image, M, (nW, nH), borderMode=cv2.BORDER_CONSTANT, borderValue=self.bg_color)
        return rotated

    def _gaussian_kernel(self, h, w, sigma_px):
        # Create separable gaussian kernel using outer product
        if sigma_px <= 0.5:
            # fallback to uniform mask
            return np.ones((h, w), dtype=np.float32)
        ky = cv2.getGaussianKernel(h, sigma_px)
        kx = cv2.getGaussianKernel(w, sigma_px)
        kernel = (ky @ kx.T).astype(np.float32)
        # normalize to max 1
        kernel /= kernel.max()
        return kernel

    def compose(self, images: dict, output_size=None):
        # reference image
        ref = images['F']
        ih, iw = ref.shape[:2]

        # choose output_size equal to reference if not provided
        if output_size is None:
            output_size = (iw, ih)

        # Create canvas large enough: canvas_scale * ref size
        canvas_w = int(output_size[0] * self.canvas_scale)
        canvas_h = int(output_size[1] * self.canvas_scale)

        # Background accumulators: numerator for RGB and denominator for weights
        accum_rgb = np.zeros((canvas_h, canvas_w, 3), dtype=np.float32)
        accum_w = np.zeros((canvas_h, canvas_w), dtype=np.float32)

        # meters-to-pixel scale: determine by fitting vehicle dims into canvas
        # heuristic: vehicle_length corresponds to about output height / 3
        px_per_m = min(canvas_h / (VEHICLE_LENGTH * 3.0), canvas_w / (VEHICLE_WIDTH * 3.0))

        # canvas center (car location)
        center_x = canvas_w // 2
        center_y = canvas_h // 2

        # For each camera: rotate, compute gaussian weight map, paste with weighted accumulation
        for key, cfg in CAMERA_CONFIG.items():
            img = images[key]

            # rotate camera image according to yaw so that its forward points 'up' on canvas
            yaw = cfg['yaw']
            # For front camera yaw=0 we don't rotate; for others rotating by yaw aligns view
            rotated = self._rotate_image(img, -yaw)

            rh, rw = rotated.shape[:2]

            # compute placement center in pixels
            cam_x_m = cfg['pos'][0]
            cam_y_m = cfg['pos'][1]
            px_x = int(center_x + cam_y_m * px_per_m)
            px_y = int(center_y - cam_x_m * px_per_m)

            # compute Gaussian sigma in pixels from sigma_m
            sigma_px = max(1.0, self.sigma_m * px_per_m)

            # generate gaussian kernel same size as rotated image
            kernel = self._gaussian_kernel(rh, rw, sigma_px)

            # mask where rotated image is not background color
            # background defined as near-white (255,255,255)
            mask = np.any(rotated < 250, axis=2).astype(np.float32)

            # combined weight = mask * kernel
            weight = (mask * kernel).astype(np.float32)

            # Region on canvas
            x1 = px_x - rw // 2
            y1 = px_y - rh // 2
            x2 = x1 + rw
            y2 = y1 + rh

            # compute overlap with canvas
            cx1 = max(0, x1)
            cy1 = max(0, y1)
            cx2 = min(canvas_w, x2)
            cy2 = min(canvas_h, y2)

            if cx1 >= cx2 or cy1 >= cy2:
                continue

            sx1 = cx1 - x1
            sy1 = cy1 - y1
            sx2 = sx1 + (cx2 - cx1)
            sy2 = sy1 + (cy2 - cy1)

            # slice arrays
            region_img = rotated[sy1:sy2, sx1:sx2].astype(np.float32)
            region_w = weight[sy1:sy2, sx1:sx2]

            # accumulate
            accum_rgb[cy1:cy2, cx1:cx2, :] += region_img * region_w[:, :, None]
            accum_w[cy1:cy2, cx1:cx2] += region_w

        # Normalize accumulators to produce final image
        out = np.zeros_like(accum_rgb, dtype=np.uint8)
        wmask = accum_w > 1e-6
        out[wmask] = (accum_rgb[wmask] / accum_w[wmask, None]).clip(0,255).astype(np.uint8)
        out[~wmask] = np.array(self.bg_color, dtype=np.uint8)

        # Crop center region equal to output_size
        crop_x = center_x - output_size[0] // 2
        crop_y = center_y - output_size[1] // 2
        crop_x = max(0, min(crop_x, canvas_w - output_size[0]))
        crop_y = max(0, min(crop_y, canvas_h - output_size[1]))
        cropped = out[crop_y:crop_y+output_size[1], crop_x:crop_x+output_size[0]]

        return cropped


def main():
    parser = argparse.ArgumentParser(description='Gaussian spatter compositor for 6-camera CARLA frames')
    parser.add_argument('folder', type=str, help='Folder with F.png,B.png,RF.png,LF.png,RB.png,LB.png')
    parser.add_argument('--output', type=str, default='patched_spatter.png', help='Output filename')
    parser.add_argument('--sigma', type=float, default=1.0, help='Gaussian sigma in meters')
    parser.add_argument('--scale', type=float, default=3.0, help='Canvas scale (relative to output size)')
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.exists():
        raise SystemExit(f'Folder not found: {folder}')

    sp = GaussianSpatter(canvas_scale=args.scale, sigma_meters=args.sigma)
    images = sp.load_images(folder)
    result = sp.compose(images)

    out_path = folder / args.output
    cv2.imwrite(str(out_path), result)
    print(f'[INFO] Saved spatter-patched image to: {out_path} (size: {result.shape[1]}x{result.shape[0]})')


if __name__ == '__main__':
    main()
