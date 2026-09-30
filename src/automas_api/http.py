"""Bounded, unauthenticated requests to public JSON endpoints."""

import gzip
import io
import json
from urllib.request import Request, urlopen

MAX_BYTES = 2 * 1024 * 1024


def get_json(url: str, *, timeout: float = 10.0) -> object:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "AUTOMAS_API/0.1",
            "Accept-Encoding": "gzip",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("response exceeds size limit")
        if response.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("decoded response exceeds size limit")
    return json.loads(raw.decode("utf-8-sig"))
