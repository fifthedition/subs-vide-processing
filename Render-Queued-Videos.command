#!/bin/zsh
set -e
cd -- "$(dirname -- "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
./prepare-mac.sh
echo "Rendering queued videos. Control-C stops the renderer."
exec .venv/bin/python worker.py
