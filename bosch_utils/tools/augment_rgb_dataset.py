"""
Simple dataset augmentation utility.

Usage:
  python bosch_utils/tools/augment_rgb_dataset.py /path/to/ego_43/rgb

"""
import sys
import os
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter
import random


def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def list_frame_dirs(rgb_dir: Path):
    return sorted([p for p in rgb_dir.iterdir() if p.is_dir()])

def augment_image(img: Image.Image):
    """Apply a sequence of randomized augmentations and return the augmented PIL image.

    Augmentations (each applied with some probability):
    - **Brightness jitter:** applied with probability 0.9. Factor sampled uniformly from `0.8` to `1.2` (values <1 darken, >1 brighten).
    - **Contrast jitter:** applied with probability 0.9. Factor sampled uniformly from `0.85` to `1.25`.
    - **Color (saturation) jitter:** applied with probability 0.6. Factor sampled uniformly from `0.9` to `1.1` (slight desaturation/saturation).
    - **Gaussian blur:** applied with probability 0.25. Radius sampled uniformly from `0.2` to `1.2` pixels (very mild blur to simulate small defocus/motion).
    - **Horizontal flip:** applied rarely with probability 0.05 (useful only if your model is invariant to left/right — use with care for driving tasks).

    """
    # Convert to RGB just in case
    img = img.convert('RGB')

    # Brightness
    if random.random() < 0.9:
        factor = random.uniform(0.8, 1.2)
        img = ImageEnhance.Brightness(img).enhance(factor)

    # Contrast
    if random.random() < 0.9:
        factor = random.uniform(0.85, 1.25)
        img = ImageEnhance.Contrast(img).enhance(factor)

    # Color
    if random.random() < 0.6:
        factor = random.uniform(0.9, 1.1)
        img = ImageEnhance.Color(img).enhance(factor)

    # Small gaussian blur
    if random.random() < 0.25:
        radius = random.uniform(0.2, 1.2)
        img = img.filter(ImageFilter.GaussianBlur(radius))

    # Horizontal flip (rare)
    if random.random() < 0.05:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)

    return img


def process_frame_dir(frame_dir: Path, out_frame_dir: Path, exts=('.jpg', '.jpeg', '.png')):
    ensure_dir(out_frame_dir)
    files = [p for p in frame_dir.iterdir() if p.suffix.lower() in exts]
    for f in files:
        try:
            img = Image.open(f)
        except Exception:
            continue

        aug = augment_image(img)
        out_path = out_frame_dir / f.name
        try:
            # Save as JPEG if original was JPEG, otherwise keep PNG
            if f.suffix.lower() in ('.jpg', '.jpeg'):
                aug.save(out_path, format='JPEG', quality=90)
            else:
                aug.save(out_path, format='PNG', compress_level=6)
        except Exception:
            aug.save(out_path)


def main(argv):
    if len(argv) < 2:
        print('[INFO]: Usage: augment_rgb_dataset.py /path/to/<run>/rgb')
        return 2

    rgb_dir = Path(argv[1])
    if not rgb_dir.exists() or not rgb_dir.is_dir():
        print('[ERROR]: rgb directory not found:', rgb_dir)
        return 2

    out_base = rgb_dir.parent / 'rgb_augmented'
    ensure_dir(out_base)

    frame_dirs = list_frame_dirs(rgb_dir)
    if not frame_dirs:
        print('[ERROR]: No frame directories found in', rgb_dir)
        return 1

    for frame in frame_dirs:
        out_frame = out_base / frame.name
        process_frame_dir(frame, out_frame)

    print('[INFO]: Augmentation complete. Output:', out_base)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
