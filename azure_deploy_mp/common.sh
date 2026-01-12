#!/bin/bash

# Shared UI helpers for azure_deploy_mp scripts
print_sep(){
    n=${1:-80}
    printf '%*s\n' "$n" '' | tr ' ' '='
}

info_n(){
    n=${1:-80}
    shift || true
    msg="$*"
    print_sep "$n"
    echo "[INFO]: $msg"
    print_sep "$n"
}

info(){
    info_n 80 "$@"
}

export -f print_sep info_n info
