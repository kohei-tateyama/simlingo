"""
Convert CARLA route XML files from Right-Hand Traffic (RHT) to Left-Hand Traffic (LHT).

This script performs a comprehensive conversion:
1. Waypoint Conversion: Shifts all route waypoints from right lanes to left lanes
2. Scenario Conversion: Moves scenario trigger points to LHT positions
3. Metadata Addition: Adds traffic_rules='left_hand' and lane_offset='-3.5' to XML root

The metadata is read by the leaderboard/scenario_runner to configure CARLA's Traffic Manager:
- traffic_manager.global_lane_offset = -3.5 (shifts all NPC traffic to left lanes)
- Ensures both ego vehicle and NPC vehicles follow left-hand traffic rules

Usage:
    python convert_simlingo_xml_to_lht.py
    
    The script will:
    - Start a CARLA server if not already running
    - Convert all XML files in leaderboard/data/ (routes_training, routes_validation, etc.)
    - Output files with '_2_LHT' suffix
    
Requirements:
    - CARLA 0.9.16 server running or Docker available
    - Python CARLA API installed
    - Network access to CARLA server (default: localhost:2000)
"""

import carla
import xml.etree.ElementTree as ET
import time
import math
import os
import sys
import subprocess
import shlex

PRINT_NUM = 100

def wait_for_carla(host='127.0.0.1', port=2000, timeout=120, interval=2.0):
    """Wait for CARLA server to be ready and return a connected client.
    Raises RuntimeError if not available within timeout seconds.
    """
    client = carla.Client(host, port)
    deadline = time.time() + float(timeout)
    last_exc = None
    while True:
        try:
            client.set_timeout(10.0)
            world = client.get_world()
            # Access map to ensure server is responsive
            _ = world.get_map()
            return client
        except Exception as e:
            last_exc = e
            if time.time() > deadline:
                raise RuntimeError(f"Could not connect to CARLA at {host}:{port} within {timeout}s: {e}")
            time.sleep(interval)


def shift_route_to_lht(xml_path, output_path, host='127.0.0.1', port=2000, wait_timeout=120):
    """
    Convert RHT (Right-Hand Traffic) routes to LHT (Left-Hand Traffic).
    
    This function:
    1. Connects to CARLA server and loads the necessary maps
    2. Shifts all waypoints to the left lane (LHT position)
    3. Updates scenario trigger points to LHT positions
    4. Adds LHT metadata to the XML root for runtime configuration
    
    Args:
        xml_path: Path to input RHT routes XML file
        output_path: Path to output LHT routes XML file
        host: CARLA server host
        port: CARLA server port
        wait_timeout: Timeout for CARLA server connection
    """
    # 1. Connect to CARLA 0.9.16 (wait for it to be ready)
    client = wait_for_carla(host=host, port=port, timeout=wait_timeout)
    client.set_timeout(30.0)
    world = client.get_world()
    carla_map = world.get_map()

    # 2. Parse your bench2drive XML
    tree = ET.parse(xml_path)
    root = tree.getroot()

    print("[INFO] Converting routes from Right-Hand Traffic to Left-Hand Traffic...")
    print(f"[INFO] Connecting to CARLA 0.9.16 at {host}:{port}...")
    print(f"[INFO] Reading from RHT routes in {xml_path}...")

    # Collect unique towns referenced by the routes file and preload them once
    towns_to_preload = set()
    for r in root.findall('.//route'):
        town_name = r.get('town') or r.get('map')
        if town_name:
            towns_to_preload.add(town_name)

    if towns_to_preload:
        print(f"[INFO] Preloading {len(towns_to_preload)} unique towns referenced by the routes file: {sorted(towns_to_preload)}")
        available_maps = []
        try:
            available_maps = client.get_available_maps()
        except Exception:
            available_maps = []

        for route_town in sorted(towns_to_preload):
            try:
                # find matching full map path
                target_map_full = None
                for mp in available_maps:
                    if mp.split('/')[-1] == route_town:
                        target_map_full = mp
                        break

                if not target_map_full:
                    # try case-insensitive or substring match
                    for mp in available_maps:
                        name = mp.split('/')[-1]
                        if route_town.lower() in name.lower():
                            target_map_full = mp
                            break

                # fallback to local content folder
                if not target_map_full:
                    local_maps_root = '/workspace/carla0916/CarlaUE4/Content/Carla/Maps'
                    local_candidate = f"{local_maps_root}/{route_town}"
                    if os.path.exists(local_candidate):
                        candidate_path = f"/Game/Carla/Maps/{route_town}"
                        print(f"[INFO] Found local map folder at {local_candidate}; will try {candidate_path} as load target")
                        target_map_full = candidate_path

                if not target_map_full:
                    print(f"[WARNING] Map '{route_town}' not found among available maps or local content; skipping preload")
                    continue

                # Load the world (with extended timeout) and refresh map
                client.set_timeout(180.0)
                start = time.time()
                world = client.load_world(target_map_full)
                # Immediately refresh world and carla_map after loading
                try:
                    world = client.get_world()
                    carla_map = world.get_map()
                except Exception:
                    pass
                elapsed = time.time() - start
                print(f"[INFO] ✓ Preloaded {route_town} via {target_map_full} in {elapsed:.1f}s")
                client.set_timeout(30.0)
            except Exception as e:
                print(f"[WARNING] Failed to preload {route_town}: {e}")

        # Refresh carla_map to current world
        try:
            carla_map = client.get_world().get_map()
        except Exception:
            pass

    # The routes files usually contain <waypoints><position ... /></waypoints>
    # We'll group routes by town so we can load each town once and convert all of its routes
    routes_by_town = {}
    routes_without_town = []
    for route in root.findall('.//route'):
        town = route.get('town') or route.get('map')
        if town:
            routes_by_town.setdefault(town, []).append(route)
        else:
            routes_without_town.append(route)

    # Helper to resolve and load a town once
    def _resolve_and_load_town(route_town):
        available_maps = []
        try:
            available_maps = client.get_available_maps()
        except Exception:
            available_maps = []

        target_map_full = None
        for mp in available_maps:
            if mp.split('/')[-1] == route_town:
                target_map_full = mp
                break
        if not target_map_full:
            for mp in available_maps:
                name = mp.split('/')[-1]
                if route_town.lower() in name.lower():
                    target_map_full = mp
                    break

        if not target_map_full:
            local_maps_root = '/workspace/carla0916/CarlaUE4/Content/Carla/Maps'
            local_candidate = f"{local_maps_root}/{route_town}"
            if os.path.exists(local_candidate):
                candidate_path = f"/Game/Carla/Maps/{route_town}"
                print(f"[INFO] Found local map folder at {local_candidate}; will try {candidate_path} as load target")
                target_map_full = candidate_path

        if not target_map_full:
            print(f"[WARNING] Map '{route_town}' not found among available maps or local content; skipping this town")
            return None

        try:
            # If current world already matches, skip reload
            try:
                cur_world = client.get_world()
                cur_map = cur_world.get_map()
                if cur_map and cur_map.name and route_town.lower() in cur_map.name.lower():
                    print(f"[INFO] Town {route_town} already loaded; skipping load")
                    return cur_map
            except Exception:
                pass

            client.set_timeout(180.0)
            start = time.time()
            world = client.load_world(target_map_full)
            # Immediately refresh world and carla_map after loading
            try:
                world = client.get_world()
                carla_map_local = world.get_map()
            except Exception:
                carla_map_local = None
            elapsed = time.time() - start
            print(f"[INFO] ✓ Loaded {route_town} via {target_map_full} in {elapsed:.1f}s")
            client.set_timeout(30.0)
            return carla_map_local
        except Exception as e:
            print(f"[WARNING] Failed to load map {target_map_full}: {e}")
            return None

    # Track diagnostics: counts of lateral shifts per town and overall
    diagnostics = { 'per_town': {}, 'total': {'moved_left': 0, 'moved_right': 0, 'unchanged': 0} }

    # Process each known town: load town once, then convert all its routes
    for town in sorted(routes_by_town.keys()):
        print(f"[INFO] Processing {len(routes_by_town[town])} route(s) for town {town}")
        carla_map = _resolve_and_load_town(town)
        if carla_map is None:
            print(f"[WARNING] Skipping routes for town {town} because map could not be loaded")
            continue

        diagnostics['per_town'][town] = {'moved_left': 0, 'moved_right': 0, 'unchanged': 0}

        for route in routes_by_town[town]:
            # Convert waypoints
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

                # Find the nearest waypoint on the map using robust projection
                loc = carla.Location(x, y, z)
                try:
                    current_wp = carla_map.get_waypoint(loc, project_to_road=True, lane_type=carla.LaneType.Any)
                    if current_wp is None:
                        raise RuntimeError('get_waypoint returned None')
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

                # If CARLA can't provide a left-lane waypoint, compute lateral coordinates directly
                if lht_wp is None:
                    try:
                        yaw_deg = current_wp.transform.rotation.yaw
                        yaw_rad = math.radians(yaw_deg)
                        left_x = -math.sin(yaw_rad)
                        left_y = math.cos(yaw_rad)
                        lane_offset = 3.5  # conservative lane half-width in meters
                        new_x = current_wp.transform.location.x + left_x * lane_offset
                        new_y = current_wp.transform.location.y + left_y * lane_offset
                        new_z = current_wp.transform.location.z
                        # We'll not create a dummy waypoint; instead use these coords and preserve yaw
                        # Build a simple namespace-like object for rotation access
                        class _CoordOnly:
                            class transform:
                                location = carla.Location(new_x, new_y, new_z)
                                rotation = current_wp.transform.rotation
                        lht_wp = _CoordOnly()
                    except Exception as e:
                        print(f"[WARNING] No left-lane waypoint found and lateral fallback failed for ({x:.3f},{y:.3f}): {e} - leaving original coords")
                        continue

                # Update the XML with the new "Left-Lane" coordinates and record the lateral shift
                try:
                    lx = getattr(lht_wp.transform.location, 'x')
                    ly = getattr(lht_wp.transform.location, 'y')
                    lz = getattr(lht_wp.transform.location, 'z')
                    # Compute lateral displacement in the map plane (signed by cross product)
                    # We'll compute a simple signed lateral shift by projecting the delta onto left vector
                    dx = lx - current_wp.transform.location.x
                    dy = ly - current_wp.transform.location.y
                    yaw_deg = current_wp.transform.rotation.yaw
                    yaw_rad = math.radians(yaw_deg)
                    left_x = -math.sin(yaw_rad)
                    left_y = math.cos(yaw_rad)
                    lateral = dx * left_x + dy * left_y

                    waypoint.set('x', str(round(lx, 3)))
                    waypoint.set('y', str(round(ly, 3)))
                    waypoint.set('z', str(round(lz, 3)))

                    if lateral < -0.001:
                        diagnostics['per_town'][town]['moved_right'] += 1
                        diagnostics['total']['moved_right'] += 1
                    elif lateral > 0.001:
                        diagnostics['per_town'][town]['moved_left'] += 1
                        diagnostics['total']['moved_left'] += 1
                    else:
                        diagnostics['per_town'][town]['unchanged'] += 1
                        diagnostics['total']['unchanged'] += 1
                except Exception:
                    waypoint.set('x', str(round(current_wp.transform.location.x, 3)))
                    waypoint.set('y', str(round(current_wp.transform.location.y, 3)))
                    waypoint.set('z', str(round(current_wp.transform.location.z, 3)))
                    diagnostics['per_town'][town]['unchanged'] += 1
                    diagnostics['total']['unchanged'] += 1

                # Update Yaw using the target left-lane waypoint rotation when available
                try:
                    if hasattr(lht_wp.transform, 'rotation'):
                        yaw_val = round(lht_wp.transform.rotation.yaw, 3)
                    else:
                        yaw_val = round(current_wp.transform.rotation.yaw, 3)
                    waypoint.set('yaw', str(yaw_val))
                    # Log if yaw changed significantly (helps debug handedness)
                    try:
                        orig_yaw = round(current_wp.transform.rotation.yaw, 3)
                        dyaw = abs(((yaw_val - orig_yaw + 180) % 360) - 180)
                        # if dyaw > 1.0:
                        #     print(f"[DEBUG] Yaw changed for waypoint: orig={orig_yaw}, new={yaw_val}, diff={dyaw}")
                    except Exception:
                        pass
                except Exception:
                    pass
            
            # Also convert scenario trigger points to LHT
            scenarios = route.findall('.//scenario')
            for scenario in scenarios:
                trigger_points = scenario.findall('.//trigger_point')
                for trigger in trigger_points:
                    try:
                        x = float(trigger.get('x'))
                        y = float(trigger.get('y'))
                        z = float(trigger.get('z'))
                    except Exception:
                        continue
                    
                    loc = carla.Location(x, y, z)
                    try:
                        current_wp = carla_map.get_waypoint(loc, project_to_road=True, lane_type=carla.LaneType.Any)
                        if current_wp is None:
                            continue
                    except Exception:
                        continue
                    
                    lht_wp = None
                    if hasattr(current_wp, 'get_left_lane'):
                        try:
                            lht_wp = current_wp.get_left_lane()
                        except Exception:
                            lht_wp = None
                    
                    if lht_wp is None:
                        try:
                            yaw_deg = current_wp.transform.rotation.yaw
                            yaw_rad = math.radians(yaw_deg)
                            left_x = -math.sin(yaw_rad)
                            left_y = math.cos(yaw_rad)
                            lane_offset = 3.5
                            new_x = current_wp.transform.location.x + left_x * lane_offset
                            new_y = current_wp.transform.location.y + left_y * lane_offset
                            new_z = current_wp.transform.location.z
                            class _CoordOnly:
                                class transform:
                                    location = carla.Location(new_x, new_y, new_z)
                                    rotation = current_wp.transform.rotation
                            lht_wp = _CoordOnly()
                        except Exception:
                            continue
                    
                    try:
                        lx = getattr(lht_wp.transform.location, 'x')
                        ly = getattr(lht_wp.transform.location, 'y')
                        lz = getattr(lht_wp.transform.location, 'z')
                        trigger.set('x', str(round(lx, 3)))
                        trigger.set('y', str(round(ly, 3)))
                        trigger.set('z', str(round(lz, 3)))
                        
                        if hasattr(lht_wp.transform, 'rotation'):
                            yaw_val = round(lht_wp.transform.rotation.yaw, 3)
                            trigger.set('yaw', str(yaw_val))
                    except Exception:
                        pass

    # Lastly, process routes that did not declare a town (attempt with current carla_map)
    if routes_without_town:
        print(f"[INFO] Processing {len(routes_without_town)} route(s) without an explicit town (using current world)")
        diagnostics['per_town'].setdefault('__no_town__', {'moved_left': 0, 'moved_right': 0, 'unchanged': 0})
        for route in routes_without_town:
            positions = route.findall('.//position')
            if not positions:
                positions = route.findall('.//waypoint')

            for waypoint in positions:
                try:
                    x = float(waypoint.get('x'))
                    y = float(waypoint.get('y'))
                    z = float(waypoint.get('z'))
                except Exception:
                    print(f"[WARNING] Skipping waypoint without numeric coordinates: {ET.tostring(waypoint, encoding='unicode')}")
                    continue

                loc = carla.Location(x, y, z)
                try:
                    current_wp = carla_map.get_waypoint(loc, project_to_road=True, lane_type=carla.LaneType.Any)
                    if current_wp is None:
                        raise RuntimeError('get_waypoint returned None')
                except Exception as e:
                    print(f"[WARNING] Could not get waypoint for loc ({x},{y},{z}): {e}")
                    continue

                lht_wp = None
                if hasattr(current_wp, 'get_left_lane'):
                    try:
                        lht_wp = current_wp.get_left_lane()
                    except Exception:
                        lht_wp = None

                if lht_wp is None:
                    try:
                        yaw_deg = current_wp.transform.rotation.yaw
                        yaw_rad = math.radians(yaw_deg)
                        left_x = -math.sin(yaw_rad)
                        left_y = math.cos(yaw_rad)
                        lane_offset = 3.5
                        new_x = current_wp.transform.location.x + left_x * lane_offset
                        new_y = current_wp.transform.location.y + left_y * lane_offset
                        new_z = current_wp.transform.location.z
                        class _CoordOnly:
                            class transform:
                                location = carla.Location(new_x, new_y, new_z)
                                rotation = current_wp.transform.rotation
                        lht_wp = _CoordOnly()
                    except Exception as e:
                        print(f"[WARNING] No left-lane waypoint found and lateral fallback failed for ({x:.3f},{y:.3f}): {e} - leaving original coords")
                        continue


                try:
                    lx = getattr(lht_wp.transform.location, 'x')
                    ly = getattr(lht_wp.transform.location, 'y')
                    lz = getattr(lht_wp.transform.location, 'z')
                    dx = lx - current_wp.transform.location.x
                    dy = ly - current_wp.transform.location.y
                    yaw_deg = current_wp.transform.rotation.yaw
                    yaw_rad = math.radians(yaw_deg)
                    left_x = -math.sin(yaw_rad)
                    left_y = math.cos(yaw_rad)
                    lateral = dx * left_x + dy * left_y

                    waypoint.set('x', str(round(lx, 3)))
                    waypoint.set('y', str(round(ly, 3)))
                    waypoint.set('z', str(round(lz, 3)))

                    if lateral < -0.001:
                        diagnostics['per_town']['__no_town__']['moved_right'] += 1
                        diagnostics['total']['moved_right'] += 1
                    elif lateral > 0.001:
                        diagnostics['per_town']['__no_town__']['moved_left'] += 1
                        diagnostics['total']['moved_left'] += 1
                    else:
                        diagnostics['per_town']['__no_town__']['unchanged'] += 1
                        diagnostics['total']['unchanged'] += 1
                except Exception:
                    waypoint.set('x', str(round(current_wp.transform.location.x, 3)))
                    waypoint.set('y', str(round(current_wp.transform.location.y, 3)))
                    waypoint.set('z', str(round(current_wp.transform.location.z, 3)))
                    diagnostics['per_town']['__no_town__']['unchanged'] += 1
                    diagnostics['total']['unchanged'] += 1

                try:
                    if hasattr(lht_wp.transform, 'rotation'):
                        yaw_val = round(lht_wp.transform.rotation.yaw, 3)
                    else:
                        yaw_val = round(current_wp.transform.rotation.yaw, 3)
                    waypoint.set('yaw', str(yaw_val))
                    try:
                        orig_yaw = round(current_wp.transform.rotation.yaw, 3)
                        dyaw = abs(((yaw_val - orig_yaw + 180) % 360) - 180)
                        if dyaw > 1.0:
                            print(f"[DEBUG] Yaw changed for waypoint (no-town block): orig={orig_yaw}, new={yaw_val}, diff={dyaw}")
                    except Exception:
                        pass
                except Exception:
                    pass

    # 3. Add left-hand traffic metadata to root element to signal LHT mode
    root.set('traffic_rules', 'left_hand')
    root.set('lane_offset', '-3.5')  # Negative offset for left-hand traffic
    
    # 4. Save the new LHT-ready XML (write declaration and UTF-8)
    tree.write(output_path, encoding='utf-8', xml_declaration=True)
    print(f"[INFO] Saved to LHT in {output_path}")

    # Print diagnostic summary
    print("[INFO] Conversion diagnostics summary:")
    for t, stats in diagnostics['per_town'].items():
        print(f"  - {t}: left={stats['moved_left']}, right={stats['moved_right']}, unchanged={stats['unchanged']}")
    tot = diagnostics['total']
    print(f"  Total: left={tot['moved_left']}, right={tot['moved_right']}, unchanged={tot['unchanged']}")
    print(f"[INFO] Added LHT metadata: traffic_rules='left_hand', lane_offset='-3.5'")

if __name__ == "__main__":
    name_folder = "/workspace/simlingo/leaderboard/data/" 
    name_files = ["routes_devtest", "bench2drive220", "routes_validation", "routes_training"]
    format = ".xml"
    new = "_LHT" 
    
    # If CARLA is not reachable, do not attempt to auto-start Docker here.
    DOCKER_EXAMPLE = (
        "docker run --rm -d --name carla_0_9_16_for_convert -p 2000:2000 -p 2001:2001 "
        "-p 2002:2002 -p 8000:8000 carlasim/carla:0.9.16 ./CarlaUE4.sh -opengl"
    )

    def docker_image_available(image_name):
        try:
            out = subprocess.check_output(["docker", "images", "-q", image_name], stderr=subprocess.DEVNULL).decode().strip()
            return bool(out)
        except Exception:
            return False

    def start_carla_container():
        # Remove any existing container with the same name
        subprocess.call(["docker", "rm", "-f", "carla-server"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Prefer custom carla-bench2drive image if present
        image = "carla-bench2drive:0.9.16" if docker_image_available("carla-bench2drive:0.9.16") else "carlasim/carla:0.9.16"

        cmd = [
            "docker", "run", "-d",
            "--name", "carla-server",
            "--runtime=nvidia",
            "--gpus", "all",
            "--net=host",
            "--shm-size=1g",
            "--env", "NVIDIA_VISIBLE_DEVICES=all",
            "--env", "NVIDIA_DRIVER_CAPABILITIES=all",
            "-v", "/workspace/simlingo/carla_logs:/workspace/CarlaUE4/Saved/Logs",
            "-v", "/workspace/carla0916/CarlaUE4/Content:/workspace/CarlaUE4/Content:ro",
            image,
            "bash", "-c", "cd /workspace && ./CarlaUE4.sh -opengl -RenderOffScreen -nosound -world-port=2000 -carla-rpc-port=2000 -log"
        ]

        print(f"[INFO] Starting CARLA container with image: {image}")
        try:
            cid = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode().strip()
            print(f"[INFO] Started container id: {cid}")
            return cid
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] docker run failed: {e.output.decode() if e.output else e}")
            return None

    def stop_carla_container():
        subprocess.call(["docker", "stop", "carla-server"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.call(["docker", "rm", "-f", "carla-server"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    started = False
    container_id = None

    try:
        # Quick check for existing CARLA
        client = wait_for_carla(timeout=5)
        print("[INFO] Found running CARLA instance — proceeding to conversion")
    except Exception:
        print("[INFO] No running CARLA detected — starting container like the test runner...")
        container_id = start_carla_container()
        if not container_id:
            print("[ERROR] Failed to start CARLA container. Exiting.")
            sys.exit(1)
        started = True

        # Wait and verify container is running
        print("[INFO] Waiting 80s for CARLA to initialize...")
        time.sleep(80)

        # Check container is still present
        try:
            ps = subprocess.check_output(["docker", "ps", "--filter", "name=carla-server", "--no-trunc"], stderr=subprocess.STDOUT).decode()
            if "carla-server" not in ps:
                print("[ERROR] CARLA container crashed immediately after starting. Showing logs:")
                try:
                    logs = subprocess.check_output(["docker", "logs", "carla-server"], stderr=subprocess.STDOUT).decode()
                    print(logs)
                except Exception:
                    print("[ERROR] Could not retrieve docker logs for carla-server")
                stop_carla_container()
                sys.exit(1)
        except subprocess.CalledProcessError:
            print("[ERROR] docker ps failed — cannot verify container state")
            stop_carla_container()
            sys.exit(1)

        # Now attempt to connect to CARLA with a longer timeout
        try:
            client = wait_for_carla(timeout=240)
        except Exception as e:
            print(f"[ERROR] Could not connect to CARLA after container start: {e}")
            try:
                logs = subprocess.check_output(["docker", "logs", "carla-server", "--tail", "200"], stderr=subprocess.STDOUT).decode()
                print("--- docker logs (tail 200) ---")
                print(logs)
            except Exception:
                print("[ERROR] Could not fetch docker logs")
            stop_carla_container()
            sys.exit(1)

    # At this point we have a connected client and can run conversions
    try:
        for i in name_files:
            in_path = name_folder + i + format
            out_path = name_folder + i + '_2' + new + format
            print('=' * PRINT_NUM)
            print(f"[INFO] Converting {in_path} -> {out_path}")
            shift_route_to_lht(in_path, out_path)
            print('=' * PRINT_NUM)
    finally:
        if started:
            print("[INFO] Stopping carla-server container...")
            stop_carla_container()
    
