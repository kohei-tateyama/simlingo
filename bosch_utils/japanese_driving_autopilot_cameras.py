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


# Import the parent class from the backup file
from bosch_utils.japanese_driving_autopilot_cameras_backup import JapaneseStyleAutopilot as JapaneseStyleAutopilotBase

class JapaneseStyleAutopilot(JapaneseStyleAutopilotBase):
    """Extended version with get_bounding_boxes() matching data_agent.py format"""
    
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
    
    def get_bounding_boxes(self, lidar=None):
        """Get bounding boxes matching data_agent.py output exactly"""
        results = []
        
        if not self.player_vehicle:
            return results
            
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
        
        # Count lanes to remove for opposite direction
        remove_lanes_for_lane_relative_to_ego = 1
        wp = ego_wp
        is_opposite = False
        while True:
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
        
        # Process vehicles
        actors = self.world.get_actors()
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
        
        # Scan left lanes
        temp_wp = ego_wp.get_left_lane()
        while temp_wp:
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
        
        # Scan right lanes
        temp_wp = ego_wp.get_right_lane()
        while temp_wp:
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
