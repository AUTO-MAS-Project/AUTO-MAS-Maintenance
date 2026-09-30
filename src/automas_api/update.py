import argparse
import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from .models import GAMES, timestamp, validate_status
from .overrides import OpenedOverride, mark_opened, merge, parse_overrides
from .parser import detect
from .providers import PROVIDERS

log = logging.getLogger(__name__)


def build_status(override_document: object, *, now: datetime, providers=None) -> tuple[dict, dict]:
    # Validate every override before polling or replacing any public file.
    overrides = parse_overrides(override_document)
    providers = PROVIDERS if providers is None else providers
    games = {}
    report = {"generated_at": timestamp(now), "errors": {}, "detected": {}, "overrides": {}}
    for game in GAMES:
        override = overrides.get(game)
        opened_at = override.opened_at if isinstance(override, OpenedOverride) else None
        if opened_at is not None and opened_at > now:
            raise ValueError(f"{game}: opened_at cannot be in the future")
        detected = None
        try:
            detected = detect(providers[game](now=now), now, opened_at=opened_at)
        except Exception as exc:
            # Never reuse old maintenance under a fresh generated_at timestamp.
            report["errors"][game] = f"{type(exc).__name__}: {exc}"
            log.error("%s: %s", game, report["errors"][game])
        report["detected"][game] = detected.to_dict() if detected else None
        if isinstance(override, OpenedOverride):
            report["overrides"][game] = {"state": "opened", "opened_at": timestamp(opened_at)}
        elif override:
            report["overrides"][game] = "active" if now < override.expires_at else "expired"
        final = merge(detected, override, now)
        games[game] = {"maintenance": final.to_dict() if final else None}
    status = {"schema_version": 1, "generated_at": timestamp(now), "games": games}
    return validate_status(status), report


def write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the AUTO-MAS maintenance policy")
    parser.add_argument("--overrides", type=Path, default=Path("config/overrides.json"))
    parser.add_argument("--output", type=Path, default=Path("api/v1/status.json"))
    parser.add_argument("--report", type=Path, default=Path("poll-report.json"))
    parser.add_argument(
        "--mark-opened",
        choices=GAMES,
        help="mark the selected game as opened now and persist the event to overrides",
    )
    parser.add_argument(
        "--allow-source-failures",
        action="store_true",
        help="exit 0 after publishing fail-open state; errors remain in the report",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        overrides = json.loads(args.overrides.read_text(encoding="utf-8"))
        now = datetime.now(UTC)
        if args.mark_opened:
            overrides = mark_opened(overrides, args.mark_opened, now)
        status, report = build_status(overrides, now=now)
        write_json(args.output, status)
        write_json(args.report, report)
        if args.mark_opened:
            write_json(args.overrides, overrides)
    except (OSError, ValueError, TypeError) as exc:
        log.error("Update failed: %s", exc)
        return 2
    log.info("Wrote %s; %d source error(s)", args.output, len(report["errors"]))
    return int(bool(report["errors"]) and not args.allow_source_failures)


if __name__ == "__main__":
    raise SystemExit(main())
