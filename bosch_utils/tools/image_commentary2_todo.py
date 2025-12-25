"""
image_describer2_todo.py
Generate driving commentary for multi-camera images using llama.cpp (Qwen3VL model).

This script combines:
- llama.cpp inference (similar to infer.sh approach)
- JSON output format compatible with simlingo commentary structure
- YOLO detection for object identification (optional)
- Structured driving scene analysis

Output JSON format matches simlingo v2:
{
    "image": "path/to/rgb/0010.jpg",
    "commentary": "Follow the route. Accelerate to follow the black SUV...",
    "commentary_template": "Follow the route. Accelerate to follow the <OBJECT>.",
    "cause_object_visible_in_image": true,
    "cause_object": {...},
    "cause_object_string": "black SUV that is to the front",
    "scenario_name": "FollowLeadVehicle",
    "placeholder": {"<OBJECT>": "black SUV that is to the front"}
}

Requirements:
- llama.cpp compiled with multimodal support (llama-completion binary)
- Qwen3VL model (.gguf) and mmproj file
- PIL (Pillow) for image handling
- Optional: ultralytics (YOLO) for object detection


# Process a single image
python news/image_describer2_todo.py path/to/rgb/0010.jpg

# Process entire directory
python news/image_describer2_todo.py path/to/rgb/ --recursive

# Lower GPU usage to avoid OOM
python news/image_describer2_todo.py image.jpg --n-gpu-layers 8 --threads 4

# Use custom model paths
python news/image_describer2_todo.py image.jpg \
  --model /path/to/model.gguf \
  --mmproj /path/to/mmproj.gguf \
  --llama-bin /path/to/llama-completion

# CPU-only mode
python news/image_describer2_todo.py image.jpg --n-gpu-layers 0

# Custom output directory
python news/image_describer2_todo.py image.jpg --output-dir /custom/path/commentary
"""

import subprocess
import os
import json
import gzip
import time
import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Dict, List, Tuple

try:
    from PIL import Image
    HAS_PIL = True
except Exception:
    HAS_PIL = False

try:
    from ultralytics import YOLO
    HAS_YOLO = True
except Exception:
    HAS_YOLO = False


# Default paths (can be overridden via CLI args or environment variables)
DEFAULT_LLAMA_BIN = "/workspace/vla_data_generation/llama.cpp/build/bin/llama-completion"
DEFAULT_MODEL = "/workspace/vla_data_generation/Qwen3VL-32B-Instruct-Q4_K_M.gguf"
DEFAULT_MMPROJ = "/workspace/vla_data_generation/mmproj-Qwen3VL-32B-Instruct-F16.gguf"


class LlamaVisionInference:
    """Wrapper for llama.cpp multimodal inference"""
    
    def __init__(self, 
                 llama_bin: str = DEFAULT_LLAMA_BIN,
                 model_path: str = DEFAULT_MODEL,
                 mmproj_path: str = DEFAULT_MMPROJ,
                 threads: int = 8,
                 ctx_size: int = 4096,
                 n_gpu_layers: int = 16,
                 predict_tokens: int = 512):
        self.llama_bin = llama_bin
        self.model_path = model_path
        self.mmproj_path = mmproj_path
        self.threads = threads
        self.ctx_size = ctx_size
        self.n_gpu_layers = n_gpu_layers
        self.predict_tokens = predict_tokens
        
        # Verify binary exists
        if not Path(llama_bin).exists():
            raise FileNotFoundError(f"llama binary not found: {llama_bin}")
        if not Path(model_path).exists():
            raise FileNotFoundError(f"Model not found: {model_path}")
        if not Path(mmproj_path).exists():
            raise FileNotFoundError(f"MMProj not found: {mmproj_path}")
    
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
You are an expert autonomous driving perception system. This image is a stitched surround-view layout consisting of 6 cameras: [Front, Front-Left, Front-Right, Rear-Right, Rear-Left, Rear-Center].

Analyze the 360-degree environment and generate a driving commentary. Your response should include:

1. **Surround Analysis**: Identify key objects across all views (vehicles, pedestrians, traffic signs, road markings).
2. **Spatial Risks**: Identify any critical hazards or important traffic elements.
3. **Reasoning**: Explain the driving decision logic based on observed objects and traffic rules.
4. **Action**: Provide a single, clear action command.

Format your response as:
Commentary: [Your full driving commentary with reasoning]
Action: [Single action command like "Accelerate to follow the lead vehicle" or "Brake for pedestrian crossing"]

Focus on being concise but specific. Mention object colors, positions (front/rear/left/right), and relative distances when relevant.<|im_end|>
<|im_start|>assistant"""
    
    def _run_llama_inference(self, image_path: str, prompt: str, n_gpu_layers: int) -> str:
        """Run llama.cpp inference subprocess"""
        cmd = [
            self.llama_bin,
            '--model', self.model_path,
            '--mmproj', self.mmproj_path,
            '--image', image_path,
            '--threads', str(self.threads),
            '--ctx-size', str(self.ctx_size),
            '--n-gpu-layers', str(n_gpu_layers),
            '--predict', str(self.predict_tokens),
            '--prompt', prompt
        ]
        
        logging.debug(f"Running: {' '.join(cmd[:6])}...")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        if result.returncode != 0:
            logging.error(f"llama.cpp failed: {result.stderr}")
            raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
        
        return result.stdout
    
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


def detect_objects_yolo(image_path: str) -> List[Dict]:
    """
    Run YOLO detection on the image (optional)
    
    Returns:
        List of detected objects with bounding boxes and classes
    """
    if not HAS_YOLO:
        return []
    
    try:
        model = YOLO('yolov8n.pt')
        results = model(image_path)[0]
        
        detections = []
        for box in getattr(results, 'boxes', []):
            try:
                cls_id = int(box.cls.cpu().numpy())
                conf = float(box.conf.cpu().numpy())
                xyxy = box.xyxy.cpu().numpy()[0].tolist()
                
                detections.append({
                    'class': results.names[cls_id],
                    'confidence': conf,
                    'bbox': xyxy,  # [x1, y1, x2, y2]
                })
            except Exception as e:
                logging.debug(f"Failed to parse YOLO box: {e}")
                continue
        
        return detections
    except Exception as e:
        logging.warning(f"YOLO detection failed: {e}")
        return []


def parse_commentary_to_structured(commentary: str, image_path: str, detections: List[Dict]) -> Dict:
    """
    Parse the generated commentary into structured simlingo format
    
    This is a simplified version - in production you'd want more sophisticated parsing
    """
    # Extract action if present in format "Action: ..."
    action = ""
    commentary_clean = commentary
    
    if "Action:" in commentary:
        parts = commentary.split("Action:", 1)
        commentary_clean = parts[0].strip()
        action = parts[1].strip().split('\n')[0].strip()
    
    # Try to identify mentioned objects for cause_object
    cause_object = {}
    cause_object_string = ""
    cause_object_visible = False
    
    # Simple heuristic: look for common object mentions
    object_keywords = ['vehicle', 'car', 'suv', 'truck', 'pedestrian', 'cyclist', 'traffic light']
    for keyword in object_keywords:
        if keyword.lower() in commentary.lower():
            cause_object_visible = True
            # Try to find color + object pattern
            words = commentary_clean.lower().split()
            for i, word in enumerate(words):
                if keyword in word and i > 0:
                    # Check if previous word might be a color
                    potential_color = words[i-1]
                    if potential_color in ['black', 'white', 'red', 'blue', 'gray', 'silver', 'green']:
                        cause_object_string = f"{potential_color} {keyword}"
                        break
            if not cause_object_string:
                cause_object_string = keyword
            break
    
    # Build cause_object from YOLO detections if available
    if detections and cause_object_visible:
        # Find most relevant detection (for now, just take first car/vehicle)
        for det in detections:
            if det['class'] in ['car', 'truck', 'bus']:
                cause_object = {
                    'class': det['class'],
                    'confidence': det['confidence'],
                    'bbox': det['bbox'],
                }
                break
    
    # Build placeholder dict
    placeholder = {}
    if cause_object_string:
        placeholder['<OBJECT>'] = cause_object_string
    
    # Create template with placeholders
    commentary_template = commentary_clean
    if cause_object_string:
        commentary_template = commentary_clean.replace(cause_object_string, '<OBJECT>')
    
    # Determine scenario name (simplified heuristic)
    scenario_name = ""
    if "follow" in commentary.lower():
        scenario_name = "FollowLeadVehicle"
    elif "lane change" in commentary.lower():
        scenario_name = "LaneChange"
    elif "turn" in commentary.lower():
        scenario_name = "Turning"
    elif "stop" in commentary.lower() or "brake" in commentary.lower():
        scenario_name = "EmergencyBraking"
    else:
        scenario_name = "RouteFollowing"
    
    return {
        'image': image_path,
        'commentary': commentary_clean,
        'commentary_template': commentary_template,
        'cause_object_visible_in_image': cause_object_visible,
        'cause_object': cause_object,
        'cause_object_string': cause_object_string,
        'scenario_name': scenario_name,
        'placeholder': placeholder,
    }


def process_image(image_path: str, 
                  llama_inference: LlamaVisionInference,
                  use_yolo: bool = True,
                  output_dir: Optional[str] = None) -> Tuple[Dict, str]:
    """
    Process a single image: generate commentary and save as .json.gz
    
    Returns:
        (metadata_dict, output_path)
    """
    t0 = time.time()
    
    img_path = Path(image_path)
    if not img_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    
    logging.info(f"Processing image: {img_path.name}")
    
    # Run YOLO detection if enabled
    detections = []
    if use_yolo and HAS_YOLO:
        logging.debug("Running YOLO detection...")
        detections = detect_objects_yolo(str(img_path))
        logging.debug(f"Detected {len(detections)} objects")
    
    # Generate commentary with llama.cpp
    logging.info("Generating commentary with llama.cpp...")
    commentary, llama_metadata = llama_inference.generate_commentary(str(img_path))
    
    # Parse to structured format
    structured_data = parse_commentary_to_structured(commentary, str(img_path), detections)
    
    # Add metadata
    structured_data['provenance'] = {
        'generator': 'image_describer2_todo.py',
        'llama_model': llama_metadata.get('model'),
        'n_gpu_layers': llama_metadata.get('n_gpu_layers'),
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'detections_count': len(detections),
    }
    
    # Determine output path
    if output_dir:
        out_dir = Path(output_dir)
    else:
        # Place commentary folder next to the image folder.
        # Use Path operations rather than string concatenation to avoid ambiguous paths.
        img_dir = img_path.parent
        out_dir = img_dir.parent / (img_dir.name + '_commentary')

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
    logging.info(f"Saved commentary to {out_path} ({elapsed:.2f}s)")
    
    return structured_data, str(out_path)


def process_directory(dir_path: str,
                      llama_inference: LlamaVisionInference,
                      recursive: bool = False,
                      exts: Tuple[str, ...] = ('jpg', 'jpeg', 'png'),
                      use_yolo: bool = True,
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
            _, out_path = process_image(str(img_path), llama_inference, use_yolo, output_dir)
            results.append((str(img_path), out_path, None))
        except Exception as e:
            logging.error(f"Failed to process {img_path}: {e}")
            results.append((str(img_path), "", str(e)))
    
    return results


def main(argv):
    parser = argparse.ArgumentParser(
        description='Generate driving commentary for images using llama.cpp (Qwen3VL)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process a single image
  python image_describer2_todo.py path/to/rgb/0010.jpg
  
  # Process all images in a directory
  python image_describer2_todo.py path/to/rgb/ --recursive
  
  # Use custom model paths
  python image_describer2_todo.py image.jpg --model /path/to/model.gguf --mmproj /path/to/mmproj.gguf
  
  # Adjust GPU usage
  python image_describer2_todo.py image.jpg --n-gpu-layers 8 --threads 4
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
    parser.add_argument('--no-yolo', action='store_true', help='Disable YOLO object detection')
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
    use_yolo = not args.no_yolo
    
    try:
        if input_path.is_file():
            # Process single image
            _, out_path = process_image(
                str(input_path), 
                llama_inference,
                use_yolo=use_yolo,
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
                use_yolo=use_yolo,
                output_dir=args.output_dir
            )
            
            succeeded = sum(1 for _, _, err in results if err is None)
            failed = sum(1 for _, _, err in results if err is not None)
            
            logging.info(f"\n{'='*60}")
            logging.info(f"Summary: {succeeded} succeeded, {failed} failed out of {len(results)} total")
            logging.info(f"{'='*60}")
            
            return 0 if failed == 0 else 1
        
        else:
            logging.error(f"Path not found or invalid: {input_path}")
            return 1
    
    except KeyboardInterrupt:
        logging.warning("\nInterrupted by user")
        return 130
    except Exception as e:
        logging.exception(f"Fatal error: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
