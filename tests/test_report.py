"""Tests for safe, human-reviewable report exports."""

import csv
import io
import unittest

from reddit_opportunity_agent.report import _FEISHU_COLUMNS, render_community_rules_csv, render_csv, render_feishu_csv, render_markdown


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

    def test_feishu_review_export_has_workflow_fields_and_retention(self):
        run = sample_run()
        item = run["opportunities"][0]
        item.update({"persona": "PM", "use_case": "Prototype", "intent": "tool_selection", "competitor": ["Figma Make"]})
        item["title"] = '=HYPERLINK("https://evil.example","click")'
        rows = list(csv.DictReader(io.StringIO(render_feishu_csv(run))))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["Persona"], "PM")
        self.assertEqual(row["Use Case"], "Prototype")
        self.assertEqual(row["Intent"], "tool_selection")
        self.assertEqual(row["Competitor"], "Figma Make")
        self.assertEqual(row["Review Status"], "待审核")
        self.assertEqual(row["Rules Checked"], "No")
        self.assertEqual(len(_FEISHU_COLUMNS), 42)
        self.assertLess(_FEISHU_COLUMNS.index("Review Status"), _FEISHU_COLUMNS.index("Summary"))
        self.assertLess(_FEISHU_COLUMNS.index("Generalized Attested"), _FEISHU_COLUMNS.index("Comment Draft"))
        self.assertEqual(row["Generalized Attested"], "No")
        for field in ("Question Theme", "Query Candidate", "Use Case Insight",
                      "Competitor Pain", "Product Feedback", "Content Idea"):
            self.assertEqual(row[field], "")
        self.assertEqual(row["Delete By UTC"], "2026-09-18T08:00:00+00:00")
        self.assertTrue(row["Thread"].startswith("'=HYPERLINK"))
        self.assertEqual(row["Thread URL"], "https://www.reddit.com/r/ProductManagement/comments/abc123/best_ai_tool/")

    def test_community_rules_template_never_implies_promotion_permission(self):
        config = {"target_subreddits": ["ProductManagement"], "promotion_policies": {
            "ProductManagement": {"status": "may_mention", "self_promo": "unknown"}
        }}
        rows = list(csv.DictReader(io.StringIO(render_community_rules_csv(config))))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Product Mention Decision"], "unknown")
        self.assertEqual(rows[0]["Self Promotion"], "unknown")
        self.assertIn("ProductManagement/about/rules", rows[0]["Rules URL"])

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
