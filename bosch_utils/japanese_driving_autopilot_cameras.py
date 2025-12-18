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
from bosch_utils.config import cfg, RECORDING_OUTPUT_DIR, IMAGE_FORMAT, IMAGE_EXT, JPG_QUALITY, PNG_COMPRESS_LEVEL


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
    def __init__(self, autopilot=False, duration=60, route_type='highway', port_localhost=2000, port_traffic=8000, town='Town13', fps=20.0, num_imgs_per_frame=6, callback_debug=False, weather='SoftRainNight',spawn_idx=None):
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

        print('[WARNING]: Currently the fps is ~40 fps for each camera. This is half of the speed in which simlingo was running')

        # Connect to CARLA
        self.client = carla.Client('localhost', port_localhost)
        # Allow longer timeouts for slower hosts
        self.client_timout_carla = 30.0
        self.client.set_timeout(self.client_timout_carla)
        self.print_length = 70
        requested_fps = float(fps)
        if requested_fps != 20.0:
            print(f"[INFO]: Overriding requested fps={requested_fps} to enforced 20.0 FPS for consistency")
        self.fps = 20.0
        self.num_imgs_per_frame = num_imgs_per_frame
        self.sleep_interval = 1.0 / self.fps
        # Spawn point override (None = use route default)
        self.spawn_idx = spawn_idx
        # Enable or disable per-callback debug logging (can be noisy at high FPS)
        self._callback_debug = bool(callback_debug)
        self.town = town
        self.port_traffic = port_traffic

        print(f'[INFO]: Recording imgs at {self.fps} FPS with interval {self.sleep_interval:.3f}s')
        print("[INFO]: Selecting world on server (prefer current world; use --force-load to override)...")

        # If a world is already loaded on the server, prefer using it to avoid heavy reloads
        try:
            current_world = self.client.get_world()
            current_map_name = getattr(current_world.get_map(), 'name', '')
            if current_map_name:
                print(f"[INFO]: Server already has map loaded: {current_map_name} — using it")
                self.world = current_world
                # self.world.set_weather(weather) # even the custom one
                time.sleep(1)
                skip_load = True
            else:
                skip_load = False
        except Exception:
            skip_load = False

        # If user explicitly wants to force a map load, set FORCE_LOAD env var or pass --force-load
        FORCE_LOAD = False

        if not skip_load and not FORCE_LOAD:
            try:
                available_maps = self.client.get_available_maps()
            except Exception:
                available_maps = []

            preferred_map = None
            for m in available_maps:
                if self.tow in m:
                    preferred_map = m
                    break

            if preferred_map is not None:
                map_to_load = preferred_map
                print(f"[INFO]: Found server map: {preferred_map} — will attempt to load it")
            elif len(available_maps) > 0:
                map_to_load = available_maps[0]
                print(f"[INFO]: {self.town} not found on server — would load {map_to_load} if needed")
            else:
                map_to_load = self.town
                print(f"[WARNING]: No maps reported by server; would try short name '{self.town}' if forced")

            # We will not call load_world by default to avoid crashes — prefer using current world.
            # If no world was set above, fall back to attempting load with retries.
            if not hasattr(self, 'world'):
                max_attempts = 4
                attempt = 0
                last_exc = None
                while attempt < max_attempts:
                    try:
                        self.world = self.client.load_world(map_to_load)
                        break
                    except Exception as e:
                        last_exc = e
                        attempt += 1
                        wait = 5
                        print(f"[INFO]: Attempt {attempt}/{max_attempts} failed: {e}. Retrying in {wait}s...")
                        time.sleep(wait)

                if not hasattr(self, 'world'):
                    raise RuntimeError(f"[ERROR]: Failed to load map '{map_to_load}' after {max_attempts} attempts: {last_exc}")

        time.sleep(1)
        
        # Get traffic manager
        self.traffic_manager = self.client.get_trafficmanager(self.port_traffic)
        
        # Setup Japanese-style traffic
        self.setup_left_hand_traffic()

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
        
        # Vehicle
        self.player_vehicle = None
        self.recording_data = []
        
        # Prepare per-run artifact folders matching training format

        # timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        # self.foldername = f"autopilot_multicamera_japanese_{self.route_type}_{timestamp}"
        # self.folderpath = os.path.join(RECORDING_OUTPUT_DIR, self.foldername)

        self.foldername = f"database/simlingo_v3_2026_01_01/auto_short_multicam_jp/training_{self.town}_scenario/routes_{self.route_type}_duration_{self.duration}_training/{self.weather}_weather/ego_{self.spawn_idx}"
        self.folderpath = os.path.join(RECORDING_OUTPUT_DIR, self.foldername)

        os.makedirs(self.folderpath, exist_ok=True)
        # Create training-format subfolders
        os.makedirs(os.path.join(self.folderpath, 'rgb'), exist_ok=True)
        os.makedirs(os.path.join(self.folderpath, 'measurements'), exist_ok=True)
        os.makedirs(os.path.join(self.folderpath, 'boxes'), exist_ok=True)
        self.last_image_filename = None
        self.sensors = []
        # Match training data image size: 1024x512
        self.image_size_x = 1024
        self.image_size_y = 512
        self.last_seg_meta = None
        # Frame counter for sequential naming (0000, 0001, ...)
        self.frame_counter = 0
        # Track which cameras have produced images for each frame
        self.frame_camera_counts = {}
        # Shutdown coordination flag
        self._stopping = False
        # Warmup: skip first N frames to let cameras stabilize
        self._warmup_frames = 5
        self._ready_to_record = False
        # Per-camera priming: require each camera to produce a valid image before recording
        self._camera_primed = { 'F': False, 'B': False, 'RF': False, 'LF': False, 'RB': False, 'LB': False }
        # Max time to wait for priming (seconds) before falling back
        self._priming_timeout = 3.0
        # Buffer for images: frame_num -> {camera_name: ndarray}
        self._image_buffer = {}
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
        self.traffic_manager.global_lane_offset = -1.5
        
        # Spawn NPC vehicles
        self.spawn_npc_vehicles(num_vehicles=30)

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
        
        # Semantic segmentation camera (DISABLED for training format compatibility)
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
        
        for i, spawn_point in enumerate(spawn_points[:num_vehicles]):
            vehicle_bp = blueprint_library.filter('vehicle.*')[i % 20]
            
            if vehicle_bp.has_attribute('driver_id'):
                vehicle_bp.set_attribute('driver_id', '0')
            
            try:
                vehicle = self.world.spawn_actor(vehicle_bp, spawn_point)
                
                if vehicle:
                    vehicle.set_autopilot(True, self.traffic_manager.get_port())
                    self.traffic_manager.vehicle_lane_offset(vehicle, -1.5)
                    self.traffic_manager.ignore_lights_percentage(vehicle, 0)
                    
            except RuntimeError as e:
                continue
                
        # print("NPC vehicles spawned!")
        
    def get_predefined_route(self):
        """Get predefined waypoints for different route types in self.town"""
        """[THIS NEEDS TO BE IMPROVED]"""
        map = self.world.get_map()
        spawn_points = map.get_spawn_points()
        
        routes = {
            'highway': {
                'description': f'Highway loop in {self.town}',
                'start_idx': self.spawn_idx if self.spawn_idx is not None else 50,
                'waypoints': [
                    carla.Location(x=-150.0, y=50.0, z=0.5),
                    carla.Location(x=-100.0, y=100.0, z=0.5),
                    carla.Location(x=0.0, y=150.0, z=0.5),
                    carla.Location(x=100.0, y=100.0, z=0.5),
                    carla.Location(x=150.0, y=0.0, z=0.5),
                    carla.Location(x=100.0, y=-100.0, z=0.5),
                    carla.Location(x=0.0, y=-150.0, z=0.5),
                    carla.Location(x=-100.0, y=-100.0, z=0.5),
                ]
            },
            'urban': {
                'description': f'Urban streets in {self.town}',
                'start_idx': self.spawn_idx if self.spawn_idx is not None else 10,
                'waypoints': [
                    carla.Location(x=-50.0, y=20.0, z=0.5),
                    carla.Location(x=-30.0, y=40.0, z=0.5),
                    carla.Location(x=0.0, y=50.0, z=0.5),
                    carla.Location(x=30.0, y=40.0, z=0.5),
                    carla.Location(x=50.0, y=20.0, z=0.5),
                    carla.Location(x=30.0, y=-20.0, z=0.5),
                    carla.Location(x=0.0, y=-30.0, z=0.5),
                ]
            },
            'simple': {
                'description': 'Simple straight path',
                'start_idx': self.spawn_idx if self.spawn_idx is not None else 0,
                'waypoints': [
                    carla.Location(x=0.0, y=0.0, z=0.5),
                    carla.Location(x=50.0, y=0.0, z=0.5),
                    carla.Location(x=100.0, y=0.0, z=0.5),
                    carla.Location(x=150.0, y=0.0, z=0.5),
                ]
            }
        }
        
        route_config = routes.get(self.route_type, routes['simple'])
        print(f"[INFO]: Route: {route_config['description']}")
        
        # Convert locations to waypoints
        waypoints = []
        for location in route_config['waypoints']:
            waypoint = map.get_waypoint(location)
            if waypoint:
                waypoints.append(waypoint)
        
        return waypoints, route_config['start_idx']
        
    def spawn_player_vehicle(self):
        """Spawn the player-controlled vehicle"""
        blueprint_library = self.world.get_blueprint_library()
        vehicle_bp = blueprint_library.find('vehicle.tesla.model3')
        vehicle_bp.set_attribute('role_name', 'hero')
        
        # Get route and spawn at start
        route_waypoints, start_idx = self.get_predefined_route()
        
        spawn_points = self.world.get_map().get_spawn_points()
        spawn_point = spawn_points[start_idx] if start_idx < len(spawn_points) else spawn_points[0]
        
        self.player_vehicle = self.world.spawn_actor(vehicle_bp, spawn_point)
        print(f"[INFO]: Player vehicle spawned at {spawn_point.location}")
        
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
            self.traffic_manager.vehicle_lane_offset(self.player_vehicle, -1.5)
            self.traffic_manager.ignore_lights_percentage(self.player_vehicle, 0)

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
        else:
            raise KeyboardInterrupt("[ERROR]: Manual driving not implemented.")

    def record_data(self):
        """Record vehicle data in training format (measurements + boxes)"""
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
                json.dump(measurements, f)
        except Exception as e:
            print(f"Error saving measurements: {e}")
        
        # Build boxes JSON: collect nearby vehicles and walkers (relative positions to ego)
        boxes_data = []
        try:
            actors = self.world.get_actors()
            # filter vehicles and walkers
            vehicles = actors.filter('vehicle.*')
            walkers = actors.filter('walker.pedestrian.*')
            # ego actor id
            ego_id = self.player_vehicle.id if self.player_vehicle else None

            def actor_to_box(a):
                try:
                    at = a.get_transform()
                    pos = at.location
                    rel_x = float(pos.x - transform.location.x)
                    rel_y = float(pos.y - transform.location.y)
                    rel_z = float(pos.z - transform.location.z)
                    extent = getattr(a, 'bounding_box', None)
                    if extent is not None:
                        ext = [float(extent.extent.x), float(extent.extent.y), float(extent.extent.z)]
                    else:
                        ext = [0.0, 0.0, 0.0]
                    yaw = float(at.rotation.yaw - transform.rotation.yaw)
                    vel = a.get_velocity()
                    speed_a = float(np.sqrt(vel.x**2 + vel.y**2 + vel.z**2))
                    # rough brake detection if actor has control
                    br = False
                    try:
                        ctrl = a.get_control()
                        br = bool(getattr(ctrl, 'brake', False))
                    except Exception:
                        br = False
                    # Compute distance from ego to actor
                    distance = float(np.sqrt(rel_x**2 + rel_y**2 + rel_z**2))
                    # Get actor's transformation matrix
                    try:
                        matrix = at.get_matrix()
                    except:
                        # Fallback: identity matrix with translation
                        matrix = [
                            [1.0, 0.0, 0.0, float(pos.x)],
                            [0.0, 1.0, 0.0, float(pos.y)],
                            [0.0, 0.0, 1.0, float(pos.z)],
                            [0.0, 0.0, 0.0, 1.0]
                        ]
                    cls = 'vehicle' if 'vehicle' in a.type_id else 'walker'
                    return {
                        'brake': br,
                        'class': cls,
                        'distance': distance,
                        'extent': ext,
                        'id': a.id,
                        'matrix': matrix,
                        'num_points': 0,  # LiDAR points (not available in this collector)
                        'position': [rel_x, rel_y, rel_z],
                        'speed': speed_a,
                        'yaw': yaw
                    }
                except Exception:
                    return None

            for v in vehicles:
                if v.id == ego_id:
                    continue
                b = actor_to_box(v)
                if b:
                    boxes_data.append(b)

            for w in walkers:
                b = actor_to_box(w)
                if b:
                    boxes_data.append(b)
        except Exception:
            boxes_data = []
        
        # Save boxes as gzipped JSON
        boxes_path = os.path.join(self.folderpath, 'boxes', f'{frame_num:04d}.json.gz')
        try:
            with gzip.open(boxes_path, 'wt', encoding='utf-8') as f:
                json.dump(boxes_data, f)
        except Exception as e:
            print(f"[ERROR]: Error saving boxes: {e}")
        
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
                est_prev = sim.estimate_recorded_frames(D=self.duration, fps=self.fps, Tprim=getattr(self, '_priming_timeout', 0.0), Toverhead=(getattr(self, '_buffer_timeout', 0.0) + 0.1), W=getattr(self, '_warmup_frames', 0), Nlost=0)
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

if __name__ == '__main__':
    main()