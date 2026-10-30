#!/usr/bin/env python3
"""Publish one original Russian Venus science short immediately.

Media is a new captioned edit made from NASA SVS public-domain animation.
Reference: https://svs.gsfc.nasa.gov/20308/
Credits: NASA Goddard Space Flight Center Conceptual Image Lab.
This intentionally does NOT download or repost someone else's YouTube Short.
This is a one-time action, not the daily scheduler.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.request import urlopen, Request

import requests

from pipeline import ROOT, gql, read_state, save_state, upload_cloudinary
from verify_connections import verify_buffer

VIDEO_ID = "original-venus-nasa-20261030"
RESULT_FILE = ROOT / "data" / "one-shot-result.json"
SOURCE_MP4 = "https://svs.gsfc.nasa.gov/vis/a020000/a020300/a020308/VenusEvoSeq01to03_21_9_1080.mp4"
SOURCE_PAGE = "https://svs.gsfc.nasa.gov/20308/"
CAPTION = "На Венере оборот вокруг оси длится дольше года! 🤯 #венера #космос #наука | Видео: NASA/GSFC"
SCRIPT = ("На Венере один оборот вокруг оси длится дольше целого года! "
          "Вокруг Солнца планета облетает за двести двадцать пять земных дней. "
          "А полный оборот вокруг собственной оси занимает двести сорок три дня. "
          "И вдобавок Венера вращается в обратную сторону по сравнению с Землёй! "
          "Космос удивляет. Подпишись на новые факты.")
APPROVAL = "POST_ONE_VIDEO_OCT30_2026"


def fetch_nasa_video(destination: Path):
    req = Request(SOURCE_MP4, headers={"User-Agent": "Mozilla/5.0 (education video bot)"})
    with urlopen(req, timeout=55) as source, destination.open("wb") as output:
        total = 0
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > 30 * 1024 * 1024:
                raise RuntimeError("Source NASA video larger than expected, refusing to download")
            output.write(chunk)
    if destination.stat().st_size < 100_000:
        raise RuntimeError("NASA source did not download completely")
    print(f"NASA: acquired public-domain animation ({destination.stat().st_size // 1024} KB).")


def duration(path: Path) -> float:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
                       capture_output=True, text=True, check=True, timeout=25)
    return float(p.stdout.strip())


def make_slide(path: Path, heading: str, body: str, footer: str):
    from PIL import Image, ImageDraw, ImageFont
    W, H = 720, 1280
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.rounded_rectangle((38, 85, W-38, 488), radius=36, fill=(9, 16, 36, 222),
                           outline=(255, 174, 79, 210), width=3)
    draw.rounded_rectangle((38, 1015, W-38, 1190), radius=30, fill=(9, 16, 36, 210))
    bold = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    normal = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font_h = ImageFont.truetype(bold, 49)
    font_b = ImageFont.truetype(normal, 37)
    font_f = ImageFont.truetype(normal, 23)
    def center(lines: list[str], font, start_y: int, fill, gap: int):
        y = start_y
        for line in lines:
            bb = draw.textbbox((0, 0), line, font=font)
            x = (W - (bb[2] - bb[0])) // 2
            draw.text((x, y), line, font=font, fill=fill, stroke_width=1,
                      stroke_fill=(0, 0, 0, 110))
            y += gap
    center(heading.split("\n"), font_h, 145, (255, 187, 93, 255), 65)
    center(body.split("\n"), font_b, 310, (242, 247, 255, 255), 55)
    center(footer.split("\n"), font_f, 1052, (218, 229, 245, 255), 33)
    layer.save(path)


def make_voice(path: Path) -> bool:
    try:
        import edge_tts
        async def create():
            talk = edge_tts.Communicate(text=SCRIPT, voice="ru-RU-SvetlanaNeural", rate="+8%")
            await asyncio.wait_for(talk.save(str(path)), timeout=55)
        asyncio.run(create())
        if path.is_file() and path.stat().st_size > 3000:
            print("VOICE: natural Russian narration generated.")
            return True
    except Exception as error:
        print(f"VOICE: TTS unavailable ({type(error).__name__}); retaining full-screen subtitles and ambient audio.")
    return False


def render_video(folder: Path) -> Path:
    source_path = folder / "nasa.mp4"
    fetch_nasa_video(source_path)
    narration_path = folder / "voice.mp3"
    voice_ok = make_voice(narration_path)
    total = max(28, min(45, math.ceil(duration(narration_path) + 3) if voice_ok else 28))
    slides = [
        ("НА ВЕНЕРЕ", "ОБОРОТ ВОКРУГ ОСИ\nДЛИННЕЕ ЦЕЛОГО ГОДА!", "ФАКТ О КОСМОСЕ"),
        ("225 ДНЕЙ", "Столько длится\nвенерианский год", "Один оборот вокруг Солнца"),
        ("243 ДНЯ", "Столько длится\nоборот Венеры вокруг оси", "Звёздный период вращения"),
        ("И ЭТО НЕ ВСЁ", "Венера вращается\nв обратную сторону", "В отличие от Земли"),
        ("УДИВЛЁН?", "Подпишись на новые\nфакты о космосе", "Видео: NASA/GSFC • монтаж: оригинальный"),
    ]
    boundaries = [0, .20, .41, .62, .82, 1.0]
    image_paths = []
    for i, (heading, body, footer) in enumerate(slides):
        p = folder / f"card{i}.png"
        make_slide(p, heading, body, footer)
        image_paths.append(p)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-stream_loop", "-1", "-i", str(source_path)]
    for path in image_paths:
        cmd += ["-loop", "1", "-i", str(path)]
    voice_index = None
    if voice_ok:
        voice_index = len(image_paths) + 1
        cmd += ["-i", str(narration_path)]
    music_index = len(image_paths) + 1 + (1 if voice_ok else 0)
    cmd += ["-f", "lavfi", "-i",
            f"sine=frequency=220:sample_rate=44100:duration={total}"]
    graph = [
        "[0:v]split=2[base][front]",
        "[base]scale=720:1280:force_original_aspect_ratio=increase,"
        "crop=720:1280,gblur=sigma=35,eq=brightness=-0.18[bg]",
        "[front]scale=720:-2[fg]",
        "[bg][fg]overlay=x=0:y=(H-h)/2:shortest=1[scene0]",
    ]
    for i in range(len(image_paths)):
        start = boundaries[i] * total
        end = boundaries[i+1] * total
        graph.append(f"[scene{i}][{i+1}:v]overlay=x=0:y=0:"
                     f"enable='between(t,{start:.3f},{end:.3f})':shortest=1[scene{i+1}]")
    graph.append(f"[scene{len(image_paths)}]format=yuv420p[v]")
    if voice_ok:
        graph.append(f"[{voice_index}:a]volume=1.0[voice]")
        graph.append(f"[{music_index}:a]volume=0.025[bed]")
        graph.append("[voice][bed]amix=inputs=2:duration=longest[a]")
    else:
        graph.append(f"[{music_index}:a]volume=0.05[a]")
    output = folder / "venus-russian-original.mp4"
    cmd += [
        "-filter_complex", ";".join(graph),
        "-map", "[v]", "-map", "[a]",
        "-t", str(total), "-r", "30", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "25",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        str(output)
    ]
    subprocess.run(cmd, check=True, timeout=480)
    if not output.exists() or output.stat().st_size < 100_000:
        raise RuntimeError("Rendered video is too small")
    print(f"RENDER: {total}s, 720x1280, 30 FPS; {output.stat().st_size // 1024} KB.")
    return output


def publish_now(channel_id: str, video_url: str) -> dict:
    token = os.environ["BUFFER_API_KEY"]
    query = """mutation PublishOriginal {
      createPost(input: {
        text: %s
        channelId: %s
        schedulingType: automatic
        mode: shareNow
        saveToDraft: false
        assets: [{ video: { url: %s } }]
      }) {
        ... on PostActionSuccess { post { id status sharedNow dueAt externalLink } }
        ... on MutationError { message }
      }
    }""" % tuple(json.dumps(x, ensure_ascii=False) for x in (CAPTION, channel_id, video_url))
    resp = gql(token, query).get("createPost") or {}
    if resp.get("message"):
        raise RuntimeError("Buffer declined post: " + str(resp["message"])[:180])
    post = resp.get("post") or {}
    if not post.get("id"):
        raise RuntimeError("Buffer did not confirm a post id")
    return post


def main():
    if os.environ.get("ONE_SHOT_APPROVAL") != APPROVAL:
        raise RuntimeError("One-shot approval missing; refusing to publish")
    if RESULT_FILE.exists():
        old = json.loads(RESULT_FILE.read_text(encoding="utf-8"))
        if old.get("buffer_post_id"):
            print("ALREADY SUBMITTED: refusing duplicate one-shot post.")
            return 0
    state = read_state()
    if VIDEO_ID in state.get("scheduled", {}):
        print("ALREADY SUBMITTED: video found in state; refusing duplicate.")
        return 0
    print("ONE-TIME ORIGINAL SCIENCE SHORT: Venus rotation vs year, credited NASA footage.")
    print("DAILY AUTOMATION: unchanged and disabled.")
    channel_id = verify_buffer()
    with tempfile.TemporaryDirectory(prefix="venus_short_") as dirname:
        video_path = render_video(Path(dirname))
        url = upload_cloudinary(video_path, VIDEO_ID)
    with requests.get(url, stream=True, timeout=35, headers={"Range": "bytes=0-1023"}) as response:
        if response.status_code not in (200, 206):
            raise RuntimeError(f"Cloudinary URL not reachable: HTTP {response.status_code}")
    print("CLOUDINARY: original edit uploaded and available publicly.")
    post = publish_now(channel_id, url)
    info = {
        "video_id": VIDEO_ID,
        "source": SOURCE_PAGE,
        "title": "На Венере оборот вокруг оси длиннее года",
        "caption": CAPTION,
        "buffer_post_id": post["id"],
        "buffer_status_at_submission": post.get("status"),
        "buffer_shared_now": post.get("sharedNow"),
        "buffer_due_at": post.get("dueAt"),
        "tiktok_url_at_submission": post.get("externalLink"),
        "cloudinary_url": url,
        "submitted_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESULT_FILE.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state.setdefault("scheduled", {})[VIDEO_ID] = {
        "title": info["title"], "source_handle": "NASA SVS",
        "cloudinary_url": url, "buffer_post_id": post["id"],
        "mode": "shareNow", "submitted_at_utc": info["submitted_at_utc"],
    }
    save_state(state)
    print(f"BUFFER: accepted one shareNow request; post {post['id']}; status={post.get('status')}.")
    print("TikTok live confirmation requires sent status and published destination URL.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as err:
        print(f"ONE-TIME ORIGINAL PUBLICATION FAILED: {type(err).__name__}.")
        if all(word not in str(err) for word in ("cloudinary://", "Bearer ", "api_secret", "authorization")):
            print(str(err)[:220])
        sys.exit(1)
