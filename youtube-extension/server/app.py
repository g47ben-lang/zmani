"""
SaveBridge-compatible relay server (free, self-hosted).

This is a drop-in replacement for the paid ``extsync.com/sb-relay`` backend that
the SaveBridge browser extension talks to. It implements exactly the HTTP API the
extension expects and does the real work locally with ``yt-dlp`` + ``ffmpeg``.

Run it anywhere you have free compute (Google Colab, a free-tier cloud host, a
VPS, or your own machine) and point the extension at its URL. Nothing is sent to
any third party: the YouTube cookies the extension forwards stay on this server
only for the duration of a download.

Endpoints (all under /api), matching the extension's serverApi.ts contract:

    POST /api/hello                 -> { token }
    GET  /api/ping                  -> { ytDlp, ffmpeg }
    POST /api/start                 -> { jobId }
    GET  /api/jobs/{id}             -> job status
    POST /api/jobs/{id}/cancel      -> { ok }
    GET  /api/jobs/{id}/file        -> the finished media file (bytes)

Auth: if the SB_TOKEN environment variable is set, that value is required as a
Bearer token (and returned from /api/hello). If it is not set, the server is
open -- fine behind a random, unguessable tunnel URL, which is the default
Colab setup. Downloads are never encrypted by this server (the extension's
"filtering mode" / pubKey path is simply ignored), so files come back as plain
media the browser saves directly.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

import yt_dlp

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

SB_TOKEN = os.environ.get("SB_TOKEN", "").strip()  # optional shared secret
WORK_ROOT = os.environ.get("SB_WORKDIR") or os.path.join(tempfile.gettempdir(), "savebridge")
MAX_CONCURRENT = int(os.environ.get("SB_MAX_CONCURRENT", "2"))

os.makedirs(WORK_ROOT, exist_ok=True)

app = FastAPI(title="SaveBridge free relay")

# Permissive CORS so the extension (any origin, custom X-SaveBridge-* headers,
# and the OPTIONS preflight they trigger) can reach us from any host, no matter
# what URL the tunnel/host hands us.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# --------------------------------------------------------------------------- #
# Errors -- shape matches packages/shared/src/errors.ts so the extension shows a
# friendly Hebrew message.
# --------------------------------------------------------------------------- #

def err(code: str, he: str, en: str, detail: Optional[str] = None) -> Dict[str, Any]:
    e: Dict[str, Any] = {"code": code, "message": he, "messageEn": en}
    if detail:
        e["detail"] = detail[:500]
    return e


ERR_DOWNLOAD = lambda d=None: err(  # noqa: E731
    "E_DOWNLOAD_FAILED", "ההורדה נכשלה.", "The download failed.", d
)
ERR_CANCELLED = err("E_CANCELLED", "ההורדה בוטלה.", "The download was cancelled.")
ERR_NOT_FOUND = err("E_JOB_NOT_FOUND", "ההורדה המבוקשת לא נמצאה.", "The requested download was not found.")


# --------------------------------------------------------------------------- #
# Job registry
# --------------------------------------------------------------------------- #

_jobs: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()
_active = threading.BoundedSemaphore(MAX_CONCURRENT)


class Cancelled(Exception):
    pass


def _new_job(title: str, fmt: str, quality: str) -> Dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "status": "preparing",   # preparing | downloading | completed | failed | cancelled
        "title": title or "video",
        "format": fmt,
        "quality": quality,
        "percent": 0,
        "speed": None,
        "eta": None,
        "error": None,
        "hasFile": False,
        "fileName": None,
        "enc": None,             # never encrypted by this server
        "_dir": None,
        "_path": None,
        "_cancel": False,
    }


def _public(job: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in job.items() if not k.startswith("_")}


# --------------------------------------------------------------------------- #
# yt-dlp option building
# --------------------------------------------------------------------------- #

def _format_selector(fmt: str, quality: str, audio_lang: Optional[str]) -> str:
    """Translate the extension's preset (format+quality) into a yt-dlp -f string."""
    # audio-only preset
    if fmt == "audio":
        return "ba/b"

    # height cap for the video presets ("best" -> no cap)
    height = {"1080": 1080, "720": 720, "480": 480}.get(str(quality))
    vcap = f"[height<=?{height}]" if height else ""

    # prefer a specific audio language track when asked (e.g. Hebrew dub)
    if audio_lang:
        acap = f"[language^=?{audio_lang}]"
        return (
            f"bv*{vcap}+ba{acap}/bv*{vcap}+ba/"
            f"b{vcap}/b"
        )
    return f"bv*{vcap}+ba/b{vcap}/b"


def _build_opts(job: Dict[str, Any], payload: Dict[str, Any], cookiefile: Optional[str]) -> Dict[str, Any]:
    fmt = payload.get("format", "video")
    quality = payload.get("quality", "best")
    audio_lang = payload.get("audioLang")
    sub_lang = payload.get("subLang")

    outtmpl = os.path.join(job["_dir"], "%(title).180B.%(ext)s")

    opts: Dict[str, Any] = {
        "outtmpl": outtmpl,
        "format": _format_selector(fmt, quality, audio_lang),
        "noplaylist": True,
        "restrictfilenames": False,
        "windowsfilenames": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "consoletitle": False,
        "retries": 5,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 4,
        "progress_hooks": [_make_hook(job)],
        "postprocessors": [],
    }

    if cookiefile:
        opts["cookiefile"] = cookiefile

    if fmt == "audio":
        opts["postprocessors"].append(
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"}
        )
    else:
        opts["merge_output_format"] = "mp4"

    if fmt == "low_phone":
        # small, phone-friendly file: cap at 480p and recode to 3gp.
        opts["postprocessors"].append(
            {"key": "FFmpegVideoConvertor", "preferedformat": "3gp"}
        )

    # Best-effort embedded subtitles. yt-dlp fetches them itself (it has the same
    # cookies), so we don't need the extension's captured subData here.
    if sub_lang and fmt != "audio":
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = True
        opts["subtitleslangs"] = [sub_lang, f"{sub_lang}.*"]
        opts["postprocessors"].append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False})

    return opts


def _make_hook(job: Dict[str, Any]):
    def hook(d: Dict[str, Any]) -> None:
        if job["_cancel"]:
            raise Cancelled()
        status = d.get("status")
        if status == "downloading":
            job["status"] = "downloading"
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            if total:
                job["percent"] = max(0, min(99, int(done * 100 / total)))
            spd = d.get("speed")
            job["speed"] = _human_speed(spd) if spd else None
            job["eta"] = d.get("eta")
        elif status == "finished":
            # a stream finished downloading; muxing/processing still to come
            job["percent"] = max(job["percent"], 99)
    return hook


def _human_speed(bps: float) -> str:
    units = ["B/s", "KB/s", "MB/s", "GB/s"]
    i = 0
    v = float(bps)
    while v >= 1024 and i < len(units) - 1:
        v /= 1024
        i += 1
    return f"{v:.1f}{units[i]}"


def _find_output(job_dir: str) -> Optional[str]:
    best = None
    best_size = -1
    for name in os.listdir(job_dir):
        if name.endswith((".part", ".ytdl", ".temp")):
            continue
        # skip leftover standalone subtitle files
        if name.endswith((".vtt", ".srt")):
            continue
        path = os.path.join(job_dir, name)
        if not os.path.isfile(path):
            continue
        size = os.path.getsize(path)
        if size > best_size:
            best_size = size
            best = path
    return best


# --------------------------------------------------------------------------- #
# Worker
# --------------------------------------------------------------------------- #

def _run_job(job_id: str, payload: Dict[str, Any]) -> None:
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        return

    cookiefile = None
    acquired = False
    try:
        _active.acquire()
        acquired = True

        job["_dir"] = os.path.join(WORK_ROOT, job_id)
        os.makedirs(job["_dir"], exist_ok=True)

        cookies = payload.get("cookies")
        if cookies:
            fd, cookiefile = tempfile.mkstemp(prefix="ck_", suffix=".txt", dir=job["_dir"])
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(cookies)

        opts = _build_opts(job, payload, cookiefile)
        url = payload.get("url")
        if not url:
            job["status"] = "failed"
            job["error"] = err("E_INVALID_URL", "הכתובת אינה תקינה.", "The URL is invalid.")
            return

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        if job["_cancel"]:
            job["status"] = "cancelled"
            job["error"] = ERR_CANCELLED
            return

        out = _find_output(job["_dir"])
        if not out:
            job["status"] = "failed"
            job["error"] = ERR_DOWNLOAD("no output file produced")
            return

        job["_path"] = out
        job["fileName"] = os.path.basename(out)
        job["hasFile"] = True
        job["percent"] = 100
        job["status"] = "completed"

    except Cancelled:
        job["status"] = "cancelled"
        job["error"] = ERR_CANCELLED
    except yt_dlp.utils.DownloadError as e:  # type: ignore[attr-defined]
        job["status"] = "failed"
        job["error"] = ERR_DOWNLOAD(str(e))
    except Exception as e:  # noqa: BLE001
        job["status"] = "failed"
        job["error"] = ERR_DOWNLOAD(str(e))
    finally:
        if cookiefile:
            try:
                os.remove(cookiefile)
            except OSError:
                pass
        if acquired:
            _active.release()


# --------------------------------------------------------------------------- #
# Auth helper
# --------------------------------------------------------------------------- #

def _check_auth(authorization: Optional[str]) -> None:
    if not SB_TOKEN:
        return  # open server
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if token != SB_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@app.get("/")
def root() -> Dict[str, Any]:
    return {"service": "savebridge-free-relay", "ok": True}


@app.post("/api/hello")
async def hello() -> Dict[str, Any]:
    # The extension registers here and stores whatever token we return. When a
    # shared secret is configured we hand it back so the extension is authorized
    # automatically; otherwise any non-empty token works.
    return {"token": SB_TOKEN or "open"}


@app.get("/api/ping")
async def ping(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _check_auth(authorization)
    try:
        version = yt_dlp.version.__version__
    except Exception:  # noqa: BLE001
        version = None
    return {"ytDlp": version, "ffmpeg": shutil.which("ffmpeg") is not None}


@app.post("/api/start")
async def start(request: Request, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _check_auth(authorization)
    payload = await request.json()
    job = _new_job(
        title=str(payload.get("title") or "video"),
        fmt=str(payload.get("format") or "video"),
        quality=str(payload.get("quality") or "best"),
    )
    with _lock:
        _jobs[job["id"]] = job
    threading.Thread(target=_run_job, args=(job["id"], payload), daemon=True).start()
    return {"jobId": job["id"]}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str, authorization: Optional[str] = Header(default=None)) -> JSONResponse:
    _check_auth(authorization)
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        return JSONResponse(status_code=404, content=ERR_NOT_FOUND)
    return JSONResponse(content=_public(job))


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _check_auth(authorization)
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="not found")
    job["_cancel"] = True
    return {"ok": True}


@app.get("/api/jobs/{job_id}/file")
async def get_file(job_id: str, token: str = "") -> FileResponse:
    # The browser's downloads API fetches this URL directly (no Bearer header),
    # so the token rides in the query string when a shared secret is set.
    if SB_TOKEN and token != SB_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")
    with _lock:
        job = _jobs.get(job_id)
    if job is None or not job.get("_path") or not os.path.isfile(job["_path"]):
        raise HTTPException(status_code=404, detail="not found")
    filename = job.get("fileName") or os.path.basename(job["_path"])
    return FileResponse(job["_path"], filename=filename, media_type="application/octet-stream")


# --------------------------------------------------------------------------- #
# Housekeeping: drop finished jobs (and their files) after a while.
# --------------------------------------------------------------------------- #

def _janitor() -> None:
    """Every 10 min, delete job folders (and their registry entries) older than
    an hour, so a long-running server doesn't fill the disk."""
    while True:
        time.sleep(600)
        cutoff = time.time() - 3600
        try:
            names = os.listdir(WORK_ROOT)
        except OSError:
            continue
        for name in names:
            path = os.path.join(WORK_ROOT, name)
            try:
                if os.path.isdir(path) and os.path.getmtime(path) < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
                    with _lock:
                        _jobs.pop(name, None)
            except OSError:
                pass


threading.Thread(target=_janitor, daemon=True).start()


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "9797"))
    uvicorn.run(app, host="0.0.0.0", port=port)
