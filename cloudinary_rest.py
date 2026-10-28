#!/usr/bin/env python3
"""Cloudinary server-side REST video uploads using HTTP Basic authentication.

The credentials are taken only from GitHub Action Secrets. Requests are made
over HTTPS and never log API secrets, credentials or signed URLs. The SDK
signed-upload path was returning AuthorizationRequired even when an isolated
Basic Auth and signed-auth preflight both succeeded.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
import uuid

import requests

from verify_connections import normalize_cloudinary_url_env


def cloudinary_auth_details():
    """Return cloud name and API auth from validated environment configuration."""
    value = normalize_cloudinary_url_env()
    parsed = urlsplit(value)
    cloud_name = unquote(parsed.hostname or "")
    api_key = unquote(parsed.username or "")
    api_secret = unquote(parsed.password or "")
    if not cloud_name or not api_key or not api_secret:
        raise RuntimeError("Cloudinary credentials are incomplete")
    if any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in cloud_name):
        raise RuntimeError("Cloudinary cloud name contains invalid characters")
    return cloud_name, api_key, api_secret


def _send_chunk(
    *,
    url: str,
    api_key: str,
    api_secret: str,
    filename: str,
    data: bytes,
    folder: str,
    public_id: str,
    overwrite: bool,
    total: int,
    start: int,
    upload_id: str | None,
):
    payload = {
        "folder": folder,
        "public_id": public_id,
        "overwrite": "true" if overwrite else "false",
        "resource_type": "video",
    }
    headers = {}
    if upload_id is not None:
        headers["X-Unique-Upload-Id"] = upload_id
        headers["Content-Range"] = f"bytes {start}-{start + len(data) - 1}/{total}"
    try:
        response = requests.post(
            url,
            auth=(api_key, api_secret),
            data=payload,
            files={"file": (filename, data, "video/mp4")},
            headers=headers,
            timeout=(20, 180),
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Cloudinary network issue ({type(exc).__name__})") from None
    if not response.ok:
        # Never include API response bodies/URLs in public Actions logs.
        raise RuntimeError(f"Cloudinary Video Upload REST returned HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise RuntimeError("Cloudinary returned a non-JSON upload response") from None


def upload_video_rest(
    path: Path,
    public_id: str,
    *,
    folder="shorts-automation",
    overwrite=True,
    chunk_size=6 * 1024 * 1024,
):
    """Upload MP4 via Cloudinary REST Basic Auth, chunking files above 90 MiB."""
    source = Path(path)
    size = source.stat().st_size
    if size <= 0:
        raise RuntimeError("Refusing to upload an empty video")
    cloud_name, api_key, api_secret = cloudinary_auth_details()
    url = f"https://api.cloudinary.com/v1_1/{quote(cloud_name, safe='')}/video/upload"
    if size <= 90 * 1024 * 1024:
        with source.open("rb") as video_file:
            data = video_file.read()
        result = _send_chunk(
            url=url, api_key=api_key, api_secret=api_secret,
            filename=source.name, data=data, folder=folder,
            public_id=public_id, overwrite=overwrite,
            total=size, start=0, upload_id=None,
        )
    else:
        upload_id = uuid.uuid4().hex
        result = {}
        with source.open("rb") as video_file:
            start = 0
            while start < size:
                data = video_file.read(chunk_size)
                if not data:
                    raise RuntimeError("Unexpected end of video during chunked upload")
                result = _send_chunk(
                    url=url, api_key=api_key, api_secret=api_secret,
                    filename=source.name, data=data, folder=folder,
                    public_id=public_id, overwrite=overwrite,
                    total=size, start=start, upload_id=upload_id,
                )
                start += len(data)
        if result.get("done") is False:
            raise RuntimeError("Cloudinary chunked upload did not finish")
    if result.get("resource_type") != "video":
        raise RuntimeError("Cloudinary did not acknowledge video resource type")
    link = result.get("secure_url")
    if not isinstance(link, str) or not link.startswith("https://res.cloudinary.com/"):
        raise RuntimeError("Cloudinary did not return a valid HTTPS media delivery URL")
    return link
