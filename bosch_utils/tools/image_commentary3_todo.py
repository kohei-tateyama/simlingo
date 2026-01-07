"""
image_commentary3_todo.py
Hybrid approach: Uses llama.cpp for commentary generation (from image_commentary2_todo.py)
+ CARLA measurements/boxes for structured fields (from carla_commentary_generator.py)

This script generates driving commentary combining:
- LLM-generated natural language commentary (via llama.cpp multimodal)
- CARLA simulation data (measurements, boxes) for cause_object and scenario metadata
- Full structured output compatible with simlingo training format

IMPORTANT: Dataset Structure Understanding
==========================================
The dataset has ONE timestamp per frame with MULTIPLE camera views:

  Frame 0010 (single timestamp):
    rgb/0010/F.jpg         ← Front camera view
    rgb/0010/B.jpg         ← Back camera view  
    rgb/0010/LF.jpg        ← Left-front view
    rgb/0010/RF.jpg        ← Right-front view
    rgb/0010/LB.jpg        ← Left-back view
    rgb/0010/RB.jpg        ← Right-back view
    rgb/0010/patched.jpg   ← Composite (6 cameras stitched)
    rgb/0010/patched2.jpg  ← Another composite variant
    boxes/0010.json.gz     ← World state (objects in ego-frame)
    measurements/0010.json.gz ← Ego state (speed, position, controls)

Key insight: boxes and measurements are per-FRAME (timestamp), not per-image-file.
All images from frame 0010 share the same boxes/measurements (world state at t=0010).
This is standard for multi-camera autonomous driving datasets (like nuScenes, Waymo).

Output JSON format:
{
    "image": "path/to/rgb/0010.jpg",
    "commentary": "Follow the route. Accelerate to follow the black SUV...",  # LLM-generated
    "commentary_template": "Follow the route. Accelerate to follow the <OBJECT>.",
    "cause_object_visible_in_image": true,
    "cause_object": {...},  # From CARLA boxes
    "cause_object_string": "black SUV that is to the front",
    "scenario_name": "FollowLeadVehicle",
    "placeholder": {"<OBJECT>": "black SUV that is to the front"}
}

Usage examples:
# Process a single image (will auto-load corresponding measurements and boxes)
python /workspace/simlingo/bosch_utils/tools/image_commentary3_todo.py \\
    /path/to/rgb/0000/patched.jpg

# Process entire directory
python /workspace/simlingo/bosch_utils/tools/image_commentary3_todo.py \\
    /path/to/rgb/ --recursive

# Lower GPU usage to avoid OOM
python /workspace/simlingo/bosch_utils/tools/image_commentary3_todo.py \\
    image.jpg --n-gpu-layers 8 --threads 4

# Custom output directory
python /workspace/simlingo/bosch_utils/tools/image_commentary3_todo.py \\
    image.jpg --output-dir /custom/path/commentary
    
# Example of concrete usage
    
python /workspace/simlingo/bosch_utils/tools/image_commentary2_todo.py /media/external_ssd/database/simlingo_v4_2026_01_01/auto_long_multicam_jp/training_Town01_scenario/routes_highway_duration_50_training/SoftRainNoon_weather/ego_42/rgb/0000/patched.jpg -v
python /workspace/simlingo/bosch_utils/tools/image_commentary3_todo.py /media/external_ssd/database/simlingo_v4_2026_01_01/auto_long_multicam_jp/training_Town01_scenario/routes_highway_duration_50_training/SoftRainNoon_weather/ego_42/rgb/0000/patched.jpg -v

python /workspace/simlingo/bosch_utils/tools/image_commentary2_todo.py recording_japan_xml/autopilot_multicamera_japanese_highway_20251212_150258/rgb/0000/
python /workspace/simlingo/bosch_utils/tools/image_commentary3_todo.py recording_japan_xml/autopilot_multicamera_japanese_highway_20251212_150258/rgb/0000/

[Type of file to investigate]: patched2_big.jpg  patched2.jpg  patched2_nuscenes.jpg


"""

import subprocess
import os
import json
import gzip
import time
import argparse
import logging
import sys
import re
import signal
import numpy as np
from pathlib import Path
from typing import Optional, Dict, List, Tuple

try:
    from PIL import Image
    HAS_PIL = True
except Exception:
    HAS_PIL = False

# Default paths (can be overridden via CLI args or environment variables)
DEFAULT_LLAMA_BIN = "/workspace/vla_data_generation/llama.cpp/build/bin/llama-cli"
DEFAULT_MODEL = "/workspace/vla_data_generation/Qwen3VL-32B-Instruct-Q4_K_M.gguf"
DEFAULT_MMPROJ = "/workspace/vla_data_generation/mmproj-Qwen3VL-32B-Instruct-F16.gguf"


class LlamaVisionInference:
    """Wrapper for llama.cpp multimodal inference using llama-server (HTTP API)"""
    
    def __init__(self, 
                 llama_bin: str = DEFAULT_LLAMA_BIN,
                 model_path: str = DEFAULT_MODEL,
                 mmproj_path: str = DEFAULT_MMPROJ,
                 threads: int = 8,
                 ctx_size: int = 4096,
                 n_gpu_layers: int = 16,
                 predict_tokens: int = 512,
                 server_port: int = 8081):
        self.llama_bin = llama_bin
        self.model_path = model_path
        self.mmproj_path = mmproj_path
        self.threads = threads
        self.ctx_size = ctx_size
        self.n_gpu_layers = n_gpu_layers
        self.predict_tokens = predict_tokens
        self.server_port = server_port
        self.server_url = f"http://127.0.0.1:{server_port}"
        self.server_process = None
        
        # Use llama-server instead of llama-cli
        server_bin = Path(llama_bin).parent / "llama-server"
        if not server_bin.exists():
            # Fallback: try finding it
            server_bin = Path(llama_bin).parent / "server"
        if not server_bin.exists():
            raise FileNotFoundError(
                f"llama-server not found. Expected at {server_bin}\\n"
                f"Make sure llama.cpp is compiled with server support."
            )
        self.server_bin = str(server_bin)
        
        # Verify files exist
        if not Path(model_path).exists():
            raise FileNotFoundError(f"Model not found: {model_path}")
        if not Path(mmproj_path).exists():
            raise FileNotFoundError(f"MMProj not found: {mmproj_path}")
        
        # Start the server
        self._start_server()
    
    def generate_commentary(self, image_path: str, retry_on_oom: bool = True) -> Tuple[str, Dict]:
        """
        Generate driving commentary for an image using llama.cpp
        
        Returns:
            (commentary_text, metadata_dict)
        """
        prompt = self._build_driving_prompt()
        
        # Try with decreasing GPU layers if OOM
        layers_to_try = [self.n_gpu_layers, 8, 4, 0] if retry_on_oom else [self.n_gpu_layers]
        
        for gpu_layers in layers_to_try:
            try:
                logging.debug(f"Attempting inference with n_gpu_layers={gpu_layers}")
                output = self._run_llama_inference(image_path, prompt, gpu_layers)
                
                # Extract commentary from output
                commentary = self._extract_commentary(output)
                
                metadata = {
                    'model': Path(self.model_path).name,
                    'n_gpu_layers': gpu_layers,
                    'threads': self.threads,
                    'ctx_size': self.ctx_size,
                    'raw_output': output[:500] if len(output) > 500 else output  # truncate for logging
                }
                
                return commentary, metadata
                
            except subprocess.CalledProcessError as e:
                if 'out of memory' in str(e.stderr).lower() or 'cudaMalloc failed' in str(e.stderr).lower():
                    logging.warning(f"OOM with n_gpu_layers={gpu_layers}, retrying with fewer layers...")
                    continue
                else:
                    raise
            except Exception as e:
                logging.error(f"Inference failed with n_gpu_layers={gpu_layers}: {e}")
                if gpu_layers == layers_to_try[-1]:
                    raise
                continue
        
        raise RuntimeError("All inference attempts failed (OOM or other errors)")
    
    def _build_driving_prompt(self) -> str:
        """Build the prompt for autonomous driving commentary generation"""
        return """<|im_start|>user
<|image|>
You are an expert autonomous (left and right) driving system analyzing a stitched 6-camera surround-view layout: [Front, Front-Left, Front-Right, Rear-Right, Rear-Left, Rear-Center].

Analyze the 360-degree scene and generate a concise driving commentary with clear reasoning and action.

Format your response as:
Commentary: [Concise driving commentary mentioning key objects, their positions (front/rear/left/right), colors, and your driving decision reasoning]
Action: [Single clear action command like "Accelerate to follow the lead vehicle" or "Brake for pedestrian"]

Be specific about object colors, positions, and distances. End your response immediately after the Action line with <|im_end|> token.<|im_end|>
<|im_start|>assistant"""
    
    def _start_server(self):
        """Start llama-server in background if not already running"""
        import urllib.request
        import signal
        
        # Check if server already running
        try:
            req = urllib.request.Request(f"{self.server_url}/health", method='GET')
            urllib.request.urlopen(req, timeout=2)
            logging.info(f"Server already running at {self.server_url}")
            return
        except:
            pass
        
        # Start server
        logging.info(f"Starting llama-server on port {self.server_port}...")
        
        cmd = [
            self.server_bin,
            "-m", self.model_path,
            "--mmproj", self.mmproj_path,
            "-ngl", str(self.n_gpu_layers),
            "-t", str(self.threads),
            "-c", str(self.ctx_size),
            "--port", str(self.server_port),
            "--host", "127.0.0.1",
            "-n", str(self.predict_tokens),
        ]
        
        # Start server in background, suppress output
        self.server_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid if hasattr(os, 'setsid') else None
        )
        
        # Wait for server to be ready
        max_wait = 60
        for i in range(max_wait):
            try:
                time.sleep(1)
                req = urllib.request.Request(f"{self.server_url}/health", method='GET')
                urllib.request.urlopen(req, timeout=2)
                logging.info(f"Server ready after {i+1}s")
                return
            except:
                continue
        
        raise RuntimeError(f"Server failed to start after {max_wait}s")
    
    def _stop_server(self):
        """Stop the llama-server"""
        if self.server_process:
            logging.debug("Stopping llama-server...")
            try:
                os.killpg(os.getpgid(self.server_process.pid), signal.SIGTERM)
            except:
                self.server_process.terminate()
            self.server_process.wait(timeout=10)
    
    def __del__(self):
        """Cleanup: stop server on deletion"""
        self._stop_server()
    
    def _run_llama_inference(self, image_path: str, prompt: str, n_gpu_layers: int) -> str:
        """Run inference via llama-server HTTP API"""
        import urllib.request
        import urllib.parse
        import base64
        
        logging.debug("Encoding image...")
        
        # Read and base64 encode image
        with open(image_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')
        
        # Build request payload for llama-server
        payload = {
            "prompt": prompt,
            "image_data": [{"data": image_data, "id": 10}],
            "n_predict": self.predict_tokens,
            "temperature": 0.7,
            "stop": ["<|im_end|>", "<|endoftext|>"],
            "cache_prompt": True,
        }
        
        logging.debug(f"Sending request to {self.server_url}/completion...")
        
        # Make HTTP POST request
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            f"{self.server_url}/completion",
            data=data,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        
        try:
            response = urllib.request.urlopen(req, timeout=120)
            result = json.loads(response.read().decode('utf-8'))
            
            # Extract generated text
            output = result.get('content', '')
            
            if not output:
                raise RuntimeError(f"Empty response from server: {result}")
            
            logging.debug(f"Generated {len(output)} characters")
            return output
            
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            raise RuntimeError(f"Server error {e.code}: {error_body}")
        except Exception as e:
            raise RuntimeError(f"Request failed: {e}")
    
    def _extract_commentary(self, raw_output: str) -> str:
        """Extract clean commentary from llama.cpp output"""
        # The model output typically contains the full conversation
        # We want to extract the assistant's response after "<|im_start|>assistant"
        
        # Try to find the assistant's response
        if '<|im_start|>assistant' in raw_output:
            parts = raw_output.split('<|im_start|>assistant')
            if len(parts) > 1:
                response = parts[-1].strip()
                # Remove end tokens if present
                response = response.replace('<|im_end|>', '').strip()
                return response
        
        # Fallback: return the full output (cleaned)
        cleaned = raw_output.strip()
        # Remove common prefixes
        for prefix in ['Commentary:', 'Response:', 'Assistant:']:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
                break
        
        return cleaned if cleaned else raw_output.strip()


def load_measurements_for_frame(image_path: str) -> Dict:
    """
    Load corresponding measurements/*.json.gz file for the given rgb image
    
    IMPORTANT: Measurements are per-frame, not per-image file.
    
    Examples:
      Input:  .../rgb/0010.jpg          → Output: .../measurements/0010.json.gz
      Input:  .../rgb/0010/F.jpg        → Output: .../measurements/0010.json.gz
      Input:  .../rgb/0010/patched.jpg  → Output: .../measurements/0010.json.gz
      Input:  .../rgb/0010/patched2.jpg → Output: .../measurements/0010.json.gz
    
    All images from frame 0010 share the same measurements file (ego state at t=0010).
    
    Returns:
        Measurements dictionary with ego state, route, commands, etc.
    """
    try:
        img_path = Path(image_path)
        
        # Extract frame number from path (directory name, not filename)
        if img_path.parent.name == 'rgb':
            # Case 1: image is directly in rgb folder (e.g., rgb/0010.jpg)
            frame_num = img_path.stem  # '0010'
        else:
            # Case 2: image is in rgb/XXXX/ subfolder (e.g., rgb/0010/patched.jpg)
            # The frame number is the directory name, not the image filename
            frame_num = img_path.parent.name  # '0010'
        
        # Navigate to measurements directory
        rgb_parent = img_path.parent if img_path.parent.name == 'rgb' else img_path.parent.parent
        dataset_root = rgb_parent.parent
        measurements_dir = dataset_root / 'measurements'
        measurements_file = measurements_dir / f'{frame_num}.json.gz'
        
        if not measurements_file.exists():
            logging.warning(f"Measurements file not found: {measurements_file}")
            return {}
        
        # Load gzipped JSON
        with gzip.open(measurements_file, 'rt', encoding='utf-8') as f:
            measurements_data = json.load(f)
        
        logging.debug(f"Loaded measurements from {measurements_file.name} for image {img_path.name}")
        return measurements_data
        
    except Exception as e:
        logging.warning(f"Failed to load measurements data: {e}")
        return {}


def load_boxes_for_frame(image_path: str) -> List[Dict]:
    """
    Load corresponding boxes/*.json.gz file for the given rgb image
    
    IMPORTANT: Boxes are per-frame (timestamp), not per-image file.
    Boxes are in ego-frame coordinates and apply to all camera views of that frame.
    
    Examples:
      Input:  .../rgb/0010.jpg          → Output: .../boxes/0010.json.gz
      Input:  .../rgb/0010/F.jpg        → Output: .../boxes/0010.json.gz
      Input:  .../rgb/0010/patched.jpg  → Output: .../boxes/0010.json.gz
      Input:  .../rgb/0010/patched2.jpg → Output: .../boxes/0010.json.gz
    
    All images from frame 0010 share the same boxes file (world state at t=0010).
    
    Returns:
        List of bounding box dictionaries (vehicles, walkers, ego_car, weather, ego_info)
    """
    try:
        img_path = Path(image_path)
        
        # Extract frame number from path (directory name, not filename)
        if img_path.parent.name == 'rgb':
            # Case 1: single image directly in rgb folder (e.g., rgb/0010.jpg)
            frame_num = img_path.stem
        else:
            # Case 2: multi-camera setup with subfolder (e.g., rgb/0010/patched.jpg)
            # The frame number is the directory name, not the image filename
            frame_num = img_path.parent.name
        
        # Navigate to boxes directory
        rgb_parent = img_path.parent if img_path.parent.name == 'rgb' else img_path.parent.parent
        dataset_root = rgb_parent.parent
        boxes_dir = dataset_root / 'boxes'
        boxes_file = boxes_dir / f'{frame_num}.json.gz'
        
        if not boxes_file.exists():
            logging.warning(f"Boxes file not found: {boxes_file}")
            return []
        
        # Load gzipped JSON
        with gzip.open(boxes_file, 'rt', encoding='utf-8') as f:
            boxes_data = json.load(f)
        
        logging.debug(f"Loaded {len(boxes_data)} boxes from {boxes_file.name} for image {img_path.name}")
        return boxes_data
        
    except Exception as e:
        logging.warning(f"Failed to load boxes data: {e}")
        return []


def get_vehicle_appearance_string(vehicle_box: Dict) -> str:
    """Generate natural language description of vehicle from box metadata"""
    if not vehicle_box:
        return "vehicle"
    
    color_name = vehicle_box.get('color_name', '')
    vehicle_type = vehicle_box.get('base_type', 'vehicle')
    
    if color_name:
        return f"{color_name} {vehicle_type}"
    else:
        return vehicle_type


def extract_cause_object_from_measurements_and_boxes(
    measurements: Dict, 
    boxes: List[Dict]
) -> Tuple[Optional[Dict], str, bool, Optional[str]]:
    """
    Extract cause_object from CARLA measurements and boxes data
    
    This follows the logic from carla_commentary_generator.py to determine:
    - What object is causing the ego to adjust speed/behavior
    - Whether that object is visible in the image
    - A natural language description of the object
    - The scenario name
    
    Returns:
        (cause_object_dict, cause_object_string, cause_object_visible, scenario_name)
    """
    cause_object = None
    cause_object_string = ""
    cause_object_visible = False
    scenario_name = None
    
    if not measurements or not boxes:
        return cause_object, cause_object_string, cause_object_visible, scenario_name
    
    # Build lookup dict for boxes by ID
    boxes_by_id = {}
    ego_info_box = None
    
    for box in boxes:
        if box.get('class') == 'ego_info':
            ego_info_box = box
        if 'id' in box:
            boxes_by_id[int(box['id'])] = box
    
    # Get speed reduction info from measurements
    speed_reduced_by_obj_type = measurements.get('speed_reduced_by_obj_type')
    speed_reduced_by_obj_id = measurements.get('speed_reduced_by_obj_id')
    speed_reduced_by_obj_distance = measurements.get('speed_reduced_by_obj_distance')
    
    # Handle stop sign hazard
    if measurements.get('stop_sign_hazard'):
        speed_reduced_by_obj_type = 'traffic.stop'
        cause_object_string = 'stop sign'
        scenario_name = 'StopSign'
        # Stop signs are typically visible infrastructure
        cause_object_visible = True
        return cause_object, cause_object_string, cause_object_visible, scenario_name
    
    # Handle traffic light hazard
    if measurements.get('light_hazard'):
        for box in boxes:
            if box.get('class') == 'traffic_light' and box.get('affects_ego') and box.get('state') == 'Red':
                cause_object = box
                cause_object_string = 'red traffic light'
                cause_object_visible = True
                scenario_name = 'TrafficLight'
                return cause_object, cause_object_string, cause_object_visible, scenario_name
    
    # Handle vehicle hazard
    vehicle_hazard_id = measurements.get('vehicle_affecting_id')
    if vehicle_hazard_id and vehicle_hazard_id in boxes_by_id:
        vehicle_box = boxes_by_id[vehicle_hazard_id]
        cause_object = vehicle_box
        cause_object_string = get_vehicle_appearance_string(vehicle_box)
        # Check visibility heuristics (position in front, has lidar points)
        if vehicle_box.get('num_points', 0) > 3 and vehicle_box.get('position', [0, 0, 0])[0] > -1.5:
            cause_object_visible = True
        scenario_name = 'FollowLeadVehicle'
        return cause_object, cause_object_string, cause_object_visible, scenario_name
    
    # Handle object-based speed reduction
    if speed_reduced_by_obj_id and speed_reduced_by_obj_id in boxes_by_id:
        obj_box = boxes_by_id[speed_reduced_by_obj_id]
        cause_object = obj_box
        
        if 'vehicle' in str(speed_reduced_by_obj_type).lower():
            cause_object_string = get_vehicle_appearance_string(obj_box)
            scenario_name = 'FollowLeadVehicle'
            # Check visibility
            if obj_box.get('num_points', 0) > 3 and obj_box.get('position', [0, 0, 0])[0] > -1.5:
                cause_object_visible = True
        elif 'walker' in str(speed_reduced_by_obj_type).lower():
            cause_object_string = 'pedestrian'
            scenario_name = 'PedestrianCrossing'
            if obj_box.get('num_points', 0) > 3:
                cause_object_visible = True
        
        return cause_object, cause_object_string, cause_object_visible, scenario_name
    
    # Fallback: find closest vehicle in front
    min_distance = float('inf')
    for box in boxes:
        if box.get('class') in ['car', 'vehicle']:
            distance = box.get('distance', float('inf'))
            position = box.get('position', [0, 0, 0])
            # Only consider objects in front
            if distance < min_distance and position[0] > 0:
                min_distance = distance
                cause_object = box
    
    if cause_object:
        cause_object_string = get_vehicle_appearance_string(cause_object)
        if cause_object.get('num_points', 0) > 3 and cause_object.get('position', [0, 0, 0])[0] > -1.5:
            cause_object_visible = True
        scenario_name = 'FollowLeadVehicle'
    
    return cause_object, cause_object_string, cause_object_visible, scenario_name


def process_image(image_path: str, 
                  llama_inference: LlamaVisionInference,
                  output_dir: Optional[str] = None) -> Tuple[Dict, str]:
    """
    Process a single image:
    1. Generate commentary with llama.cpp (multimodal LLM)
    2. Load CARLA measurements and boxes
    3. Extract cause_object and scenario from CARLA data
    4. Save structured output as .json.gz
    
    Returns:
        (metadata_dict, output_path)
    """
    t0 = time.time()
    
    img_path = Path(image_path)
    if not img_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    
    logging.info(f"Processing image: {img_path.name}")
    
    # Load CARLA measurements and boxes
    logging.debug("Loading CARLA measurements and boxes...")
    measurements = load_measurements_for_frame(str(img_path))
    boxes_data = load_boxes_for_frame(str(img_path))
    logging.debug(f"Loaded measurements and {len(boxes_data)} boxes")
    
    # Generate commentary with llama.cpp (LLM-generated natural language)
    logging.info("Generating commentary with llama.cpp...")
    commentary_raw, llama_metadata = llama_inference.generate_commentary(str(img_path))
    
    # Parse the LLM output to extract commentary and action
    commentary_text = commentary_raw
    action_text = ""
    
    if "Action:" in commentary_raw:
        parts = commentary_raw.split("Action:", 1)
        commentary_text = parts[0].replace("Commentary:", "").strip()
        action_text = parts[1].strip().split('\\n')[0].strip()
    elif "Commentary:" in commentary_raw:
        commentary_text = commentary_raw.split("Commentary:", 1)[1].strip()
    
    # Extract cause_object and scenario from CARLA data (following carla_commentary_generator.py logic)
    cause_object, cause_object_string, cause_object_visible, scenario_name = \
        extract_cause_object_from_measurements_and_boxes(measurements, boxes_data)
    
    # Build placeholder dict and template
    placeholder = {}
    commentary_template = commentary_text
    
    if cause_object_string and cause_object_string in commentary_text:
        placeholder['<OBJECT>'] = cause_object_string
        commentary_template = commentary_text.replace(cause_object_string, '<OBJECT>')
    
    # Extract distance placeholders (e.g., "in 15.3 meters" -> "in <DISTANCE>")
    distance_patterns = [
        r'in -?\d+\.\d+ meters',
        r'at -?\d+\.\d+ meters',
    ]
    for pattern in distance_patterns:
        match = re.search(pattern, commentary_text)
        if match:
            placeholder['<DISTANCE>'] = match.group(0)
            commentary_template = re.sub(pattern, lambda m: m.group(0).split()[0] + ' <DISTANCE>', commentary_template)
    
    # Build final structured output (compatible with simlingo training format)
    structured_data = {
        'image': str(img_path),
        'commentary': commentary_text,
        'commentary_template': commentary_template,
        'cause_object_visible_in_image': cause_object_visible,
        'cause_object': cause_object if cause_object else {},
        'cause_object_string': cause_object_string,
        'scenario_name': scenario_name if scenario_name else 'Unknown',
        'placeholder': placeholder,
        'provenance': {
            'generator': 'image_commentary3_todo.py',
            'llama_model': llama_metadata.get('model'),
            'n_gpu_layers': llama_metadata.get('n_gpu_layers'),
            'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'measurements_available': bool(measurements),
            'boxes_count': len(boxes_data),
        }
    }
    
    # Add action if extracted
    if action_text:
        structured_data['action'] = action_text
    
    # Determine output path
    if output_dir:
        out_dir = Path(output_dir)
    else:
        # For simlingo structure: place commentary next to original dataset
        # Input:  .../simlingo_v5.../auto_long_multicam_jp/training_.../ego_42/rgb/0000/patched.jpg
        # Output: .../simlingo_v5.../commentary/auto_long_multicam_jp/training_.../ego_42/rgb/0000.json.gz
        img_dir = img_path.parent
        
        try:
            path_parts = img_path.parts
            # Find the database root (contains 'simlingo')
            simlingo_idx = None
            for i, part in enumerate(path_parts):
                if 'simlingo' in part.lower():
                    simlingo_idx = i
                    break
            
            if simlingo_idx is not None and simlingo_idx + 1 < len(path_parts):
                database_root = Path(*path_parts[:simlingo_idx + 1])
                dataset_type = path_parts[simlingo_idx + 1]
                rest_of_path = path_parts[simlingo_idx + 2:-1]
                
                out_dir = database_root / 'commentary_3' / dataset_type / Path(*rest_of_path)
            else:
                out_dir = img_dir.parent / (img_dir.name + '_commentary_3')
        except Exception:
            out_dir = img_dir.parent / (img_dir.name + '_commentary_3')

    # Ensure output directory exists and is writable
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise PermissionError(f"Cannot create output directory {out_dir}: {e}")

    # Quick writability check
    test_file = out_dir / ('.write_test_' + str(int(time.time())))
    try:
        with open(test_file, 'w') as tf:
            tf.write('ok')
        test_file.unlink()
    except Exception as e:
        raise PermissionError(f"Output directory not writable: {out_dir}: {e}")
    
    # Save as gzipped JSON
    out_name = img_path.stem + '.json.gz'
    out_path = out_dir / out_name
    
    with gzip.open(out_path, 'wt', encoding='utf-8') as f:
        json.dump(structured_data, f, indent=2, ensure_ascii=False)
    
    elapsed = time.time() - t0
    print('=' * 100)
    logging.info(f"✓ Saved commentary to {out_path} ({elapsed:.2f}s)")
    logging.info(f"  Commentary: {commentary_text[:80]}...")
    logging.info(f"  Cause: {cause_object_string} (visible: {cause_object_visible})")
    logging.info(f"  Scenario: {scenario_name}")
    print('=' * 100)
    
    return structured_data, str(out_path)


def process_directory(dir_path: str,
                      llama_inference: LlamaVisionInference,
                      recursive: bool = False,
                      exts: Tuple[str, ...] = ('jpg', 'jpeg', 'png'),
                      output_dir: Optional[str] = None) -> List[Tuple[str, str, Optional[str]]]:
    """
    Process all images in a directory
    
    Returns:
        List of (image_path, output_path, error_msg) tuples
    """
    dir_p = Path(dir_path)
    if not dir_p.is_dir():
        raise NotADirectoryError(f"Not a directory: {dir_path}")
    
    # Find all images
    if recursive:
        images = [p for p in dir_p.rglob('*') if p.is_file() and p.suffix.lower().lstrip('.') in exts]
    else:
        images = [p for p in dir_p.iterdir() if p.is_file() and p.suffix.lower().lstrip('.') in exts]
    
    images = sorted(images)
    logging.info(f"Found {len(images)} images in {dir_path}")
    
    results = []
    for img_path in images:
        try:
            _, out_path = process_image(str(img_path), llama_inference, output_dir)
            results.append((str(img_path), out_path, None))
        except Exception as e:
            logging.error(f"Failed to process {img_path}: {e}")
            results.append((str(img_path), "", str(e)))
    
    return results


def main(argv):
    parser = argparse.ArgumentParser(
        description='Generate driving commentary using llama.cpp + CARLA data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process a single image
  python image_commentary3_todo.py path/to/rgb/0010.jpg
  
  # Process all images in a directory
  python image_commentary3_todo.py path/to/rgb/ --recursive
  
  # Use custom model paths
  python image_commentary3_todo.py image.jpg --model /path/to/model.gguf --mmproj /path/to/mmproj.gguf
  
  # Adjust GPU usage
  python image_commentary3_todo.py image.jpg --n-gpu-layers 8 --threads 4
        """
    )
    
    parser.add_argument('path', help='Image file or directory to process')
    parser.add_argument('--recursive', '-r', action='store_true', help='Process directory recursively')
    parser.add_argument('--ext', default='jpg,jpeg,png', help='Comma-separated image extensions (default: jpg,jpeg,png)')
    
    # Model configuration
    parser.add_argument('--llama-bin', default=DEFAULT_LLAMA_BIN, help=f'Path to llama-completion binary (default: {DEFAULT_LLAMA_BIN})')
    parser.add_argument('--model', default=DEFAULT_MODEL, help=f'Path to GGUF model (default: {DEFAULT_MODEL})')
    parser.add_argument('--mmproj', default=DEFAULT_MMPROJ, help=f'Path to mmproj file (default: {DEFAULT_MMPROJ})')
    
    # Inference parameters
    parser.add_argument('--threads', type=int, default=8, help='Number of threads (default: 8)')
    parser.add_argument('--ctx-size', type=int, default=4096, help='Context size (default: 4096)')
    parser.add_argument('--n-gpu-layers', type=int, default=16, help='Number of GPU layers (default: 16, 0=CPU only)')
    parser.add_argument('--predict', type=int, default=512, help='Max tokens to predict (default: 512)')
    parser.add_argument('--no-retry-oom', action='store_true', help='Disable automatic retry with fewer GPU layers on OOM')
    
    # Processing options
    parser.add_argument('--output-dir', '-o', help='Custom output directory for commentary files')
    
    # Logging
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args(argv[1:])
    
    # Setup logging
    log_level = logging.DEBUG if args.debug else (logging.INFO if args.verbose else logging.WARNING)
    logging.basicConfig(
        level=log_level,
        format='[%(levelname)s] %(message)s'
    )
    
    # Initialize llama inference
    try:
        llama_inference = LlamaVisionInference(
            llama_bin=args.llama_bin,
            model_path=args.model,
            mmproj_path=args.mmproj,
            threads=args.threads,
            ctx_size=args.ctx_size,
            n_gpu_layers=args.n_gpu_layers,
            predict_tokens=args.predict,
        )
    except FileNotFoundError as e:
        logging.error(f"Setup failed: {e}")
        return 1
    
    # Process input path
    input_path = Path(args.path)
    exts = tuple(x.strip().lower() for x in args.ext.split(',') if x.strip())
    
    try:
        if input_path.is_file():
            # Process single image
            _, out_path = process_image(
                str(input_path), 
                llama_inference,
                output_dir=args.output_dir
            )
            logging.info(f"✓ Successfully processed: {out_path}")
            return 0
        
        elif input_path.is_dir():
            # Process directory
            results = process_directory(
                str(input_path),
                llama_inference,
                recursive=args.recursive,
                exts=exts,
                output_dir=args.output_dir
            )
            
            succeeded = sum(1 for _, _, err in results if err is None)
            failed = sum(1 for _, _, err in results if err is not None)
            
            logging.info(f"\\n{'='*60}")
            logging.info(f"Summary: {succeeded} succeeded, {failed} failed out of {len(results)} total")
            logging.info(f"{'='*60}")
            
            return 0 if failed == 0 else 1
        
        else:
            logging.error(f"Path not found or invalid: {input_path}")
            return 1
    
    except KeyboardInterrupt:
        logging.warning("\\nInterrupted by user")
        return 130
    except Exception as e:
        logging.exception(f"Fatal error: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
