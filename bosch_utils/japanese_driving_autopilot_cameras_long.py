"""Extended Japanese-style autopilot with long-run features.

This module provides `LongRunJapaneseAutopilot`, a thin wrapper around
`JapaneseStyleAutopilot` (from japanese_driving_autopilot_cameras.py) that
adds planner-based route computation, periodic autosave/checkpointing,
output-folder rotation and a simple stuck-detection + respawn mechanism.

The goal is to be conservative: reuse as much behavior as possible from the
original class and add safe, togglable features useful for multi-hour runs.
"""
import os
import time
import math
import threading
import argparse
import gzip
import json
from datetime import datetime
import sys
import glob


try:
    # import the existing class from the same package
    from .japanese_driving_autopilot_cameras import JapaneseStyleAutopilot
except Exception:
    # allow running from workspace root where package semantics may differ
    from japanese_driving_autopilot_cameras import JapaneseStyleAutopilot


class LongRunJapaneseAutopilot(JapaneseStyleAutopilot):
    """Extend `JapaneseStyleAutopilot` with long-run safety features.

    Features added:
    - `autosave_secs`: periodically call `save_training_format()` to checkpoint
      collected data to disk so long runs survive crashes.
    - `rotate_secs`: optional rotate of output folder every N seconds (new folder)
      to limit per-folder size. Rotation will trigger a `save_training_format()`
      and reset in-memory `recording_data`.
    - `use_planner`: when True, try to compute a route with CARLA's
      GlobalRoutePlanner; if unavailable, fall back to predefined routes.
    - `stuck_seconds`: monitor average forward speed and if below threshold for
      `stuck_seconds` trigger a respawn at the next route waypoint.
    - lightweight CLI wrapper for quick testing.

    # Usage
        python -m bosch_utils/japanese_driving_autopilot_cameras_long --autopilot --duration 120 --fps 20 --autosave-secs 30
    """

    def __init__(self, *args, autosave_secs=60, rotate_secs=0, use_planner=True, stuck_seconds=30, stuck_speed_thresh_kmh=1.0, **kwargs):
        super().__init__(*args, **kwargs)
        # Autosave interval in seconds (0 disables)
        self.autosave_secs = int(autosave_secs) if autosave_secs is not None else 0
        self.rotate_secs = int(rotate_secs) if rotate_secs is not None else 0
        self.use_planner = bool(use_planner)
        self.stuck_seconds = int(stuck_seconds) if stuck_seconds is not None else 0
        self.stuck_speed_thresh_kmh = float(stuck_speed_thresh_kmh)

        # Internal rotation bookkeeping
        self._last_autosave = time.time()
        self._last_rotate = time.time()
        self._rotation_index = 0

        # Stuck detection state
        self._speed_history = []  # (timestamp, speed_kmh)
        self._stuck_since = None

        # Planner cache
        self._planner_route = None

        # Start a background watchdog thread to manage autosave/rotate/stuck
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()

    def compute_planner_route(self):
        """Try to compute a route using CARLA's GlobalRoutePlanner.

        If the planner is not available or fails, return the predefined route.
        The method stores a list of waypoints in `self._planner_route`.
        """
        def _auto_add_carla_agents_paths():
            """Try to locate common CARLA PythonAPI/agents paths and add them to sys.path.

            Returns list of paths that were added (may be empty).
            """
            added = []
            # Respect CARLA_ROOT if set
            carla_root = os.environ.get('CARLA_ROOT')
            candidates = []
            if carla_root:
                candidates.append(os.path.join(carla_root, 'PythonAPI', 'agents'))
                candidates.extend(glob.glob(os.path.join(carla_root, 'PythonAPI', 'carla', 'dist', '*.egg')))

            """Extended Japanese-style autopilot with long-run features.

            This module provides `LongRunJapaneseAutopilot`, a thin wrapper around
            `JapaneseStyleAutopilot` (from japanese_driving_autopilot_cameras.py) that
            adds planner-based route computation, periodic autosave/checkpointing,
            output-folder rotation and a simple stuck-detection + respawn mechanism.

            The goal is to be conservative: reuse as much behavior as possible from the
            original class and add safe, togglable features useful for multi-hour runs.
            """
            import os
            import time
            import math
            import threading
            import argparse
            import gzip
            import json
            from datetime import datetime
            import sys
            import glob


            try:
                # import the existing class from the same package
                from .japanese_driving_autopilot_cameras import JapaneseStyleAutopilot
            except Exception:
                # allow running from workspace root where package semantics may differ
                from japanese_driving_autopilot_cameras import JapaneseStyleAutopilot


            class LongRunJapaneseAutopilot(JapaneseStyleAutopilot):
                """Clean long-run autopilot that can execute multiple autopilot runs.

                High-level features:
                - `repeat_runs`: run autopilot multiple times in sequence (useful for batch collection).
                - Autosave and optional folder rotation with thread-safe IO.
                - Planner integration with agents if available; map-based fallback otherwise.
                - Stuck detection and safe respawn that cleans up sensors before reattaching.
                """

                def __init__(self, *args, repeat_runs=1, autosave_secs=60, rotate_secs=0, use_planner=True,
                             stuck_seconds=30, stuck_speed_thresh_kmh=1.0, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.repeat_runs = int(repeat_runs)
                    self.autosave_secs = int(autosave_secs) if autosave_secs else 0
                    self.rotate_secs = int(rotate_secs) if rotate_secs else 0
                    self.use_planner = bool(use_planner)
                    self.stuck_seconds = int(stuck_seconds) if stuck_seconds else 0
                    self.stuck_speed_thresh_kmh = float(stuck_speed_thresh_kmh)

                    # Locks and internal bookkeeping
                    self._io_lock = threading.Lock()
                    self._last_autosave = time.time()
                    self._last_rotate = time.time()
                    self._rotation_index = 0

                    self._speed_history = []
                    self._stuck_since = None
                    self._planner_route = None

                    # Watchdog thread
                    self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
                    self._watchdog_thread.start()

                def _auto_add_carla_agents_paths(self):
                    added = []
                    carla_root = os.environ.get('CARLA_ROOT')
                    candidates = []
                    if carla_root:
                        candidates.append(os.path.join(carla_root, 'PythonAPI', 'agents'))
                        candidates.extend(glob.glob(os.path.join(carla_root, 'PythonAPI', 'carla', 'dist', '*.egg')))
                    common = ['/opt/carla', '/workspace/carla', '/workspace/CarlaUE4', os.path.join(os.getcwd(), 'carla')]
                    for c in common:
                        candidates.append(os.path.join(c, 'PythonAPI', 'agents'))
                        candidates.extend(glob.glob(os.path.join(c, 'PythonAPI', 'carla', 'dist', '*.egg')))
                    for p in candidates:
                        try:
                            if p and os.path.exists(p) and p not in sys.path:
                                sys.path.insert(0, p)
                                added.append(p)
                        except Exception:
                            pass
                    return added

                def compute_planner_route(self):
                    """Compute a route using agents planner if available, otherwise fallback to map stepping."""
                    # try agents planner
                    grp = None
                    try:
                        from agents.navigation.global_route_planner import GlobalRoutePlanner
                        from agents.navigation.global_route_planner_dao import GlobalRoutePlannerDAO
                        dao = GlobalRoutePlannerDAO(self.world.get_map(), sampling_resolution=2.0)
                        grp = GlobalRoutePlanner(dao)
                        grp.setup()
                    except Exception:
                        tried = self._auto_add_carla_agents_paths()
                        if tried:
                            print(f"[INFO]: Added CARLA agents paths: {tried}")
                        try:
                            from agents.navigation.global_route_planner import GlobalRoutePlanner
                            from agents.navigation.global_route_planner_dao import GlobalRoutePlannerDAO
                            dao = GlobalRoutePlannerDAO(self.world.get_map(), sampling_resolution=2.0)
                            grp = GlobalRoutePlanner(dao)
                            grp.setup()
                        except Exception:
                            grp = None

                    def _map_based_route(start_loc, end_loc, step=2.0, max_steps=1000):
                        try:
                            mp = self.world.get_map()
                            cur = mp.get_waypoint(start_loc)
                            if cur is None:
                                return []
                            route = [cur]
                            for _ in range(max_steps):
                                if math.hypot(cur.transform.location.x - end_loc.x, cur.transform.location.y - end_loc.y) < max(4.0, step * 2):
                                    break
                                nxt = cur.next(step)
                                if not nxt:
                                    break
                                cur = nxt[0]
                                route.append(cur)
                            return route
                        except Exception:
                            return []

                    waypoints, start_idx = self.get_predefined_route()
                    if waypoints and len(waypoints) >= 2:
                        start = waypoints[0].transform.location
                        end = waypoints[-1].transform.location
                    else:
                        sp = self.world.get_map().get_spawn_points()
                        if len(sp) < 2:
                            self._planner_route = []
                            return self._planner_route
                        start = sp[0].location
                        end = sp[min(1, len(sp)-1)].location

                    if grp is not None:
                        try:
                            route = grp.trace_route(start, end)
                            planner_wps = [wp for wp, _ in route]
                            self._planner_route = planner_wps
                            return planner_wps
                        except Exception:
                            pass

                    # fallback to map-based
                    planner_wps = _map_based_route(start, end)
                    if planner_wps:
                        self._planner_route = planner_wps
                        return planner_wps

                    # final fallback: predefined waypoints
                    self._planner_route = waypoints
                    return waypoints

                def _watchdog_loop(self):
                    while not getattr(self, '_stopping', False):
                        now = time.time()
                        try:
                            if self.autosave_secs > 0 and (now - self._last_autosave) >= self.autosave_secs:
                                with self._io_lock:
                                    try:
                                        print(f"[WATCHDOG]: Autosave {self.folderpath}")
                                        self.save_training_format()
                                    except Exception as e:
                                        print(f"[WATCHDOG]: Autosave failed: {e}")
                                self._last_autosave = now

                            if self.rotate_secs > 0 and (now - self._last_rotate) >= self.rotate_secs:
                                with self._io_lock:
                                    try:
                                        print(f"[WATCHDOG]: Rotate {self.folderpath}")
                                        self.save_training_format()
                                        base = getattr(self, '_base_foldername', None) or self.foldername
                                        self._rotation_index += 1
                                        new_name = f"{base}_rot{self._rotation_index}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                                        self.foldername = new_name
                                        self.folderpath = os.path.join(os.path.dirname(self.folderpath), self.foldername)
                                        os.makedirs(self.folderpath, exist_ok=True)
                                        for d in ('rgb', 'measurements', 'boxes'):
                                            os.makedirs(os.path.join(self.folderpath, d), exist_ok=True)
                                        self.recording_data = []
                                        print(f"[WATCHDOG]: Rotated to {self.folderpath}")
                                    except Exception as e:
                                        print(f"[WATCHDOG]: Rotation failed: {e}")
                                self._last_rotate = now

                            # stuck detection
                            if self.stuck_seconds > 0 and self.recording_data:
                                nowt = time.time()
                                self._speed_history = [(t, s) for (t, s) in self._speed_history if t >= nowt - max(10, self.stuck_seconds * 2)]
                                self._speed_history.append((nowt, float(self.recording_data[-1].get('speed', 0.0))))
                                window = [s for (t, s) in self._speed_history if t >= nowt - self.stuck_seconds]
                                if window:
                                    avg = sum(window) / len(window)
                                    if avg <= self.stuck_speed_thresh_kmh:
                                        if self._stuck_since is None:
                                            self._stuck_since = nowt
                                        elif nowt - self._stuck_since >= self.stuck_seconds:
                                            print(f"[WATCHDOG]: Detected stuck (avg={avg:.2f} km/h), attempting respawn")
                                            try:
                                                self._attempt_respawn()
                                            except Exception as e:
                                                print(f"[WATCHDOG]: Respawn failed: {e}")
                                            self._stuck_since = None
                                            self._speed_history = []
                                    else:
                                        self._stuck_since = None

                            time.sleep(1.0)
                        except Exception:
                            time.sleep(1.0)

                def cleanup_sensors(self):
                    # Stop and destroy sensors safely
                    for s in list(getattr(self, 'sensors', [])):
                        try:
                            s.stop()
                        except Exception:
                            pass
                        try:
                            s.destroy()
                        except Exception:
                            pass
                    self.sensors = []

                def _attempt_respawn(self):
                    # Destroy sensors, destroy vehicle, and spawn at nearest planner waypoint
                    try:
                        # pick route waypoints
                        wps = self._planner_route or (self.get_predefined_route()[0] or [])
                        if not wps:
                            print('[RESPAWN]: no route to respawn on')
                            return
                        # find nearest
                        ego_loc = None
                        try:
                            ego_loc = self.player_vehicle.get_transform().location
                        except Exception:
                            pass
                        target = wps[0]
                        if ego_loc is not None:
                            best = None
                            best_d = float('inf')
                            for wp in wps:
                                d = math.hypot(wp.transform.location.x - ego_loc.x, wp.transform.location.y - ego_loc.y)
                                if d < best_d:
                                    best = wp; best_d = d
                            if best is not None:
                                target = best

                        # cleanup sensors and vehicle
                        try:
                            self.cleanup_sensors()
                        except Exception:
                            pass
                        try:
                            if self.player_vehicle:
                                self.player_vehicle.destroy()
                        except Exception:
                            pass

                        # spawn
                        blueprint_library = self.world.get_blueprint_library()
                        vehicle_bp = blueprint_library.find('vehicle.tesla.model3')
                        vehicle_bp.set_attribute('role_name', 'hero')
                        spawn_point = target.transform
                        self.player_vehicle = self.world.spawn_actor(vehicle_bp, spawn_point)
                        print(f"[RESPAWN]: respawned at {spawn_point.location}")
                        # reattach cameras
                        try:
                            self.setup_camera()
                        except Exception as e:
                            print(f"[RESPAWN]: reattach cameras failed: {e}")
                        try:
                            self.player_vehicle.set_autopilot(True, self.traffic_manager.get_port())
                        except Exception:
                            pass

                    except Exception as e:
                        print(f"[RESPAWN]: unexpected error: {e}")

                def run(self):
                    """Run `repeat_runs` autopilot runs, saving outputs per run."""
                    original_settings = None
                    try:
                        try:
                            original_settings = self.world.get_settings()
                            new_settings = self.world.get_settings()
                            new_settings.synchronous_mode = True
                            new_settings.fixed_delta_seconds = self.sleep_interval
                            self.world.apply_settings(new_settings)
                            print(f"[INFO]: Enabled synchronous mode (dt={self.sleep_interval}s)")
                        except Exception as e:
                            print(f"[WARN]: cannot enable synchronous mode: {e}")

                        for run_idx in range(max(1, self.repeat_runs)):
                            print(f"[RUN]: Starting run {run_idx+1}/{self.repeat_runs}")
                            # set a base folder name for rotations
                            self._base_foldername = getattr(self, 'foldername', None) or f"autopilot_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                            # ensure spawn and sensors
                            try:
                                self.spawn_player_vehicle()
                            except Exception as e:
                                print(f"[RUN]: spawn failed: {e}")
                                continue

                            # warmup and recording loop similar to parent but scoped per-run
                            start_time = time.time()
                            frame_count = 0
                            warmup_done = False
                            while (time.time() - start_time) < self.duration:
                                if not warmup_done and frame_count >= self._warmup_frames:
                                    primed_ok = all(self._camera_primed.values())
                                    priming_elapsed = time.time() - start_time
                                    if primed_ok or (priming_elapsed >= self._priming_timeout):
                                        with self._buffer_lock:
                                            self._image_buffer.clear(); self._last_frame_seen_time.clear()
                                            self.frame_counter = 0
                                        self._ready_to_record = True
                                        warmup_done = True
                                        print(f"[RUN]: Warmup complete, recording started (primed_ok={primed_ok})")

                                try:
                                    settings = self.world.get_settings()
                                    if getattr(settings, 'synchronous_mode', False):
                                        self.world.tick()
                                    else:
                                        time.sleep(self.sleep_interval)
                                except Exception:
                                    time.sleep(self.sleep_interval)

                                if getattr(self, '_ready_to_record', False):
                                    self.record_data()

                                frame_count += 1

                            print(f"[RUN]: Completed run {run_idx+1}, frames={len(self.recording_data)}")
                            with self._io_lock:
                                try:
                                    self.save_training_format()
                                except Exception as e:
                                    print(f"[RUN]: save failed: {e}")
                            # cleanup sensors and vehicle before next run
                            try:
                                self.cleanup()
                            except Exception:
                                pass

                        print("[INFO]: All runs completed")

                    finally:
                        try:
                            if original_settings is not None:
                                self.world.apply_settings(original_settings)
                        except Exception:
                            pass
                        try:
                            self.cleanup()
                        except Exception:
                            pass

                def _attempt_respawn(self):
                    """Try a simple respawn: destroy and respawn player vehicle at next route waypoint."""
                    try:
                        # find next waypoint from planner or predefined route
                        wps = self._planner_route if self._planner_route else self.get_predefined_route()[0]
                        if not wps:
                            print("[RESPAWN]: No route available to respawn on")
                            return

                        # pick a waypoint near the vehicle (or the first if none)
                        target_wp = None
                        try:
                            ego_loc = self.player_vehicle.get_transform().location
                            best = None
                            best_dist = float('inf')
                            for wp in wps:
                                dx = wp.transform.location.x - ego_loc.x
                                dy = wp.transform.location.y - ego_loc.y
                                d = math.hypot(dx, dy)
                                if d < best_dist:
                                    best = wp
                                    best_dist = d
                            # choose a waypoint a bit ahead (index+3) if possible
                            target_wp = best
                        except Exception:
                            target_wp = wps[0]

                        if target_wp is None:
                            target_wp = wps[0]

                        # destroy and respawn vehicle at target
                        try:
                            if self.player_vehicle:
                                self.player_vehicle.destroy()
                        except Exception:
                            pass

                        # spawn new vehicle at target transform
                        blueprint_library = self.world.get_blueprint_library()
                        vehicle_bp = blueprint_library.find('vehicle.tesla.model3')
                        vehicle_bp.set_attribute('role_name', 'hero')
                        spawn_point = target_wp.transform
                        self.player_vehicle = self.world.spawn_actor(vehicle_bp, spawn_point)
                        print(f"[RESPAWN]: Respawned vehicle at {spawn_point.location}")

                        # reattach cameras and sensors
                        try:
                            self.setup_camera()
                        except Exception as e:
                            print(f"[RESPAWN]: Failed to reattach cameras: {e}")

                        # re-enable autopilot
                        try:
                            self.player_vehicle.set_autopilot(True, self.traffic_manager.get_port())
                            self.traffic_manager.vehicle_lane_offset(self.player_vehicle, -1.5)
                        except Exception:
                            pass

                    except Exception as e:
                        print(f"[RESPAWN]: Unexpected error: {e}")


            def main():
                parser = argparse.ArgumentParser(description='Long-run Japanese-style autopilot (wrapper)')
                parser.add_argument('--autopilot', action='store_true')
                parser.add_argument('--duration', type=int, default=300)
                parser.add_argument('--route', type=str, default='highway')
                parser.add_argument('--fps', type=float, default=30.0)
                parser.add_argument('--autosave-secs', type=int, default=60, help='Periodic autosave interval (0 disables)')
                parser.add_argument('--rotate-secs', type=int, default=0, help='Rotate output folder every N seconds (0 disables)')
                parser.add_argument('--no-planner', action='store_true', help='Disable GlobalRoutePlanner and use predefined routes')
                parser.add_argument('--stuck-secs', type=int, default=30, help='Seconds below speed threshold to consider stuck')
                parser.add_argument('--stuck-speed-kmh', type=float, default=1.0, help='Speed threshold (km/h) for stuck detection')
                args = parser.parse_args()

                sim = LongRunJapaneseAutopilot(autopilot=args.autopilot, duration=args.duration, route_type=args.route, fps=args.fps,
                                               autosave_secs=args.autosave_secs, rotate_secs=args.rotate_secs,
                                               use_planner=(not args.no_planner), stuck_seconds=args.stuck_secs,
                                               stuck_speed_thresh_kmh=args.stuck_speed_kmh)

                # Optionally compute planner route eagerly
                if sim.use_planner:
                    try:
                        sim.compute_planner_route()
                        print(f"[MAIN]: Planner route length: {len(sim._planner_route) if sim._planner_route else 0}")
                    except Exception as e:
                        print(f"[MAIN]: Planner computation failed: {e}")

                try:
                    sim.run()
                except KeyboardInterrupt:
                    print('[MAIN]: Interrupted by user')
                finally:
                    sim.cleanup()


            if __name__ == '__main__':
                main()
