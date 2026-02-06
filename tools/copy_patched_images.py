#!/usr/bin/env python3
"""
Copy patched2_big.jpg files and rename them to match their parent folder name.

Usage:
    # Process single route directory
    python tools/copy_patched_images.py /path/to/route_folder/rgb
    
    # Process multiple routes
    python tools/copy_patched_images.py /path/to/routes/*/rgb
    
    # Dry run (show what would be copied without actually copying)
    python tools/copy_patched_images.py --dry-run /path/to/route_folder/rgb

Example structure:
    rgb/0000/patched2_big.jpg  ->  rgb/0000.jpg
    rgb/0001/patched2_big.jpg  ->  rgb/0001.jpg
    rgb/0002/patched2_big.jpg  ->  rgb/0002.jpg
"""

import argparse
import shutil
from pathlib import Path
import sys


def copy_patched_images(rgb_dir, dry_run=False, verbose=True):
    """
    Copy patched2_big.jpg files to parent folder with folder name.
    
    Args:
        rgb_dir: Path to rgb directory containing numbered subfolders
        dry_run: If True, only print what would be done without copying
        verbose: If True, print progress
    
    Returns:
        Number of files copied
    """
    rgb_dir = Path(rgb_dir)
    
    if not rgb_dir.exists():
        print(f"Error: Directory not found: {rgb_dir}")
        return 0
    
    if not rgb_dir.is_dir():
        print(f"Error: Not a directory: {rgb_dir}")
        return 0
    
    # Find all subdirectories (should be numbered like 0000, 0001, etc.)
    subdirs = sorted([d for d in rgb_dir.iterdir() if d.is_dir()])
    
    if not subdirs:
        print(f"Warning: No subdirectories found in {rgb_dir}")
        return 0
    
    copied_count = 0
    
    for subdir in subdirs:
        # Source file: subdir/patched2_big.jpg
        source = subdir / "patched2_big.jpg"
        
        # Destination: rgb/subdir_name.jpg
        dest = rgb_dir / f"{subdir.name}.jpg"
        
        if not source.exists():
            if verbose:
                print(f"⚠️  Skip (source missing): {source}")
            continue
        
        if dry_run:
            print(f"[DRY RUN] Would copy: {source} -> {dest}")
            copied_count += 1
        else:
            try:
                shutil.copy2(source, dest)
                if verbose:
                    print(f"✓ Copied: {subdir.name}/patched2_big.jpg -> {dest.name}")
                copied_count += 1
            except Exception as e:
                print(f"✗ Error copying {source}: {e}")
    
    return copied_count


def main():
    parser = argparse.ArgumentParser(
        description="Copy patched2_big.jpg files and rename to parent folder name",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process single route
  python tools/copy_patched_images.py /workspace/simlingo/database/.../rgb

  # Process with dry run
  python tools/copy_patched_images.py --dry-run /path/to/rgb

  # Quiet mode
  python tools/copy_patched_images.py -q /path/to/rgb
        """
    )
    parser.add_argument('rgb_dirs', nargs='+', help='Path(s) to rgb directory/directories')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Show what would be done without actually copying')
    parser.add_argument('-q', '--quiet', action='store_true',
                       help='Only show errors')
    
    args = parser.parse_args()
    
    total_copied = 0
    total_dirs = len(args.rgb_dirs)
    
    for i, rgb_dir_str in enumerate(args.rgb_dirs, 1):
        rgb_dir = Path(rgb_dir_str)
        
        if total_dirs > 1 and not args.quiet:
            print(f"\n[{i}/{total_dirs}] Processing: {rgb_dir}")
            print("-" * 60)
        
        copied = copy_patched_images(
            rgb_dir, 
            dry_run=args.dry_run,
            verbose=not args.quiet
        )
        
        total_copied += copied
        
        if not args.quiet:
            if copied > 0:
                status = "[DRY RUN] " if args.dry_run else ""
                print(f"{status}Processed {copied} images in {rgb_dir}")
            else:
                print(f"No images processed in {rgb_dir}")
    
    # Summary
    if total_dirs > 1:
        print("\n" + "=" * 60)
        action = "Would copy" if args.dry_run else "Copied"
        print(f"Total: {action} {total_copied} images across {total_dirs} directories")
    
    return 0 if total_copied > 0 else 1


if __name__ == '__main__':
    sys.exit(main())
