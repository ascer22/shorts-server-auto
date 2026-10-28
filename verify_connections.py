#!/usr/bin/env python3
"""Read-only verification of Cloudinary and Buffer credentials from GitHub Secrets.

Does not download videos, upload media, create Buffer posts, or publish anything.
Does not print API keys, API secrets, or connection strings.
"""
from __future__ import annotations

import json
import os
import sys

import requests

BUFFER_API = "https://api.buffer.com"


def query_buffer(token: str, query: str, *, http=requests.post):
    response = http(
        BUFFER_API,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": query},
        timeout=25,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("errors"):
        raise RuntimeError("Buffer GraphQL query was rejected")
    return data.get("data") or {}


def verify_buffer():
    token = os.getenv("BUFFER_API_KEY")
    if not token:
        raise RuntimeError("Missing GitHub Secret BUFFER_API_KEY")
    root = query_buffer(token, "query { account { organizations { id name } } }")
    organizations = (root.get("account") or {}).get("organizations") or []
    channels = []
    for org in organizations:
        org_id = json.dumps(org["id"])
        result = query_buffer(token, f"query {{ channels(input: {{ organizationId: {org_id} }}) {{ id name service }} }}")
        channels.extend(result.get("channels") or [])
    tiktoks = [c for c in channels if str(c.get("service", "")).lower() == "tiktok"]
    target = os.getenv("TARGET_TIKTOK_HANDLE", "kaspy_58").lower().lstrip("@")
    selected = [c for c in tiktoks if str(c.get("name", "")).lower().lstrip("@") == target]
    print(f"BUFFER: authentication OK; organizations={len(organizations)}; TikTok channels={len(tiktoks)}.")
    if len(selected) != 1:
        raise RuntimeError(f"Expected one connected TikTok channel @{target}; found {len(selected)}")
    print(f"BUFFER: target @{target} found. No posts were created.")
    return selected[0]["id"]


def normalize_cloudinary_url_env():
    """Normalize a Cloudinary environment URI without printing its credentials.

    The GitHub Secret needs one complete URI, not merely an API key or
    API secret. Accept common dashboard copy/paste wrappers.
    """
    import re
    raw = os.getenv("CLOUDINARY_URL", "")
    value = raw.strip().strip("\x60")
    if not value:
        print("CLOUDINARY FORMAT: GitHub secret is absent or empty.")
        raise RuntimeError("CLOUDINARY_URL secret is empty")
    # Dashboard may copy a shell assignment, optionally prefixed with export.
    value = re.sub(r"^(?:export\\s+)?CLOUDINARY_URL\\s*=\\s*", "", value, count=1, flags=re.I)
    value = value.strip().strip("\x60").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1].strip()
    value = value.strip()
    if not value.lower().startswith("cloudinary://"):
        if value.isdigit():
            reason = "API key only (numeric); full connection URI required"
        elif value.lower().startswith(("http://", "https://")):
            reason = "website URL rather than cloudinary:// connection URI"
        elif ("api_key" in value.lower() or "api_secret" in value.lower()
              or "\\n" in value):
            reason = "Cloudinary fields/template rather than single connection URI"
        else:
            reason = "unrecognized connection string format"
        print(f"CLOUDINARY FORMAT: {reason}. Secret value not displayed.")
        raise RuntimeError("CLOUDINARY_URL format is not a cloudinary:// URI")
    # Validate basic structure without ever echoing the secret or cloud name.
    from urllib.parse import urlsplit
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "cloudinary" or not parsed.username or not parsed.password or not parsed.hostname:
            raise ValueError("missing URI components")
    except (ValueError, TypeError):
        print("CLOUDINARY FORMAT: cloudinary:// URI is missing one or more components.")
        raise RuntimeError("CLOUDINARY_URL URI components are incomplete") from None
    print("CLOUDINARY FORMAT: full cloudinary:// URI recognized. Value remains masked.")
    os.environ["CLOUDINARY_URL"] = value
    return value


def verify_cloudinary():
    normalize_cloudinary_url_env()
    import cloudinary
    conf = cloudinary.config()
    if not all((conf.cloud_name, conf.api_key, conf.api_secret)):
        raise RuntimeError("Cloudinary connection string is incomplete")
    # Admin API ping() requires broader permissions than the Upload API.
    # A restricted Media Library User API key can therefore fail ping() even
    # when its credentials have been entered correctly. Do not request
    # elevated permissions solely for this read-only configuration check.
    print("CLOUDINARY: secret is present and SDK credentials are parsed.")
    print("CLOUDINARY: upload permissions NOT yet tested; Admin API ping skipped.")


def main():
    failed = False
    for name, fn in (("BUFFER", verify_buffer), ("CLOUDINARY", verify_cloudinary)):
        try:
            fn()
        except Exception as exc:
            # Avoid printing exception details: some SDKs include URLs or credentials.
            print(f"{name}: FAILED ({type(exc).__name__}).")
            if str(exc).startswith(("Missing GitHub", "Expected one connected TikTok", "CLOUDINARY_URL must", "Cloudinary connection string")):
                print(f"{name}: {exc}")
            failed = True
    if failed:
        print("CHECK FAILED. Publishing remains disabled.")
        return 1
    print("CHECK COMPLETE: Buffer authenticated; Cloudinary config parsed only. Nothing uploaded or published.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
