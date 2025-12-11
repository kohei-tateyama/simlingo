#!/usr/bin/env python3
"""
team_code/undestand_carla_api.py

Lightweight CARLA inspector utility (headless-friendly + importable).
- Provides helpers for agents: connect_client, find_vehicle, get_vehicle_state, stream_vehicle_state
- CLI: emits JSON-lines when requested (good for headless logging by how_to_run_headless.sh)
- Reads CARLA_HOST/CARLA_PORT or HOST/PORT from environment (compatible with your headless launcher)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import signal
import sys
import time
from datetime import datetime
from typing import Dict, Generator, Optional, Tuple

try:
    import carla
except Exception:
    carla = None  

import matplotlib.pyplot as plt
try:
    import cv2
except Exception:
    cv2 = None

base_output_dir = "/workspace/simlingo/team_code/routes_validation_xml"
if os.path.exists(base_output_dir):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = f"{base_output_dir}_{timestamp}"
else:
    output_dir = base_output_dir

os.makedirs(output_dir, exist_ok=True)
print(f"[INFO] Using output directory: {output_dir}")

# Add global lists to collect data for plotting
positions = []
controls = {"timestamps": [], "steer": [], "throttle": []}


def connect_client(host: str = "localhost", port: int = 2000, timeout: float = 5.0):
    """Return connected carla.Client. Raises RuntimeError if CARLA API missing."""
    if carla is None:
        raise RuntimeError("CARLA PythonAPI not available (set CARLA_ROOT/PYTHONPATH)")
    client = carla.Client(host, port)
    client.set_timeout(timeout)
    return client


def find_vehicle(world, role_names: Tuple[str, ...] = ("hero", "ego", "player")):
    """Return a vehicle actor (prefers actors with role_name in role_names) or None."""
    actors = world.get_actors().filter("vehicle.*")
    for a in actors:
        try:
            if a.attributes.get("role_name", "").lower() in role_names:
                return a
        except Exception:
            continue
    return actors[0] if len(actors) > 0 else None


def _vec_len3(v) -> float:
    return math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)


def get_vehicle_state(vehicle) -> Dict:
    """
    Read telemetry from a vehicle actor and return a dict:
      { id, role_name, position: [x,y,z], heading_deg, speed, accel (may be None), accel_est, control (may be None), timestamp }
    Non-destructive read only.
    """
    tr = vehicle.get_transform()
    loc = tr.location
    rot = tr.rotation
    vel = vehicle.get_velocity()

    accel_val = None
    try:
        accel_vec = vehicle.get_acceleration()
        accel_val = _vec_len3(accel_vec)
    except Exception:
        accel_val = None

    speed = _vec_len3(vel)

    control = None
    try:
        c = vehicle.get_control()
        control = {
            "steer": float(c.steer),
            "throttle": float(c.throttle),
            "brake": float(c.brake),
            "hand_brake": bool(c.hand_brake),
            "reverse": bool(c.reverse),
        }
    except Exception:
        control = None

    # Collect data for plotting
    positions.append((loc.x, loc.y))
    if control:
        controls["timestamps"].append(time.time())
        controls["steer"].append(control["steer"])
        controls["throttle"].append(control["throttle"])

    return {
        "id": vehicle.id,
        "role_name": vehicle.attributes.get("role_name", ""),
        "position": [loc.x, loc.y, loc.z],  # Already in meters (CARLA default unit)
        "heading_deg": float(rot.yaw),
        "speed": float(speed),
        "accel": accel_val,
        "accel_est": None,  # filled by stream_vehicle_state
        "control": control,
        "timestamp": time.time(),  # Ensure timestamp is included
        "readable_timestamp": datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S'),
    }


def stream_vehicle_state(client,
                         steps: int = 200,
                         dt: float = 0.2,
                         role_names: Tuple[str, ...] = ("hero", "ego", "player")) -> Generator[Dict, None, None]:
    """
    Generator yielding telemetry dicts each tick.
    Raises RuntimeError if cannot get world or no vehicle found.
    """
    if carla is None:
        raise RuntimeError("CARLA PythonAPI not available")

    world = client.get_world()
    vehicle = find_vehicle(world, role_names=role_names)
    # Ensure the script does not fail if no vehicle is found; instead, log a warning
    if vehicle is None:
        print("[WARN] No vehicle actor found in the world. Waiting for a vehicle to appear.", file=sys.stderr)
        while vehicle is None:
            time.sleep(1)  # Wait for a vehicle to appear
            vehicle = find_vehicle(world, role_names=role_names)

    print("[INFO] Vehicle found. Starting telemetry stream.")

    prev_speed: Optional[float] = None
    prev_time: Optional[float] = None
    for _ in range(steps):
        t0 = time.time()
        try:
            state = get_vehicle_state(vehicle)
            # if accel missing, provide estimated longitudinal accel via finite difference
            if state["accel"] is None and prev_speed is not None and prev_time is not None:
                now = state["timestamp"]
                state["accel_est"] = (state["speed"] - prev_speed) / max(1e-6, now - prev_time)
            else:
                state["accel_est"] = state["accel"]
            prev_speed = state["speed"]
            prev_time = state["timestamp"]
        except Exception as e:
            state = {"error": str(e), "timestamp": time.time()}
        yield state
        elapsed = time.time() - t0
        to_sleep = max(0.0, dt - elapsed)
        time.sleep(to_sleep)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="CARLA inspector (headless + importable)")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=2000)
    p.add_argument("--steps", type=int, default=999999)  # Run indefinitely by default
    p.add_argument("--dt", type=float, default=0.1)      # Sample at 10 Hz (faster for better resolution)
    p.add_argument("--role-names", nargs="+", default=["hero", "ego", "player"])
    p.add_argument("--headless", action="store_true", help="Quiet output mode (equivalent to --json).")
    p.add_argument("--json", action="store_true", help="Emit one JSON object per line.")
    p.add_argument("--timeout", type=float, default=5.0, help="CARLA client timeout (s).")

    return p.parse_args(argv)


def create_video_from_images(images_dir: str, out_file: str, fps: float = 10.0):
    """
    Create a video from images in `images_dir` saved to `out_file` at `fps` frames per second.
    Images are read in lexicographic order and must be common image formats (png/jpg/jpeg).
    Requires OpenCV (`cv2`).
    """
    if cv2 is None:
        raise RuntimeError("OpenCV (cv2) is required to create videos. Install via `pip install opencv-python`.")

    if not os.path.isdir(images_dir):
        raise RuntimeError(f"images_dir does not exist or is not a directory: {images_dir}")

    exts = (".png", ".jpg", ".jpeg", ".bmp")
    files = [f for f in sorted(os.listdir(images_dir)) if f.lower().endswith(exts)]
    if not files:
        raise RuntimeError(f"No image files found in {images_dir} (supported: {exts})")

    first = os.path.join(images_dir, files[0])
    img = cv2.imread(first)
    if img is None:
        raise RuntimeError(f"Failed to read first image: {first}")

    height, width = img.shape[:2]
    # Ensure output directory exists
    out_dir = os.path.dirname(out_file)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(out_file, fourcc, float(fps), (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"Failed to open VideoWriter for {out_file}")

    print(f"[INFO] Creating video {out_file} from {len(files)} frames at {fps} FPS")
    for idx, fn in enumerate(files, start=1):
        path = os.path.join(images_dir, fn)
        frame = cv2.imread(path)
        if frame is None:
            print(f"[WARN] Skipping unreadable frame: {path}")
            continue
        # Resize if frame size differs from first image
        if frame.shape[0] != height or frame.shape[1] != width:
            frame = cv2.resize(frame, (width, height))
        writer.write(frame)
        if idx % 50 == 0:
            print(f"[INFO] Written {idx}/{len(files)} frames...")

    writer.release()
    print(f"[INFO] Video saved to: {out_file}")

# Update save_plots to print where the plots are saved
def save_plots():
    """Save telemetry plots (position trajectory and control inputs)."""
    if not positions and not controls["timestamps"]:
        print("[INFO] No telemetry data collected - skipping plots")
        return
    
    line_width = 3.0
    alpha_value = 0.7
    font_size = 12
    alpha_font = 0.3
    marker_size = 14

    ## conversion 
    steer_scale_rad = 0.36848336
    steer_scale_deg = 21 

    throttle_scale_ms2 = 0.5633837
    brake_scale_ms2 = -4.952399
    
    # Plot trajectory (2D top-down view)
    if positions:
        x, y = zip(*positions)
        # Compute centroid and center positions so plot origin is at centroid
        centroid_x = sum(x) / len(x)
        centroid_y = sum(y) / len(y)
        centered_x = [xi - centroid_x for xi in x]
        centered_y = [yi - centroid_y for yi in y]

        # Plot 1: Centered trajectory
        plt.figure(figsize=(12, 10))
        plt.plot(centered_x, centered_y, 'b-', linewidth=line_width, alpha=alpha_value, label='Trajectory')
        plt.plot(centered_x[0], centered_y[0], 'go', markersize=marker_size, label='Start')
        plt.plot(centered_x[-1], centered_y[-1], 'ro', markersize=marker_size, label='End')
        plt.title("Vehicle Trajectory (Top-Down View, Centered)", fontsize=font_size, fontweight='bold')
        plt.xlabel("X Position (m, centered)", fontsize=font_size)
        plt.ylabel("Y Position (m, centered)", fontsize=font_size)
        plt.grid(True, alpha=alpha_font)
        plt.legend(fontsize=font_size)
        plt.axis('equal')
        centered_plot_path = os.path.join(output_dir, "vehicle_trajectory_centered.png")
        plt.savefig(centered_plot_path, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"[INFO] Centered trajectory plot saved to: {centered_plot_path}")
        print(f"      Total samples: {len(positions)}")
        print(f"      Centroid used for centering: X={centroid_x:.2f} m, Y={centroid_y:.2f} m")

        # Plot 2: Absolute coordinates
        plt.figure(figsize=(12, 10))
        plt.plot(x, y, 'b-', linewidth=line_width, alpha=alpha_value, label='Trajectory')
        plt.plot(x[0], y[0], 'go', markersize=marker_size, label='Start')
        plt.plot(x[-1], y[-1], 'ro', markersize=marker_size, label='End')
        plt.title("Vehicle Trajectory (Top-Down View, Absolute)", fontsize=font_size, fontweight='bold')
        plt.xlabel("X Position (m)", fontsize=font_size)
        plt.ylabel("Y Position (m)", fontsize=font_size)
        plt.grid(True, alpha=alpha_font)
        plt.legend(fontsize=font_size)
        plt.axis('equal')
        absolute_plot_path = os.path.join(output_dir, "vehicle_trajectory_absolute.png")
        plt.savefig(absolute_plot_path, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"[INFO] Absolute trajectory plot saved to: {absolute_plot_path}")

    # Plot controls over time
    if controls["timestamps"]:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8))

        # Convert timestamps to relative seconds for nicer x-axis
        t0 = controls["timestamps"][0]
        rel_times = [t - t0 for t in controls["timestamps"]]

        # Ensure steer/throttle lists match timestamps; truncate to min length if necessary
        n_t = len(rel_times)
        n_s = len(controls["steer"])
        n_th = len(controls["throttle"])
        n_min = min(n_t, n_s, n_th)
        if n_min < n_t or n_min < n_s or n_min < n_th:
            print(f"[WARN] Control arrays length mismatch (timestamps={n_t}, steer={n_s}, throttle={n_th}), truncating to {n_min}", file=sys.stderr)
            rel_times = rel_times[:n_min]
        else:
            # when lengths match, keep full arrays
            rel_times = rel_times[:n_min]

        # Element-wise scaling (avoid list * int repetition)
        steer_vals = [s * steer_scale_deg for s in controls["steer"][:n_min]]
        throttle_vals = [th * throttle_scale_ms2 for th in controls["throttle"][:n_min]]

        # Steering
        ax1.plot(rel_times, steer_vals, 'b-', linewidth=line_width, label="Steering")
        ax1.set_ylabel(f"Steering (deg)", fontsize=font_size)
        ax1.set_title("Control Inputs Over Time", fontsize=font_size, fontweight='bold')
        ax1.grid(True, alpha=alpha_font)
        ax1.legend(loc='upper right')
        ax1.axhline(y=0, color='k', linestyle='--', alpha=alpha_font)

        # Throttle
        ax2.plot(rel_times, throttle_vals, 'g-', linewidth=line_width, label="Throttle (m/s^2)")
        ax2.set_xlabel("Time (s)", fontsize=font_size)
        ax2.set_ylabel(f"Throttle (m/s^2)", fontsize=font_size)
        ax2.grid(True, alpha=alpha_font)
        ax2.legend(loc='upper right')

        plt.tight_layout()
        control_plot_path = os.path.join(output_dir, "control_inputs.png")
        plt.savefig(control_plot_path, dpi=150, bbox_inches='tight')
        plt.close()
        print(f"[INFO] Control input plot saved to: {control_plot_path}")
        if n_min >= 2:
            print(f"      Duration: {rel_times[-1] - rel_times[0]:.1f} seconds")
        else:
            print(f"      Duration: 0.0 seconds (insufficient samples)")


def main(argv=None):
    args = parse_args(argv)
    json_mode = args.json or args.headless
    
    # Setup signal handler for graceful shutdown
    def signal_handler(sig, frame):
        print("\n[INFO] Interrupted by user (Ctrl+C) - saving plots and exiting...")
        save_plots()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)

    try:
        client = connect_client(args.host, args.port, timeout=args.timeout)
    except Exception as e:
        print(f"[ERROR] cannot connect to CARLA at {args.host}:{args.port}: {e}", file=sys.stderr)
        return 2

    try:
        for s in stream_vehicle_state(client, steps=args.steps, dt=args.dt, role_names=tuple(args.role_names)):
            if json_mode:
                sys.stdout.write(json.dumps(s, default=lambda o: None) + "\n")
                sys.stdout.flush()
            else:
                if "error" in s:
                    print(f"[WARN] {s['timestamp']}: {s['error']}")
                else:
                    pos = s["position"]
                    print(f"\n[INFO]: EGO VEHICLE STATE @ {s['readable_timestamp']}")
                    print(f"\tID: {s['id']} | Role: {s['role_name']}")
                    print(f"\tPosition : X={pos[0]:8.2f}m Y={pos[1]:8.2f}m Z={pos[2]:8.2f}m")
                    if s.get("control") is not None:
                        c = s["control"]
                        print(f"\tControl  :\n\t\t\tSteer={c['steer']:+6.3f} | Throttle={c['throttle']:.3f} | Brake={c['brake']:.3f} | HBrake={c['hand_brake']} | Rev={c['reverse']}")
                    print(f"\tHeading  : {s['heading_deg']:6.2f}°")
                    print(f"\tSpeed    : {s['speed']:6.2f} m/s  ({s['speed']*3.6:6.2f} km/h)")
                    if s.get('accel_est') is not None:
                        print(f"\tAccel    : {s['accel_est']:6.2f} m/s²")
                    print("=" * 80)
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user - saving plots...")
    except Exception as e:
        print(f"[ERROR] streaming failed: {e}", file=sys.stderr)
        return 3
    finally:
        save_plots()
        print(f"[INFO] Telemetry monitoring complete. Total samples: {len(positions)}")

    return 0

def main_video(images_dir: str, out_file: str, fps: float = 10.0):
    create_video_from_images(images_dir, out_file, fps)

if __name__ == "__main__":

    print('+++ THIS SCRIPT CAN RUN THE DEBUG-LIKE OF CARLA CREATE VIDEOS FROM INFERENCE IMAGES +++')

    CARLAS_DEBUG = True

    if CARLAS_DEBUG:
        print('[INFO]: RUNNING CARLA DEBUGGING MODE...')
        ## dummy debugging carla 
        sys.exit(main())
    else:
        print('[INFO]: RUNNING VIDEO CREATION FROM IMAGES SEQUENCE...')
        ## dummy video main
        # These frames where extracted from /workspace/simlingo/japanese_street/testride/IMG_0006.mov 
        # using /workspace/simlingo/japanese_street/testride/extract_video_frames.py.
        # We can chenge the fps and re run these
        fps = 0.2 # 30 fps --> 1 frame each 5 secs 

        images_dir = "/workspace/simlingo/japanese_street/testride/"
        out_file = "/workspace/simlingo/japanese_street/testride/video_tested.mp4"
        main_video(images_dir=images_dir, out_file=out_file, fps=fps)

        images_dir = "/workspace/simlingo/japanese_street/testride/japanese_street_test_simlingo"
        out_file = "/workspace/simlingo/japanese_street/testride/video_simlingo.mp4"
        main_video(images_dir=images_dir, out_file=out_file, fps=fps)

