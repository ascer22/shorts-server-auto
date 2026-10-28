#!/usr/bin/env python3
"""YouTube RSS -> optional accessible download -> horizontal flip -> Cloudinary -> Buffer.

By default this only checks YouTube RSS. No DRM or access-control bypass.
Use publishing only where you have the necessary rights/permission.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / 'data' / 'state.json'
CONFIG_FILE = ROOT / 'config.json'
ATOM = '{http://www.w3.org/2005/Atom}'
YT = '{http://www.youtube.com/xml/schemas/2015}'
BUFFER_ENDPOINT = 'https://api.buffer.com'
LOG = logging.getLogger('shorts')


def get_config():
    return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))


def read_state():
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding='utf-8'))
    else:
        state = {'scheduled': {}}
    state.setdefault('scheduled', {})
    return state


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_FILE.with_suffix('.tmp')
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temp, STATE_FILE)


def parse_rss(xml_bytes):
    root = ET.fromstring(xml_bytes)
    result = []
    for entry in root.findall(f'{ATOM}entry'):
        identifier = entry.findtext(f'{YT}videoId')
        if not identifier:
            continue
        result.append({
            'id': identifier,
            'title': entry.findtext(f'{ATOM}title', default='Short'),
            'published': entry.findtext(f'{ATOM}published', default=''),
            'youtube_url': f'https://www.youtube.com/watch?v={identifier}',
            'shorts_url': f'https://www.youtube.com/shorts/{identifier}',
        })
    return sorted(result, key=lambda v: v['published'], reverse=True)


def parse_channel_playlist(payload):
    """Normalize yt-dlp --flat-playlist output into the feed item schema."""
    items = []
    for entry in payload.get('entries') or []:
        if not isinstance(entry, dict):
            continue
        identifier = entry.get('id') or entry.get('url')
        if not identifier or len(identifier) != 11 or not all(c.isalnum() or c in '-_' for c in identifier):
            continue
        upload_date = entry.get('upload_date') or ''
        published = (f'{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}'
                     if len(upload_date) == 8 and upload_date.isdigit() else '')
        items.append({
            'id': identifier,
            'title': entry.get('title') or 'Short',
            'published': published,
            'youtube_url': f'https://www.youtube.com/watch?v={identifier}',
            'shorts_url': f'https://www.youtube.com/shorts/{identifier}',
        })
    return items


def load_channel_via_ytdlp(channel_handle, limit=20):
    """Public channel listing fallback; doesn't download video files."""
    handle = '@' + channel_handle.lstrip('@')
    cmd = ['yt-dlp', '--flat-playlist', '--playlist-end', str(limit),
           '--dump-single-json', '--skip-download',
           f'https://www.youtube.com/{handle}/shorts']
    process = subprocess.run(cmd, text=True, capture_output=True, check=True, timeout=120)
    items = parse_channel_playlist(json.loads(process.stdout))
    if not items:
        raise RuntimeError('YouTube channel Shorts listing is empty or inaccessible')
    return items


def load_channel_feed(channel_id=None, channel_handle=None):
    """Read a channel using RSS if its ID is known; otherwise use public Shorts listing."""
    if channel_id:
        url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'
        try:
            with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=30) as response:
                items = parse_rss(response.read())
            if items:
                return items
            LOG.warning('YouTube RSS returned no videos for %s.', channel_handle)
        except Exception as exc:
            LOG.warning('YouTube RSS failed for %s (%s). Using Shorts listing.', channel_handle, exc)
    if not channel_handle:
        raise RuntimeError('No channel handle available for Shorts listing')
    return load_channel_via_ytdlp(channel_handle)


def collect_source_shorts(cfg, state):
    """Collect from all sources; prioritize a different source after each scheduled post.

    A failure of an individual source does not block the other configured sources.
    """
    sources = cfg.get('youtube_sources')
    if not sources:
        sources = [{'handle': cfg['youtube_handle'],
                    'channel_id': cfg.get('youtube_channel_id')}]
    groups = []
    known_ids = set()
    for source in sources:
        handle = source['handle']
        try:
            videos = load_channel_feed(source.get('channel_id'), handle)
        except Exception as exc:
            LOG.warning('Source %s unavailable: %s', handle, exc)
            continue
        entries = []
        for video in videos:
            if video['id'] in state['scheduled'] or video['id'] in known_ids:
                continue
            known_ids.add(video['id'])
            entries.append({**video, 'source_handle': handle})
        LOG.info('YouTube %s: %d recent, %d unscheduled', handle, len(videos), len(entries))
        groups.append((handle, entries))
    if not groups:
        raise RuntimeError('No YouTube channel could be checked. See warnings above.')
    previous = state.get('last_scheduled_source')
    names = [handle for handle, _ in groups]
    offset = (names.index(previous) + 1) % len(groups) if previous in names else 0
    ordered = groups[offset:] + groups[:offset]
    combined = []
    for index in range(max(len(videos) for _, videos in ordered)):
        for handle, videos in ordered:
            if index < len(videos):
                combined.append(videos[index])
    return combined


def video_info(url):
    p = subprocess.run(
        ['yt-dlp', '--no-playlist', '--dump-single-json', '--skip-download', url],
        text=True, capture_output=True, check=True, timeout=120,
    )
    return json.loads(p.stdout)


def is_eligible(info, max_duration):
    duration = info.get('duration')
    if not duration or not (3 <= duration <= max_duration):
        return False
    return info.get('live_status') not in ('is_live', 'is_upcoming')


def download_mirror(url, destination, mirror=True):
    destination.parent.mkdir(exist_ok=True, parents=True)
    with tempfile.TemporaryDirectory(prefix='shorts_') as tmp:
        work = Path(tmp)
        subprocess.run([
            'yt-dlp', '--no-playlist', '--no-progress',
            '-f', 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best',
            '--merge-output-format', 'mp4',
            '-o', str(work / 'source.%(ext)s'), url,
        ], check=True, timeout=600)
        matches = [p for p in work.glob('source.*') if p.suffix.lower() in ('.mp4', '.webm', '.mkv')]
        if not matches:
            raise RuntimeError('YouTube did not provide an accessible video file')
        source = matches[0]
        cmd = [
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
            '-i', str(source), '-map', '0:v:0', '-map', '0:a:0?',
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '24',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart',
        ]
        if mirror:
            cmd.extend(['-vf', 'hflip'])
        cmd.append(str(destination))
        subprocess.run(cmd, check=True, timeout=600)
        if not destination.exists() or destination.stat().st_size < 1024:
            raise RuntimeError('Output MP4 was empty')
    return destination


def upload_cloudinary(file_path: Path, public_id: str):
    # Direct REST Basic Auth is verified by the credentials-only preflight.
    # The earlier Python SDK signature flow returned AuthorizationRequired.
    from cloudinary_rest import upload_video_rest

    return upload_video_rest(
        file_path,
        public_id=public_id,
        folder="shorts-automation",
        overwrite=True,
    )


def gql(api_key, query):
    response = requests.post(
        BUFFER_ENDPOINT,
        json={'query': query},
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        timeout=45,
    )
    response.raise_for_status()
    data = response.json()
    if data.get('errors'):
        raise RuntimeError(f'Buffer GraphQL: {data["errors"]}')
    return data.get('data') or {}


def buffer_tiktok_channel(api_key, target_handle, explicit_id=None):
    organizations = gql(api_key, 'query { account { organizations { id name } } }')\
        .get('account', {}).get('organizations', [])
    candidates = []
    for org in organizations:
        query = 'query { channels(input: { organizationId: %s }) { id name displayName service isQueuePaused } }' % json.dumps(org['id'])
        candidates.extend(gql(api_key, query).get('channels') or [])
    tiktoks = [c for c in candidates if str(c.get('service', '')).lower() == 'tiktok']
    if explicit_id:
        chosen = [c for c in tiktoks if c['id'] == explicit_id]
    else:
        normalized = target_handle.lower().lstrip('@').strip()
        chosen = [c for c in tiktoks if normalized in [
            str(c.get('name') or '').lower().lstrip('@'),
            str(c.get('displayName') or '').lower().lstrip('@'),
        ]]
    if len(chosen) != 1:
        names = ', '.join(f"{c.get('name')} ({c.get('id')})" for c in tiktoks) or 'none'
        raise RuntimeError(f'Cannot unambiguously select TikTok channel. Available: {names}. Set BUFFER_CHANNEL_ID variable.')
    channel = chosen[0]
    if channel.get('isQueuePaused'):
        raise RuntimeError('TikTok queue is paused in Buffer; unpause before scheduling.')
    return channel['id']


def next_publication(now_utc: datetime, target_tz='Europe/Moscow', clock='18:00'):
    local = now_utc.astimezone(ZoneInfo(target_tz))
    hour, minute = map(int, clock.split(':'))
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if (candidate - local).total_seconds() < 30 * 60:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def create_buffer_post(api_key, channel_id, title, video_url, due_at, suffix):
    text = f'{title}\n{suffix}'.strip()[:2100]
    query = '''mutation CreatePost {
      createPost(input: {
        text: %s
        channelId: %s
        schedulingType: automatic
        mode: customScheduled
        dueAt: %s
        assets: [{ video: { url: %s } }]
      }) {
        ... on PostActionSuccess { post { id text } }
        ... on MutationError { message }
      }
    }''' % tuple(json.dumps(x, ensure_ascii=False) for x in (text, channel_id, due_at, video_url))
    result = gql(api_key, query).get('createPost') or {}
    if result.get('message'):
        raise RuntimeError(f"Buffer refused post: {result['message']}")
    post = result.get('post') or {}
    if not post.get('id'):
        raise RuntimeError(f'Buffer did not confirm a scheduled post: {result}')
    return post['id']


def run(mode):
    cfg = get_config()
    state = read_state()
    new_videos = collect_source_shorts(cfg, state)
    LOG.info('Total unscheduled Shorts across sources: %d', len(new_videos))
    if mode == 'check':
        for item in new_videos[:30]:
            print(f"{item['source_handle']} | {item['published'][:10]} | {item['title']} | {item['shorts_url']}")
        print('CHECK ONLY: Nothing downloaded, uploaded, or scheduled.')
        return 0

    if os.environ.get('ENABLE_AUTOMATION') != 'true':
        raise RuntimeError('ENABLE_AUTOMATION must be set to true in GitHub Actions Variables')
    api_key = os.environ.get('BUFFER_API_KEY')
    cloudinary_url_present = bool(os.environ.get('CLOUDINARY_URL'))
    cloudinary_split_present = all(os.environ.get(key) for key in (
        'CLOUDINARY_CLOUD_NAME', 'CLOUDINARY_API_KEY', 'CLOUDINARY_API_SECRET'))
    if not api_key or not (cloudinary_url_present or cloudinary_split_present):
        raise RuntimeError('Configure Buffer API Key and either CLOUDINARY_URL or three individual Cloudinary secrets')
    channel = buffer_tiktok_channel(
        api_key, os.environ.get('TARGET_TIKTOK_HANDLE') or cfg['target_tiktok_handle'],
        explicit_id=os.environ.get('BUFFER_CHANNEL_ID') or None,
    )
    max_seconds = int(cfg.get('max_video_duration_seconds', 180))
    count = int(cfg.get('max_candidates_per_run', 5))
    for item in new_videos[:count]:
        try:
            info = video_info(item['youtube_url'])
            if not is_eligible(info, max_seconds):
                LOG.info('Skip longer or live video %s', item['id'])
                continue
            with tempfile.TemporaryDirectory(prefix='work_') as temp:
                path = Path(temp) / f"{item['id']}.mp4"
                download_mirror(item['youtube_url'], path, cfg.get('mirror_horizontal', True))
                remote_url = upload_cloudinary(path, item['id'])
            date = next_publication(datetime.now(timezone.utc), cfg['publish_timezone'], cfg['publish_time'])
            post_id = create_buffer_post(api_key, channel, item['title'], remote_url, date, cfg['description_suffix'])
            state['scheduled'][item['id']] = {
                'title': item['title'], 'youtube': item['shorts_url'],
                'source_handle': item['source_handle'],
                'cloudinary_url': remote_url, 'buffer_post_id': post_id,
                'scheduled_at_utc': date,
            }
            state['last_scheduled_source'] = item['source_handle']
            save_state(state)
            LOG.info('Scheduled %s for %s via Buffer post %s', item['shorts_url'], date, post_id)
            return 0
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, RuntimeError, ValueError, OSError, requests.RequestException) as ex:
            LOG.warning('Could not process %s: %s', item['shorts_url'], ex)
    LOG.warning('No short was successfully scheduled. Feed may have long/private/unavailable videos.')
    return 2


def main():
    parser = argparse.ArgumentParser(description='Daily Shorts -> Cloudinary -> Buffer scheduler')
    parser.add_argument('--mode', choices=['check', 'publish'], default='check')
    args = parser.parse_args()
    logging.basicConfig(format='%(levelname)s %(message)s', level=logging.INFO)
    try:
        return run(args.mode)
    except Exception as ex:
        LOG.exception('Pipeline failed: %s', ex)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
