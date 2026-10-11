"""One HTTP GET that never raises: the CD scripts decide what a bad answer means."""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable

# url -> (status, body). Status 0 means the request never got an answer.
Fetch = Callable[[str], tuple[int, str]]

TIMEOUT_S = 20
MAX_BYTES = 5_000_000


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
