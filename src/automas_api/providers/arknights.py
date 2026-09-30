from datetime import datetime

from ..http import get_json
from ..models import CST
from ..parser import Announcement, is_candidate
from .common import data, epoch, identifier, items, text

LIST_URL = "https://ak-webview.hypergryph.com/api/game/bulletinList?target=Android"
DETAIL_URL = "https://ak-webview.hypergryph.com/api/game/bulletin/"


def fetch(*, now: datetime, get=get_json) -> list[Announcement]:
    rows = items(get(LIST_URL))
    if not rows:
        raise ValueError("Arknights returned an empty announcement feed")
    notices = []
    for row in rows:
        title = text(row.get("title"), "title")
        if not is_candidate(title):
            continue
        cid = identifier(row.get("cid"))
        detail = data(get(DETAIL_URL + cid))
        if detail.get("cid") != cid:
            raise ValueError("Arknights detail ID differs from requested ID")
        published = datetime.strptime(text(detail.get("displayTime"), "displayTime"), "%Y-%m-%d")
        notices.append(
            Announcement(
                text(detail.get("header") or detail.get("title"), "title"),
                text(detail.get("content"), "content"),
                published.replace(tzinfo=CST),
                DETAIL_URL + cid,
                epoch(detail["updatedAt"]) if "updatedAt" in detail else None,
            )
        )
    return notices
