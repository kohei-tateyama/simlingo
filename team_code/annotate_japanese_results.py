"""
Annotate images using agent control outputs saved in a JSON file.

Usage:
    python team_code/annotate_japanese_results.py /tmp/japanese_results.json japanese_street

This will create `japanese_street/japanese_street_tested/` and save annotated images `image_0001_tested.png` etc.
"""
from pathlib import Path
import json
import cv2
import math
import numpy as np
import sys

###################################### config in the future you coudl so a .yaml
DUMMY_SENSITIVITY = 0.005
THICKNESS_LINE = 4
THICKNESS_LINE_CURVE = 10
SMALL_CIRCLE_RADIUS = 10

_draw_slot_idx = 0
_draw_last_img_id = None
SLOT_SPACING_RATIO = 0.18
SLOT_BASE_Y_RATIO = 0.78

# make arrow heads larger for visibility in panel visuals
ARROW_HEAD_LEN = 36
ARROW_HEAD_WIDTH = 18

# Brightened steer color (BGR)
STEER_COLOR = (200, 50, 200)
# Throttle color (green) and directional arrow color (yellow)
THROTTLE_COLOR = (0, 220, 0)
DIRECTIONAL_COLOR = (0, 255, 255)  # yellow in BGR

# Directional arrow parameters
DIRECTIONAL_MAX_LEN_RATIO = 0.28  # fraction of min(w,h)
DIRECTIONAL_MIN_LEN = 20
DIRECTIONAL_THICK = 8
DIRECTIONAL_TRAIL_STEPS = 4
DIRECTIONAL_TRAIL_FADE = 0.18
# multiplier applied to max_dir_angle when computing the yellow directional arrow
DIRECTION_ANGLE_MULTIPLIER = 1.5

STEER_MIN_SCALE = 0.18
STEER_SCALE_FACTOR = 0.6
THROTTLE_MIN_SCALE = 0.12
THROTTLE_SCALE_FACTOR = 0.5
BRAKE_BASE_SIZE = 30
BRAKE_MIN_SCALE = 0.18
BRAKE_SCALE_FACTOR = 0.5

# Labels and values
headers = ["steer", "throttle", "brake"]
HEADER_OFFSET_Y = 30
VALUE_OFFSET_Y = 70
# increase bottom offset so visuals appear higher in the panel
VISUAL_BOTTOM_OFFSET = 90

# offsets
LABEL_STEER_OFFSET_X = 120
LABEL_STEER_OFFSET_Y = 30
LABEL_THROTTLE_OFFSET_X = 80
DEGREES_ARC_EXTENT = 35

fontScale = 0.9
label_color = (255, 128, 0) 
label_font_scale = 2.0
label_thickness = 3
count_down = 60
X_img = 10
alpha = 0.45 
lineWidth = 2

# header/value font scales used in the bottom panel (larger than before)
HEADER_FONT_SCALE = 1.4
VALUE_FONT_SCALE = 1.4
HEADER_FONT_THICK = 3
VALUE_FONT_THICK = 3

# Visual ratio constants (make scaling clearer)
PANEL_HEIGHT_MIN = 120        # minimum panel height in px
PANEL_HEIGHT_MAX = 220        # maximum panel height in px
PANEL_HEIGHT_RATIO = 0.22     # fraction of image height used for panel

VISUAL_RADIUS_RATIO = 0.22    # proportion of panel_h for visual radius
VISUAL_ARROW_LEN_RATIO = 0.26 # proportion of panel_h for small arrow length
VISUAL_BRAKE_RATIO = 0.18     # proportion of panel_h for brake size
max_dir_angle = 35
STEER_START_DOWN_RATIO = 0.28

###################################### utils 

def draw_steer_arrow(img, steer_value, origin=None, color=STEER_COLOR, thickness=THICKNESS_LINE):
    """Draw a curved arc + arrow representing steering.
    This implementation follows the earlier working version: it draws an arc
    starting at 0deg (right) or 180deg (left) and sweeps by sign*angle.
    """
    h, w = img.shape[:2]
    global _draw_slot_idx, _draw_last_img_id
    if _draw_last_img_id != id(img):
        _draw_slot_idx = 0
        _draw_last_img_id = id(img)
    if origin is None:
        base_x = w // 2
        spacing = int(w * SLOT_SPACING_RATIO)
        slots = [base_x - spacing, base_x, base_x + spacing]
        origin = (slots[_draw_slot_idx % len(slots)], int(h * SLOT_BASE_Y_RATIO))
        _draw_slot_idx += 1

    # Prefer centering the arc on the provided origin so visuals align with column centers
    max_radius = min(w, h) // 3
    radius = int(max(12, max_radius * (STEER_MIN_SCALE + STEER_SCALE_FACTOR * abs(steer_value))))
    sign = -1 if steer_value < 0 else 1
    angle = int(DEGREES_ARC_EXTENT * (STEER_SCALE_FACTOR + 0.4 * abs(steer_value)))
    cx = origin[0]
    cy = origin[1] + int(radius * STEER_START_DOWN_RATIO) # harcoded

    pts = []
    ##############################################################################################################
    ### THIS NEED TP BE CHECK !! ###
    start_angle = -90
    # invert the sweep direction: positive steer will now sweep the opposite way
    end_angle = start_angle - sign * angle
    ##############################################################################################################
    for a in np.linspace(start_angle, end_angle, num=40):
        theta = math.radians(a)
        x = int(cx + radius * math.cos(theta))
        y = int(cy + radius * math.sin(theta))
        pts.append((x, y))
    pts = np.array(pts, dtype=np.int32)

    # draw a dark outline under the arc for contrast and bump thickness
    outline_thick = max(2, int(thickness * 1.8))
    cv2.polylines(img, [pts], False, (8, 8, 8), outline_thick, lineType=cv2.LINE_AA)
    # draw the colored arc on top
    cv2.polylines(img, [pts], False, color, max(2, thickness - 1), lineType=cv2.LINE_AA)
    # optionally a small marker at the end of the arc
    if len(pts) >= 1:
        p2 = pts[-1].astype(int)
        cv2.circle(img, tuple(p2), max(2, int(radius * 0.08)), color, -1, cv2.LINE_AA)

    if abs(steer_value) < 0.02:
        cv2.line(img, (cx - radius // 4, cy), (cx + radius // 4, cy), (150, 150, 150), 2, cv2.LINE_AA)

def draw_throttle_circle(img, throttle_value, origin=None, color=(0, 255, 0), thickness=THICKNESS_LINE):
    """Draw a circular arrow representing throttle. throttle_value in [0,1]"""
    h, w = img.shape[:2]
    global _draw_slot_idx, _draw_last_img_id
    if _draw_last_img_id != id(img):
        _draw_slot_idx = 0
        _draw_last_img_id = id(img)
    if origin is None:
        base_x = w // 2
        spacing = int(w * SLOT_SPACING_RATIO)
        slots = [base_x - spacing, base_x, base_x + spacing]
        origin = (slots[_draw_slot_idx % len(slots)], int(h * SLOT_BASE_Y_RATIO))
        _draw_slot_idx += 1

    max_r = min(w, h) // 6
    r = int(max_r * (THROTTLE_MIN_SCALE + THROTTLE_SCALE_FACTOR * throttle_value))

    # circle arc
    center = (origin[0], origin[1] - r - 2 * SMALL_CIRCLE_RADIUS)
    startAngle = 0
    endAngle = int(360 * throttle_value)
    cv2.ellipse(img, center, (r, r), 0, startAngle, endAngle, color, thickness, cv2.LINE_AA)

    # arrow head at end
    theta = math.radians(endAngle - SMALL_CIRCLE_RADIUS)
    x = int(center[0] + r * math.cos(theta))
    y = int(center[1] + r * math.sin(theta))
    p1 = np.array([x, y], dtype=np.int32)
    p2 = np.array([int(x - ARROW_HEAD_WIDTH), int(y - ARROW_HEAD_WIDTH)], dtype=np.int32)
    p3 = np.array([int(x + ARROW_HEAD_WIDTH), int(y - ARROW_HEAD_WIDTH)], dtype=np.int32)
    cv2.fillConvexPoly(img, np.array([p1, p2, p3], dtype=np.int32), color)

    # label - this i do not like
    text = f"throttle: {throttle_value:.3f}"
    (text_w, text_h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, fontScale, lineWidth)
    tx = center[0] - LABEL_THROTTLE_OFFSET_X
    tx = max(SMALL_CIRCLE_RADIUS / 2, min(tx, w - text_w - SMALL_CIRCLE_RADIUS / 2))
    ty = center[1] - r - SMALL_CIRCLE_RADIUS
    # cv2.putText(img, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, fontScale, color, lineWidth, cv2.LINE_AA)

# Draw small semi-transparent background boxes behind status texts
def draw_status_box(img, text, x, y, padding=12, bg_color=(0, 0, 0), alpha_overlay=0.35, text_color=label_color):
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, label_font_scale, label_thickness)
    box_tl = (x, y - th - padding)
    box_br = (x + tw + padding * 2, y + padding // 2)
    overlay = img.copy()
    cv2.rectangle(overlay, box_tl, box_br, bg_color, -1)
    cv2.addWeighted(overlay, alpha_overlay, img, 1 - alpha_overlay, 0, img)
    cv2.putText(img, text, (x + padding, y), cv2.FONT_HERSHEY_SIMPLEX, label_font_scale, text_color, label_thickness, cv2.LINE_AA)

def draw_brake_x(img, brake_value, origin=None, color=(0, 0, 255), thickness=THICKNESS_LINE):
    """Draw an X in front of the vehicle scaled by brake_value"""
    h, w = img.shape[:2]
    global _draw_slot_idx, _draw_last_img_id
    if _draw_last_img_id != id(img):
        _draw_slot_idx = 0
        _draw_last_img_id = id(img)
    if origin is None:
        base_x = w // 2
        spacing = int(w * SLOT_SPACING_RATIO)
        slots = [base_x - spacing, base_x, base_x + spacing]
        origin = (slots[_draw_slot_idx % len(slots)], int(h * SLOT_BASE_Y_RATIO))
        _draw_slot_idx += 1

    size = int(BRAKE_BASE_SIZE * (BRAKE_MIN_SCALE + BRAKE_SCALE_FACTOR * brake_value))
    x1 = origin[0] - size
    y1 = origin[1] - size
    x2 = origin[0] + size
    y2 = origin[1] + size
    cv2.line(img, (x1, y1), (x2, y2), color, thickness, cv2.LINE_AA)
    cv2.line(img, (x1, y2), (x2, y1), color, thickness, cv2.LINE_AA)
    text = f"brake: {brake_value:.3f}"
    (text_w, text_h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, fontScale, lineWidth)
    tx = origin[0] - 60
    tx = max(SMALL_CIRCLE_RADIUS / 2, min(tx, w - text_w - SMALL_CIRCLE_RADIUS / 2))
    ty = origin[1] - size - SMALL_CIRCLE_RADIUS
    cv2.putText(img, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, fontScale, color, lineWidth, cv2.LINE_AA)

def annotate_results(json_path, images_dir, out_dir=None, suffix="_tested"):
    json_path = Path(json_path)
    images_dir = Path(images_dir)
    if out_dir is None:
        out_dir = images_dir / f"{images_dir.name}_tested"
    else:
        out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(json_path, 'r') as f:
        data = json.load(f)

    if isinstance(data, dict):
        entries = [data]
    else:
        entries = data

    for entry in entries:
        img_rel = entry.get('image')
        if img_rel is None:
            print("Skipping entry without 'image'")
            continue

        img_path = images_dir / Path(img_rel).name
        if not img_path.exists():
            print(f"Image not found: {img_path}, skipping")
            continue

        img = cv2.imread(str(img_path))
        if img is None:
            print(f"Failed to load {img_path}")
            continue

        control = entry.get('control', {})
        steer = float(control.get('steer', 0.0))
        throttle = float(control.get('throttle', 0.0))
        brake = float(control.get('brake', 0.0))
        hand_brake = control.get('hand_brake', False)
        reverse = control.get('reverse', False)

        # Draw fixed bottom panel: three columns (steer | throttle | brake)
        out_img = img.copy()
        hb_text = f"hand_brake: {hand_brake}"
        rv_text = f"reverse: {reverse}"

        label_line = 1
        x0 = X_img
        y0 = count_down * label_line + X_img
        draw_status_box(out_img, hb_text, x0, y0)
        label_line += 1
        y1 = count_down * label_line + X_img
        draw_status_box(out_img, rv_text, x0, y1)

        h, w = out_img.shape[:2]
        panel_h = int(max(PANEL_HEIGHT_MIN, min(PANEL_HEIGHT_MAX, int(h * PANEL_HEIGHT_RATIO))))
        panel_top = h - panel_h
        panel_color = (0, 0, 0)
        overlay = out_img.copy()
        
        cv2.rectangle(overlay, (0, panel_top), (w, h), panel_color, -1)
        cv2.addWeighted(overlay, alpha, out_img, 1 - alpha, 0, out_img)

        col_w = w // 3
        centers = [int(col_w * 0.5), int(col_w * 1.5), int(col_w * 2.5)]
        values = [f"{steer:.3f}", f"{throttle:.3f}", f"{brake:.3f}"]

        # move labels up by 20% of panel height so they appear higher
        shift_up = int(panel_h * 0.20)
        header_y = panel_top + HEADER_OFFSET_Y - shift_up
        value_y = panel_top + VALUE_OFFSET_Y - shift_up
        visual_y = panel_top + panel_h - VISUAL_BOTTOM_OFFSET

        visual_max_radius = int(panel_h * VISUAL_RADIUS_RATIO)
        visual_arrow_len = int(panel_h * VISUAL_ARROW_LEN_RATIO)
        visual_brake_size = int(panel_h * VISUAL_BRAKE_RATIO)

        for i, cx in enumerate(centers):
            # center header and value under the visual center
            (hdr_w, hdr_h), _ = cv2.getTextSize(headers[i], cv2.FONT_HERSHEY_SIMPLEX, HEADER_FONT_SCALE, HEADER_FONT_THICK)
            (val_w, val_h), _ = cv2.getTextSize(values[i], cv2.FONT_HERSHEY_SIMPLEX, VALUE_FONT_SCALE, VALUE_FONT_THICK)
            hdr_x = int(cx - hdr_w // 2)
            val_x = int(cx - val_w // 2)
            cv2.putText(out_img, headers[i], (hdr_x, header_y), cv2.FONT_HERSHEY_SIMPLEX, HEADER_FONT_SCALE, label_color, HEADER_FONT_THICK, cv2.LINE_AA)
            cv2.putText(out_img, values[i], (val_x, value_y), cv2.FONT_HERSHEY_SIMPLEX, VALUE_FONT_SCALE, label_color, VALUE_FONT_THICK, cv2.LINE_AA)

        # Draw per column
        # Steer: small curved/arrow depending on sign, skip visual when near-zero
        sx = centers[0]
        sy = visual_y
        if abs(steer) >= DUMMY_SENSITIVITY:
            # use centralized steer drawing helper (scales with steer magnitude)
            try:
                draw_steer_arrow(out_img, steer, origin=(sx, sy), color=STEER_COLOR, thickness=8)
            except Exception:
                cv2.circle(out_img, (sx, sy), SMALL_CIRCLE_RADIUS, STEER_COLOR, 2, cv2.LINE_AA)
        else:
            cv2.circle(out_img, (sx, sy), SMALL_CIRCLE_RADIUS, STEER_COLOR, 2, cv2.LINE_AA)

        # Throttle: circular arc, skip visual when near-zero
        tx = centers[1]
        ty = visual_y
        if abs(throttle) >= DUMMY_SENSITIVITY:
            # Draw a longitudinal arrow pointing into the image (upwards from panel)
            max_len = int(panel_h * 0.9)
            arrow_len = int(max(visual_max_radius, int(max_len * 0.45 * min(1.0, throttle))))
            start_pt = (tx, ty - arrow_len)
            end_pt = (tx, ty + int(visual_max_radius*0.2))
            cv2.arrowedLine(out_img, (end_pt[0], end_pt[1]), (start_pt[0], start_pt[1]), THROTTLE_COLOR, 5, tipLength=0.2)
        else:
            cv2.circle(out_img, (tx, ty), SMALL_CIRCLE_RADIUS, THROTTLE_COLOR, 2, cv2.LINE_AA)

        # Brake: X, skip visual when near-zero
        bx = centers[2]
        by = visual_y
        if abs(brake) >= DUMMY_SENSITIVITY:
            bsize = max(SMALL_CIRCLE_RADIUS, visual_brake_size)
            cv2.line(out_img, (bx - bsize, by - bsize), (bx + bsize, by + bsize), (0, 0, 255), 8, cv2.LINE_AA)
            cv2.line(out_img, (bx - bsize, by + bsize), (bx + bsize, by - bsize), (0, 0, 255), 8, cv2.LINE_AA)
        else:
            cv2.circle(out_img, (bx, by), SMALL_CIRCLE_RADIUS, (0, 0, 255), 2, cv2.LINE_AA)

        # Draw motiondirection: steer + throttle
        im_cx = w // 2
        im_cy = (panel_top // 2)  # place above the panel, centered vertically in image
        # directional angle: steer [-1,1] to [-max_dir_angle, +max_dir_angle]
        ang_deg = max_dir_angle * DIRECTION_ANGLE_MULTIPLIER * steer
        # Convert so 0deg -> -90deg (up). anticlockwise. Harcoded for better showing not much. 
        dir_angle = math.radians(-90 - ang_deg)
        base_len = int(min(w, h) * DIRECTIONAL_MAX_LEN_RATIO)
        dir_len = int(max(DIRECTIONAL_MIN_LEN, base_len * (STEER_SCALE_FACTOR / 2 + 0.7 * throttle)))
        dx = int(dir_len * math.cos(dir_angle))
        dy = int(dir_len * math.sin(dir_angle))
        # draw a single prominent directional arrow (no trail)
        im_cy = (panel_top // 2) + (dir_len // 2)
        sfx = int(im_cx - dx * 0.15)
        sfy = int(im_cy - dy * 0.15)
        efx = int(im_cx + dx)
        efy = int(im_cy + dy)
        dir_thick = max(2, int(DIRECTIONAL_THICK * STEER_SCALE_FACTOR))
        cv2.arrowedLine(out_img, (sfx, sfy), (efx, efy), DIRECTIONAL_COLOR, dir_thick, tipLength=0.25)

        out_name = Path(img_path.stem + suffix + img_path.suffix)
        out_path = out_dir / out_name
        cv2.imwrite(str(out_path), out_img)
        print(f"[INFO]: Saved annotated: {out_path}")


if __name__ == '__main__':
    # if len(sys.argv) < 3:
    #     print("Usage: python team_code/annotate_japanese_results.py <json_path> <images_dir> [out_dir]")
    #     sys.exit(1)
    # json_path = sys.argv[1]
    # images_dir = sys.argv[2]
    # out_dir = sys.argv[3] if len(sys.argv) > 3 else None
    # annotate_results(json_path, images_dir, out_dir)

    # Hardcoded quick testing
    json_path = '/tmp/japanese_results.json'
    images_dir = 'japanese_street'
    out_dir = 'japanese_street/japanese_street_test'
    annotate_results(json_path, images_dir, out_dir)





# # from the agent_simlingo.py up to lino 800

# @torch.no_grad()
#     def run_step(self, input_data, timestamp, sensors=None):  # pylint: disable=locally-disabled, unused-argument
#         self.step += 1

#         if not self.initialized:
#             self._init()
#             control = carla.VehicleControl(steer=0.0, throttle=0.0, brake=1.0)
#             self.control = control
#             tick_data = self.tick(input_data)
#             return control

#         # Need to run this every step for GPS filtering
#         tick_data = self.tick(input_data)

#         # ###############################adding frame skipping##########################
        
#         # # FRAME SKIPPING: Process every 4th frame to achieve 5 FPS effective rate
#         # # Simulation runs at 20 FPS, so skip 3 frames, process 1 frame
#         # if not hasattr(self, '_frame_skip_counter'):
#         #     self._frame_skip_counter = 0
#         #     self._cached_control = carla.VehicleControl(steer=0.0, throttle=0.0, brake=1.0)
        
#         # self._frame_skip_counter += 1
        
#         # # Only run full model inference every 4th frame
#         # if self._frame_skip_counter % 4 != 0:
#         #     # Reuse cached control from last inference
#         #     return self._cached_control

#         # ###############################################################################
        
        
#         # initialize DrivingInput with dict self.DrivingInput
#         model_input = DrivingInput(**self.DrivingInput)
#         pred_speed_wps, pred_route, language = self.model(model_input)
#         pred_speed_wps = pred_speed_wps.float() if pred_speed_wps is not None else None
#         pred_route = pred_route.float() if pred_route is not None else None

#         ## understand how they plots the wwaypoints

#         gt_velocity = tick_data['speed']

#         if DEBUG and self.step%5 == 0:
#             tvec = None
#             rvec = None

#             if HD_VIZ:
#                 self.camera_for_viz = self.hd_cam_for_viz
#                 tvec = np.array([[0.0, 3.5, 5.5]], np.float32)

#                 cam_rots = [0.0, -15.0, 0.0]
#                 rot_matrix = get_rotation_matrix(-cam_rots[0], -cam_rots[1], cam_rots[2])
#                 rvec = cv2.Rodrigues(rot_matrix[:3, :3])[0].flatten()

#             W=self.camera_for_viz.shape[1]
#             H=self.camera_for_viz.shape[0]
#             camera_intrinsics = np.asarray(get_camera_intrinsics(W,H,110))

#             # bgr to rgb
#             self.camera_for_viz = cv2.cvtColor(self.camera_for_viz, cv2.COLOR_BGR2RGB)

#             # draw the predicted waypoints
#             image = Image.fromarray(self.camera_for_viz)
#             draw = ImageDraw.Draw(image)

#             if self.target_points is not None:
#                 target_point_img_coords = project_points(self.target_points, camera_intrinsics, tvec=tvec, rvec=rvec)
#                 for points_2d in target_point_img_coords:
#                     # in blue
#                     draw.ellipse((points_2d[0]-4, points_2d[1]-4, points_2d[0]+4, points_2d[1]+4), fill=(0, 0, 255, 255))

#             if pred_route is not None:
#                 pred_route_img_coords = project_points(pred_route[0].detach().cpu().numpy(), camera_intrinsics, tvec=tvec, rvec=rvec)
#                 for points_2d in pred_route_img_coords:
#                         draw.ellipse((points_2d[0]-3, points_2d[1]-3, points_2d[0]+3, points_2d[1]+3), fill=(255, 0, 0, 255))
            
#             if pred_speed_wps is not None:
#                 pred_speed_wps_img_coords = project_points(pred_speed_wps[0].detach().cpu().numpy(), camera_intrinsics, tvec=tvec, rvec=rvec)
#                 for points_2d in pred_speed_wps_img_coords:
#                         draw.ellipse((points_2d[0]-2, points_2d[1]-2, points_2d[0]+2, points_2d[1]+2), fill=(0, 255, 0, 255))

#             if language is not None:
#                 # write the language to the bottom of the image
#                 black_box = Image.new('RGBA', (W, 400), (0, 0, 0, 255))
#                 # concatenate the images
#                 image_all = Image.new('RGBA', (W, H+400))
#                 image_all.paste(image, (0, 0))
#                 image_all.paste(black_box, (0, H))
#                 image = image_all
#                 draw = ImageDraw.Draw(image)

#                 if HD_VIZ:
#                     font_size = 50
#                     line_width = 60
#                     y_dist = 60
#                     y_start = H + 20
#                 else:
#                     font_size = 20
#                     line_width = 100
#                     y_dist = 30
#                     y_start = H + 20
#                 font = ImageFont.truetype("arial.ttf", font_size)
#                 import textwrap
#                 lines = textwrap.wrap(f"Prompt: {self.prompt}", width=line_width)
#                 for idx, line in enumerate(lines):
#                         draw.text((10, y_start + y_dist*(idx)), line, font=font, fill=(255, 255, 255, 255))
                
#                 y_start = H + 20 + y_dist*(idx+1)

#                 lines = textwrap.wrap(f"Answer: {language[0]}", width=line_width)
#                 for idx, line in enumerate(lines):
#                         draw.text((10, y_start + y_dist*(idx)), line, font=font, fill=(255, 255, 255, 255))

#             # save
#             image.save(f"{self.save_path_img}/{self.step}.png")