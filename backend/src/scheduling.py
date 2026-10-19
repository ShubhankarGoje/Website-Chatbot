"""Availability rules. Pure functions: no I/O, all datetimes timezone-aware."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config import Settings

Interval = tuple[datetime, datetime]


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime

    def describe(self, guest_tz: ZoneInfo, owner_tz: ZoneInfo) -> dict:
        local = self.start.astimezone(guest_tz)
        return {
            "start": local.isoformat(),
            "label": local.strftime("%a %b %-d, %-I:%M %p %Z"),
            "owner_local": self.start.astimezone(owner_tz).strftime("%-I:%M %p %Z"),
        }


def booking_window(now: datetime, settings: Settings) -> Interval:
    """Earliest and latest instants a meeting may start."""
    return (
        now + timedelta(hours=settings.min_notice_hours),
        now + timedelta(days=settings.max_days_ahead),
    )


def guest_date_range(start: date, end: date, guest_tz: ZoneInfo) -> Interval:
    """Whole days [start, end] in the guest's timezone, as aware datetimes."""
    return (
        datetime.combine(start, datetime.min.time(), guest_tz),
        datetime.combine(end + timedelta(days=1), datetime.min.time(), guest_tz),
    )


def _working_intervals(range_start: datetime, range_end: datetime, settings: Settings):
    """Yield the owner's working windows (in UTC) that touch [range_start, range_end)."""
    tz = settings.owner_tz
    day = range_start.astimezone(tz).date() - timedelta(days=1)
    last_day = range_end.astimezone(tz).date() + timedelta(days=1)
    while day <= last_day:
        for start_t, end_t in settings.working_hours.get(day.weekday(), []):
            start = datetime.combine(day, start_t, tz).astimezone(timezone.utc)
            end = datetime.combine(day, end_t, tz).astimezone(timezone.utc)
            if end > range_start and start < range_end:
                yield start, end
        day += timedelta(days=1)


def _conflicts(start: datetime, end: datetime, busy: list[Interval], buffer: timedelta) -> bool:
    return any(start < b_end + buffer and end > b_start - buffer for b_start, b_end in busy)


def available_slots(
    range_start: datetime,
    range_end: datetime,
    duration_minutes: int,
    busy: list[Interval],
    now: datetime,
    settings: Settings,
) -> list[Slot]:
    """Every bookable slot starting inside [range_start, range_end), on the slot grid."""
    earliest, latest = booking_window(now, settings)
    duration = timedelta(minutes=duration_minutes)
    step = timedelta(minutes=settings.slot_interval_minutes)
    buffer = timedelta(minutes=settings.buffer_minutes)

    slots = []
    for win_start, win_end in _working_intervals(range_start, range_end, settings):
        t = win_start
        while t + duration <= win_end:
            if (
                range_start <= t < range_end
                and earliest <= t <= latest
                and not _conflicts(t, t + duration, busy, buffer)
            ):
                slots.append(Slot(t, t + duration))
            t += step
    return slots


def check_bookable(
    start: datetime,
    duration_minutes: int,
    busy: list[Interval],
    now: datetime,
    settings: Settings,
) -> str | None:
    """Return None if the meeting can be booked, else a reason it can't."""
    if duration_minutes not in settings.meeting_durations:
        allowed = ", ".join(str(d) for d in settings.meeting_durations)
        return f"Meetings must be one of these lengths (minutes): {allowed}."
    end = start + timedelta(minutes=duration_minutes)
    earliest, latest = booking_window(now, settings)
    if start < earliest:
        return f"Meetings need at least {settings.min_notice_hours} hours' notice."
    if start > latest:
        return f"Meetings can be booked at most {settings.max_days_ahead} days ahead."
    in_hours = any(
        w_start <= start and end <= w_end
        for w_start, w_end in _working_intervals(start, end, settings)
    )
    if not in_hours:
        return f"That time is outside {settings.owner_name}'s working hours."
    if _conflicts(start, end, busy, timedelta(minutes=settings.buffer_minutes)):
        return "That time is no longer free."
    return None


def summarize_slots(slots: list[Slot], limit_per_day: int, guest_tz: ZoneInfo) -> list[Slot]:
    """Thin out long lists so each guest-local day contributes at most limit_per_day
    slots, spread across the day rather than just the earliest ones."""
    by_day: dict[date, list[Slot]] = {}
    for slot in slots:
        by_day.setdefault(slot.start.astimezone(guest_tz).date(), []).append(slot)
    picked = []
    for day_slots in by_day.values():
        if len(day_slots) <= limit_per_day:
            picked.extend(day_slots)
        else:
            stride = (len(day_slots) - 1) / (limit_per_day - 1) if limit_per_day > 1 else 0
            picked.extend(day_slots[round(i * stride)] for i in range(limit_per_day))
    return picked
