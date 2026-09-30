"""Conservative parsing of Chinese mainland maintenance announcements.

Uncertain maintenance notices raise ParseError; callers publish fail-open state
and surface the error for an operator to supply an override.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from html.parser import HTMLParser

from .models import CST, Maintenance, aware


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class Announcement:
    title: str
    content: str
    published_at: datetime
    url: str
    updated_at: datetime | None = None


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    text = unicodedata.normalize("NFKC", "".join(parser.parts)).replace("\\n", "\n")
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def is_candidate(title: str) -> bool:
    return bool(
        re.search(r"维护|停机|停服|闪断|版本.*更新|更新预告|提前开服|恢复登录|开服时间", title)
    )


DATE = r"(?:(?:\d{4})\s*[年/.-]\s*)?\d{1,2}\s*[月/.-]\s*\d{1,2}\s*日?"
CLOCK = r"\d{1,2}:\d{2}(?::\d{2})?"
RANGE = re.compile(
    rf"(?P<start_date>{DATE})\s*(?P<start_time>{CLOCK})\s*"
    rf"(?:[-~～—–至到])+\s*(?:(?P<end_date>{DATE})\s*)?(?P<end_time>{CLOCK})"
)
END = re.compile(
    rf"(?:延长至|延迟至|延期至|推迟至|提前至|预计(?:将)?于|已于|将于)\s*"
    rf"(?:(?P<date>{DATE})\s*)?(?P<time>{CLOCK})"
)
AMENDMENT = re.compile(r"延长|延期|延迟|推迟|提前开服|维护结束|恢复登录|开服时间调整")
CONTEXT = re.compile(r"停机|停服|闪断|维护时间|更新维护|临时维护|紧急维护|服务器.{0,12}维护")
HEADER = re.compile(r"(?:维护|停机|停服|闪断|更新)(?:更新|维护)?时间\s*[:：]?$")


def _date(value: str, anchor: datetime) -> datetime:
    parts = [int(x) for x in re.findall(r"\d+", value)]
    if len(parts) == 3:
        return datetime(*parts, tzinfo=CST)
    # An omitted year is anchored to the publication date, never the polling year.
    choices = []
    for year in (anchor.year - 1, anchor.year, anchor.year + 1):
        try:
            choices.append(datetime(year, *parts, tzinfo=CST))
        except ValueError:
            continue
    if not choices:
        raise ParseError("invalid month/day")
    return min(choices, key=lambda d: abs(d - anchor))


def _time(day: datetime, value: str) -> datetime:
    parts = [int(x) for x in value.split(":")]
    return day.replace(hour=parts[0], minute=parts[1], second=parts[2] if len(parts) > 2 else 0)


def _range(match: re.Match, published: datetime) -> tuple[datetime, datetime]:
    start = _time(_date(match["start_date"], published), match["start_time"])
    end_day = _date(match["end_date"], start) if match["end_date"] else start
    end = _time(end_day, match["end_time"])
    if not match["end_date"] and end < start:
        end += timedelta(days=1)
    if not timedelta(0) < end - start <= timedelta(hours=48):
        raise ParseError("automatic maintenance interval must be between 0 and 48 hours")
    return start, end


def _maintenance_ranges(text: str, title: str, published: datetime):
    lines = text.splitlines()
    found = set()
    for index, line in enumerate(lines):
        previous = lines[index - 1] if index else ""
        has_context = CONTEXT.search(line) or (HEADER.search(previous) and is_candidate(title))
        if not has_context:
            continue
        # These paragraphs contain reward/event windows, not server downtime.
        if re.search(r"补偿范围|发放时间|领取时间|活动时间|兑换时间", line + previous):
            continue
        for match in RANGE.finditer(line):
            found.add(_range(match, published))
    return found


def detect(
    announcements: list[Announcement], now: datetime, *, opened_at: datetime | None = None
) -> Maintenance | None:
    """Apply notices chronologically, then expose an active or earliest future window."""
    aware(now)
    if opened_at is not None and aware(opened_at) > now:
        raise ValueError("opened_at cannot be in the future")
    windows: list[Maintenance] = []
    ordered = sorted(
        announcements,
        key=lambda item: (
            item.updated_at or item.published_at,
            bool(AMENDMENT.search(item.title)),
            item.url,
        ),
    )
    for notice in ordered:
        if not is_candidate(notice.title):
            continue
        text = plain_text(notice.content)
        title = plain_text(notice.title)
        published = aware(notice.published_at).astimezone(CST)
        try:
            # Non-disruptive hot updates do not constitute maintenance.
            if re.search(r"不停服|无需停服|不影响.{0,8}(?:登录|正常游戏)", text):
                disruptive_text = re.sub(r"不停服|无需停服", "", text)
                if not CONTEXT.search(disruptive_text):
                    continue
            spans = _maintenance_ranges(text, title, published)
            amendment = AMENDMENT.search(title)
            if amendment:
                ends = list(END.finditer(text))
                if ends:
                    values = {
                        _time(
                            _date(m["date"], published) if m["date"] else published, m["time"]
                        ).replace(microsecond=0)
                        for m in ends
                    }
                    if len(values) != 1:
                        raise ParseError("ambiguous revised opening time")
                    end = values.pop()
                    bases = [
                        w
                        for w in windows
                        if timedelta(0) < end - w.start <= timedelta(hours=48)
                        and abs((published.date() - w.end.date()).days) <= 1
                    ]
                    if len(bases) != 1:
                        raise ParseError("cannot uniquely associate amendment with maintenance")
                    base = bases[0]
                    windows.remove(base)
                    windows.append(Maintenance(base.start, end, "extension", notice.url))
                    continue
                if not spans:
                    raise ParseError("amendment has no explicit opening time")
            if not spans:
                if CONTEXT.search(text) or re.search(r"维护|停机|停服|闪断", title):
                    raise ParseError("maintenance notice has no unambiguous time interval")
                continue
            if len(spans) != 1:
                raise ParseError("maintenance notice contains conflicting time intervals")
            start, end = spans.pop()
            kind = (
                "extension"
                if amendment
                else (
                    "hotfix"
                    if "闪断" in title + text
                    else ("emergency" if re.search(r"临时|紧急", title) else "version_update")
                )
            )
            # Later notices for the same start supersede pre-announcements.
            windows = [w for w in windows if w.start != start]
            windows.append(Maintenance(start, end, kind, notice.url))
        except ValueError as exc:
            raise ParseError(f"{notice.url}: {exc}") from exc
    relevant = sorted(
        (w for w in windows if w.end > now and (opened_at is None or w.start > opened_at)),
        key=lambda w: w.start,
    )
    if not relevant:
        return None
    selected = relevant[0]
    # Fold touching/overlapping windows so the minimal single-window protocol
    # cannot resume tasks in the middle of a second known maintenance.
    for window in relevant[1:]:
        if window.start > selected.end:
            break
        if window.end > selected.end:
            selected = Maintenance(selected.start, window.end, window.kind, window.url)
    return selected
