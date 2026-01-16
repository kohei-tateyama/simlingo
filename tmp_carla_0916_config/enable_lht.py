#!/usr/bin/env python3
"""
Idempotently set OpenDrive roads to LHT and inject CARLA userData vectorLane tag.

This script creates a backup <file>.backup_rht the first time it modifies a file.
"""
import os
import shutil
import sys
import xml.etree.ElementTree as ET

# Adjust maps dir if CARLA is installed elsewhere in the container
MAPS_DIR = "/workspace/CarlaUE4/Content/Carla/Maps"
TOWNS = [
    "Town01","Town02","Town03","Town04","Town05","Town06","Town07","Town10HD","Town12","Town13",
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

def process_xodr(path):
    print("Processing:", path)
    tree = ET.parse(path)
    root = tree.getroot()
    modified = False

    modified |= ensure_userdata_header(root)
    changed_roads = set_roads_rule_lht(root)
    modified |= (changed_roads > 0)

    if modified:
        bak = path + ".backup_rht"
        if not os.path.exists(bak):
            shutil.copy2(path, bak)
            print("  backed up to", bak)
        tree.write(path, encoding='utf-8', xml_declaration=True)
        print(f"  modified (roads updated: {changed_roads})")
    else:
        print("  no changes needed")

def main():
    any_changed = False
    for town in TOWNS:
        xodr = os.path.join(MAPS_DIR, town, "OpenDrive", f"{town}.xodr")
        if not os.path.isfile(xodr):
            print(f"[WARN] {xodr} not found, skipping")
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

if __name__ == '__main__':
    main()
