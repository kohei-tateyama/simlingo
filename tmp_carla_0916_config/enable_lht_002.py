#!/usr/bin/env python3
"""
LHT XODR Converter for CARLA 0.9.16
Converts ALL towns to Left-Hand Traffic by default.
Only modifies header rule - does NOT change traffic lights to prevent map load failures.
"""
import os
import shutil
import sys
import xml.etree.ElementTree as ET

# For host execution (not inside container)
MAPS_DIR = "/workspace/carla0916/CarlaUE4/Content/Carla/Maps"

# ALL towns - convert everything by default
ALL_TOWNS = [
    "Town01","Town01_Opt","Town02","Town02_Opt","Town03","Town03_Opt",
    "Town04","Town04_Opt","Town05","Town05_Opt","Town06","Town06_Opt",
    "Town07","Town07_Opt","Town10HD","Town10HD_Opt","Town12","Town13","Town15",
]

def find_element_any_ns(parent, tag):
    for child in parent:
        if child.tag.endswith('}' + tag) or child.tag == tag:
            return child
    return None

def process_xodr_minimal(path):
    """
    MINIMAL LHT conversion - ONLY sets header rule="LHT"
    
    Does NOT modify (to prevent map loading failures):
    - Traffic light lane IDs
    - Road geometries  
    - Lane sections
    - userData elements
    """
    print(f"Processing: {path}")
    
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        modified = False
        
        # Find header element (handle namespaces)
        header = find_element_any_ns(root, 'header')
        
        if header is None:
            print("  [ERROR] No header element found")
            return False
        
        # Check current rule
        current_rule = header.get('rule', 'RHT')
        
        if current_rule != 'LHT':
            # Create backup on first modification
            bak = path + ".backup_rht"
            if not os.path.exists(bak):
                shutil.copy2(path, bak)
                print(f"  ✓ Backup created: {os.path.basename(bak)}")
            
            # ONLY change header rule
            header.set('rule', 'LHT')
            modified = True
            print(f"  ✓ Header rule: {current_rule} → LHT")
        else:
            print(f"  Already LHT")
        
        if modified:
            # Write with proper XML declaration
            tree.write(path, encoding='utf-8', xml_declaration=True)
            print(f"  ✓ Saved")
            return True
        
        return False
        
    except ET.ParseError as e:
        print(f"  [ERROR] XML parsing failed: {e}")
        return False
    except Exception as e:
        print(f"  [ERROR] {e}")
        import traceback
        traceback.print_exc()
        return False

def restore_from_backup(path):
    """Restore original RHT version from backup"""
    bak = path + ".backup_rht"
    if os.path.exists(bak):
        shutil.copy2(bak, path)
        print(f"  ✓ Restored from: {os.path.basename(bak)}")
        return True
    else:
        print(f"  [WARN] No backup found")
        return False

def verify_lht_conversion(path):
    """Verify the XODR header is set to LHT"""
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        
        # Check header rule
        header = find_element_any_ns(root, 'header')
        if header is None:
            print(f"  [VERIFY] ✗ No header found")
            return False
        
        rule = header.get('rule', 'RHT')
        
        if rule == 'LHT':
            print(f"  [VERIFY] ✓ Header rule = LHT")
            return True
        else:
            print(f"  [VERIFY] ✗ Header rule = {rule} (expected LHT)")
            return False
            
    except Exception as e:
        print(f"  [VERIFY] ✗ Error: {e}")
        return False

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='LHT XODR converter for CARLA 0.9.16 - Converts ALL towns by default',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert ALL towns to LHT
  python3 %(prog)s
  
  # Convert specific towns only
  python3 %(prog)s --towns Town12 Town13
  
  # Restore ALL towns from backups
  python3 %(prog)s --restore
  
  # Verify ALL towns
  python3 %(prog)s --verify
        """
    )
    parser.add_argument(
        '--restore',
        action='store_true',
        help='Restore original RHT versions from .backup_rht files'
    )
    parser.add_argument(
        '--verify',
        action='store_true',
        help='Verify LHT conversion (check header rule only)'
    )
    parser.add_argument(
        '--towns',
        nargs='+',
        help='Specific towns to process (default: ALL towns)'
    )
    
    args = parser.parse_args()
    
    # Process ALL towns by default, or specific ones if requested
    towns = args.towns if args.towns else ALL_TOWNS
    
    print("=" * 80)
    if args.restore:
        print("RESTORING ORIGINAL RHT MAPS")
    elif args.verify:
        print("VERIFYING LHT CONVERSION")
    else:
        print("MINIMAL LHT CONVERSION - CARLA 0.9.16")
        print("Only modifies: <header rule=\"LHT\">")
        print("Does NOT modify: traffic lights, roads, geometry (prevents crashes)")
    
    if args.towns:
        print(f"Processing SPECIFIC towns: {', '.join(towns)}")
    else:
        print(f"Processing ALL {len(towns)} towns")
    
    print("=" * 80)
    print()
    
    success_count = 0
    fail_count = 0
    skip_count = 0
    any_changed = False
    
    for town in towns:
        # CARLA 0.9.16 has two possible locations for .xodr files
        xodr_paths = [
            os.path.join(MAPS_DIR, town, "OpenDrive", f"{town}.xodr"),
            os.path.join(MAPS_DIR, "OpenDrive", f"{town}.xodr"),
        ]
        
        xodr = None
        for candidate in xodr_paths:
            if os.path.isfile(candidate):
                xodr = candidate
                break
        
        if xodr is None:
            print(f"[{town}] NOT FOUND - skipping")
            skip_count += 1
            print()
            continue
        
        try:
            if args.verify:
                if verify_lht_conversion(xodr):
                    success_count += 1
                else:
                    fail_count += 1
            elif args.restore:
                if restore_from_backup(xodr):
                    success_count += 1
                    any_changed = True
                else:
                    fail_count += 1
            else:
                if process_xodr_minimal(xodr):
                    success_count += 1
                    any_changed = True
        
        except Exception as e:
            print(f"  [ERROR] {e}")
            fail_count += 1
        
        print()
    
    print("=" * 80)
    print(f"Results: {success_count} succeeded, {fail_count} failed, {skip_count} skipped")
    
    if any_changed and not args.verify:
        if args.restore:
            print(f"\n✓ Restored {success_count} maps to RHT")
        else:
            print(f"\n✓ Converted {success_count} maps to LHT")
        
        print("\nIMPORTANT: Restart CARLA server to load modified maps:")
        print("  docker restart carla0916")
        print("  # Wait 30 seconds for startup")
        print("  sleep 30")
    elif args.verify:
        if success_count == len(towns) - skip_count:
            print("\n✓ All existing maps verified as LHT")
        else:
            print(f"\n⚠ {fail_count} maps not properly converted to LHT")
    else:
        print("\nNo changes made (all maps already LHT)")
    
    print("=" * 80)
    
    return 0 if fail_count == 0 else 1

if __name__ == '__main__':
    sys.exit(main())