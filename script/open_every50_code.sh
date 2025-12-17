
#!/usr/bin/env bash
set -euo pipefail

# Usage: ./open_every50_code.sh [recording_folder] [viewer] [step] [which_img]
#  recording_folder: path to a recording run folder containing 'rgb/' (default: current dir)
#  viewer: optional, defaults to 'code' (VS Code). Pass 'xdg-open' or 'feh' to use a different viewer.

RECORDING_DIR="${1:-.}"
VIEWER="${2:-code}"
STEP="${3:-code}"
WHICH_IMGS="${4:-F}"

# Resolve root rgb folder
ROOT="${RECORDING_DIR%/}/rgb"
if [[ ! -d "$ROOT" ]]; then
  echo "RGB folder not found at: $ROOT"
  exit 1
fi

# Find the last folder name (preserve leading zeros width)
last=$(for d in "$ROOT"/*/; do printf '%s\n' "${d%/}"; done | sed 's!.*/!!' | sort -V | tail -n1)
if [[ -z "$last" ]]; then
  echo "No folders found under ${ROOT}/"
  exit 1
fi
width=${#last}
last_nz=$(echo "$last" | sed 's/^0*//')
last_nz=${last_nz:-0}

files=()
for ((n=0; n<=last_nz; n+=$STEP)); do
  idx=$(printf "%0${width}d" "$n")
  img="$ROOT/${idx}/${WHICH_IMGS}.png"
  if [[ -f "$img" ]]; then
    files+=("$img")
    echo "[INFO]: Opening $img"
  else
    echo "[WARNING]: Missing: $img"
  fi
done

if [[ ${#files[@]} -eq 0 ]]; then
  echo "[WARNING]: No files selected. Exiting."
  exit 0
fi

if command -v "$VIEWER" >/dev/null 2>&1; then
  echo "Opening ${#files[@]} files with $VIEWER"
  if [[ "$VIEWER" == "xdg-open" ]]; then
    for f in "${files[@]}"; do
      "$VIEWER" "$f" &
      sleep 0.1
    done
  else
    "$VIEWER" "${files[@]}"
  fi
else
  echo "Viewer '$VIEWER' not found. Selected files:"
  printf '%s\n' "${files[@]}"
  exit 1
fi
