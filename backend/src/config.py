"""Runtime settings, read once from Lambda environment variables."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import time
from zoneinfo import ZoneInfo

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# Window = (start, end) wall-clock times in the owner's timezone.
Window = tuple[time, time]


def parse_working_hours(spec: str) -> dict[int, list[Window]]:
    """Parse e.g. "mon-fri 09:00-12:00,13:00-17:00; sat 10:00-12:00".

    Returns {weekday (0=Mon): [(start, end), ...]}.
    """
    hours: dict[int, list[Window]] = {}
    for rule in filter(None, (r.strip() for r in spec.split(";"))):
        m = re.fullmatch(r"([a-z]{3})(?:-([a-z]{3}))?\s+(.+)", rule.lower())
        if not m:
            raise ValueError(f"Bad working-hours rule: {rule!r}")
        first, last, windows = m.group(1), m.group(2) or m.group(1), m.group(3)
        if first not in WEEKDAYS or last not in WEEKDAYS:
            raise ValueError(f"Bad weekday in rule: {rule!r}")
        days = range(WEEKDAYS.index(first), WEEKDAYS.index(last) + 1)
        for window in windows.split(","):
            start_s, end_s = (part.strip() for part in window.split("-"))
            start, end = time.fromisoformat(start_s), time.fromisoformat(end_s)
            if start >= end:
                raise ValueError(f"Window must end after it starts: {window!r}")
            for day in days:
                hours.setdefault(day, []).append((start, end))
    for windows in hours.values():
        windows.sort()
    return hours


def _int_list(value: str) -> list[int]:
    return [int(v) for v in value.split(",") if v.strip()]


def _str_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    owner_name: str = "Shubhankar"
    owner_timezone: str = "America/Los_Angeles"
    working_hours: dict[int, list[Window]] = field(
        default_factory=lambda: parse_working_hours("mon-fri 09:00-17:00")
    )
    meeting_durations: list[int] = field(default_factory=lambda: [15, 30, 60])
    slot_interval_minutes: int = 30
    buffer_minutes: int = 10
    min_notice_hours: int = 12
    max_days_ahead: int = 30
    # Calendars whose busy time blocks availability; bookings land on the first.
    calendar_ids: list[str] = field(default_factory=lambda: ["primary"])
    max_upcoming_bookings_per_guest: int = 2
    model_id: str = "anthropic.claude-haiku-5-5"
    effort: str = "low"
    bedrock_region: str = "us-west-2"
    google_secret_id: str = "eeva/google-calendar"

    @property
    def owner_tz(self) -> ZoneInfo:
        return ZoneInfo(self.owner_timezone)

    @property
    def booking_calendar_id(self) -> str:
        return self.calendar_ids[0]

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)
        defaults = cls()
        settings = cls(
            owner_name=env.get("OWNER_NAME", defaults.owner_name),
            owner_timezone=env.get("OWNER_TIMEZONE", defaults.owner_timezone),
            working_hours=(
                parse_working_hours(env["WORKING_HOURS"])
                if env.get("WORKING_HOURS")
                else defaults.working_hours
            ),
            meeting_durations=_int_list(env.get("MEETING_DURATIONS", "15,30,60")),
            slot_interval_minutes=int(env.get("SLOT_INTERVAL_MINUTES", "30")),
            buffer_minutes=int(env.get("BUFFER_MINUTES", "10")),
            min_notice_hours=int(env.get("MIN_NOTICE_HOURS", "12")),
            max_days_ahead=int(env.get("MAX_DAYS_AHEAD", "30")),
            calendar_ids=_str_list(env.get("CALENDAR_IDS", "primary")),
            max_upcoming_bookings_per_guest=int(env.get("MAX_BOOKINGS_PER_GUEST", "2")),
            model_id=env.get("MODEL_ID", defaults.model_id),
            effort=env.get("MODEL_EFFORT", defaults.effort),
            bedrock_region=env.get("BEDROCK_REGION")
            or env.get("AWS_REGION", defaults.bedrock_region),
            google_secret_id=env.get("GOOGLE_SECRET_ID", defaults.google_secret_id),
        )
        settings.owner_tz  # fail fast on an unknown timezone
        if not settings.meeting_durations or not settings.calendar_ids:
            raise ValueError("MEETING_DURATIONS and CALENDAR_IDS must not be empty")
        return settings
