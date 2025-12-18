import os
import numpy as np
import xml.etree.ElementTree as ET
import time
import threading
import argparse
from PIL import Image as PILImage
import carla 

from bosch_utils.japanese_driving_autopilot_cameras import JapaneseStyleAutopilot
from bosch_utils.japanese_driving_autopilot_cameras import _resolve_weather_param
from bosch_utils.config import cfg, RECORDING_OUTPUT_DIR

class LongJapaneseStyleAutopilot(JapaneseStyleAutopilot):
    def __init__(self, *args, autosave_secs=300, rotate_secs=0, repeat=1, random_spawn=False, **kwargs):
        fps = kwargs.pop('fps', None) # trying to enforce the 20 fps as simlingo
        if fps is not None and float(fps) != 20.0:
            print(f"[INFO]: Overriding requested fps={fps} to enforced 20.0 FPS for consistency")
        kwargs['fps'] = 20.0
        self.fps = kwargs['fps']
        self.random_spawn = bool(random_spawn)
        super().__init__(*args, **kwargs)
        # Use a distinct folder prefix for long-run autopilot outputs
        try:
            self.foldername = f"database/simlingo_v3_2026_01_01/auto_long_multicam_jp/training_{self.town}_scenario/routes_{self.route_type}_duration_{self.duration}_training/{self.weather}_weather/ego_{self.spawn_idx}"
            self.folderpath = os.path.join(RECORDING_OUTPUT_DIR, self.foldername)
            os.makedirs(self.folderpath, exist_ok=True)
            os.makedirs(os.path.join(self.folderpath, 'rgb'), exist_ok=True)
            os.makedirs(os.path.join(self.folderpath, 'measurements'), exist_ok=True)
            os.makedirs(os.path.join(self.folderpath, 'boxes'), exist_ok=True)
        except Exception:
            # Non-fatal: if path creation fails, fall back to parent's folder settings
            pass
        self.autosave_secs = int(autosave_secs) if autosave_secs else 0
        self.rotate_secs = int(rotate_secs) if rotate_secs else 0
        self.repeat = int(repeat)
        self._last_autosave = time.time()
        self._last_rotate = time.time()
        self._stop_flag = threading.Event()
        self._io_lock = threading.Lock()

        # Note: initialization of CARLA client, world, traffic manager and
        # folders is handled by the parent class (`JapaneseStyleAutopilot`).
        # Avoid re-initializing those attributes here — the subclass only
        # adds long-run specific state (autosave/rotation/repeat).


    def get_predefined_route(self):
        """Compute a route using CARLA agents GlobalRoutePlanner for long-run data collection.

        Returns (waypoints, start_idx) where waypoints is a list of carla.Waypoint
        instances and start_idx is an index into map.get_spawn_points() to use
        as the spawn point.

        For long runs, picks spawn points that are far apart to create extended routes.
        If the agents package is not available, fall back to the parent's
        simple waypoint lookup using self.route_type definitions.
        """
        # Try to use CARLA agents planner
        try:
            # Import lazily to avoid hard dependency at module import time
            from agents.navigation.global_route_planner import GlobalRoutePlanner, GlobalRoutePlannerDAO
            dao = GlobalRoutePlannerDAO(self.world.get_map(), sampling_resolution=2.0)
            grp = GlobalRoutePlanner(dao)
            grp.setup()
            spawn_points = self.world.get_map().get_spawn_points()
            if len(spawn_points) < 2:
                raise RuntimeError('Not enough spawn points to plan route')
            
            # For long runs, pick distant spawn points to maximize route length
            # Use spawn_idx if specified, otherwise random or default strategy
            if self.spawn_idx is not None:
                start_idx = self.spawn_idx % len(spawn_points)
            elif self.random_spawn:
                import random
                start_idx = random.randint(0, len(spawn_points) - 1)
                print(f"[INFO] Random spawn enabled: selected spawn point {start_idx}")
            else:
                start_idx = 0
            
            # Pick distant goal for longest route
            goal_idx = max(len(spawn_points) // 2, len(spawn_points) - 1)
            
            start = spawn_points[start_idx].location
            goal = spawn_points[goal_idx].location
            
            # Calculate distance for logging
            import math
            dist = math.sqrt((goal.x - start.x)**2 + (goal.y - start.y)**2)
            
            plan = grp.trace_route(start, goal)
            waypoints = [wp for wp, _ in plan]
            
            print(f"[INFO] Planner route: start={start_idx}, goal={goal_idx}, straight-line dist={dist:.1f}m, waypoints={len(waypoints)}")
            return waypoints, start_idx
        except Exception as e:
            # Planner unavailable or failed — fall back to parent's predefined route
            print('=' * self.print_length)
            print('=' * self.print_length)
            print(f"[WARNING]: agents planner unavailable or failed:\n{e}\n[WARNING]: falling back to predefined routes")
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
                # Ensure fixed delta matches enforced 20 FPS
                new_settings.fixed_delta_seconds = 1.0 / self.fps
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
            
            # Calculate target number of frames to record at 20 FPS
            target_frames = int(self.duration * self.fps)
            print(f"[INFO]: Target frames to record: {target_frames} (duration={self.duration}s at {self.fps} fps)")
            
            # Start time (for progress reporting only, not loop control)
            start_time = time.time()
            frame_count = 0
            warmup_done = False

            # Main loop: run until we've recorded the target number of frames
            while len(self.recording_data) < target_frames:
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

                # Print progress every 20 frames
                if len(self.recording_data) % 20 == 0 and len(self.recording_data) > 0:
                    elapsed = time.time() - start_time
                    speed = self.recording_data[-1]['speed'] if self.recording_data else 0
                    pct = 100.0 * len(self.recording_data) / target_frames if target_frames > 0 else 0
                    print(f"[INFO]: Frames: {len(self.recording_data):4d}/{target_frames} ({pct:5.1f}%) | "
                          f"Elapsed: {elapsed:5.1f}s | Speed: {speed:5.1f} km/h")

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
            
            # Give writer thread time to flush all buffered images
            print("[INFO]: Flushing image buffer...")
            max_wait = 120.0
            wait_start = time.time()
            while (time.time() - wait_start) < max_wait:
                with self._buffer_lock:
                    pending = len(self._image_buffer)
                if pending == 0:
                    break
                time.sleep(0.5)
            if pending > 0:
                print(f"[WARN]: {pending} frames still in buffer after {max_wait}s wait")
            else:
                print("[INFO]: All images flushed to disk")
            
        finally:
            try:
                if original_settings is not None:
                    self.world.apply_settings(original_settings)
                    print("[INFO]: Restored original world settings (synchronous mode off)")
            except Exception as e:
                print(f"[WARNING]: Failed to restore world settings: {e}")

            self.cleanup()      
        
####################################################################

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
    parser.add_argument('--fps', type=float, default=20.0,
                       help='Target frames per second for recording (default: 20 - enforced)')
    parser.add_argument('--weather', type=str, default='',
                       help='CARLA weather preset name (e.g. ClearNoon, CloudyNoon, WetNoon)')
    parser.add_argument('--spawn-index', type=int, default=None,
                       help='Spawn point index (0-based, None=use default strategy)')
    parser.add_argument('--random-spawn', action='store_true',
                       help='Randomize spawn location for data variety')
    
    args = parser.parse_args()
    
    sim = LongJapaneseStyleAutopilot(
        autopilot=args.autopilot,
        duration=args.duration,
        route_type=args.route,
        fps=args.fps,
        spawn_idx=args.spawn_index,
        random_spawn=args.random_spawn
    )
    # Apply weather if provided (best-effort; ignore if CARLA not available)
    if getattr(args, 'weather', ''):
        try:
            wp = _resolve_weather_param(args.weather)
            if wp is not None and hasattr(sim, 'world'):
                try:
                    sim.world.set_weather(wp)
                    print(f"[INFO] Applied CARLA weather preset: {args.weather}")
                except Exception as e:
                    print(f"[WARNING] Failed to apply weather: {e}")
        except Exception as e:
            print(f"[WARNING] Unknown weather preset '{args.weather}': {e}")
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
        print(f"[INFO]: Estimated recorded frames: {est}")
    except Exception:
        pass
    sim.run()

if __name__ == '__main__':
    main()