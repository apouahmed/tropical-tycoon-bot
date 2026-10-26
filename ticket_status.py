"""Ticket channel names and close-request deadlines. No Discord calls."""

from __future__ import annotations

import re

NAME_LIMIT = 100
HOURS_MIN = 1
HOURS_MAX = 168

RESOLVED_NAME = "🟢-resolved"
HIGHER_NAME = "🔴-higher-up-needed"
BUG_NAME = "🟣-bug-report"

_NON_SLUG = re.compile(r"[^a-z0-9]+")


class TicketStatusError(ValueError):
    pass


def slug(display: str) -> str:
    text = _NON_SLUG.sub("-", (display or "").lower()).strip("-")
    return text or "staff"


def claimed_channel_name(display: str) -> str:
    """🟡- plus the claimer's name, within Discord's 100-character channel limit."""
    prefix = "🟡-"
    room = NAME_LIMIT - len(prefix)
    body = slug(display)[:room].strip("-")
    return prefix + (body or "staff")


def close_deadline(hours: int, now: float) -> int:
    if isinstance(hours, bool) or not isinstance(hours, int):
        raise TicketStatusError(f"Hours must be a whole number from {HOURS_MIN} to {HOURS_MAX}.")
    if hours < HOURS_MIN or hours > HOURS_MAX:
        raise TicketStatusError(f"Hours must be a whole number from {HOURS_MIN} to {HOURS_MAX}.")
    return int(now) + hours * 3600


def seconds_until(deadline: int, now: float) -> float:
    return max(0.0, float(deadline) - float(now))


def transcript_filename(channel_name: str, number: str) -> str:
    body = slug(channel_name)
    if str(number).isdigit():
        return f"ticket-{number}-{body}.txt"
    return f"{body}.txt"
