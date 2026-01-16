import carla
import xml.etree.ElementTree as ET

def shift_route_to_lht(xml_path, output_path, host='127.0.0.1', port=2000):
    # 1. Connect to CARLA 0.9.16
    client = carla.Client(host, port)
    client.set_timeout(10.0)
    world = client.get_world()
    carla_map = world.get_map()

    # 2. Parse your bench2drive XML
    tree = ET.parse(xml_path)
    root = tree.getroot()

    print("[INFO] Converting routes Left-Hand Traffic... Once per file...")
    print(f"[INFO] Connecting to CARLA at 0.9.16 {host}:{port}...")
    print(f"[INFO] Reading from RHT in {xml_path}...")

    # The routes files usually contain <waypoints><position ... /></waypoints>
    # Accept both 'position' and 'waypoint' element names for compatibility.
    for route in root.findall('.//route'):
        # find all position-like elements under this route
        positions = route.findall('.//position')
        if not positions:
            positions = route.findall('.//waypoint')

        for waypoint in positions:
            # Get old RHT coordinates
            try:
                x = float(waypoint.get('x'))
                y = float(waypoint.get('y'))
                z = float(waypoint.get('z'))
            except Exception:
                print(f"[WARNING] Skipping waypoint without numeric coordinates: {ET.tostring(waypoint, encoding='unicode')}")
                continue

            # Find the nearest waypoint on the map
            loc = carla.Location(x, y, z)
            try:
                current_wp = carla_map.get_waypoint(loc)
            except Exception as e:
                print(f"[WARNING] Could not get waypoint for loc ({x},{y},{z}): {e}")
                continue

            # Prefer CARLA API method if available
            lht_wp = None
            if hasattr(current_wp, 'get_left_lane'):
                try:
                    lht_wp = current_wp.get_left_lane()
                except Exception:
                    lht_wp = None

            # If CARLA didn't provide a left-lane waypoint, warn and skip
            if lht_wp is None:
                print(f"[WARNING] No left-lane waypoint found for ({x:.3f},{y:.3f}) - leaving original coords")
                continue

            # Update the XML with the new "Left-Lane" coordinates
            waypoint.set('x', str(round(lht_wp.transform.location.x, 3)))
            waypoint.set('y', str(round(lht_wp.transform.location.y, 3)))
            waypoint.set('z', str(round(lht_wp.transform.location.z, 3)))
            # Update Yaw if present in target waypoint
            try:
                yaw_val = round(lht_wp.transform.rotation.yaw, 3)
                waypoint.set('yaw', str(yaw_val))
            except Exception:
                pass

    # 3. Save the new LHT-ready XML (write declaration and UTF-8)
    tree.write(output_path, encoding='utf-8', xml_declaration=True)
    print(f"[INFO] Saved to LHT in {output_path}")

if __name__ == "__main__":
    name_folder = "/workspace/simlingo/leaderboard/data/" 
    name_files = ["routes_devtest", "bench2drive220", "routes_validation", "routes_training"]
    format = ".xml"
    new = "_LHT" 
    
    for i in name_files:
        shift_route_to_lht(name_folder + i + format, name_folder + i + new + format)
    
