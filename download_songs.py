#!/usr/bin/env python3
"""
download_songs.py
=================

Take a list of song names, search each one on YouTube, download the audio as
MP3, and hand you the results one of two ways:

  1. --remote : upload straight to a cloud folder via rclone (e.g. Google Drive)
  2. --link   : zip everything and upload to a file-share that returns a
                download link (a "Send" instance via ffsend, or 0x0.st)

Nothing is meant to live on your local machine long-term: run it on a server /
cloud box and grab the result from Drive or the link.

Usage:
    # Google Drive:
    python3 download_songs.py --list songs.txt --remote gdrive:Music

    # Zip + shareable link (e.g. a Send instance like send.magicode.me):
    python3 download_songs.py --list songs.txt --link \
        --send-host https://send.magicode.me/

Arguments:
    --list      Path to a text file with one song per line. Blank lines and
                lines starting with '#' are ignored.
    --out       Local folder to download into (temporary). Default: ./downloads
    --remote    rclone remote + folder to upload to, e.g. "gdrive:Music".
    --link      Zip the downloads and upload to a file-share; print the link.
    --send-host A "Send" host used by --link (via ffsend), e.g.
                "https://send.magicode.me/". Falls back to 0x0.st if ffsend
                is missing or the upload fails. Env: SEND_HOST.
    --zip-name  Name of the zip file created by --link. Default: songs.zip
    --quality   MP3 quality for ffmpeg (0 = best, 9 = smallest). Default: 0
    --keep      Keep local files after a successful upload (default: delete).
    --upload-each  Upload each song right after it downloads (rclone only).

Requirements: yt-dlp, ffmpeg; rclone (for --remote); ffsend (for --link,
optional). See README.md.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile
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


# Search "engines" tried in order. YouTube has the best catalogue but blocks
# datacenter IPs with a bot check; SoundCloud is a resilient fallback that
# does not block cloud runners. Override with the SOURCES env var, e.g.
# SOURCES="yt,sc" (default) or SOURCES="sc" to skip YouTube entirely.
SEARCH_PREFIXES = {
    "yt": "ytsearch1:",   # YouTube
    "sc": "scsearch1:",   # SoundCloud
}


def _try_download(query: str, out_dir: Path, quality: str) -> Path | None:
    """Run yt-dlp for a single search query. Returns the file path or None."""
    out_template = str(out_dir / "%(title)s [%(id)s].%(ext)s")

    cmd = [
        "yt-dlp",
        query,
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
    # Extra yt-dlp extractor args (e.g. a PO-token / player_client tweak) can be
    # injected without touching the code, via the env var below.
    extra = os.environ.get("YTDLP_EXTRACTOR_ARGS")
    if extra:
        cmd += ["--extractor-args", extra]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        err = (result.stderr or "").strip().splitlines()
        return None if not err else (_Fail(err[-1]))  # carry last error line

    lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    if not lines:
        return None
    path = Path(lines[-1])
    return path if path.exists() else None


class _Fail(str):
    """A str subclass used to signal 'failed with this error message'."""
    __slots__ = ()


def download_song(song: str, out_dir: Path, quality: str) -> Path | None:
    """
    Search each configured source (YouTube, then SoundCloud) for `song` and
    download the first result as MP3. Returns the file path, or None if every
    source failed.
    """
    order = [s.strip() for s in os.environ.get("SOURCES", "yt,sc").split(",") if s.strip()]
    last_err = ""

    for src in order:
        prefix = SEARCH_PREFIXES.get(src)
        if not prefix:
            continue
        label = {"yt": "YouTube", "sc": "SoundCloud"}.get(src, src)
        print(f"  -> searching {label}: {song}")
        outcome = _try_download(f"{prefix}{song}", out_dir, quality)
        if isinstance(outcome, Path):
            print(f"  [ok] {outcome.name}  (via {label})")
            return outcome
        if isinstance(outcome, _Fail):
            last_err = str(outcome)
            # Surface why a source failed (helps diagnose YouTube bot-checks).
            if os.environ.get("DEBUG_SOURCES"):
                print(f"     ({label} failed: {last_err})")

    print(f"  [x] failed on all sources: {song}")
    if last_err:
        print(f"      {last_err}")
    return None


def upload(path: Path, remote: str) -> bool:
    """Upload a single file (or a whole folder) to the rclone remote."""
    cmd = ["rclone", "copy", "--progress", str(path), remote]
    print(f"  -> uploading '{path.name}' to {remote}")
    return subprocess.run(cmd).returncode == 0


def make_zip(files: list[Path], zip_name: str, out_dir: Path) -> Path:
    """Bundle the downloaded files into a single zip and return its path."""
    zip_path = out_dir.parent / zip_name
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, f.name)  # store by basename, no folder structure
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"  -> created {zip_path.name} ({size_mb:.1f} MB)")
    return zip_path


def _extract_url(text: str) -> str | None:
    """Pull the first http(s) URL out of a tool's output."""
    match = re.search(r"https?://\S+", text or "")
    return match.group(0).rstrip(".,) ") if match else None


def _curl(args: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(["curl", "-s", "--max-time", "300", *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def upload_link(zip_path: Path, send_host: str | None) -> list[tuple[str, str]]:
    """
    Upload the zip to several file-share services and return every
    (service_name, url) that succeeded. We try multiple because which sites
    are reachable depends on the user's network (some ISPs filter aggressively);
    the user picks whichever link opens for them.
    """
    zp = str(zip_path)
    links: list[tuple[str, str]] = []

    def add(name: str, url: str | None):
        if url and url.startswith("http"):
            links.append((name, url))
            print(f"  [ok] {name}: {url}")

    if not shutil.which("curl"):
        print("  [x] curl not available; cannot upload.")
        return links

    # 1) litterbox (catbox) — up to 1 GB, 72h, plain URL in the body.
    print(f"  -> uploading {zip_path.name} to litterbox ...")
    rc, out, _ = _curl(["-F", "reqtype=fileupload", "-F", "time=72h",
                        "-F", f"fileToUpload=@{zp}",
                        "https://litterbox.catbox.moe/resources/internals/api.php"])
    if rc == 0:
        add("litterbox", _extract_url(out))

    # 2) 0x0.st — needs a custom User-Agent or it 403s.
    print(f"  -> uploading {zip_path.name} to 0x0.st ...")
    rc, out, _ = _curl(["-A", "music-dl/1.0", "-F", f"file=@{zp}", "https://0x0.st"])
    if rc == 0:
        add("0x0.st", _extract_url(out))

    # 3) bashupload.com — plain PUT, returns a wget URL in the body.
    print(f"  -> uploading {zip_path.name} to bashupload ...")
    rc, out, _ = _curl(["--upload-file", zp, "https://bashupload.com/songs.zip"])
    if rc == 0:
        add("bashupload", _extract_url(out))

    # 4) A "Send" instance (e.g. send.magicode.me) via ffsend, if available.
    if send_host and shutil.which("ffsend"):
        print(f"  -> uploading {zip_path.name} to {send_host} (ffsend) ...")
        env = {**os.environ, "FFSEND_HOST": send_host}
        r = subprocess.run(["ffsend", "upload", "--host", send_host, zp],
                           capture_output=True, text=True, env=env)
        add("magicode", _extract_url(r.stdout) or _extract_url(r.stderr))
        if not (_extract_url(r.stdout) or _extract_url(r.stderr)) and r.stderr.strip():
            print(f"      (ffsend: {r.stderr.strip().splitlines()[-1]})")

    if not links:
        print("  [x] All upload services failed.")
    return links


def main() -> int:
    parser = argparse.ArgumentParser(description="Download songs and upload to a cloud folder.")
    parser.add_argument("--list", required=True, help="Text file with one song per line.")
    parser.add_argument("--out", default="./downloads", help="Local download folder.")
    parser.add_argument("--remote", default=None, help='rclone remote:folder, e.g. "gdrive:Music".')
    parser.add_argument("--link", action="store_true", help="Zip downloads and print a share link.")
    parser.add_argument("--send-host", default=os.environ.get("SEND_HOST"),
                        help='Send host for --link, e.g. "https://send.magicode.me/".')
    parser.add_argument("--zip-name", default="songs.zip", help="Zip file name for --link.")
    parser.add_argument("--quality", default="0", help="MP3 quality 0 (best) - 9 (smallest).")
    parser.add_argument("--keep", action="store_true", help="Keep local files after upload.")
    parser.add_argument("--upload-each", action="store_true", help="Upload each song right after download (rclone only).")
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

    # Zip everything and produce shareable download links.
    share_links: list[tuple[str, str]] = []
    if args.link and downloaded:
        print(f"\nZipping {len(downloaded)} file(s) ...")
        zip_path = make_zip(downloaded, args.zip_name, out_dir)
        share_links = upload_link(zip_path, args.send_host)
        if not args.keep:
            zip_path.unlink(missing_ok=True)
            for p in downloaded:
                p.unlink(missing_ok=True)

    # Summary
    print("\n" + "=" * 50)
    print(f"Done. {len(downloaded)} succeeded, {len(failed)} failed.")
    if args.remote:
        print(f"Uploaded to: {args.remote}")
    elif share_links:
        print("\n  >>> DOWNLOAD LINKS (open whichever works on your network):")
        for name, url in share_links:
            print(f"      [{name}] {url}")
        print("")
    elif args.link:
        print("[!] Could not produce a download link (see errors above).")
    else:
        print(f"Files are in: {out_dir.resolve()}")
    if failed:
        print("\nFailed songs (check spelling or try a more exact name):")
        for s in failed:
            print(f"  - {s}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
