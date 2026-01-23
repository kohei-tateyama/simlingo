"""
Data collection agent for right-hand traffic with 6-camera setup.

Combines:
- DataAgent's leaderboard21 integration and sensor pipeline
- 6-camera multi-view recording (F, B, RF, LF, RB, LB)
- Output structure: database/simlingo_v2_2025_01_10/data/simlingo/{scenario}/{route_config}/{route_id}/
"""
# TODO clean 

import os
import sys
import json
import gzip
import time
import math
import threading
import signal
from pathlib import Path
from datetime import datetime
import shutil

import cv2
import carla
import numpy as np
import laspy
import torch

from PIL import Image as PILImage
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.lines as mlines

from shapely.geometry import Polygon

from autopilot_0916 import AutoPilot
import team_code.transfuser_utils as t_u

from birds_eye_view.chauffeurnet import ObsManager
from birds_eye_view.run_stop_sign import RunStopSign

from agents.tools.misc import (is_within_distance, get_trafficlight_trigger_location, compute_distance)
from agents.navigation.local_planner import LocalPlanner

# Color name conversion for vehicle colors
from scipy.spatial import KDTree
from webcolors import CSS2_HEX_TO_NAMES, hex_to_rgb

def convert_rgb_to_names(rgb_tuple):
    css3_db = CSS2_HEX_TO_NAMES
    names = []
    rgb_values = []
    for color_hex, color_name in css3_db.items():
        names.append(color_name)
        rgb_values.append(hex_to_rgb(color_hex))
    
    kdt_db = KDTree(rgb_values)
    distance, index = kdt_db.query(rgb_tuple)
    return f'{names[index]}'


def get_entry_point():
    return 'DataAgentMulticamera'


# --- LHT CRASH FIX START --- added carela 0.9.16

sr_base = "/workspace/simlingo/scenario_runner21/srunner"

if sr_base not in sys.path:
    sys.path.insert(0, sr_base)

try:
    # 2. Use the exact folder name found: 'scenarioatomics' (no underscore)
    import scenariomanager.scenarioatomics.atomic_criteria as criteria
    
    # Define the safe setup to prevent the LHT IndexError
    def patched_setup(self, actor, debug=False):
        self._actor = actor
        self._world = actor.get_world()
        self._map = self._world.get_map()
        # Setting this to None prevents: traffic_light = traffic_light_list[0] -> IndexError
        self._traffic_light = None 

    # Apply the patch to the class
    criteria.RunningRedLightTest.setup = patched_setup
    print("[INFO]: LHT patch ok via scenarioatomics")

except ImportError as e:
    print(f"[ERROR]: Still could not find ScenarioRunner. Error: {e}")

# --- LHT CRASH FIX END ---


class DataAgentMulticamera(AutoPilot):
    """
    Right-hand traffic data collection agent with multi-camera setup.
    
    Features:
    - Right-hand traffic configuration (default for CARLA maps)
    - 6 RGB cameras: Front, Back, Right-Front, Left-Front, Right-Back, Left-Back
    - Per-frame synchronized camera capture with buffer management
    - GPS trajectory recording and plotting
    - Enriched bounding boxes with lane-relative information
    - Output compatible with simlingo_v2_2025_01_10 format
    """

    def __init__(self, carla_host='localhost', carla_port=2000, debug=False):
        """
        Initialize agent for leaderboard21 compatibility.
        
        The leaderboard21 calls __init__(host, port, debug), but AutoPilot
        uses setup(path_to_conf_file, route_index, traffic_manager).
        This __init__ stores the args but defers actual initialization to setup().
        """
        # Store for potential future use, but AutoPilot doesn't use these
        self._carla_host = carla_host
        try:
            self._carla_port = int(os.environ.get('CARLA_PORT', carla_port))
        except Exception:
            self._carla_port = carla_port
        self._debug = debug
        
        # Initialize sensor_interface required by standard leaderboard21
        from leaderboard21.envs.sensor_interface import SensorInterface
        self.sensor_interface = SensorInterface()
        
        # Initialize global plan attributes (required by leaderboard21)
        self._global_plan = None
        self._global_plan_world_coord = None
        self.wallclock_t0 = None
        # Ensure save_path exists even if setup fails early
        self.save_path = None
        
        # Records for records.json.gz (per-frame data)
        self._frame_records = []
        
        # Setup signal handler for graceful shutdown on timeout
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    
    
    
    def setup(self, path_to_conf_file, route_index=None, traffic_manager=None):
        """
        Precise setup for CARLA 0.9.16 with Auto-LHT support.
        Fixes the 'object has no attribute client' error.
        """
        import os
        import time
        import shutil
        import carla
        from pathlib import Path
        from datetime import datetime

        # --- 1. PRE-INITIALIZATION (Naming & Routes) ---
        try:
            self.scenario_name = Path(path_to_conf_file).parent.name if path_to_conf_file else 'Scenario'
        except Exception:
            self.scenario_name = 'Scenario'

        if route_index is None:
            curr_route_idx = getattr(self, '_route_counter', 0)
            timestamp = time.strftime("%m_%d_%H_%M_%S")
            route_id = f"{curr_route_idx}_route0_{timestamp}"
        else:
            route_id = route_index
            curr_route_idx = route_index

        self.route_id = route_id
        self._original_route_index = curr_route_idx

        # --- 2. LHT/RHT SMART DETECTION ---
        # We use a local client here because super().setup() hasn't created self.client yet
        try:
            _host = os.environ.get('CARLA_HOST', 'localhost')
            _port = int(os.environ.get('CARLA_PORT', 2000))
            _tm_port = int(os.environ.get('TRAFFIC_MANAGER_PORT', 8000))
            
            check_client = carla.Client(_host, _port)
            check_client.set_timeout(10.0)
            check_world = check_client.get_world()
            check_map = check_world.get_map()
            tm = check_client.get_trafficmanager(_tm_port)

            # Check Side
            is_lht = False
            if hasattr(check_map, 'get_driving_side'):
                is_lht = (check_map.get_driving_side() == carla.DrivingSide.Left)
            elif 'driving_side="left"' in check_map.to_opendrive().lower():
                is_lht = True

            print(f"\033[94m[DEBUG] Map: {check_map.name} | Detected LHT: {is_lht}\033[0m")

            if is_lht:
                print("\033[92m[INFO] Setting up Left-Hand Traffic offsets...\033[0m")
                if hasattr(tm, 'set_global_lane_direction_if_lht'):
                    tm.set_global_lane_offset(-0.5)
                    tm.set_global_lane_direction_if_lht(True)
                elif hasattr(tm, 'global_lane_offset'):
                    tm.global_lane_offset(-0.5)
            else:
                print("\033[93m[INFO] Standard Right-Hand Traffic detected. Resetting offset.\033[0m")
                if hasattr(tm, 'global_lane_offset'):
                    tm.global_lane_offset(0.0)

        except Exception as e:
            print(f"\033[91m[ERROR] LHT Hook Failed: {e}\033[0m")

        # --- 3. LEADERBOARD CORE SETUP ---
        # Now we call the parent setup
        super().setup(path_to_conf_file, route_id, traffic_manager=traffic_manager)

        # --- 4. SIMLINGO V4 FOLDER STRUCTURE ---
        # (This part of your code remains the same as your previous version)
        if os.environ.get("SAVE_PATH", None) is not None:
            base_path = Path(os.environ["SAVE_PATH"])
            save_subdir = os.environ.get('SAVE_SUBDIR', None)
            town = os.environ.get('FORCE_TOWN', '') or os.environ.get("TOWN", "Town03")
            rep = os.environ.get("REPETITION", "0")
            weather_config = os.environ.get("WEATHER_CONFIG", "test_clear_noon")
            timestamp = datetime.now().strftime('%m_%d_%H_%M_%S')

            # Build Folder Name
            route_token = str(route_index) if route_index is not None else "0"
            town_folder = f"{town}_Rep{rep}_route{route_token}_{timestamp}"

            if save_subdir:
                self.save_path = base_path / Path(save_subdir) / weather_config / town_folder
            else:
                consolidated_root = base_path / 'training_3_scenarios' / 'routes_devtest' / weather_config
                consolidated_root.mkdir(parents=True, exist_ok=True)
                self.save_path = consolidated_root / town_folder

            self.save_path.mkdir(parents=True, exist_ok=True)
            if self.datagen:
                (self.save_path / "measurements").mkdir(exist_ok=True)
        
        from leaderboard21.autoagents.autonomous_agent import Track
        self.track = Track.SENSORS
        self.step_tmp = 0
        self.cutin_vehicle_starting_position = None

        
        
        
        
        
        
        
        
        
        
        
        
        
        
        # Multi-camera frame management
        self.frame_counter = 0
        self._image_buffer = {}  # frame_num -> {camera_name: ndarray}
        self._buffer_lock = threading.Lock()
        self._frame_camera_counts = {}  # frame_num -> set of camera names seen
        self._stopping = False
        
        # GPS trajectory tracking
        self._gps_trajectory = []
        
        # Cache for actor list to avoid expensive get_actors() calls
        self._actors_cache = None
        self._actors_cache_frame = -999
        self._actors_cache_interval = 10  # Update every N frames
        
        # Print output path and verify it's safe
        if self.save_path is not None:
            print("=" * 80)
            print("[INFO][DATA_AGENT_MULTICAMERAE] Output Configuration:")
            print(f"[INFO] Save Path: {self.save_path}")
            if 'training_3_scenarios' in str(self.save_path):
                print("[INFO] Using consolidated default: training_3_scenarios/routes_devtest (override with SAVE_SUBDIR)")
            print(f"[INFO] Data Collection (DATAGEN): {self.datagen}")
            print(f"[INFO] Route Index              : {route_index}")
            print(f"[INFO] Scenario                 : {self.scenario_name}")
            
            # Check if path already has data to avoid overwriting
            if self.datagen and self.save_path.exists():
                existing_files = []
                for subdir in ['rgb', 'boxes', 'measurements', 'lidar']:
                    subpath = self.save_path / subdir
                    if subpath.exists():
                        file_count = len(list(subpath.glob('*')))
                        if file_count > 0:
                            existing_files.append(f"{subdir}/: {file_count} items")
                
                if existing_files:
                    print("[WARNING] Directory already contains data:")
                    for item in existing_files:
                        print(f"    - {item}")
                    print("[WARNING] New data will be added/overwritten in this directory!")
                else:
                    print("[INFO][OK] Directory exists but is empty - safe to proceed")
            
            print("=" * 80)
        
        # Setup output directory structure matching simlingo_v2 format
        if self.save_path is not None and self.datagen:
            # Create multi-camera directories instead of single rgb/
            (self.save_path / 'rgb').mkdir(exist_ok=True)  # Will contain subdirs: 0000/, 0001/, ...
            (self.save_path / 'boxes').mkdir(exist_ok=True)
            (self.save_path / 'measurements').mkdir(exist_ok=True)
            (self.save_path / 'lidar').mkdir(exist_ok=True)
            (self.save_path / 'left_signal').mkdir(exist_ok=True)
            
            if self.SAVE_TF_LABELS:
                (self.save_path / 'semantics').mkdir(exist_ok=True)
                (self.save_path / 'depth').mkdir(exist_ok=True)
                (self.save_path / 'bev_semantics').mkdir(exist_ok=True)

            print(f"[INFO][DATA_AGENT_MULTICAMERA] Created output directories in: {self.save_path}")
            # write sentinel so runners can find this exact run directory
            try:
                base_path = Path(os.environ.get('SAVE_PATH', '.'))
                last_run_file = base_path / '.last_run'
                with open(last_run_file, 'w') as fh:
                    fh.write(str(self.save_path))
            except Exception:
                pass

        self.tmp_visu = int(os.environ.get('TMP_VISU', 0))

        self._active_traffic_light = None
        self.last_lidar = None
        self.last_ego_transform = None
        
        # Image size for cameras (matching training format, not always)
        self.camera_width = 1024
        self.camera_height = 512

    def _init(self, hd_map):
        super()._init(hd_map)
        
        # Initialize observation managers and criteria
        obs_config = {
            'width_in_pixels': self.config.lidar_resolution_width,
            'pixels_ev_to_bottom': self.config.lidar_resolution_height / 2.0,
            'pixels_per_meter': self.config.pixels_per_meter_collection,
            'history_idx': [-1],
            'scale_bbox': True,
            'scale_mask_col': 1.0,
            'map_folder': 'maps_2ppm_cv'
        }

        self.stop_sign_criteria = RunStopSign(self._world)
        self.ss_bev_manager = ObsManager(obs_config, self.config)
        self.ss_bev_manager.attach_ego_vehicle(self._vehicle, criteria_stop=self.stop_sign_criteria)

        self._local_planner = LocalPlanner(self._vehicle, opt_dict={}, map_inst=self.world_map)


    def sensors(self):
        """
        Define sensor suite: 6 RGB cameras positioned around vehicle for 360° coverage.
        
        Camera layout (top view):
                    LF ---- F ---- RF
                    |              |
                  (ego vehicle)
                    |              |
                    LB ---- B ---- RB
        """
        result = super().sensors()
        
        # CRITICAL: Remove opendrive_map sensor since we're using Track.SENSORS
        # (opendrive_map is only allowed in Track.MAP)
        result = [s for s in result if s.get('type') != 'sensor.opendrive_map']

        if self.save_path is not None and (self.datagen or self.tmp_visu):
            # Remove default single RGB camera from parent class if present
            result = [s for s in result if s.get('id') not in ['rgb', 'rgb_augmented']]
            
            # Camera baseline parameters
            cam_height = 1.5  # meters above vehicle center
            fov = '110'
            
            # Define 6-camera configuration matching japanese_driving_autopilot_cameras_mp.py
            camera_configs = [
                {'name': 'F', 'x': 2.5, 'y': 0.0, 'yaw': 0.0},      # Front center
                {'name': 'B', 'x': -2.5, 'y': 0.0, 'yaw': 180.0},   # Back center
                {'name': 'RF', 'x': 1.0, 'y': 1.0, 'yaw': 55.0},    # Right-Front diagonal
                {'name': 'LF', 'x': 1.0, 'y': -1.0, 'yaw': -55.0},  # Left-Front diagonal
                {'name': 'RB', 'x': -1.0, 'y': 1.0, 'yaw': 125.0},  # Right-Back diagonal
                {'name': 'LB', 'x': -1.0, 'y': -1.0, 'yaw': -125.0} # Left-Back diagonal
            ]
            
            for cam in camera_configs:
                result.append({
                    'type': 'sensor.camera.rgb',
                    'x': cam['x'],
                    'y': cam['y'],
                    'z': cam_height,
                    'roll': 0.0,
                    'pitch': 0.0,
                    'yaw': cam['yaw'],
                    'width': self.camera_width,
                    'height': self.camera_height,
                    'fov': fov,
                    'id': f'rgb_{cam["name"]}'  # e.g., 'rgb_F', 'rgb_B', etc.
                })
            
            if self.SAVE_TF_LABELS:
                # Semantic segmentation for front camera only (to save resources)
                result.append({
                    'type': 'sensor.camera.semantic_segmentation',
                    'x': 2.5,
                    'y': 0.0,
                    'z': cam_height,
                    'roll': 0.0,
                    'pitch': 0.0,
                    'yaw': 0.0,
                    'width': self.camera_width,
                    'height': self.camera_height,
                    'fov': fov,
                    'id': 'semantics'
                })
                
                result.append({
                    'type': 'sensor.camera.depth',
                    'x': 2.5,
                    'y': 0.0,
                    'z': cam_height,
                    'roll': 0.0,
                    'pitch': 0.0,
                    'yaw': 0.0,
                    'width': self.camera_width,
                    'height': self.camera_height,
                    'fov': fov,
                    'id': 'depth'
                })

        # LiDAR sensor
        result.append({
            'type': 'sensor.lidar.ray_cast',
            'x': self.config.lidar_pos[0],
            'y': self.config.lidar_pos[1],
            'z': self.config.lidar_pos[2],
            'roll': self.config.lidar_rot[0],
            'pitch': self.config.lidar_rot[1],
            'yaw': self.config.lidar_rot[2],
            'rotation_frequency': self.config.lidar_rotation_frequency,
            'points_per_second': self.config.lidar_points_per_second,
            'id': 'lidar'
        })

        return result

    def tick(self, input_data):
        """
        Process sensor data for current frame.
        
        Collects:
        - 6 RGB camera images (F, B, RF, LF, RB, LB)
        - LiDAR point cloud (combined 2 half-sweeps for 360°)
        - Enriched bounding boxes with lane-relative info
        - Optional: semantic segmentation, depth, BEV
        """
        result = {}
        
        # Collect multi-camera images
        rgb_images = {}
        camera_names = ['F', 'B', 'RF', 'LF', 'RB', 'LB']
        
        if self.save_path is not None and (self.datagen or self.tmp_visu):
            for cam_name in camera_names:
                sensor_id = f'rgb_{cam_name}'
                if sensor_id in input_data:
                    rgb_images[cam_name] = input_data[sensor_id][1][:, :, :3]
            
            if self.SAVE_TF_LABELS:
                depth = input_data.get('depth', [None, None])[1]
                if depth is not None:
                    depth = (t_u.convert_depth(depth[:, :, :3]) * 255.0 + 0.5).astype(np.uint8)
                
                semantics = input_data.get('semantics', [None, None])[1]
                if semantics is not None:
                    semantics = semantics[:, :, 2]

        # Combine LiDAR half-sweeps into full 360° sweep (10Hz LiDAR at 20Hz tick rate)
        if self.last_lidar is not None:
            ego_transform = self._vehicle.get_transform()
            ego_location = ego_transform.location
            last_ego_location = self.last_ego_transform.location
            relative_translation = np.array([
                ego_location.x - last_ego_location.x,
                ego_location.y - last_ego_location.y,
                ego_location.z - last_ego_location.z
            ])

            ego_yaw = ego_transform.rotation.yaw
            last_ego_yaw = self.last_ego_transform.rotation.yaw
            relative_rotation = np.deg2rad(t_u.normalize_angle_degree(ego_yaw - last_ego_yaw))

            orientation_target = np.deg2rad(ego_yaw)
            rotation_matrix = np.array([
                [np.cos(orientation_target), -np.sin(orientation_target), 0.0],
                [np.sin(orientation_target), np.cos(orientation_target), 0.0],
                [0.0, 0.0, 1.0]
            ])
            relative_translation = rotation_matrix.T @ relative_translation

            lidar_last = t_u.algin_lidar(self.last_lidar, relative_translation, relative_rotation)
            lidar_360 = np.concatenate((input_data['lidar'], lidar_last), axis=0)
        else:
            lidar_360 = input_data['lidar']  # First frame only has 1 half

        # Get enriched bounding boxes (vehicles, walkers, traffic lights, stop signs, landmarks, weather)
        bounding_boxes = self.get_bounding_boxes(lidar=lidar_360)

        self.stop_sign_criteria.tick(self._vehicle)

        if self.SAVE_TF_LABELS:
            bev_semantics = self.ss_bev_manager.get_observation(self.close_traffic_lights)
            if self.tmp_visu and 'F' in rgb_images:
                self.visualuize(bev_semantics['rendered'], rgb_images['F'])

        result.update({
            'lidar': lidar_360,
            'rgb_images': rgb_images,  # Dict of {camera_name: image}
            'bounding_boxes': bounding_boxes,
        })
        
        if self.SAVE_TF_LABELS:
            result.update({
                'semantics': semantics if 'semantics' in locals() else None,
                'depth': depth if 'depth' in locals() else None,
                'bev_semantics': bev_semantics['bev_semantic_classes'] if 'bev_semantics' in locals() else None,
            })

        return result

    def _manage_route_obstacle_scenarios(self, target_speed, ego_speed, route_wp, vehicles, route_np):
        """
        Override parent method to handle missing active_scenarios attribute.
        
        Standard leaderboard21 doesn't have CarlaDataProvider.active_scenarios,
        so we skip scenario-specific obstacle management and use basic control.
        """
        # Return defaults: no speed reduction, no keep_driving, no obstacle info
        return target_speed, False, [target_speed, None, None, None]

    def _get_forward_speed(self, transform=None, velocity=None):
        """
        Calculate the forward speed of the vehicle based on its transform and velocity.
        
        Args:
            transform (carla.Transform, optional): The transform of the vehicle.
            velocity (carla.Vector3D, optional): The velocity of the vehicle.
        
        Returns:
            float: The forward speed of the vehicle in m/s.
        """
        if not velocity:
            velocity = self._vehicle.get_velocity()

        if not transform:
            transform = self._vehicle.get_transform()

        # Convert the velocity vector to a NumPy array
        velocity_np = np.array([velocity.x, velocity.y, velocity.z])

        # Convert rotation angles from degrees to radians
        pitch_rad = np.deg2rad(transform.rotation.pitch)
        yaw_rad = np.deg2rad(transform.rotation.yaw)

        # Calculate the orientation vector based on pitch and yaw angles
        orientation_vector = np.array([
            np.cos(pitch_rad) * np.cos(yaw_rad),
            np.cos(pitch_rad) * np.sin(yaw_rad),
            np.sin(pitch_rad)
        ])

        # Calculate the forward speed by taking the dot product of velocity and orientation vectors
        forward_speed = np.dot(velocity_np, orientation_vector)

        return forward_speed

    @torch.inference_mode()
    def run_step(self, input_data, timestamp, sensors=None, plant=False):
        """Main run loop called by leaderboard21 at each tick."""
        self.step_tmp += 1

        # Convert LiDAR into ego coordinate frame
        input_data['lidar'] = t_u.lidar_to_ego_coordinate(self.config, input_data['lidar'])

        # Parent class runs control logic
        control = super().run_step(input_data, timestamp, plant=plant)

        # Collect sensor data for this frame
        tick_data = self.tick(input_data)

        # Save data at specified frequency
        if self.step % self.config.data_save_freq == 0:
            if self.save_path is not None and self.datagen:
                self.save_sensors(tick_data)
                # Record frame data for records.json.gz
                self._record_frame_data(tick_data)

        self.last_lidar = input_data['lidar']
        self.last_ego_transform = self._vehicle.get_transform()

        if plant:
            return {**tick_data, **control}
        else:
            return control

    def _record_frame_data(self, tick_data):
        """
        Record per-frame data for records.json.gz generation.
        Called after each save_sensors().
        """
        try:
            # Calculate frame number consistently with save_sensors()
            frame = self.step // self.config.data_save_freq
            
            # Calculate elapsed time safely
            if self.wallclock_t0 is not None:
                # wallclock_t0 is a datetime object, convert to timestamp
                if isinstance(self.wallclock_t0, datetime):
                    wallclock_start = self.wallclock_t0.timestamp()
                else:
                    wallclock_start = float(self.wallclock_t0)
                elapsed_time = time.time() - wallclock_start
            else:
                elapsed_time = 0.0
            
            frame_record = {
                'timestamp': elapsed_time,
                'frame': frame,
                'command': tick_data.get('command', 4),
                'speed': tick_data.get('speed', 0.0),
                'position': tick_data.get('pos_global', [0.0, 0.0]),
                'theta': tick_data.get('theta', 0.0),
                'steer': tick_data.get('steer', 0.0),
                'throttle': tick_data.get('throttle', 0.0),
                'brake': tick_data.get('brake', 0.0),
                # Paths relative to save_path (use frame number, not step)
                'rgb_front': f'rgb/{frame:04d}/F.jpg',
                'rgb_back': f'rgb/{frame:04d}/B.jpg',
                'rgb_right_front': f'rgb/{frame:04d}/RF.jpg',
                'rgb_left_front': f'rgb/{frame:04d}/LF.jpg',
                'rgb_right_back': f'rgb/{frame:04d}/RB.jpg',
                'rgb_left_back': f'rgb/{frame:04d}/LB.jpg',
                'lidar': f'lidar/{frame:04d}.laz',
                'measurements': f'measurements/{frame:04d}.json.gz',
                'boxes': f'boxes/{frame:04d}.json.gz'
            }
            self._frame_records.append(frame_record)
        except Exception as e:
            print(f"Warning: Failed to record frame data: {e}")
    
    def save_sensors(self, tick_data):
        """
        Save multi-camera images, LiDAR, boxes, and measurements to disk.
        
        Output structure (per frame):
        - rgb/{frame:04d}/F.jpg, B.jpg, RF.jpg, LF.jpg, RB.jpg, LB.jpg
        - measurements/{frame:04d}.json.gz
        - boxes/{frame:04d}.json.gz
        - lidar/{frame:04d}.laz
        """
        # Avoid saving before the vehicle is initialized (prevents crashes
        # when leaderboard/evaluator calls run_step very early).
        if not hasattr(self, '_vehicle') or self._vehicle is None:
            print('[WARN][DATA_AGENT_MULTICAMERA] _vehicle not initialized — skipping save_sensors')
            return

        frame = self.step // self.config.data_save_freq

        # Log first frame save to confirm output location
        if frame == 0:
            print(f"[DATA_AGENT_MULTICAMERA] Starting to save {self.save_path / 'rgb' / f'{frame:04d}'}/")

        # Create per-frame RGB directory
        rgb_frame_dir = self.save_path / 'rgb' / f'{frame:04d}'
        rgb_frame_dir.mkdir(parents=True, exist_ok=True)

        # Save 6 camera images (wrap each write to avoid crashing on bad frames)
        for cam_name, img in dict(tick_data.get('rgb_images', {})).items():
            try:
                if img is None:
                    print(f"[WARN][DATA_AGENT_MULTICAMERA] Missing image for camera {cam_name} frame {frame}")
                    continue
                # Some sensors may return non-array placeholders
                if not hasattr(img, 'shape'):
                    print(f"[WARN][DATA_AGENT_MULTICAMERA] Invalid image for camera {cam_name} frame {frame}")
                    continue
                img_path = rgb_frame_dir / f'{cam_name}.jpg'
                ok = cv2.imwrite(str(img_path), img)
                if not ok:
                    print(f"[WARN][DATA_AGENT_MULTICAMERA] cv2.imwrite failed for {img_path}")
            except Exception as e:
                print(f"[WARN][DATA_AGENT_MULTICAMERA] Failed to write image {cam_name} frame {frame}: {e}")
        
        # Save optional TensorFlow labels
        if self.SAVE_TF_LABELS:
            if tick_data.get('semantics') is not None:
                cv2.imwrite(str(self.save_path / 'semantics' / f'{frame:04d}.png'), tick_data['semantics'])
            if tick_data.get('depth') is not None:
                cv2.imwrite(str(self.save_path / 'depth' / f'{frame:04d}.png'), tick_data['depth'])
            if tick_data.get('bev_semantics') is not None:
                cv2.imwrite(str(self.save_path / 'bev_semantics' / f'{frame:04d}.png'), tick_data['bev_semantics'])

        # Save LiDAR with compression if available
        try:
            lidar_data = tick_data.get('lidar')
            if lidar_data is not None and getattr(lidar_data, 'shape', None) is not None and lidar_data.shape[0] > 0:
                header = laspy.LasHeader(point_format=self.config.point_format)
                header.offsets = np.min(lidar_data, axis=0)
                header.scales = np.array([
                    self.config.point_precision,
                    self.config.point_precision,
                    self.config.point_precision
                ])

                with laspy.open(self.save_path / 'lidar' / f'{frame:04d}.laz', mode='w', header=header) as writer:
                    point_record = laspy.ScaleAwarePointRecord.zeros(lidar_data.shape[0], header=header)
                    point_record.x = lidar_data[:, 0]
                    point_record.y = lidar_data[:, 1]
                    point_record.z = lidar_data[:, 2]
                    writer.write_points(point_record)
            else:
                print(f"[WARN][DATA_AGENT_MULTICAMERA] No lidar data for frame {frame}, skipping lidar write")
        except Exception as e:
            print(f"[WARN][DATA_AGENT_MULTICAMERA] Failed to write lidar for frame {frame}: {e}")

        # Save bounding boxes
        with gzip.open(self.save_path / 'boxes' / f'{frame:04d}.json.gz', 'wt', encoding='utf-8') as f:
            json.dump(tick_data['bounding_boxes'], f, indent=4, ensure_ascii=False)
        
        # Get ego transform for signal metadata and GPS tracking
        transform = self._vehicle.get_transform()
        
        
        # Save measurements (ego state + route info)
        try:
            measurements = self._build_measurements()
            with gzip.open(self.save_path / 'measurements' / f'{frame:04d}.json.gz', 'wt', encoding='utf-8') as f:
                json.dump(measurements, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[WARN][DATA_AGENT_MULTICAMERA] Failed to write measurements for frame {frame}: {e}")
        
        # Track GPS for trajectory plot (transform already retrieved above)
        self._gps_trajectory.append([float(transform.location.x), float(transform.location.y)])
        
        self.frame_counter += 1
        # Log step into ScenarioLogger if available so records.json.gz is populated
        try:
            if hasattr(self, 'lon_logger') and getattr(self, 'lon_logger') is not None:
                # Build a simple route representation from remaining_route for logging
                # ScenarioLogger expects numeric arrays (not Python lists) so convert to a NumPy array. Ensure shape (N,2) and provide an empty array fallback to avoid subtraction between lists inside rdp/route_as_boxes.
                route_for_log = np.empty((0, 2), dtype=float)
                if hasattr(self, 'remaining_route') and self.remaining_route is not None and len(getattr(self, 'remaining_route')) > 0:
                    try:
                        pts = self.remaining_route[:self.config.num_route_points_saved]
                        route_arr = np.asarray([[float(p[0]), float(p[1])] for p in pts], dtype=float)
                        # Ensure 2D shape even for single point
                        if route_arr.ndim == 1:
                            route_arr = route_arr.reshape(1, 2)
                        route_for_log = route_arr
                    except Exception as e:
                        print(f"[WARN] Could not build numeric route_for_log: {e}")
                        route_for_log = np.empty((0, 2), dtype=float)
                ego_control = None
                try:
                    ego_control = self._vehicle.get_control()
                except Exception:
                    ego_control = None

                try:
                    self.lon_logger.log_step(route_for_log, ego_control=ego_control)
                except Exception as e:
                    print(f"[WARN] lon_logger.log_step failed: {e}")
        except Exception:
            pass

    def _build_measurements(self):
        """
        Build measurements JSON matching simlingo training format.
        
        Returns dict with ego state, control, route, hazards, etc.
        MUST match exact format from japanese_driving_autopilot_cameras_mp.py
        """
        transform = self._vehicle.get_transform()
        velocity = self._vehicle.get_velocity()
        control = self._vehicle.get_control()
        
        speed = float(np.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2))
        
        # Get waypoint info
        try:
            current_wp = self.world_map.get_waypoint(transform.location)
            junction = current_wp.is_junction if current_wp else False
            speed_limit = float(current_wp.lane_width * 3.6) if current_wp else 60.0
        except Exception:
            junction = False
            speed_limit = 60.0

        # Ego transformation matrix (for coordinate transformations)
        ego_matrix_np = np.array(transform.get_matrix())
        
        # For JSON serialization, convert to nested Python list
        try:
            ego_matrix_json = transform.get_matrix()  # Returns Python list
        except:
            ego_matrix_json = [
                [1.0, 0.0, 0.0, float(transform.location.x)],
                [0.0, 1.0, 0.0, float(transform.location.y)],
                [0.0, 0.0, 1.0, float(transform.location.z)],
                [0.0, 0.0, 0.0, 1.0]
            ]

        # Route information from AutoPilot (CRITICAL: use remaining_route)
        # AutoPilot populates self.remaining_route in _get_control()
        # IMPORTANT: Convert to ego-relative coords to match simlingo reference format
        if hasattr(self, 'remaining_route') and self.remaining_route is not None and len(getattr(self, 'remaining_route')) > 0:
            route = []
            for p in self.remaining_route[:self.config.num_route_points_saved]:
                # Build 4x4 matrix for route point (same format as vehicle matrices)
                point_matrix = np.array([
                    [1.0, 0.0, 0.0, float(p[0])],
                    [0.0, 1.0, 0.0, float(p[1])],
                    [0.0, 0.0, 1.0, 0.0],
                    [0.0, 0.0, 0.0, 1.0]
                ])
                relative_pos = t_u.get_relative_transform(ego_matrix_np, point_matrix)
                # CRITICAL: Convert NumPy array to Python list for JSON serialization
                route.append([float(relative_pos[0].item() if hasattr(relative_pos[0], 'item') else relative_pos[0]), 
                             float(relative_pos[1].item() if hasattr(relative_pos[1], 'item') else relative_pos[1])])
            
            # Same transformation for route_original
            route_original = []
            if hasattr(self, 'remaining_route_original') and self.remaining_route_original is not None:
                for p in self.remaining_route_original[:self.config.num_route_points_saved]:
                    point_matrix = np.array([
                        [1.0, 0.0, 0.0, float(p[0])],
                        [0.0, 1.0, 0.0, float(p[1])],
                        [0.0, 0.0, 1.0, 0.0],
                        [0.0, 0.0, 0.0, 1.0]
                    ])
                    relative_pos = t_u.get_relative_transform(ego_matrix_np, point_matrix)
                    # CRITICAL: Convert NumPy array to Python list for JSON serialization
                    route_original.append([float(relative_pos[0].item() if hasattr(relative_pos[0], 'item') else relative_pos[0]), 
                                          float(relative_pos[1].item() if hasattr(relative_pos[1], 'item') else relative_pos[1])])
            else:
                route_original = route
        else:
            # Fallback to empty route if not initialized yet
            route = []
            route_original = []
        
        target_point = route[0] if len(route) > 0 else [0.0, 0.0]
        target_point_next = route[1] if len(route) > 1 else target_point
        
        # Aim waypoint from autopilot - ensure it's a Python list, not numpy array
        if hasattr(self, 'aim_wp') and self.aim_wp is not None:
            if hasattr(self.aim_wp, 'tolist'):
                aim_wp = self.aim_wp.tolist()
            elif isinstance(self.aim_wp, (list, tuple)):
                aim_wp = [float(x) for x in self.aim_wp]
            else:
                aim_wp = target_point
        else:
            aim_wp = target_point
        
        # Command (from autopilot's command buffer)
        command = int(self.commands[0]) if hasattr(self, 'commands') and len(self.commands) > 0 else 4
        next_command = int(self.commands[1]) if hasattr(self, 'commands') and len(self.commands) > 1 else 4
        
        # Changed route detection
        changed_route = getattr(self, '_route_changed', False)
        
        # Speed reduction info - ensure all are JSON-serializable
        if hasattr(self, 'speed_reduced_by_obj_type'):
            speed_reduced_by_obj_type = self.speed_reduced_by_obj_type
            speed_reduced_by_obj_id = self.speed_reduced_by_obj_id
            # Convert numpy float to Python float if needed
            speed_reduced_by_obj_distance = float(self.speed_reduced_by_obj_distance) if self.speed_reduced_by_obj_distance is not None else None
        else:
            speed_reduced_by_obj_type = None
            speed_reduced_by_obj_id = None
            speed_reduced_by_obj_distance = None
        
        measurements = {
            'pos_global': [float(transform.location.x), float(transform.location.y)],
            'theta': float(np.radians(transform.rotation.yaw)),
            'speed': speed,
            'target_speed': float(getattr(self, 'target_speed', 20.0)),
            'speed_limit': speed_limit,
            'target_point': target_point,
            'target_point_next': target_point_next,
            'command': command,
            'next_command': next_command,
            'aim_wp': aim_wp,
            'route': route, # local ego-relative coords
            'route_original': route_original,
            'changed_route': changed_route,
            'speed_reduced_by_obj_type': speed_reduced_by_obj_type,
            'speed_reduced_by_obj_id': speed_reduced_by_obj_id,
            'speed_reduced_by_obj_distance': speed_reduced_by_obj_distance,
            'steer': float(control.steer),
            'throttle': float(control.throttle),
            'brake': float(control.brake),
            'control_brake': bool(control.brake > 0.0),
            'junction': junction,
            'vehicle_hazard': getattr(self, 'vehicle_hazard', False),
            'vehicle_affecting_id': None,
            'light_hazard': getattr(self, 'traffic_light_hazard', False),
            'walker_hazard': getattr(self, 'walker_hazard', False),
            'walker_affecting_id': None,
            'stop_sign_hazard': getattr(self, 'stop_sign_hazard', False),
            'stop_sign_close': getattr(self, 'stop_sign_close', False),
            'walker_close': getattr(self, 'walker_close', False),
            'walker_close_id': None,
            'angle': float(getattr(self, 'angle', 0.0)),
            'augmentation_translation': float(getattr(self, 'augmentation_translation', 0.0)),
            'augmentation_rotation': float(getattr(self, 'augmentation_rotation', 0.0)),
            'ego_matrix': ego_matrix_json
        }
        
        return measurements

    def get_bounding_boxes(self, lidar=None):
        """
        Get enriched bounding boxes matching simlingo_v2_2025_01_10 format.
        
        Combines data_agent.py's comprehensive object detection with
        japanese_driving_autopilot_cameras_mp.py's lane-relative calculations.
        
        Returns list of dicts with classes: ego_car, car, walker, traffic_light,
        traffic_light_vqa, stop_sign, stop_sign_vqa, static, landmark, ego_info, weather.
        """
        results = []

        if not self._vehicle:
            return results

        ego_transform = self._vehicle.get_transform()
        ego_control = self._vehicle.get_control()
        ego_velocity = self._vehicle.get_velocity()
        ego_matrix = np.array(ego_transform.get_matrix())
        ego_rotation = ego_transform.rotation
        ego_extent = self._vehicle.bounding_box.extent
        ego_speed = self._get_forward_speed(transform=ego_transform, velocity=ego_velocity)
        ego_dx = np.array([ego_extent.x, ego_extent.y, ego_extent.z])
        ego_yaw = np.deg2rad(ego_rotation.yaw)
        ego_brake = ego_control.brake
        ego_location = ego_transform.location

        ego_wp = self.world_map.get_waypoint(ego_location, project_to_road=True, lane_type=carla.libcarla.LaneType.Any)
        
        if not ego_wp:
            return results

        # Compute lane direction info for lane_relative_to_ego calculations
        left_wp, right_wp = ego_wp.get_left_lane(), ego_wp.get_right_lane()
        left_decreasing_lane_id = (left_wp is not None and left_wp.lane_id < ego_wp.lane_id) or \
                                   (right_wp is not None and right_wp.lane_id > ego_wp.lane_id)
        
        # Count lanes to remove for opposite direction
        remove_lanes_for_lane_relative_to_ego = 1
        wp = ego_wp
        is_opposite = False
        max_lane_scan = 20
        scan_count = 0
        while scan_count < max_lane_scan:
            flag = ego_wp.lane_id > 0 and left_decreasing_lane_id or ego_wp.lane_id < 0 and not left_decreasing_lane_id
            if is_opposite:
                flag = not flag
            wp = wp.get_left_lane() if flag else wp.get_right_lane()
                
            if wp is None or wp.lane_type == carla.LaneType.Driving and ego_wp.lane_id * wp.lane_id < 0:
                break
            
            is_opposite = ego_wp.lane_id * wp.lane_id < 0
            
            if wp.lane_type != carla.LaneType.Driving:
                remove_lanes_for_lane_relative_to_ego += 1
            
            scan_count += 1

        ego_lane_direction = ego_wp.lane_id / abs(ego_wp.lane_id)

        # Build ego_car entry
        relative_yaw = 0.0
        relative_pos = t_u.get_relative_transform(ego_matrix, ego_matrix)

        result = {
            'class': 'ego_car',
            'extent': [ego_dx[0], ego_dx[1], ego_dx[2]],
            'position': [relative_pos[0], relative_pos[1], relative_pos[2]],
            'yaw': relative_yaw,
            'num_points': -1,
            'distance': -1,
            'speed': ego_speed,
            'brake': ego_brake,
            'id': int(self._vehicle.id),
            'matrix': ego_transform.get_matrix()
        }
        results.append(result)

        # Process vehicles (use cached actor list to avoid slow get_actors() every frame)
        current_frame = self.frame_counter
        if self._actors_cache is None or (current_frame - self._actors_cache_frame) >= self._actors_cache_interval:
            self._actors = self._world.get_actors()
            self._actors_cache = self._actors
            self._actors_cache_frame = current_frame
        else:
            self._actors = self._actors_cache

        vehicle_list = self._actors.filter('*vehicle*')

        for vehicle in vehicle_list:
            if vehicle.get_location().distance(self._vehicle.get_location()) < self.config.bb_save_radius:
                if vehicle.id != self._vehicle.id:
                    vehicle_transform = vehicle.get_transform()
                    vehicle_rotation = vehicle_transform.rotation
                    vehicle_matrix = np.array(vehicle_transform.get_matrix())
                    vehicle_control = vehicle.get_control()
                    vehicle_velocity = vehicle.get_velocity()
                    vehicle_extent = vehicle.bounding_box.extent
                    vehicle_id = vehicle.id
                    vehicle_wp = self.world_map.get_waypoint(vehicle.get_location(), project_to_road=True,
                                                             lane_type=carla.libcarla.LaneType.Any)
                    same_road_as_ego = False
                    lane_relative_to_ego = None
                    same_direction_as_ego = False

                    # Get next road/junction info
                    next_wps = self._wps_next_until_lane_end(vehicle_wp)
                    try:
                        next_lane_wps = next_wps[-1].next(1) if next_wps else []
                        if len(next_lane_wps) == 0 and next_wps:
                            next_lane_wps = [next_wps[-1]]
                    except:
                        next_lane_wps = []

                    if vehicle_wp.is_junction:
                        distance_to_junction = 0.0
                    elif next_lane_wps and next_lane_wps[0].is_junction:
                        distance_to_junction = next_lane_wps[0].transform.location.distance(vehicle_wp.transform.location)
                    else:
                        distance_to_junction = None

                    next_road_ids = [wp.road_id for wp in next_lane_wps if wp.road_id not in []]
                    
                    # Compute lane-relative position
                    if vehicle_wp.road_id == ego_wp.road_id:
                        same_road_as_ego = True
                        direction = vehicle_wp.lane_id / abs(vehicle_wp.lane_id)
                        if direction == ego_lane_direction:
                            same_direction_as_ego = True

                        lane_relative_to_ego = vehicle_wp.lane_id - ego_wp.lane_id
                        lane_relative_to_ego *= -1 if left_decreasing_lane_id else 1
                        
                        if not same_direction_as_ego:
                            lane_relative_to_ego += remove_lanes_for_lane_relative_to_ego * (1 if lane_relative_to_ego < 0 else -1)
                        
                        lane_relative_to_ego = -lane_relative_to_ego

                    vehicle_extent_list = [vehicle_extent.x, vehicle_extent.y, vehicle_extent.z]
                    yaw = np.deg2rad(vehicle_rotation.yaw)

                    relative_yaw = t_u.normalize_angle(yaw - ego_yaw)
                    relative_pos = t_u.get_relative_transform(ego_matrix, vehicle_matrix)
                    vehicle_speed = self._get_forward_speed(transform=vehicle_transform, velocity=vehicle_velocity)
                    vehicle_brake = vehicle_control.brake
                    vehicle_steer = vehicle_control.steer
                    vehicle_throttle = vehicle_control.throttle

                    if lidar is not None:
                        num_in_bbox_points = self.get_points_in_bbox(relative_pos, relative_yaw, vehicle_extent_list, lidar)
                    else:
                        num_in_bbox_points = -1

                    distance = np.linalg.norm(relative_pos)
                    
                    # Get vehicle color
                    try:
                        rgb = tuple(map(int, vehicle.attributes['color'].split(',')))
                        color_name = convert_rgb_to_names(rgb)
                    except:
                        rgb = None
                        color_name = None
                    
                    # Get light state
                    try:
                        light_state = vehicle.get_light_state()
                        light_state_bin = bin(int(light_state))
                        light_state_bin_pos = [i for i, x in enumerate(reversed(light_state_bin)) if x == '1']
                        light_state_dec_pos = [2**i for i in light_state_bin_pos]
                    except:
                        light_state_dec_pos = []
                    
                    # Traffic light state for vehicle
                    tl = self._world.get_traffic_lights_from_waypoint(vehicle_wp, 30.0)
                    tl_state_vehicle = str(tl[0].state) if len(tl) > 0 else 'None'

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
                        'distance_to_junction': distance_to_junction,
                        'next_junction_id': next_lane_wps[0].junction_id if next_lane_wps else -1,
                        'next_road_ids': next_road_ids,
                        'next_next_road_ids': [],
                        'same_road_as_ego': same_road_as_ego,
                        'same_direction_as_ego': same_direction_as_ego,
                        'lane_relative_to_ego': lane_relative_to_ego,
                        'light_state': light_state_dec_pos,
                        'traffic_light_state': tl_state_vehicle,
                        'is_at_traffic_light': vehicle.is_at_traffic_light(),
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

        # Process walkers (pedestrians)
        walkers = self._actors.filter('*walker*')
        for walker in walkers:
            if walker.get_location().distance(self._vehicle.get_location()) < self.config.bb_save_radius:
                walker_transform = walker.get_transform()
                walker_velocity = walker.get_velocity()
                walker_rotation = walker_transform.rotation
                walker_matrix = np.array(walker_transform.get_matrix())
                walker_id = walker.id
                walker_extent = walker.bounding_box.extent
                walker_extent_list = [walker_extent.x, walker_extent.y, walker_extent.z]
                yaw = np.deg2rad(walker_rotation.yaw)

                relative_yaw = t_u.normalize_angle(yaw - ego_yaw)
                relative_pos = t_u.get_relative_transform(ego_matrix, walker_matrix)
                walker_speed = self._get_forward_speed(transform=walker_transform, velocity=walker_velocity)

                if lidar is not None:
                    num_in_bbox_points = self.get_points_in_bbox(relative_pos, relative_yaw, walker_extent_list, lidar)
                else:
                    num_in_bbox_points = -1

                distance = np.linalg.norm(relative_pos)
                
                walker_wp = self.world_map.get_waypoint(walker.get_location(), project_to_road=True,
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
                        lane_relative_to_ego += remove_lanes_for_lane_relative_to_ego * (1 if lane_relative_to_ego < 0 else -1)
                    
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

        # Add traffic lights and stop signs (from parent autopilot's close_* lists)
        for traffic_light in getattr(self, 'close_traffic_lights', []):
            traffic_light_extent = [traffic_light[0].extent.x, traffic_light[0].extent.y, traffic_light[0].extent.z]
            traffic_light_transform = carla.Transform(traffic_light[0].location, traffic_light[0].rotation)
            traffic_light_rotation = traffic_light_transform.rotation
            traffic_light_matrix = np.array(traffic_light_transform.get_matrix())
            yaw = np.deg2rad(traffic_light_rotation.yaw)

            relative_yaw = t_u.normalize_angle(yaw - ego_yaw)
            relative_pos = t_u.get_relative_transform(ego_matrix, traffic_light_matrix)
            distance = np.linalg.norm(relative_pos)

            result = {
                'class': 'traffic_light',
                'extent': traffic_light_extent,
                'position': [relative_pos[0], relative_pos[1], relative_pos[2]],
                'yaw': relative_yaw,
                'distance': distance,
                'state': str(traffic_light[1]),
                'id': int(traffic_light[2]),
                'affects_ego': traffic_light[3],
                'matrix': traffic_light_transform.get_matrix()
            }
            results.append(result)

        for stop_sign in getattr(self, 'close_stop_signs', []):
            stop_sign_extent = [stop_sign[0].extent.x, stop_sign[0].extent.y, stop_sign[0].extent.z]
            stop_sign_transform = carla.Transform(stop_sign[0].location, stop_sign[0].rotation)
            stop_sign_rotation = stop_sign_transform.rotation
            stop_sign_matrix = np.array(stop_sign_transform.get_matrix())
            yaw = np.deg2rad(stop_sign_rotation.yaw)

            relative_yaw = t_u.normalize_angle(yaw - ego_yaw)
            relative_pos = t_u.get_relative_transform(ego_matrix, stop_sign_matrix)
            distance = np.linalg.norm(relative_pos)

            result = {
                'class': 'stop_sign',
                'extent': stop_sign_extent,
                'position': [relative_pos[0], relative_pos[1], relative_pos[2]],
                'yaw': relative_yaw,
                'distance': distance,
                'id': int(stop_sign[1]),
                'affects_ego': stop_sign[2],
                'matrix': stop_sign_transform.get_matrix()
            }
            results.append(result)

        # Build ego_info (lane configuration, hazards, etc.)
        tl_state = 'None'
        try:
            tl = self._world.get_traffic_lights_from_waypoint(ego_wp, 50.0)
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

        # Count lanes (same logic as data_agent.py)
        ego_lane_number = 1
        num_lanes_same_direction = 1
        num_lanes_opposite_direction = 0
        shoulder_left = shoulder_right = False
        parking_left = parking_right = False
        sidewalk_left = sidewalk_right = False
        bikelane_left = bikelane_right = False

        # Scan left and right lanes
        for i, direction_name in enumerate(['left', 'right']):
            lane_wp = ego_wp
            is_opposite_dir = False
            scan_limit = 20
            scan_count = 0
            
            while scan_count < scan_limit:
                if i == 0:  # left
                    lane_wp = lane_wp.get_left_lane() if not is_opposite_dir else lane_wp.get_right_lane()
                else:  # right
                    lane_wp = lane_wp.get_right_lane() if not is_opposite_dir else lane_wp.get_left_lane()

                if lane_wp is None:
                    break

                direction = lane_wp.lane_id / abs(lane_wp.lane_id)
                lane_type = lane_wp.lane_type
                
                if lane_type == carla.LaneType.Driving and direction == ego_lane_direction:
                    num_lanes_same_direction += 1
                elif lane_type == carla.LaneType.Driving and direction != ego_lane_direction:
                    num_lanes_opposite_direction += 1
                elif lane_type == carla.LaneType.Shoulder and i == 0:
                    shoulder_left = True
                elif lane_type == carla.LaneType.Shoulder and i == 1:
                    shoulder_right = True
                elif lane_type == carla.LaneType.Parking and i == 0:
                    parking_left = True
                elif lane_type == carla.LaneType.Parking and i == 1:
                    parking_right = True
                elif lane_type == carla.LaneType.Sidewalk and i == 0:
                    sidewalk_left = True
                elif lane_type == carla.LaneType.Sidewalk and i == 1:
                    sidewalk_right = True
                elif lane_type == carla.LaneType.Biking and i == 0:
                    bikelane_left = True
                elif lane_type == carla.LaneType.Biking and i == 1:
                    bikelane_right = True

                if direction != ego_lane_direction:
                    is_opposite_dir = True
                
                scan_count += 1

        ego_lane = {'type:': str(ego_wp.lane_type), 'width': ego_wp.lane_width}
        left_lanes = []
        right_lanes = []

        ego_info = {
            'class': 'ego_info',
            'scenario': self.scenario_name,
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
        weather = self._world.get_weather()
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

    def _wps_next_until_lane_end(self, wp):
        """Get waypoints until lane ends or changes road/lane ID."""
        try:
            road_id_cur = wp.road_id
            lane_id_cur = wp.lane_id
            road_id_next = road_id_cur
            lane_id_next = lane_id_cur
            curr_wp = [wp]
            next_wps = []
            while road_id_cur == road_id_next and lane_id_cur == lane_id_next:
                next_wp = curr_wp[0].next(1)
                if len(next_wp) == 0:
                    break
                curr_wp = next_wp
                next_wps.append(next_wp[0])
                road_id_next = next_wp[0].road_id
                lane_id_next = next_wp[0].lane_id
        except:
            next_wps = []
        return next_wps

    def get_points_in_bbox(self, vehicle_pos, vehicle_yaw, extent, lidar):
        """Count LiDAR points inside bounding box."""
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

    def visualuize(self, rendered, visu_img):
        """Debug visualization overlay."""
        visu_img = cv2.resize(visu_img, dsize=(rendered.shape[1], rendered.shape[0]), interpolation=cv2.INTER_NEAREST)
        final = np.concatenate((visu_img, rendered), axis=0)
        cv2.imshow('BEV', final)
        cv2.waitKey(1)

    def _save_gps_plot(self, line_width=3, font_size=14, font_size_title=16):
        """Save GPS trajectory plot as GPS.jpg in output folder
        Implementation ported from japanese_driving_autopilot_cameras_mp.py — supports
        single-point plots, arrows for end direction, legend and styling options.
        """
        if not hasattr(self, '_gps_trajectory') or len(self._gps_trajectory) == 0:
            print("[INFO]: No GPS points to plot trajectory")
            return

        try:
            # Ensure non-interactive backend already selected elsewhere; defensive fallback
            try:
                matplotlib.use('Agg')
            except Exception:
                pass

            # Extract X and Y coordinates
            xs = [pt[0] for pt in self._gps_trajectory]
            ys = [pt[1] for pt in self._gps_trajectory]

            # Create plot with configurable styling
            fig, ax = plt.subplots(figsize=(10, 8))
            ax.plot(xs, ys, linewidth=line_width, color='blue', alpha=0.9)
            ax.set_xlabel('X [m]', fontsize=font_size)
            ax.set_ylabel('Y [m]', fontsize=font_size)
            ax.set_title('Vehicle GPS Trajectory', fontsize=font_size_title)
            ax.grid(True, alpha=0.7)
            ax.axis('equal')

            # Mark start point with a filled circle
            start_x, start_y = xs[0], ys[0]
            ax.scatter([start_x], [start_y], s=120, c='green', marker='o', zorder=5, edgecolors='black')
            ax.text(start_x, start_y, '  START', fontsize=font_size, verticalalignment='center', horizontalalignment='left', color='black')

            # If trajectory has at least two points, draw arrow to final point
            if len(xs) >= 2:
                end_x, end_y = xs[-1], ys[-1]
                prev_x, prev_y = xs[-2], ys[-2]
                ax.annotate('', xy=(end_x, end_y), xytext=(prev_x, prev_y), arrowprops=dict(arrowstyle='->', color='red', linewidth=2), zorder=6)
                ax.scatter([end_x], [end_y], s=100, c='red', marker='>', zorder=6)
                ax.text(end_x, end_y, '  END', fontsize=font_size, verticalalignment='center', horizontalalignment='left', color='black')
            else:
                # Single-point trajectory: mark it as POINT
                ax.text(start_x, start_y, '  POINT', fontsize=font_size, verticalalignment='center', horizontalalignment='left', color='black')

            # Legend entries
            start_patch = mpatches.Circle((0, 0), radius=0.1, facecolor='green', edgecolor='black')
            end_line = mlines.Line2D([], [], color='red', marker='>', linestyle='None')
            ax.legend([start_patch, end_line], ['Start', 'End'], loc='best', framealpha=0.3)

            gps_path = self.save_path / 'GPS.jpg'
            plt.savefig(str(gps_path), dpi=150, bbox_inches='tight')
            plt.close(fig)
            print(f"[INFO]: Saved GPS trajectory plot to {gps_path}")
        except Exception as e:
            print(f"[WARNING]: Failed to save GPS plot: {e}")

    def _signal_handler(self, signum, frame):
        """
        Handle SIGTERM/SIGINT gracefully by saving files directly.
        This ensures results.json.gz and records.json.gz are saved even with timeout.
        """
        # Use os.write for signal-safe output (avoids reentrant call errors)
        try:
            msg = f"\n{'='*80}\n[DATA_AGENT_MULTICAMERA] Received signal {signum} - saving files and exiting...\n{'='*80}\n".encode()
            os.write(1, msg)
        except:
            pass
        try:
            # Save results.json.gz directly
            if hasattr(self, 'save_path') and self.save_path is not None:
                # Get route_id (stored in setup())
                route_id = getattr(self, 'route_id', 'unknown')
                
                results_path = self.save_path / 'results.json.gz'
                # Build richer infractions structure like example
                infractions_template = {
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
                }

                # Compute route_length from GPS trajectory if available
                try:
                    route_length = 0.0
                    if hasattr(self, '_gps_trajectory') and len(self._gps_trajectory) > 1:
                        pts = self._gps_trajectory
                        for i in range(1, len(pts)):
                            dx = pts[i][0] - pts[i-1][0]
                            dy = pts[i][1] - pts[i-1][1]
                            route_length += math.hypot(dx, dy)
                    else:
                        route_length = 0.0
                except Exception:
                    route_length = 0.0

                # Durations
                try:
                    duration_system = time.time() - (self.wallclock_t0.timestamp() if isinstance(self.wallclock_t0, datetime) and self.wallclock_t0 else time.time())
                except Exception:
                    duration_system = 0.0

                # duration_game is not available here; set to duration_system as fallback
                duration_game = duration_system

                results_data = {
                    'timestamp': getattr(self, 'route_id', route_id),
                    'index': 0,
                    'route_id': getattr(self, 'route_id_export', route_id),
                    'status': 'Timeout',
                    'num_infractions': 0,
                    'infractions': infractions_template,
                    'scores': {'score_route': 0.0, 'score_penalty': 1.0, 'score_composed': 0.0},
                    'meta': {
                        'route_length': route_length,
                        'duration_game': duration_game,
                        'duration_system': duration_system
                    }
                }

                with gzip.open(results_path, 'wt', encoding='utf-8') as f:
                    json.dump(results_data, f, indent=4, ensure_ascii=False)
                print(f"[DATA_AGENT_MULTICAMERA] Saved results.json.gz (route_id_export={getattr(self, 'route_id_export', route_id)})")
                
                # Save records.json.gz via scenario logger with explicit path
                records_path = self.save_path / 'records.json.gz'
                if hasattr(self, 'lon_logger') and self.lon_logger is not None:
                    try:
                        # Call lon_logger's dump_to_json with explicit path
                        self.lon_logger.save_path = str(self.save_path)
                        self.lon_logger.dump_to_json()
                        print(f"[DATA_AGENT_MULTICAMERA] Saved records.json.gz via lon_logger")
                    except Exception as e:
                        print(f"[WARN] lon_logger.dump_to_json() failed: {e}")
                        # Fallback: save basic records from _frame_records
                        if self._frame_records:
                            with gzip.open(records_path, 'wt', encoding='utf-8') as f:
                                json.dump({'records': self._frame_records}, f, indent=4, ensure_ascii=False)
                            print(f"[DATA_AGENT_MULTICAMERA] Saved records.json.gz (fallback with {len(self._frame_records)} frames)")
                else:
                    # No lon_logger - use _frame_records as fallback
                    if self._frame_records:
                        with gzip.open(records_path, 'wt', encoding='utf-8') as f:
                            json.dump({'records': self._frame_records}, f, indent=4, ensure_ascii=False)
                        print(f"[DATA_AGENT_MULTICAMERA] Saved records.json.gz (no lon_logger, {len(self._frame_records)} frames)")
                    else:
                        pass  # Skip message to avoid reentrant I/O

                # Attempt to save GPS plot if trajectory exists (run regardless of lon_logger result)
                try:
                    # If in-memory GPS trajectory exists, use it
                    if hasattr(self, '_gps_trajectory') and self._gps_trajectory and hasattr(self, '_save_gps_plot'):
                        try:
                            self._save_gps_plot()
                        except Exception:
                            pass
                    else:
                        # Try to rebuild GPS trajectory from measurements files on disk
                        try:
                            meas_dir = Path(self.save_path) / 'measurements'
                            if meas_dir.exists():
                                gps_pts = []
                                for mf in sorted(meas_dir.glob('*.json.gz')):
                                    try:
                                        with gzip.open(mf, 'rt', encoding='utf-8') as f:
                                            md = json.load(f)
                                        pg = md.get('pos_global') or md.get('pos')
                                        if isinstance(pg, (list, tuple)) and len(pg) >= 2:
                                            gps_pts.append([float(pg[0]), float(pg[1])])
                                    except Exception:
                                        continue
                                if gps_pts:
                                    self._gps_trajectory = gps_pts
                                    try:
                                        self._save_gps_plot()
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass  # Fail silently to avoid cascading errors
        finally:
            os._exit(0)  # Force immediate exit without cleanup

    def _try_load_leaderboard21_checkpoint(self):
        """
        Attempt to read the leaderboard21 checkpoint JSON pointed by env leaderboard21_CHECKPOINT
        and extract the matching route record for the current `route_id_export` if present.
        Returns a dict or None.
        """
        try:
            cp_path = os.environ.get('leaderboard21_CHECKPOINT', None)
            if not cp_path:
                return None
            if not os.path.exists(cp_path):
                return None
            with open(cp_path, 'r') as f:
                data = json.load(f)
            # checkpoint format: { 'global_record': ..., 'progress': ..., 'records': [...] }
            records = data.get('records', []) if isinstance(data, dict) else []
            target_id = getattr(self, 'route_id_export', getattr(self, 'route_id', None))
            for r in records:
                # route_id in checkpoint might be string like 'RouteScenario_0_rep0' or similar
                if r.get('route_id') == target_id or r.get('route_id') == getattr(self, 'route_id', None):
                    return r
            return None
        except Exception:
            return None

    def _compute_statistics_from_data(self):
        """
        Compute basic statistics from collected data when leaderboard21 doesn't provide results.
        This fallback is used when leaderboard21_TIMEOUT kills the process before statistics registration.
        Attempts to extract actual infractions from scenario criteria if available.
        
        Returns:
            dict: RouteRecord-like structure with computed statistics
        """
        try:
            records_path = Path(self.save_path) / 'records.json.gz'
            if not records_path.exists():
                return None
            
            with gzip.open(records_path, 'rt', encoding='utf-8') as f:
                records = json.load(f)
            
            # Compute route distance from GPS trajectory
            route_length = 0.0
            if hasattr(self, '_gps_trajectory') and len(self._gps_trajectory) > 1:
                for i in range(1, len(self._gps_trajectory)):
                    p1, p2 = self._gps_trajectory[i-1], self._gps_trajectory[i]
                    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
                    route_length += np.sqrt(dx*dx + dy*dy)
            
            # Compute duration (step_count / 10 Hz = seconds)
            duration_sec = self.step / 10.0 if self.step > 0 else 0.0
            
            # Compute route completion percentage from waypoint progress
            score_route = 0.0
            if hasattr(self, '_waypoint_planner'):
                try:
                    current_index = getattr(self._waypoint_planner, 'route_index', 0)
                    # Try to get total route length from commands or route_points
                    total_length = 0
                    if hasattr(self._waypoint_planner, 'commands'):
                        total_length = len(self._waypoint_planner.commands)
                    elif hasattr(self._waypoint_planner, 'route_points'):
                        total_length = len(self._waypoint_planner.route_points)
                    
                    if total_length > 0:
                        score_route = min(100.0, (current_index / total_length) * 100.0)
                        print(f"[DATA_AGENT_MULTICAMERA] Route progress: {current_index}/{total_length} = {score_route:.1f}%")
                except Exception as e:
                    print(f"[INFO] Could not compute route completion: {e}")
            
            # Try to extract infractions from scenario criteria (if scenario is still accessible)
            infractions = {
                'collisions_layout': [],
                'collisions_pedestrian': [],
                'collisions_vehicle': [],
                'red_light': [],
                'stop_infraction': [],
                'outside_route_lanes': [],
                'route_dev': [],
                'vehicle_blocked': [],
                'min_speed_infractions': []
            }
            
            # Attempt to get infractions from scenario manager if available
            try:
                from srunner.scenariomanager.carla_data_provider import CarlaDataProvider
                from leaderboard21.utils.statistics_manager_local import PENALTY_NAME_DICT
                
                # Check if we have active scenario with criteria
                if hasattr(self, '_current_scenario') and self._current_scenario is not None:
                    scenario = self._current_scenario
                    if hasattr(scenario, 'get_criteria'):
                        for node in scenario.get_criteria():
                            if hasattr(node, 'events'):
                                for event in node.events:
                                    event_type = event.get_type()
                                    if event_type in PENALTY_NAME_DICT:
                                        infraction_name = PENALTY_NAME_DICT[event_type]
                                        if infraction_name in infractions:
                                            infractions[infraction_name].append(event.get_message())
                        print(f"[DATA_AGENT_MULTICAMERA] Extracted {sum(len(v) for v in infractions.values())} infractions from scenario criteria")
            except Exception as e:
                print(f"[INFO] Could not extract infractions from scenario: {e}")
            
            # Compute penalty score from infractions (simplified - actual leaderboard21 has complex penalty calculation)
            score_penalty = 1.0  # No penalty if no infractions found
            total_infractions = sum(len(v) for v in infractions.values())
            if total_infractions > 0:
                # Simple penalty: each infraction reduces score by ~7% (matching leaderboard21 PENALTY_VALUE_DICT)
                score_penalty = max(0.0, 1.0 - (total_infractions * 0.07))
            
            score_composed = score_route * score_penalty
            
            # Build RouteRecord-like result structure
            results_data = {
                'route_id': getattr(self, 'route_id', 'unknown'),
                'index': getattr(self, 'route_index', 0),
                'status': 'Completed' if score_route >= 100.0 else 'Timeout',
                'infractions': infractions,
                'scores': {
                    'score_route': round(score_route, 2),
                    'score_penalty': round(score_penalty, 4),
                    'score_composed': round(score_composed, 2)
                },
                'meta': {
                    'route_length': route_length,
                    'duration_game': duration_sec,
                    'duration_system': duration_sec
                }
            }
            
            print(f"[DATA_AGENT_MULTICAMERA] Computed statistics from collected data:")
            print(f"  Steps: {self.step}")
            print(f"  Route length: {route_length:.1f}m")
            print(f"  Duration: {duration_sec:.1f}s")
            
            return results_data
            
        except Exception as e:
            print(f"[WARN] Failed to compute statistics from data: {e}")
            return None

    def destroy(self, results=None):
        """
        Clean up and save final results.json.gz.
        Parent AutoPilot.destroy() saves records.json.gz via ScenarioLogger.
        
        Args:
            results: RouteRecord from leaderboard21 with computed statistics (completion %, infractions, scores)
        """
        torch.cuda.empty_cache()
        
        # Save GPS trajectory plot before cleanup
        if getattr(self, 'save_path', None) is not None and hasattr(self, '_gps_trajectory'):
            try:
                self._save_gps_plot()
            except Exception as e:
                print(f"[WARN] Failed to save GPS plot: {e}")
        
        # If no results provided (timeout scenario), try computing from collected data
        if results is None and getattr(self, 'save_path', None) is not None:
            print(f"[INFO] No results from leaderboard21 - computing statistics from collected data")
            results_data = self._compute_statistics_from_data()
            if results_data is not None:
                # Save computed statistics as results.json.gz
                try:
                    results_path = Path(self.save_path) / 'results.json.gz'
                    with gzip.open(results_path, 'wt', encoding='utf-8') as f:
                        json.dump(results_data, f, indent=4, ensure_ascii=False)
                    print(f"[DATA_AGENT_MULTICAMERA] Saved computed results.json.gz")
                except Exception as e:
                    print(f"[WARN] Failed to save computed results.json.gz: {e}")
        
        # Save results.json.gz if leaderboard21 provided route statistics
        elif results is not None and getattr(self, 'save_path', None) is not None:
            try:
                results_path = Path(self.save_path) / 'results.json.gz'
                # RouteRecord has a to_json() method that returns vars(self)
                results_data = results.to_json() if hasattr(results, 'to_json') else results.__dict__
                
                # Check if leaderboard21 reported 0% completion but we actually have data
                # This happens when timeout occurs before leaderboard21 computes route progress
                scores = results_data.get('scores', {})
                if scores.get('score_route', 0) == 0 and self.step > 0:
                    print(f"[INFO] leaderboard21 reported 0% completion, computing actual progress...")
                    computed_stats = self._compute_statistics_from_data()
                    if computed_stats is not None:
                        # Override route completion and composed score with our computation
                        results_data['scores']['score_route'] = computed_stats['scores']['score_route']
                        results_data['scores']['score_composed'] = computed_stats['scores']['score_composed']
                        # Keep leaderboard21's infractions and penalty (they're accurate)
                        print(f"[DATA_AGENT_MULTICAMERA] Enhanced results with computed route completion: {results_data['scores']['score_route']:.1f}%")
                
                with gzip.open(results_path, 'wt', encoding='utf-8') as f:
                    json.dump(results_data, f, indent=4, ensure_ascii=False)
                
                print(f"[DATA_AGENT_MULTICAMERA] Saved results.json.gz:")
                print(f"  Route: {results_data.get('route_id', 'unknown')}")
                print(f"  Status: {results_data.get('status', 'unknown')}")
                print(f"  Score: {results_data.get('scores', {}).get('score_route', 0)}%")
                print(f"  Completion: {results_data.get('scores', {}).get('score_composed', 0)}")
            except Exception as e:
                print(f"[WARN] Failed to save results.json.gz: {e}")

        # Call parent destroy - this saves records.json.gz via lon_logger.dump_to_json()
        super().destroy(results)


# Entry point for leaderboard21
if __name__ == '__main__':
    print("[INFO] DataAgentMulticamera: traffic data collection agent with multicamera")
