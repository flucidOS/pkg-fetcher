#!/bin/bash
set -e

# Path to your offline sources inside pkg-fetcher
PKG_SRC_DIR="pkg-src"
# Your new empty GitHub repository URL
REPO_URL="https://github.com/flucidOS/pkg-src.git"

echo "========================================"
echo "Preparing pkg-src mirror update..."
echo "========================================"

if [ ! -d "$PKG_SRC_DIR" ]; then
    echo "Error: '$PKG_SRC_DIR' directory not found. Run './flfetch sync' first."
    exit 1
fi

cd "$PKG_SRC_DIR"

# 1. Initialize the root Git repository if it doesn't exist
if [ ! -d ".git" ]; then
    git init
    git checkout -b main
    git remote add origin "$REPO_URL"
fi

# 2. Scrub nested submodules safely (mindepth 2 protects the root .git folder)
echo "Scrubbing nested upstream .git folders..."
find . -mindepth 2 -name ".git" -type d -prune -exec rm -rf '{}' +

# 3. Chunked Upload: Add, commit, and push category by category
echo "Starting chunked upload to prevent HTTP 500 timeouts..."
for category in */ ; do
    cat_name="${category%/}"
    
    echo "-> Staging $cat_name..."
    git add "$category"
    
    if ! git diff --cached --quiet; then
        git commit -m "Automated mirror sync: $cat_name - $(date -u +%Y-%m-%d)"
        
        echo "-> Pushing $cat_name to GitHub..."
        git push -u origin main
    else
        echo "-> No changes in $cat_name, skipping."
    fi
done

echo "========================================"
echo "Mirror synchronization complete!"
echo "========================================"
