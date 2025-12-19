"""Compare structure (not values) of measurements, boxes and debug.log between two run folders.

Usage:
  python compare_structure.py --a PATH_A --b PATH_B

This prints counts, filename differences, and top-level JSON keys/types for a small sample of files.
"""
import os
import gzip
import json
import argparse
from typing import Any, Dict, List
from bosch_utils import config as _cfg

# Defaults come from configuration YAML; fall back to None if not set
DEFAULT_SIM = _cfg.DEFAULT_SIM
DEFAULT_OURS = _cfg.DEFAULT_OURS

def load_gz_json(path: str):
    try:
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def top_level_keys(obj: Any) -> Dict[str, str]:
    if isinstance(obj, dict):
        return {k: type(v).__name__ for k, v in obj.items()}
    return {}


def list_json_gz(path: str) -> List[str]:
    if not os.path.isdir(path):
        return []
    files = [f for f in os.listdir(path) if f.endswith('.json.gz')]
    files.sort()
    return files


def compare_folder(a: str, b: str, sub: str, sample_n: int = 5):
    pa = os.path.join(a, sub)
    pb = os.path.join(b, sub)
    print('\n' + '=' * 40)
    print(f'Comparing subfolder: {sub}')
    print(f' A: {pa}')
    print(f' B: {pb}')

    fa = list_json_gz(pa)
    fb = list_json_gz(pb)

    print(f'  Count A={len(fa)} B={len(fb)}')

    only_a = sorted(set(fa) - set(fb))
    only_b = sorted(set(fb) - set(fa))
    common = sorted(set(fa) & set(fb))

    if only_a:
        print(f'  Files only in A (sample 10): {only_a[:10]}')
    if only_b:
        print(f'  Files only in B (sample 10): {only_b[:10]}')
    print(f'  Common files: {len(common)} (showing up to {sample_n})')

    # examine samples from common
    for i, fname in enumerate(common[:sample_n]):
        path_a = os.path.join(pa, fname)
        path_b = os.path.join(pb, fname)
        ja = load_gz_json(path_a)
        jb = load_gz_json(path_b)
        print(f'\n  Sample file: {fname}')
        if ja is None:
            print('    A: failed to read or parse')
        else:
            ka = top_level_keys(ja)
            print(f'    A keys ({len(ka)}): {list(ka.keys())[:20]}')
        if jb is None:
            print('    B: failed to read or parse')
        else:
            kb = top_level_keys(jb)
            print(f'    B keys ({len(kb)}): {list(kb.keys())[:20]}')

        if ja is not None and jb is not None:
            onlya = sorted(set(ka.keys()) - set(kb.keys()))
            onlyb = sorted(set(kb.keys()) - set(ka.keys()))
            if onlya:
                print(f'    Keys only in A: {onlya[:10]}')
            if onlyb:
                print(f'    Keys only in B: {onlyb[:10]}')

    # If there are files only in one side, show one sample's keys
    if only_a:
        sample = only_a[:min(3, len(only_a))]
        print('\n  Sample keys from files only in A:')
        for fname in sample:
            ja = load_gz_json(os.path.join(pa, fname))
            print(f'    {fname}:', list(top_level_keys(ja).keys())[:20] if ja else 'read-failed')

    if only_b:
        sample = only_b[:min(3, len(only_b))]
        print('\n  Sample keys from files only in B:')
        for fname in sample:
            jb = load_gz_json(os.path.join(pb, fname))
            print(f'    {fname}:', list(top_level_keys(jb).keys())[:20] if jb else 'read-failed')


def compare_debug(a: str, b: str, lines: int = 5):
    pa = os.path.join(a, 'debug.log')
    pb = os.path.join(b, 'debug.log')
    print('\n' + '=' * 40)
    print('Comparing debug.log')
    ea = os.path.exists(pa)
    eb = os.path.exists(pb)
    print(f'  A has debug.log: {ea}, B has debug.log: {eb}')
    if ea:
        try:
            with open(pa, 'rt', encoding='utf-8', errors='replace') as f:
                lines_a = [l.rstrip('\n') for l in f.readlines()]
            print(f'    A: size={os.path.getsize(pa)} bytes, lines={len(lines_a)}')
            print('    A head:')
            for l in lines_a[:lines]:
                print('      ', l)
        except Exception as e:
            print('    A: read error', e)
    if eb:
        try:
            with open(pb, 'rt', encoding='utf-8', errors='replace') as f:
                lines_b = [l.rstrip('\n') for l in f.readlines()]
            print(f'    B: size={os.path.getsize(pb)} bytes, lines={len(lines_b)}')
            print('    B head:')
            for l in lines_b[:lines]:
                print('      ', l)
        except Exception as e:
            print('    B: read error', e)


def main():
    p = argparse.ArgumentParser(description='Compare structure of run folders')
    p.add_argument('--a', help='First run folder')
    p.add_argument('--b', help='Second run folder')
    p.add_argument('--sample', type=int, default=5, help='Number of sample files to compare')
    args = p.parse_args()

    # Sensible defaults so the script can be run without arguments
    if not args.a:
        args.a = DEFAULT_OURS
    if not args.b:
        args.b = DEFAULT_SIM

    for sub in ('measurements', 'boxes'):
        compare_folder(args.a, args.b, sub, sample_n=args.sample)

    compare_debug(args.a, args.b)


if __name__ == '__main__':
    main()


