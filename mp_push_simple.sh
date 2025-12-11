#!/usr/bin/env bash
set -euo pipefail

# Simple push helper: stage all, commit, push to myfork
# Usage: ./mp_push_simple.sh "Commit message"

MSG=${1:-"Update from workspace"}
REMOTE=${2:-myfork}

echo "[mp_push_simple] Staging all changes..."
git add -A

if git diff --staged --quiet; then
  echo "[mp_push_simple] No changes to commit. Pushing current branch to $REMOTE..."
else
  echo "[mp_push_simple] Committing: $MSG"
  git commit -m "$MSG"
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "[mp_push_simple] Pushing $BRANCH to $REMOTE..."
git push -u "$REMOTE" "$BRANCH"

echo "[mp_push_simple] Done."
