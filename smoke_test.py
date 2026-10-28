#!/usr/bin/env python3
# Credential retest requested by owner after correcting CLOUDINARY_URL; draft only.
"""Manual/one-shot integration smoke test; NEVER schedule or publish to TikTok.

Creates an original 6-second FFmpeg test MP4, uploads to Cloudinary,
checks the public MP4 URL, then creates a Buffer *draft* only.
The draft remains unscheduled. Does not download YouTube videos.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import requests

from verify_connections import verify_buffer, normalize_cloudinary_url_env

BUFFER_ENDPOINT = "https://api.buffer.com"


def make_test_video(path: Path):
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=#293347:s=360x640:r=20:d=6",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
        "-t", "6",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-crf", "25", "-c:a", "aac", "-b:a", "64k",
        "-movflags", "+faststart",
        str(path),
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
    if result.returncode != 0 or not path.is_file() or path.stat().st_size < 1000:
        raise RuntimeError("Synthetic FFmpeg video generation failed")
    print(f"TEST MP4: original 6s 360x640 clip generated ({path.stat().st_size // 1024} KB).")


def upload_video(path: Path):
    from cloudinary import config, uploader

    normalize_cloudinary_url_env()
    cloud = config()
    if not (cloud.cloud_name and cloud.api_key and cloud.api_secret):
        raise RuntimeError("Cloudinary credentials are incomplete")
    # Do not hard-code the cloud name based on screenshots: let the authenticated
    # Upload API verify that all three credentials belong to the same account.
    print("CLOUDINARY DIAGNOSTICS: complete connection URI parsed; checking Upload API.")
    # Deliberately use the same Video Upload API as the actual pipeline.
    run_id = os.getenv("GITHUB_RUN_ID") or "manual"
    result = uploader.upload(
        str(path),
        resource_type="video",
        folder="shorts-integration-tests",
        public_id=f"original-smoke-{run_id}",
        overwrite=False,
    )
    if result.get("resource_type") != "video":
        raise RuntimeError("Cloudinary response did not confirm video upload")
    public_url = result.get("secure_url")
    if not isinstance(public_url, str) or not public_url.startswith("https://"):
        raise RuntimeError("Cloudinary did not return a public HTTPS video URL")
    print("CLOUDINARY: Upload API accepted the original synthetic MP4.")
    return public_url


def check_public_video(url: str):
    # Streaming GET (not a download of the whole media). Public access is
    # essential for Buffer to fetch the file later.
    last_error = None
    for delay in (0, 2, 5, 10):
        if delay:
            time.sleep(delay)
        try:
            with requests.get(
                url, stream=True, timeout=30,
                headers={"Range": "bytes=0-1023"}
            ) as response:
                if response.status_code not in (200, 206):
                    last_error = f"HTTP {response.status_code}"
                    continue
                mime = response.headers.get("content-type", "")
                if not (mime.startswith("video/") or mime.startswith("application/octet-stream")):
                    last_error = f"unexpected content-type: {mime.split(';')[0]}"
                    continue
                chunk = next(response.iter_content(chunk_size=32), b"")
                if not chunk:
                    last_error = "response has no video bytes"
                    continue
                print(f"CLOUDINARY: public video URL is readable (HTTP {response.status_code}).")
                return
        except requests.RequestException as exc:
            last_error = type(exc).__name__
    raise RuntimeError(f"Cloudinary video is not externally readable: {last_error}")


def create_buffer_video_draft(channel_id: str, video_url: str):
    token = os.environ.get("BUFFER_API_KEY", "")
    if not token:
        raise RuntimeError("BUFFER_API_KEY missing in GitHub Secrets")
    query = """
    mutation CreateDraftPost {
      createPost(input: {
        text: "Integration test — video upload check. Do not publish."
        channelId: %s
        schedulingType: automatic
        mode: addToQueue
        saveToDraft: true
        assets: [{ video: { url: %s } }]
      }) {
        ... on PostActionSuccess { post { id text } }
        ... on MutationError { message }
      }
    }""" % (json.dumps(channel_id), json.dumps(video_url))
    response = requests.post(
        BUFFER_ENDPOINT,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": query},
        timeout=60,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Buffer returned HTTP {response.status_code}")
    data = response.json()
    if data.get("errors"):
        raise RuntimeError("Buffer rejected draft GraphQL schema")
    result = (data.get("data") or {}).get("createPost") or {}
    if result.get("message"):
        # MutationError may contain user-facing validation details. Avoid
        # logging entire response or anything credential-like.
        raise RuntimeError("Buffer declined to create video draft (media/permissions validation)")
    post = result.get("post") or {}
    if not post.get("id"):
        raise RuntimeError("Buffer did not return a draft identifier")
    print("BUFFER: video draft created successfully (saveToDraft=true).")
    print("BUFFER: no scheduled or published post was created.")
    return post["id"]


def main():
    print("SMOKE TEST: synthetic test media only; no YouTube download; no TikTok publishing.")
    try:
        channel_id = verify_buffer()
        with tempfile.TemporaryDirectory(prefix="smoke_") as folder:
            video_path = Path(folder) / "original-smoke.mp4"
            make_test_video(video_path)
            url = upload_video(video_path)
            check_public_video(url)
            create_buffer_video_draft(channel_id, url)
        print("SMOKE TEST PASSED: Cloudinary public MP4 -> Buffer video draft.")
        return 0
    except Exception as exc:
        # Avoid secrets and signed URL output in publicly readable logs.
        print(f"SMOKE TEST FAILED: {type(exc).__name__}")
        safe = str(exc)
        if any(s in safe for s in ("Cloudinary", "Buffer", "FFmpeg", "GitHub Secrets")) \
                and all(s not in safe for s in ("cloudinary://", "Authorization:", "Bearer ")):
            print(safe[:180])
        print("No TikTok post was published or scheduled by this script.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
