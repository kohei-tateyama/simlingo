"""
Generate LHT routes for TownXX using spawn points
Compatible with CARLA 0.9.16 headless setup
"""
import sys
import os
import time
import random
import xml.etree.ElementTree as ET

# Set up CARLA Python API path (same as your bash script)
CARLA_API_BASE = "/workspace/carla0916/PythonAPI/carla/dist/carla_0916_lib"
CARLA_SRC = "/workspace/carla0916/PythonAPI/carla"

# Clean sys.path and add CARLA
sys.path = [p for p in sys.path if not ('site-packages' in p and 'carla' in p.lower())]
if CARLA_API_BASE not in sys.path:
    sys.path.insert(0, CARLA_API_BASE)

import carla

def generate_town_routes(num_routes=20, min_distance=100, town="Town06", output_file=None):
    """
    Generate routes for TownXX using LHT spawn points (negative lane IDs)
    
    Args:
        num_routes: Number of routes to generate
        min_distance: Minimum distance between start and end (meters)
        output_file: Path to save XML (default: auto-generate name)
    """
    
    print("[INFO] Connecting to CARLA server...")
    
    # Connect to CARLA (should already be running from your bash script)
    client = carla.Client('localhost', 2000)
    client.set_timeout(10.0)
    
    print(f"[INFO] Loading {town}...")
    world = client.load_world(town)
    time.sleep(3)  # Wait for map to load
    
    carla_map = world.get_map()
    
    # Get all spawn points
    spawn_points = carla_map.get_spawn_points()
    print(f"[INFO] Found {len(spawn_points)} total spawn points")
    
    # Filter for LHT lanes (negative lane IDs)
    lht_spawns = []
    rht_spawns = []
    
    for sp in spawn_points:
        wp = carla_map.get_waypoint(sp.location, project_to_road=True, lane_type=carla.LaneType.Driving)
        if wp:
            if wp.lane_id < 0:
                lht_spawns.append(sp)
            else:
                rht_spawns.append(sp)
    
    print(f"[INFO] Found {len(lht_spawns)} LHT spawn points (negative lane IDs)")
    print(f"[INFO] Found {len(rht_spawns)} RHT spawn points (positive lane IDs)")
    
    if len(lht_spawns) < 2:
        print("[ERROR] Not enough LHT spawn points to generate routes!")
        return False
    
    # Generate routes
    routes_root = ET.Element('routes')
    
    successful_routes = 0
    attempts = 0
    max_attempts = num_routes * 3  # Allow some failed attempts
    
    while successful_routes < num_routes and attempts < max_attempts:
        attempts += 1
        
        # Pick random start and end from LHT spawns
        start = random.choice(lht_spawns)
        end = random.choice(lht_spawns)
        
        # Ensure minimum distance
        distance = start.location.distance(end.location)
        if distance < min_distance:
            continue
        
        # Create route element
        route = ET.SubElement(routes_root, 'route', 
                            id=str(successful_routes), 
                            town=town)
        
        # Add random weather
        cloudiness = random.uniform(0, 50)
        sun_altitude = random.uniform(30, 90)
        
        weather = ET.SubElement(route, 'weather',
                              cloudiness=f'{cloudiness:.1f}',
                              precipitation='0',
                              precipitation_deposits='0',
                              wind_intensity='10',
                              sun_azimuth_angle='70',
                              sun_altitude_angle=f'{sun_altitude:.1f}',
                              fog_density='0',
                              fog_distance='0',
                              wetness='0')
        
        # Add waypoints
        waypoints = ET.SubElement(route, 'waypoints')
        
        start_pos = ET.SubElement(waypoints, 'position',
                                x=f"{start.location.x:.2f}",
                                y=f"{start.location.y:.2f}",
                                z=f"{start.location.z:.2f}")
        
        end_pos = ET.SubElement(waypoints, 'position',
                              x=f"{end.location.x:.2f}",
                              y=f"{end.location.y:.2f}",
                              z=f"{end.location.z:.2f}")
        
        successful_routes += 1
        print(f"[INFO] Generated route {successful_routes}/{num_routes} (distance: {distance:.1f}m)")
    
    if successful_routes == 0:
        print("[ERROR] Failed to generate any routes!")
        return False
    
    # Auto-generate filename if not provided
    if output_file is None:
        output_file = f'/workspace/simlingo/leaderboard21/data/routes_{town}_lht_{num_routes}.xml'
    
    # Pretty-print XML
    indent_xml(routes_root)
    
    # Save
    tree = ET.ElementTree(routes_root)
    tree.write(output_file, encoding='utf-8', xml_declaration=True)
    
    print(f"\n[SUCCESS] Generated {successful_routes} routes")
    print(f"[SUCCESS] Saved to: {output_file}")
    print(f"\nTo use these routes:")
    print(f'  export ROUTES="{output_file}"')
    print(f'  export FORCE_TOWN="{town}"')
    print(f'  export ROUTES_SUBSET=""  # Use all routes')
    
    return True

def indent_xml(elem, level=0):
    """Pretty-print XML with indentation"""
    i = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "  "
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for child in elem:
            indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i

if __name__ == '__main__':
    import argparse
    town = "Town06"
    parser = argparse.ArgumentParser(description='Generate LHT routes for town')
    parser.add_argument('--num-routes', type=int, default=20,
                       help='Number of routes to generate (default: 20)')
    parser.add_argument('--min-distance', type=float, default=100,
                       help='Minimum distance between start/end in meters (default: 100)')
    parser.add_argument('--output', type=str, default=None,
                       help='Output XML file path (default: auto-generate)')
    
    args = parser.parse_args()
    
    print("=" * 70)
    print(f"{town} LHT Route Generator for CARLA 0.9.16")
    print("=" * 70)
    
    success = generate_town_routes(
        num_routes=args.num_routes,
        min_distance=args.min_distance,
        output_file=args.output
    )
    
    sys.exit(0 if success else 1)