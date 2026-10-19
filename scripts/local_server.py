#!/usr/bin/env python3
"""Run Eeva locally: serves the widget demo page and the /chat endpoint.

Uses your real AWS credentials (for Bedrock) and Google credentials, so a booking
made here is a real booking.

    pip install -r backend/requirements-dev.txt
    GOOGLE_CREDENTIALS_FILE=google-credentials.json python scripts/local_server.py
    open http://127.0.0.1:8787
"""

from __future__ import annotations

import http.server
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

import app  # noqa: E402


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "frontend"), **kwargs)

    def do_POST(self):
        if self.path != "/chat":
            self.send_error(404)
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
        result = app.handler({"body": body, "isBase64Encoded": False}, None)
        payload = result["body"].encode()
        self.send_response(result["statusCode"])
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8787"))
    print(f"Eeva running at http://127.0.0.1:{port}  (demo page uses api-url=/chat)")
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
