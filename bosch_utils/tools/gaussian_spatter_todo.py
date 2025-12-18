"""
Gaussian Spatter compositor for 6 CARLA cameras

Reads the same input folder format as `patch_multicamera.py` (F.png, B.png, RF.png, LF.png, RB.png, LB.png)
and produces a single patched top-down-like image by placing each camera image on a canvas
and blending overlaps using per-camera Gaussian weight maps (a simple 'spatter' strategy).

Usage:
    python gaussian_spatter.py /path/to/frame_folder --output patched_spatter.png

python3 bosch_utils/gaussian_spatter.py \
    /workspace/simlingo/recording_japan_xml/<run>/rgb/0000 \
    --output patched_spatter.png \
    --sigma 1.2 \
    --scale 3.0 \
    --hard-assign --weight-mode prod


python3 /workspace/simlingo/bosch_utils/gaussian_spatter_todo.py /workspace/simlingo/recording_japan_xml/autopilot_multicamera_japanese_highway_20251212_150258/rgb/0000 --sigma 1.2 --scale 3.0 --hard-assign --weight-mode prod --sigma-fwd-mult 1.0 --sigma-lat-mult 0.6

python3 /workspace/simlingo/bosch_utils/gaussian_spatter_todo.py /workspace/simlingo/recording_japan_xml/autopilot_multicamera_japanese_highway_20251212_150258/rgb/0000 --sigma 1.2 --scale 3.0 --hard-assign --weight-mode prod --sigma-fwd-mult 1.0 --sigma-lat-mult 0.55 --curvature-power 1.6 --central-boost 0.8 --central-boost-sigma 0.8

code /workspace/simlingo/recording_japan_xml/autopilot_multicamera_japanese_highway_20251212_150258/rgb/0000/patched_spatter.png /workspace/simlingo/recording_japan_xml/autopilot_multicamera_japanese_highway_20251212_150258/rgb/0000/patched_spatter_weights.png /workspace/simlingo/recording_japan_xml/autopilot_multicamera_japanese_highway_20251212_150258/rgb/0000/patched_spatter_argmax.png
 rm -r ./patched_*
"""

import cv2
import numpy as np
from pathlib import Path
import argparse
from bosch_utils.config import IMAGE_EXT

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
            p = folder_path / f"{k}{IMAGE_EXT}"
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

        # Create canvas large enough: canvas_scale * ref size (keep same heuristic as patch_multicamera)
        canvas_w = int(output_size[0] * self.canvas_scale)
        canvas_h = int(output_size[1] * self.canvas_scale)

        # Background accumulators: numerator for RGB and denominator for weights
        accum_rgb = np.zeros((canvas_h, canvas_w, 3), dtype=np.float32)
        accum_w = np.zeros((canvas_h, canvas_w), dtype=np.float32)

        # meters-to-pixel scale: same heuristic as patch_multicamera
        pixels_per_meter = min(canvas_w / (VEHICLE_WIDTH * 3.0), canvas_h / (VEHICLE_LENGTH * 3.0))

        # canvas center (car location)
        center_x = canvas_w // 2
        center_y = canvas_h // 2

        # Placement tweak constants (keep in sync with patch_multicamera)
        HORIZONTAL_MULT = 3.25
        VERTICAL_MULT = 0.6
        LEFT_VERTICAL_SPREAD = 1.5
        RIGHT_VERTICAL_SPREAD = 1.5
        IMAGE_SCALE_MULTIPLIER = 1.08

        # For each camera: resize (preserving aspect), compute placement with same math as patch_multicamera,
        # compute distance+direction weights, and accumulate. We do NOT rotate input images for placement
        # so the geometry matches the `patch_multicamera.py` layout.
        per_camera_accum = {k: np.zeros((canvas_h, canvas_w), dtype=np.float32) for k in CAMERA_KEYS}
        # per-camera raw RGB (unweighted) and mask accumulators for hard-assign/comparison
        per_camera_rgb = {k: np.zeros((canvas_h, canvas_w, 3), dtype=np.float32) for k in CAMERA_KEYS}
        per_camera_mask = {k: np.zeros((canvas_h, canvas_w), dtype=np.float32) for k in CAMERA_KEYS}
        camera_info = {}
        for key, cfg in CAMERA_CONFIG.items():
            img = images[key]
            yaw = cfg['yaw']
            # precompute forward unit vector from yaw for diagnostics
            yaw_rad = np.deg2rad(float(yaw))
            f_x = np.sin(yaw_rad)
            f_y = np.cos(yaw_rad)

            # Resize preserving aspect ratio: longer side -> target_size_px
            target_size_px = max(1, int(round(pixels_per_meter * 3.0 * IMAGE_SCALE_MULTIPLIER)))
            h0, w0 = img.shape[:2]
            if w0 >= h0:
                new_w = target_size_px
                new_h = max(1, int(round(h0 * (target_size_px / float(w0)))))
            else:
                new_h = target_size_px
                new_w = max(1, int(round(w0 * (target_size_px / float(h0)))))

            img_resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
            rh, rw = img_resized.shape[:2]

            # Compute placement using patch_multicamera math
            cam_x_m = cfg['pos'][0]
            cam_y_m = cfg['pos'][1]
            canvas_x = int(center_x + cam_y_m * pixels_per_meter * HORIZONTAL_MULT)

            side_mult = 1.0
            if key in ('LF', 'LB'):
                side_mult = LEFT_VERTICAL_SPREAD
            elif key in ('RF', 'RB'):
                side_mult = RIGHT_VERTICAL_SPREAD

            canvas_y = int(center_y - cam_x_m * pixels_per_meter * VERTICAL_MULT * side_mult)

            # Camera placement centre for weight calculations
            px_x = canvas_x
            px_y = canvas_y

            # forward unit vector in canvas pixel coords (lateral, forward -> canvas x/y)
            # recall: f_x (lateral, right+), f_y (forward, forward+)
            # canvas lateral corresponds to +x canvas (to the right), forward corresponds to -y canvas
            # so pixel vector = (f_x * pixels_per_meter, -f_y * pixels_per_meter)
            forward_px = (f_x * pixels_per_meter, -f_y * pixels_per_meter)

            # store camera info in canvas coords; will crop later
            camera_info[key] = {
                'canvas_x': px_x,
                'canvas_y': px_y,
                'forward_px': forward_px,
                'yaw': yaw,
            }

            # Region on canvas where this image will be placed
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

            # slice arrays (from resized image)
            region_img = img_resized[sy1:sy2, sx1:sx2].astype(np.float32)

            # mask where resized image is not near-white (i.e. valid pixels)
            mask = np.any(img_resized[sy1:sy2, sx1:sx2] < 250, axis=2).astype(np.float32)

            # Create distance field (in meters) relative to camera placement for the region
            ys = np.arange(cy1, cy2) - px_y
            xs = np.arange(cx1, cx2) - px_x
            xx, yy = np.meshgrid(xs, ys)
            # convert px to meters
            lat_m = (xx / pixels_per_meter).astype(np.float32)    # lateral offset (right+)
            fwd_m = (-yy / pixels_per_meter).astype(np.float32)   # forward offset (forward+)

            # Anisotropic (elliptical) gaussian: allow different sigma along forward and lateral axes.
            # Default behavior (sigma_fwd == sigma_lat == self.sigma_m) reproduces previous radial falloff.
            sigma_fwd = max(1e-6, getattr(self, 'sigma_fwd_m', self.sigma_m))
            sigma_lat = max(1e-6, getattr(self, 'sigma_lat_m', self.sigma_m))

            # rotate pixel coords into camera-aligned frame (camera forward axis aligned to fwd_m)
            # camera forward unit vector in (lateral, forward) coords is (f_x, f_y)
            # build perpendicular (right) unit vector
            right_x = f_y  # rotated 90deg (lateral axis)
            right_y = -f_x
            # project pixel vector onto camera-forward and camera-right axes
            proj_fwd = lat_m * f_x + fwd_m * f_y
            proj_right = lat_m * right_x + fwd_m * right_y

            # compute anisotropic gaussian weight in meters
            g_f = np.exp(-0.5 * (proj_fwd / sigma_fwd) ** 2).astype(np.float32)
            g_r = np.exp(-0.5 * (proj_right / sigma_lat) ** 2).astype(np.float32)
            rad_weight = (g_f * g_r)

            # directional falloff: compute angle of pixel relative to camera forward direction
            # compute angle between pixel vector and forward vector via dot-product
            v_x = lat_m
            v_y = fwd_m
            v_norm = np.sqrt(v_x ** 2 + v_y ** 2) + 1e-9
            cosang = (v_x * f_x + v_y * f_y) / v_norm
            cosang = np.clip(cosang, -1.0, 1.0)
            angle = np.arccos(cosang)

            # per-camera angular sigma (degrees) biased by camera type to focus side cameras
            # slightly widened to give smoother, overlapping coverage
            angle_sigma_map = {'F': 75.0, 'B': 75.0, 'RF': 45.0, 'LF': 45.0, 'RB': 45.0, 'LB': 45.0}
            angle_sigma = np.deg2rad(angle_sigma_map.get(key, 45.0))
            dir_weight = np.exp(-0.5 * (angle / angle_sigma) ** 2).astype(np.float32)

            # optional distance attenuation to favor nearer pixels slightly (1/(1+dist))
            # compute radial distance in meters from camera placement (using original lat/fwd meters)
            dist_m = np.sqrt((lat_m ** 2) + (fwd_m ** 2))
            atten = 1.0 / (1.0 + 0.2 * dist_m)

            # final raw score combines radial (anisotropic), directional and mask
            weight = rad_weight * dir_weight * atten * mask

            # optional central boost: add a small gaussian centered on vehicle center (in meters)
            if getattr(self, 'central_boost', 0.0) > 0.0:
                # vehicle center relative to camera placement: compute meters distance from vehicle center (0,0) in camera coords
                # vehicle center in camera-aligned coords is simply (-cam_x_m, -cam_y_m) but easier: compute distance of pixel to canvas center
                # px_x, px_y are camera placement coords; canvas center is at (center_x, center_y)
                # compute vector from pixel (in meters) to vehicle center
                vx = ( (px_x - center_x) / pixels_per_meter ).astype(np.float32) if False else None
                # simpler: distance of pixel to vehicle center in meters (using existing lat_m/fwd_m + camera position)
                # approximation: use radial distance from canvas center by computing pixel coordinates relative to center
                cys = np.arange(cy1, cy2) - center_y
                cxs = np.arange(cx1, cx2) - center_x
                cxx, cyy = np.meshgrid(cxs, cys)
                dist_center_m = np.sqrt((cxx / pixels_per_meter) ** 2 + ((-cyy) / pixels_per_meter) ** 2).astype(np.float32)
                cb_sigma = max(1e-6, getattr(self, 'central_boost_sigma', 0.5))
                central = np.exp(-0.5 * (dist_center_m / cb_sigma) ** 2).astype(np.float32)
                weight = weight + (self.central_boost * central)

            # curvature exponent: raise weights to a power >1 to concentrate them towards peaks
            cp = getattr(self, 'curvature_power', 1.0)
            if cp != 1.0:
                # ensure non-negative before exponent
                weight = np.power(np.maximum(weight, 0.0), float(cp)).astype(np.float32)

            # store raw per-camera accumulators (we'll normalize across cameras later)
            per_camera_accum[key][cy1:cy2, cx1:cx2] += weight
            # store raw rgb and mask for this camera to allow recomposition/hard-assign outputs
            per_camera_rgb[key][cy1:cy2, cx1:cx2, :] += img_resized[sy1:sy2, sx1:sx2].astype(np.float32) * mask[:, :, None]
            per_camera_mask[key][cy1:cy2, cx1:cx2] += mask

        # Normalize accumulators to produce final image
        # Apply a small gaussian smoothing to per-camera accumulators to avoid hard, noisy seams
        try:
            blur_sigma_px = max(1.0, self.sigma_m * pixels_per_meter * 0.5)
            for k in CAMERA_KEYS:
                per_camera_accum[k] = cv2.GaussianBlur(per_camera_accum[k], (0, 0), blur_sigma_px)
        except Exception:
            pass

        # Normalize per-camera accumulators across cameras (so weights sum ~1 per-pixel)
        eps = 1e-7
        sum_map = np.zeros_like(list(per_camera_accum.values())[0])
        for k in CAMERA_KEYS:
            sum_map += per_camera_accum[k]

        # Build normalized per-camera weight maps and composite from per_camera_rgb
        accum_rgb = np.zeros((canvas_h, canvas_w, 3), dtype=np.float32)
        accum_w = np.zeros((canvas_h, canvas_w), dtype=np.float32)
        for k in CAMERA_KEYS:
            pk = per_camera_accum[k]
            norm = pk / (sum_map + eps)
            # optional small boost near camera center to favor centrally viewed pixels
            accum_rgb += per_camera_rgb[k] * norm[:, :, None]
            accum_w += norm

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

        # Also return cropped weight map and per-camera cropped maps for debugging
        cropped_w = accum_w[crop_y:crop_y+output_size[1], crop_x:crop_x+output_size[0]]
        per_camera_cropped = {k: v[crop_y:crop_y+output_size[1], crop_x:crop_x+output_size[0]] for k, v in per_camera_accum.items()}
        per_camera_rgb_cropped = {k: v[crop_y:crop_y+output_size[1], crop_x:crop_x+output_size[0], :] for k, v in per_camera_rgb.items()}
        per_camera_mask_cropped = {k: v[crop_y:crop_y+output_size[1], crop_x:crop_x+output_size[0]] for k, v in per_camera_mask.items()}
        # crop camera info into output pixel coords
        camera_info_cropped = {}
        for k, v in camera_info.items():
            cx = int(v['canvas_x'] - crop_x)
            cy = int(v['canvas_y'] - crop_y)
            fx_px = v['forward_px'][0]
            fy_px = v['forward_px'][1]
            camera_info_cropped[k] = {
                'x': cx,
                'y': cy,
                'fx_px': fx_px,
                'fy_px': fy_px,
                'yaw': v['yaw'],
            }
        return cropped, cropped_w, per_camera_cropped, per_camera_rgb_cropped, per_camera_mask_cropped, camera_info_cropped
        


def main():
    parser = argparse.ArgumentParser(description='Gaussian spatter compositor for 6-camera CARLA frames')
    parser.add_argument('folder', type=str, help='Folder with F.png,B.png,RF.png,LF.png,RB.png,LB.png')
    parser.add_argument('--output', type=str, default='patched_spatter.png', help='Output filename')
    parser.add_argument('--sigma', type=float, default=1.0, help='Gaussian sigma in meters')
    parser.add_argument('--scale', type=float, default=3.0, help='Canvas scale (relative to output size)')
    parser.add_argument('--per-camera', action='store_true', help='Save per-camera weight heatmaps for debugging')
    parser.add_argument('--argmax', action='store_true', help='Save argmax overlay (strongest camera per pixel)')
    parser.add_argument('--hard-assign', action='store_true', help='Save hard-assign composite (pixel assigned to single camera)')
    parser.add_argument('--debug', action='store_true', help='Save camera center/forward overlay and print camera info')
    parser.add_argument('--weight-mode', type=str, default='softmax', help="Weighting mode: 'prod' (current) or 'softmax'")
    parser.add_argument('--temp', type=float, default=0.2, help='Temperature for softmax weighting (lower = sharper)')
    parser.add_argument('--sigma-fwd-mult', type=float, default=1.0, help='Multiplier for forward-axis sigma (anisotropic)')
    parser.add_argument('--sigma-lat-mult', type=float, default=1.0, help='Multiplier for lateral-axis sigma (anisotropic)')
    parser.add_argument('--curvature-power', type=float, default=1.0, help='Exponent applied to per-camera weight to increase curvature (>1 sharpens center)')
    parser.add_argument('--central-boost', type=float, default=0.0, help='Additive central boost (in meters) to favor pixels near vehicle center')
    parser.add_argument('--central-boost-sigma', type=float, default=0.5, help='Sigma (meters) for central boost gaussian')
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.exists():
        raise SystemExit(f'Folder not found: {folder}')

    sp = GaussianSpatter(canvas_scale=args.scale, sigma_meters=args.sigma)
    # attach anisotropic sigma settings (in meters) computed from multipliers
    sp.sigma_fwd_m = float(args.sigma) * float(args.sigma_fwd_mult)
    sp.sigma_lat_m = float(args.sigma) * float(args.sigma_lat_mult)
    sp.curvature_power = float(args.curvature_power)
    sp.central_boost = float(args.central_boost)
    sp.central_boost_sigma = float(args.central_boost_sigma)
    images = sp.load_images(folder)
    out_path = folder / args.output
    # compose now returns the image, the combined weight map and per-camera maps
    # note: compose now also computes camera_info for debugging
    result, weight_map, per_camera_maps, per_camera_rgbs, per_camera_masks, camera_info = sp.compose(images)

    # Optionally recompute final composite using softmax over per-camera scores
    if args.weight_mode == 'softmax':
        # build stacked scores (shape: K,H,W)
        keys = CAMERA_KEYS
        stack_scores = np.stack([per_camera_maps[k] for k in keys], axis=0)
        eps = 1e-9
        # avoid log(0)
        log_scores = np.log(stack_scores + eps)
        T = float(args.temp)
        exp_scores = np.exp(log_scores / max(1e-6, T))
        sum_exp = np.sum(exp_scores, axis=0)
        weights = exp_scores / (sum_exp[None, :, :] + 1e-12)

        # compute new composite from per_camera_rgbs using normalized weights
        h_out, w_out = weights.shape[1], weights.shape[2]
        composite = np.zeros((h_out, w_out, 3), dtype=np.float32)
        for i, k in enumerate(keys):
            rgb = per_camera_rgbs[k].astype(np.float32)
            composite += rgb * weights[i, :, :, None]
        result = np.clip(composite, 0, 255).astype(np.uint8)
        # recompute weight_map as sum of weights
        weight_map = np.sum(weights, axis=0)
        # save overridden output
        softmax_out = folder / (out_path.stem + f'_softmax_T{T:.2f}.png')
        cv2.imwrite(str(softmax_out), result)
        print(f'[INFO] Saved softmax-weighted composite to: {softmax_out}')

    cv2.imwrite(str(out_path), result)
    # save a visualized weight heatmap using percentile clipping + gamma correction
    try:
        # percentile range to clip for visualization (reduces effect of outliers)
        low_p = 5.0
        high_p = 99.0
        flat = weight_map.flatten()
        low = float(np.percentile(flat, low_p))
        high = float(np.percentile(flat, high_p))
        # avoid degenerate range
        if high <= low:
            low = float(flat.min())
            high = float(flat.max()) if float(flat.max()) > low else low + 1e-6
        norm = np.clip((weight_map - low) / (high - low + 1e-12), 0.0, 1.0)
        # gamma <1 brightens mid-values, gamma>1 darkens
        gamma = 0.7
        vis = (np.power(norm, gamma) * 255.0).astype(np.uint8)
    except Exception:
        vis = (255 * (weight_map / (weight_map.max() if weight_map.max() > 0 else 1.0))).astype(np.uint8)

    heatmap_color = cv2.applyColorMap(vis, cv2.COLORMAP_JET)
    heat_path = folder / (out_path.stem + "_weights.png")
    cv2.imwrite(str(heat_path), heatmap_color)

    if args.per_camera:
        for k, pm in per_camera_maps.items():
            pmn = (255 * (pm / (pm.max() if pm.max() > 0 else 1.0))).astype(np.uint8)
            pmc = cv2.applyColorMap(pmn, cv2.COLORMAP_JET)
            ppath = folder / f"{out_path.stem}_weights_{k}.png"
            cv2.imwrite(str(ppath), pmc)
        print(f'[INFO] Saved per-camera heatmaps: {[f for f in folder.glob(out_path.stem + "_weights_*.png")]}')

    # Argmax overlay: which camera contributes most at each pixel
    if args.argmax or args.hard_assign:
        # stack per-camera weight maps in deterministic order
        keys = CAMERA_KEYS
        stack = np.stack([per_camera_maps[k] for k in keys], axis=0)  # shape (6, H, W)
        winner = np.argmax(stack, axis=0)
        # color map for keys (distinct colors)
        color_map = {
            'F': (0, 0, 255),
            'B': (0, 255, 255),
            'RF': (0, 255, 0),
            'LF': (255, 0, 0),
            'RB': (255, 0, 255),
            'LB': (255, 255, 0),
        }
        # build color image
        h_out, w_out = winner.shape
        argimg = np.zeros((h_out, w_out, 3), dtype=np.uint8)
        for i, k in enumerate(keys):
            mask_i = (winner == i)
            argimg[mask_i] = color_map[k]

        # overlay onto result (translucent)
        overlay = cv2.addWeighted(result, 0.7, argimg, 0.3, 0)
        arg_path = folder / (out_path.stem + "_argmax.png")
        cv2.imwrite(str(arg_path), overlay)
        print(f'[INFO] Saved argmax overlay to: {arg_path}')

    # Hard-assign composite: take pixel directly from the winning camera
    if args.hard_assign:
        # prepare per-camera rgb divided by mask (to recover original pixels)
        keys = CAMERA_KEYS
        h_out, w_out = weight_map.shape
        per_cam_rgb_norm = {}
        for k in keys:
            mask = per_camera_masks[k]
            rgb = per_camera_rgbs[k]
            denom = np.maximum(mask[:, :, None], 1e-6)
            per_cam_rgb_norm[k] = (rgb / denom).astype(np.uint8)

        hard_img = np.zeros_like(result)
        for i, k in enumerate(keys):
            mask_i = (winner == i)
            if mask_i.any():
                hard_img[mask_i] = per_cam_rgb_norm[k][mask_i]

        hard_path = folder / (out_path.stem + "_hard.png")
        cv2.imwrite(str(hard_path), hard_img)
        print(f'[INFO] Saved hard-assign composite to: {hard_path}')

    if args.debug:
        # draw camera centers and forward arrows onto overlay of weight heatmap
        dbg = result.copy()
        for k, info in camera_info.items():
            x = int(info['x'])
            y = int(info['y'])
            fx = info['fx_px']
            fy = info['fy_px']
            # draw center
            cv2.circle(dbg, (x, y), 6, (0, 255, 255), -1)
            # forward arrow scaled for visibility
            ax = int(round(x + fx * 20))
            ay = int(round(y + fy * 20))
            cv2.arrowedLine(dbg, (x, y), (ax, ay), (0, 128, 255), 2, tipLength=0.2)
            # put label
            cv2.putText(dbg, k, (x + 8, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        debug_path = folder / (out_path.stem + "_debug.png")
        cv2.imwrite(str(debug_path), dbg)
        print('[DEBUG] Camera info:')
        for k, info in camera_info.items():
            print(f"  {k}: pixel=({info['x']},{info['y']}), forward_px=({info['fx_px']:.1f},{info['fy_px']:.1f}), yaw={info['yaw']}")
        print(f'[INFO] Saved debug overlay to: {debug_path}')

    print(f'[INFO] Saved spatter-patched image to: {out_path} (size: {result.shape[1]}x{result.shape[0]})')
    print(f'[INFO] Saved weight heatmap to: {heat_path} (for debugging)')


if __name__ == '__main__':
    main()
