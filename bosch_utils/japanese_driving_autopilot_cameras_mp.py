# Copy of japanese_driving_autopilot_cameras_backup.py with added get_bounding_boxes() method from data_agent.py
# This file adds ego_car dictionary and enriched bounding box information matching the simlingo training format
# TODO clean 

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
import yaml

from pathlib import Path
from bosch_utils.config import cfg, RECORDING_OUTPUT_DIR, IMAGE_FORMAT, IMAGE_EXT, JPG_QUALITY, PNG_COMPRESS_LEVEL, SIMLINGO_VERSION_DIR, NEW_SIMLINGO_MATCH


def _resolve_weather_param(name: str):
    """Resolve a weather name to a carla.WeatherParameters attribute.

    Accepts common CARLA preset names, refer to the config_bosch_utils.yaml for the complete list.
    """

    # weather = carla.WeatherParameters(
    #     cloudiness=10.0,
    #     precipitation=0.0,
    #     sun_altitude_angle=-80.0, # Below horizon for night
    #     sun_azimuth_angle=90.0,
    #     fog_density=0.0
    # )
    ## Usage see later in the code 
    ## world.set_weather(weather)

    def make_weather_parameters(cloudiness=None,
                                precipitation=None,
                                sun_altitude_angle=None,
                                sun_azimuth_angle=None,
                                fog_density=None,
                                precipitation_deposits=None,
                                wetness=None):
        """Build and return a carla.WeatherParameters object from provided values.
        Returns: populated weather object
        """
        try:
            wp = carla.WeatherParameters()
        except Exception:
            raise(RuntimeError("CARLA module not available; cannot create WeatherParameters"))

        mapping = {
            'cloudiness': cloudiness,
            'precipitation': precipitation,
            'sun_altitude_angle': sun_altitude_angle,
            'sun_azimuth_angle': sun_azimuth_angle,
            'fog_density': fog_density,
            'precipitation_deposits': precipitation_deposits,
            'wetness': wetness,
        }

        for k, v in mapping.items():
            if v is not None:
                try:
                    setattr(wp, k, float(v))
                except Exception:
                    try:
                        setattr(wp, k, v)
                    except Exception:
                        pass

        return wp

    def get_weather_object(weather):
        """Normalize various weather inputs into a carla.WeatherParameters object.

        Accepted inputs:
        - None -> returns None
        - str  -> name of CARLA preset (falls back to _resolve_weather_param)
        - dict -> mapping of weather parameter names to values (passed to make_weather_parameters)
        - tuple/list -> positional values interpreted as (cloudiness, precipitation, sun_altitude_angle, sun_azimuth_angle, fog_density)
        """
        if weather is None:
            return None

        # If a preset name, try resolving via existing helper
        if isinstance(weather, str):
            try:
                return _resolve_weather_param(weather)
            except Exception:
                # re-raise with clearer message
                raise ValueError(f"Unknown CARLA weather preset or string: {weather}")

        # If a mapping, use it to construct WeatherParameters
        if isinstance(weather, dict):
            return make_weather_parameters(**weather)

        # If a sequence, map positional args to common names
        if isinstance(weather, (list, tuple)):
            keys = ('cloudiness', 'precipitation', 'sun_altitude_angle', 'sun_azimuth_angle', 'fog_density')
            kw = {k: weather[i] for i, k in enumerate(keys) if i < len(weather)}
            return make_weather_parameters(**kw)

        raise ValueError('Unsupported weather input type; expected None, str, dict, list, or tuple')

    if not name:
        return None
    name = str(name)
    if hasattr(carla.WeatherParameters, name):
        return getattr(carla.WeatherParameters, name)
    # tolerate some common alternative names (case-insensitive)
    for attr in dir(carla.WeatherParameters):
        if attr.lower() == name.lower():
            return getattr(carla.WeatherParameters, attr)
    raise ValueError(f"Unknown CARLA weather preset: {name}")


class JapaneseStyleAutopilot:
    def __init__(self, autopilot=False, duration=60, 
                 route_type='highway', port_localhost=2000, 
                 port_traffic=8000, town='Town13', 
                 fps=20.0, num_imgs_per_frame=6, 
                 callback_debug=False, weather='SoftRainNight',
                 spawn_idx=None):
        
        """Initialize the Japanese-style driving autopilot with 6 cameras.

        Args:
            autopilot (bool): Whether to enable autopilot mode.
            duration (int): Duration of the recording in seconds.
            route_type (str): Type of route to follow ('highway', 'urban', 'simple').
            port_localhost (int): Port for connecting to CARLA server.
            port_traffic (int): Port for traffic manager.
            town (str): Town/map name to load.
            fps (float): Frames per second for recording.
            callback_debug (bool): Enable debug logging in sensor callbacks.
            spawn_idx (int): Spawn point index to use (None = use route default).
        """

        # Connect to CARLA
        print(f"[INFO]: Connecting to CARLA server on localhost:{port_localhost}...", flush=True)
        self.client = carla.Client('localhost', port_localhost)
        # Allow longer timeouts for slower hosts
        self.client_timout_carla = 15.0  # Reduced from 30s to fail faster if CARLA not responding
        self.client.set_timeout(self.client_timout_carla)
        print(f"[INFO]: CARLA client created (timeout={self.client_timout_carla}s)", flush=True)
        self.print_length = 70
        requested_fps = float(fps)
        if requested_fps != 20.0:
            print(f"[INFO]: Overriding requested fps={requested_fps} to enforced 20.0 FPS for consistency")
        self.fps = 20.0
        self.num_imgs_per_frame = num_imgs_per_frame
        self.sleep_interval = 1.0 / self.fps
        self.spawn_idx = spawn_idx
        # Enable or disable per-callback debug logging (can be noisy at high FPS)
        self._callback_debug = bool(callback_debug)
        self.town = town
        self.port_traffic = port_traffic

        print(f'[INFO]: Recording imgs at {self.fps} FPS with interval {self.sleep_interval:.3f}s', flush=True)
        # If a world is already loaded on the server, prefer using it to avoid heavy reloads
        try:
            print(f"[DEBUG MP] About to call self.client.get_world()... 10-30s on first call ...", flush=True)
            current_world = self.client.get_world()
            print(f"[INFO]: client.get_world() returned successfully", flush=True)
            current_map_name = getattr(current_world.get_map(), 'name', '')
            if current_map_name:
                print(f"[INFO]: Server already has map loaded: {current_map_name}", flush=True)
                if self.town in current_map_name:
                    print(f"[INFO]: Current map matches requested town '{self.town}' — using it", flush=True)
                    self.world = current_world
                    # self.world.set_weather(weather) # even the custom one
                    time.sleep(1)
                    skip_load = True
                else:
                    print(f"[INFO]: Current map '{current_map_name}' does NOT match requested town '{self.town}' — will load correct map", flush=True)
                    skip_load = False
            else:
                skip_load = False
        except Exception as e:
            skip_load = False

        # If user explicitly wants to force a map load, set FORCE_LOAD env var or pass --force-load
        FORCE_LOAD = False

        print(f"[DEBUG MP] skip_load={skip_load}, FORCE_LOAD={FORCE_LOAD}", flush=True)
        if not skip_load and not FORCE_LOAD:
            try:
                available_maps = self.client.get_available_maps()
                # print(f"[DEBUG MP] Available maps: {available_maps}", flush=True)
            except Exception:
                available_maps = []

            preferred_map = None
            for m in available_maps:
                if self.town in m:
                    preferred_map = m
                    break

            if preferred_map is not None:
                map_to_load = preferred_map
                print(f"[INFO]: Found server map: {preferred_map} — will attempt to load it", flush=True)
            elif len(available_maps) > 0:
                map_to_load = available_maps[0]
                print(f"[INFO]: {self.town} not found on server — would load {map_to_load} if needed", flush=True)
            else:
                map_to_load = self.town
                print(f"[WARNING]: No maps reported by server; would try short name '{self.town}' if forced", flush=True)

            if not hasattr(self, 'world'):
                max_attempts = 2  # Reduce attempts to fail faster
                attempt = 0
                last_exc = None
                while attempt < max_attempts:
                    try:
                        self.client.set_timeout(60.0)
                        self.world = self.client.load_world(map_to_load)
                        # Restore normal timeout
                        self.client.set_timeout(self.client_timout_carla)
                        print(f"[INFO] load_world() completed successfully!", flush=True)
                        if self.world is None:
                            raise RuntimeError("load_world() returned None")
                        break
                    except Exception as e:
                        last_exc = e
                        attempt += 1
                        print(f"[ERROR MP]: Attempt {attempt}/{max_attempts} failed: {type(e).__name__}: {e}", flush=True)
                        if attempt < max_attempts:
                            wait = 3
                            print(f"[INFO]: Retrying in {wait}s...", flush=True)
                            time.sleep(wait)

                if not hasattr(self, 'world') or self.world is None:
                    error_msg = f"Failed to load map '{map_to_load}' after {max_attempts} attempts. Last error: {last_exc}"
                    print(f"[ERROR]: {error_msg}", flush=True)
                    raise RuntimeError(error_msg)

        time.sleep(1)
        print("")
        print('=' * self.print_length, flush=True)
        print('[INFO]: Setting the Japanese world configuration...', flush=True)
        # Get traffic manager
        print(f"[DEBUG] Getting traffic manager on port {self.port_traffic}...", flush=True)
        try:
            self.traffic_manager = self.client.get_trafficmanager(self.port_traffic)
            print(f"[INFO] Traffic manager obtained successfully", flush=True)
        except Exception as e:
            print(f"[ERROR] Failed to get traffic manager: {e}", flush=True)
            raise
        
        # Setup Japanese-style traffic
        print(f"[DEBUG] Setting up left-hand traffic...", flush=True)
        try:
            self.setup_left_hand_traffic()
            print(f"[INFO] Left-hand traffic setup complete", flush=True)
        except Exception as e:
            print(f"[ERROR] Failed to setup left-hand traffic: {e}", flush=True)
            raise
        
        print(f"[DEBUG] Flipping world infrastructure...", flush=True)
        try:
            self.flip_world_infrastructure_for_lht()
            print(f"[DEBUG] Infrastructure flip complete", flush=True)
        except Exception as e:
            print(f"[ERROR] Failed to flip infrastructure: {e}", flush=True)
            raise
        print('=' * self.print_length, flush=True)
        print("")
        # Weather (optional): apply chosen CARLA weather preset if provided
        self.weather = weather
        if self.weather:
            try:
                wp = _resolve_weather_param(self.weather)
                if wp is not None and hasattr(self, 'world'):
                    try:
                        self.world.set_weather(wp)
                        print(f"[INFO]: Applied CARLA weather preset: {self.weather}")
                    except Exception as e:
                        print(f"[WARNING]: Failed to apply weather '{self.weather}': {e}")
            except Exception as e:
                print(f"[WARNING]: Unknown weather preset '{self.weather}': {e}")
        
        # Autopilot settings
        self.autopilot = autopilot
        self.duration = duration  # seconds
        self.route_type = route_type
        self.enforce_left_hand_traffic = True  # Enable left-hand traffic route correction
        
        # Vehicle
        self.player_vehicle = None
        self.recording_data = []
        
        self._actors_cache = None
        self._actors_cache_frame = -999   # Frame number when cache was last updated
        self._actors_cache_interval = 10  # Update cache every N frames (at 20fps = every 0.5s)
        
        # timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        # self.foldername = f"autopilot_multicamera_japanese_{self.route_type}_{timestamp}"
        # self.folderpath = os.path.join(RECORDING_OUTPUT_DIR, self.foldername)

        # self.foldername = f"database/{SIMLINGO_VERSION_DIR}/auto_short_multicam_jp/training_{self.town}_scenario/routes_{self.route_type}_duration_{self.duration}_training/{self.weather}_weather/ego_{self.spawn_idx}" # ok work
        # If NEW_SIMLINGO_MATCH is absolute (leading '/'), strip it so RECORDING_OUTPUT_DIR
        # remains the true base directory when joining.
        new_simlingo_rel = NEW_SIMLINGO_MATCH.lstrip(os.sep)

        self.foldername = os.path.join(
            new_simlingo_rel,
            "auto_short_multicam_jp",
            "routes_training",
            f"{self.weather}_weather",
            f"{self.town}_Rep0_scenario",
            f"routes_{self.route_type}",
            f"duration_{self.duration}",
            f"ego_{self.spawn_idx}",
        )

        # Prepend the configured RECORDING_OUTPUT_DIR to form the absolute folder path
        self.folderpath = os.path.join(RECORDING_OUTPUT_DIR, self.foldername)
        
        print(f'[INFO]: Created the folder: {self.folderpath}')

        # TODO move this into the config.py/yaml
        os.makedirs(self.folderpath, exist_ok=True)
        # Create training-format subfolders
        os.makedirs(os.path.join(self.folderpath, 'rgb'), exist_ok=True)
        os.makedirs(os.path.join(self.folderpath, 'measurements'), exist_ok=True)
        os.makedirs(os.path.join(self.folderpath, 'boxes'), exist_ok=True)
        os.makedirs(os.path.join(self.folderpath, 'left_signal'), exist_ok=True)
        self.last_image_filename = None
        self.sensors = []

        self.image_size_x = 1024
        self.image_size_y = 512
        self.last_seg_meta = None
        self.frame_counter = 0 # sequential naming (0000, 0001, ...)
        self.frame_camera_counts = {} # Track which cameras have produced images 
        self._stopping = False
        self._warmup_frames = 5 # Warmup camera: skip first N frames to stabilize
        self._ready_to_record = False
        # Per-camera priming: require each camera to produce a valid image before recording
        self._camera_primed = { 'F': False, 'B': False, 'RF': False, 'LF': False, 'RB': False, 'LB': False }
        # Max time to wait for priming (seconds) before falling back
        self._priming_timeout = 3.0
        self._image_buffer = {} # Buffer for images {camera_name: ndarray}
        self._buffer_lock = threading.Lock()
        # Event signaled when we have seen and written a full 6-camera frame
        self._complete_frame_event = threading.Event()
        # Count how many full frames have been observed (writer increments)
        self._complete_frame_count = 0
        # How many full frames to wait for before enabling autopilot
        self._required_full_frames = 1
        # Track last seen time per frame to implement timeout flush
        self._last_frame_seen_time = {}
        self._buffer_timeout = 0.5  # seconds
        # Writer thread
        self._writer_thread = threading.Thread(target=self._buffer_writer, daemon=True)
        self._writer_thread.start()
        # Debug log file for runtime diagnostic messages
        try:
            self._debug_log_path = os.path.join(self.folderpath, 'debug.log')
            with open(self._debug_log_path, 'a') as _:
                pass
        except Exception:
            self._debug_log_path = None
        # By default do not print debug lines to stdout (can be enabled)
        self._print_debug = False
        # GPS trajectory tracking (XY positions)
        self._gps_trajectory = []

    def _log_debug(self, msg):
        try:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            out = f"[{ts}] {msg}\n"
            if getattr(self, '_debug_log_path', None):
                try:
                    with open(self._debug_log_path, 'a') as f:
                        f.write(out)
                except Exception:
                    pass
            # Optionally print to stdout for live observation when enabled
            if getattr(self, '_print_debug', False):
                print(out, end='')
        except Exception:
            pass

    def _save_compressed_png(self, pil_img, dst_path, colors=128, compress_level=9):
        """Save a PIL image as a compressed paletted PNG without changing dimensions.

        - `colors`: number of palette colors to keep (try 128, 64, 32)
        - `compress_level`: zlib compression level 0-9 (9 = max)

        Falls back to a standard PNG save on error.
        """
        try:
            # Ensure RGB for quantization step
            if pil_img.mode not in ('RGB', 'RGBA'):
                pil_img = pil_img.convert('RGB')

            # Use PIL quantize to create a paletted image (P-mode) with adaptive palette
            # MEDIANCUT or FASTOCTREE are available; MEDIANCUT is a solid default.
            pal = pil_img.quantize(colors=colors, method=PILImage.MEDIANCUT)

            # Save with optimization and max compression
            pal.save(dst_path, format='PNG', optimize=True, compress_level=compress_level)
        except Exception:
            try:
                pil_img.save(dst_path, 'PNG', optimize=True, compress_level=compress_level)
            except Exception:
                # Last resort: plain save
                pil_img.save(dst_path, 'PNG')

    def _save_image(self, pil_img, dst_path):
        """Save PIL image according to global IMAGE_FORMAT (JPG or PNG).

        Ensures the file extension matches IMAGE_EXT and handles RGBA->RGB conversion for JPG.
        """
        try:
            root, _ = os.path.splitext(dst_path)
            dst_path = root + IMAGE_EXT
            fmt = IMAGE_FORMAT.upper()
            if fmt == 'JPG':
                if pil_img.mode == 'RGBA':
                    pil_img = pil_img.convert('RGB')
                pil_img.save(dst_path, format='JPG', quality=JPG_QUALITY, optimize=True)
            else:
                # Use compressed paletted PNG when possible
                try:
                    if pil_img.mode not in ('RGB', 'RGBA'):
                        pil_img = pil_img.convert('RGB')
                    pal = pil_img.quantize(colors=128, method=PILImage.MEDIANCUT)
                    pal.save(dst_path, format='PNG', optimize=True, compress_level=PNG_COMPRESS_LEVEL)
                except Exception:
                    pil_img.save(dst_path, format='PNG', optimize=True)
        except Exception:
            try:
                pil_img.save(dst_path)
            except Exception:
                pass

    def estimate_recorded_frames(self, D=None, fps=None, Tprim=None, Toverhead=None, W=None, Nlost=0):
        """Estimate number of recorded timesteps using the user's formula.

        Formula:
            R = max(0, floor((D - Tprim - Toverhead) * fps) - W - Nlost)

        Parameters (defaults taken from instance when None):
            D (float): desired recording duration in seconds (defaults to self.duration)
            fps (float): target frames per second (defaults to self.fps)
            Tprim (float): priming timeout in seconds (defaults to self._priming_timeout)
            Toverhead (float): estimated extra overhead seconds (defaults to _buffer_timeout + 0.1s)
            W (int): warmup frames to skip (defaults to self._warmup_frames)
            Nlost (int): estimated lost frames due to missing sensors (defaults 0)

        Returns:
            int: estimated number of recorded frames (non-negative)

        Example (30 fps):
            If D=60, fps=30, W=5, Tprim=0.5, Toverhead=0.5, Nlost=0:
                R = floor((60 - 0.5 - 0.5) * 30) - 5 = 1765
        """
        # Use instance defaults when parameters are not provided
        D = float(D) if D is not None else float(getattr(self, 'duration', 0.0))
        fps = float(fps) if fps is not None else float(getattr(self, 'fps', 0.0))
        W = int(W) if W is not None else int(getattr(self, '_warmup_frames', 0))
        Tprim = float(Tprim) if Tprim is not None else float(getattr(self, '_priming_timeout', 0.0))
        if Toverhead is None:
            # Conservative default: buffer timeout plus small I/O overhead
            Toverhead = float(getattr(self, '_buffer_timeout', 0.0)) + 0.1
        else:
            Toverhead = float(Toverhead)

        Nlost = int(Nlost)

        # Compute raw estimate and clamp to non-negative
        raw = math.floor((D - Tprim - Toverhead) * fps) - W - Nlost
        return max(0, int(raw))
        
    def setup_left_hand_traffic(self):
        """Configure traffic manager for left-hand traffic (Japan/UK)"""
        # print("Configuring Japanese-style (left-hand) traffic...")
        self.traffic_manager.set_global_distance_to_leading_vehicle(2.5)

        # Compute and apply geometry-aware left-hand driving configuration
        try:
            # prefer to compute a safe offset using current map and default spawn point
            self.enforce_driving_side(side='left', margin=0.10)
        except Exception:
            # Fallback to a conservative default offset (meters)
            try:
                self.traffic_manager.global_lane_offset = -0.8
            except Exception:
                pass

        # NOTE: NPCs are spawned AFTER ego vehicle to avoid blocking spawn points
        # See spawn_player_vehicle() which calls spawn_npc_vehicles() after ego spawns
    
    def flip_world_infrastructure_for_lht(self):
        """
        Flip traffic lights and signs to face left-hand lanes for proper camera visibility.
        
        **Purpose**: CARLA 0.9.15 maps are designed for right-hand traffic. When driving in
        left lanes, signals face away from camera. This method relocates movable actors
        (traffic lights, stop/yield signs) and spawns new speed limit signs at mirrored positions.
        
        **Trade-offs**:
        - ✅ Vision models see front-facing signals (better training data quality)
        - ⚠️ Traffic Manager may get confused (TM uses OpenDRIVE topology, not actor positions)
        - ⚠️ Assumes Y-axis mirroring works for map layout (not guaranteed for all towns)
        
        **Usage**: Enable via environment variable FLIP_INFRASTRUCTURE=1
        """
        if not int(os.environ.get('FLIP_INFRASTRUCTURE', '0')):
            return
        
        print("[INFO]: Flipping world infrastructure for left-hand traffic...")
        
        try:
            world = self.world
            blueprint_library = world.get_blueprint_library()
            carla_map = world.get_map()
            
            relocated_count = 0
            spawned_count = 0
            self._flipped_actors = []  # Track spawned actors for cleanup
            
            # PART 1: Flip movable actors (traffic lights, stop, yield)
            movable_types = ['traffic.traffic_light', 'traffic.stop', 'traffic.yield']
            for actor in world.get_actors():
                if any(t in actor.type_id for t in movable_types):
                    try:
                        t = actor.get_transform()
                        # Mirror across Y-axis
                        t.location.y *= -1
                        # Rotate 180 degrees to face opposite direction
                        t.rotation.yaw = (t.rotation.yaw + 180) % 360
                        actor.set_transform(t)
                        relocated_count += 1
                    except RuntimeError as e:
                        print(f"[WARN]: Could not move {actor.type_id} ({actor.id}): {e}")
            
            # PART 2: Handle static landmarks (speed limit signs)
            # OpenDRIVE landmark type 101 = speed limit signs
            try:
                speed_landmarks = carla_map.get_all_landmarks_of_type('101')
                for lm in speed_landmarks:
                    try:
                        t = lm.transform
                        # Mirror across Y-axis
                        t.location.y *= -1
                        # Rotate 180 degrees
                        t.rotation.yaw = (t.rotation.yaw + 180) % 360
                        
                        # Try to spawn new sign at flipped location
                        value = lm.value if hasattr(lm, 'value') else None
                        if value:
                            bp_id = f"static.prop.speedlimit.{value}"
                            try:
                                speed_bp = blueprint_library.find(bp_id)
                            except:
                                speed_bp = blueprint_library.find("static.prop.speedlimit")
                        else:
                            speed_bp = blueprint_library.find("static.prop.speedlimit")
                        
                        new_sign = world.try_spawn_actor(speed_bp, t)
                        if new_sign:
                            spawned_count += 1
                            self._flipped_actors.append(new_sign.id)
                    except Exception as e:
                        pass  # Fail silently for individual signs
            except Exception as e:
                print(f"[WARN]: Could not process speed limit signs: {e}")
            
            print(f"[INFO]: Infrastructure flip complete: {relocated_count} actors relocated, {spawned_count} signs spawned")
            
        except Exception as e:
            print(f"[ERROR]: Failed to flip infrastructure: {e}")

    def enforce_driving_side(self, side='left', margin=0.10):
        """Compute a safe lateral lane offset (meters) for left/right driving and apply it.

        - side: 'left' or 'right'
        - margin: small clearance from curb in metres

        The method attempts to query a representative waypoint (spawn point) to get lane width,
        and obtains ego vehicle half-width from its bounding box when available. It then computes
        a desired offset and applies it to both `traffic_manager.global_lane_offset` and,
        when a vehicle is available, `traffic_manager.vehicle_lane_offset(self.player_vehicle, offset)`.

        Returns the applied offset.
        """
        dir_sign = -1.0 if side == 'left' else 1.0

        # Default fallbacks
        lane_w = 3.5
        vehicle_half_w = 0.9

        try:
            # pick a representative spawn point or player position
            spawn_points = self.world.get_map().get_spawn_points()
            if spawn_points:
                sp = spawn_points[0]
            else:
                sp = None
        except Exception:
            sp = None

        try:
            if sp is not None:
                wp = self.world.get_map().get_waypoint(sp.location)
                if wp is not None and getattr(wp, 'lane_width', None) is not None:
                    lane_w = float(wp.lane_width)
        except Exception:
            pass

        try:
            if self.player_vehicle is not None:
                bb = getattr(self.player_vehicle, 'bounding_box', None)
                if bb is not None:
                    vehicle_half_w = float(bb.extent.y)
        except Exception:
            pass

        # compute safe offset so vehicle remains within lane (from lane center)
        max_safe = max(0.02, lane_w / 2.0 - 0.02)  # small safety clamp
        desired = dir_sign * (lane_w / 2.0 - vehicle_half_w - float(margin))
        # clamp
        if desired > max_safe:
            desired = max_safe
        if desired < -max_safe:
            desired = -max_safe
        
        # Safety validation: ensure computed value is finite and within expected bounds
        try:
            if not math.isfinite(desired) or abs(desired) > 2.5:
                print(f"[WARN]: Computed lane offset {desired} out of expected range; clamping to safe value")
                desired = max(-2.5, min(2.5, desired))
        except Exception:
            # If math is not available for some reason, proceed with clamped value above
            pass
        # Apply to traffic manager
        try:
            self.traffic_manager.global_lane_offset = desired
        except Exception:
            pass

        try:
            # If the player vehicle exists, apply per-vehicle offset as well
            if self.player_vehicle is not None:
                self.traffic_manager.vehicle_lane_offset(self.player_vehicle, desired)
        except Exception:
            pass

        # Ensure traffic manager light/behavior is coherent: make NPCs obey lights by default
        try:
            # 0 => obey lights, so set ignore_lights_percentage to 0 for all vehicles
            self.traffic_manager.ignore_lights_percentage(self.player_vehicle if self.player_vehicle else None, 0)
        except Exception:
            # some TM versions expect actor arg or global setting; set per-npc in spawn loop if needed
            pass

        try:
            self._driving_side_offset = float(desired)
        except Exception:
            self._driving_side_offset = desired

        # Log result for debugging
        try:
            print(f"[INFO]: enforce_driving_side: applied offset={desired:.2f}m (lane_w={lane_w:.2f}, veh_half_w={vehicle_half_w:.2f}) for side='{side}'")
        except Exception:
            pass

        return desired

    def detect_traffic_infrastructure_issues(self, max_distance=50.0):
        """
        Detect traffic lights and signs that may be facing away from ego vehicle.
        
        CARLA 0.9.15 maps are designed for right-hand traffic. When driving in left lanes,
        traffic lights and signs may face the wrong direction.
        
        Args:
            max_distance: Maximum distance (meters) to check for traffic infrastructure
        
        Returns:
            dict with 'back_facing_lights' (count), 'warnings' (list), and 'signals' (list of signal metadata)
        """
        if not self.player_vehicle:
            return {'back_facing_lights': 0, 'warnings': [], 'signals': []}
        
        ego_location = self.player_vehicle.get_location()
        ego_transform = self.player_vehicle.get_transform()
        ego_forward = ego_transform.get_forward_vector()
        
        warnings = []
        back_facing_count = 0
        signals = []
        
        try:
            # Check traffic lights (actors we can query)
            actors = self.world.get_actors().filter('traffic.traffic_light')
            
            for light in actors:
                light_loc = light.get_location()
                distance = light_loc.distance(ego_location)
                
                if distance < max_distance:
                    # Get light's forward vector (direction it's facing)
                    light_transform = light.get_transform()
                    light_forward = light_transform.get_forward_vector()
                    
                    # Vector from light to ego
                    to_ego = ego_location - light_loc
                    to_ego_norm = to_ego / (distance + 0.001)  # normalize
                    
                    # Dot product: positive if light faces toward ego, negative if away
                    dot = (light_forward.x * to_ego_norm.x + 
                           light_forward.y * to_ego_norm.y + 
                           light_forward.z * to_ego_norm.z)
                    
                    # Build signal metadata record
                    # facing_dot interpretation:
                    #   > 0.7: Light FACES ego (colored lens visible)
                    #   0.0 to 0.7: Light at angle (partially visible)
                    #   < -0.3: Light FACES AWAY (approaching from back, only metal housing visible)
                    visible_from_ego = bool(dot > 0.3)  # Only consider visible if reasonably facing ego
                    
                    signal_record = {
                        'id': int(light.id),
                        'type': 'traffic_light',
                        'subtype': 'traffic_light',  # vs 'speed_limit', 'stop_sign', etc.
                        'position': [float(light_loc.x), float(light_loc.y), float(light_loc.z)],
                        'distance': float(distance),
                        'facing_dot': float(dot),
                        'is_back_facing': bool(dot < -0.3),
                        'visible_from_ego': visible_from_ego,
                        'state': str(light.get_state()) if hasattr(light, 'get_state') else 'Unknown',
                        'approaching_from': 'front' if dot > 0.3 else ('side' if dot > -0.3 else 'back')
                    }
                    signals.append(signal_record)
                    
                    if dot < -0.3:  # Light facing significantly away from ego
                        back_facing_count += 1
                        warnings.append(
                            f"Traffic light at ({light_loc.x:.1f}, {light_loc.y:.1f}) "
                            f"faces AWAY from ego (dist={distance:.1f}m, state={signal_record['state']})"
                        )
        except Exception as e:
            warnings.append(f"Error scanning traffic lights: {e}")
        
        # Attempt to detect traffic signs (static meshes - best effort)
        try:
            # Get level bounding boxes for traffic signs (static meshes)
            # Note: These don't have orientation info, only positions
            import carla
            if hasattr(carla, 'CityObjectLabel'):
                try:
                    sign_bbs = self.world.get_level_bbs(carla.CityObjectLabel.TrafficSigns)
                    for bb in sign_bbs:
                        # Bounding box center
                        sign_loc = bb.location
                        distance = sign_loc.distance(ego_location)
                        
                        if distance < max_distance:
                            # We can't determine orientation for static meshes, so mark as 'unknown'
                            signal_record = {
                                'id': -1,  # No actor ID for static meshes
                                'type': 'traffic_sign',
                                'subtype': 'unknown_sign',  # Could be speed_limit, stop, yield, etc.
                                'position': [float(sign_loc.x), float(sign_loc.y), float(sign_loc.z)],
                                'distance': float(distance),
                                'facing_dot': None,  # Cannot determine for static meshes
                                'is_back_facing': None,  # Unknown orientation
                                'visible_from_ego': None,  # Cannot determine
                                'state': 'N/A',
                                'approaching_from': 'unknown'
                            }
                            signals.append(signal_record)
                except Exception as sign_error:
                    warnings.append(f"Failed to query traffic signs: {sign_error}")
        except Exception as e:
            warnings.append(f"Error scanning traffic signs: {e}")
        
        return {
            'back_facing_lights': back_facing_count,
            'warnings': warnings,
            'signals': signals
        }

    def _verify_and_correct_route_for_left_hand_traffic(self, route_waypoints):
        """
        Verify route waypoints align with left-hand driving and correct if needed.
        
        Returns corrected list of waypoints.
        """
        print(f"[DEBUG] _verify_and_correct_route_for_left_hand_traffic ENTERED (got {len(route_waypoints) if route_waypoints else 0} waypoints)")
        if not route_waypoints or len(route_waypoints) == 0:
            print("[DEBUG] No waypoints to verify, returning early")
            return route_waypoints
        
        corrected = []
        corrections_made = 0
        sample_log_interval = max(1, len(route_waypoints) // 10)
        
        for i, wp in enumerate(route_waypoints):
            if wp is None:
                corrected.append(wp)
                continue
            
            # Check if left lane exists and is drivable
            left_wp = wp.get_left_lane()
            if left_wp and left_wp.lane_type == carla.LaneType.Driving:
                # Only switch if left lane is same direction
                same_direction = (wp.lane_id > 0) == (left_wp.lane_id > 0)
                if same_direction:
                    corrected.append(left_wp)
                    corrections_made += 1
                    
                    if corrections_made <= 3 or i % sample_log_interval == 0:
                        print(f"[INFO] Route waypoint {i}: switched from lane {wp.lane_id} to left lane {left_wp.lane_id}")
                else:
                    corrected.append(wp)
            else:
                corrected.append(wp)
        
        if corrections_made > 0:
            print(f"[INFO] Left-hand route correction: adjusted {corrections_made}/{len(route_waypoints)} waypoints")
        else:
            print(f"[INFO] Route already aligned with left-hand traffic")
        
        return corrected

    def setup_camera(self):
        """Attach 6 RGB cameras around the vehicle: Front, Back, RF, LF, RB, LB.
        Save images into per-frame folders: /folderpath/0XXX/{F,B,RF,LF,RB,LB}.png
        """
        if not self.player_vehicle:
            raise RuntimeError("Player vehicle not spawned yet")

        blueprint_library = self.world.get_blueprint_library()
        
        # Define 6 camera configurations: name, transform, FOV
        # Heights matched; front/back on center-line; corners angled appropriately
        camera_configs = [
            {
                'name': 'F',  # Front camera
                'transform': carla.Transform(
                    carla.Location(x=2.5, y=0.0, z=1.5),
                    carla.Rotation(pitch=0.0, yaw=0.0, roll=0.0)
                ),
                'fov': '110'
            },
            {
                'name': 'B',  # Back camera
                'transform': carla.Transform(
                    carla.Location(x=-2.5, y=0.0, z=1.5),
                    carla.Rotation(pitch=0.0, yaw=180.0, roll=0.0)
                ),
                'fov': '110'
            },
            {
                'name': 'RF',  # Right Front camera
                'transform': carla.Transform(
                    carla.Location(x=1.0, y=1.0, z=1.5),
                    carla.Rotation(pitch=0.0, yaw=55.0, roll=0.0)
                ),
                'fov': '110'
            },
            {
                'name': 'LF',  # Left Front camera
                'transform': carla.Transform(
                    carla.Location(x=1.0, y=-1.0, z=1.5),
                    carla.Rotation(pitch=0.0, yaw=-55.0, roll=0.0)
                ),
                'fov': '110'
            },
            {
                'name': 'RB',  # Right Back camera
                'transform': carla.Transform(
                    carla.Location(x=-1.0, y=1.0, z=1.5),
                    carla.Rotation(pitch=0.0, yaw=125.0, roll=0.0)
                ),
                'fov': '110'
            },
            {
                'name': 'LB',  # Left Back camera
                'transform': carla.Transform(
                    carla.Location(x=-1.0, y=-1.0, z=1.5),
                    carla.Rotation(pitch=0.0, yaw=-125.0, roll=0.0)
                ),
                'fov': '110'
            }
        ]
        
        # Spawn each camera and attach callback
        for cam_config in camera_configs:
            cam_bp = blueprint_library.find('sensor.camera.rgb')
            cam_bp.set_attribute('image_size_x', str(self.image_size_x))
            cam_bp.set_attribute('image_size_y', str(self.image_size_y))
            cam_bp.set_attribute('fov', cam_config['fov'])
            # Ensure cameras sample at same rate as recording loop
            try:
                cam_bp.set_attribute('sensor_tick', str(self.sleep_interval))
            except Exception:
                pass
            
            camera = self.world.spawn_actor(
                cam_bp, 
                cam_config['transform'], 
                attach_to=self.player_vehicle
            )
            
            # Create closure to capture camera name
            cam_name = cam_config['name']
            
            def make_callback(camera_name):
                def _on_image(image):
                    if getattr(self, '_stopping', False):
                        return

                    try:
                        # Always use internal frame_counter for consistent numbering with record_data()
                        # (image.frame is the simulator's global frame number, often very high like 20000+)
                        with self._buffer_lock:
                            frame_num = int(self.frame_counter)

                        # Convert CARLA image and push into in-memory buffer for coordinated writing
                        try:
                            img_array = np.frombuffer(image.raw_data, dtype=np.uint8)
                            img_array = img_array.reshape((image.height, image.width, 4))  # BGRA
                            img_rgb = img_array[:, :, :3][:, :, ::-1]  # Convert BGRA to RGB

                            # Validate image is not all black (common during startup/shutdown)
                            im_max = int(img_rgb.max())
                            # Only emit verbose per-callback debug lines when explicitly enabled
                            if getattr(self, '_callback_debug', False):
                                self._log_debug(f"callback {camera_name} frame={frame_num} max={im_max}")
                            if im_max < 5:
                                return

                            # Mark this camera as primed (saw first valid image)
                            try:
                                self._camera_primed[camera_name] = True
                            except Exception:
                                pass

                            # Push into buffer so writer can detect complete frames even before _ready_to_record
                            with self._buffer_lock:
                                frame_dict = self._image_buffer.setdefault(frame_num, {})
                                # store a copy to avoid referencing shared memory
                                frame_dict[camera_name] = img_rgb.copy()
                                self._last_frame_seen_time[frame_num] = time.time()
                                # update camera counts for diagnostics
                                try:
                                    s = self.frame_camera_counts.setdefault(frame_num, set())
                                    s.add(camera_name)
                                except Exception:
                                    pass
                        except Exception as e:
                            if not getattr(self, '_stopping', False):
                                print(f"[WARN] Failed to process {camera_name} image: {e}")
                                traceback.print_exc()
                    except Exception as e:
                        if not getattr(self, '_stopping', False):
                            print(f"[ERROR] Camera callback error for {camera_name}: {e}")

                return _on_image
            
            camera.listen(make_callback(cam_name))
            self.sensors.append(camera)
        
        print(f"[INFO]: Attached 6 cameras: F, B, RF, LF, RB, LB")
        
        # Semantic segmentation camera (DISABLED)
        # Uncomment below to enable semantic segmentation recording
        # try:
        #     self.setup_semantic_camera()
        # except Exception as e:
        #     print(f"Failed to setup semantic camera: {e}")

    def setup_semantic_camera(self):
        """Attach a semantic segmentation camera and save mask + metadata per frame."""
        if not self.player_vehicle:
            raise RuntimeError("Player vehicle not spawned yet")

        blueprint_library = self.world.get_blueprint_library()
        sem_bp = blueprint_library.find('sensor.camera.semantic_segmentation')
        sem_bp.set_attribute('image_size_x', str(self.image_size_x))
        sem_bp.set_attribute('image_size_y', str(self.image_size_y))
        sem_bp.set_attribute('fov', '90')
        # sample at same rate as RGB (use sensor_tick to throttle if needed)
        sem_bp.set_attribute('sensor_tick', '0.05')

        sem_transform = carla.Transform(carla.Location(x=1.5, z=2.0))
        sem_cam = self.world.spawn_actor(sem_bp, sem_transform, attach_to=self.player_vehicle)

        def _on_semantic(image):
            try:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                color_fname = f"seg_color_{timestamp}.png"
                color_path = os.path.join(self.folderpath, 'img', color_fname)
                # save a human-view color image using CityScapes palette
                # Use frame id for deterministic pairing when available
                if hasattr(image, 'frame'):
                    base = f"frame_{image.frame:08d}"
                else:
                    base = datetime.now().strftime('frame_%Y%m%d_%H%M%S_%f')

                # save semantic color image into img/ with same base
                color_fname = f"{base}_seg_color.png"
                color_path = os.path.join(self.folderpath, 'img', color_fname)
                try:
                    image.save_to_disk(color_path, carla.ColorConverter.CityScapesPalette)
                except Exception:
                    image.save_to_disk(color_path)

                # Robust extraction of class ids from raw_data.
                # CARLA sometimes stores the class id in the low byte of a uint32 per-pixel,
                # or in one of the BGRA bytes. Try multiple strategies and pick the one with
                # meaningful (non-zero) distribution.
                mask = None
                try:
                    arr32 = np.frombuffer(image.raw_data, dtype=np.uint32)
                    arr32 = arr32.reshape((image.height, image.width))
                    mask_candidate = (arr32 & 0xFF).astype(np.int32)
                    # accept candidate if it has >1 unique value or many non-zero pixels
                    u, c = np.unique(mask_candidate, return_counts=True)
                    if (len(u) > 1) or (int((mask_candidate != 0).sum()) > 10):
                        mask = mask_candidate
                except Exception:
                    mask = None

                if mask is None:
                    try:
                        arr = np.frombuffer(image.raw_data, dtype=np.uint8).reshape((image.height, image.width, 4))
                        # check each channel (B,G,R,A) for meaningful values
                        channel_scores = []
                        for ch in range(4):
                            chvals = arr[:, :, ch]
                            nz = int((chvals != 0).sum())
                            channel_scores.append(nz)
                        best_ch = int(np.argmax(channel_scores))
                        mask_candidate = arr[:, :, best_ch].astype(np.int32)
                        u, c = np.unique(mask_candidate, return_counts=True)
                        if (len(u) > 1) or (int((mask_candidate != 0).sum()) > 10):
                            mask = mask_candidate
                    except Exception:
                        mask = None

                # If still None, fall back to low-byte of uint32 without checks
                if mask is None:
                    try:
                        arr32 = np.frombuffer(image.raw_data, dtype=np.uint32)
                        arr32 = arr32.reshape((image.height, image.width))
                        mask = (arr32 & 0xFF).astype(np.int32)
                    except Exception:
                        # last resort: zeros
                        mask = np.zeros((image.height, image.width), dtype=np.int32)

                # Save mask into img/ with same base
                mask_fname = f"{base}_seg_mask.png"
                mask_path = os.path.join(self.folderpath, 'img', mask_fname)
                saved_mask_path = None
                try:
                    from PIL import Image
                    # Ensure mask fits into 8-bit for PNG viewers; if max class id exceeds 255,
                    # scale down with clipping (most use-cases have <256 classes).
                    mmax = int(mask.max()) if mask.size else 0
                    if mmax > 255:
                        scaled = (mask.astype(np.float32) / float(mmax) * 255.0).astype(np.uint8)
                    else:
                        scaled = mask.astype(np.uint8)
                    Image.fromarray(scaled).save(mask_path)
                    saved_mask_path = os.path.join('img', mask_fname)
                except Exception:
                    # fallback to npz if saving as PNG fails
                    npz_fname = f"{base}_seg_mask.npz"
                    np.savez_compressed(os.path.join(self.folderpath, 'img', npz_fname), mask=mask)
                    saved_mask_path = os.path.join('img', npz_fname)

                # Build mapping of present indices and counts
                unique, counts = np.unique(mask, return_counts=True)
                counts_map = {int(u): int(c) for u, c in zip(unique, counts)}

                # Build detailed mapping with a sample RGB for each class (written here during collection)
                present_detailed = {}
                try:
                    from PIL import Image
                    # load the saved color image to sample RGB values (ensure consistent saved path)
                    color_arr = None
                    try:
                        color_arr = np.array(Image.open(color_path).convert('RGB'))
                    except Exception:
                        color_arr = None

                    for u, c in zip(unique, counts):
                        ui = int(u)
                        sample_rgb = [0, 0, 0]
                        if color_arr is not None:
                            ys, xs = np.where(mask == ui)
                            if ys.size > 0:
                                idx = len(ys) // 2
                                y = ys[idx]
                                x = xs[idx]
                                sample_rgb = [int(v) for v in color_arr[y, x, :3]]
                        present_detailed[str(ui)] = {'count': int(c), 'sample_rgb': sample_rgb}
                except Exception:
                    # fallback to counts only
                    present_detailed = {str(int(u)): {'count': int(c), 'sample_rgb': [0, 0, 0]} for u, c in zip(unique, counts)}

                meta = {
                    'base': base,
                    'timestamp': timestamp,
                    'color_image': os.path.join('img', color_fname),
                    'mask_image': saved_mask_path,
                    'present_indices': counts_map,
                    'present_indices_detailed': present_detailed,
                }

                # Create a bright, human-friendly visualization of the mask.
                try:
                    from PIL import Image
                    import colorsys

                    mask_arr = mask.astype(np.int32)
                    unique_vals = np.unique(mask_arr)

                    def gen_palette(n):
                        pal = []
                        for i in range(n):
                            # golden-ratio step in hue gives well-separated colors
                            h = (i * 0.618033988749895) % 1.0
                            s = 0.65
                            v = 0.95
                            r, g, b = colorsys.hsv_to_rgb(h, s, v)
                            pal.append((int(r * 255), int(g * 255), int(b * 255)))
                        return pal

                    # Assign bright colors: reserve index 0 for background as light gray
                    color_map = {}
                    nonzero_vals = [int(v) for v in unique_vals if int(v) != 0]
                    palette = gen_palette(max(1, len(nonzero_vals)))
                    for i, v in enumerate(nonzero_vals):
                        color_map[v] = palette[i]
                    if 0 in unique_vals:
                        color_map[0] = (200, 200, 200)

                    h, w = mask_arr.shape
                    color_img = np.zeros((h, w, 3), dtype=np.uint8)
                    for v, col in color_map.items():
                        color_img[mask_arr == int(v)] = col

                    color_pil = Image.fromarray(color_img)

                    # If a recent RGB exists, blend to produce a more natural overlay
                    if self.last_image_filename:
                        rgb_full = os.path.join(self.folderpath, self.last_image_filename)
                        try:
                            if os.path.exists(rgb_full):
                                rgb_im = Image.open(rgb_full).convert('RGB')
                                if rgb_im.size != color_pil.size:
                                    rgb_im = rgb_im.resize(color_pil.size)
                                color_pil = Image.blend(rgb_im, color_pil, alpha=0.45)
                        except Exception:
                            pass

                    viz_fname = f"{base}_seg_mask_viz.png"
                    viz_path = os.path.join(self.folderpath, 'img', viz_fname)
                    try:
                        color_pil.save(viz_path)
                        meta['mask_viz'] = os.path.join('img', viz_fname)
                    except Exception:
                        pass
                except Exception:
                    pass

                meta = {
                    'base': base,
                    'timestamp': timestamp,
                    'color_image': os.path.join('img', color_fname),
                    'mask_image': saved_mask_path,
                    'present_indices': counts_map,
                }

                # write paired metadata JSON into img/ using same base
                meta_fname = f"{base}.json"
                meta_path = os.path.join(self.folderpath, 'img', meta_fname)
                with open(meta_path, 'w') as f:
                    json.dump(meta, f, indent=2)

                # append to NDJSON log in text/ for session-level records
                try:
                    with open(self.ndjson_path, 'a') as f:
                        f.write(json.dumps({'type': 'segmentation', **meta}) + '\n')
                except Exception:
                    pass

                # store latest segmentation meta for main loop to attach to frame records
                self.last_seg_meta = meta
            except Exception as e:
                print(f"[ERROR]: error in semantic callback: {e}")

        sem_cam.listen(_on_semantic)
        self.sensors.append(sem_cam)
        
    def spawn_npc_vehicles(self, num_vehicles=30):
        """Spawn NPC vehicles following Japanese traffic rules"""
        blueprint_library = self.world.get_blueprint_library()
        spawn_points = self.world.get_map().get_spawn_points()
        
        print(f"[INFO]: Spawning {num_vehicles} NPC vehicles...")
        
        # Use stored offset computed by enforce_driving_side if available, otherwise compute now
        offset = getattr(self, '_driving_side_offset', None)
        if offset is None:
            try:
                offset = self.enforce_driving_side(side='left', margin=0.10)
                print(f"[INFO]: Computed NPC offset: {offset:.2f}m (LEFT)")
            except Exception as e:
                print(f"[WARN]: enforce_driving_side failed for NPCs, using fallback: {e}")
                offset = -0.8  # Conservative fallback

        for i, spawn_point in enumerate(spawn_points[:num_vehicles]):
            vehicle_bp = blueprint_library.filter('vehicle.*')[i % 20]

            if vehicle_bp.has_attribute('driver_id'):
                vehicle_bp.set_attribute('driver_id', '0')

            try:
                vehicle = self.world.spawn_actor(vehicle_bp, spawn_point)

                if vehicle:
                    vehicle.set_autopilot(True, self.traffic_manager.get_port())
                    try:
                        # apply per-NPC lane offset so NPCs follow the same side
                        self.traffic_manager.vehicle_lane_offset(vehicle, float(offset)) 
                    except Exception:
                        pass
                    try:
                        # make NPCs obey traffic lights
                        self.traffic_manager.ignore_lights_percentage(vehicle, 0)
                    except Exception:
                        pass

            except RuntimeError:
                continue
                
        # print("NPC vehicles spawned!")
        
    def get_predefined_route(self):
        """Get predefined waypoints for different route types in self.town
        
        Uses spawn points to generate valid routes for any map instead of hardcoded coordinates.
        """
        map = self.world.get_map()
        spawn_points = map.get_spawn_points()
        
        if not spawn_points or len(spawn_points) == 0:
            print("[ERROR]: No spawn points found on map!")
            return [], 0
        
        # Determine start index (use spawn_idx override if provided)
        start_idx = self.spawn_idx if self.spawn_idx is not None else min(10, len(spawn_points) - 1)
        
        # Generate route by selecting spawn points with spacing
        route_config = {
            'highway': {'description': f'Highway loop in {self.town}', 'spacing': 15, 'count': 8},
            'urban': {'description': f'Urban streets in {self.town}', 'spacing': 8, 'count': 7},
            'simple': {'description': 'Simple straight path', 'spacing': 5, 'count': 4}
        }
        
        config = route_config.get(self.route_type, route_config['simple'])
        print(f"[INFO]: Route: {config['description']}")
        
        # Select spawn points with spacing to create a route
        waypoints = []
        spacing = config['spacing']
        count = config['count']
        
        for i in range(count):
            idx = (start_idx + i * spacing) % len(spawn_points)
            spawn_location = spawn_points[idx].location
            waypoint = map.get_waypoint(spawn_location)
            if waypoint:
                waypoints.append(waypoint)
        
        if not waypoints:
            print(f"[ERROR]: Failed to generate valid route for {self.route_type} in {self.town}")
            print(f"[ERROR]: No waypoints found from {count} spawn points with spacing {spacing}")
            return [], start_idx
        
        print(f"[INFO]: Generated route with {len(waypoints)} waypoints")
        
        # CRITICAL: Correct waypoints for left-hand traffic if enabled
        print(f"[DEBUG] get_predefined_route (mp.py): enforce_left_hand_traffic={getattr(self, 'enforce_left_hand_traffic', 'NOT_SET')}")
        if hasattr(self, 'enforce_left_hand_traffic') and self.enforce_left_hand_traffic:
            print(f"[DEBUG] Calling _verify_and_correct_route_for_left_hand_traffic with {len(waypoints)} waypoints")
            waypoints = self._verify_and_correct_route_for_left_hand_traffic(waypoints)
            print(f"[DEBUG] Route verification completed")
        else:
            print(f"[DEBUG] Skipping route verification")
        
        return waypoints, start_idx
        
    def spawn_player_vehicle(self):
        """Spawn the player-controlled vehicle"""
        blueprint_library = self.world.get_blueprint_library()
        vehicle_bp = blueprint_library.find('vehicle.tesla.model3')
        vehicle_bp.set_attribute('role_name', 'hero')
        
        # Get route and spawn at start
        # Allow optional use of alternate planner when the instance sets
        # `use_predefined_route2 = True` (manual toggle; no CLI flag added).
        if getattr(self, 'use_predefined_route2', False):
            try:
                route_waypoints, start_idx = self.get_predefined_route2()
            except Exception:
                # Fallback to default planner on any error
                route_waypoints, start_idx = self.get_predefined_route()
        else:
            route_waypoints, start_idx = self.get_predefined_route()
        
        spawn_points = self.world.get_map().get_spawn_points()
        spawn_point = spawn_points[start_idx] if start_idx < len(spawn_points) else spawn_points[0]
        
        # Try to spawn with collision retry logic
        max_spawn_attempts = min(50, len(spawn_points))  # Try up to 50 points
        spawn_attempt = 0
        spawned = False
        
        while spawn_attempt < max_spawn_attempts and not spawned:
            try:
                # Try preferred spawn point first, then cycle through all available
                if spawn_attempt == 0:
                    current_spawn = spawn_point
                else:
                    alt_idx = (start_idx + spawn_attempt) % len(spawn_points)
                    current_spawn = spawn_points[alt_idx]
                    
                self.player_vehicle = self.world.spawn_actor(vehicle_bp, current_spawn)
                spawned = True
                if spawn_attempt > 0:
                    print(f"[INFO]: Player spawned at alt index {(start_idx + spawn_attempt) % len(spawn_points)} after {spawn_attempt + 1} attempts")
                else:
                    print(f"[INFO]: Player spawned at requested index {start_idx}")
                break
            except RuntimeError as e:
                if "collision" in str(e).lower():
                    spawn_attempt += 1
                    if spawn_attempt >= max_spawn_attempts:
                        print(f"[ERROR]: All {max_spawn_attempts} spawn points blocked")
                        raise
                else:
                    raise
        
        # Now spawn NPC vehicles AFTER ego is placed (avoids blocking ego spawn)
        try:
            self.spawn_npc_vehicles(num_vehicles=30)
        except Exception as e:
            print(f"[WARN]: NPC spawn issues: {e}")
        
        if self.autopilot:
            # Enable autopilot with Japanese traffic settings
            # Attach cameras first so we can prime sensors before motion
            try:
                self.setup_camera()
            except Exception as e:
                print(f"Failed to setup camera sensor: {e}")

            # Wait until all cameras have produced at least one valid image (priming),
            # Prefer to wait for the first complete 6-camera frame to be written.
            # This ensures we start motion only after a fully populated frame exists on disk.
            priming_start = time.time()
            priming_timeout = getattr(self, '_priming_timeout', 3.0)
            required = max(1, getattr(self, '_required_full_frames', 1))
            got_required = False
            while (time.time() - priming_start) < priming_timeout:
                # If running in synchronous mode, the world needs ticks to deliver sensor callbacks.
                try:
                    settings = self.world.get_settings()
                    if getattr(settings, 'synchronous_mode', False):
                        try:
                            self.world.tick()
                        except Exception:
                            # ignore tick failures here; we'll sleep instead
                            time.sleep(0.02)
                    else:
                        # in async mode, sleep briefly to let callbacks run
                        time.sleep(0.02)
                except Exception:
                    time.sleep(0.02)

                if self._complete_frame_count >= required:
                    got_required = True
                    break

            priming_elapsed = time.time() - priming_start
            if got_required:
                print(f"[INFO]: Observed {required} complete 6-camera frame(s) after {priming_elapsed:.2f}s, enabling autopilot...")
            else:
                # Fallback: if we didn't see a full frame, fall back to per-camera priming flags
                primed_ok = all(self._camera_primed.values())
                if primed_ok:
                    print(f"[INFO]: Per-camera priming satisfied after {priming_elapsed:.2f}s, enabling autopilot...")
                else:
                    print(f"[WARN]: Camera priming incomplete after {priming_elapsed:.2f}s, enabling autopilot anyway")

            # Now enable autopilot/motion
            self.player_vehicle.set_autopilot(True, self.traffic_manager.get_port())
            # CRITICAL: Use computed offset from enforce_driving_side, not hardcoded value
            # This ensures consistent left-hand driving on all maps with varying lane widths
            ego_offset = getattr(self, '_driving_side_offset', -1.5)
            self.traffic_manager.vehicle_lane_offset(self.player_vehicle, ego_offset)
            self.traffic_manager.ignore_lights_percentage(self.player_vehicle, 0)
            print(f"[INFO]: Ego vehicle lane offset applied: {ego_offset:.2f}m (LEFT)")

            # Optional: Set destination for route following
            if route_waypoints:
                self.traffic_manager.set_path(self.player_vehicle, 
                                             [wp.transform.location for wp in route_waypoints])

            # store a lightweight copy of the planned route (list of [x,y]) for later measurement files
            try:
                self._route_points = [[float(wp.transform.location.x), float(wp.transform.location.y)] for wp in route_waypoints]
            except Exception:
                self._route_points = []

            print("[INFO]: Autopilot enabled (Japanese-style left-hand traffic)")
            
            # Check for traffic infrastructure orientation issues
            try:
                infra_check = self.detect_traffic_infrastructure_issues(max_distance=50.0)
                if infra_check['back_facing_lights'] > 0:
                    print(f"[WARN]: Detected {infra_check['back_facing_lights']} back-facing traffic lights within 50m")
                    print("[WARN]: Traffic signs/lights are oriented for RIGHT-hand traffic in CARLA 0.9.15 maps")
                    print("[WARN]: Consider upgrading to CARLA 0.9.16+ for native left-hand traffic support")
                    # Log first few warnings
                    for w in infra_check['warnings'][:3]:
                        print(f"[WARN]:   {w}")
            except Exception as e:
                print(f"[WARN]: Traffic infrastructure check failed: {e}")
        else:
            raise KeyboardInterrupt("[ERROR]: Manual driving not implemented.")

    def _get_forward_speed(self, transform=None, velocity=None):
        """Calculate forward speed by projecting velocity onto forward vector"""
        if not velocity:
            velocity = self.player_vehicle.get_velocity()
        if not transform:
            transform = self.player_vehicle.get_transform()
        
        velocity_np = np.array([velocity.x, velocity.y, velocity.z])
        pitch_rad = np.deg2rad(transform.rotation.pitch)
        yaw_rad = np.deg2rad(transform.rotation.yaw)
        
        orientation_vector = np.array([
            np.cos(pitch_rad) * np.cos(yaw_rad),
            np.cos(pitch_rad) * np.sin(yaw_rad),
            np.sin(pitch_rad)
        ])
        
        return np.dot(velocity_np, orientation_vector)

    def _get_relative_transform(self, ego_matrix, target_matrix):
        """Get relative position of target in ego coordinate frame"""
        ego_inv = np.linalg.inv(ego_matrix)
        rel_matrix = ego_inv @ target_matrix
        return rel_matrix[:3, 3]
    
    def _normalize_angle(self, angle):
        """Normalize angle to [-pi, pi]"""
        while angle > np.pi:
            angle -= 2.0 * np.pi
        while angle < -np.pi:
            angle += 2.0 * np.pi
        return angle
    
    def _get_points_in_bbox(self, vehicle_pos, vehicle_yaw, extent, lidar):
        """Count LiDAR points inside bounding box (matching data_agent.py)"""
        rotation_matrix = np.array([
            [np.cos(vehicle_yaw), -np.sin(vehicle_yaw), 0.0],
            [np.sin(vehicle_yaw), np.cos(vehicle_yaw), 0.0],
            [0.0, 0.0, 1.0]
        ])
        
        vehicle_lidar = (rotation_matrix.T @ (lidar - vehicle_pos).T).T
        
        x, y, z = extent[0], extent[1], extent[2]
        num_points = ((vehicle_lidar[:, 0] < x) & (vehicle_lidar[:, 0] > -x) &
                      (vehicle_lidar[:, 1] < y) & (vehicle_lidar[:, 1] > -y) &
                      (vehicle_lidar[:, 2] < z) & (vehicle_lidar[:, 2] > -z)).sum()
        return num_points

    def get_bounding_boxes(self, lidar=None):
        """Get bounding boxes matching data_agent.py output exactly - for simlingo_v2_2025_01_10 format"""
        results = []
        
        if not self.player_vehicle:
            return results
        
        if self._callback_debug:
            print(f"[DEBUG] get_bounding_boxes: Starting")
            
        ego_transform = self.player_vehicle.get_transform()
        ego_control = self.player_vehicle.get_control()
        ego_velocity = self.player_vehicle.get_velocity()
        ego_matrix = np.array(ego_transform.get_matrix())
        ego_rotation = ego_transform.rotation
        ego_extent = self.player_vehicle.bounding_box.extent
        ego_speed = self._get_forward_speed(transform=ego_transform, velocity=ego_velocity)
        ego_dx = np.array([ego_extent.x, ego_extent.y, ego_extent.z])
        ego_yaw = np.deg2rad(ego_rotation.yaw)
        ego_brake = ego_control.brake
        ego_location = ego_transform.location
        
        carla_map = self.world.get_map()
        ego_wp = carla_map.get_waypoint(ego_location, project_to_road=True, lane_type=carla.libcarla.LaneType.Any)
        
        if not ego_wp:
            return results
        
        # Compute lane direction info for lane_relative_to_ego calculations
        left_wp, right_wp = ego_wp.get_left_lane(), ego_wp.get_right_lane()
        left_decreasing_lane_id = (left_wp is not None and left_wp.lane_id < ego_wp.lane_id) or \
                                   (right_wp is not None and right_wp.lane_id > ego_wp.lane_id)
        
        # Count lanes to remove for opposite direction (with safety limit)
        remove_lanes_for_lane_relative_to_ego = 1
        wp = ego_wp
        is_opposite = False
        max_lane_scan_iterations = 20
        lane_scan_count = 0
        while lane_scan_count < max_lane_scan_iterations:
            if left_wp and not is_opposite:
                wp = left_wp
                left_wp = wp.get_left_lane()
                if left_wp and ((wp.lane_id > 0) != (left_wp.lane_id > 0)):
                    is_opposite = True
                    remove_lanes_for_lane_relative_to_ego += 1
            elif right_wp and not is_opposite:
                wp = right_wp
                right_wp = wp.get_right_lane()
                if right_wp and ((wp.lane_id > 0) != (right_wp.lane_id > 0)):
                    is_opposite = True
                    remove_lanes_for_lane_relative_to_ego += 1
            else:
                break
            lane_scan_count += 1
        
        ego_lane_direction = ego_wp.lane_id / abs(ego_wp.lane_id)
        
        # Build ego_car entry
        relative_yaw = 0.0
        relative_pos = self._get_relative_transform(ego_matrix, ego_matrix)
        
        result = {
            'class': 'ego_car',
            'extent': [ego_dx[0], ego_dx[1], ego_dx[2]],
            'position': [relative_pos[0], relative_pos[1], relative_pos[2]],
            'yaw': relative_yaw,
            'num_points': -1,
            'distance': -1,
            'speed': ego_speed,
            'brake': ego_brake,
            'id': int(self.player_vehicle.id),
            'matrix': ego_transform.get_matrix()
        }
        results.append(result)
        
        # Process vehicles (use cached actor list to avoid slow get_actors() every frame)
        current_frame = self.frame_counter
        if self._actors_cache is None or (current_frame - self._actors_cache_frame) >= self._actors_cache_interval:
            if self._callback_debug:
                print(f"[DEBUG] get_bounding_boxes: Refreshing actor cache (frame {current_frame})")
            self._actors_cache = self.world.get_actors()
            self._actors_cache_frame = current_frame
        
        actors = self._actors_cache
        vehicle_list = actors.filter('*vehicle*')
        
        for vehicle in vehicle_list:
            if vehicle.get_location().distance(self.player_vehicle.get_location()) < 60.0:
                if vehicle.id != self.player_vehicle.id:
                    vehicle_transform = vehicle.get_transform()
                    vehicle_rotation = vehicle_transform.rotation
                    vehicle_matrix = np.array(vehicle_transform.get_matrix())
                    vehicle_control = vehicle.get_control()
                    vehicle_velocity = vehicle.get_velocity()
                    vehicle_extent = vehicle.bounding_box.extent
                    vehicle_id = vehicle.id
                    vehicle_wp = carla_map.get_waypoint(vehicle.get_location(), project_to_road=True, 
                                                        lane_type=carla.libcarla.LaneType.Any)
                    
                    if not vehicle_wp:
                        continue
                    
                    same_road_as_ego = False
                    lane_relative_to_ego = None
                    same_direction_as_ego = False
                    
                    # Check if same road and compute lane offset
                    if vehicle_wp.road_id == ego_wp.road_id:
                        same_road_as_ego = True
                        direction = vehicle_wp.lane_id / abs(vehicle_wp.lane_id)
                        if direction == ego_lane_direction:
                            same_direction_as_ego = True
                        
                        lane_relative_to_ego = vehicle_wp.lane_id - ego_wp.lane_id
                        lane_relative_to_ego *= -1 if left_decreasing_lane_id else 1
                        
                        if not same_direction_as_ego:
                            lane_relative_to_ego += remove_lanes_for_lane_relative_to_ego * \
                                                   (1 if lane_relative_to_ego < 0 else -1)
                        
                        lane_relative_to_ego = -lane_relative_to_ego
                    
                    vehicle_extent_list = [vehicle_extent.x, vehicle_extent.y, vehicle_extent.z]
                    yaw = np.deg2rad(vehicle_rotation.yaw)
                    
                    relative_yaw = self._normalize_angle(yaw - ego_yaw)
                    relative_pos = self._get_relative_transform(ego_matrix, vehicle_matrix)
                    vehicle_speed = self._get_forward_speed(transform=vehicle_transform, velocity=vehicle_velocity)
                    vehicle_brake = vehicle_control.brake
                    vehicle_steer = vehicle_control.steer
                    vehicle_throttle = vehicle_control.throttle
                    
                    if lidar is not None:
                        num_in_bbox_points = self._get_points_in_bbox(relative_pos, relative_yaw, 
                                                                       vehicle_extent_list, lidar)
                    else:
                        num_in_bbox_points = -1
                    
                    distance = np.linalg.norm(relative_pos)
                    
                    # Get color
                    try:
                        from scipy.spatial import KDTree
                        from webcolors import CSS2_HEX_TO_NAMES, hex_to_rgb
                        rgb = tuple(map(int, vehicle.attributes['color'].split(',')))
                        names = []
                        rgb_values = []
                        for color_hex, color_name in CSS2_HEX_TO_NAMES.items():
                            names.append(color_name)
                            rgb_values.append(hex_to_rgb(color_hex))
                        kdt_db = KDTree(rgb_values)
                        distance_color, index = kdt_db.query(rgb)
                        color_name = names[index]
                    except:
                        rgb = None
                        color_name = None
                    
                    # Get traffic light state
                    tl_state_vehicle = 'None'
                    is_at_traffic_light = False
                    try:
                        is_at_traffic_light = vehicle.is_at_traffic_light()
                        tl = self.world.get_traffic_lights_from_waypoint(vehicle_wp, 30.0)
                        if len(tl) > 0:
                            tl_state_vehicle = str(tl[0].state)
                    except:
                        pass
                    
                    # Get light state
                    try:
                        light_state = vehicle.get_light_state()
                        light_state_bin = bin(int(light_state))
                        light_state_bin_pos = [i for i, x in enumerate(reversed(light_state_bin)) if x == '1']
                        light_state_dec_pos = [2**i for i in light_state_bin_pos]
                    except:
                        light_state_dec_pos = []
                    
                    result = {
                        'class': 'car',
                        'color_rgb': rgb,
                        'color_name': color_name,
                        'next_action': None,
                        'vehicle_cuts_in': False,
                        'road_id': vehicle_wp.road_id,
                        'lane_id': vehicle_wp.lane_id,
                        'lane_type': vehicle_wp.lane_type,
                        'lane_type_str': str(vehicle_wp.lane_type),
                        'is_in_junction': vehicle_wp.is_junction,
                        'junction_id': vehicle_wp.junction_id,
                        'distance_to_junction': None,
                        'next_junction_id': -1,
                        'next_road_ids': [],
                        'next_next_road_ids': [],
                        'same_road_as_ego': same_road_as_ego,
                        'same_direction_as_ego': same_direction_as_ego,
                        'lane_relative_to_ego': lane_relative_to_ego,
                        'light_state': light_state_dec_pos,
                        'traffic_light_state': tl_state_vehicle,
                        'is_at_traffic_light': is_at_traffic_light,
                        'base_type': vehicle.attributes.get('base_type', 'car'),
                        'number_of_wheels': vehicle.attributes.get('number_of_wheels', '4'),
                        'extent': vehicle_extent_list,
                        'position': [relative_pos[0], relative_pos[1], relative_pos[2]],
                        'yaw': relative_yaw,
                        'num_points': int(num_in_bbox_points),
                        'distance': distance,
                        'speed': vehicle_speed,
                        'brake': vehicle_brake,
                        'steer': vehicle_steer,
                        'throttle': vehicle_throttle,
                        'id': int(vehicle_id),
                        'role_name': vehicle.attributes.get('role_name', ''),
                        'type_id': vehicle.type_id,
                        'matrix': vehicle_transform.get_matrix()
                    }
                    results.append(result)
            
        # Process walkers
        walkers = actors.filter('*walker*')
        for walker in walkers:
            if walker.get_location().distance(self.player_vehicle.get_location()) < 60.0:
                walker_transform = walker.get_transform()
                walker_velocity = walker.get_velocity()
                walker_rotation = walker_transform.rotation
                walker_matrix = np.array(walker_transform.get_matrix())
                walker_id = walker.id
                walker_extent = walker.bounding_box.extent
                walker_extent_list = [walker_extent.x, walker_extent.y, walker_extent.z]
                yaw = np.deg2rad(walker_rotation.yaw)
                
                relative_yaw = self._normalize_angle(yaw - ego_yaw)
                relative_pos = self._get_relative_transform(ego_matrix, walker_matrix)
                walker_speed = self._get_forward_speed(transform=walker_transform, velocity=walker_velocity)
                
                if lidar is not None:
                    num_in_bbox_points = self._get_points_in_bbox(relative_pos, relative_yaw, 
                                                                   walker_extent_list, lidar)
                else:
                    num_in_bbox_points = -1
                
                distance = np.linalg.norm(relative_pos)
                
                walker_wp = carla_map.get_waypoint(walker.get_location(), project_to_road=True, 
                                                   lane_type=carla.libcarla.LaneType.Any)
                lane_type = walker_wp.lane_type if walker_wp else None
                same_road_as_ego = False
                lane_relative_to_ego = None
                same_direction_as_ego = False
                
                if walker_wp and walker_wp.road_id == ego_wp.road_id:
                    same_road_as_ego = True
                    
                    direction = walker_wp.lane_id / abs(walker_wp.lane_id)
                    if direction == ego_lane_direction:
                        same_direction_as_ego = True
                    
                    lane_relative_to_ego = walker_wp.lane_id - ego_wp.lane_id
                    lane_relative_to_ego *= -1 if left_decreasing_lane_id else 1
                    
                    if not same_direction_as_ego:
                        lane_relative_to_ego += remove_lanes_for_lane_relative_to_ego * \
                                               (1 if lane_relative_to_ego < 0 else -1)
                    
                    lane_relative_to_ego = -lane_relative_to_ego
                
                result = {
                    'class': 'walker',
                    'role_name': walker.attributes.get('role_name', ''),
                    'gender': walker.attributes.get('gender', ''),
                    'age': walker.attributes.get('age', ''),
                    'extent': walker_extent_list,
                    'position': [relative_pos[0], relative_pos[1], relative_pos[2]],
                    'yaw': relative_yaw,
                    'num_points': int(num_in_bbox_points),
                    'distance': distance,
                    'speed': walker_speed,
                    'id': int(walker_id),
                    'lane_type': lane_type,
                    'same_road_as_ego': same_road_as_ego,
                    'same_direction_as_ego': same_direction_as_ego,
                    'lane_relative_to_ego': lane_relative_to_ego,
                    'matrix': walker_transform.get_matrix()
                }
                results.append(result)
        
        # Add traffic lights (matching simlingo format)
        try:
            traffic_lights = actors.filter('*traffic_light*')
            for tl in traffic_lights:
                if tl.get_location().distance(self.player_vehicle.get_location()) < 60.0:
                    tl_transform = tl.get_transform()
                    tl_location = tl_transform.location
                    tl_rotation = tl_transform.rotation
                    tl_extent = tl.trigger_volume.extent
                    
                    # Get relative position
                    tl_matrix = np.array(tl_transform.get_matrix())
                    relative_pos = self._get_relative_transform(ego_matrix, tl_matrix)
                    distance = np.sqrt(relative_pos[0]**2 + relative_pos[1]**2 + relative_pos[2]**2)
                    
                    # Compute relative yaw
                    relative_yaw = (tl_rotation.yaw - ego_rotation.yaw) % 360.0
                    if relative_yaw > 180.0:
                        relative_yaw -= 360.0
                    relative_yaw = np.deg2rad(relative_yaw)
                    
                    # Check if traffic light affects ego
                    tl_wp = carla_map.get_waypoint(tl_location, project_to_road=True, lane_type=carla.libcarla.LaneType.Any)
                    affects_ego = False
                    if tl_wp and ego_wp:
                        # Traffic light affects ego if it's on same road and ahead
                        if tl_wp.road_id == ego_wp.road_id and relative_pos[0] > 0:
                            affects_ego = True
                    
                    tl_result = {
                        'class': 'traffic_light',
                        'extent': [tl_extent.x, tl_extent.y, tl_extent.z],
                        'position': [relative_pos[0], relative_pos[1], relative_pos[2]],
                        'yaw': relative_yaw,
                        'distance': distance,
                        'state': str(tl.state),
                        'id': int(tl.id),
                        'affects_ego': affects_ego,
                        'matrix': tl_transform.get_matrix()
                    }
                    results.append(tl_result)
                    
                    # Also add traffic_light_vqa entry (VQA-specific format)
                    if tl_wp:
                        tl_vqa_result = {
                            'class': 'traffic_light_vqa',
                            'extent': [tl_extent.x, tl_extent.y, tl_extent.z],
                            'position': [relative_pos[0], relative_pos[1], relative_pos[2]],
                            'road_id': tl_wp.road_id,
                            'lane_id': tl_wp.lane_id,
                            'junction_id': tl_wp.junction_id if tl_wp.is_junction else -1,
                            'yaw': relative_yaw,
                            'num_points': 0,
                            'distance': distance,
                            'state_str': str(tl.state),
                            'state': 0 if str(tl.state) == 'Red' else (1 if str(tl.state) == 'Yellow' else (2 if str(tl.state) == 'Green' else 3)),
                            'same_road_as_ego': tl_wp.road_id == ego_wp.road_id,
                            'same_direction_as_ego': (tl_wp.lane_id > 0) == (ego_wp.lane_id > 0) if tl_wp and ego_wp else False,
                            'affects_ego': affects_ego,
                            'lane_relative_to_ego': None  # Would need complex calculation like for vehicles
                        }
                        results.append(tl_vqa_result)
        except Exception as e:
            if self._callback_debug:
                print(f"[DEBUG] get_bounding_boxes: Error collecting traffic lights: {e}")
        
        # Build ego_info matching data_agent.py
        # Get traffic light state
        tl_state = 'None'
        try:
            tl = self.world.get_traffic_lights_from_waypoint(ego_wp, 50.0)
            if len(tl) > 0:
                tl_state = str(tl[0].state)
        except:
            pass
        
        # Compute distance to junction
        if ego_wp.is_junction:
            distance_to_junction_ego = 0.0
        else:
            distance_to_junction_ego = None
            test_wp = ego_wp
            for _ in range(200):
                next_wps = test_wp.next(0.5)
                if not next_wps:
                    break
                test_wp = next_wps[0]
                if test_wp.is_junction:
                    distance_to_junction_ego = ego_location.distance(test_wp.transform.location)
                    break
        
        # Count lanes
        ego_lane_number = 1
        lanes_to_the_left = []
        lanes_to_the_right = []
        num_lanes_same_direction = 1
        num_lanes_opposite_direction = 0
        shoulder_left = False
        shoulder_right = False
        parking_left = False
        parking_right = False
        sidewalk_left = False
        sidewalk_right = False
        bikelane_left = False
        bikelane_right = False
        
        # Scan left lanes (with safety limit to prevent infinite loops on circular topology)
        temp_wp = ego_wp.get_left_lane()
        visited_left = set()
        max_iterations_left = 20
        iteration_count_left = 0
        while temp_wp and temp_wp.lane_id not in visited_left and iteration_count_left < max_iterations_left:
            visited_left.add(temp_wp.lane_id)
            lanes_to_the_left.append(temp_wp)
            if temp_wp.lane_type == carla.LaneType.Driving:
                if (temp_wp.lane_id > 0) == (ego_wp.lane_id > 0):
                    num_lanes_same_direction += 1
                else:
                    num_lanes_opposite_direction += 1
            elif temp_wp.lane_type == carla.LaneType.Shoulder:
                shoulder_left = True
            elif temp_wp.lane_type == carla.LaneType.Parking:
                parking_left = True
            elif temp_wp.lane_type == carla.LaneType.Sidewalk:
                sidewalk_left = True
            elif temp_wp.lane_type == carla.LaneType.Biking:
                bikelane_left = True
            temp_wp = temp_wp.get_left_lane()
            iteration_count_left += 1
        
        # Scan right lanes (with safety limit to prevent infinite loops on circular topology)
        temp_wp = ego_wp.get_right_lane()
        visited_right = set()
        max_iterations_right = 20
        iteration_count_right = 0
        while temp_wp and temp_wp.lane_id not in visited_right and iteration_count_right < max_iterations_right:
            visited_right.add(temp_wp.lane_id)
            lanes_to_the_right.append(temp_wp)
            if temp_wp.lane_type == carla.LaneType.Driving:
                if (temp_wp.lane_id > 0) == (ego_wp.lane_id > 0):
                    num_lanes_same_direction += 1
                else:
                    num_lanes_opposite_direction += 1
            elif temp_wp.lane_type == carla.LaneType.Shoulder:
                shoulder_right = True
            elif temp_wp.lane_type == carla.LaneType.Parking:
                parking_right = True
            elif temp_wp.lane_type == carla.LaneType.Sidewalk:
                sidewalk_right = True
            elif temp_wp.lane_type == carla.LaneType.Biking:
                bikelane_right = True
            temp_wp = temp_wp.get_right_lane()
            iteration_count_right += 1
        
        ego_lane = {
            'type:': str(ego_wp.lane_type),
            'width': ego_wp.lane_width,
        }
        left_lanes = [{'type:': str(wp.lane_type), 'width': wp.lane_width} for wp in lanes_to_the_left]
        right_lanes = [{'type:': str(wp.lane_type), 'width': wp.lane_width} for wp in lanes_to_the_right]
        
        ego_info = {
            'class': 'ego_info',
            'scenario': getattr(self, 'route_type', 'highway'),
            'traffic_light_state': tl_state,
            'distance_to_junction': distance_to_junction_ego,
            'ego_lane_number': ego_lane_number,
            'road_id': ego_wp.road_id,
            'lane_id': ego_wp.lane_id,
            'is_in_junction': ego_wp.is_junction,
            'is_intersection': ego_wp.is_intersection,
            'junction_id': ego_wp.junction_id,
            'next_road_junction': False,
            'next_junction_id': -1,
            'next_road_ids': [],
            'next_next_road_ids_ego': [],
            'ego_lane': ego_lane,
            'left_lanes': left_lanes,
            'right_lanes': right_lanes,
            'num_lanes_same_direction': num_lanes_same_direction,
            'num_lanes_opposite_direction': num_lanes_opposite_direction,
            'lane_change': ego_wp.lane_change,
            'lane_change_str': str(ego_wp.lane_change),
            'lane_type': ego_wp.lane_type,
            'lane_type_str': str(ego_wp.lane_type),
            'left_lane_marking_color': ego_wp.left_lane_marking.color,
            'left_lane_marking_color_str': str(ego_wp.left_lane_marking.color),
            'left_lane_marking_type': ego_wp.left_lane_marking.type,
            'left_lane_marking_type_str': str(ego_wp.left_lane_marking.type),
            'right_lane_marking_color': ego_wp.right_lane_marking.color,
            'right_lane_marking_color_str': str(ego_wp.right_lane_marking.color),
            'right_lane_marking_type': ego_wp.right_lane_marking.type,
            'right_lane_marking_type_str': str(ego_wp.right_lane_marking.type),
            'shoulder_left': shoulder_left,
            'shoulder_right': shoulder_right,
            'parking_left': parking_left,
            'parking_right': parking_right,
            'sidewalk_left': sidewalk_left,
            'sidewalk_right': sidewalk_right,
            'bike_lane_left': bikelane_left,
            'bike_lane_right': bikelane_right,
            'hazard_detected_10': False,
            'affects_ego_10': None,
            'hazard_detected_15': False,
            'affects_ego_15': None,
            'hazard_detected_20': False,
            'affects_ego_20': None,
            'hazard_detected_40': False,
            'affects_ego_40': None,
        }
        results.append(ego_info)
        
        # Add weather information
        weather = self.world.get_weather()
        weather_info = {
            'class': 'weather',
            'cloudiness': weather.cloudiness,
            'dust_storm': weather.dust_storm,
            'fog_density': weather.fog_density,
            'fog_distance': weather.fog_distance,
            'fog_falloff': weather.fog_falloff,
            'mie_scattering_scale': weather.mie_scattering_scale,
            'precipitation': weather.precipitation,
            'precipitation_deposits': weather.precipitation_deposits,
            'rayleigh_scattering_scale': weather.rayleigh_scattering_scale,
            'scattering_intensity': weather.scattering_intensity,
            'sun_altitude_angle': weather.sun_altitude_angle,
            'sun_azimuth_angle': weather.sun_azimuth_angle,
            'wetness': weather.wetness,
            'wind_intensity': weather.wind_intensity,
        }
        results.append(weather_info)
        
        return results

    def record_data(self):
        """Record vehicle data using get_bounding_boxes() for enriched boxes format"""
        if not self.player_vehicle:
            return
            
        transform = self.player_vehicle.get_transform()
        velocity = self.player_vehicle.get_velocity()
        control = self.player_vehicle.get_control()
        
        frame_num = self.frame_counter
        
        # Build measurements JSON (matching simlingo training format)
        speed = float(np.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2))
        
        # Get current waypoint for junction and speed limit info
        try:
            current_wp = self.world.get_map().get_waypoint(transform.location)
            junction = current_wp.is_junction if current_wp else False
            speed_limit = float(current_wp.lane_width * 3.6) if current_wp else 60.0  # km/h
        except Exception:
            junction = False
            speed_limit = 60.0

        # Compute ego transformation matrix (4x4) with proper rotation from CARLA transform
        # Use get_matrix() for full 4x4 transformation matrix
        try:
            ego_matrix = transform.get_matrix()
        except:
            # Fallback to identity with translation if get_matrix() not available
            ego_matrix = [
                [1.0, 0.0, 0.0, float(transform.location.x)],
                [0.0, 1.0, 0.0, float(transform.location.y)],
                [0.0, 0.0, 1.0, float(transform.location.z)],
                [0.0, 0.0, 0.0, 1.0]
            ]

        # Route information: prefer stored planned route if available
        route_original = getattr(self, '_route_points', [])
        route = list(route_original) if route_original else []
        
        # Compute target points from route
        target_point = route[0] if len(route) > 0 else [0.0, 0.0]
        target_point_next = route[1] if len(route) > 1 else target_point
        aim_wp = route[0] if len(route) > 0 else [0.0, 0.0]

        # Simplified command encoding: retain previous defaults if unknown
        command = int(getattr(self, 'last_command', 4)) if hasattr(self, 'last_command') else 4
        next_command = int(getattr(self, 'next_command', command)) if hasattr(self, 'next_command') else command
        
        # Control signals from vehicle
        steer = float(control.steer)
        throttle = float(control.throttle)
        brake = bool(control.brake > 0.0)
        control_brake = bool(control.brake)
        
        # Augmentation fields (no augmentation during data collection)
        angle = 0.0
        augmentation_rotation = 0.0
        augmentation_translation = 0.0
        
        # Speed reduction and route changes (not implemented in autopilot mode)
        changed_route = False
        speed_reduced_by_obj_type = None
        speed_reduced_by_obj_id = None
        speed_reduced_by_obj_distance = None
        
        # Hazard detection (simplified - not implemented in autopilot mode)
        light_hazard = False
        vehicle_hazard = False
        vehicle_affecting_id = None
        walker_hazard = False
        walker_affecting_id = None
        stop_sign_hazard = False
        stop_sign_close = False
        walker_close = False
        walker_close_id = None

        measurements = {
            'pos_global': [float(transform.location.x), float(transform.location.y)],
            'theta': float(np.radians(transform.rotation.yaw)),
            'speed': speed,
            'target_speed': 20.0,  # Default target speed in m/s
            'speed_limit': speed_limit,
            'target_point': target_point,
            'target_point_next': target_point_next,
            'command': int(command),
            'next_command': int(next_command),
            'aim_wp': aim_wp,
            'route': route,
            'route_original': route_original,
            'changed_route': changed_route,
            'speed_reduced_by_obj_type': speed_reduced_by_obj_type,
            'speed_reduced_by_obj_id': speed_reduced_by_obj_id,
            'speed_reduced_by_obj_distance': speed_reduced_by_obj_distance,
            'steer': steer,
            'throttle': throttle,
            'brake': brake,
            'control_brake': control_brake,
            'junction': junction,
            'vehicle_hazard': vehicle_hazard,
            'vehicle_affecting_id': vehicle_affecting_id,
            'light_hazard': light_hazard,
            'walker_hazard': walker_hazard,
            'walker_affecting_id': walker_affecting_id,
            'stop_sign_hazard': stop_sign_hazard,
            'stop_sign_close': stop_sign_close,
            'walker_close': walker_close,
            'walker_close_id': walker_close_id,
            'angle': angle,
            'augmentation_translation': augmentation_translation,
            'augmentation_rotation': augmentation_rotation,
            'ego_matrix': ego_matrix
        }
        
        # Save measurements as gzipped JSON
        measurements_path = os.path.join(self.folderpath, 'measurements', f'{frame_num:04d}.json.gz')
        try:
            with gzip.open(measurements_path, 'wt', encoding='utf-8') as f:
                json.dump(measurements, f, indent=4)
        except Exception as e:
            print(f"Error saving measurements: {e}")
        
        # Track GPS trajectory for plotting
        self._gps_trajectory.append([float(transform.location.x), float(transform.location.y)])
        
        # Use get_bounding_boxes() for enriched dataset format (matching simlingo_v2_2025_01_10)
        boxes_data = self.get_bounding_boxes(lidar=None)
        
        # Save boxes as gzipped JSON (with indentation for readability, matching simlingo format)
        boxes_path = os.path.join(self.folderpath, 'boxes', f'{frame_num:04d}.json.gz')
        try:
            with gzip.open(boxes_path, 'wt', encoding='utf-8') as f:
                json.dump(boxes_data, f, indent=4)
        except Exception as e:
            print(f"[ERROR]: Error saving boxes: {e}")
        
        # Save left-hand traffic signal metadata (NEW)
        try:
            signal_metadata = self.detect_traffic_infrastructure_issues(max_distance=50.0)
            signal_file = os.path.join(self.folderpath, 'left_signal', f'{frame_num:04d}.json.gz')
            signal_data = {
                'frame': frame_num,
                'timestamp': datetime.now().isoformat(),
                'ego_position': [float(transform.location.x), float(transform.location.y), float(transform.location.z)],
                'ego_rotation': [float(transform.rotation.pitch), float(transform.rotation.yaw), float(transform.rotation.roll)],
                'back_facing_count': signal_metadata['back_facing_lights'],
                'signals': signal_metadata['signals']
            }
            with gzip.open(signal_file, 'wt', encoding='utf-8') as f:
                json.dump(signal_data, f, indent=4)
        except Exception as e:
            if self._callback_debug:
                print(f"[WARN] Failed to save signal metadata for frame {frame_num}: {e}")
        
        # Store minimal info for summary
        data_point = {
            'frame': frame_num,
            'timestamp': time.time(),
            'location': [transform.location.x, transform.location.y, transform.location.z],
            'speed': speed * 3.6  # km/h
        }
        self.recording_data.append(data_point)
        # Before incrementing the frame counter, ensure camera images for this frame exist.
        expected_cams = {'F', 'B', 'RF', 'LF', 'RB', 'LB'}
        # Wait briefly for camera callbacks to arrive (they should run on the same world.tick)
        wait_start = time.time()
        timeout = 0.5  # seconds
        while time.time() - wait_start < timeout:
            got = self.frame_camera_counts.get(frame_num, set())
            if expected_cams.issubset(got):
                break
            time.sleep(0.02)

        got = self.frame_camera_counts.get(frame_num, set())
        missing = expected_cams.difference(got)
        if missing:
            frame_folder = f"{frame_num:04d}"
            frame_dir = os.path.join(self.folderpath, 'rgb', frame_folder)
            os.makedirs(frame_dir, exist_ok=True)
            for cam_name in missing:
                path = os.path.join(frame_dir, f"{cam_name}{IMAGE_EXT}")
                try:
                    # create a blank black image matching the camera resolution
                    blank = PILImage.new('RGB', (self.image_size_x, self.image_size_y), (0, 0, 0))
                    try:
                        self._save_image(blank, path)
                    except Exception:
                        blank.save(path)
                except Exception as e:
                    print(f"[ERROR]: Failed to write placeholder for missing camera {cam_name} at frame {frame_num}: {e}")

        # Increment frame counter atomically with buffer lock to avoid races
        with self._buffer_lock:
            self.frame_counter += 1
        
    def save_to_xml(self, filename=None):
        """Save recorded data to XML file"""
        if not self.recording_data:
            print("No data to save!")
            return
        # Ensure base recording dir exists (per-run folder created at init)
        os.makedirs(RECORDING_OUTPUT_DIR, exist_ok=True)

        # Use the run-specific folder created in __init__ (keeps names consistent)
        foldername = getattr(self, 'foldername', f"autopilot_multicamera_japanese_{self.route_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        folderpath = getattr(self, 'folderpath', os.path.join(RECORDING_OUTPUT_DIR, foldername))
        os.makedirs(folderpath, exist_ok=True)
        os.makedirs(os.path.join(folderpath, 'img'), exist_ok=True)
        os.makedirs(os.path.join(folderpath, 'text'), exist_ok=True)

        if filename is None:
            filename = os.path.join(folderpath, foldername + ".xml")
        else:
            # If a relative filename is provided, place it into the run folder
            if not os.path.isabs(filename):
                filename = os.path.join(folderpath, filename)
        
        root = ET.Element('DrivingSession')
        root.set('map', self.town)
        root.set('traffic_style', 'Japanese (Left-hand)')
        root.set('mode', 'Autopilot' if self.autopilot else 'Manual')
        root.set('route_type', self.route_type)
        root.set('total_frames', str(len(self.recording_data)))
        root.set('duration_seconds', str(self.duration))
        root.set('artifact_folder', foldername)
        
        for i, data in enumerate(self.recording_data):
            frame = ET.SubElement(root, 'Frame')
            frame.set('id', str(i))
            frame.set('timestamp', str(data['timestamp']))
            
            location = ET.SubElement(frame, 'Location')
            location.set('x', str(data['location']['x']))
            location.set('y', str(data['location']['y']))
            location.set('z', str(data['location']['z']))
            
            rotation = ET.SubElement(frame, 'Rotation')
            rotation.set('pitch', str(data['rotation']['pitch']))
            rotation.set('yaw', str(data['rotation']['yaw']))
            rotation.set('roll', str(data['rotation']['roll']))
            
            velocity = ET.SubElement(frame, 'Velocity')
            velocity.set('x', str(data['velocity']['x']))
            velocity.set('y', str(data['velocity']['y']))
            velocity.set('z', str(data['velocity']['z']))
            velocity.set('speed_kmh', str(data['velocity']['speed']))
            
            control = ET.SubElement(frame, 'Control')
            control.set('throttle', str(data['control']['throttle']))
            control.set('steer', str(data['control']['steer']))
            control.set('brake', str(data['control']['brake']))
            control.set('hand_brake', str(data['control']['hand_brake']))
            control.set('reverse', str(data['control']['reverse']))
            
            # Collision info
            collision = ET.SubElement(frame, 'Collision')
            coll = data.get('collision', {})
            collision.set('is_colliding', str(coll.get('is_colliding', False)))
            collision.set('note', str(coll.get('note', '')))

            # Waypoint info
            wp = data.get('waypoint')
            if wp:
                waypoint = ET.SubElement(frame, 'Waypoint')
                waypoint.set('x', str(wp.get('x', 0)))
                waypoint.set('y', str(wp.get('y', 0)))
                waypoint.set('z', str(wp.get('z', 0)))
                waypoint.set('lane_id', str(wp.get('lane_id', '')))
                waypoint.set('road_id', str(wp.get('road_id', '')))
                waypoint.set('is_junction', str(wp.get('is_junction', False)))
        
        xml_str = minidom.parseString(ET.tostring(root)).toprettyxml(indent="  ")
        
        with open(filename, 'w') as f:
            f.write(xml_str)
            
        print(f"[INFO]: Data saved to {filename}")
    
    def save_training_format(self):
        """Save records.json.gz and results.json.gz matching training format"""
        if not self.recording_data:
            print("[WARN]: No data to save!")
            return
        
        # Save records.json.gz
        records = {
            'meta_data': {
                'index': self.foldername,
                'town': f'Carla/Maps/{self.town}/{self.town}'
            },
            'states': [],
            'lights': [],
            'route': [],
            'ego_actions': [],
            'adv_actions': []
        }
        
        records_path = os.path.join(self.folderpath, 'records.json.gz')
        try:
            with gzip.open(records_path, 'wt', encoding='utf-8') as f:
                json.dump(records, f)
            print(f"[INFO]: Saved records.json.gz")
        except Exception as e:
            print(f"[ERROR]: Failed to save records.json.gz: {e}")
        
        # Save results.json.gz
        results = {
            'timestamp': self.foldername,
            'index': 0,
            'route_id': f'{self.route_type}_route',
            'status': 'Completed',
            'num_infractions': 0,
            'infractions': {
                'collisions_layout': [],
                'collisions_pedestrian': [],
                'collisions_vehicle': [],
                'red_light': [],
                'stop_infraction': [],
                'outside_route_lanes': [],
                'min_speed_infractions': [],
                'yield_emergency_vehicle_infractions': [],
                'scenario_timeouts': [],
                'route_dev': [],
                'vehicle_blocked': [],
                'route_timeout': []
            },
            'scores': {
                'score_route': 100,
                'score_penalty': 1.0,
                'score_composed': 100.0
            },
            'meta': {
                'route_length': 0.0,  # Would need route calculation
                'duration_game': self.duration,
                'duration_system': self.duration
            }
        }
        
        results_path = os.path.join(self.folderpath, 'results.json.gz')
        try:
            with gzip.open(results_path, 'wt', encoding='utf-8') as f:
                json.dump(results, f, indent=2)
            print(f"[INFO]: Saved results.json.gz")
            print(f"[INFO]: All training-format data saved to {self.folderpath}")
        except Exception as e:
            print(f"[ERROR]: Failed to save results.json.gz: {e}")
        
        # Save GPS trajectory plot
        self._save_gps_plot()
    
    def _save_gps_plot(self, line_width=3, font_size=14, font_size_title=16):
        """Save GPS trajectory plot as GPS.jpg in output folder
        """
        if not self._gps_trajectory or len(self._gps_trajectory) < 2:
            print("[INFO]: Not enough GPS points to plot trajectory")
            return
        
        try:
            import matplotlib
            matplotlib.use('Agg')  # Non-interactive backend for headless mode
            import matplotlib.pyplot as plt
            import matplotlib.patches as mpatches
            import matplotlib.lines as mlines
            
            # Extract X and Y coordinates
            xs = [pt[0] for pt in self._gps_trajectory]
            ys = [pt[1] for pt in self._gps_trajectory]
            
            # Pull plot style values from config if available
            try:
                plot_cfg = cfg or {}
            except Exception:
                plot_cfg = {}

            lw = float(plot_cfg.get('LINE_WIDTH', line_width))
            fs = int(plot_cfg.get('FONT_SIZE', font_size))
            fst = int(plot_cfg.get('FONT_SIZE_TITLE', font_size_title))
            alpha_grid = float(plot_cfg.get('ALPHA_GRID', 0.7))
            alpha_legend = float(plot_cfg.get('ALPHA_LEGEND', 0.3))

            # Create plot
            fig, ax = plt.subplots(figsize=(10, 8))
            ax.plot(xs, ys, linewidth=lw, color='blue', alpha=max(0.05, min(1.0, 1.0 - alpha_legend)))
            ax.set_xlabel('X [m]', fontsize=fs)
            ax.set_ylabel('Y [m]', fontsize=fs)
            ax.set_title('Vehicle GPS Trajectory', fontsize=fst)
            ax.grid(True, alpha=alpha_grid)
            ax.axis('equal')

            # Mark start point with a filled circle
            start_x, start_y = xs[0], ys[0]
            ax.scatter([start_x], [start_y], s=120, c='green', marker='o', zorder=5, edgecolors='black')
            ax.text(start_x, start_y, '  START', fontsize=fs, verticalalignment='center', horizontalalignment='left', color='black')

            # Mark end point with an arrow from penultimate to final point
            end_x, end_y = xs[-1], ys[-1]
            prev_x, prev_y = xs[-2], ys[-2]
            # Draw an arrow indicating direction to the final point
            ax.annotate('', xy=(end_x, end_y), xytext=(prev_x, prev_y), arrowprops=dict(arrowstyle='->', color='red', linewidth=2), zorder=6)
            ax.scatter([end_x], [end_y], s=100, c='red', marker='>', zorder=6)
            ax.text(end_x, end_y, '  END', fontsize=fs, verticalalignment='center', horizontalalignment='left', color='black')

            # Add legend entries for clarity
            start_patch = mpatches.Circle((0, 0), radius=0.1, facecolor='green', edgecolor='black')
            end_line = mlines.Line2D([], [], color='red', marker='>', linestyle='None')
            ax.legend([start_patch, end_line], ['Start', 'End'], loc='best', framealpha=alpha_legend)

            # Save plot
            gps_path = os.path.join(self.folderpath, 'GPS.jpg')
            plt.savefig(gps_path, dpi=150, bbox_inches='tight')
            plt.close(fig)
            print(f"[INFO]: Saved GPS trajectory plot to {gps_path}")
        except Exception as e:
            print(f"[WARNING]: Failed to save GPS plot: {e}")
        
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
                print(f"[WARN]: Could not enable synchronous mode, falling back to async: {e}")

            self.spawn_player_vehicle()
            
            print("\n" + "=" * self.print_length)
            print("[INFO]: AUTOPILOT MODE - Japanese-Style Driving")
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

                # if getattr(self, '_ready_to_record', False):
                #     if frame_count % 3 == 0:
                #         self.record_data()

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
            # estimate expected number of rgb folders from measurements (assuming 6 images per frame)
            est_folders = int(round(total / float(self.num_imgs_per_frame))) if self.num_imgs_per_frame > 0 else 0
            print(f"[INFO]: Total frames recorded: {total}")
            print(f"[INFO]: Estimated rgb folders expected (measurements/{self.num_imgs_per_frame}): {est_folders}")
            # If estimator used earlier produced an unexpected large number, print a warning
            try:
                est_prev = self.estimate_recorded_frames(D=self.duration, fps=self.fps, Tprim=getattr(self, '_priming_timeout', 0.0), Toverhead=(getattr(self, '_buffer_timeout', 0.0) + 0.1), W=getattr(self, '_warmup_frames', 0), Nlost=0)
                if est_prev > total * 5:
                    print(f"[WARN]: Estimator earlier returned a large value ({est_prev}); this may be due to missing/duplicate estimator calls or mis-set defaults.")
            except Exception:
                pass
            print("=" * self.print_length + "\n")
            
            # Save data in training format
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
            
    def cleanup(self):
        """Clean up resources"""
        print("\n[INFO]: Cleaning up...")
        
        # Signal all callbacks to stop
        self._stopping = True
        # Give callbacks time to finish current work
        time.sleep(0.3)
        
        # Destroy sensors first
        for s in list(self.sensors):
            try:
                s.stop()
            except Exception:
                pass
            try:
                s.destroy()
            except Exception:
                pass
        self.sensors = []
        
        # Wait for any remaining callback threads to exit
        time.sleep(0.2)
        
        # Destroy vehicle after sensors are cleaned up
        if self.player_vehicle:
            try:
                self.player_vehicle.destroy()
            except Exception:
                pass
            
        # Wait for writer thread to flush buffer
        try:
            # signal writer thread via stopping flag and join
            if hasattr(self, '_writer_thread') and self._writer_thread.is_alive():
                self._writer_thread.join(timeout=10.0)
        except Exception:
            pass

        print("[INFO]: Done!")

    def _buffer_writer(self):
        """Background thread: flush image buffer to disk when complete or on timeout

        Behavior:
        - Wait for all 6 cameras to be present for a frame, then write files.
        - If only a subset arrives and `self._buffer_timeout` elapsed since first sighting, write whatever valid images exist (to avoid stalls), but prefer complete frames.
        """
        CAMS = {'F', 'B', 'RF', 'LF', 'RB', 'LB'}
        while not getattr(self, '_stopping', False):
            now = time.time()
            to_write = []
            with self._buffer_lock:
                for frame_num, cam_dict in list(self._image_buffer.items()):
                    cams_present = set(cam_dict.keys())
                    if cams_present >= CAMS:
                        # mark that we observed a complete frame and increment counter
                        try:
                            self._complete_frame_event.set()
                            self._complete_frame_count += 1
                        except Exception:
                            pass

                        # If we haven't started recording yet, drop buffered frames to avoid
                        # writing files with simulator frame ids (they'd be large numbers like 19343).
                        if not getattr(self, '_ready_to_record', False) and not getattr(self, '_stopping', False):
                            # just discard this buffered full frame; spawn will be signalled via the event
                            del self._image_buffer[frame_num]
                            self._last_frame_seen_time.pop(frame_num, None)
                        else:
                            to_write.append((frame_num, dict(cam_dict)))
                            del self._image_buffer[frame_num]
                            self._last_frame_seen_time.pop(frame_num, None)
                    else:
                        first_seen = self._last_frame_seen_time.get(frame_num, now)
                        if (now - first_seen) >= self._buffer_timeout:
                            # flush partial frame after timeout, but only if we're recording or stopping
                            if getattr(self, '_ready_to_record', False) or getattr(self, '_stopping', False):
                                to_write.append((frame_num, dict(cam_dict)))
                            # in any case, remove from buffer to avoid indefinite growth
                            del self._image_buffer[frame_num]
                            self._last_frame_seen_time.pop(frame_num, None)
            # perform writes outside lock
            for frame_num, cam_dict in to_write:
                frame_folder = f"{frame_num:04d}"
                frame_dir = os.path.join(self.folderpath, 'rgb', frame_folder)
                os.makedirs(frame_dir, exist_ok=True)
                # log what we are writing
                try:
                    cams_written = list(cam_dict.keys())
                    max_vals = {c: int(arr.max()) for c, arr in cam_dict.items()}
                    self._log_debug(f"writer flush frame={frame_num} cams={cams_written} max_vals={max_vals}")
                except Exception:
                    pass
                for cam_name, arr in cam_dict.items():
                    try:
                        pil_img = PILImage.fromarray(arr)
                        # pil_img.save(os.path.join(frame_dir, f"{cam_name}.png"), 'PNG') # THIS SI THE CLASSIC NO COMPRESSED
                        dst = os.path.join(frame_dir, f"{cam_name}{IMAGE_EXT}")
                        try:
                            self._save_image(pil_img, dst)
                        except Exception:
                            # fallback to plain save with a matching extension
                            try:
                                pil_img.save(dst)
                            except Exception:
                                pil_img.save(os.path.splitext(dst)[0] + '.png')
                    except Exception as e:
                        if not getattr(self, '_stopping', False):
                            print(f"[WARN] Failed to write image for frame {frame_num} cam {cam_name}: {e}")
            # Only sleep if no work was done
            if not to_write:
                time.sleep(0.02)

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
    parser.add_argument('--town', type=str, default='Town13',
                       help='CARLA town/map name (default: Town13)')
    parser.add_argument('--fps', type=float, default=20.0,
                       help='Target frames per second for recording (default: 20 - enforced)')
    parser.add_argument('--weather', type=str, default='SoftRainNight',
                       choices=['ClearNoon', 'CloudyNoon', 'WetNoon', 'WetCloudyNoon',
                                'SoftRainNoon', 'MidRainyNoon', 'HardRainNoon',
                                'ClearSunset', 'CloudySunset', 'WetSunset', 'WetCloudySunset',
                                'SoftRainSunset', 'MidRainSunset', 'HardRainSunset',
                                'ClearNight', 'CloudyNight', 'WetNight', 'WetCloudyNight',
                                'SoftRainNight', 'MidRainyNight', 'HardRainNight', 'DustStorm'],
                       help='Weather preset to use (default: SoftRainNight)') 
    parser.add_argument('--spawn-index', type=int, default=None,
                       help='Spawn point index (0-based, None=use route default)')
    
    args = parser.parse_args()
    
    sim = JapaneseStyleAutopilot(
        autopilot=args.autopilot,
        duration=args.duration,
        route_type=args.route,
        town=args.town,
        fps=args.fps,
        weather=args.weather,
        spawn_idx=args.spawn_index
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
        print(f"[INFO]: Estimated recorded frames: {est}")
    except Exception:
        pass
    sim.run()
    
    # Output dataset path for shell script to capture and pass to post-processing
    # This avoids expensive auto-discovery on external SSD
    print(f"\n__DATASET_PATH__={sim.folderpath}")

if __name__ == '__main__':
    main()