#!/usr/bin/env python3
"""
Create a video from images in a directory.
Images are sorted by filename and combined into an MP4 video.
"""
import os
import sys
import glob
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:
    print("ERROR: OpenCV not installed. Install with: pip install opencv-python")
    sys.exit(1)


def create_video_from_images(image_dir, output_video=None, fps=20):
    """
    Create a video from all images in a directory.
    
    Args:
        image_dir: Path to directory containing images
        output_video: Output video path (default: same dir as images with _video.mp4)
        fps: Frames per second for output video
    """
    image_dir = Path(image_dir)
    
    if not image_dir.exists():
        print(f"ERROR: Directory not found: {image_dir}")
        return False
    
    # Find all image files (common formats)
    image_patterns = ['*.png', '*.jpg', '*.jpeg', '*.bmp']
    image_files = []
    for pattern in image_patterns:
        image_files.extend(glob.glob(str(image_dir / pattern)))
    
    if not image_files:
        print(f"ERROR: No images found in {image_dir}")
        return False
    
    # Sort images numerically by extracting the number from filename
    # e.g., "0.png", "5.png", "10.png" -> sorted as 0, 5, 10 (not "0", "10", "5")
    def extract_number(filepath):
        filename = Path(filepath).stem  # Get filename without extension
        try:
            return int(filename)
        except ValueError:
            # If filename is not a number, fall back to string sorting
            return filename
    
    image_files.sort(key=extract_number)
    
    print(f"Found {len(image_files)} images")
    print(f"First image: {Path(image_files[0]).name}")
    print(f"Last image: {Path(image_files[-1]).name}")
    
    # Read first image to get dimensions
    first_img = cv2.imread(image_files[0])
    if first_img is None:
        print(f"ERROR: Could not read first image: {image_files[0]}")
        return False
    
    height, width, _ = first_img.shape
    print(f"Image size: {width}x{height}")
    
    # Default output video path
    if output_video is None:
        output_video = image_dir.parent / f"{image_dir.name}_video.mp4"
    else:
        output_video = Path(output_video)
    
    # Create video writer
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    video_writer = cv2.VideoWriter(str(output_video), fourcc, fps, (width, height))
    
    if not video_writer.isOpened():
        print("ERROR: Could not create video writer")
        return False
    
    print(f"\nCreating video at {fps} FPS...")
    print(f"Output: {output_video}")
    
    # Write images to video
    for i, img_path in enumerate(image_files):
        img = cv2.imread(img_path)
        
        if img is None:
            print(f"WARNING: Could not read image {img_path}, skipping...")
            continue
        
        # Resize if dimensions don't match
        if img.shape[0] != height or img.shape[1] != width:
            img = cv2.resize(img, (width, height))
        
        video_writer.write(img)
        
        # Progress indicator
        if (i + 1) % 10 == 0 or (i + 1) == len(image_files):
            print(f"  Processed {i + 1}/{len(image_files)} images...", end='\r')
    
    print(f"\n✓ Video created successfully!")
    print(f"  Output: {output_video}")
    print(f"  Duration: {len(image_files) / fps:.1f} seconds")
    
    video_writer.release()
    return True


if __name__ == "__main__":
    # Default directory
    default_dir = "/workspace/simlingo/outputs/test_run_port2003/RouteScenario_0_rep0_Town13_ParkingExit_1_6_12_09_16_56_55/debug_viz/simlingo2/iter_013.ckpt/_2025_12_09_16_58_28/images"
    
    # Parse command line arguments
    if len(sys.argv) > 1:
        image_dir = sys.argv[1]
    else:
        image_dir = default_dir
    
    if len(sys.argv) > 2:
        output_video = sys.argv[2]
    else:
        output_video = None
    
    if len(sys.argv) > 3:
        fps = int(sys.argv[3])
    else:
        fps = 20  # Default to 20 FPS (CARLA frame rate)
    
    print("="*60)
    print("Creating video from images")
    print("="*60)
    print(f"Input directory: {image_dir}")
    
    success = create_video_from_images(image_dir, output_video, fps)
    
    sys.exit(0 if success else 1)
