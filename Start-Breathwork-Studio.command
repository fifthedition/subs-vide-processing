#!/bin/zsh
set -e
cd -- "$(dirname -- "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required. Install Python from https://www.python.org/downloads/macos/ and run this again."
  read -r "studio_reply?Press Return to close. "
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)'; then
  echo "Python 3.11 or newer is required. Install a current Python and run this again."
  read -r "studio_reply?Press Return to close. "
  exit 1
fi
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "FFmpeg is required for music and MP4 export. If you use Homebrew, run: brew install ffmpeg"
  read -r "studio_reply?Press Return to close. "
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import PIL' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
fi
echo "Starting Breathwork Studio. Keep this window open while editing or rendering."
echo "Press Control-C here to stop the app."
exec .venv/bin/python app.py --open
