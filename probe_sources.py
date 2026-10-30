#!/usr/bin/env python3
"""Read-only verification that YouTube Shorts are accessible from ONLY user-selected channels.

No video downloading, modification, upload to Cloudinary, Buffer post, or TikTok post.
A failed source is never silently replaced with third-party/stock/AI content.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from pipeline import get_config, parse_channel_playlist

ALLOWED_HANDLES = frozenset({"@i11ush", "@keymood_yt", "@world_edges"})


def sanitize(error: str) -> str:
    lines = [l.strip() for l in error.splitlines() if l.strip()]
    # Avoid sending URLs, raw tokens, cookies, or query parameters to public logs.
    result = " ".join(lines[-2:]).lower()
    known = (
        ("sign in to confirm", "YouTube requested a logged-in session / bot verification"),
        ("requested format is not available", "YouTube formats unavailable"),
        ("http error 403", "YouTube denied video metadata (HTTP 403)"),
        ("http error 429", "YouTube rate-limited this GitHub runner (HTTP 429)"),
        ("video unavailable", "YouTube video unavailable"),
        ("timed out", "Video metadata request timed out"),
        ("not a bot", "YouTube requested bot verification"),
        ("403 forbidden", "YouTube denied request (HTTP 403)"),
    )
    for pattern, label in known:
        if pattern in result:
            return label
    return "Unable to access metadata from GitHub Actions runner"


def get_candidates(handle: str, count=2):
    cmd = [
        "yt-dlp", "--ignore-config", "--flat-playlist",
        "--playlist-end", str(count),
        "--skip-download", "--dump-single-json", "--no-warnings",
        "--socket-timeout", "15", "--retries", "1",
        f"https://www.youtube.com/{handle}/shorts",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=95)
    if proc.returncode:
        print(f"SOURCE {handle}: channel listing not accessible: {sanitize(proc.stderr)}")
        return []
    return parse_channel_playlist(json.loads(proc.stdout))[:count]


def test_metadata(video: dict):
    cmd = [
        "yt-dlp", "--ignore-config", "--no-playlist",
        "--dump-single-json", "--skip-download", "--no-warnings",
        "--socket-timeout", "15", "--retries", "1",
        video["youtube_url"],
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=65)
    except subprocess.TimeoutExpired:
        return False, "Timed out while requesting video metadata"
    if proc.returncode:
        return False, sanitize(proc.stderr)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return False, "YouTube returned invalid metadata"
    duration = data.get("duration")
    if not isinstance(duration, (int, float)) or not 3 <= duration <= 180:
        return False, f"Not eligible: duration={duration}"
    return True, f"Video metadata OK, {round(duration)}s"


def main():
    cfg = get_config()
    sources = [entry["handle"] for entry in cfg.get("youtube_sources", [])]
    if len(sources) != 3 or set(sources) != ALLOWED_HANDLES:
        print("REFUSING: YouTube sources do not match user-approved channel allowlist.")
        return 2
    print("APPROVED YOUTUBE CHANNELS ONLY:", ", ".join(sources))
    print("NO FALLBACK TO NASA, STOCK, AI, OR UNAPPROVED CHANNELS.")
    accessible = []
    for handle in sources:
        try:
            candidates = get_candidates(handle)
        except (subprocess.TimeoutExpired, ValueError, OSError):
            print(f"SOURCE {handle}: channel listing failed.")
            continue
        print(f"SOURCE {handle}: {len(candidates)} recent candidate(s) checked.")
        for video in candidates:
            valid, note = test_metadata(video)
            print(f"  {video['id']} from {handle}: {note}")
            if valid:
                accessible.append((handle, video["id"]))
                break
    if accessible:
        print("ACCESSIBLE VIDEOS (metadata only):", ", ".join(f"{h}/{id}" for h,id in accessible))
        print("NOTE: Metadata access does not guarantee that an MP4 is downloadable.")
        return 0
    print("RESULT: No selected-channel Short had accessible video metadata.")
    print("No download, Cloudinary upload, Buffer submission, or TikTok publication occurred.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
