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

RECORDING_OUTPUT_DIR = "/workspace/simlingo/recording_japan_xml"

# # Highway route (default)
# python japanese_driving_autopilot.py --autopilot --route highway
# # Urban streets
# python japanese_driving_autopilot.py --autopilot --route urban
# # Simple straight path
# python japanese_driving_autopilot.py --autopilot --route simple
# python japanese_driving_autopilot.py --autopilot --duration 300 --route highway


class JapaneseStyleAutopilot:
    def __init__(self, autopilot=False, duration=60, route_type='highway', port_localhost=2000, town='Town13'):
        # Connect to CARLA
        self.client = carla.Client('localhost', port_localhost)
        # Allow longer timeouts for slower hosts
        self.client_timout_carla = 30.0
        self.client.set_timeout(self.client_timout_carla)
        self.print_length = 70
        self.sleep_interval = 0.05 # 20 Hz
        self.town = town

        print("[INFO]: Selecting world on server (prefer current world; use --force-load to override)...")

        # If a world is already loaded on the server, prefer using it to avoid heavy reloads
        try:
            current_world = self.client.get_world()
            current_map_name = getattr(current_world.get_map(), 'name', '')
            if current_map_name:
                print(f"[INFO]: Server already has map loaded: {current_map_name} — using it")
                self.world = current_world
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
                        print(f"  Attempt {attempt}/{max_attempts} failed: {e}. Retrying in {wait}s...")
                        time.sleep(wait)

                if not hasattr(self, 'world'):
                    raise RuntimeError(f"Failed to load map '{map_to_load}' after {max_attempts} attempts: {last_exc}")

        time.sleep(1)
        
        # Get traffic manager
        self.traffic_manager = self.client.get_trafficmanager(8000)
        
        # Setup Japanese-style traffic
        self.setup_left_hand_traffic()
        
        # Autopilot settings
        self.autopilot = autopilot
        self.duration = duration  # seconds
        self.route_type = route_type
        
        # Vehicle
        self.player_vehicle = None
        
        # Recording data
        self.recording_data = []
        # Prepare per-run artifact folders matching training format
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.foldername = f"autopilot_multicamera_japanese_{self.route_type}_{timestamp}"
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
            # also print to stdout for live observation
            print(out, end='')
        except Exception:
            pass
        
    def setup_left_hand_traffic(self):
        """Configure traffic manager for left-hand traffic (Japan/UK)"""
        # print("Configuring Japanese-style (left-hand) traffic...")
        
        self.traffic_manager.set_global_distance_to_leading_vehicle(2.5)
        self.traffic_manager.global_lane_offset = -1.5
        
        # Spawn NPC vehicles
        self.spawn_npc_vehicles(num_vehicles=30)

    def setup_camera(self):
        """Attach 6 RGB cameras around the vehicle: Front, Back, RF, LF, RB, LB.
        Save images into per-frame folders: /folderpath/00XX/{F,B,RF,LF,RB,LB}.png
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
                    # Skip if shutting down
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
                print(f"Error in semantic callback: {e}")

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
                'start_idx': 50,
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
                'start_idx': 10,
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
                'start_idx': 0,
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
        
        # Build measurements JSON (matching training format)
        speed = np.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2)
        
        # Get waypoint for route/command info
        try:
            wp = self.world.get_map().get_waypoint(transform.location)
            next_wps = wp.next(10.0)
            target_wp = next_wps[0] if next_wps else wp
            target_loc = target_wp.transform.location
            target_point = [
                target_loc.x - transform.location.x,
                target_loc.y - transform.location.y
            ]
        except Exception:
            target_point = [0.0, 0.0]
        
        measurements = {
            'pos_global': [transform.location.x, transform.location.y],
            'theta': np.radians(transform.rotation.yaw),
            'speed': speed,
            'target_speed': 15.0,  # Placeholder
            'speed_limit': 22.22,  # Placeholder (80 km/h)
            'target_point': target_point,
            'target_point_next': target_point,  # Simplified
            'command': 4,  # LANE_FOLLOW
            'next_command': 4,
            'aim_wp': target_point,
            'route': []  # Simplified - would need route planner
        }
        
        # Save measurements as gzipped JSON
        measurements_path = os.path.join(self.folderpath, 'measurements', f'{frame_num:04d}.json.gz')
        try:
            with gzip.open(measurements_path, 'wt', encoding='utf-8') as f:
                json.dump(measurements, f)
        except Exception as e:
            print(f"Error saving measurements: {e}")
        
        # Build boxes JSON (ego car + weather)
        ego_extent = self.player_vehicle.bounding_box.extent
        weather = self.world.get_weather()
        
        boxes_data = [
            {
                'class': 'ego_car',
                'extent': [ego_extent.x, ego_extent.y, ego_extent.z],
                'position': [0.0, 0.0, 0.0],
                'yaw': 0.0,
                'num_points': -1,
                'distance': -1,
                'speed': speed,
                'brake': control.brake,
                'id': self.player_vehicle.id,
                'matrix': [
                    [1.0, 0.0, 0.0, transform.location.x],
                    [0.0, 1.0, 0.0, transform.location.y],
                    [0.0, 0.0, 1.0, transform.location.z],
                    [0.0, 0.0, 0.0, 1.0]
                ]
            },
            {
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
                'sun_azimuth_angle': weather.sun_azimuth_angle
            }
        ]
        
        # Save boxes as gzipped JSON
        boxes_path = os.path.join(self.folderpath, 'boxes', f'{frame_num:04d}.json.gz')
        try:
            with gzip.open(boxes_path, 'wt', encoding='utf-8') as f:
                json.dump(boxes_data, f)
        except Exception as e:
            print(f"Error saving boxes: {e}")
        
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
                path = os.path.join(frame_dir, f"{cam_name}.png")
                try:
                    # create a blank black image matching the camera resolution
                    blank = PILImage.new('RGB', (self.image_size_x, self.image_size_y), (0, 0, 0))
                    blank.save(path, 'PNG')
                except Exception as e:
                    print(f"[ERROR]: Failed to write placeholder for missing camera {cam_name} at frame {frame_num}: {e}")

        # Increment frame counter
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
                        # Reset frame counter to 0 when recording starts
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

                # Record data at ~20 Hz (chosen from server 60Hz)
                # Only start recording once cameras are ready to avoid creating placeholder images
                if getattr(self, '_ready_to_record', False):
                    if frame_count % 3 == 0:
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
            print(f"[INFO]: Total frames recorded: {len(self.recording_data)}")
            print("=" * self.print_length + "\n")
            
            # Save data in training format
            self.save_training_format()
            
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
                self._writer_thread.join(timeout=2.0)
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
                        pil_img.save(os.path.join(frame_dir, f"{cam_name}.png"), 'PNG')
                    except Exception as e:
                        if not getattr(self, '_stopping', False):
                            print(f"[WARN] Failed to write image for frame {frame_num} cam {cam_name}: {e}")
            time.sleep(0.05)

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
    
    args = parser.parse_args()
    
    sim = JapaneseStyleAutopilot(
        autopilot=args.autopilot,
        duration=args.duration,
        route_type=args.route
    )
    sim.run()

if __name__ == '__main__':
    main()