# Copy of japanese_driving_autopilot_cameras.py with added get_bounding_boxes() method from data_agent.py
# This file adds ego_car dictionary and enriched bounding box information matching the simlingo training format

# NOTE: This is an extended version that includes the get_bounding_boxes() method
# from team_code/data_agent.py to ensure all ego_car and actor fields are captured
# for training compatibility with simlingo_v2_2025_01_10 dataset format

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
from bosch_utils.config import cfg, RECORDING_OUTPUT_DIR, IMAGE_FORMAT, IMAGE_EXT, JPG_QUALITY, PNG_COMPRESS_LEVEL, SIMLINGO_VERSION_DIR


# Import the parent class from the original file
import sys
sys.path.insert(0, os.path.dirname(__file__))
from japanese_driving_autopilot_cameras import JapaneseStyleAutopilot as JapaneseStyleAutopilotBase


class JapaneseStyleAutopilot(JapaneseStyleAutopilotBase):
    """Extended version with get_bounding_boxes() matching data_agent.py format"""
    
    def get_bounding_boxes(self, lidar=None):
        """Get bounding boxes for all nearby actors with ego_car entry matching data_agent.py
        
        This method is adapted from team_code/data_agent.py to ensure complete field coverage
        for training data compatibility.
        """
        results = []
        
        # Get ego vehicle information
        if not self.player_vehicle:
            return results
            
        ego_transform = self.player_vehicle.get_transform()
        ego_control = self.player_vehicle.get_control()
        ego_velocity = self.player_vehicle.get_velocity()
        ego_matrix = np.array(ego_transform.get_matrix())
        ego_rotation = ego_transform.rotation
        ego_extent = self.player_vehicle.bounding_box.extent
        ego_speed = float(np.sqrt(ego_velocity.x**2 + ego_velocity.y**2 + ego_velocity.z**2))
        ego_dx = np.array([ego_extent.x, ego_extent.y, ego_extent.z])
        ego_yaw = np.deg2rad(ego_rotation.yaw)
        ego_brake = ego_control.brake
        ego_location = ego_transform.location
        
        # Get ego waypoint for road/lane information
        try:
            carla_map = self.world.get_map()
            ego_wp = carla_map.get_waypoint(ego_location)
        except Exception as e:
            print(f"[WARN] Could not get ego waypoint: {e}")
            ego_wp = None
        
        # Build ego_car entry matching data_agent.py format
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
        
        # Get all actors in the world
        try:
            actors = self.world.get_actors()
            vehicles = actors.filter('vehicle.*')
            walkers = actors.filter('walker.pedestrian.*')
            ego_id = self.player_vehicle.id
            
            # Process vehicles
            for vehicle in vehicles:
                if vehicle.id == ego_id:
                    continue
                    
                if vehicle.get_location().distance(self.player_vehicle.get_location()) < 60.0:  # 60m radius
                    vehicle_transform = vehicle.get_transform()
                    vehicle_rotation = vehicle_transform.rotation
                    vehicle_matrix = np.array(vehicle_transform.get_matrix())
                    vehicle_control = vehicle.get_control()
                    vehicle_velocity = vehicle.get_velocity()
                    vehicle_extent = vehicle.bounding_box.extent
                    vehicle_id = vehicle.id
                    
                    vehicle_extent_list = [vehicle_extent.x, vehicle_extent.y, vehicle_extent.z]
                    yaw = np.deg2rad(vehicle_rotation.yaw)
                    
                    relative_yaw = self._normalize_angle(yaw - ego_yaw)
                    relative_pos = self._get_relative_transform(ego_matrix, vehicle_matrix)
                    vehicle_speed = float(np.sqrt(vehicle_velocity.x**2 + vehicle_velocity.y**2 + vehicle_velocity.z**2))
                    vehicle_brake = vehicle_control.brake
                    vehicle_steer = vehicle_control.steer
                    vehicle_throttle = vehicle_control.throttle
                    
                    # Compute LiDAR points in bbox (if lidar available)
                    if lidar is not None:
                        num_in_bbox_points = self._get_points_in_bbox(relative_pos, relative_yaw, vehicle_extent_list, lidar)
                    else:
                        num_in_bbox_points = -1
                        
                    distance = np.linalg.norm(relative_pos)
                    
                    # Get vehicle waypoint for road/lane information
                    try:
                        vehicle_wp = carla_map.get_waypoint(vehicle.get_location())
                    except:
                        vehicle_wp = None
                    
                    # Compute road/lane metadata
                    road_id = vehicle_wp.road_id if vehicle_wp else -1
                    lane_id = vehicle_wp.lane_id if vehicle_wp else 0
                    is_in_junction = vehicle_wp.is_junction if vehicle_wp else False
                    
                    # Compute lane relative to ego
                    same_road_as_ego = False
                    lane_relative_to_ego = 0
                    if ego_wp and vehicle_wp:
                        same_road_as_ego = (ego_wp.road_id == vehicle_wp.road_id)
                        if same_road_as_ego:
                            lane_relative_to_ego = vehicle_wp.lane_id - ego_wp.lane_id
                    
                    # Get vehicle color from attributes
                    try:
                        color_rgb = vehicle.attributes.get('color', '0,0,0')
                        color_name = 'unknown'
                    except:
                        color_rgb = '0,0,0'
                        color_name = 'unknown'
                    
                    result = {
                        'class': 'car',
                        'color_rgb': color_rgb,
                        'color_name': color_name,
                        'road_id': int(road_id),
                        'lane_id': int(lane_id),
                        'is_in_junction': is_in_junction,
                        'same_road_as_ego': same_road_as_ego,
                        'lane_relative_to_ego': int(lane_relative_to_ego),
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
                        'type_id': vehicle.type_id,
                        'matrix': vehicle_transform.get_matrix()
                    }
                    results.append(result)
            
            # Process walkers
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
                    
                    walker_speed = float(np.sqrt(walker_velocity.x**2 + walker_velocity.y**2 + walker_velocity.z**2))
                    
                    # Compute LiDAR points in bbox (if lidar available)
                    if lidar is not None:
                        num_in_bbox_points = self._get_points_in_bbox(relative_pos, relative_yaw, walker_extent_list, lidar)
                    else:
                        num_in_bbox_points = -1
                        
                    distance = np.linalg.norm(relative_pos)
                    
                    # Get walker waypoint for road/lane information
                    try:
                        walker_wp = carla_map.get_waypoint(walker.get_location())
                    except:
                        walker_wp = None
                    
                    # Compute lane metadata
                    same_road_as_ego = False
                    lane_relative_to_ego = 0
                    lane_type = 'Unknown'
                    if ego_wp and walker_wp:
                        same_road_as_ego = (ego_wp.road_id == walker_wp.road_id)
                        if same_road_as_ego:
                            lane_relative_to_ego = walker_wp.lane_id - ego_wp.lane_id
                        lane_type = str(walker_wp.lane_type) if walker_wp else 'Unknown'
                    
                    # Get walker attributes
                    try:
                        gender = walker.attributes.get('gender', 'unknown')
                        age = walker.attributes.get('age', 'unknown')
                    except:
                        gender = 'unknown'
                        age = 'unknown'
                    
                    result = {
                        'class': 'walker',
                        'gender': gender,
                        'age': age,
                        'lane_type': lane_type,
                        'same_road_as_ego': same_road_as_ego,
                        'lane_relative_to_ego': int(lane_relative_to_ego),
                        'extent': walker_extent_list,
                        'position': [relative_pos[0], relative_pos[1], relative_pos[2]],
                        'yaw': relative_yaw,
                        'num_points': int(num_in_bbox_points),
                        'distance': distance,
                        'speed': walker_speed,
                        'id': int(walker_id),
                        'matrix': walker_transform.get_matrix()
                    }
                    results.append(result)
                    
        except Exception as e:
            print(f"[ERROR] Error in get_bounding_boxes: {e}")
        
        # Add ego_info entry (CRITICAL for commentary generation)
        try:
            if ego_wp:
                # Get junction information
                is_in_junction = ego_wp.is_junction
                junction_id = ego_wp.get_junction().id if is_in_junction else -1
                
                # Compute distance to next junction
                distance_to_junction = 9999.0
                if not is_in_junction:
                    # Look ahead for next junction
                    test_wp = ego_wp
                    for _ in range(200):  # Look up to 200 waypoints ahead (~100m)
                        next_wps = test_wp.next(0.5)
                        if not next_wps:
                            break
                        test_wp = next_wps[0]
                        if test_wp.is_junction:
                            distance_to_junction = ego_location.distance(test_wp.transform.location)
                            break
                
                # Get lane information
                left_lane = ego_wp.get_left_lane()
                right_lane = ego_wp.get_right_lane()
                
                # Count lanes in same direction
                num_lanes_same_direction = 1
                temp_wp = ego_wp.get_left_lane()
                while temp_wp and temp_wp.lane_type == carla.LaneType.Driving:
                    num_lanes_same_direction += 1
                    temp_wp = temp_wp.get_left_lane()
                temp_wp = ego_wp.get_right_lane()
                while temp_wp and temp_wp.lane_type == carla.LaneType.Driving:
                    num_lanes_same_direction += 1
                    temp_wp = temp_wp.get_right_lane()
                
                # Get lane marking info
                left_marking = ego_wp.left_lane_marking
                right_marking = ego_wp.right_lane_marking
                
                ego_info = {
                    'class': 'ego_info',
                    'scenario': getattr(self, 'route_type', 'highway'),
                    'traffic_light_state': 'None',
                    'distance_to_junction': float(distance_to_junction),
                    'ego_lane_number': num_lanes_same_direction,
                    'road_id': int(ego_wp.road_id),
                    'lane_id': int(ego_wp.lane_id),
                    'is_in_junction': is_in_junction,
                    'is_intersection': is_in_junction,
                    'junction_id': int(junction_id),
                    'num_lanes_same_direction': num_lanes_same_direction,
                    'num_lanes_opposite_direction': 0,
                    'lane_change': int(ego_wp.lane_change),
                    'lane_type': int(ego_wp.lane_type),
                    'left_lane_marking_type': int(left_marking.type) if left_marking else 6,
                    'left_lane_marking_color': int(left_marking.color) if left_marking else 2,
                    'right_lane_marking_type': int(right_marking.type) if right_marking else 6,
                    'right_lane_marking_color': int(right_marking.color) if right_marking else 2,
                    'shoulder_left': left_lane.lane_type == carla.LaneType.Shoulder if left_lane else False,
                    'shoulder_right': right_lane.lane_type == carla.LaneType.Shoulder if right_lane else False,
                    'parking_left': left_lane.lane_type == carla.LaneType.Parking if left_lane else False,
                    'parking_right': right_lane.lane_type == carla.LaneType.Parking if right_lane else False,
                    'sidewalk_left': left_lane.lane_type == carla.LaneType.Sidewalk if left_lane else False,
                    'sidewalk_right': right_lane.lane_type == carla.LaneType.Sidewalk if right_lane else False,
                    'bike_lane_left': left_lane.lane_type == carla.LaneType.Biking if left_lane else False,
                    'bike_lane_right': right_lane.lane_type == carla.LaneType.Biking if right_lane else False,
                }
                results.append(ego_info)
            else:
                # Fallback ego_info when waypoint is unavailable
                ego_info = {
                    'class': 'ego_info',
                    'scenario': getattr(self, 'route_type', 'highway'),
                    'traffic_light_state': 'None',
                    'distance_to_junction': 9999.0,
                    'ego_lane_number': 1,
                    'road_id': -1,
                    'lane_id': 0,
                    'is_in_junction': False,
                    'is_intersection': False,
                    'junction_id': -1,
                }
                results.append(ego_info)
        except Exception as e:
            print(f"[WARN] Could not add ego_info: {e}")
        
        # Add weather information entry
        try:
            weather = self.world.get_weather()
            weather_info = {
                'class': 'weather',
                'cloudiness': float(weather.cloudiness),
                'dust_storm': float(weather.dust_storm),
                'fog_density': float(weather.fog_density),
                'fog_distance': float(weather.fog_distance),
                'fog_falloff': float(weather.fog_falloff),
                'mie_scattering_scale': float(weather.mie_scattering_scale),
                'precipitation': float(weather.precipitation),
                'precipitation_deposits': float(weather.precipitation_deposits),
                'rayleigh_scattering_scale': float(weather.rayleigh_scattering_scale),
                'scattering_intensity': float(weather.scattering_intensity),
                'sun_altitude_angle': float(weather.sun_altitude_angle),
                'sun_azimuth_angle': float(weather.sun_azimuth_angle),
                'wetness': float(weather.wetness),
                'wind_intensity': float(weather.wind_intensity)
            }
            results.append(weather_info)
        except Exception as e:
            print(f"[WARN]: Could not add weather info: {e}")
            
        return results
    
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
    
    def _get_points_in_bbox(self, relative_pos, relative_yaw, extent, lidar):
        """Count LiDAR points inside a bounding box"""
        try:
            # Transform LiDAR points to bbox coordinate frame
            cos_yaw = np.cos(-relative_yaw)
            sin_yaw = np.sin(-relative_yaw)
            rotation_matrix = np.array([[cos_yaw, -sin_yaw, 0],
                                       [sin_yaw, cos_yaw, 0],
                                       [0, 0, 1]])
            
            # Translate points relative to bbox center
            points = lidar[:, :3] - np.array(relative_pos)
            # Rotate points to bbox frame
            points = (rotation_matrix @ points.T).T
            
            # Count points inside bbox
            mask_x = np.abs(points[:, 0]) < extent[0]
            mask_y = np.abs(points[:, 1]) < extent[1]
            mask_z = np.abs(points[:, 2]) < extent[2]
            mask = mask_x & mask_y & mask_z
            
            return np.sum(mask)
        except Exception:
            return 0
    
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

        # Compute ego transformation matrix
        try:
            ego_matrix = transform.get_matrix()
        except:
            ego_matrix = [
                [1.0, 0.0, 0.0, float(transform.location.x)],
                [0.0, 1.0, 0.0, float(transform.location.y)],
                [0.0, 0.0, 1.0, float(transform.location.z)],
                [0.0, 0.0, 0.0, 1.0]
            ]

        # Route information
        route_original = getattr(self, '_route_points', [])
        route = list(route_original) if route_original else []
        
        target_point = route[0] if len(route) > 0 else [0.0, 0.0]
        target_point_next = route[1] if len(route) > 1 else target_point
        aim_wp = route[0] if len(route) > 0 else [0.0, 0.0]

        command = int(getattr(self, 'last_command', 4)) if hasattr(self, 'last_command') else 4
        next_command = int(getattr(self, 'next_command', command)) if hasattr(self, 'next_command') else command
        
        steer = float(control.steer)
        throttle = float(control.throttle)
        brake = bool(control.brake > 0.0)
        control_brake = bool(control.brake)
        
        angle = 0.0
        augmentation_rotation = 0.0
        augmentation_translation = 0.0
        
        changed_route = False
        speed_reduced_by_obj_type = None
        speed_reduced_by_obj_id = None
        speed_reduced_by_obj_distance = None
        
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
            'target_speed': 20.0,
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
        
        # Save measurements
        measurements_path = os.path.join(self.folderpath, 'measurements', f'{frame_num:04d}.json.gz')
        try:
            with gzip.open(measurements_path, 'wt', encoding='utf-8') as f:
                json.dump(measurements, f)
        except Exception as e:
            print(f"Error saving measurements: {e}")
        
        # Track GPS
        self._gps_trajectory.append([float(transform.location.x), float(transform.location.y)])
        
        # Use get_bounding_boxes() for enriched format
        boxes_data = self.get_bounding_boxes(lidar=None)
        
        # Save boxes
        boxes_path = os.path.join(self.folderpath, 'boxes', f'{frame_num:04d}.json.gz')
        try:
            with gzip.open(boxes_path, 'wt', encoding='utf-8') as f:
                json.dump(boxes_data, f)
        except Exception as e:
            print(f"[ERROR]: Error saving boxes: {e}")
        
        # Store minimal info for summary
        data_point = {
            'timestamp': time.time(),
            'frame': frame_num,
            'location': {'x': float(transform.location.x), 'y': float(transform.location.y), 'z': float(transform.location.z)},
            'rotation': {'pitch': float(transform.rotation.pitch), 'yaw': float(transform.rotation.yaw), 'roll': float(transform.rotation.roll)},
            'velocity': {'x': float(velocity.x), 'y': float(velocity.y), 'z': float(velocity.z), 'speed': speed},
            'control': {'throttle': float(control.throttle), 'steer': float(control.steer), 'brake': float(control.brake), 'hand_brake': control.hand_brake, 'reverse': control.reverse},
            'speed': speed,
            'collision': {'is_colliding': False, 'note': ''}
        }
        self.recording_data.append(data_point)
        self.frame_counter += 1


def main():
    print('\n')
    parser = argparse.ArgumentParser(description='Japanese-style autopilot driving in CARLA (v2 with enriched boxes)')
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
    # Print estimate
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
    
    print(f"\n__DATASET_PATH__={sim.folderpath}")

if __name__ == '__main__':
    main()
