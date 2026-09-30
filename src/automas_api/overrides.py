from dataclasses import dataclass, replace
from datetime import datetime

from .models import GAMES, Maintenance, aware, parse_timestamp, timestamp


@dataclass(frozen=True)
class Override:
    maintenance: Maintenance | None
    expires_at: datetime
    reason: str


@dataclass(frozen=True)
class OpenedOverride:
    opened_at: datetime


def parse_overrides(document: object) -> dict[str, Override | OpenedOverride]:
    if not isinstance(document, dict) or set(document) != {"schema_version", "games"}:
        raise ValueError("invalid override document")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValueError("unsupported override schema_version")
    games = document["games"]
    if not isinstance(games, dict) or set(games) - set(GAMES):
        raise ValueError("unknown game in overrides")
    result = {}
    for game, value in games.items():
        if isinstance(value, dict) and set(value) == {"opened_at"}:
            result[game] = OpenedOverride(parse_timestamp(value["opened_at"]))
            continue
        if not isinstance(value, dict) or set(value) != {"maintenance", "expires_at", "reason"}:
            raise ValueError(f"{game}: expected opened_at or maintenance, expires_at and reason")
        expires = parse_timestamp(value["expires_at"])
        if not isinstance(value["reason"], str) or not value["reason"].strip():
            raise ValueError(f"{game}: override reason cannot be empty")
        maintenance = value["maintenance"]
        if maintenance is not None:
            if not isinstance(maintenance, dict) or "override" in maintenance:
                raise ValueError(f"{game}: override flag is generated, do not set it in config")
            maintenance = Maintenance.from_dict({**maintenance, "override": True})
            if expires <= maintenance.start:
                raise ValueError(f"{game}: override expires before maintenance starts")
        result[game] = Override(maintenance, expires, value["reason"])
    return result


def mark_opened(document: object, game: str, now: datetime) -> dict:
    """Persist an opening event without suppressing subsequently starting maintenance."""
    parse_overrides(document)
    if game not in GAMES:
        raise ValueError(f"unknown game: {game}")
    return {
        "schema_version": 1,
        "games": {**document["games"], game: {"opened_at": timestamp(now)}},
    }


def merge(
    detected: Maintenance | None, override: Override | OpenedOverride | None, now: datetime
) -> Maintenance | None:
    if isinstance(override, OpenedOverride):
        if override.opened_at > aware(now):
            raise ValueError("opened_at cannot be in the future")
        if detected is not None and detected.start <= override.opened_at:
            return None
        return detected
    if override is None or now >= override.expires_at:
        return detected
    if override.maintenance is None:
        return None
    # Also cap the public interval: a cached document must not enforce an
    # override after it expires if CI stops between polls.
    maintenance = override.maintenance
    end = min(maintenance.end, override.expires_at)
    if end <= now:
        return None
    return replace(maintenance, end=end, override=True)
