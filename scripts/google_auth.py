#!/usr/bin/env python3
"""One-time setup: authorize Eeva to use your Google Calendar.

Runs Google's OAuth flow for installed apps in your browser, then stores
{client_id, client_secret, refresh_token} in AWS Secrets Manager so the Lambda
can check free/busy and create meetings as you.

Usage:
    python scripts/google_auth.py --client-secrets client_secret.json
    python scripts/google_auth.py --client-secrets client_secret.json --out google-credentials.json

Needs only the standard library, plus boto3 when storing to Secrets Manager.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = [
    "https://www.googleapis.com/auth/calendar.freebusy",  # read busy times (never event details)
    "https://www.googleapis.com/auth/calendar.events",  # create meetings and send invites
]


def wait_for_code(expected_state: str) -> tuple[str, int, http.server.HTTPServer]:
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if "code" not in params and "error" not in params:
                self.send_response(404)
                self.end_headers()
                return
            result.update(params)
            ok = params.get("state") == expected_state and "code" in params
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<h2>Eeva is connected to your calendar. You can close this tab.</h2>"
                if ok
                else b"<h2>Authorization failed. Check the terminal.</h2>"
            )

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    return result, server.server_address[1], server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--client-secrets", required=True, help="OAuth client JSON downloaded from Google Cloud (Desktop app type)")
    parser.add_argument("--secret-name", default="eeva/google-calendar", help="Secrets Manager secret to create/update")
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--out", help="Write credentials to this local file instead of Secrets Manager (for local testing)")
    args = parser.parse_args()

    with open(args.client_secrets) as f:
        client = json.load(f)
    client = client.get("installed") or client.get("web") or client
    client_id, client_secret = client["client_id"], client["client_secret"]

    state = secrets.token_urlsafe(16)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()

    result, port, server = wait_for_code(state)
    redirect_uri = f"http://127.0.0.1:{port}/"
    url = AUTH_URL + "?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",  # always return a refresh token
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    print("Opening your browser to authorize Google Calendar access.")
    print(f"If it doesn't open, visit:\n\n{url}\n")
    webbrowser.open(url)
    while "code" not in result and "error" not in result:
        server.handle_request()
    server.server_close()

    if result.get("state") != state or "code" not in result:
        sys.exit(f"Authorization failed: {result.get('error', 'state mismatch')}")

    body = urllib.parse.urlencode(
        {
            "code": result["code"],
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        }
    ).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body, method="POST")) as resp:
        tokens = json.load(resp)
    if "refresh_token" not in tokens:
        sys.exit("Google did not return a refresh token. Remove Eeva's access at "
                 "https://myaccount.google.com/permissions and run this again.")

    creds = {"client_id": client_id, "client_secret": client_secret, "refresh_token": tokens["refresh_token"]}

    if args.out:
        with open(args.out, "w") as f:
            json.dump(creds, f)
        print(f"Saved credentials to {args.out}. Keep this file private; do not commit it.")
        return

    import boto3

    sm = boto3.client("secretsmanager", region_name=args.region)
    value = json.dumps(creds)
    try:
        sm.put_secret_value(SecretId=args.secret_name, SecretString=value)
        print(f"Updated secret {args.secret_name} in {args.region}.")
    except sm.exceptions.ResourceNotFoundException:
        sm.create_secret(Name=args.secret_name, SecretString=value,
                         Description="Google Calendar OAuth credentials for the Eeva scheduler")
        print(f"Created secret {args.secret_name} in {args.region}.")


if __name__ == "__main__":
    main()
