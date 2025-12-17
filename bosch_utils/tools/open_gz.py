import gzip
import json
import os
import argparse
from typing import Any


DEFAULT_SIM = "/workspace/simlingo/database/simlingo_v2_2025_01_10/data/simlingo/training_1_scenario/routes_training/random_weather_seed_1_balanced_150/Town12_Rep0_1000_route0_01_11_15_39_27/"
DEFAULT_OURS = "/workspace/simlingo/recording_japan_xml/autopilot_multicamera_japanese_highway_20251212_150258/"


def short(obj: Any, maxlen: int = 160) -> str:
    s = repr(obj)
    return s if len(s) <= maxlen else s[:maxlen] + '...'


def summarize(obj: Any, indent: int = 2):
    t = type(obj)
    if isinstance(obj, dict):
        print(' ' * indent + f'Dict with {len(obj)} keys:')
        for k in list(obj.keys())[:20]:
            v = obj[k]
            print(' ' * (indent + 2) + f'- {k}: {type(v).__name__}')
        if len(obj) > 20:
            print(' ' * (indent + 2) + f'... ({len(obj)-20} more keys)')
    elif isinstance(obj, list):
        print(' ' * indent + f'List length={len(obj)}')
        if len(obj) > 0:
            first = obj[0]
            print(' ' * (indent + 2) + f'First item type: {type(first).__name__}')
            if isinstance(first, dict):
                print(' ' * (indent + 2) + 'First item keys: ' + ', '.join(list(first.keys())[:20]))
    else:
        print(' ' * indent + f'{type(obj).__name__}: {short(obj)}')


def inspect_gz(path: str):
    if not os.path.exists(path):
        print(f'  MISSING: {path}')
        return
    try:
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f'  ERROR reading {path}: {e}')
        return

    print(f'  Parsed {type(data).__name__} from {os.path.basename(path)}')
    summarize(data, indent=4)
    # For lists, optionally show a compact sample of first few entries
    if isinstance(data, list):
        n = min(3, len(data))
        print('    Sample entries:')
        for i in range(n):
            print(' ' * 6 + f'[{i}] {short(data[i], maxlen=240)}')
    elif isinstance(data, dict):
        # show details for common keys
        for key in ('states', 'meta_data', 'timestamp', 'index', 'route'):
            if key in data:
                print(f'    Key "{key}": type={type(data[key]).__name__}')
                if isinstance(data[key], (list, dict)):
                    summarize(data[key], indent=6)


def inspect_folder(folder: str, label: str):
    print('\n' + '=' * 60)
    print(f'Inspecting {label}: {folder}')
    if not os.path.isdir(folder):
        print('  Not a directory or not found')
        return
    print('  Listing top-level entries:')
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        typ = 'dir' if os.path.isdir(path) else 'file'
        print(f'   - {name} ({typ})')

    # Inspect common files
    for fname in ('records.json.gz', 'results.json.gz'):
        path = os.path.join(folder, fname)
        print(f'\n  -- {fname}')
        inspect_gz(path)


def load_gz_json(path: str):
    if not os.path.exists(path):
        return None
    try:
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def compare_json(a, b, label_a='A', label_b='B', indent=2):
    if a is None or b is None:
        print('Compare: one of the inputs is missing')
        return
    print('\n' + '=' * 60)
    print(f'Comparing {label_a} vs {label_b}')
    # top-level type
    ta, tb = type(a), type(b)
    print(f'  Types: {label_a}={ta.__name__}, {label_b}={tb.__name__}')

    if isinstance(a, dict) and isinstance(b, dict):
        keys_a = set(a.keys())
        keys_b = set(b.keys())
        only_a = sorted(keys_a - keys_b)
        only_b = sorted(keys_b - keys_a)
        both = sorted(keys_a & keys_b)
        if only_a:
            print(f'  Keys only in {label_a}: {only_a}')
        if only_b:
            print(f'  Keys only in {label_b}: {only_b}')
        print(f'  Keys in both ({len(both)}): {both[:20]}{"..." if len(both)>20 else ""}')

        # For common keys, compare types and summary stats
        for k in both:
            va = a[k]
            vb = b[k]
            if type(va) != type(vb):
                print(f'  Key "{k}": type differs: {type(va).__name__} vs {type(vb).__name__}')
                continue
            if isinstance(va, list):
                print(f'  Key "{k}": list lengths {label_a}={len(va)} {label_b}={len(vb)}')
            elif isinstance(va, dict):
                # show small key diffs
                ka = set(va.keys())
                kb = set(vb.keys())
                if ka != kb:
                    onlya = sorted(list(ka - kb))
                    onlyb = sorted(list(kb - ka))
                    if onlya:
                        print(f'    Nested keys only in {label_a}.{k}: {onlya[:10]}')
                    if onlyb:
                        print(f'    Nested keys only in {label_b}.{k}: {onlyb[:10]}')
                else:
                    if len(va) <= 6:
                        print(f'    Nested {k} keys: {list(va.keys())}')
            else:
                # scalar: compare equality
                if va != vb:
                    print(f'  Key "{k}": values differ (sample) {label_a}={short(va,80)} {label_b}={short(vb,80)}')

    elif isinstance(a, list) and isinstance(b, list):
        print(f'  Both are lists: lengths {len(a)} vs {len(b)}')
        n = min(5, len(a), len(b))
        for i in range(n):
            if type(a[i]) != type(b[i]) or a[i] != b[i]:
                print(f'   - First differing index {i}: {short(a[i],120)} vs {short(b[i],120)}')
                break
    else:
        if a != b:
            print('  Different scalar contents (truncated):')
            print('   -', short(a, 200))
            print('   -', short(b, 200))



def main():
    p = argparse.ArgumentParser(description='Inspect records/results json.gz in two folders.')
    p.add_argument('--sim', default=DEFAULT_SIM, help='Path to simlingo dataset folder')
    p.add_argument('--ours', default=DEFAULT_OURS, help='Path to our recordings folder')
    args = p.parse_args()

    inspect_folder(args.sim, 'SIMLINGO')
    inspect_folder(args.ours, 'OURS')


if __name__ == '__main__':
    main()
