import json
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from agent import SchedulingTools, run_conversation
from config import Settings, parse_working_hours
from google_calendar import CalendarError

LA = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 10, 19, 8, 0, tzinfo=LA).astimezone(timezone.utc)
SETTINGS = Settings(
    owner_timezone="America/Los_Angeles",
    working_hours=parse_working_hours("mon-fri 09:00-17:00"),
    meeting_durations=[30, 60],
    buffer_minutes=0,
)


class FakeCalendar:
    def __init__(self, busy=(), existing=0, fail=False):
        self.busy = list(busy)
        self.existing = existing
        self.fail = fail
        self.created = []

    def busy_intervals(self, start, end, calendar_ids):
        if self.fail:
            raise CalendarError("down")
        return self.busy

    def upcoming_bookings_for(self, calendar_id, email, now):
        return self.existing

    def create_meeting(self, **kwargs):
        self.created.append(kwargs)
        return {"id": "evt1", "meet_link": "https://meet.google.com/abc-defg-hij"}


def text(t):
    return SimpleNamespace(type="text", text=t)


def tool_use(id, name, input):
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


class FakeClaude:
    """Replays scripted responses and records each request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = self

    def create(self, **kwargs):
        self.requests.append(json.loads(json.dumps(kwargs, default=lambda o: vars(o))))
        content, stop = self.responses.pop(0)
        return SimpleNamespace(content=content, stop_reason=stop)


def tools(calendar=None):
    return SchedulingTools(calendar or FakeCalendar(), SETTINGS, LA, NOW)


def test_find_slots_returns_guest_local_times():
    result, is_error = tools().run(
        "find_available_slots", {"start_date": "2026-10-20", "end_date": "2026-10-20", "duration_minutes": 30}
    )
    assert not is_error
    assert result["slots"][0]["start"] == "2026-10-20T09:00:00-07:00"
    assert result["slots"][0]["label"] == "Tue Oct 20, 9:00 AM PDT"


def test_find_slots_outside_window_explains():
    result, is_error = tools().run(
        "find_available_slots", {"start_date": "2027-03-01", "end_date": "2027-03-02", "duration_minutes": 30}
    )
    assert not is_error and result["slots"] == [] and "Bookable window" in result["note"]


def test_bad_tool_input_is_reported_as_error():
    result, is_error = tools().run(
        "find_available_slots", {"start_date": "next tuesday", "end_date": "2026-10-20", "duration_minutes": 30}
    )
    assert is_error and "Invalid input" in result["error"]


def test_calendar_outage_is_reported_as_error():
    result, is_error = tools(FakeCalendar(fail=True)).run(
        "find_available_slots", {"start_date": "2026-10-20", "end_date": "2026-10-20", "duration_minutes": 30}
    )
    assert is_error and "unavailable" in result["error"]


BOOK = {
    "start": "2026-10-20T14:00:00-07:00",
    "duration_minutes": 30,
    "guest_name": "Ada Lovelace",
    "guest_email": "ada@example.com",
    "topic": "Chat about the UAV project",
}


def test_book_meeting_creates_event():
    cal = FakeCalendar()
    t = tools(cal)
    result, is_error = t.run("book_meeting", BOOK)
    assert not is_error and result["status"] == "booked"
    assert result["meet_link"].startswith("https://meet.google.com/")
    created = cal.created[0]
    assert created["guest_email"] == "ada@example.com"
    assert created["start"].isoformat() == "2026-10-20T14:00:00-07:00"
    assert created["end"].isoformat() == "2026-10-20T14:30:00-07:00"
    # Only one booking per request.
    result, is_error = t.run("book_meeting", BOOK)
    assert is_error and len(cal.created) == 1


def test_book_meeting_rejects_busy_time():
    busy = [(datetime(2026, 10, 20, 14, 0, tzinfo=LA), datetime(2026, 10, 20, 15, 0, tzinfo=LA))]
    cal = FakeCalendar(busy=busy)
    result, _ = tools(cal).run("book_meeting", BOOK)
    assert result["status"] == "not_booked" and not cal.created


def test_book_meeting_enforces_per_guest_cap():
    cal = FakeCalendar(existing=2)
    result, _ = tools(cal).run("book_meeting", BOOK)
    assert result["status"] == "not_booked" and "maximum" in result["reason"] and not cal.created


def test_book_meeting_validates_email():
    result, is_error = tools().run("book_meeting", {**BOOK, "guest_email": "not-an-email"})
    assert is_error and "email" in result["error"]


def test_conversation_runs_tools_then_replies():
    claude = FakeClaude(
        [
            ([text("Let me check."), tool_use("t1", "book_meeting", BOOK)], "tool_use"),
            ([text("Booked! Check your inbox.")], "end_turn"),
        ]
    )
    cal = FakeCalendar()
    out = run_conversation(claude, cal, SETTINGS, [{"role": "user", "content": "Yes, book it"}], LA, NOW)
    assert out["reply"] == "Booked! Check your inbox."
    assert out["booking"]["meet_link"]
    # Second request carries the assistant turn and the tool result, in order.
    second = claude.requests[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    tool_result = second[2]["content"][0]
    assert tool_result["tool_use_id"] == "t1" and not tool_result["is_error"]
    assert json.loads(tool_result["content"])["status"] == "booked"
    assert claude.requests[0]["output_config"] == {"effort": "low"}


def test_refusal_gets_friendly_reply():
    claude = FakeClaude([([], "refusal")])
    out = run_conversation(claude, FakeCalendar(), SETTINGS, [{"role": "user", "content": "hi"}], LA, NOW)
    assert "can't help" in out["reply"]
