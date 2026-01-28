#!/usr/bin/env python3
"""
Flip scenario directions in route XML files for LHT conversion.
Handles both simple direction flips and scenario-specific adjustments.
Creates output file: <input>_LHT.xml

If no input files specified, processes ALL .xml files in current directory.
"""
import xml.etree.ElementTree as ET
import sys
import os
import glob
import shutil
import argparse

# Scenarios safe to flip directly
SAFE_TO_FLIP = {
    'ParkingExit',
    'ParkingCutIn', 
    'ControlLoss',
    'EnterActorFlow',
    'MergerIntoSlowTraffic',
}

# Scenarios that need special handling
NEEDS_REVIEW = {
    'OppositeVehicleRunningRedLight': 'Lane configuration differs in LHT',
    'HazardAtSideLane': 'Side lanes are mirrored in LHT',
    'VehicleTurningRoute': 'Turn logic is different',
    'VehicleTurningRoutePedestrian': 'Turn logic is different',
    'NonSignalizedJunctionLeftTurn': 'Priority rules differ in LHT',
    'NonSignalizedJunctionRightTurn': 'Priority rules differ in LHT',
}

# Scenarios that work fine without modification
NO_CHANGE_NEEDED = {
    'Accident',
    'AccidentTwoWays',
    'BlockedIntersection',
    'ConstructionObstacle',
    'ConstructionObstacleTwoWays',
    'DynamicObjectCrossing',
    'HardBreakRoute',
    'ParkedObstacleTwoWays',
    'SignalizedJunctionLeftTurn',
    'SignalizedJunctionRightTurn',
    'VehicleOpensDoorTwoWays',
}

def flip_direction(value):
    """Flip left ↔ right"""
    if value == 'right':
        return 'left'
    elif value == 'left':
        return 'right'
    return value

def convert_route_to_lht(input_file, output_file, force=False, verbose=True):
    """Convert RHT route XML to LHT"""
    
    if verbose:
        print("="*80)
        print(f"Processing: {os.path.basename(input_file)}")
        print("="*80)
        print(f"Input:  {input_file}")
        print(f"Output: {output_file}")
        print("-"*80)
    
    tree = ET.parse(input_file)
    root = tree.getroot()
    
    stats = {
        'flipped': 0,
        'needs_review': 0,
        'no_change': 0,
        'unknown': 0,
    }
    
    warnings = []
    
    for route in root.findall('.//route'):
        route_id = route.get('id', 'unknown')
        town = route.get('town', 'unknown')
        
        if verbose:
            print(f"\n[Route {route_id}] Town: {town}")
        
        for scenario in route.findall('.//scenario'):
            name = scenario.get('name', '')
            stype = scenario.get('type', '')
            
            # Find direction element
            direction_elem = scenario.find('direction')
            
            if direction_elem is not None:
                current = direction_elem.get('value', '')
                
                # Determine action
                if stype in SAFE_TO_FLIP or force:
                    new_value = flip_direction(current)
                    direction_elem.set('value', new_value)
                    if verbose:
                        print(f"  ✓ {name} ({stype}): {current} → {new_value}")
                    stats['flipped'] += 1
                    
                elif stype in NEEDS_REVIEW:
                    reason = NEEDS_REVIEW[stype]
                    warning = f"  ⚠ {name} ({stype}): direction='{current}' - {reason}"
                    if verbose:
                        print(warning)
                    warnings.append(warning)
                    stats['needs_review'] += 1
                    
                    if force:
                        new_value = flip_direction(current)
                        direction_elem.set('value', new_value)
                        if verbose:
                            print(f"    → FORCED: {current} → {new_value}")
                        stats['flipped'] += 1
                
                else:
                    # Unknown scenario type
                    warning = f"  ? {name} ({stype}): unknown type with direction='{current}'"
                    if verbose:
                        print(warning)
                    warnings.append(warning)
                    stats['unknown'] += 1
                    
                    if force:
                        new_value = flip_direction(current)
                        direction_elem.set('value', new_value)
                        if verbose:
                            print(f"    → FORCED: {current} → {new_value}")
            
            else:
                # No direction element
                if stype in NO_CHANGE_NEEDED:
                    if verbose:
                        print(f"  · {name} ({stype}): no direction (OK)")
                    stats['no_change'] += 1
                elif stype not in SAFE_TO_FLIP and stype not in NEEDS_REVIEW:
                    if verbose:
                        print(f"  · {name} ({stype}): no direction element")
    
    # Summary
    if verbose:
        print("\n" + "-"*80)
        print("SUMMARY:")
        print(f"  Flipped: {stats['flipped']}")
        print(f"  Needs review: {stats['needs_review']}")
        print(f"  No change needed: {stats['no_change']}")
        print(f"  Unknown types: {stats['unknown']}")
    
    # Save
    tree.write(output_file, encoding='utf-8', xml_declaration=True)
    
    if verbose:
        print(f"\n✓ Saved to: {output_file}")
        print("="*80 + "\n")
    
    return stats

def get_lht_output_filename(input_file):
    """Generate output filename: <input>_LHT.xml"""
    base = os.path.basename(input_file)
    dirname = os.path.dirname(input_file)
    
    # Remove .xml extension
    if base.endswith('.xml'):
        base = base[:-4]
    
    # Add _LHT suffix
    lht_base = base + '_LHT.xml'
    
    # Combine with directory
    if dirname:
        return os.path.join(dirname, lht_base)
    else:
        return lht_base

def find_route_xml_files(directory='.'):
    """Find all route XML files, excluding already-converted LHT files"""
    all_xml = glob.glob(os.path.join(directory, '*.xml'))
    
    # Exclude files that are already LHT versions or backups
    route_files = [
        f for f in all_xml 
        if not f.endswith('_LHT.xml') 
        and not f.endswith('.backup_RHT')
        and 'routes' in os.path.basename(f).lower()
    ]
    
    return sorted(route_files)

def main():
    parser = argparse.ArgumentParser(
        description='Convert route XML files from RHT to LHT (creates <input>_LHT.xml)\n'
                    'If no files specified, processes ALL route XML files in current directory.\n'
                    'The main idea is to check this string in any .xml <direction value="..."/> and replace right <-> left',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert ALL route XML files in current directory
  python3 flip_route_directions_lht.py
  
  # Convert specific file
  python3 flip_route_directions_lht.py routes_training.xml
  
  # Convert multiple files
  python3 flip_route_directions_lht.py routes_training.xml routes_devtest.xml
  
  # Force flip ALL directions (use with caution)
  python3 flip_route_directions_lht.py --force
  
  # Specify custom output file (single input only)
  python3 flip_route_directions_lht.py routes_training.xml -o my_lht_routes.xml
        """
    )
    
    parser.add_argument('input', nargs='*', help='Input route XML file(s). If omitted, processes all routes_*.xml files.')
    parser.add_argument('-o', '--output', help='Output file (default: <input>_LHT.xml, only for single input)')
    parser.add_argument('--force', action='store_true', 
                       help='Force flip all directions, even uncertain ones')
    parser.add_argument('--no-backup', action='store_true',
                       help='Do not create backup of input files')
    parser.add_argument('-q', '--quiet', action='store_true',
                       help='Quiet mode - minimal output')
    
    args = parser.parse_args()
    
    # If no input files specified, find all route XML files
    if not args.input:
        args.input = find_route_xml_files()
        
        if not args.input:
            print("ERROR: No route XML files found in current directory")
            print("Looking for files matching: routes*.xml (excluding *_LHT.xml)")
            return 1
        
        print("="*80)
        print(f"No input specified - processing ALL {len(args.input)} route files:")
        for f in args.input:
            print(f"  - {os.path.basename(f)}")
        print("="*80)
        
        if not args.force:
            response = input("\nProceed? [Y/n]: ")
            if response.lower() in ['n', 'no']:
                print("Aborted.")
                return 0
        print()
    
    # Handle multiple input files
    if len(args.input) > 1:
        if args.output:
            print("ERROR: Cannot specify --output with multiple input files")
            return 1
        
        total_stats = {
            'flipped': 0,
            'needs_review': 0,
            'no_change': 0,
            'unknown': 0,
        }
        
        processed = 0
        failed = 0
        
        for input_file in args.input:
            output_file = get_lht_output_filename(input_file)
            
            # Backup
            if not args.no_backup:
                backup = input_file + '.backup_RHT'
                if not os.path.exists(backup):
                    shutil.copy2(input_file, backup)
                    if not args.quiet:
                        print(f"Backup: {backup}")
            
            try:
                stats = convert_route_to_lht(input_file, output_file, force=args.force, verbose=not args.quiet)
                
                # Accumulate stats
                for key in total_stats:
                    total_stats[key] += stats[key]
                
                processed += 1
                
            except Exception as e:
                print(f"ERROR processing {input_file}: {e}")
                failed += 1
        
        # Overall summary
        print("\n" + "="*80)
        print("OVERALL SUMMARY:")
        print(f"  Files processed: {processed}")
        print(f"  Files failed: {failed}")
        print(f"  Total flipped: {total_stats['flipped']}")
        print(f"  Total needs review: {total_stats['needs_review']}")
        print(f"  Total no change: {total_stats['no_change']}")
        print(f"  Total unknown: {total_stats['unknown']}")
        print("="*80)
        
        if total_stats['needs_review'] > 0 and not args.force:
            print(f"\n⚠ {total_stats['needs_review']} scenarios need manual review")
            print("  Run with --force to flip all directions anyway")
        
        return 0
    
    # Single input file
    input_file = args.input[0]
    
    # Determine output file
    if args.output:
        output_file = args.output
    else:
        output_file = get_lht_output_filename(input_file)
    
    # Check if files exist
    if not os.path.exists(input_file):
        print(f"ERROR: Input file not found: {input_file}")
        return 1
    
    if os.path.exists(output_file) and not args.quiet:
        print(f"WARNING: Output file already exists: {output_file}")
        response = input("Overwrite? [y/N]: ")
        if response.lower() not in ['y', 'yes']:
            print("Aborted.")
            return 0
    
    # Backup
    if not args.no_backup:
        backup = input_file + '.backup_RHT'
        if not os.path.exists(backup):
            shutil.copy2(input_file, backup)
            if not args.quiet:
                print(f"Backup: {backup}\n")
    
    # Convert
    try:
        stats = convert_route_to_lht(input_file, output_file, force=args.force, verbose=not args.quiet)
        
        if stats['needs_review'] > 0 and not args.force:
            print(f"\n⚠ {stats['needs_review']} scenarios need manual review")
            print(f"  Run with --force to flip all: python3 {sys.argv[0]} {input_file} --force")
        
        return 0
        
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())