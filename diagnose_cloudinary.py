#!/usr/bin/env python3
"""Credential-only Cloudinary diagnostics. Does not upload a file or publish posts.

Uses the *exact three separate GitHub Secrets* and makes:
- an Admin API ping (read-only; can fail if Admin API role restricted)
- an Upload API preflight with NO file (intentionally cannot create media)
  under HTTP Basic authentication
- the same no-file preflight with Cloudinary's SHA-1 signed upload scheme.

The public CI logs never contain cloud name, API key, secret, URLs, hashes,
API response bodies, authorization headers, or credential lengths.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen


def get_credentials(env=os.environ):
    names = ["CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET"]
    missing = [name for name in names if not env.get(name, "").strip()]
    if missing:
        print("SECRETS: missing/empty variable names: " + ", ".join(missing))
        return None
    cloud = env[names[0]].strip()
    key = env[names[1]].strip()
    secret = env[names[2]].strip()
    print("SECRETS: all three separate GitHub Secrets are populated.")
    print("FORMAT: cloud name is simple ASCII slug:", bool(re.fullmatch(r"[a-z0-9_-]+", cloud)))
    print("FORMAT: API key consists only of digits:", key.isascii() and key.isdecimal())
    print("FORMAT: API secret contains no angle-bracket placeholders:", "<" not in secret and ">" not in secret)
    print("FORMAT: API secret has leading/trailing whitespace:", env[names[2]] != secret)
    if not re.fullmatch(r"[a-z0-9_-]+", cloud) or not re.fullmatch(r"[0-9]+", key):
        print("FORMAT: one or more fields don't match Cloudinary's expected format.")
        return None
    if "<" in secret or ">" in secret:
        print("FORMAT: API secret appears to contain a placeholder.")
        return None
    return cloud, key, secret


def http_status_only(url: str, *, method="GET", body=None, auth=None):
    # No response body or response headers are logged.
    headers = {"User-Agent": "Cloudinary-Diagnostics/1", "Content-Type": "application/x-www-form-urlencoded"}
    if auth:
        raw = (auth[0] + ":" + auth[1]).encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
    request = Request(url, data=body, method=method, headers=headers)
    try:
        with urlopen(request, timeout=25) as response:
            return response.status
    except HTTPError as error:
        code = error.code
        error.close()
        return code
    except (URLError, TimeoutError, OSError):
        return "NETWORK_ERROR"


def main():
    print("CLOUDINARY DIAGNOSIS: NO MEDIA UPLOAD, NO BUFFER POST, NO TIKTOK PUBLICATION.")
    credentials = get_credentials()
    if not credentials:
        print("DIAGNOSIS: incomplete or malformed input. Correct the three GitHub Secrets.")
        return 1

    cloud, key, secret = credentials
    endpoint = f"https://api.cloudinary.com/v1_1/{quote(cloud, safe='')}"
    # An Admin API GET can be denied for restricted keys even when uploads work.
    admin_code = http_status_only(endpoint + "/ping", auth=(key, secret))
    print("ADMIN PING HTTP status:", admin_code)
    print("ADMIN PING NOTE: 401/403 alone does not prove Upload API credentials invalid.")

    # Intentionally omit the mandatory 'file' parameter, so a request cannot
    # upload, overwrite, create, or modify media. A 400 often means authentication
    # succeeded and input validation rejected the missing file.
    basic_code = http_status_only(
        endpoint + "/video/upload",
        method="POST", body=b"",
        auth=(key, secret),
    )
    print("UPLOAD PREFLIGHT (Basic Auth, no file) HTTP status:", basic_code)

    stamp = int(time.time())
    raw_sig = f"timestamp={stamp}{secret}".encode("utf-8")
    signature = hashlib.sha1(raw_sig).hexdigest()
    signed_body = urlencode({
        "timestamp": str(stamp),
        "api_key": key,
        "signature": signature,
    }).encode("ascii")
    signed_code = http_status_only(
        endpoint + "/video/upload",
        method="POST", body=signed_body,
    )
    print("UPLOAD PREFLIGHT (Signed, no file) HTTP status:", signed_code)
    if basic_code in (401, 403) and signed_code in (401, 403):
        print("DIAGNOSIS: Cloudinary rejected both authentications, likely key/secret/cloud mismatch or disabled key.")
        return 2
    if basic_code == 400 or signed_code == 400:
        print("DIAGNOSIS: at least one preflight reached input validation; auth may be valid.")
        return 0
    if basic_code in (200, 201) or signed_code in (200, 201):
        print("DIAGNOSIS: unexpected preflight success; inspect account in Cloudinary Console.")
        return 3
    print("DIAGNOSIS: HTTP statuses were not definitive; check the console and Cloudinary docs.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
