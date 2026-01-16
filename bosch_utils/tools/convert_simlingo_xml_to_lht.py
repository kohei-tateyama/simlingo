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
    root = tree.get_root()

    print("[INFO] Converting routes Left-Hand Traffic... Once per file ...")
    print(f"[INFO] Connecting to CARLA at 0.9.16 {host}:{port}...")
    print(f"[INFO] Reading from RHT in {xml_path}...")

    for route in root.findall('route'):
        for waypoint in route.findall('.//waypoint'):
            # Get old RHT coordinates
            x = float(waypoint.get('x'))
            y = float(waypoint.get('y'))
            z = float(waypoint.get('z'))
            
            # Find the nearest waypoint on the map
            loc = carla.Location(x, y, z)
            current_wp = carla_map.get_waypoint(loc)
            
            # 0.9.16 Magic: Get the waypoint in the left-hand lane
            lht_wp = current_wp.get_left_lane()
            
            if lht_wp:
                # Update the XML with the new "Left-Lane" coordinates
                waypoint.set('x', str(round(lht_wp.transform.location.x, 3)))
                waypoint.set('y', str(round(lht_wp.transform.location.y, 3)))
                waypoint.set('z', str(round(lht_wp.transform.location.z, 3)))
                # Update Yaw to face the correct direction
                waypoint.set('yaw', str(round(lht_wp.transform.rotation.yaw, 3)))

    # 3. Save the new LHT-ready XML
    tree.write(output_path)
    print(f"[INFO] Saved to LHF in {output_path}")

if __name__ == "__main__":
    name_folder = "/workspace/simlingo/leaderboard/data/" 
    name_files = ["routes_devtest", "bench2drive220", "routes_validation", "routes_training"]
    format = ".xml"
    new = "_LHT" 
    
    for i in name_files:
        shift_route_to_lht(name_folder + i + format, name_folder + i + new + format)
    
