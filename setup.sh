#!/usr/bin/env bash
#
# setup.sh — install the tools download_songs.py needs:
#   * yt-dlp  (downloads the audio)          -> via pip
#   * ffmpeg  (converts to mp3)              -> via apt / brew / static build
#   * rclone  (uploads to Google Drive etc.) -> via official installer
#
# Safe to re-run. Works on most Debian/Ubuntu boxes and macOS.
set -e

echo "==> Installing yt-dlp (pip)"
python3 -m pip install --upgrade --user yt-dlp

echo "==> Installing ffmpeg"
if command -v ffmpeg >/dev/null 2>&1; then
  echo "    ffmpeg already installed."
elif command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -y && sudo apt-get install -y ffmpeg
elif command -v brew >/dev/null 2>&1; then
  brew install ffmpeg
else
  echo "    Could not auto-install ffmpeg. Please install it manually:"
  echo "    https://ffmpeg.org/download.html"
fi

echo "==> Installing rclone"
if command -v rclone >/dev/null 2>&1; then
  echo "    rclone already installed."
else
  curl -fsSL https://rclone.org/install.sh | sudo bash
fi

echo "==> Installing ffsend (for --link uploads to a Send instance)"
if command -v ffsend >/dev/null 2>&1; then
  echo "    ffsend already installed."
else
  FFSEND_URL="https://github.com/timvisee/ffsend/releases/download/v0.2.76/ffsend-v0.2.76-linux-x64-static"
  if curl -fsSL "$FFSEND_URL" -o /tmp/ffsend 2>/dev/null; then
    chmod +x /tmp/ffsend && sudo mv /tmp/ffsend /usr/local/bin/ffsend 2>/dev/null \
      || mv /tmp/ffsend /usr/local/bin/ffsend 2>/dev/null \
      || echo "    Could not place ffsend on PATH; move /tmp/ffsend manually."
  else
    echo "    Could not download ffsend (Linux x64 only). --link will fall back to 0x0.st."
  fi
fi

echo ""
echo "Done."
echo "  * Link flow:   python3 download_songs.py --list songs.txt --link --send-host https://send.magicode.me/"
echo "  * Drive flow:  configure with 'rclone config' first (see README.md)."
