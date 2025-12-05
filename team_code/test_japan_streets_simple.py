"""
Standalone inference script to test SimLingo model on Japanese street images.
Based on agent_simlingo.py, does NOT use data_agent or autopilot. This will be the next topic. 
"""
import cv2
import numpy as np
import torch
from pathlib import Path
import sys
import os
import hydra
from hydra.utils import get_original_cwd, to_absolute_path
import argparse
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

class JapaneseStreetsInference:
    def __init__(self, config_path=None, checkpoint_path=None):
        """
        Args:
            config_path: Path to agent config file
            checkpoint_path: Optional path to model checkpoint
        """
        self.agent = LingoAgent(carla_host='localhost', carla_port=2000) # dummy config 
        ## we have done something quite wrong in the dowaloading of the dataset, hence this part is hardcoded. 
        # agent_simlingo.py uses config_path as the checkpoint path -> .hydra/config.yaml at Path(config_path).parent.parent / '.hydra' / 'config.yaml'
        self.config_path = config_path if config_path else "/workspace/simlingo/outputs/simlingo2/checkpoints/epoch=013.ckpt/pytorch_model.pt"
        self.checkpoint_path = checkpoint_path if checkpoint_path else "/workspace/simlingo/outputs/simlingo2/checkpoints/epoch=013.ckpt/pytorch_model.pt"
        
    def setup(self):
        """Initialize the agent"""
        if 'SAVE_PATH' not in os.environ:
            os.environ['SAVE_PATH'] = '/workspace/simlingo/outputs/test_inference/'
        if 'ROUTES' not in os.environ:
            os.environ['ROUTES'] = '/workspace/simlingo/data/benchmarks/test/routes_test.xml'
        
        self.agent.save_path = None
        self.agent.debug_save_path = '/tmp/dummy_debug_japan'
        self.agent.save_path_metric = '/tmp/dummy_metric_japan'
        
        self.agent.get_metric_info = lambda: {}
        
        import carla
        sys.path.insert(0, str(project_root / "scenario_runner" / "srunner" / "tests" / "carla_mocks"))
        from agents.navigation.local_planner import RoadOption
        
        dummy_location = carla.Location(x=0.0, y=0.0, z=0.0)
        dummy_transform = carla.Transform(dummy_location, carla.Rotation(pitch=0, yaw=0, roll=0))
        
        # Create a simple route with "follow lane" commands
        # Launching the Carla setup this will be no longer needed.
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
        
        ###
        try:
            self.agent.setup(path_to_conf_file=self.config_path, route_index='japanese_test')
            print(f"[INFO]: Agent loaded successfully")
        except Exception as e:
            print(f"[ERROR]: Error initializing agent: {e}")
            import traceback
            traceback.print_exc()
            raise
        
    def preprocess_image(self, image_path):
        """Load and preprocess a single image"""
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"Could not load image: {image_path}")
        return img
    
    @torch.inference_mode()
    def infer_single(self, image_path):
        """Run inference on a single Japanese street image
        
        Args: image_path: Path to input image
        Returns: dict with control outputs (steer, throttle, brake, etc.)
        """
        img = self.preprocess_image(image_path)
        
        # # Prepare input in format expected by LingoAgent

        # input_data = {
        #     'rgb_0': (0, img),             # Real img from Japanese street
        #     'imu': (0, [0.0]),             # Dummy compass/heading pointing north (0.0 radians = east in CARLA), scalar 
        #     'gps': (0, [0.0, 0.0, 0.0]),   # Dummy GPS at origin (x, y, z)
        #     'speed': (0, {'speed': 5.0}),  # Dummy speed of 5 m/s
        # }

        metadata = {}  # {'image_001.png': {'imu': [0.1], 'gps': [1.2, 3.4, 0.0], 'speed': {'speed': 4.5}}}
        meta = metadata.get(Path(image_path).name, {})
        input_data = {
            'rgb_0': (0, img),
            'imu': (0, meta.get('imu', [0.0])),
            'gps': (0, meta.get('gps', [0.0, 0.0, 0.0])),   
            'speed': (0, meta.get('speed', {'speed': 5.0})),
        }
                
        # Run inference step-wise
        timestamp = 0.0
        t0 = time.time()
        control = self.agent.run_step(input_data, timestamp)
        duration = time.time() - t0
        print(f"[INFO]: Run Step done in {duration:.3f}s")
                
        return control
    
    def infer_directory(self, image_dir, output_file=None):
        """Run inference on all images in a directory
        
        Args:
            image_dir: Directory containing Japanese street images
            output_file: Optional path to save results as JSON 
        Returns: List of results for each image
        """
        image_dir = Path(image_dir)
        results = []
        
        # Find all image files
        image_files = sorted(list(image_dir.glob("*.jpg")) + 
                           list(image_dir.glob("*.png")) +
                           list(image_dir.glob("*.jpeg")))
        
        print(f"\nProcessing {len(image_files)} images from {image_dir}")
        
        for img_path in image_files:
            try:
                print(f"Processing: {img_path.name}...", end=" ")
                t0 = time.time()
                control = self.infer_single(img_path)
                duration = time.time() - t0
                print(f"[INFO]: Inference done in {duration:.3f}s")

                result = {
                    'image': str(img_path),
                    'control': {
                        'steer': float(control.steer),
                        'throttle': float(control.throttle),
                        'brake': float(control.brake),
                        'hand_brake': bool(control.hand_brake),
                        'reverse': bool(control.reverse)
                    }
                }
                results.append(result)
                print(f"steer={control.steer:.3f}, throttle={control.throttle:.3f}, brake={control.brake:.3f}")
                
            except Exception as e:
                print(f"Error: {e}")
                results.append({
                    'image': str(img_path),
                    'error': str(e)
                })
        
        # Optionally save results
        if output_file:
            import json
            with open(output_file, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"\nResults saved to {output_file}")
        
        return results


def main():
    """Main minimal implementation"""
      
    parser = argparse.ArgumentParser(description='Test SimLingo on Japanese street images')
    parser.add_argument('--config', help='Path to hydra output directory containing .hydra/config.yaml')
    parser.add_argument('--checkpoint', help='Path to model checkpoint (optional)')
    parser.add_argument('--image', help='Single image path')
    parser.add_argument('--image-dir', help='Directory of images')
    parser.add_argument('--output', help='Output JSON file for results')
    
    args = parser.parse_args()
    
    # Initialize inference
    config_path = args.config if args.config else None
    checkpoint_path = args.checkpoint if args.checkpoint else None
    # inference = JapaneseStreetsInference(args.config, args.checkpoint)
    inference = JapaneseStreetsInference(config_path, checkpoint_path)

    inference.setup()
    
    # Run inference
    if args.image:
        print(f"\n=== Single Image Inference ===")
        control = inference.infer_single(args.image)
        print(f"Result: {control}")
        
    elif args.image_dir:
        print(f"\n=== Batch Inference ===")
        results = inference.infer_directory(args.image_dir, args.output)
        print(f"\nProcessed {len(results)} images")
        
    else:
        print("Error: Provide either --image or --image-dir")
        sys.exit(1)


if __name__ == '__main__':
    print(f"\033[33m{'=' * 100}\033[0m")
    print("[INFO] This script just run the inference on Japanese street images using SimLingo model.")
    print(f"\033[33m{'=' * 100}\033[0m")
    main()

