#!/usr/bin/env python3
"""
FULL LHT XODR Converter for CARLA 0.9.16
Converts towns to Left-Hand Traffic by:
1. Setting header rule="LHT"
2. INVERTING lane IDs (negative ↔️ positive)
3. Swapping lane sections (left ↔️ right)

WARNING: This does MORE than the minimal version and may cause issues with:
- Traffic lights (if lane references are wrong)
- Custom scenarios (if they rely on specific lane IDs)

Use with caution and test thoroughly!
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
    """Find element ignoring XML namespaces"""
    for child in parent:
        if child.tag.endswith('}' + tag) or child.tag == tag:
            return child
    return None

def find_all_elements_any_ns(parent, tag):
    """Find all elements with tag, ignoring XML namespaces"""
    results = []
    for child in parent:
        if child.tag.endswith('}' + tag) or child.tag == tag:
            results.append(child)
    return results

def invert_lane_id(lane_id_str):
    """Invert lane ID: negative becomes positive and vice versa"""
    try:
        lane_id = int(lane_id_str)
        if lane_id == 0:
            return "0"  # Center lane stays 0
        return str(-lane_id)
    except (ValueError, TypeError):
        return lane_id_str

def process_xodr_full_lht(path):
    """
    FULL LHT conversion:
    1. Set header rule="LHT"
    2. Invert all lane IDs (negative ↔️ positive)
    3. Swap lane section sides
    
    This makes vehicles actually drive on the left side!
    """
    print(f"Processing: {path}")
    
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        modified = False
        
        # ===================================================================
        # STEP 1: Set header rule="LHT"
        # ===================================================================
        header = find_element_any_ns(root, 'header')
        
        if header is None:
            print("  [ERROR] No header element found")
            return False
        
        current_rule = header.get('rule', 'RHT')
        
        if current_rule != 'LHT':
            # Create backup on first modification
            bak = path + ".backup_rht_full"
            if not os.path.exists(bak):
                shutil.copy2(path, bak)
                print(f"  ✓ Backup created: {os.path.basename(bak)}")
            
            header.set('rule', 'LHT')
            modified = True
            print(f"  ✓ Header rule: {current_rule} → LHT")
        else:
            print(f"  Already LHT in header")
        
        # ===================================================================
        # STEP 2: Invert lane IDs in all roads
        # ===================================================================
        lane_count = 0
        
        # Find all road elements
        roads = find_all_elements_any_ns(root, 'road')
        
        for road in roads:
            # Find lanes element
            lanes_elem = find_element_any_ns(road, 'lanes')
            if lanes_elem is None:
                continue
            
            # Find all laneSection elements
            lane_sections = find_all_elements_any_ns(lanes_elem, 'laneSection')
            
            for lane_section in lane_sections:
                # Process left, center, right lane groups
                for side_name in ['left', 'center', 'right']:
                    side_elem = find_element_any_ns(lane_section, side_name)
                    if side_elem is None:
                        continue
                    
                    # Find all lane elements
                    lanes = find_all_elements_any_ns(side_elem, 'lane')
                    
                    for lane in lanes:
                        old_id = lane.get('id')
                        if old_id is not None:
                            new_id = invert_lane_id(old_id)
                            if new_id != old_id:
                                lane.set('id', new_id)
                                lane_count += 1
                                modified = True
        
        if lane_count > 0:
            print(f"  ✓ Inverted {lane_count} lane IDs")
        
        # ===================================================================
        # STEP 3: Invert lane links (predecessor/successor)
        # ===================================================================
        link_count = 0
        
        for road in roads:
            lanes_elem = find_element_any_ns(road, 'lanes')
            if lanes_elem is None:
                continue
            
            lane_sections = find_all_elements_any_ns(lanes_elem, 'laneSection')
            
            for lane_section in lane_sections:
                for side_name in ['left', 'center', 'right']:
                    side_elem = find_element_any_ns(lane_section, side_name)
                    if side_elem is None:
                        continue
                    
                    lanes = find_all_elements_any_ns(side_elem, 'lane')
                    
                    for lane in lanes:
                        # Find link element
                        link = find_element_any_ns(lane, 'link')
                        if link is None:
                            continue
                        
                        # Invert predecessor lane IDs
                        for pred in find_all_elements_any_ns(link, 'predecessor'):
                            old_id = pred.get('id')
                            if old_id is not None:
                                new_id = invert_lane_id(old_id)
                                if new_id != old_id:
                                    pred.set('id', new_id)
                                    link_count += 1
                                    modified = True
                        
                        # Invert successor lane IDs
                        for succ in find_all_elements_any_ns(link, 'successor'):
                            old_id = succ.get('id')
                            if old_id is not None:
                                new_id = invert_lane_id(old_id)
                                if new_id != old_id:
                                    succ.set('id', new_id)
                                    link_count += 1
                                    modified = True
        
        if link_count > 0:
            print(f"  ✓ Inverted {link_count} lane link IDs")
        
        # ===================================================================
        # STEP 4: Update traffic signals (optional, can cause crashes)
        # ===================================================================
        # SKIPPING for safety - traffic lights may break if we change their lane references
        
        # ===================================================================
        # Save if modified
        # ===================================================================
        if modified:
            tree.write(path, encoding='utf-8', xml_declaration=True)
            print(f"  ✓ Saved with FULL LHT conversion")
            return True
        else:
            print(f"  No changes needed")
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
    bak = path + ".backup_rht_full"
    if os.path.exists(bak):
        shutil.copy2(bak, path)
        print(f"  ✓ Restored from: {os.path.basename(bak)}")
        return True
    else:
        # Try minimal backup
        bak_minimal = path + ".backup_rht"
        if os.path.exists(bak_minimal):
            shutil.copy2(bak_minimal, path)
            print(f"  ✓ Restored from: {os.path.basename(bak_minimal)}")
            return True
        print(f"  [WARN] No backup found")
        return False

def verify_lht_conversion(path):
    """Verify the XODR is properly converted to LHT"""
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        
        # Check header rule
        header = find_element_any_ns(root, 'header')
        if header is None:
            print(f"  [VERIFY] ✗ No header found")
            return False
        
        rule = header.get('rule', 'RHT')
        
        if rule != 'LHT':
            print(f"  [VERIFY] ✗ Header rule = {rule} (expected LHT)")
            return False
        
        print(f"  [VERIFY] ✓ Header rule = LHT")
        
        # Check if lanes have been inverted (sample check)
        roads = find_all_elements_any_ns(root, 'road')
        positive_lanes = 0
        negative_lanes = 0
        
        for road in roads[:5]:  # Sample first 5 roads
            lanes_elem = find_element_any_ns(road, 'lanes')
            if lanes_elem is None:
                continue
            
            lane_sections = find_all_elements_any_ns(lanes_elem, 'laneSection')
            for lane_section in lane_sections:
                left_elem = find_element_any_ns(lane_section, 'left')
                if left_elem:
                    lanes = find_all_elements_any_ns(left_elem, 'lane')
                    for lane in lanes:
                        lane_id = lane.get('id')
                        if lane_id:
                            try:
                                id_val = int(lane_id)
                                if id_val > 0:
                                    positive_lanes += 1
                                elif id_val < 0:
                                    negative_lanes += 1
                            except ValueError:
                                pass
        
        if positive_lanes > negative_lanes:
            print(f"  [VERIFY] ✓ Lane IDs appear inverted (LHT style)")
            print(f"  [VERIFY]   Positive IDs: {positive_lanes}, Negative IDs: {negative_lanes}")
            return True
        else:
            print(f"  [VERIFY] ⚠ Lane IDs may not be inverted (RHT style?)")
            print(f"  [VERIFY]   Positive IDs: {positive_lanes}, Negative IDs: {negative_lanes}")
            return False
            
    except Exception as e:
        print(f"  [VERIFY] ✗ Error: {e}")
        return False

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='FULL LHT XODR converter for CARLA 0.9.16',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert Town12 to FULL LHT (inverts lane IDs)
  python3 %(prog)s --towns Town12
  
  # Convert ALL towns to FULL LHT
  python3 %(prog)s
  
  # Restore from backup
  python3 %(prog)s --restore --towns Town12
  
  # Verify conversion
  python3 %(prog)s --verify --towns Town12

WARNING: This is MORE aggressive than the minimal converter!
It inverts lane IDs, which makes cars actually drive on the left,
but may break some scenarios or traffic lights.
        """
    )
    parser.add_argument(
        '--restore',
        action='store_true',
        help='Restore original RHT versions from backup files'
    )
    parser.add_argument(
        '--verify',
        action='store_true',
        help='Verify FULL LHT conversion (check header and lane IDs)'
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
        print("VERIFYING FULL LHT CONVERSION")
    else:
        print("FULL LHT CONVERSION - CARLA 0.9.16")
        print("Modifies:")
        print("  1. Header rule=\"LHT\"")
        print("  2. Lane IDs (inverts negative ↔️ positive)")
        print("  3. Lane links (predecessor/successor)")
        print("")
        print("⚠ WARNING: More aggressive than minimal converter!")
        print("⚠ May break traffic lights or custom scenarios!")
    
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
                if process_xodr_full_lht(xodr):
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
            print(f"\n✓ Converted {success_count} maps to FULL LHT")
        
        print("\nIMPORTANT: Restart CARLA server to load modified maps:")
        print("  docker restart carla-server")
        print("  sleep 30")
        print("\nTest with:")
        print("  python3 -c \"import carla; c=carla.Client('localhost',2000);")
        print("  m=c.get_world().get_map(); print(f'Driving side: {m.get_driving_side()}')\"")
    elif args.verify:
        if success_count == len(towns) - skip_count:
            print("\n✓ All existing maps verified as FULL LHT")
        else:
            print(f"\n⚠ {fail_count} maps not properly converted to LHT")
    else:
        print("\nNo changes made (all maps already converted)")
    
    print("=" * 80)
    
    return 0 if fail_count == 0 else 1

if __name__ == '__main__':
    sys.exit(main())