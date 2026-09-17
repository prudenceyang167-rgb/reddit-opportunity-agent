"""The Feishu review reader must not turn drafts into replies or retain source text."""

import csv
import io
import unittest

from reddit_opportunity_agent.report import render_feishu_csv
from reddit_opportunity_agent.review_import import parse_feishu_review_csv
from reddit_opportunity_agent.weekly import make_daily_digest


def sample_run():
    return {
        "generated_at": "2026-09-17T08:00:00Z",
        "window_start": "2026-09-16T08:00:00Z",
        "window_end": "2026-09-17T08:00:00Z",
        "source": "Reddit OAuth Data API — approved use only",
        "opportunities": [{
            "id": "abc123", "title": "Raw source title", "priority": "P0",
            "pain_point": "Prototype", "use_case": "Prototype", "core_question": "Raw question",
            "permalink": "/r/ProductManagement/comments/abc123/raw_source_title/",
        }],
    }


def edit_csv(run, **changes):
    rows = list(csv.DictReader(io.StringIO(render_feishu_csv(run))))
    rows[0].update(changes)
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator="\n", quoting=csv.QUOTE_ALL)
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


class ReviewImportTests(unittest.TestCase):
    def test_pending_is_not_reviewed(self):
        run = sample_run()
        self.assertEqual(parse_feishu_review_csv(render_feishu_csv(run), run), [])

    def test_approved_review_has_no_raw_text_or_made_up_metrics(self):
        run = sample_run()
        text = edit_csv(run, **{
            "Review Status": "已批准", "Reviewer Notes": "private raw notes",
        })
        reviews = parse_feishu_review_csv(text, run)
        self.assertEqual(reviews, [{"post_id": "abc123", "status": "approved", "outcome_metrics": {}}])
        self.assertNotIn("private raw", str(make_daily_digest(run, reviews)))

    def test_attested_human_insights_populate_all_six_digest_categories(self):
        run = sample_run()
        text = edit_csv(run, **{
            "Review Status": "已审核", "Generalized Attested": "Yes",
            "Question Theme": "Prototype iteration workflow",
            "Query Candidate": "interactive prototype builder",
            "Use Case Insight": "Rapid concept validation",
            "Competitor Pain": "Limited editable output",
            "Product Feedback": "Need more context preservation",
            "Content Idea": "Prototype validation checklist",
            "Reviewer Notes": "A raw note that must not survive",
        })
        reviews = parse_feishu_review_csv(text, run)
        self.assertEqual(reviews[0]["generalized_insights"], {
            "question_themes": ["Prototype iteration workflow"],
            "query_candidates": ["interactive prototype builder"],
            "use_cases": ["Rapid concept validation"],
            "competitor_pains": ["Limited editable output"],
            "product_feedback": ["Need more context preservation"],
            "content_ideas": ["Prototype validation checklist"],
        })
        self.assertIs(reviews[0]["generalized_attested"], True)
        digest = make_daily_digest(run, reviews)
        self.assertEqual(digest["question_themes"][0]["theme"], "Prototype iteration workflow")
        self.assertEqual(digest["new_query_candidates"][0]["query"], "interactive prototype builder")
        self.assertEqual(digest["use_cases"][0]["use_case"], "Rapid concept validation")
        self.assertEqual(digest["competitor_pains"][0]["issue"], "Limited editable output")
        self.assertEqual(digest["product_feedback"][0]["feedback"], "Need more context preservation")
        self.assertEqual(digest["content_ideas"][0]["working_topic"], "Prototype validation checklist")
        self.assertNotIn("A raw note", str(digest))
        self.assertNotIn("Raw source title", str(digest))

    def test_insights_never_silently_disappear_when_pending_or_unattested(self):
        run = sample_run()
        with self.assertRaisesRegex(ValueError, "pending but contains generalized insights"):
            parse_feishu_review_csv(edit_csv(run, **{
                "Question Theme": "Prototype iteration workflow",
            }), run)
        with self.assertRaisesRegex(ValueError, "Generalized Attested=Yes"):
            parse_feishu_review_csv(edit_csv(run, **{
                "Review Status": "reviewed", "Query Candidate": "interactive prototype builder",
            }), run)
        with self.assertRaisesRegex(ValueError, "pending but contains generalized insights"):
            parse_feishu_review_csv(edit_csv(run, **{
                "Generalized Attested": "Yes",
            }), run)

    def test_attestation_cannot_launder_source_text_or_urls(self):
        run = sample_run()
        for bad in ("Raw source title", "https://www.reddit.com/r/ProductManagement",
                    "u/example", "x" * 81, "=SUM(1)", "'=SUM(1)"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_feishu_review_csv(edit_csv(run, **{
                    "Review Status": "reviewed", "Generalized Attested": "Yes",
                    "Question Theme": bad,
                }), run)

    def test_replied_requires_evidence_and_preserves_measured_zero(self):
        run = sample_run()
        text = edit_csv(run, **{
            "Review Status": "已回复", "Original Thread Read": "Yes", "Rules Checked": "是",
            "Manual Reply URL": "https://www.reddit.com/r/ProductManagement/comments/abc123/raw_source_title/xy987/",
            "Reply Interactions": "0", "Comment Draft": "untrusted raw text",
        })
        reviews = parse_feishu_review_csv(text, run)
        self.assertEqual(reviews, [{"post_id": "abc123", "status": "replied",
                                    "outcome_metrics": {"reply_interactions": 0}}])
        digest = make_daily_digest(run, reviews)
        self.assertEqual(digest["kpis"]["community"]["confirmed_replies"]["value"], 1)
        self.assertEqual(digest["kpis"]["community"]["reply_interactions"]["value"], 0)
        self.assertNotIn("reddit.com", str(digest))
        self.assertNotIn("untrusted raw text", str(digest))

    def test_blank_interactions_is_unmeasured_not_zero(self):
        run = sample_run()
        reviews = parse_feishu_review_csv(edit_csv(run, **{
            "Review Status": "replied", "Original Thread Read": "yes", "Rules Checked": "yes",
            "Manual Reply URL": "https://reddit.com/r/ProductManagement/comments/abc123/raw_source_title/xy987/",
        }), run)
        digest = make_daily_digest(run, reviews)
        self.assertIsNone(digest["kpis"]["community"]["reply_interactions"]["value"])
        self.assertEqual(digest["kpis"]["community"]["reply_interactions"]["observed_records"], 0)

    def test_reject_synthetic_or_unapproved_source(self):
        run = sample_run()
        text = render_feishu_csv(run)
        for source in ("SYNTHETIC DEMO — no real Reddit data", "Reddit public API", ""):
            run["source"] = source
            with self.subTest(source=source), self.assertRaises(ValueError):
                parse_feishu_review_csv(text, run)

    def test_reject_bad_header_and_duplicate_matching_id(self):
        run = sample_run()
        text = render_feishu_csv(run)
        with self.assertRaisesRegex(ValueError, "header"):
            parse_feishu_review_csv(text.replace("Review Status", "Status", 1), run)
        lines = text.splitlines(keepends=True)
        with self.assertRaisesRegex(ValueError, "repeats"):
            parse_feishu_review_csv("".join(lines + lines[1:]), run)

    def test_reject_unknown_id_and_status(self):
        run = sample_run()
        with self.assertRaisesRegex(ValueError, "Thread ID"):
            parse_feishu_review_csv(edit_csv(run, **{"Thread ID": "other"}), run)
        with self.assertRaisesRegex(ValueError, "Review Status"):
            parse_feishu_review_csv(edit_csv(run, **{"Review Status": "posted by agent"}), run)

    def test_reject_unverified_or_cross_thread_reply(self):
        run = sample_run()
        base = {"Review Status": "replied", "Original Thread Read": "Yes", "Rules Checked": "Yes"}
        bad_urls = (
            "", "http://www.reddit.com/r/ProductManagement/comments/abc123/t/xy987/",
            "https://evil.example/r/ProductManagement/comments/abc123/t/xy987/",
            "https://reddit.com/r/ProductManagement/comments/other/t/xy987/",
            "https://reddit.com/r/ProductManagement/comments/abc123/t/",
            "https://user@reddit.com/r/ProductManagement/comments/abc123/t/xy987/",
        )
        for url in bad_urls:
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "same-thread"):
                parse_feishu_review_csv(edit_csv(run, **base, **{"Manual Reply URL": url}), run)
        with self.assertRaisesRegex(ValueError, "community-rule"):
            parse_feishu_review_csv(edit_csv(run, **{**base, "Rules Checked": "No",
                "Manual Reply URL": "https://reddit.com/r/ProductManagement/comments/abc123/t/xy987/"}), run)

    def test_only_replied_may_have_metrics_and_counts_must_be_whole(self):
        run = sample_run()
        with self.assertRaisesRegex(ValueError, "without replied status"):
            parse_feishu_review_csv(edit_csv(run, **{"Review Status": "approved", "Reply Interactions": "1"}), run)
        base = {"Review Status": "replied", "Original Thread Read": "Yes", "Rules Checked": "Yes",
                "Manual Reply URL": "https://reddit.com/r/ProductManagement/comments/abc123/t/xy987/"}
        for value in ("-1", "1.5", "one", "=1+1"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "nonnegative whole number"):
                parse_feishu_review_csv(edit_csv(run, **base, **{"Reply Interactions": value}), run)

    def test_other_day_in_rolling_sheet_is_ignored(self):
        run = sample_run()
        text = edit_csv(run, **{"Run Date UTC": "2026-09-16T08:00:00Z", "Thread ID": "older"})
        self.assertEqual(parse_feishu_review_csv(text, run), [])


if __name__ == "__main__":
    unittest.main()
