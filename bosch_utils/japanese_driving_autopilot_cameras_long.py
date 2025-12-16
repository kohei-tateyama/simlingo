import carla
import numpy as np
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
import time
import threading
import queue
import traceback
import json
import argparse
import os
import gzip
from PIL import Image as PILImage
import math

RECORDING_OUTPUT_DIR = "/workspace/simlingo/recording_japan_xml"

from .japanese_driving_autopilot_cameras import JapaneseStyleAutopilot

class LongJapaneseStyleAutopilot(JapaneseStyleAutopilot):
    def __init__(self, *args, autosave_secs=300, rotate_secs=0, repeat=1, num_imgs_per_frame=6, **kwargs):
        super().__init__(*args, **kwargs)
        self.autosave_secs = int(autosave_secs) if autosave_secs else 0
        self.rotate_secs = int(rotate_secs) if rotate_secs else 0
        self.repeat = int(repeat)
        self._last_autosave = time.time()
        self._last_rotate = time.time()
        self._stop_flag = threading.Event()
        self._io_lock = threading.Lock()
        self.num_imgs_per_frame = num_imgs_per_frame

        # Note: initialization of CARLA client, world, traffic manager and
        # folders is handled by the parent class (`JapaneseStyleAutopilot`).
        # Avoid re-initializing those attributes here — the subclass only
        # adds long-run specific state (autosave/rotation/repeat).


    def get_predefined_route(self):
        """Compute a route using CARLA agents GlobalRoutePlanner if available.

        Returns (waypoints, start_idx) where waypoints is a list of carla.Waypoint
        instances and start_idx is an index into map.get_spawn_points() to use
        as the spawn point.

        If the agents package is not available, fall back to the parent's
        simple waypoint lookup using self.route_type definitions.
        """
        # Try to use CARLA agents planner
        try:
            # Import lazily to avoid hard dependency at module import time
            from agents.navigation.global_route_planner import GlobalRoutePlanner
            from agents.navigation.global_route_planner_dao import GlobalRoutePlannerDAO
            dao = GlobalRoutePlannerDAO(self.world.get_map(), sampling_resolution=2.0)
            grp = GlobalRoutePlanner(dao)
            grp.setup()
            # Choose two spawn points as start and goal (use map spawn points)
            spawn_points = self.world.get_map().get_spawn_points()
            if len(spawn_points) < 2:
                raise RuntimeError('Not enough spawn points to plan route')
            start = spawn_points[0].location
            goal = spawn_points[min(1, len(spawn_points)-1)].location
            plan = grp.trace_route(start, goal)
            waypoints = [wp for wp, _ in plan]
            start_idx = 0
            print(f"[INFO] Planner produced {len(waypoints)} waypoints using agents planner")
            return waypoints, start_idx
        except Exception as e:
            # Planner unavailable or failed — fall back to parent's predefined route
            print('=' * self.print_length)
            print('=' * self.print_length)
            print(f"[WARNING] agents planner unavailable or failed: {e}; falling back to predefined routes")
            print('=' * self.print_length)
            print('=' * self.print_length)
            return super().get_predefined_route()

    def run(self):
        """Run autopilot simulation"""
        try:
            # Try to enable synchronous mode for deterministic sensor pairing
            original_settings = None
            sync_enabled = False
            try:
                original_settings = self.world.get_settings()
                new_settings = self.world.get_settings()
                new_settings.synchronous_mode = True
                new_settings.fixed_delta_seconds = self.sleep_interval
                self.world.apply_settings(new_settings)
                sync_enabled = True
                print(f"[INFO]: Enabled synchronous mode (dt={self.sleep_interval}s)")
            except Exception as e:
                print(f"[WARNING]: Could not enable synchronous mode, falling back to async: {e}")

            self.spawn_player_vehicle()
            
            print("\n" + "=" * self.print_length)
            print("[INFO]: AUTOPILOT MODE FROM CARLA - Japanese-Style Driving")
            print("="*self.print_length)
            print(f"Map       : {self.town}")
            print(f"Route     : {self.route_type}")
            print(f"Duration  : {self.duration} seconds")
            print(f"Recording : Enabled")
            print("="*self.print_length + "\n")
            
            # Start time should be measured after the vehicle is spawned and autopilot enabled
            start_time = time.time()
            frame_count = 0
            warmup_done = False

            # Main loop
            while (time.time() - start_time) < self.duration:
                # Enable recording after warmup period and after cameras have been primed
                if not warmup_done and frame_count >= self._warmup_frames:
                    primed_ok = all(self._camera_primed.values())
                    priming_elapsed = time.time() - start_time
                    if primed_ok or (priming_elapsed >= self._priming_timeout):
                        # Drop any buffered warmup frames to avoid writing placeholders
                        with self._buffer_lock:
                            self._image_buffer.clear()
                            self._last_frame_seen_time.clear()
                        self._ready_to_record = True
                        # Reset frame counter to 0 when recording starts (under lock to avoid races)
                        with self._buffer_lock:
                            self.frame_counter = 0
                        warmup_done = True
                        print(f"[INFO]: Warmup complete ({self._warmup_frames} frames skipped), recording started (primed_ok={primed_ok}, priming_elapsed={priming_elapsed:.2f}s)")
                
                # Advance simulator deterministically if possible
                if sync_enabled:
                    try:
                        self.world.tick()
                    except Exception as e:
                        print(f"[WARNING]: world.tick() failed, switching to async sleep: {e}")
                        sync_enabled = False
                        time.sleep(self.sleep_interval)
                else:
                    time.sleep(self.sleep_interval)


                if getattr(self, '_ready_to_record', False):
                    self.record_data()

                # Print progress every 5 seconds
                elapsed = time.time() - start_time
                if int(elapsed) % 5 == 0 and frame_count % 100 == 0:
                    speed = self.recording_data[-1]['speed'] if self.recording_data else 0
                    print(f"[INFO]: {int(elapsed):2d}s / {int(self.duration):2d}s | "
                          f"Frames: {len(self.recording_data):4d} | "
                          f"Speed: {speed:5.1f} km/h")

                frame_count += 1
            print("\n" + "=" * self.print_length)  
            print(f"[INFO]: Simulation completed!")
            total = len(self.recording_data)
            est_folders = int(round(total / float(self.num_imgs_per_frame))) if self.num_imgs_per_frame > 0 else 0
            print(f"[INFO]: Total frames recorded: {total}")
            print(f"[INFO]: Estimated rgb folders expected (measurements/{self.num_imgs_per_frame}): {est_folders}")
            try:
                est_prev = sim.estimate_recorded_frames(D=self.duration, fps=self.fps, Tprim=getattr(self, '_priming_timeout', 0.0), Toverhead=(getattr(self, '_buffer_timeout', 0.0) + 0.1), W=getattr(self, '_warmup_frames', 0), Nlost=0)
                if est_prev > total * 5:
                    print(f"[WARNING]: Estimator earlier returned a large value ({est_prev}); this may be due to missing/duplicate estimator calls or mis-set defaults.")
            except Exception:
                pass
            print("=" * self.print_length + "\n")
            
            # Save data
            self.save_training_format()
            
        finally:
            try:
                if original_settings is not None:
                    self.world.apply_settings(original_settings)
                    print("[INFO]: Restored original world settings (synchronous mode off)")
            except Exception as e:
                print(f"[WARNING]: Failed to restore world settings: {e}")

            self.cleanup()      
        

    

def main():
    print('\n')
    parser = argparse.ArgumentParser(description='Japanese-style autopilot driving in CARLA')
    parser.add_argument('--autopilot', action='store_true', 
                       help='Enable autopilot mode (default: False)')
    parser.add_argument('--duration', type=int, default=60,
                       help='Duration of recording in seconds (default: 60)')
    parser.add_argument('--route', type=str, default='highway',
                       choices=['highway', 'urban', 'simple'],
                       help='Route type: highway, urban, or simple (default: highway)')
    parser.add_argument('--fps', type=float, default=60.0,
                       help='Target frames per second for recording (default: 60)')
    
    args = parser.parse_args()
    
    sim = LongJapaneseStyleAutopilot(
        autopilot=args.autopilot,
        duration=args.duration,
        route_type=args.route,
        fps=args.fps
    )
    # Print an estimate of expected recorded frames using current inputs
    try:
        est = sim.estimate_recorded_frames(
            D=args.duration,
            fps=args.fps,
            Tprim=getattr(sim, '_priming_timeout', 0.0),
            Toverhead=(getattr(sim, '_buffer_timeout', 0.0) + 0.1),
            W=getattr(sim, '_warmup_frames', 0),
            Nlost=0
        )
        print(f"[INFO] Estimated recorded frames: {est}")
    except Exception:
        pass
    sim.run()

if __name__ == '__main__':
    main()