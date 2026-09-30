"""Reference client. A failure in the maintenance protection layer never blocks a task."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from .http import get_json
from .models import GAMES, Maintenance, aware, parse_timestamp, validate_status

# Allow the daily publishing interval plus one interval of scheduling slack.
DEFAULT_MAX_AGE = timedelta(hours=48)
FUTURE_SKEW = timedelta(minutes=5)


@dataclass(frozen=True)
class Decision:
    skip: bool
    reason: str
    maintenance: Maintenance | None = None


def evaluate_status(
    document: object,
    game: str,
    *,
    now: datetime | None = None,
    max_age: timedelta = DEFAULT_MAX_AGE,
) -> Decision:
    try:
        now = aware(now or datetime.now(UTC))
        if max_age <= timedelta(0):
            raise ValueError("max_age must be positive")
        if game not in GAMES:
            return Decision(False, "unknown_game")
        value = validate_status(document)
        age = now - parse_timestamp(value["generated_at"])
        if age > max_age:
            return Decision(False, "stale_status")
        if age < -FUTURE_SKEW:
            return Decision(False, "future_status")
        raw = value["games"][game]["maintenance"]
        if raw is None:
            return Decision(False, "no_maintenance")
        maintenance = Maintenance.from_dict(raw)
        if maintenance.start <= now < maintenance.end:
            return Decision(True, "maintenance", maintenance)
        return Decision(False, "outside_window", maintenance)
    except (ValueError, TypeError, KeyError, OverflowError):
        return Decision(False, "invalid_status")


def check_maintenance(
    url: str,
    game: str,
    *,
    now: datetime | None = None,
    timeout: float = 3.0,
    max_age: timedelta = DEFAULT_MAX_AGE,
    get=get_json,
) -> Decision:
    """Fetch on each task start. No stale-cache fallback and no network retries."""
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"https", "http"} or not parts.hostname:
            raise ValueError("status URL must be HTTP(S)")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        document = get(url, timeout=timeout)
    except Exception:
        # This boundary is deliberately fail-open, including malformed JSON,
        # HTTP/TLS errors and unexpected errors from an injected HTTP adapter.
        return Decision(False, "fetch_failed")
    return evaluate_status(document, game, now=now, max_age=max_age)
