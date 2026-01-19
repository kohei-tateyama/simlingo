#!/bin/bash
# Common helper functions for route handling

build_routes_subset() {
    # If ROUTES_SUBSET already set and not '0', keep it
    if [ -n "${ROUTES_SUBSET:-}" ] && [ "${ROUTES_SUBSET}" != "0" ]; then
        return 0
    fi

    if [ -z "${ROUTES:-}" ]; then
        # nothing to do
        return 0
    fi

    if [ ! -f "${ROUTES}" ]; then
        # file not found
        return 0
    fi

    # Attempt to parse XML and extract route ids
    ROUTES_SUBSET=$(python - <<'PY'
import xml.etree.ElementTree as ET, os, sys
routes_file = os.environ.get('ROUTES','')
if not routes_file or not os.path.exists(routes_file):
    print('', end='')
    sys.exit(0)
tree = ET.parse(routes_file)
root = tree.getroot()
ids = [r.get('id') for r in root.findall('.//route') if r.get('id')]
print(','.join(ids), end='')
PY
)

    # export the derived subset (may be empty)
    export ROUTES_SUBSET
}

# --- Logging helpers and colors (define only if not already set) -----------------
# Default color helpers unless already set in the environment
: ${GREEN:="\033[0;32m"}
: ${YELLOW:="\033[0;33m"}
: ${RED:="\033[0;31m"}
: ${BLUE:="\033[0;34m"}
: ${RESET:="\033[0m"}

# Define logging functions using the requested style, but only if they don't exist
if ! declare -F info >/dev/null 2>&1; then
    info() { echo -e "${GREEN}[INFO]${RESET} $*"; }
fi
if ! declare -F warn >/dev/null 2>&1; then
    warn() { echo -e "${YELLOW}[WARN]${RESET} $*"; }
fi
if ! declare -F err >/dev/null 2>&1; then
    err() { echo -e "${RED}[ERROR]${RESET} $*"; }
fi
if ! declare -F sep >/dev/null 2>&1; then
    sep() { printf "%b\n" "${BLUE}$(printf '=%.0s' {1..80})${RESET}"; }
fi


### end common.sh