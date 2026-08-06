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

echo ""
echo "Done. Next: configure Google Drive with 'rclone config' (see README.md)."
