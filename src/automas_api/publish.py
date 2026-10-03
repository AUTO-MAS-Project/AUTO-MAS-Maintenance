"""Publish maintain.json as a new version in the AUTO-MAS data center."""

import argparse
import json
import logging
import os
import secrets
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .http import MAX_BYTES, get_json
from .models import validate_status

DEFAULT_BASE_URL = "https://data.auto-mas.top"
log = logging.getLogger(__name__)


class PublishError(ValueError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # An upload credential must only reach the configured API endpoint.
        return None


def validate_target(base_url: str, public_url: str, file_id: int) -> str:
    base = urlsplit(base_url)
    public = urlsplit(public_url)
    if (
        base.scheme != "https"
        or not base.hostname
        or base.username
        or base.password
        or base.path not in {"", "/"}
        or base.query
        or base.fragment
    ):
        raise PublishError("AUTOMAS_BASE_URL must be an HTTPS origin")
    if (
        public.scheme != "https"
        or public.netloc != base.netloc
        or public.username
        or public.password
        or public.query
        or public.fragment
        or not public.path.startswith("/api/v1/files/")
        or not public.path.endswith("/download")
    ):
        raise PublishError("AUTOMAS_PUBLIC_URL must be the unversioned public download URL")
    if type(file_id) is not int or file_id < 1:
        raise PublishError("AUTOMAS_FILE_ID must be a positive integer")
    return base_url.rstrip("/")


def _upload(url: str, token: str, content: bytes, change_note: str) -> object:
    boundary = "automas-" + secrets.token_hex(24)
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="change_note"\r\n\r\n'
            f"{change_note}\r\n--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="maintain.json"\r\n'
            "Content-Type: application/json\r\n\r\n"
        ).encode()
        + content
        + f"\r\n--{boundary}--\r\n".encode()
    )
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "AUTOMAS_API/0.1",
        },
    )
    # No POST retry: an interrupted response may already have created a version.
    with build_opener(_NoRedirect()).open(request, timeout=30) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise PublishError("upload response exceeds size limit")
    return json.loads(raw.decode("utf-8-sig"))


def _matches(public_url: str, expected: dict, get) -> bool:
    try:
        return validate_status(get(public_url, timeout=10)) == expected
    except (OSError, ValueError, TypeError):
        return False


def publish(
    content: bytes,
    *,
    file_id: int,
    public_url: str,
    token: str,
    base_url: str = DEFAULT_BASE_URL,
    change_note: str = "AUTO-MAS maintenance policy",
    get=get_json,
    upload=_upload,
    sleep=time.sleep,
) -> dict:
    base_url = validate_target(base_url, public_url, file_id)
    if not token.strip() or "\r" in token or "\n" in token:
        raise PublishError("set the AUTOMAS_TOKEN Actions secret to a data-center Access Key")
    if len(content) > MAX_BYTES:
        raise PublishError("status document exceeds size limit")
    expected = validate_status(json.loads(content.decode("utf-8-sig")))
    if _matches(public_url, expected, get):
        return {"state": "unchanged", "public_url": public_url}

    version_no = None
    try:
        response = upload(
            f"{base_url}/api/v1/user/files/{file_id}/versions", token, content, change_note
        )
    except HTTPError as exc:
        if exc.code != 409:
            # Do not echo headers, tokens or an arbitrary upstream response body.
            raise PublishError(f"data-center upload failed (HTTP {exc.code})") from None
        # The API returns 409 for duplicate content, including pending versions.
        # Only an exact public read-back can make this a successful retry.
    else:
        if (
            not isinstance(response, dict)
            or type(response.get("code")) is not int
            or response["code"] != 0
            or not isinstance(response.get("data"), dict)
        ):
            raise PublishError("data center returned an invalid upload response")
        data = response["data"]
        if data.get("id") != file_id:
            raise PublishError("upload response has an unexpected file ID")
        keys = [data.get(key) for key in ("project_key", "category_key", "file_key")]
        if any(not isinstance(key, str) or not key for key in keys):
            raise PublishError("upload response is missing the public file location")
        actual_url = base_url + "/api/v1/files/" + "/".join(quote(k, safe="") for k in keys)
        if actual_url + "/download" != public_url:
            raise PublishError("AUTOMAS_PUBLIC_URL does not match the uploaded file")
        version = data.get("version")
        if not isinstance(version, dict):
            raise PublishError("upload response is missing version information")
        version_no = version.get("version_no")
        if (
            type(version_no) is not int
            or version_no < 1
            or version.get("review_status") != "approved"
            or data.get("published_version_no") != version_no
        ):
            raise PublishError(
                "version was uploaded but is not published; "
                "the current backend auto-publishes only uploads by an admin account"
            )

    # Check the same stable URL clients use, without a cache-busting query.
    # A CDN still serving an old version must not be reported as synchronized.
    for attempt in range(6):
        if _matches(public_url, expected, get):
            return {"state": "published", "version_no": version_no, "public_url": public_url}
        if attempt < 5:
            sleep(5)
    raise PublishError(
        "public download does not match maintain.json; check publication and CDN cache"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize maintain.json to data.auto-mas.top")
    parser.add_argument("--source", type=Path, default=Path("api/v1/maintain.json"))
    parser.add_argument(
        "--base-url", default=os.environ.get("AUTOMAS_BASE_URL") or DEFAULT_BASE_URL
    )
    parser.add_argument("--file-id", type=int, default=os.environ.get("AUTOMAS_FILE_ID") or None)
    parser.add_argument("--public-url", default=os.environ.get("AUTOMAS_PUBLIC_URL", ""))
    parser.add_argument("--change-note", default="AUTO-MAS maintenance policy")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        if args.file_id is None or not args.public_url:
            raise PublishError(
                "set the AUTOMAS_FILE_ID and AUTOMAS_PUBLIC_URL repository variables"
            )
        result = publish(
            args.source.read_bytes(),
            file_id=args.file_id,
            public_url=args.public_url,
            token=os.environ.get("AUTOMAS_TOKEN", ""),
            base_url=args.base_url,
            change_note=args.change_note,
        )
    except (OSError, ValueError, TypeError) as exc:
        # Exception text from socket/TLS implementations could contain request
        # information; only our own controlled errors are suitable for logs.
        detail = str(exc) if isinstance(exc, PublishError) else type(exc).__name__
        log.error("Synchronization failed: %s", detail)
        return 1
    log.info("Synchronization %s: %s", result["state"], result["public_url"])
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(f"\nData center: **{result['state']}** — {result['public_url']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
