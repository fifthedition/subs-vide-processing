#!/bin/zsh
set -e
cd -- "$(dirname -- "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
./prepare-mac.sh
exec .venv/bin/python worker.py --configure
