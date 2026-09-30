"""Small v1 wire format. All timestamps must include a UTC offset."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

CST = timezone(timedelta(hours=8))
GAMES = ("arknights", "endfield")
MAINTENANCE_TYPES = ("version_update", "hotfix", "emergency", "extension")
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


def parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not STAMP.fullmatch(value):
        raise ValueError("expected an RFC 3339 timestamp with a timezone")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("timestamp has no timezone")
    return result


def aware(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("now must include a timezone")
    return value


def timestamp(value: datetime) -> str:
    return aware(value).astimezone(CST).isoformat(timespec="seconds")


def source_url(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("source_url must be a URL")
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("source_url must be an absolute HTTPS URL")
    return value


@dataclass(frozen=True)
class Maintenance:
    start: datetime
    end: datetime
    kind: str
    url: str
    override: bool = False

    def __post_init__(self):
        if aware(self.start) >= aware(self.end):
            raise ValueError("maintenance start must precede end")
        if self.kind not in MAINTENANCE_TYPES:
            raise ValueError("unknown maintenance type")
        source_url(self.url)
        if type(self.override) is not bool:
            raise ValueError("override must be boolean")

    def to_dict(self) -> dict:
        return {
            "planned_start_at": timestamp(self.start),
            "planned_end_at": timestamp(self.end),
            "type": self.kind,
            "source_url": self.url,
            "override": self.override,
        }

    @classmethod
    def from_dict(cls, value: object) -> "Maintenance":
        fields = {"planned_start_at", "planned_end_at", "type", "source_url", "override"}
        if not isinstance(value, dict) or set(value) != fields:
            raise ValueError("invalid maintenance fields")
        return cls(
            parse_timestamp(value["planned_start_at"]),
            parse_timestamp(value["planned_end_at"]),
            value["type"],
            value["source_url"],
            value["override"],
        )


def validate_status(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"schema_version", "generated_at", "games"}:
        raise ValueError("invalid status document")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("unsupported schema_version")
    parse_timestamp(value["generated_at"])
    if not isinstance(value["games"], dict) or set(value["games"]) != set(GAMES):
        raise ValueError("invalid games")
    for game in value["games"].values():
        if not isinstance(game, dict) or set(game) != {"maintenance"}:
            raise ValueError("invalid game state")
        if game["maintenance"] is not None:
            Maintenance.from_dict(game["maintenance"])
    return value
