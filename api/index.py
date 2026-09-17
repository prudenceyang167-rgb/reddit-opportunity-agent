"""Vercel's documented Python Function entrypoint; public synthetic demo only."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

from reddit_opportunity_agent.web import demo_run, render_dashboard


class handler(BaseHTTPRequestHandler):
    def _respond(self, *, include_body: bool) -> None:
        parsed = urlsplit(self.path)
        if parsed.path not in {"/", "/api", "/api/"}:
            status, content_type, payload = 404, "text/plain; charset=utf-8", b"Not found"
        else:
            query = parse_qs(parsed.query)
            if query.get("view") == ["health"]:
                status, content_type, payload = 200, "application/json; charset=utf-8", b'{"status":"ok","mode":"synthetic_only"}'
            else:
                run = demo_run()
                if query.get("format") == ["json"]:
                    status, content_type = 200, "application/json; charset=utf-8"
                    payload = json.dumps(run, ensure_ascii=False).encode("utf-8")
                else:
                    status, content_type = 200, "text/html; charset=utf-8"
                    payload = render_dashboard(run).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        self.end_headers()
        if include_body:
            self.wfile.write(payload)

    def do_GET(self) -> None:
        self._respond(include_body=True)

    def do_HEAD(self) -> None:
        self._respond(include_body=False)

    def do_POST(self) -> None:
        self.send_response(405)
        self.send_header("Allow", "GET, HEAD")
        self.send_header("Content-Length", "0")
        self.end_headers()
