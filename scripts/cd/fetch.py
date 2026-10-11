"""One HTTP GET that never raises: the CD scripts decide what a bad answer means."""

from __future__ import annotations

import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit

# url -> (status, body). Status 0 means the request never got an answer.
Fetch = Callable[[str], tuple[int, str]]

TIMEOUT_S = 20
MAX_BYTES = 5_000_000


def cache_busted(url: str) -> str:
    """`url` with a query parameter no other request ever has.

    A CDN may ignore the request's no-cache headers (Fastly served a build.json that was 288
    seconds old under a 600 second max-age), so every probe asks for a URL nobody has cached.
    """
    parts = urlsplit(url)
    token = f"cb={uuid.uuid4().hex}"
    query = f"{parts.query}&{token}" if parts.query else token
    return urlunsplit(parts._replace(query=query))


def http_fetch(url: str) -> tuple[int, str]:
    request = urllib.request.Request(
        url, headers={"Cache-Control": "no-cache", "Pragma": "no-cache", "User-Agent": "cd-probe"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return response.status, response.read(MAX_BYTES).decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, err.read(MAX_BYTES).decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        return 0, str(err)
