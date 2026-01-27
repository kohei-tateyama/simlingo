# import os
# import shutil
# import sys
# import xml.etree.ElementTree as ET

# # For host execution (not inside container)
# MAPS_DIR = "/workspace/carla0916/CarlaUE4/Content/Carla/Maps"
# TOWNS = [
#     "Town01","Town01_Opt","Town02","Town02_Opt","Town03","Town03_Opt",
#     "Town04","Town04_Opt","Town05","Town05_Opt","Town06","Town06_Opt",
#     "Town07","Town07_Opt","Town10HD","Town10HD_Opt","Town12","Town13","Town15",
# ]

# def find_element_any_ns(parent, tag):
#     for child in parent:
#         if child.tag.endswith('}' + tag) or child.tag == tag:
#             return child
#     return None

# def has_vectorlane_in_header(header):
#     for ud in header:
#         for node in ud:
#             if node.tag.lower().endswith('vectorlane') and node.attrib.get('code','').endswith('carla:lane_direction'):
#                 return True
#     return False

# def ensure_userdata_header(root):
#     header = find_element_any_ns(root, 'header')
#     if header is None:
#         return False
#     if has_vectorlane_in_header(header):
#         return False
#     userData = ET.Element('userData')
#     vectorLane = ET.Element('vectorLane', {'code': 'carla:lane_direction', 'value': 'left'})
#     userData.append(vectorLane)
#     header.append(userData)
#     return True

# def set_roads_rule_lht(root):
#     changed = 0
#     for elem in root.iter():
#         tag = elem.tag
#         if isinstance(tag, str) and (tag.endswith('}road') or tag == 'road'):
#             prev = elem.attrib.get('rule')
#             if prev != 'LHT':
#                 elem.attrib['rule'] = 'LHT'
#                 changed += 1
#     return changed

# def flip_traffic_light_lane_ids(root):
#     """
#     For LHT, traffic lights reference negative lane IDs (left side lanes).
#     This function negates all lane IDs in <signal> and <signalReference> elements.
#     """
#     changed = 0
    
#     for elem in root.iter():
#         tag = elem.tag
#         # Handle both namespaced and non-namespaced tags
#         is_signal = isinstance(tag, str) and (tag.endswith('}signal') or tag == 'signal')
#         is_signal_ref = isinstance(tag, str) and (tag.endswith('}signalReference') or tag == 'signalReference')
        
#         if is_signal or is_signal_ref:
#             # Check for validity elements that contain lane IDs
#             for validity in elem:
#                 validity_tag = validity.tag
#                 if isinstance(validity_tag, str) and (validity_tag.endswith('}validity') or validity_tag == 'validity'):
#                     from_lane = validity.attrib.get('fromLane')
#                     to_lane = validity.attrib.get('toLane')
                    
#                     if from_lane is not None:
#                         try:
#                             old_val = int(from_lane)
#                             new_val = -old_val
#                             validity.attrib['fromLane'] = str(new_val)
#                             changed += 1
#                         except ValueError:
#                             pass
                    
#                     if to_lane is not None:
#                         try:
#                             old_val = int(to_lane)
#                             new_val = -old_val
#                             validity.attrib['toLane'] = str(new_val)
#                             changed += 1
#                         except ValueError:
#                             pass
    
#     return changed

# def process_xodr(path):
#     print("Processing:", path)
#     tree = ET.parse(path)
#     root = tree.getroot()
#     modified = False

#     modified |= ensure_userdata_header(root)
#     changed_roads = set_roads_rule_lht(root)
#     modified |= (changed_roads > 0)
    
#     # Fix traffic light lane IDs for LHT
#     changed_signals = flip_traffic_light_lane_ids(root)
#     modified |= (changed_signals > 0)

#     if modified:
#         bak = path + ".backup_rht"
#         if not os.path.exists(bak):
#             shutil.copy2(path, bak)
#             print("  backed up to", bak)
#         tree.write(path, encoding='utf-8', xml_declaration=True)
#         print(f"  modified (roads: {changed_roads}, traffic signals: {changed_signals})")
#     else:
#         print("  no changes needed")

# def main():
#     any_changed = False
#     for town in TOWNS:
#         # CARLA 0.9.16 has two locations for .xodr files:
#         # - Maps/OpenDrive/{town}.xodr (Town01-07, Town10HD)
#         # - Maps/{town}/OpenDrive/{town}.xodr (Town12, Town13, Town15)
#         xodr = os.path.join(MAPS_DIR, "OpenDrive", f"{town}.xodr")
#         if not os.path.isfile(xodr):
#             # Try per-town subfolder
#             xodr = os.path.join(MAPS_DIR, town, "OpenDrive", f"{town}.xodr")
#             if not os.path.isfile(xodr):
#                 print(f"[WARN] {town}.xodr not found in either location, skipping")
#                 continue
#         try:
#             process_xodr(xodr)
#             any_changed = True
#         except Exception as e:
#             print(f"[ERROR] failed to process {xodr}: {e}", file=sys.stderr)
#     if any_changed:
#         print("Done. Restart CARLA to pick up modified maps.")
#     else:
#         print("No files changed.")

# if __name__ == '__main__':
#     main()


import os
import shutil
import sys
import xml.etree.ElementTree as ET

# For host execution (not inside container)
MAPS_DIR = "/workspace/carla0916/CarlaUE4/Content/Carla/Maps"
TOWNS = [
    "Town01","Town01_Opt","Town02","Town02_Opt","Town03","Town03_Opt",
    "Town04","Town04_Opt","Town05","Town05_Opt","Town06","Town06_Opt",
    "Town07","Town07_Opt","Town10HD","Town10HD_Opt","Town12","Town13","Town15",
]

def find_element_any_ns(parent, tag):
    for child in parent:
        if child.tag.endswith('}' + tag) or child.tag == tag:
            return child
    return None

def has_vectorlane_in_header(header):
    for ud in header:
        for node in ud:
            if node.tag.lower().endswith('vectorlane') and node.attrib.get('code','').endswith('carla:lane_direction'):
                return True
    return False

def ensure_userdata_header(root):
    header = find_element_any_ns(root, 'header')
    if header is None:
        return False
    if has_vectorlane_in_header(header):
        return False
    userData = ET.Element('userData')
    vectorLane = ET.Element('vectorLane', {'code': 'carla:lane_direction', 'value': 'left'})
    userData.append(vectorLane)
    header.append(userData)
    return True

def set_roads_rule_lht(root):
    changed = 0
    for elem in root.iter():
        tag = elem.tag
        if isinstance(tag, str) and (tag.endswith('}road') or tag == 'road'):
            prev = elem.attrib.get('rule')
            if prev != 'LHT':
                elem.attrib['rule'] = 'LHT'
                changed += 1
    return changed

def negate_lane_id(lane_id_str):
    """Negate a lane ID: '1' -> '-1', '-1' -> '1', '0' -> '0'"""
    try:
        lane_id = int(lane_id_str)
        if lane_id == 0:
            return '0'
        return str(-lane_id)
    except (ValueError, TypeError):
        return lane_id_str

def swap_lane_sections(root):
    """
    Swap <left> and <right> lane sections and negate all lane IDs.
    This is the CRITICAL step for converting RHT to LHT geometry.
    """
    changed_sections = 0
    changed_lane_ids = 0
    
    for road in root.iter():
        tag = road.tag
        if not (isinstance(tag, str) and (tag.endswith('}road') or tag == 'road')):
            continue
            
        # Find lanes element
        lanes = find_element_any_ns(road, 'lanes')
        if lanes is None:
            continue
        
        # Process each laneSection
        for laneSection in lanes:
            if not (laneSection.tag.endswith('}laneSection') or laneSection.tag == 'laneSection'):
                continue
            
            left_section = None
            right_section = None
            center_section = None
            
            # Find left, right, center sections
            for child in laneSection:
                if child.tag.endswith('}left') or child.tag == 'left':
                    left_section = child
                elif child.tag.endswith('}right') or child.tag == 'right':
                    right_section = child
                elif child.tag.endswith('}center') or child.tag == 'center':
                    center_section = child
            
            # Skip if both left and right don't exist
            if left_section is None or right_section is None:
                continue
            
            # STEP 1: Swap left and right sections
            laneSection.remove(left_section)
            laneSection.remove(right_section)
            
            # Re-add in swapped order (preserving center in middle)
            # Order matters for XML structure
            laneSection.insert(0, right_section)  # What was right is now left
            if center_section is not None:
                laneSection.remove(center_section)
                laneSection.insert(1, center_section)
                laneSection.insert(2, left_section)  # What was left is now right
            else:
                laneSection.insert(1, left_section)
            
            # Update the tags
            right_section.tag = right_section.tag.replace('right', 'left') if 'right' in right_section.tag else 'left'
            left_section.tag = left_section.tag.replace('left', 'right') if 'left' in left_section.tag else 'right'
            
            changed_sections += 1
            
            # STEP 2: Negate all lane IDs in this laneSection
            for section in [right_section, left_section]:  # Now they're swapped
                for lane in section:
                    if not (lane.tag.endswith('}lane') or lane.tag == 'lane'):
                        continue
                    
                    old_id = lane.attrib.get('id')
                    if old_id:
                        new_id = negate_lane_id(old_id)
                        if new_id != old_id:
                            lane.attrib['id'] = new_id
                            changed_lane_ids += 1
                            
                            # Also update travelDir if present
                            for userData in lane:
                                if not (userData.tag.endswith('}userData') or userData.tag == 'userData'):
                                    continue
                                for vectorLane in userData:
                                    if vectorLane.tag.endswith('}vectorLane') or vectorLane.tag == 'vectorLane':
                                        travel_dir = vectorLane.attrib.get('travelDir')
                                        if travel_dir == 'forward':
                                            vectorLane.attrib['travelDir'] = 'backward'
                                        elif travel_dir == 'backward':
                                            vectorLane.attrib['travelDir'] = 'forward'
    
    print(f"  Swapped {changed_sections} lane sections, negated {changed_lane_ids} lane IDs")
    return changed_sections > 0

def flip_traffic_light_lane_ids(root):
    """
    For LHT, traffic lights reference negative lane IDs (left side lanes).
    This function negates all lane IDs in <signal> and <signalReference> elements.
    """
    changed = 0
    
    for elem in root.iter():
        tag = elem.tag
        is_signal = isinstance(tag, str) and (tag.endswith('}signal') or tag == 'signal')
        is_signal_ref = isinstance(tag, str) and (tag.endswith('}signalReference') or tag == 'signalReference')
        
        if is_signal or is_signal_ref:
            for validity in elem:
                validity_tag = validity.tag
                if isinstance(validity_tag, str) and (validity_tag.endswith('}validity') or validity_tag == 'validity'):
                    from_lane = validity.attrib.get('fromLane')
                    to_lane = validity.attrib.get('toLane')
                    
                    if from_lane is not None:
                        try:
                            old_val = int(from_lane)
                            new_val = -old_val
                            validity.attrib['fromLane'] = str(new_val)
                            changed += 1
                        except ValueError:
                            pass
                    
                    if to_lane is not None:
                        try:
                            old_val = int(to_lane)
                            new_val = -old_val
                            validity.attrib['toLane'] = str(new_val)
                            changed += 1
                        except ValueError:
                            pass
    
    return changed

def process_xodr(path):
    print("Processing:", path)
    tree = ET.parse(path)
    root = tree.getroot()
    modified = False

    # Backup first
    bak = path + ".backup_rht"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
        print("  backed up to", bak)

    # Apply transformations
    modified |= ensure_userdata_header(root)
    
    changed_roads = set_roads_rule_lht(root)
    modified |= (changed_roads > 0)
    
    # **CRITICAL**: Swap lane geometry
    modified |= swap_lane_sections(root)
    
    # Fix traffic light lane IDs
    changed_signals = flip_traffic_light_lane_ids(root)
    modified |= (changed_signals > 0)

    if modified:
        tree.write(path, encoding='utf-8', xml_declaration=True)
        print(f"  ✓ Converted to LHT (roads: {changed_roads}, signals: {changed_signals})")
    else:
        print("  no changes needed")

def main():
    any_changed = False
    for town in TOWNS:
        xodr = os.path.join(MAPS_DIR, "OpenDrive", f"{town}.xodr")
        if not os.path.isfile(xodr):
            xodr = os.path.join(MAPS_DIR, town, "OpenDrive", f"{town}.xodr")
            if not os.path.isfile(xodr):
                print(f"[WARN] {town}.xodr not found in either location, skipping")
                continue
        try:
            process_xodr(xodr)
            any_changed = True
        except Exception as e:
            print(f"[ERROR] failed to process {xodr}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
    
    if any_changed:
        print("\n✓✓✓ Done. Restart CARLA to pick up LHT maps.")
    else:
        print("No files changed.")

if __name__ == '__main__':
    main()