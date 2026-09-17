from __future__ import annotations

import io
import json
import os
import unittest
from unittest.mock import patch

from api.index import handler
from reddit_opportunity_agent.web import demo_run, render_dashboard


def _invoke(method: str, path: str) -> tuple[int, dict[str, str], bytes]:
    instance = handler.__new__(handler)
    instance.path = path
    instance.wfile = io.BytesIO()
    result = {"status": 0, "headers": {}}
    instance.send_response = lambda status: result.__setitem__("status", status)
    instance.send_header = lambda key, value: result["headers"].__setitem__(key, value)
    instance.end_headers = lambda: None
    getattr(instance, "do_" + method)()
    return result["status"], result["headers"], instance.wfile.getvalue()


class WebTest(unittest.TestCase):
    def test_demo_page_is_explicitly_fictional_and_never_calls_external_services(self):
        with patch.dict(os.environ, {
            "REDDIT_APPROVAL_CONFIRMED": "true", "REDDIT_APPROVAL_REFERENCE": "test",
            "REDDIT_AI_PROCESSING_APPROVED": "true", "DEEPSEEK_API_KEY": "test",
        }), patch("reddit_opportunity_agent.reddit_client.fetch_new_posts") as reddit_call, \
             patch("reddit_opportunity_agent.ai.enrich_selected") as ai_call:
            html = render_dashboard(demo_run())
        self.assertIn("模拟演示 · 非实时 Reddit 数据", html)
        self.assertIn("P0 / P1 / P2", html)
        self.assertIn("no comment has been posted", html.lower())
        self.assertNotIn("href=\"https://www.reddit.com/r/Synthetic", html)
        reddit_call.assert_not_called()
        ai_call.assert_not_called()

    def test_public_renderer_rejects_real_reports_and_escapes_post_text(self):
        run = demo_run()
        run["source"] = "approved real Reddit data"
        with self.assertRaisesRegex(ValueError, "synthetic"):
            render_dashboard(run)
        run["source"] = "SYNTHETIC DEMO — no real Reddit data"
        run["opportunities"][0]["title"] = '<script>alert("x")</script>'
        page = render_dashboard(run)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn('<script>alert("x")</script>', page)

    def test_http_entrypoint_routes_and_denies_writes_or_local_files(self):
        status, headers, body = _invoke("GET", "/api")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("Synthetic Demo", body.decode())

        status, _, body = _invoke("GET", "/api?format=json")
        self.assertEqual(status, 200)
        self.assertIn("SYNTHETIC DEMO", json.loads(body)["source"])

        status, _, body = _invoke("GET", "/api?view=health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["mode"], "synthetic_only")

        status, _, body = _invoke("HEAD", "/api")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")

        for path in ("/.runs/secret", "/config.local.json", "/api/private"):
            status, _, _ = _invoke("GET", path)
            self.assertEqual(status, 404)

        status, headers, body = _invoke("POST", "/api")
        self.assertEqual(status, 405)
        self.assertEqual(headers["Allow"], "GET, HEAD")
        self.assertEqual(body, b"")


if __name__ == "__main__":
    unittest.main()
