from datetime import timedelta

from automas_api.client import evaluate_status
from automas_api.models import parse_timestamp
from automas_api.overrides import mark_opened
from automas_api.parser import Announcement
from automas_api.update import build_status

NOW = parse_timestamp("2026-10-03T14:00:00+08:00")
OLD = Announcement(
    title="停机维护公告",
    content="维护时间：2026年10月3日10:00 - 16:00",
    published_at=NOW - timedelta(days=1),
    url="https://ak.hypergryph.com/news/1",
)
NEW = Announcement(
    title="停机维护公告",
    content="维护时间：2026年10月4日10:00 - 16:00",
    published_at=NOW,
    url="https://ak.hypergryph.com/news/2",
)


def providers(*announcements):
    return {
        "arknights": lambda **kwargs: announcements,
        "endfield": lambda **kwargs: [OLD],
    }


def test_early_opening_immediately_releases_client_and_keeps_other_game():
    overrides = {"schema_version": 1, "games": {}}
    before, _ = build_status(overrides, now=NOW, providers=providers(OLD))
    assert evaluate_status(before, "arknights", now=NOW).skip
    opened = mark_opened(overrides, "arknights", NOW)
    after, report = build_status(opened, now=NOW, providers=providers(OLD))
    assert not evaluate_status(after, "arknights", now=NOW).skip
    assert after["games"]["arknights"]["maintenance"] is None
    assert after["games"]["endfield"] == before["games"]["endfield"]
    assert report["errors"] == {}


def test_next_poll_does_not_restore_old_maintenance():
    opened = mark_opened({"schema_version": 1, "games": {}}, "arknights", NOW)
    status, _ = build_status(opened, now=NOW + timedelta(hours=1), providers=providers(OLD))
    assert status["games"]["arknights"]["maintenance"] is None


def test_opening_does_not_suppress_next_maintenance():
    opened = mark_opened({"schema_version": 1, "games": {}}, "arknights", NOW)
    later = NOW + timedelta(hours=21)
    status, _ = build_status(opened, now=later, providers=providers(OLD, NEW))
    assert evaluate_status(status, "arknights", now=later).skip
    assert status["games"]["arknights"]["maintenance"]["source_url"] == NEW.url


def test_opening_preserves_other_games_opening_record():
    overrides = {
        "schema_version": 1,
        "games": {"endfield": {"opened_at": "2026-10-03T12:00:00+08:00"}},
    }
    opened = mark_opened(overrides, "arknights", NOW)
    assert opened["games"]["endfield"] == overrides["games"]["endfield"]
    assert "arknights" not in overrides["games"]
