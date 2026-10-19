from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from config import Settings, parse_working_hours
from scheduling import available_slots, check_bookable, guest_date_range, summarize_slots

LA = ZoneInfo("America/Los_Angeles")
NY = ZoneInfo("America/New_York")


def settings(**overrides):
    base = dict(
        owner_timezone="America/Los_Angeles",
        working_hours=parse_working_hours("mon-fri 09:00-12:00,13:00-17:00"),
        meeting_durations=[30, 60],
        slot_interval_minutes=30,
        buffer_minutes=0,
        min_notice_hours=12,
        max_days_ahead=30,
    )
    base.update(overrides)
    return Settings(**base)


# Monday 2026-10-19 08:00 PDT
NOW = datetime(2026, 10, 19, 8, 0, tzinfo=LA).astimezone(timezone.utc)


def la(*args):
    return datetime(*args, tzinfo=LA)


def test_parse_working_hours():
    hours = parse_working_hours("mon-wed 09:00-17:00; sat 10:00-12:00,13:00-14:00")
    assert set(hours) == {0, 1, 2, 5}
    assert [str(s) for s, _ in hours[5]] == ["10:00:00", "13:00:00"]
    with pytest.raises(ValueError):
        parse_working_hours("funday 09:00-10:00")
    with pytest.raises(ValueError):
        parse_working_hours("mon 17:00-09:00")


def test_slots_respect_hours_lunch_and_notice():
    s = settings()
    start, end = guest_date_range(date(2026, 10, 19), date(2026, 10, 20), LA)
    slots = available_slots(start, end, 60, [], NOW, s)
    starts = [x.start.astimezone(LA).strftime("%a %H:%M") for x in slots]
    # Monday is entirely inside the 12h notice window (ends 20:00 Mon).
    assert not any(s.startswith("Mon") for s in starts)
    assert starts == ["Tue 09:00", "Tue 09:30", "Tue 10:00", "Tue 10:30", "Tue 11:00",
                      "Tue 13:00", "Tue 13:30", "Tue 14:00", "Tue 14:30",
                      "Tue 15:00", "Tue 15:30", "Tue 16:00"]


def test_busy_time_and_buffer_block_slots():
    s = settings(buffer_minutes=15)
    busy = [(la(2026, 10, 20, 10, 0), la(2026, 10, 20, 10, 30))]
    start, end = guest_date_range(date(2026, 10, 20), date(2026, 10, 20), LA)
    starts = [x.start.astimezone(LA).strftime("%H:%M") for x in available_slots(start, end, 30, busy, NOW, s)]
    # 09:30-10:00 ends inside the 15 min buffer; 10:30 starts inside it too.
    assert "09:00" in starts
    assert "09:30" not in starts and "10:00" not in starts and "10:30" not in starts
    assert "11:00" in starts


def test_weekend_has_no_slots():
    start, end = guest_date_range(date(2026, 10, 24), date(2026, 10, 25), LA)
    assert available_slots(start, end, 30, [], NOW, settings()) == []


def test_guest_timezone_day_boundaries():
    # Guest in New York asks for Tue 20 Oct: that is Tue 00:00-24:00 ET = Mon 21:00 - Tue 21:00 PT.
    start, end = guest_date_range(date(2026, 10, 20), date(2026, 10, 20), NY)
    slots = available_slots(start, end, 30, [], NOW, settings())
    assert slots[0].start.astimezone(NY).strftime("%H:%M") == "12:00"  # 09:00 PT
    assert all(x.start.astimezone(NY).date() == date(2026, 10, 20) for x in slots)


def test_dst_transition_keeps_wall_clock_hours():
    # US DST ends Sunday 2026-11-01; Monday 2026-11-02 09:00 PST is 17:00 UTC.
    s = settings(max_days_ahead=60)
    start, end = guest_date_range(date(2026, 11, 2), date(2026, 11, 2), LA)
    slots = available_slots(start, end, 30, [], NOW, s)
    assert slots[0].start.astimezone(LA).strftime("%H:%M") == "09:00"
    assert slots[0].start.astimezone(timezone.utc).hour == 17


def test_max_days_ahead():
    start, end = guest_date_range(date(2026, 12, 1), date(2026, 12, 2), LA)
    assert available_slots(start, end, 30, [], NOW, settings(max_days_ahead=30)) == []


def test_check_bookable():
    s = settings()
    ok = la(2026, 10, 20, 14, 0)
    assert check_bookable(ok, 30, [], NOW, s) is None
    assert "lengths" in check_bookable(ok, 45, [], NOW, s)
    assert "notice" in check_bookable(la(2026, 10, 19, 15, 0), 30, [], NOW, s)
    assert "working hours" in check_bookable(la(2026, 10, 20, 11, 30), 60, [], NOW, s)  # runs into lunch
    assert "working hours" in check_bookable(la(2026, 10, 24, 10, 0), 30, [], NOW, s)  # Saturday
    busy = [(la(2026, 10, 20, 14, 15), la(2026, 10, 20, 14, 45))]
    assert "no longer free" in check_bookable(ok, 30, busy, NOW, s)
    # Off-grid starts are fine as long as they fit.
    assert check_bookable(la(2026, 10, 20, 14, 10), 30, [], NOW, s) is None


def test_summarize_spreads_across_day():
    s = settings()
    start, end = guest_date_range(date(2026, 10, 20), date(2026, 10, 21), LA)
    slots = available_slots(start, end, 30, [], NOW, s)
    picked = summarize_slots(slots, 3, LA)
    tue = [x.start.astimezone(LA).strftime("%H:%M") for x in picked if x.start.astimezone(LA).day == 20]
    assert tue == ["09:00", "13:00", "16:30"]
    assert len(picked) == 6
