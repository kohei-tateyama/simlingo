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

def flip_traffic_light_lane_ids(root):
    """
    For LHT, traffic lights reference negative lane IDs (left side lanes).
    This function negates all lane IDs in <signal> and <signalReference> elements.
    """
    changed = 0
    
    for elem in root.iter():
        tag = elem.tag
        # Handle both namespaced and non-namespaced tags
        is_signal = isinstance(tag, str) and (tag.endswith('}signal') or tag == 'signal')
        is_signal_ref = isinstance(tag, str) and (tag.endswith('}signalReference') or tag == 'signalReference')
        
        if is_signal or is_signal_ref:
            # Check for validity elements that contain lane IDs
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

    modified |= ensure_userdata_header(root)
    changed_roads = set_roads_rule_lht(root)
    modified |= (changed_roads > 0)
    
    # Fix traffic light lane IDs for LHT
    changed_signals = flip_traffic_light_lane_ids(root)
    modified |= (changed_signals > 0)

    if modified:
        bak = path + ".backup_rht"
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
            print("  backed up to", bak)
        tree.write(path, encoding='utf-8', xml_declaration=True)
        print(f"  modified (roads: {changed_roads}, traffic signals: {changed_signals})")
    else:
        print("  no changes needed")

def main():
    any_changed = False
    for town in TOWNS:
        # CARLA 0.9.16 has two locations for .xodr files:
        # - Maps/OpenDrive/{town}.xodr (Town01-07, Town10HD)
        # - Maps/{town}/OpenDrive/{town}.xodr (Town12, Town13, Town15)
        xodr = os.path.join(MAPS_DIR, "OpenDrive", f"{town}.xodr")
        if not os.path.isfile(xodr):
            # Try per-town subfolder
            xodr = os.path.join(MAPS_DIR, town, "OpenDrive", f"{town}.xodr")
            if not os.path.isfile(xodr):
                print(f"[WARN] {town}.xodr not found in either location, skipping")
                continue
        try:
            process_xodr(xodr)
            any_changed = True
        except Exception as e:
            print(f"[ERROR] failed to process {xodr}: {e}", file=sys.stderr)
    if any_changed:
        print("Done. Restart CARLA to pick up modified maps.")
    else:
        print("No files changed.")
        
        
        
def verify_lht_conversion(path):
    """Verify the XODR is properly converted to LHT"""
    tree = ET.parse(path)
    root = tree.getroot()
    
    # Check 1: Header has LHT userData
    header = find_element_any_ns(root, 'header')
    has_lht_marker = has_vectorlane_in_header(header) if header else False
    
    # Check 2: Count RHT vs LHT roads
    rht_roads = 0
    lht_roads = 0
    for elem in root.iter():
        if isinstance(elem.tag, str) and (elem.tag.endswith('}road') or elem.tag == 'road'):
            rule = elem.attrib.get('rule', 'RHT')
            if rule == 'LHT':
                lht_roads += 1
            else:
                rht_roads += 1
    
    # Check 3: Traffic light lane IDs
    positive_signal_lanes = 0
    negative_signal_lanes = 0
    for elem in root.iter():
        if isinstance(elem.tag, str) and (elem.tag.endswith('}validity') or elem.tag == 'validity'):
            from_lane = elem.attrib.get('fromLane')
            if from_lane:
                try:
                    val = int(from_lane)
                    if val > 0:
                        positive_signal_lanes += 1
                    else:
                        negative_signal_lanes += 1
                except ValueError:
                    pass
    
    print(f"\n[VERIFY] {os.path.basename(path)}:")
    print(f"  Header userData: {'✓ LHT' if has_lht_marker else '✗ Missing'}")
    print(f"  Roads: {lht_roads} LHT, {rht_roads} RHT")
    print(f"  Traffic signals: {negative_signal_lanes} LHT lanes, {positive_signal_lanes} RHT lanes")
    
    return has_lht_marker and lht_roads > 0 and positive_signal_lanes == 0


if __name__ == '__main__':
    main()

