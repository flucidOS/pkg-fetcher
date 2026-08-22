#!/bin/bash
set -e

PKG_SRC_DIR="pkg-src"
REPO_URL="https://github.com/flucidOS/pkg-src.git"

echo "========================================"
echo "Preparing Micro-Chunked Mirror Update..."
echo "========================================"

if [ ! -d "$PKG_SRC_DIR" ]; then
    echo "Error: '$PKG_SRC_DIR' not found."
    exit 1
fi

cd "$PKG_SRC_DIR"

if [ ! -d ".git" ]; then
    git init
    git checkout -b main
    git remote add origin "$REPO_URL"
fi

echo "Scrubbing nested upstream .git folders..."
find . -mindepth 2 -name ".git" -type d -prune -exec rm -rf '{}' +

echo "Starting package-by-package upload..."

# Iterate through every single package directory (2 levels deep)
for pkg in */*/ ; do
    pkg_name="${pkg%/}"
    
    echo "-> Staging $pkg_name..."
    git add "$pkg"
    
    if ! git diff --cached --quiet; then
        git commit -m "Automated mirror sync: $pkg_name - $(date -u +%Y-%m-%d)"
        
        echo "-> Pushing $pkg_name..."
        # Wrap the push in a retry loop in case GitHub drops a connection
        n=0
        until [ "$n" -ge 3 ]
        do
           git push -u origin main && break
           n=$((n+1))
           echo "Push failed, retrying ($n/3) in 5 seconds..."
           sleep 5
        done
    fi
done

# Catch any straggling files in the root
git add .
if ! git diff --cached --quiet; then
    git commit -m "Automated mirror sync: final root files - $(date -u +%Y-%m-%d)"
    git push -u origin main
fi

echo "========================================"
echo "Mirror synchronization complete!"
echo "========================================"
