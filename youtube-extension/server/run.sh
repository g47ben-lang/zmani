#!/usr/bin/env bash
# Run the SaveBridge free relay on a VPS, a free-tier host, or your own machine.
#
#   ./run.sh                # listen on 0.0.0.0:9797, open (no token)
#   SB_TOKEN=secret ./run.sh # require a Bearer token = "secret"
#   PORT=8080 ./run.sh       # different port (e.g. Cloud Run sets $PORT)
#
# Needs python3 and ffmpeg. Installs Python deps into a local venv on first run.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "!! ffmpeg not found. Install it first (e.g. 'sudo apt install -y ffmpeg')." >&2
fi

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

export PORT="${PORT:-9797}"
echo ">>> SaveBridge relay listening on 0.0.0.0:${PORT}"
exec python app.py
