#!/usr/bin/env python3
"""
download_songs.py
=================

Take a list of song names, search each one on YouTube, download the audio as
MP3, and (optionally) upload the results straight to a cloud folder via rclone
(e.g. Google Drive). Nothing is meant to live on your local machine long-term:
run it on a server / cloud box, let it push the files to your Drive, and grab
them from there.

Usage:
    python3 download_songs.py --list songs.txt --out ./downloads \
        --remote gdrive:Music

Arguments:
    --list     Path to a text file with one song per line. Blank lines and
               lines starting with '#' are ignored.
    --out      Local folder to download into (temporary). Default: ./downloads
    --remote   rclone remote + folder to upload to, e.g. "gdrive:Music".
               Omit to only download locally without uploading.
    --quality  MP3 quality for ffmpeg (0 = best, 9 = smallest). Default: 0
    --keep     Keep local files after a successful upload (default: delete).
    --upload-each  Upload each song right after it downloads instead of once
               at the end (safer for long lists / flaky connections).

Requirements: yt-dlp, ffmpeg, and (for uploading) rclone. See README.md.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def read_song_list(path: Path) -> list[str]:
    """Read the song list, skipping blank lines and comments."""
    songs = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        songs.append(line)
    return songs


def require_tool(name: str) -> None:
    """Exit with a friendly message if a required command is missing."""
    if shutil.which(name) is None:
        sys.exit(
            f"[!] '{name}' is not installed or not on PATH.\n"
            f"    See README.md for install instructions (try ./setup.sh)."
        )


def download_song(song: str, out_dir: Path, quality: str) -> Path | None:
    """
    Search YouTube for `song` and download the first result as MP3.
    Returns the path to the created file, or None on failure.
    """
    # A predictable output name so we can find the file afterwards.
    # yt-dlp fills in the real title; %(ext)s becomes mp3 after extraction.
    out_template = str(out_dir / "%(title)s [%(id)s].%(ext)s")

    cmd = [
        "yt-dlp",
        f"ytsearch1:{song}",        # take the top YouTube search result
        "--no-playlist",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", quality,
        "--embed-thumbnail",        # nice-to-have: cover art (ignored if unsupported)
        "--add-metadata",           # write title/artist tags
        "--output", out_template,
        "--print", "after_move:filepath",   # print the final file path
        "--no-warnings",
        "--quiet",
    ]

    print(f"  -> searching & downloading: {song}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  [x] failed: {song}")
        err = (result.stderr or "").strip().splitlines()
        if err:
            print(f"      {err[-1]}")
        return None

    # The printed filepath is the last non-empty stdout line.
    lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    if not lines:
        print(f"  [x] downloaded but could not locate file: {song}")
        return None

    path = Path(lines[-1])
    if not path.exists():
        print(f"  [x] reported file missing: {path}")
        return None

    print(f"  [ok] {path.name}")
    return path


def upload(path: Path, remote: str) -> bool:
    """Upload a single file (or a whole folder) to the rclone remote."""
    cmd = ["rclone", "copy", "--progress", str(path), remote]
    print(f"  -> uploading '{path.name}' to {remote}")
    return subprocess.run(cmd).returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Download songs and upload to a cloud folder.")
    parser.add_argument("--list", required=True, help="Text file with one song per line.")
    parser.add_argument("--out", default="./downloads", help="Local download folder.")
    parser.add_argument("--remote", default=None, help='rclone remote:folder, e.g. "gdrive:Music".')
    parser.add_argument("--quality", default="0", help="MP3 quality 0 (best) - 9 (smallest).")
    parser.add_argument("--keep", action="store_true", help="Keep local files after upload.")
    parser.add_argument("--upload-each", action="store_true", help="Upload each song right after download.")
    args = parser.parse_args()

    require_tool("yt-dlp")
    require_tool("ffmpeg")
    if args.remote:
        require_tool("rclone")

    list_path = Path(args.list)
    if not list_path.exists():
        sys.exit(f"[!] song list not found: {list_path}")

    songs = read_song_list(list_path)
    if not songs:
        sys.exit(f"[!] no songs found in {list_path}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Found {len(songs)} song(s). Downloading into '{out_dir}'.\n")

    downloaded: list[Path] = []
    failed: list[str] = []

    for i, song in enumerate(songs, 1):
        print(f"[{i}/{len(songs)}] {song}")
        path = download_song(song, out_dir, args.quality)
        if path is None:
            failed.append(song)
            continue
        downloaded.append(path)

        if args.remote and args.upload_each:
            if upload(path, args.remote):
                if not args.keep:
                    path.unlink(missing_ok=True)
            else:
                print(f"  [x] upload failed, keeping local copy: {path.name}")
        print()

    # Upload everything at once (unless we already uploaded per-song).
    if args.remote and not args.upload_each and downloaded:
        print(f"Uploading {len(downloaded)} file(s) to {args.remote} ...")
        if upload(out_dir, args.remote):
            if not args.keep:
                for p in downloaded:
                    p.unlink(missing_ok=True)
        else:
            print("[!] bulk upload failed; local files kept.")

    # Summary
    print("\n" + "=" * 50)
    print(f"Done. {len(downloaded)} succeeded, {len(failed)} failed.")
    if args.remote:
        print(f"Uploaded to: {args.remote}")
    else:
        print(f"Files are in: {out_dir.resolve()}")
    if failed:
        print("\nFailed songs (check spelling or try a more exact name):")
        for s in failed:
            print(f"  - {s}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
