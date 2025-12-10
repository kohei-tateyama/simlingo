import carla
import numpy as np
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime
import time
import argparse
import os

RECORDING_OUTPUT_DIR = "/workspace/simlingo/recording_japan_xml"

# # Highway route (default)
# python japanese_driving_autopilot.py --autopilot --route highway
# # Urban streets
# python japanese_driving_autopilot.py --autopilot --route urban
# # Simple straight path
# python japanese_driving_autopilot.py --autopilot --route simple

# python japanese_driving_autopilot.py --autopilot --duration 300 --route highway

class JapaneseStyleAutopilot:
    def __init__(self, autopilot=False, duration=60, route_type='highway'):
        # Connect to CARLA
        self.client = carla.Client('localhost', 2000)
        # Allow longer timeouts for slower hosts
        self.client.set_timeout(30.0)

        print("Selecting world on server (prefer current world; use --force-load to override)...")

        # If a world is already loaded on the server, prefer using it to avoid heavy reloads
        try:
            current_world = self.client.get_world()
            current_map_name = getattr(current_world.get_map(), 'name', '')
            if current_map_name:
                print(f"  Server already has map loaded: {current_map_name} — using it")
                self.world = current_world
                time.sleep(1)
                skip_load = True
            else:
                skip_load = False
        except Exception:
            skip_load = False

        # If user explicitly wants to force a map load, set FORCE_LOAD env var or pass --force-load
        FORCE_LOAD = False

        # If skip_load is False, attempt to load Town13 or fall back to server-reported maps
        if not skip_load and not FORCE_LOAD:
            try:
                available_maps = self.client.get_available_maps()
            except Exception:
                available_maps = []

            preferred_map = None
            for m in available_maps:
                if 'Town13' in m:
                    preferred_map = m
                    break

            if preferred_map is not None:
                map_to_load = preferred_map
                print(f"  Found server map: {preferred_map} — will attempt to load it")
            elif len(available_maps) > 0:
                map_to_load = available_maps[0]
                print(f"  Town13 not found on server — would load {map_to_load} if needed")
            else:
                map_to_load = 'Town13'
                print("  No maps reported by server; would try short name 'Town13' if forced")

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
        
    def setup_left_hand_traffic(self):
        """Configure traffic manager for left-hand traffic (Japan/UK)"""
        print("Configuring Japanese-style (left-hand) traffic...")
        
        self.traffic_manager.set_global_distance_to_leading_vehicle(2.5)
        self.traffic_manager.global_lane_offset = -1.5
        
        # Spawn NPC vehicles
        self.spawn_npc_vehicles(num_vehicles=30)
        
    def spawn_npc_vehicles(self, num_vehicles=30):
        """Spawn NPC vehicles following Japanese traffic rules"""
        blueprint_library = self.world.get_blueprint_library()
        spawn_points = self.world.get_map().get_spawn_points()
        
        print(f"Spawning {num_vehicles} NPC vehicles...")
        
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
                
        print("NPC vehicles spawned!")
        
    def get_predefined_route(self):
        """Get predefined waypoints for different route types in Town13"""
        map = self.world.get_map()
        spawn_points = map.get_spawn_points()
        
        routes = {
            'highway': {
                'description': 'Highway loop in Town13',
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
                'description': 'Urban streets in Town13',
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
        print(f"Route: {route_config['description']}")
        
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
        print(f"Player vehicle spawned at {spawn_point.location}")
        
        if self.autopilot:
            # Enable autopilot with Japanese traffic settings
            self.player_vehicle.set_autopilot(True, self.traffic_manager.get_port())
            self.traffic_manager.vehicle_lane_offset(self.player_vehicle, -1.5)
            self.traffic_manager.ignore_lights_percentage(self.player_vehicle, 0)
            
            # Optional: Set destination for route following
            if route_waypoints:
                self.traffic_manager.set_path(self.player_vehicle, 
                                             [wp.transform.location for wp in route_waypoints])
            
            print("🤖 Autopilot enabled (Japanese-style left-hand traffic)")
        else:
            print("⚠️  Manual control mode (run japanese_driving_town13.py instead)")
            
    def record_data(self):
        """Record vehicle data for XML export"""
        if not self.player_vehicle:
            return
            
        transform = self.player_vehicle.get_transform()
        velocity = self.player_vehicle.get_velocity()
        control = self.player_vehicle.get_control()
        
        data_point = {
            'timestamp': time.time(),
            'location': {
                'x': transform.location.x,
                'y': transform.location.y,
                'z': transform.location.z
            },
            'rotation': {
                'pitch': transform.rotation.pitch,
                'yaw': transform.rotation.yaw,
                'roll': transform.rotation.roll
            },
            'velocity': {
                'x': velocity.x,
                'y': velocity.y,
                'z': velocity.z,
                'speed': np.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2) * 3.6
            },
            'control': {
                'throttle': control.throttle,
                'steer': control.steer,
                'brake': control.brake,
                'hand_brake': control.hand_brake,
                'reverse': control.reverse
            }
        }
        
        self.recording_data.append(data_point)
        
    def save_to_xml(self, filename=None):
        """Save recorded data to XML file"""
        if not self.recording_data:
            print("No data to save!")
            return
        # Ensure output directory exists
        os.makedirs(RECORDING_OUTPUT_DIR, exist_ok=True)

        if filename is None:
            filename = f"autopilot_japanese_{self.route_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xml"
            filename = os.path.join(RECORDING_OUTPUT_DIR, filename)
        else:
            # If a relative filename is provided, place it into the recording dir
            if not os.path.isabs(filename):
                filename = os.path.join(RECORDING_OUTPUT_DIR, filename)
        
        root = ET.Element('DrivingSession')
        root.set('map', 'Town13')
        root.set('traffic_style', 'Japanese (Left-hand)')
        root.set('mode', 'Autopilot' if self.autopilot else 'Manual')
        root.set('route_type', self.route_type)
        root.set('total_frames', str(len(self.recording_data)))
        root.set('duration_seconds', str(self.duration))
        
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
        
        xml_str = minidom.parseString(ET.tostring(root)).toprettyxml(indent="  ")
        
        with open(filename, 'w') as f:
            f.write(xml_str)
            
        print(f"Data saved to {filename} ({len(self.recording_data)} frames)")
        
    def run(self):
        """Run autopilot simulation"""
        try:
            self.spawn_player_vehicle()
            
            print("\n" + "="*60)
            print("AUTOPILOT MODE - Japanese-Style Driving")
            print("="*60)
            print(f"Map: Town13")
            print(f"Route: {self.route_type}")
            print(f"Duration: {self.duration} seconds")
            print(f"Recording: Enabled")
            print("="*60 + "\n")
            
            start_time = time.time()
            frame_count = 0
            
            # Main loop
            while (time.time() - start_time) < self.duration:
                # Record data at 20 Hz
                if frame_count % 3 == 0:  # ~20 FPS from 60 Hz server
                    self.record_data()
                
                # Print progress every 5 seconds
                elapsed = time.time() - start_time
                if int(elapsed) % 5 == 0 and frame_count % 100 == 0:
                    speed = self.recording_data[-1]['velocity']['speed'] if self.recording_data else 0
                    print(f"{int(elapsed)}s / {self.duration}s | "
                          f"Frames: {len(self.recording_data)} | "
                          f"Speed: {speed:.1f} km/h")
                
                frame_count += 1
                time.sleep(0.05)  # 20 Hz
                
            print(f"\nSimulation completed!")
            print(f"Total frames recorded: {len(self.recording_data)}")
            
            # Save data
            self.save_to_xml()
            
        finally:
            self.cleanup()
            
    def cleanup(self):
        """Clean up resources"""
        print("\nCleaning up...")
        
        if self.player_vehicle:
            self.player_vehicle.destroy()
            
        print("Done!")

def main():
    parser = argparse.ArgumentParser(description='Japanese-style autopilot driving in CARLA Town13')
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