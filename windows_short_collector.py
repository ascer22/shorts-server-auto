#!/usr/bin/env python3
"""Automatically save MP4 Shorts from exactly the 3 channels in config.json.

Runs on the owner's Windows computer, not on GitHub-hosted datacenter IPs.
No Buffer publication or Cloudinary upload is performed. Access to video
files is subject to YouTube's actual restrictions and republishing rights.

Usage:
    py -3 windows_short_collector.py --probe
    py -3 windows_short_collector.py
    py -3 windows_short_collector.py --browser edge
    py -3 windows_short_collector.py --max-downloads 2

Never export browser session cookies to a Git repo or to ChatGPT.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.json"
OUT = ROOT / "local_downloads"
STATE_FILE = OUT / "downloaded.json"
LOG = logging.getLogger("shorts.collector")
APPROVED = frozenset(("@i11ush", "@keymood_yt", "@world_edges"))
VIDEO_ID = re.compile(r"^[a-zA-Z0-9_-]{11}$")


def setup_log() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    LOG.setLevel(logging.INFO)
    LOG.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for handler in (logging.StreamHandler(sys.stdout),
                    RotatingFileHandler(OUT / "collector.log", maxBytes=500_000,
                                        backupCount=2, encoding="utf-8")):
        handler.setFormatter(formatter)
        LOG.addHandler(handler)


def load_config():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    sources = cfg.get("youtube_sources", [])
    handles = [x["handle"] for x in sources]
    if len(handles) != 3 or set(handles) != APPROVED:
        raise RuntimeError("Refusing unapproved source; expected only three user-selected channels")
    return cfg, sources


def read_state():
    if not STATE_FILE.exists():
        return {"downloaded": {}, "last_downloaded_source": None}
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    state.setdefault("downloaded", {})
    return state


def save_state(state) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def yt_command(browser: str):
    # Use the browser session on this PC only, never a cookies.txt secret.
    base = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-warnings",
            "--no-progress", "--socket-timeout", "20", "--retries", "1"]
    if browser != "none":
        base += ["--cookies-from-browser", browser]
    return base


def safe_failure(output: str):
    """Convert raw stderr into a category without exposing cookie/session data."""
    s = output.lower()
    for pattern, reason in (
        ("sign in to confirm you're not a bot", "YouTube requires account/bot verification"),
        ("sign in to confirm", "YouTube requires account verification"),
        ("failed to decrypt", "Browser session could not be read; close browser and retry"),
        ("could not copy chrome cookie database", "Browser cookie database locked"),
        ("could not copy", "Browser cookie database locked or inaccessible"),
        ("http error 403", "YouTube returned HTTP 403"),
        ("http error 429", "YouTube rate limiting (429)"),
        ("video unavailable", "Video is unavailable"),
        ("requested format is not available", "No compatible video format"),
        ("ffmpeg", "FFmpeg or media merge error"),
    ):
        if pattern in s:
            return reason
    return "YouTube refused/failed the request; see platform access restrictions"


def run_ytdlp(arguments, browser, *, timeout):
    result = subprocess.run(yt_command(browser) + arguments,
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(safe_failure(result.stderr))
    return result.stdout


def listing(handle, browser, limit):
    output = run_ytdlp(
        ["--flat-playlist", "--playlist-end", str(limit),
         "--skip-download", "--dump-single-json",
         f"https://www.youtube.com/{handle}/shorts"],
        browser, timeout=105
    )
    data = json.loads(output)
    candidates = []
    for item in data.get("entries") or []:
        video_id = item.get("id")
        if not VIDEO_ID.fullmatch(str(video_id or "")):
            continue
        candidates.append({
            "id": video_id,
            "title": item.get("title") or "Short",
            "handle": handle,
            "url": f"https://www.youtube.com/watch?v={video_id}",
        })
    return candidates


def ffprobe_duration(path: Path):
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
        capture_output=True, text=True, check=True, timeout=25,
    )
    return float(p.stdout.strip())


def download_one(video, browser, max_seconds, mirror):
    """Download accessible source into a temporary folder, then export MP4."""
    with tempfile.TemporaryDirectory(prefix="shorts_owner_") as folder:
        tmp = Path(folder)
        output_template = str(tmp / "source.%(ext)s")
        run_ytdlp([
            "--no-playlist", "-f",
            "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/best",
            "--merge-output-format", "mp4",
            "-o", output_template, video["url"]
        ], browser, timeout=450)
        files = [x for x in tmp.glob("source.*")
                 if x.suffix.lower() in (".mp4", ".mkv", ".webm")]
        if not files:
            raise RuntimeError("No downloadable video media was obtained")
        source = max(files, key=lambda x: x.stat().st_size)
        length = ffprobe_duration(source)
        if not (3 <= length <= max_seconds):
            raise RuntimeError(f"Video duration {length:.1f}s is outside 3-{max_seconds}s")
        channel_dir = OUT / video["handle"]
        channel_dir.mkdir(parents=True, exist_ok=True)
        target = channel_dir / (video["id"] + ".mp4")
        pending = channel_dir / (video["id"] + ".pending.mp4")
        command = [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-y", "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart"
        ]
        if mirror:
            command += ["-vf", "hflip"]
        command += [str(pending)]
        try:
            subprocess.run(command, capture_output=True, check=True, timeout=450)
            if not pending.is_file() or pending.stat().st_size < 5000:
                raise RuntimeError("MP4 rendering produced an empty file")
            os.replace(pending, target)
        finally:
            pending.unlink(missing_ok=True)
    return target, round(length, 2)


def main():
    parser = argparse.ArgumentParser(description="Locally download MP4 from approved Shorts channels")
    parser.add_argument("--browser", choices=("none", "edge", "chrome", "firefox"),
                        default="none", help="Use an existing session on THIS PC only")
    parser.add_argument("--probe", action="store_true",
                        help="List recent shorts only, without downloading")
    parser.add_argument("--max-downloads", type=int, default=1,
                        help="Maximum successful MP4 files per run (1-3)")
    parser.add_argument("--per-channel", type=int, default=5,
                        help="Maximum recent Shorts to inspect per channel (1-20)")
    args = parser.parse_args()
    setup_log()
    if not 1 <= args.max_downloads <= 3 or not 1 <= args.per_channel <= 20:
        parser.error("max-downloads must be 1-3; per-channel must be 1-20")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("Install FFmpeg and ensure ffmpeg/ffprobe are available in PATH")
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        raise RuntimeError("Install yt-dlp: py -3 -m pip install -U yt-dlp") from None
    cfg, sources = load_config()
    state = read_state()
    max_seconds = min(180, int(cfg.get("max_video_duration_seconds", 180)))
    mirror = bool(cfg.get("mirror_horizontal", True))
    handles = [s["handle"] for s in sources]
    previous = state.get("last_downloaded_source")
    offset = (handles.index(previous) + 1) % len(handles) if previous in handles else 0
    handles = handles[offset:] + handles[:offset]
    LOG.info("Allowed channels only: %s; browser=%s; upload/publish=OFF.",
             ", ".join(handles), args.browser)
    candidates = []
    for handle in handles:
        try:
            entries = listing(handle, args.browser, args.per_channel)
            LOG.info("%s: found %s Shorts", handle, len(entries))
            candidates.append((handle, entries))
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
            LOG.warning("%s: listing failed (%s)", handle, type(error).__name__
                        if not isinstance(error, RuntimeError) else str(error))
    if args.probe:
        for handle, videos in candidates:
            for v in videos:
                LOG.info("SOURCE %s id=%s title=%s", handle, v["id"],
                         v["title"][:75].replace("\n", " "))
        LOG.info("Probe done: no MP4 files downloaded or published.")
        return 0
    already = state["downloaded"]
    downloaded = 0
    for row in range(max((len(vs) for _, vs in candidates), default=0)):
        for handle, videos in candidates:
            if row >= len(videos):
                continue
            video = videos[row]
            if video["id"] in already:
                continue
            try:
                target, seconds = download_one(video, args.browser, max_seconds, mirror)
                already[video["id"]] = {
                    "source": handle, "title": video["title"],
                    "youtube_url": video["url"], "file": str(target),
                    "seconds": seconds,
                    "downloaded_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")
                }
                state["last_downloaded_source"] = handle
                save_state(state)
                downloaded += 1
                LOG.info("MP4 saved: %s (%ss)", target, seconds)
                if downloaded >= args.max_downloads:
                    LOG.info("Download limit reached. No Cloudinary upload or TikTok post was made.")
                    return 0
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError,
                    RuntimeError, OSError, ValueError) as err:
                message = str(err) if isinstance(err, RuntimeError) else type(err).__name__
                LOG.warning("%s/%s: skipped (%s)", handle, video["id"], message)
    if downloaded:
        LOG.info("Saved %s MP4(s). No Cloudinary upload or TikTok post was made.", downloaded)
        return 0
    LOG.warning("No MP4 could be fetched this run. This may be YouTube bot verification.")
    LOG.warning("Never switch to an unapproved channel or alternative footage.")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        # Avoid leaking cookies or login tokens in job logs.
        print(f"Collector stopped: {type(error).__name__}")
        if isinstance(error, RuntimeError):
            print(str(error)[:220])
        sys.exit(2)
