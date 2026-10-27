#!/bin/zsh
set -e
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' >/dev/null 2>&1; then
  echo "Install Python 3.11 or newer from https://www.python.org/downloads/macos/"
  exit 1
fi
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "Install FFmpeg first: brew install ffmpeg"
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import PIL; assert PIL.__version__ == "13.0.0"' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
fi
