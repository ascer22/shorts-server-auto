#!/usr/bin/env python3
"""One-time publish-now for one specifically selected YouTube Short.

This is deliberately separate from the daily scheduler. It never changes
ENABLE_AUTOMATION or posts on a recurring schedule. It accepts one explicit
GitHub Actions opt-in value and one pinned video. Reruns do not post again
when a successful result is already committed to the repository.

Only use for content that you are authorized to republish on TikTok.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import requests

from pipeline import (
    STATE_FILE,
    ROOT,
    download_mirror,
    gql,
    is_eligible,
    read_state,
    save_state,
    upload_cloudinary,
    video_info,
)
from verify_connections import verify_buffer

VIDEO_ID = "e-m3fpa5m-w"
SOURCE = "@i11ush"
SOURCE_TITLE = "Благодарность за спасение"
YOUTUBE_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
SHORTS_URL = f"https://www.youtube.com/shorts/{VIDEO_ID}"
RESULT_FILE = ROOT / "data" / "one-shot-result.json"
EXPECTED_APPROVAL = "POST_ONE_VIDEO_OCT30_2026"
CAPTION = "Благодарность за спасение ❤️ #истории #доброта #shorts"


def verify_video_format(path: Path) -> None:
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,avg_frame_rate,codec_name",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30, check=True,
    )
    streams = json.loads(p.stdout).get("streams") or []
    if not streams:
        raise RuntimeError("Video stream is missing")
    stream = streams[0]
    w, h = int(stream.get("width") or 0), int(stream.get("height") or 0)
    fraction = stream.get("avg_frame_rate", "0/1").split("/")
    fps = float(fraction[0]) / float(fraction[1]) if len(fraction) == 2 and float(fraction[1]) else 0
    if w < 360 or h < 360 or not (23 <= fps <= 60):
        raise RuntimeError(f"Video format not suitable for Buffer TikTok: {w}x{h}, {fps:.2f} fps")
    if stream.get("codec_name") != "h264":
        raise RuntimeError("Video must be encoded with H.264")
    print(f"VIDEO: MP4 ready; {w}x{h}, {fps:.2f} fps, H.264; mirrored horizontally.")


def publish_now(channel_id: str, video_url: str) -> dict:
    token = os.getenv("BUFFER_API_KEY", "")
    if not token:
        raise RuntimeError("GitHub Secret BUFFER_API_KEY is missing")
    query = """mutation PublishOneShort {
      createPost(input: {
        text: %s
        channelId: %s
        schedulingType: automatic
        mode: shareNow
        saveToDraft: false
        assets: [{ video: { url: %s, metadata: { thumbnailOffset: 1000 } } }]
      }) {
        ... on PostActionSuccess {
          post { id status sharedNow dueAt externalLink }
        }
        ... on MutationError { message }
      }
    }""" % tuple(json.dumps(s, ensure_ascii=False) for s in (CAPTION, channel_id, video_url))
    result = gql(token, query).get("createPost") or {}
    if result.get("message"):
        raise RuntimeError("Buffer rejected immediate TikTok post: " + str(result["message"])[:240])
    post = result.get("post") or {}
    if not post.get("id"):
        raise RuntimeError("Buffer did not return a post ID")
    return post


def main() -> int:
    logging.basicConfig(format="%(levelname)s %(message)s", level=logging.INFO)
    if os.getenv("ONE_SHOT_APPROVAL") != EXPECTED_APPROVAL:
        raise RuntimeError("One-time publication requires the exact GitHub opt-in")
    if RESULT_FILE.exists():
        prior = json.loads(RESULT_FILE.read_text(encoding="utf-8"))
        if prior.get("buffer_post_id"):
            print("ALREADY SUBMITTED: one-time result exists. Not posting a duplicate.")
            return 0
    state = read_state()
    if VIDEO_ID in state.get("scheduled", {}):
        print("ALREADY SUBMITTED: video exists in scheduling history. Not posting a duplicate.")
        return 0
    print(f"ONE-TIME PUBLICATION: {SOURCE_TITLE}, source {SOURCE}, video {VIDEO_ID}.")
    print("AUTOMATIC DAILY POSTING: not enabled or modified by this action.")
    info = video_info(YOUTUBE_URL)
    if not is_eligible(info, 180):
        raise RuntimeError("Chosen video is not eligible: must be 3-180 seconds and not a live stream")
    print(f"VIDEO: source duration {info.get('duration')} seconds; title available.")
    channel_id = verify_buffer()
    with tempfile.TemporaryDirectory(prefix="tiktok_once_") as folder:
        video_path = Path(folder) / f"{VIDEO_ID}.mp4"
        download_mirror(YOUTUBE_URL, video_path, mirror=True)
        verify_video_format(video_path)
        remote_url = upload_cloudinary(video_path, f"one-shot-{VIDEO_ID}")
    with requests.get(remote_url, stream=True, timeout=35, headers={"Range": "bytes=0-256"}) as check:
        if check.status_code not in (200, 206):
            raise RuntimeError(f"Video URL cannot be accessed by Buffer: HTTP {check.status_code}")
    print("CLOUDINARY: video uploaded; public URL accessible.")
    post = publish_now(channel_id, remote_url)
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = {
        "video_id": VIDEO_ID,
        "source": SOURCE,
        "youtube_url": SHORTS_URL,
        "title": SOURCE_TITLE,
        "caption": CAPTION,
        "buffer_post_id": post["id"],
        "buffer_status_at_submission": post.get("status"),
        "buffer_shared_now": post.get("sharedNow"),
        "buffer_due_at": post.get("dueAt"),
        "tiktok_url_at_submission": post.get("externalLink"),
        "cloudinary_url": remote_url,
        "submitted_at_utc": timestamp,
    }
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULT_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state.setdefault("scheduled", {})[VIDEO_ID] = {
        "title": SOURCE_TITLE,
        "youtube": SHORTS_URL,
        "source_handle": SOURCE,
        "cloudinary_url": remote_url,
        "buffer_post_id": post["id"],
        "submitted_at_utc": timestamp,
        "mode": "shareNow",
    }
    state["last_scheduled_source"] = SOURCE
    save_state(state)
    print("BUFFER: accepted one shareNow publication request.")
    print(f"BUFFER: post id {post['id']}; initial status {post.get('status')}; sharedNow={post.get('sharedNow')}.")
    print("NOTICE: Buffer acceptance is not confirmation that TikTok has published the video.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # Never print secrets, token or Cloudinary URL, including in tracebacks.
        print(f"ONE-TIME PUBLICATION FAILED: {type(exc).__name__}")
        message = str(exc)
        if "cloudinary://" not in message and "Bearer " not in message:
            print(message[:240])
        sys.exit(1)
