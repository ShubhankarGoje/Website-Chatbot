"""Lambda entry point for POST /chat (API Gateway HTTP API, payload v2)."""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import anthropic

from agent import run_conversation
from config import Settings
from google_calendar import GoogleCalendar, load_credentials

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MAX_MESSAGES = 30
MAX_MESSAGE_CHARS = 2000

# Created on first use and reused across warm invocations.
_settings: Settings | None = None
_client = None
_calendar: GoogleCalendar | None = None


def _deps():
    global _settings, _client, _calendar
    if _settings is None:
        _settings = Settings.from_env()
    if _client is None:
        _client = anthropic.AnthropicBedrockMantle(aws_region=_settings.bedrock_region, timeout=25.0)
    if _calendar is None:
        _calendar = GoogleCalendar(load_credentials(_settings.google_secret_id))
    return _settings, _client, _calendar


class BadRequest(ValueError):
    pass


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def parse_request(event: dict, default_tz: str) -> tuple[list[dict], ZoneInfo]:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        raise BadRequest("Body must be JSON.")
    if not isinstance(body, dict):
        raise BadRequest("Body must be a JSON object.")

    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise BadRequest("messages must be a non-empty list.")
    if len(messages) > MAX_MESSAGES:
        raise BadRequest("This conversation is too long. Please refresh to start over.")

    history: list[dict] = []
    for m in messages:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant"):
            raise BadRequest("Each message needs a role of 'user' or 'assistant'.")
        content = m.get("content")
        if not isinstance(content, str) or not content.strip():
            raise BadRequest("Each message needs text content.")
        if len(content) > MAX_MESSAGE_CHARS:
            raise BadRequest(f"Messages are limited to {MAX_MESSAGE_CHARS} characters.")
        if not history and m["role"] == "assistant":
            continue  # the widget's greeting; Claude's history must start with the user
        if history and history[-1]["role"] == m["role"]:
            history[-1]["content"] += "\n\n" + content.strip()
        else:
            history.append({"role": m["role"], "content": content.strip()})
    if not history or history[-1]["role"] != "user":
        raise BadRequest("The last message must be from the user.")

    try:
        guest_tz = ZoneInfo(str(body.get("timezone") or default_tz))
    except (ZoneInfoNotFoundError, ValueError):
        guest_tz = ZoneInfo(default_tz)
    return history, guest_tz


def handler(event, context):
    try:
        settings, client, calendar = _deps()
        history, guest_tz = parse_request(event, settings.owner_timezone)
        result = run_conversation(
            client, calendar, settings, history, guest_tz, datetime.now(timezone.utc)
        )
        return _response(200, result)
    except BadRequest as e:
        return _response(400, {"error": str(e)})
    except anthropic.RateLimitError:
        logger.warning("Bedrock throttled the request")
        return _response(429, {"error": "Eeva is a little busy right now. Please try again in a minute."})
    except (anthropic.APIStatusError, anthropic.APIConnectionError):
        logger.exception("Bedrock call failed")
        return _response(502, {"error": "Eeva is unavailable right now. Please try again shortly."})
    except Exception:
        logger.exception("Unhandled error")
        return _response(500, {"error": "Something went wrong. Please try again shortly."})
