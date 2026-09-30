from datetime import datetime

from ..models import CST


def data(payload: object) -> dict:
    if (
        not isinstance(payload, dict)
        or type(payload.get("code")) is not int
        or payload["code"] != 0
    ):
        raise ValueError("official API returned an error or an unknown envelope")
    if "status" in payload and payload["status"] != 0:
        raise ValueError("official API returned an error status")
    value = payload.get("data")
    if not isinstance(value, dict):
        raise ValueError("official API data is not an object")
    return value


def items(payload: object) -> list[dict]:
    value = data(payload).get("list")
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("official API announcement list has an unknown shape")
    return value


def text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing or empty official field: {field}")
    return value


def identifier(value: object) -> str:
    value = text(value, "cid")
    if not value.isascii() or not value.isdigit():
        raise ValueError("invalid announcement identifier")
    return value


def epoch(value: object) -> datetime:
    if type(value) not in (int, float):
        raise ValueError("invalid official displayTime")
    return datetime.fromtimestamp(value, CST)
