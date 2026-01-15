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

    print("Converting routes to Left-Hand Traffic...")

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
    print(f"Success! Saved to {output_path}")

if __name__ == "__main__":
    shift_route_to_lht('bench2drive220.xml', 'bench2drive220_LHT.xml')