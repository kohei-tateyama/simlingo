"""
Inference script with trajectory visualization on real-world images.
Runs SimLingo model and overlays predicted waypoint trajectories directly on input images.

Usage:
    # Single image
    python team_code/inference.py --image path/to/image.jpg --output output.jpg
    
    # Directory of images
    python team_code/inference.py --image-dir path/to/images --output-dir path/to/output
    
    # With JSON export
    python team_code/inference.py --image-dir data/testride --output-dir data/output --save-json results.json
"""

import cv2
import numpy as np
import torch
from pathlib import Path
import sys
import os
import argparse
import json
import time

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "leaderboard"))
sys.path.insert(0, str(project_root / "scenario_runner"))

conda_prefix = os.environ.get('CONDA_PREFIX', '')
if conda_prefix:
    carla_path = Path(conda_prefix) / "lib" / "python3.8" / "site-packages"
    sys.path.insert(0, str(carla_path))

from team_code.agent_simlingo import LingoAgent


def get_camera_intrinsics(w, h, fov=110):
    """
    Get camera intrinsics matrix from width, height and fov.
    Returns:
        K: A numpy array of shape [3, 3] containing the intrinsic calibration matrices
    """
    focal = w / (2.0 * np.tan(np.radians(fov) / 2.0))
    K = np.identity(3, dtype=np.float32)
    K[0, 0] = K[1, 1] = focal
    K[0, 2] = w / 2.0
    K[1, 2] = h / 2.0
    return K


def project_waypoints_to_image(waypoints_3d, camera_intrinsics, tvec=None, rvec=None, camera_height=1.5):
    """
    Project 3D CARLA waypoints to 2D image coordinates.
    
    Args:
        waypoints_3d: numpy array of shape [N, 3] in CARLA coordinates (x=forward, y=lateral, z=height)
        camera_intrinsics: numpy array [3, 3]
        tvec: translation vector for projection
        rvec: rotation vector for projection
        camera_height: Camera height above ground in meters (default 1.5 for CARLA, adjust for handheld)
    
    Returns:
        List of (px, py) tuples
    """
    all_points_2d = []
    
    # Default camera transformation parameters
    if rvec is None:
        rvec_new = np.zeros((3, 1), np.float32)
    else:
        rvec_new = np.array([[-rvec[1], rvec[2], rvec[0]]], np.float32)
    
    if tvec is None:
        tvec = np.array([[0.0, 2.0, camera_height]], np.float32)
    
    dist_coeffs = np.zeros((5, 1), np.float32)
    
    for point in waypoints_3d:
        # Transform CARLA coordinates: swap x/y and add z offset
        # point[0] = x (forward), point[1] = y (lateral), point[2] = z (height)
        pos_3d = np.array([point[1], point[2] if len(point) > 2 else 0, point[0] + tvec[0][2]])
        
        # Use cv2.projectPoints for proper pinhole camera projection
        points_2d, _ = cv2.projectPoints(
            pos_3d,
            rvec=rvec_new,
            tvec=tvec,
            cameraMatrix=camera_intrinsics,
            distCoeffs=dist_coeffs
        )
        
        px, py = points_2d[0][0]
        all_points_2d.append((int(px), int(py)))
    
    return all_points_2d


def draw_trajectory_on_image(img, pred_route, pred_speed_wps=None, language=None, 
                            prompt=None, fov=110, show_speeds=True, show_text=True):
    """
    Draw predicted trajectory and optional annotations on image.
    
    Args:
        img: Input image (BGR)
        pred_route: Predicted waypoints, shape [N, 2] or [N, 3] in CARLA coords
        pred_speed_wps: Optional speed predictions at waypoints
        language: Optional language description from model
        prompt: Optional input prompt
        fov: Camera field of view in degrees
        show_speeds: Whether to show speed annotations
        show_text: Whether to show language/prompt text
    
    Returns:
        Annotated image
    """
    out_img = img.copy()
    h, w = out_img.shape[:2]
    
    # Get camera intrinsics
    camera_intrinsics = get_camera_intrinsics(w, h, fov)
    
    # Project waypoints to image coordinates
    if pred_route is not None and len(pred_route) > 0:
        # Ensure waypoints are numpy array
        if isinstance(pred_route, list):
            pred_route = np.array(pred_route, dtype=np.float32)
        
        # Handle 2D waypoints (add z=0)
        if pred_route.shape[1] == 2:
            pred_route = np.column_stack([pred_route, np.zeros(len(pred_route))])
        
        # Project to image
        points_2d = project_waypoints_to_image(pred_route, camera_intrinsics)
        
        # Filter points within image bounds
        valid_points = []
        for px, py in points_2d:
            if 0 <= px < w and 0 <= py < h:
                valid_points.append((px, py))
        
        if len(valid_points) >= 2:
            # Draw trajectory curve (thick orange line)
            pts = np.array(valid_points, dtype=np.int32)
            cv2.polylines(out_img, [pts], False, (0, 165, 255), 5, cv2.LINE_AA)
            
            # Draw waypoint markers
            for i, (px, py) in enumerate(valid_points):
                # Color code: green (start) -> cyan (middle) -> red (end)
                if i == 0:
                    color = (0, 255, 0)  # Green - start
                    radius = 12
                elif i == len(valid_points) - 1:
                    color = (0, 0, 255)  # Red - end
                    radius = 12
                else:
                    color = (255, 255, 0)  # Yellow - middle
                    radius = 8
                
                # Draw filled circle
                cv2.circle(out_img, (px, py), radius, color, -1, cv2.LINE_AA)
                # Draw white outline
                cv2.circle(out_img, (px, py), radius + 2, (255, 255, 255), 2, cv2.LINE_AA)
                
                # Optionally show speed at each waypoint
                if show_speeds and pred_speed_wps is not None and i < len(pred_speed_wps):
                    try:
                        speed = float(pred_speed_wps[i])
                        speed_text = f"{speed:.1f}"
                        cv2.putText(out_img, speed_text, (px + 15, py - 10),
                                  cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
                    except:
                        pass
    
    # Add text panel at bottom if language/prompt provided
    if show_text and (language is not None or prompt is not None):
        import textwrap
        
        lines = []
        if prompt is not None:
            prompt_str = str(prompt) if not isinstance(prompt, (list, tuple)) else str(prompt[0])
            prompt_wrapped = textwrap.wrap(f"Prompt: {prompt_str}", width=80)
            lines.extend(prompt_wrapped)
        
        if language is not None:
            if lines:
                lines.append("")  # Blank separator
            lang_str = str(language) if not isinstance(language, (list, tuple)) else str(language[0])
            lang_wrapped = textwrap.wrap(f"Model: {lang_str}", width=80)
            lines.extend(lang_wrapped)
        
        if lines:
            # Create semi-transparent panel at bottom
            panel_h = max(80, 22 * len(lines) + 20)
            overlay = out_img.copy()
            cv2.rectangle(overlay, (0, h - panel_h), (w, h), (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.6, out_img, 0.4, 0, out_img)
            
            # Draw text
            y = h - panel_h + 25
            for line in lines:
                cv2.putText(out_img, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 
                          0.6, (255, 255, 255), 1, cv2.LINE_AA)
                y += 22
    
    return out_img


class SimLingoInference:
    """Wrapper for SimLingo model inference on real-world images"""
    
    def __init__(self, config_path=None, checkpoint_path=None):
        """
        Initialize SimLingo agent.
        
        Args:
            config_path: Path to model config/checkpoint
            checkpoint_path: Optional separate checkpoint path
        """
        self.agent = LingoAgent(carla_host='localhost', carla_port=2000)
        self.config_path = config_path if config_path else \
            "/workspace/simlingo/outputs/simlingo2/checkpoints/epoch=013.ckpt/pytorch_model.pt"
        self.checkpoint_path = checkpoint_path if checkpoint_path else self.config_path
        
    def setup(self):
        """Initialize the agent with dummy route/environment"""
        # Set required environment variables
        if 'SAVE_PATH' not in os.environ:
            os.environ['SAVE_PATH'] = '/tmp/simlingo_inference/'
        if 'ROUTES' not in os.environ:
            os.environ['ROUTES'] = '/tmp/dummy_routes.xml'
        
        # Disable saving
        self.agent.save_path = None
        self.agent.debug_save_path = '/tmp/dummy_debug'
        self.agent.save_path_metric = '/tmp/dummy_metric'
        self.agent.get_metric_info = lambda: {}
        
        # Import CARLA types
        import carla
        project_root = Path(__file__).parent.parent
        sys.path.insert(0, str(project_root / "scenario_runner" / "srunner" / "tests" / "carla_mocks"))
        from agents.navigation.local_planner import RoadOption
        
        # Create dummy route (needed by agent but not used in inference)
        dummy_location = carla.Location(x=0.0, y=0.0, z=0.0)
        dummy_transform = carla.Transform(dummy_location, carla.Rotation(pitch=0, yaw=0, roll=0))
        
        self.agent._global_plan_world_coord = [
            (dummy_transform, RoadOption.LANEFOLLOW),
            (carla.Transform(carla.Location(x=10.0, y=0.0, z=0.0), carla.Rotation()), RoadOption.LANEFOLLOW),
            (carla.Transform(carla.Location(x=20.0, y=0.0, z=0.0), carla.Rotation()), RoadOption.LANEFOLLOW),
        ]
        self.agent._global_plan = [
            ({'lat': 0.0, 'lon': 0.0, 'z': 0.0}, RoadOption.LANEFOLLOW),
            ({'lat': 0.0001, 'lon': 0.0, 'z': 0.0}, RoadOption.LANEFOLLOW),
            ({'lat': 0.0002, 'lon': 0.0, 'z': 0.0}, RoadOption.LANEFOLLOW),
        ]
        
        # Load agent
        try:
            self.agent.setup(path_to_conf_file=self.config_path, route_index='inference')
            print(f"✓ Model loaded successfully")
        except Exception as e:
            print(f"✗ Error loading model: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def preprocess_image(self, image_path):
        """Load and validate image"""
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"Could not load image: {image_path}")
        return img
    
    @torch.inference_mode()
    def infer(self, image_path, visualize=True, fov=110):
        """
        Run inference on a single image.
        
        Args:
            image_path: Path to input image
            visualize: Whether to create visualization
            fov: Camera field of view
        
        Returns:
            result: Dict with predictions and optionally visualized image
        """
        img = self.preprocess_image(image_path)
        
        # Prepare input data (minimal required by agent)
        input_data = {
            'rgb_0': (0, img),
            'imu': (0, [0.0]),
            'gps': (0, [0.0, 0.0, 0.0]),
            'speed': (0, {'speed': 40.0}),
        }
        
        # Run inference
        # Note: First call initializes the agent and returns brake without running model
        # We need to call it twice to get actual predictions
        timestamp = 0.0
        if not self.agent.initialized:
            # First call just initializes
            _ = self.agent.run_step(input_data, timestamp)
        
        # Second call actually runs the model
        t0 = time.perf_counter()
        control = self.agent.run_step(input_data, timestamp)
        elapsed = time.perf_counter() - t0
        
        # Extract predictions
        pred_route = getattr(self.agent, 'pred_route', None)
        pred_speed_wps = getattr(self.agent, 'pred_speed_wps', None)
        language = getattr(self.agent, 'language', None)
        prompt = getattr(self.agent, 'prompt', None)
        
        # Convert to serializable format
        pred_route_list = None
        if pred_route is not None:
            try:
                pred_route_list = pred_route[0].detach().cpu().numpy().tolist()
            except:
                pass
        
        pred_speed_wps_list = None
        if pred_speed_wps is not None:
            try:
                pred_speed_wps_list = pred_speed_wps[0].detach().cpu().numpy().tolist()
            except:
                pass
        
        language_str = None
        if language is not None:
            try:
                language_str = language[0] if isinstance(language, (list, tuple)) else str(language)
            except:
                pass
        
        # Create result dict
        result = {
            'image_path': str(image_path),
            'inference_time': elapsed,
            'control': {
                'steer': float(control.steer),
                'throttle': float(control.throttle),
                'brake': float(control.brake),
                'hand_brake': bool(control.hand_brake),
                'reverse': bool(control.reverse),
            },
            'pred_route': pred_route_list,
            'pred_speed_wps': pred_speed_wps_list,
            'language': language_str,
            'prompt': str(prompt) if prompt is not None else None,
        }
        
        # Create visualization
        if visualize and pred_route_list is not None:
            vis_img = draw_trajectory_on_image(
                img, 
                pred_route_list,
                pred_speed_wps_list,
                language_str,
                prompt,
                fov=fov
            )
            result['vis_image'] = vis_img
        
        return result


def main():
    parser = argparse.ArgumentParser(description='SimLingo Inference with Trajectory Visualization')
    parser.add_argument('--config', help='Path to model config/checkpoint')
    parser.add_argument('--checkpoint', help='Path to model checkpoint (optional)')
    parser.add_argument('--image', help='Single image path')
    parser.add_argument('--image-dir', help='Directory of images')
    parser.add_argument('--output', help='Output image path (for single image)')
    parser.add_argument('--output-dir', help='Output directory (for batch processing)')
    parser.add_argument('--save-json', help='Save results as JSON file')
    parser.add_argument('--fov', type=float, default=110, help='Camera field of view (degrees)')
    parser.add_argument('--no-viz', action='store_true', help='Skip visualization (faster)')
    
    args = parser.parse_args()
    
    # Initialize model
    print("=" * 80)
    print("SimLingo Inference with Trajectory Visualization")
    print("=" * 80)
    
    inference = SimLingoInference(args.config, args.checkpoint)
    inference.setup()
    
    # Single image mode
    if args.image:
        print(f"\n📷 Processing single image: {args.image}")
        result = inference.infer(args.image, visualize=not args.no_viz, fov=args.fov)
        
        print(f"⏱️  Inference time: {result['inference_time']:.3f}s")
        print(f"🎮 Control: steer={result['control']['steer']:.3f}, "
              f"throttle={result['control']['throttle']:.3f}, "
              f"brake={result['control']['brake']:.3f}")
        
        if result.get('language'):
            print(f"💬 Model output: {result['language']}")
        
        # Debug: Check what predictions we got
        if result.get('pred_route') is None:
            print(f"⚠️  Warning: No trajectory predictions generated")
        else:
            num_waypoints = len(result['pred_route']) if isinstance(result['pred_route'], list) else 0
            print(f"🛣️  Predicted {num_waypoints} waypoints")
        
        # Save visualization
        if 'vis_image' in result:
            if args.output:
                output_path = Path(args.output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(output_path), result['vis_image'])
                print(f"✓ Saved visualization to: {args.output}")
            else:
                print(f"⚠️  Visualization created but no --output path specified")
        else:
            if args.output:
                print(f"⚠️  No visualization created (missing predictions)")
        
        # Save JSON
        if args.save_json:
            json_path = Path(args.save_json)
            json_path.parent.mkdir(parents=True, exist_ok=True)
            with open(json_path, 'w') as f:
                json.dump({k: v for k, v in result.items() if k != 'vis_image'}, f, indent=2)
            print(f"✓ Saved JSON to: {args.save_json}")
    
    # Batch processing mode
    elif args.image_dir:
        image_dir = Path(args.image_dir)
        output_dir = Path(args.output_dir) if args.output_dir else image_dir / "inference_output"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Find all images
        image_files = sorted(list(image_dir.glob("*.jpg")) + 
                           list(image_dir.glob("*.png")) +
                           list(image_dir.glob("*.jpeg")))
        
        print(f"\n📁 Processing {len(image_files)} images from {image_dir}")
        print(f"📁 Output directory: {output_dir}")
        
        all_results = {}
        
        for i, img_path in enumerate(image_files, 1):
            try:
                print(f"\n[{i}/{len(image_files)}] {img_path.name}...", end=" ")
                
                result = inference.infer(img_path, visualize=not args.no_viz, fov=args.fov)
                
                print(f"✓ {result['inference_time']:.3f}s | "
                      f"steer={result['control']['steer']:.2f} | "
                      f"throttle={result['control']['throttle']:.2f}")
                
                # Save visualization
                if 'vis_image' in result:
                    out_path = output_dir / f"{img_path.stem}_trajectory.jpg"
                    cv2.imwrite(str(out_path), result['vis_image'])
                
                # Store result (without image)
                all_results[img_path.name] = {k: v for k, v in result.items() if k != 'vis_image'}
                
            except Exception as e:
                print(f"✗ Error: {e}")
                all_results[img_path.name] = {'error': str(e)}
        
        # Save JSON summary
        if args.save_json:
            json_path = args.save_json
        else:
            json_path = output_dir / "results.json"
        
        with open(json_path, 'w') as f:
            json.dump(all_results, f, indent=2)
        
        print(f"\n{'=' * 80}")
        print(f"✓ Processed {len(image_files)} images")
        print(f"✓ Visualizations saved to: {output_dir}")
        print(f"✓ Results saved to: {json_path}")
        print(f"{'=' * 80}")
    
    else:
        print("Error: Provide either --image or --image-dir")
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
