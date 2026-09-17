"""Tests for safe, human-reviewable report exports."""

import csv
import io
import unittest

from reddit_opportunity_agent.report import render_csv, render_markdown


def sample_run():
    return {
        "generated_at": "2026-09-17T08:00:00Z",
        "window_start": "2026-09-16T08:00:00Z",
        "window_end": "2026-09-17T08:00:00Z",
        "source": "Reddit public API",
        "opportunities": [{
            "id": "t3_abc123", "subreddit": "ProductManagement",
            "title": "Best AI tool for prototyping?",
            "permalink": "/r/ProductManagement/comments/abc123/best_ai_tool/",
            "created_at": "2026-09-17T07:00:00Z", "score": 91, "priority": "P0",
            "icp": "PM", "pain_point": "Prototype", "fit_reason": "Fast iteration",
            "promotion_risk": "Check the community's self-promotion rule",
            "product_mention_allowed": True, "action": "Answer, then mention OJO if allowed",
            "summary": "A PM asks for a quick prototype workflow.",
            "core_question": "What can create a testable prototype?",
            "reply_angle": "Compare approaches and trade-offs.",
            "comment_draft": "Start with the user flow, then test an interactive prototype.",
            "evidence": ["Fresh post", "Explicit tool request"],
            "flags": ["Verify current rules"],
        }],
    }


class ReportTests(unittest.TestCase):
    def test_markdown_has_complete_review_context(self):
        report = render_markdown(sample_run())
        self.assertIn("P0 1, P1 0, P2 0", report)
        self.assertIn("Drafts only — no comment has been posted automatically", report)
        self.assertIn("check current subreddit rules", report)
        self.assertIn("[Best AI tool for prototyping?](https://www.reddit.com/r/ProductManagement/comments/abc123/best_ai_tool/)", report)
        self.assertIn("Comment draft — review and edit", report)
        self.assertIn("Verify current rules", report)

    def test_untrusted_reddit_text_cannot_forge_markdown_or_html(self):
        run = sample_run()
        item = run["opportunities"][0]
        item["title"] = "](<https://evil.example>)\n# Fake report heading | P0"
        item["comment_draft"] = "<script>alert(1)</script>\n## Approved by OJO"
        item["evidence"] = ["new\n- forged bullet [click](https://evil.example)"]
        item["permalink"] = "https://evil.example/r/ProductManagement/comments/abc123/"
        report = render_markdown(run)
        self.assertNotIn("<script>", report)
        self.assertNotIn("\n# Fake report heading", report)
        self.assertNotIn("\n## Approved by OJO", report)
        self.assertNotIn("](https://evil.example)", report)
        self.assertNotIn("(<https://evil.example>)", report)
        self.assertIn("URL omitted (not a valid Reddit post URL)", report)
        self.assertIn("&lt;script&gt;", report)

    def test_csv_roundtrip_and_formula_neutralization(self):
        run = sample_run()
        item = run["opportunities"][0]
        item["title"] = "=HYPERLINK(\"https://evil.example\",\"click\")"
        item["comment_draft"] = "\ufeff\t@SUM(1,1)"
        item["evidence"] = ["+cmd", "-danger"]
        item["permalink"] = "javascript:alert(1)"
        rows = list(csv.DictReader(io.StringIO(render_csv(run))))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["title"].startswith("'=HYPERLINK"))
        self.assertTrue(rows[0]["comment_draft"].startswith("'\ufeff\t@SUM"))
        self.assertTrue(rows[0]["evidence"].startswith("'+cmd"))
        self.assertEqual(rows[0]["permalink"], "")
        self.assertIn("P0 1", rows[0]["qa_summary"])
        self.assertIn("check current subreddit rules", rows[0]["limitations"])
        self.assertEqual(rows[0]["posting_status"], "Draft only; not posted")

    def test_empty_run_and_invalid_payload(self):
        run = sample_run()
        run["opportunities"] = []
        self.assertIn("No opportunities matched", render_markdown(run))
        self.assertEqual(len(list(csv.DictReader(io.StringIO(render_csv(run))))), 0)
        run["opportunities"] = "not a list"
        with self.assertRaises(ValueError):
            render_markdown(run)


if __name__ == "__main__":
    unittest.main()
