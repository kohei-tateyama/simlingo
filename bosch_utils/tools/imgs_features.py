import os, sys, glob, math
from PIL import Image
import numpy as np
import cv2

# python3 simlingo/bosch_utils/imgs_features.py [ROOT_OURS] [ROOT_SIMLINGO]
url_simlingo = "/workspace/simlingo/database/simlingo_v2_2025_01_10/data/simlingo/training_1_scenario/routes_training/random_weather_seed_1_balanced_150/Town12_Rep0_1000_route0_01_11_15_39_27/rgb"
url_ours = "/workspace/simlingo/recording_japan_xml/autopilot_multicamera_japanese_highway_20251212_150258/rgb"

ROOT_OURS = sys.argv[1] if len(sys.argv) > 1 else url_ours
ROOT_SIM = sys.argv[2] if len(sys.argv) > 2 else url_simlingo

CAM_NAMES = ['F','B','RF','LF','RB','LB']

def variance_of_laplacian(gray):
    return cv2.Laplacian(gray, cv2.CV_64F).var()

def entropy(img_arr):
    h, _ = np.histogram(img_arr.flatten(), bins=256, range=(0,255))
    p = h / h.sum() if h.sum() else h
    p = p[p>0]
    return -np.sum(p * np.log2(p))


def analyze_root(root):
    """Analyze a dataset root where each frame is a directory or a sequence of files.
    Returns stats per camera: counts, dims, sizes, blur, entropy, dark counts."""
    stats = {c: {'count':0, 'dark':0, 'blur':[], 'entropy':[], 'dims':[], 'sizes':[]} for c in CAM_NAMES}
    entries = sorted(glob.glob(os.path.join(root, '*')))
    if len(entries) == 0:
        print('No entries found in', root)
        return stats

    first = entries[0]
    if os.path.isdir(first):
        frame_dirs = [p for p in entries if os.path.isdir(p)]
        for d in frame_dirs:
            cams = []
            for c in CAM_NAMES:
                path = os.path.join(d, f"{c}.png")
                if os.path.isfile(path):
                    cams.append(c)
                    try:
                        im = Image.open(path).convert('RGB')
                        arr = np.array(im)
                        maxv = int(arr.max())
                        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
                        blur = variance_of_laplacian(gray)
                        ent = entropy(gray)
                        stats[c]['count'] += 1
                        stats[c]['blur'].append(blur)
                        stats[c]['entropy'].append(ent)
                        stats[c]['dims'].append(arr.shape)
                        stats[c]['sizes'].append(os.path.getsize(path))
                        if maxv < 8:
                            stats[c]['dark'] += 1
                    except Exception as e:
                        print('ERR reading', path, e)
                else:
                    pass
            if set(cams) != set(CAM_NAMES):
                pass
    else:
        files = sorted([p for p in entries if os.path.isfile(p)])
        for p in files:
            base = os.path.basename(p)
            for c in CAM_NAMES:
                if base.endswith(f"{c}.png") or base.endswith(f"{c}.jpg") or base == f"{c}.png":
                    try:
                        im = Image.open(p).convert('RGB')
                        arr = np.array(im)
                        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
                        blur = variance_of_laplacian(gray)
                        ent = entropy(gray)
                        stats[c]['count'] += 1
                        stats[c]['blur'].append(blur)
                        stats[c]['entropy'].append(ent)
                        stats[c]['dims'].append(arr.shape)
                        stats[c]['sizes'].append(os.path.getsize(p))
                        if int(arr.max()) < 8:
                            stats[c]['dark'] += 1
                    except Exception as e:
                        print('ERR reading', p, e)
                    break
        if sum(stats[c]['count'] for c in CAM_NAMES) == 0:
            for p in files:
                if p.lower().endswith(('.jpg', '.jpeg', '.png')):
                    try:
                        im = Image.open(p).convert('RGB')
                        arr = np.array(im)
                        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
                        blur = variance_of_laplacian(gray)
                        ent = entropy(gray)
                        stats['F']['count'] += 1
                        stats['F']['blur'].append(blur)
                        stats['F']['entropy'].append(ent)
                        stats['F']['dims'].append(arr.shape)
                        stats['F']['sizes'].append(os.path.getsize(p))
                        if int(arr.max()) < 8:
                            stats['F']['dark'] += 1
                    except Exception as e:
                        print('ERR reading', p, e)

    return stats


def summarize_stats(name, stats):
    print('\nSUMMARY for', name)
    for c in CAM_NAMES:
        s = stats[c]
        cnt = s['count']
        if cnt == 0:
            print(f"{c}: NO IMAGES")
            continue
        dims = s['dims']
        unique_dims = {}
        for d in dims:
            unique_dims[d] = unique_dims.get(d, 0) + 1
        most_common_dim = max(unique_dims.items(), key=lambda x: x[1])[0]
        avg_blur = float(np.mean(s['blur'])) if len(s['blur'])>0 else float('nan')
        min_blur = float(np.min(s['blur'])) if len(s['blur'])>0 else float('nan')
        avg_ent = float(np.mean(s['entropy'])) if len(s['entropy'])>0 else float('nan')
        avg_size = int(np.mean(s['sizes'])) if len(s['sizes'])>0 else 0
        print(f"{c}: count={cnt} dark={s['dark']} most_common_dim={most_common_dim} avg_size={avg_size} avg_blur={avg_blur:.1f} avg_entropy={avg_ent:.2f}")


def compare_and_print(root_ours, root_sim):
    stats_ours = analyze_root(root_ours)
    stats_sim = analyze_root(root_sim)
    summarize_stats('OURS', stats_ours)
    summarize_stats('SIMLINGO', stats_sim)


if __name__ == '__main__':
    print('ROOT_OURS =', ROOT_OURS)
    print('ROOT_SIM =', ROOT_SIM)
    compare_and_print(ROOT_OURS, ROOT_SIM)