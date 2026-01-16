import carla
import numpy as np
import time
import threading
import os
import argparse
from datetime import datetime
from PIL import Image as PILImage

try:
    import pygame
    from pygame.locals import K_w, K_s, K_a, K_d, K_q, K_SPACE
except Exception:
    pygame = None

RECORDING_OUTPUT_DIR = "/workspace/simlingo/recording_japan_manual"


# THIS SCRIPT ENABLES A MANUAL DRIVING OF THE EGO USING CARLA 0.9.15.
# THIS CODE HAS NEVER BEEN TESTED.

class JapaneseDrivingCameras:
    def __init__(self, duration=60, port_localhost=2000, town='Town13', fps=20.0):
        self.client = carla.Client('localhost', port_localhost)
        self.client.set_timeout(10.0)
        self.fps = fps
        self.sleep_interval = 1.0 / self.fps
        self.town = town

        # world selection
        try:
            self.world = self.client.get_world()
        except Exception:
            self.world = self.client.load_world(self.town)

        # traffic manager for left-hand traffic
        try:
            self.traffic_manager = self.client.get_trafficmanager(8000)
            self.traffic_manager.global_lane_offset = -1.5
        except Exception:
            self.traffic_manager = None

        # Recording / sensors
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.foldername = f"manual_multicamera_japanese_{timestamp}"
        self.folderpath = os.path.join(RECORDING_OUTPUT_DIR, self.foldername)
        os.makedirs(os.path.join(self.folderpath, 'rgb'), exist_ok=True)

        self.image_size_x = 1024
        self.image_size_y = 512

        self.player_vehicle = None
        self.sensors = []

        # Buffering for coordinated multi-camera writes (simple version)
        self._image_buffer = {}
        self._buffer_lock = threading.Lock()
        self._last_frame_seen_time = {}
        self._buffer_timeout = 0.5
        self._stopping = False
        self.frame_counter = 0

        # start writer thread
        self._writer_thread = threading.Thread(target=self._buffer_writer, daemon=True)
        self._writer_thread.start()

    def spawn_player(self):
        blueprint_library = self.world.get_blueprint_library()
        vehicle_bp = blueprint_library.find('vehicle.tesla.model3')
        vehicle_bp.set_attribute('role_name', 'hero')

        spawn_points = self.world.get_map().get_spawn_points()
        spawn_point = spawn_points[0] if spawn_points else carla.Transform(carla.Location(x=0, y=0, z=0))
        self.player_vehicle = self.world.spawn_actor(vehicle_bp, spawn_point)
        print(f"[INFO] Spawned player vehicle at {spawn_point.location}")

    def setup_camera(self):
        if not self.player_vehicle:
            raise RuntimeError('Player vehicle not spawned')

        blueprint_library = self.world.get_blueprint_library()

        camera_configs = [
            {'name': 'F', 'transform': carla.Transform(carla.Location(x=2.5, y=0.0, z=1.5), carla.Rotation(pitch=0.0, yaw=0.0)), 'fov': '110'},
            {'name': 'B', 'transform': carla.Transform(carla.Location(x=-2.5, y=0.0, z=1.5), carla.Rotation(pitch=0.0, yaw=180.0)), 'fov': '110'},
            {'name': 'RF', 'transform': carla.Transform(carla.Location(x=1.0, y=1.0, z=1.5), carla.Rotation(pitch=0.0, yaw=55.0)), 'fov': '110'},
            {'name': 'LF', 'transform': carla.Transform(carla.Location(x=1.0, y=-1.0, z=1.5), carla.Rotation(pitch=0.0, yaw=-55.0)), 'fov': '110'},
            {'name': 'RB', 'transform': carla.Transform(carla.Location(x=-1.0, y=1.0, z=1.5), carla.Rotation(pitch=0.0, yaw=125.0)), 'fov': '110'},
            {'name': 'LB', 'transform': carla.Transform(carla.Location(x=-1.0, y=-1.0, z=1.5), carla.Rotation(pitch=0.0, yaw=-125.0)), 'fov': '110'},
        ]

        for cam in camera_configs:
            cam_bp = blueprint_library.find('sensor.camera.rgb')
            cam_bp.set_attribute('image_size_x', str(self.image_size_x))
            cam_bp.set_attribute('image_size_y', str(self.image_size_y))
            cam_bp.set_attribute('fov', cam['fov'])
            try:
                cam_bp.set_attribute('sensor_tick', str(self.sleep_interval))
            except Exception:
                pass

            actor = self.world.spawn_actor(cam_bp, cam['transform'], attach_to=self.player_vehicle)

            cam_name = cam['name']

            def make_cb(name):
                def _on_image(image):
                    if getattr(self, '_stopping', False):
                        return
                    try:
                        with self._buffer_lock:
                            frame_num = int(self.frame_counter)
                        arr = np.frombuffer(image.raw_data, dtype=np.uint8)
                        arr = arr.reshape((image.height, image.width, 4))
                        rgb = arr[:, :, :3][:, :, ::-1]
                        with self._buffer_lock:
                            d = self._image_buffer.setdefault(frame_num, {})
                            d[name] = rgb.copy()
                            self._last_frame_seen_time[frame_num] = time.time()
                    except Exception as e:
                        if not getattr(self, '_stopping', False):
                            print(f"[WARN] camera {name} callback error: {e}")

                return _on_image

            actor.listen(make_cb(cam_name))
            self.sensors.append(actor)

        print('[INFO] Attached 6 cameras (F,B,RF,LF,RB,LB)')

    def _buffer_writer(self):
        CAMS = {'F', 'B', 'RF', 'LF', 'RB', 'LB'}
        while not getattr(self, '_stopping', False):
            now = time.time()
            to_write = []
            with self._buffer_lock:
                for frame_num, cam_dict in list(self._image_buffer.items()):
                    cams_present = set(cam_dict.keys())
                    if cams_present >= CAMS:
                        to_write.append((frame_num, dict(cam_dict)))
                        del self._image_buffer[frame_num]
                        self._last_frame_seen_time.pop(frame_num, None)
                    else:
                        first = self._last_frame_seen_time.get(frame_num, now)
                        if (now - first) >= self._buffer_timeout:
                            to_write.append((frame_num, dict(cam_dict)))
                            del self._image_buffer[frame_num]
                            self._last_frame_seen_time.pop(frame_num, None)

            for frame_num, cam_dict in to_write:
                frame_folder = f"{frame_num:04d}"
                frame_dir = os.path.join(self.folderpath, 'rgb', frame_folder)
                os.makedirs(frame_dir, exist_ok=True)
                for cam_name, arr in cam_dict.items():
                    try:
                        pil = PILImage.fromarray(arr)
                        pil.save(os.path.join(frame_dir, f"{cam_name}.png"), 'PNG')
                    except Exception as e:
                        print(f"[WARN] failed to write frame {frame_num} cam {cam_name}: {e}")

            time.sleep(0.03)

    def run(self, duration=60):
        # Try to enable synchronous mode
        original_settings = None
        sync_enabled = False
        try:
            original_settings = self.world.get_settings()
            new_settings = self.world.get_settings()
            new_settings.synchronous_mode = True
            new_settings.fixed_delta_seconds = self.sleep_interval
            self.world.apply_settings(new_settings)
            sync_enabled = True
            print(f"[INFO] Enabled synchronous mode dt={self.sleep_interval}")
        except Exception as e:
            print(f"[WARN] could not enable synchronous mode: {e}")

        try:
            self.spawn_player()
            self.setup_camera()

            # initialize pygame for keyboard control
            if pygame is None:
                print('[ERROR] pygame not available; install pygame to use keyboard control')
                return

            pygame.init()
            pygame.display.set_caption('CARLA Manual Control - Press Q to quit')
            screen = pygame.display.set_mode((320, 240))

            control = carla.VehicleControl()
            start_time = time.time()

            while (time.time() - start_time) < duration:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self._stopping = True
                        break

                keys = pygame.key.get_pressed()
                throttle = 0.0
                steer = 0.0
                brake = 0.0

                if keys[K_w]:
                    throttle = 0.6
                if keys[K_s]:
                    throttle = -0.2
                if keys[K_a]:
                    steer = -0.5
                if keys[K_d]:
                    steer = 0.5
                if keys[K_SPACE]:
                    brake = 1.0
                if keys[K_q]:
                    print('[INFO] Quit key pressed')
                    break

                control.throttle = max(0.0, throttle) if throttle >= 0 else 0.0
                control.brake = brake
                control.steer = steer
                if throttle < 0:
                    control.reverse = True
                    control.throttle = abs(throttle)
                else:
                    control.reverse = False

                try:
                    self.player_vehicle.apply_control(control)
                except Exception:
                    pass

                # advance simulator
                if sync_enabled:
                    try:
                        self.frame_counter += 1
                        self.world.tick()
                    except Exception:
                        time.sleep(self.sleep_interval)
                else:
                    self.frame_counter += 1
                    time.sleep(self.sleep_interval)

                # small display update so pygame processes events
                screen.fill((0, 0, 0))
                pygame.display.flip()

        finally:
            try:
                if original_settings is not None:
                    self.world.apply_settings(original_settings)
            except Exception:
                pass

            self.cleanup()

    def cleanup(self):
        print('[INFO] Cleaning up...')
        self._stopping = True
        time.sleep(0.2)
        for s in list(self.sensors):
            try:
                s.stop()
            except Exception:
                pass
            try:
                s.destroy()
            except Exception:
                pass
        self.sensors = []

        if self.player_vehicle:
            try:
                self.player_vehicle.destroy()
            except Exception:
                pass

        try:
            if hasattr(self, '_writer_thread') and self._writer_thread.is_alive():
                self._writer_thread.join(timeout=1.0)
        except Exception:
            pass

        if pygame is not None:
            try:
                pygame.quit()
            except Exception:
                pass

        print('[INFO] Done')


def main():
    parser = argparse.ArgumentParser(description='Japanese manual driving with multi cameras')
    parser.add_argument('--duration', type=int, default=60, help='Duration in seconds')
    args = parser.parse_args()

    sim = JapaneseDrivingCameras(duration=args.duration)
    sim.run(duration=args.duration)


if __name__ == '__main__':
    main()
