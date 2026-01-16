import carla
import xml.etree.ElementTree as ET
import time
import sys
import subprocess
import shlex

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
    # 1. Connect to CARLA 0.9.16 (wait for it to be ready)
    client = wait_for_carla(host=host, port=port, timeout=wait_timeout)
    client.set_timeout(30.0)
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
    
    # If CARLA is not reachable, do not attempt to auto-start Docker here.
    # Instead, print a clear docker run command the user can run manually and exit.
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
            out_path = name_folder + i + new + format
            print(f"[INFO] Converting {in_path} -> {out_path}")
            shift_route_to_lht(in_path, out_path)
    finally:
        if started:
            print("[INFO] Stopping carla-server container...")
            stop_carla_container()
    
