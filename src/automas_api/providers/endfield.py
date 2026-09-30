from datetime import datetime, timedelta
from urllib.parse import urlencode

from ..http import get_json
from ..parser import Announcement, is_candidate
from .common import data, epoch, identifier, items, text

API_ROOT = "https://web-news.hypergryph.com/api/bulletin"
PARAMS = {"lang": "zh-cn", "code": "endfield_web"}
LOOKBACK = timedelta(days=45)
MAX_PAGES = 10


def fetch(*, now: datetime, get=get_json) -> list[Announcement]:
    """Read recent official notices, respecting the server's actual page size."""
    notices = []
    seen = set()
    for page in range(1, MAX_PAGES + 1):
        query = urlencode({**PARAMS, "page": page, "pageSize": 20, "tabs[]": "notices"})
        payload = get(f"{API_ROOT}?{query}")
        rows = items(payload)
        meta = data(payload)
        if not rows:
            raise ValueError("Endfield returned an unexpected empty announcement page")
        if (
            meta.get("current") != page
            or type(meta.get("total")) is not int
            or type(meta.get("pageSize")) is not int
            or meta["pageSize"] <= 0
        ):
            raise ValueError("invalid Endfield pagination metadata")
        regular_dates = []
        fresh_ids = 0
        for row in rows:
            cid = identifier(row.get("cid"))
            published = epoch(row.get("displayTime"))
            if not row.get("sticky", False):
                regular_dates.append(published)
            if cid in seen:
                continue
            seen.add(cid)
            fresh_ids += 1
            title = text(row.get("title"), "title")
            if published < now - LOOKBACK or not is_candidate(title):
                continue
            detail = data(get(f"{API_ROOT}/{cid}?{urlencode(PARAMS)}"))
            if detail.get("cid") != cid:
                raise ValueError("Endfield detail ID differs from requested ID")
            notices.append(
                Announcement(
                    text(detail.get("title"), "title"),
                    text(detail.get("data"), "data"),
                    epoch(detail.get("displayTime")),
                    f"https://endfield.hypergryph.com/news/{cid}",
                )
            )
        if not fresh_ids:
            raise ValueError("Endfield pagination did not advance")
        if page * meta["pageSize"] >= meta["total"]:
            return notices
        if regular_dates and min(regular_dates) < now - LOOKBACK:
            return notices
    raise ValueError("Endfield pagination exceeded the limit; feed may be incomplete")
