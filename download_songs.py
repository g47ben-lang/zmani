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
    --min-duration  Skip results shorter than N seconds and download the first
                one that is long enough (e.g. 600 = at least 10 min). Useful to
                get the full version instead of a short clip. Env: MIN_DURATION.
    --keep      Keep local files after a successful upload (default: delete).
    --upload-each  Upload each song right after it downloads (rclone only).

Requirements: yt-dlp, ffmpeg; rclone (for --remote); ffsend (for --link,
optional). See README.md.
"""

import argparse
import os
import random
import re
import shutil
import string
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
SEARCH_ENGINES = {
    "yt": "ytsearch",   # YouTube
    "sc": "scsearch",   # SoundCloud
}
SEARCH_LABELS = {"yt": "YouTube", "sc": "SoundCloud"}

# How many candidates to pull per search when a duration filter is active. We
# need more than one so yt-dlp can skip the short clips and reach a long one.
DEFAULT_SEARCH_COUNT = 20


def _try_download(query: str, out_dir: Path, quality: str,
                  video: bool = False, video_res: str | None = None,
                  min_duration: int = 0) -> Path | None:
    """Run yt-dlp for a single search query. Returns the file path or None.

    In audio mode (default) the result is an MP3. In video mode (`video=True`)
    the full video is downloaded and merged into a single MP4, optionally
    capped at a max height via `video_res` (e.g. "1080").

    When `min_duration` (seconds) is set, yt-dlp skips any result shorter than
    that and downloads the first one that is long enough — so you get the full
    version, not a short clip. The caller must pass a multi-result search query
    (e.g. "ytsearch20:...") so there are candidates to filter through.
    """
    out_template = str(out_dir / "%(title)s [%(id)s].%(ext)s")

    cmd = ["yt-dlp", query]
    # `--no-playlist` collapses a search to a single result, which would defeat
    # the duration filter (nothing left to skip to). Only use it when we are
    # NOT filtering by length.
    if min_duration <= 0:
        cmd += ["--no-playlist"]
    else:
        # Skip results shorter than the threshold, stop after the first that
        # passes. `--max-downloads 1` makes yt-dlp exit as soon as one long
        # enough result is fetched (handled as success below).
        cmd += [
            "--match-filter", f"duration >= {min_duration}",
            "--max-downloads", "1",
        ]
    cmd += [
        "--retries", "8",
        "--fragment-retries", "8",
        "--extractor-retries", "3",
    ]

    if video:
        # Grab the best video+audio and merge into one MP4 file. `video_res`
        # caps the height so runs stay reasonably sized (e.g. 720/1080).
        if video_res:
            fmt = f"bv*[height<={video_res}]+ba/b[height<={video_res}]/bv*+ba/b"
        else:
            fmt = "bv*+ba/b"
        cmd += [
            "-f", fmt,
            "--merge-output-format", "mp4",
            "--remux-video", "mp4",     # remux (no re-encode) to mp4 when possible
            "--embed-thumbnail",
            "--embed-metadata",
        ]
    else:
        cmd += [
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", quality,
            "--embed-thumbnail",        # nice-to-have: cover art (ignored if unsupported)
            "--add-metadata",           # write title/artist tags
        ]

    cmd += [
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

    # A cookies.txt (Netscape format) lets yt-dlp pass YouTube's bot check.
    # Point YTDLP_COOKIES at the file to enable it.
    cookies = os.environ.get("YTDLP_COOKIES")
    if cookies and Path(cookies).exists():
        cmd += ["--cookies", cookies]

    # Route through a proxy (e.g. a residential proxy so YouTube treats the
    # request as a normal home user). Format: http://user:pass@host:port
    proxy = os.environ.get("YTDLP_PROXY")
    if proxy:
        # For sticky-session residential proxies (e.g. Geonode's "session-XXXX"
        # username), use a fresh session id per download so one stable IP serves
        # the whole song — avoids mid-download "HTTP 403" from IP rotation.
        rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        proxy = re.sub(r"(session-)[A-Za-z0-9]+", r"\g<1>" + rand, proxy)
        cmd += ["--proxy", proxy]

    result = subprocess.run(cmd, capture_output=True, text=True)

    # Parse the printed filepath first, regardless of exit code: with
    # `--max-downloads 1` yt-dlp exits non-zero (code 101, "max downloads
    # reached") even though the download succeeded. If a real file was
    # produced, that's a success.
    lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    if lines:
        path = Path(lines[-1])
        if path.exists():
            return path

    if result.returncode != 0:
        err = (result.stderr or "").strip().splitlines()
        return None if not err else (_Fail(err[-1]))  # carry last error line
    return None


class _Fail(str):
    """A str subclass used to signal 'failed with this error message'."""
    __slots__ = ()


def download_song(song: str, out_dir: Path, quality: str,
                  video: bool = False, video_res: str | None = None,
                  min_duration: int = 0) -> Path | None:
    """
    Search each configured source (YouTube, then SoundCloud) for `song` and
    download the first result — as MP3 (default) or as a merged MP4 when
    `video=True`. Returns the file path, or None if every source failed.

    When `min_duration` (seconds) is set, short clips are skipped and the first
    result at least that long is downloaded instead.
    """
    order = [s.strip() for s in os.environ.get("SOURCES", "yt,sc").split(",") if s.strip()]
    # SoundCloud has no video; in video mode only search sources that carry it.
    if video:
        order = [s for s in order if s == "yt"] or ["yt"]
    last_err = ""

    # With a duration filter we need several candidates to skip past the short
    # clips; without one, the single top result is enough.
    count = DEFAULT_SEARCH_COUNT if min_duration > 0 else 1

    for src in order:
        engine = SEARCH_ENGINES.get(src)
        if not engine:
            continue
        label = SEARCH_LABELS.get(src, src)
        query = f"{engine}{count}:{song}"
        if min_duration > 0:
            print(f"  -> searching {label} (>= {min_duration}s): {song}")
        else:
            print(f"  -> searching {label}: {song}")
        outcome = _try_download(query, out_dir, quality, video, video_res, min_duration)
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
    #    Host is passed via FFSEND_HOST env (more reliable across versions than
    #    the --host flag). Try a couple of invocations for compatibility.
    if send_host and shutil.which("ffsend"):
        env = {**os.environ, "FFSEND_HOST": send_host}
        for cmd in (["ffsend", "upload", "--yes", zp],
                    ["ffsend", "upload", "--host", send_host, zp]):
            print(f"  -> uploading {zip_path.name} to {send_host} (ffsend) ...")
            r = subprocess.run(cmd, capture_output=True, text=True, env=env)
            url = _extract_url(r.stdout) or _extract_url(r.stderr)
            if url:
                add("magicode", url)
                break
            if r.stderr.strip():
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
    parser.add_argument("--video", action="store_true",
                        help="Download the full video (MP4) instead of extracting audio.")
    parser.add_argument("--video-res", default=os.environ.get("VIDEO_RES"),
                        help='Cap video height, e.g. "720" or "1080" (video mode only).')
    parser.add_argument("--min-duration", type=int,
                        default=int(os.environ.get("MIN_DURATION") or 0),
                        help="Skip results shorter than this many SECONDS and "
                             "download the first long-enough one (e.g. 600 = "
                             "at least 10 minutes). Env: MIN_DURATION.")
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

    # Video mode can also be turned on via the VIDEO env var (=1/true/yes),
    # so the workflow can toggle it without changing the command line.
    video = args.video or os.environ.get("VIDEO", "").lower() in ("1", "true", "yes")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    kind = "video (MP4)" if video else "audio (MP3)"
    length_note = f", min length {args.min_duration}s" if args.min_duration > 0 else ""
    print(f"Found {len(songs)} item(s). Downloading as {kind}{length_note} into '{out_dir}'.\n")

    downloaded: list[Path] = []
    failed: list[str] = []

    for i, song in enumerate(songs, 1):
        print(f"[{i}/{len(songs)}] {song}")
        path = download_song(song, out_dir, args.quality, video,
                             args.video_res, args.min_duration)
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
