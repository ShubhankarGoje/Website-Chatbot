"""Minimal Google Calendar REST client.

Authenticates as the calendar owner with an OAuth refresh token (created once by
scripts/google_auth.py and kept in AWS Secrets Manager). Uses only the standard
library so the Lambda package stays small.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"
GUEST_EMAIL_PROPERTY = "eevaGuestEmail"


class CalendarError(Exception):
    pass


def load_credentials(secret_id: str) -> dict:
    """{client_id, client_secret, refresh_token} from a local file (dev) or Secrets Manager."""
    local_file = os.environ.get("GOOGLE_CREDENTIALS_FILE")
    if local_file:
        with open(local_file) as f:
            return json.load(f)
    import boto3

    secret = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)
    return json.loads(secret["SecretString"])


def _rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class GoogleCalendar:
    def __init__(self, credentials: dict, timeout: float = 8.0):
        self._creds = credentials
        self._timeout = timeout
        self._access_token: str | None = None
        self._expires_at = 0.0

    def _token(self) -> str:
        if self._access_token and time.time() < self._expires_at - 60:
            return self._access_token
        body = urllib.parse.urlencode(
            {
                "client_id": self._creds["client_id"],
                "client_secret": self._creds["client_secret"],
                "refresh_token": self._creds["refresh_token"],
                "grant_type": "refresh_token",
            }
        ).encode()
        data = self._send(urllib.request.Request(TOKEN_URL, data=body, method="POST"))
        self._access_token = data["access_token"]
        self._expires_at = time.time() + int(data.get("expires_in", 3600))
        return self._access_token

    def _send(self, req: urllib.request.Request) -> dict:
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            logger.error("Google API %s %s failed: %s %s", req.method, req.full_url, e.code, detail)
            raise CalendarError(f"Google API returned {e.code}") from e
        except urllib.error.URLError as e:
            raise CalendarError(f"Could not reach Google: {e.reason}") from e

    def _api(self, method: str, path: str, query: dict | None = None, body: dict | None = None) -> dict:
        url = API + path + ("?" + urllib.parse.urlencode(query) if query else "")
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"},
        )
        return self._send(req)

    def busy_intervals(self, start: datetime, end: datetime, calendar_ids: list[str]):
        """Busy blocks across the given calendars. Only times are returned, never event details."""
        data = self._api(
            "POST",
            "/freeBusy",
            body={
                "timeMin": _rfc3339(start),
                "timeMax": _rfc3339(end),
                "items": [{"id": cid} for cid in calendar_ids],
            },
        )
        busy = []
        for cid, cal in data.get("calendars", {}).items():
            if cal.get("errors"):
                raise CalendarError(f"Free/busy lookup failed for calendar {cid}: {cal['errors']}")
            busy.extend((_parse(b["start"]), _parse(b["end"])) for b in cal.get("busy", []))
        return busy

    def upcoming_bookings_for(self, calendar_id: str, guest_email: str, now: datetime) -> int:
        """How many future meetings this guest has already booked through Eeva."""
        data = self._api(
            "GET",
            f"/calendars/{urllib.parse.quote(calendar_id)}/events",
            query={
                "privateExtendedProperty": f"{GUEST_EMAIL_PROPERTY}={guest_email.lower()}",
                "timeMin": _rfc3339(now),
                "singleEvents": "true",
                "maxResults": "50",
            },
        )
        return sum(1 for e in data.get("items", []) if e.get("status") != "cancelled")

    def create_meeting(
        self,
        calendar_id: str,
        start: datetime,
        end: datetime,
        summary: str,
        description: str,
        guest_name: str,
        guest_email: str,
        request_id: str,
    ) -> dict:
        """Create the event with a Google Meet link and email the guest an invite."""
        event = self._api(
            "POST",
            f"/calendars/{urllib.parse.quote(calendar_id)}/events",
            query={"conferenceDataVersion": "1", "sendUpdates": "all"},
            body={
                "summary": summary,
                "description": description,
                "start": {"dateTime": start.isoformat()},
                "end": {"dateTime": end.isoformat()},
                "attendees": [{"email": guest_email, "displayName": guest_name}],
                "conferenceData": {
                    "createRequest": {
                        "requestId": request_id,
                        "conferenceSolutionKey": {"type": "hangoutsMeet"},
                    }
                },
                "extendedProperties": {"private": {GUEST_EMAIL_PROPERTY: guest_email.lower()}},
                "reminders": {"useDefault": True},
            },
        )
        return {"id": event.get("id"), "meet_link": event.get("hangoutLink")}
