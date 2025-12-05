"""
Standalone inference script to test SimLingo model on Japanese street images.
Does NOT modify any existing code.
"""
import cv2
import numpy as np
import torch
from pathlib import Path
import sys
import os

# Add project root and dependencies to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "leaderboard"))
sys.path.insert(0, str(project_root / "scenario_runner"))

# Add CARLA Python API from conda environment
conda_prefix = os.environ.get('CONDA_PREFIX', '')
if conda_prefix:
    carla_path = Path(conda_prefix) / "lib" / "python3.8" / "site-packages"
    sys.path.insert(0, str(carla_path))


# --- Mock agents module if missing ---
import types
try:
    import agents.navigation.local_planner
except ModuleNotFoundError:
    agents = types.ModuleType('agents')
    navigation = types.ModuleType('navigation')
    local_planner = types.ModuleType('local_planner')
    class RoadOption:
        VOID = -1
        LEFT = 1
        RIGHT = 2
        STRAIGHT = 3
        LANEFOLLOW = 4
        CHANGELANELEFT = 5
        CHANGELANERIGHT = 6
    local_planner.RoadOption = RoadOption
    navigation.local_planner = local_planner
    agents.navigation = navigation
    sys.modules['agents'] = agents
    sys.modules['agents.navigation'] = navigation
    sys.modules['agents.navigation.local_planner'] = local_planner

from team_code.data_agent import DataAgent

class JapaneseStreetsInference:
    def __init__(self, config_path, checkpoint_path=None):
        """
        Args:
            config_path: Path to agent config file
            checkpoint_path: Optional path to model checkpoint
        """
        self.agent = DataAgent()
        self.config_path = config_path
        self.checkpoint_path = checkpoint_path
        
    def setup(self):
        """Initialize the agent"""
        try:
            self.agent.setup(
                path_to_conf_file=self.config_path,
                route_index=None,
                traffic_manager=None
            )
            print(f"✓ Agent loaded successfully")
        except Exception as e:
            print(f"Warning: Could not fully initialize agent: {e}")
            print("Creating minimal config...")
            self._create_minimal_config()
    
    def _create_minimal_config(self):
        """Create minimal config for offline inference"""
        from types import SimpleNamespace
        # normal HD image 
        self.agent.config = SimpleNamespace(
            camera_width=1920,
            camera_height=1080,
            data_save_freq=1,
        )
        self.agent.save_path = None
        self.agent.datagen = False
        self.agent.initialized = True
        self.agent.step = 0
        
    def preprocess_image(self, image_path):
        """Load and preprocess a single image"""
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"Could not load image: {image_path}")
        
        # Convert BGR to RGB if needed by model
        # img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        
        return img
    
    @torch.inference_mode()
    def infer_single(self, image_path):
        """
        Run inference on a single Japanese street image
        
        Args:
            image_path: Path to input image
            
        Returns:
            dict with control outputs (steer, throttle, brake, etc.)
        """
        img = self.preprocess_image(image_path)
        
        # Prepare input in format expected by DataAgent
        input_data = {
            'rgb': (None, img),  # Tuple format: (sensor_object, numpy_array)
            'lidar': np.zeros((0, 3), dtype=np.float32),  # Empty LiDAR
        }
        
        # Run inference
        timestamp = 0.0
        control = self.agent.run_step(
            input_data, 
            timestamp=timestamp,
            sensors=None,
            plant=False
        )
        
        return control
    
    def infer_directory(self, image_dir, output_file=None):
        """
        Run inference on all images in a directory
        
        Args:
            image_dir: Directory containing Japanese street images
            output_file: Optional path to save results as JSON
            
        Returns:
            List of results for each image
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
                control = self.infer_single(img_path)
                
                result = {
                    'image': str(img_path),
                    'control': control
                }
                results.append(result)
                print(f"✓ {control}")
                
            except Exception as e:
                print(f"✗ Error: {e}")
                results.append({
                    'image': str(img_path),
                    'error': str(e)
                })
        
        # Optionally save results
        if output_file:
            import json
            with open(output_file, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"\n✓ Results saved to {output_file}")
        
        return results


def main():
    """Example usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Test SimLingo on Japanese street images')
    parser.add_argument('--config', required=True, help='Path to agent config file')
    parser.add_argument('--checkpoint', help='Path to model checkpoint (optional)')
    parser.add_argument('--image', help='Single image path')
    parser.add_argument('--image-dir', help='Directory of images')
    parser.add_argument('--output', help='Output JSON file for results')
    
    args = parser.parse_args()
    
    # Initialize inference
    inference = JapaneseStreetsInference(args.config, args.checkpoint)
    inference.setup()
    
    # Run inferenceƒimGE
    if args.image:
        print(f"\n=== Single Image Inference ===")
        control = inference.infer_single(args.image)
        print(f"Result: {control}")
        
    elif args.image_dir:
        print(f"\n=== Batch Inference ===")
        results = inference.infer_directory(args.image_dir, args.output)
        print(f"\n✓ Processed {len(results)} images")
        print('\n\n\n[INFO]: OUTPUT SAMPLE:')
    else:
        print("Error: Provide either --image or --image-dir")
        sys.exit(1)


if __name__ == '__main__':
    main()


# # Single image
# python /workspace/simlingo/team_code/agent_simlingo_japan_copilot.py \
#     --config /workspace/simlingo/config.py \
#     --image /workspace/simlingo/japanese_street/images_005.png


# Single image
# python /workspace/simlingo/team_code/agent_simlingo_japan_copilot.py \
#     --config /team_code/config.py \
#     --image /japanese_street/images_0005.png


# # Batch directory
# python /workspace/simlingo/test_japanese_streets.py \
#     --config /path/to/config.py \
#     --image-dir /path/to/japanese_streets/ \
#     --output results.json