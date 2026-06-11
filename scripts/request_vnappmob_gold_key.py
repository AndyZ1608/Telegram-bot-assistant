"""Request a VNAppMob Gold API key and print it to stdout.

This script does not write to .env and does not enable automatic renewal.
Use it manually, then update VNAPPMOB_GOLD_API_KEY in .env yourself.
"""

from __future__ import annotations

import json
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REQUEST_URL = "https://api.vnappmob.com/api/request_api_key?scope=gold"
KEY_NAMES = {"api_key", "apikey", "key", "token", "access_token"}


def _find_key(payload: Any) -> str | None:
    if isinstance(payload, str):
        value = payload.strip()
        return value or None

    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.lower() in KEY_NAMES and isinstance(value, (str, int)):
                return str(value).strip()
        for value in payload.values():
            found = _find_key(value)
            if found:
                return found

    if isinstance(payload, list):
        for item in payload:
            found = _find_key(item)
            if found:
                return found

    return None


def main() -> int:
    request = Request(REQUEST_URL, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8").strip()
    except HTTPError as exc:
        print(f"Request failed: HTTP {exc.code}", file=sys.stderr)
        return 1
    except URLError as exc:
        print(f"Request failed: {exc.reason}", file=sys.stderr)
        return 1

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = body

    api_key = _find_key(payload)
    if not api_key:
        print("Không tìm thấy API key trong response.", file=sys.stderr)
        return 1

    print(api_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
