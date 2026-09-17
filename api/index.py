"""Vercel's documented Python Function entrypoint; public synthetic demo only."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from reddit_opportunity_agent.report import render_community_rules_csv, render_feishu_csv
from reddit_opportunity_agent.web import demo_run, render_dashboard


class handler(BaseHTTPRequestHandler):
    def _respond(self, *, include_body: bool) -> None:
        parsed = urlsplit(self.path)
        attachment = None
        if parsed.path not in {"/", "/api", "/api/"}:
            status, content_type, payload = 404, "text/plain; charset=utf-8", b"Not found"
        else:
            query = parse_qs(parsed.query)
            if query.get("view") == ["health"]:
                status, content_type, payload = 200, "application/json; charset=utf-8", b'{"status":"ok","mode":"synthetic_only"}'
            else:
                run = demo_run()
                format_value = query.get("format", ["html"])
                if format_value == ["json"]:
                    status, content_type = 200, "application/json; charset=utf-8"
                    payload = json.dumps(run, ensure_ascii=False).encode("utf-8")
                elif format_value == ["feishu-csv"]:
                    status, content_type = 200, "text/csv; charset=utf-8"
                    payload = ("\ufeff" + render_feishu_csv(run)).encode("utf-8")
                    attachment = "ojo-feishu-review-demo.csv"
                elif format_value == ["rules-csv"]:
                    status, content_type = 200, "text/csv; charset=utf-8"
                    config_path = Path(__file__).resolve().parents[1] / "config.example.json"
                    config = json.loads(config_path.read_text(encoding="utf-8"))
                    payload = ("\ufeff" + render_community_rules_csv(config)).encode("utf-8")
                    attachment = "ojo-community-rules-template.csv"
                elif format_value == ["html"]:
                    status, content_type = 200, "text/html; charset=utf-8"
                    payload = render_dashboard(run).encode("utf-8")
                else:
                    status, content_type, payload = 400, "text/plain; charset=utf-8", b"Unsupported format"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
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
