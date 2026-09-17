"""Weekly insight aggregation never invents activity or conversion outcomes."""

from __future__ import annotations

import unittest
import json
from datetime import datetime, timezone

from reddit_opportunity_agent.weekly import (
    aggregate_weekly, aggregate_weekly_digests, make_daily_digest, render_weekly_markdown,
)


NOW = datetime(2026, 9, 18, 12, tzinfo=timezone.utc)


def opportunity(post_id: str, *, pain: str = "Prototype", priority: str = "P1", title: str = "How can I prototype faster?") -> dict:
    return {
        "id": post_id, "priority": priority, "pain_point": pain,
        "title": title, "core_question": title,
        "permalink": f"/r/ExamplePM/comments/{post_id}/question/",
    }


def daily(day: int, *opportunities: dict) -> dict:
    return {
        "window_start": f"2026-09-{day:02d}T00:00:00Z",
        "window_end": f"2026-09-{day + 1:02d}T00:00:00Z",
        "opportunities": list(opportunities),
    }


class WeeklyTests(unittest.TestCase):
    def test_daily_runs_deduplicate_threads_and_do_not_invent_outcomes(self):
        runs = [
            daily(11, opportunity("a1"), opportunity("b2", pain="MVP", priority="P2", title="What tool helps my MVP?")),
            daily(12, opportunity("a1", priority="P0"), opportunity("c3")),
        ]
        report = aggregate_weekly(runs, now=NOW)
        self.assertEqual(report["run_count"], 2)
        self.assertEqual(report["screened_days"], 2)
        self.assertEqual(report["unique_discussions"], 3)
        self.assertEqual(report["duplicate_selections"], 1)
        self.assertEqual(report["kpis"]["community"]["screened_high_value_discussions"], 2)
        self.assertEqual(report["pain_point_frequency"][0]["pain_point"], "Prototype")
        self.assertEqual(report["pain_point_frequency"][0]["discussion_count"], 2)
        self.assertEqual(report["frequent_user_questions"][0]["discussion_count"], 2)
        self.assertEqual(report["new_query_candidates"][0]["validation_status"], "unvalidated_candidate")
        self.assertEqual(report["new_query_candidates"][0]["origins"], ["screened_thread_question"])
        self.assertEqual(report["use_cases"], [])
        self.assertEqual(report["competitor_pains"], [])
        self.assertEqual(report["product_feedback"], [])
        self.assertEqual(report["top_responses"], [])
        self.assertIsNone(report["kpis"]["community"]["confirmed_replies"]["value"])
        self.assertIsNone(report["kpis"]["community"]["natural_mentions"]["value"])
        self.assertIsNone(report["kpis"]["growth"]["signups"]["value"])
        rendered = render_weekly_markdown(report)
        self.assertIn("Not measured", rendered)
        self.assertIn("Not recorded in human review", rendered)
        self.assertNotIn("Paid customers: 0", rendered)

    def test_human_review_annotations_and_observed_metrics(self):
        runs = [daily(11, opportunity("a1"), opportunity("b2", title="Which AI design tool?"))]
        reviews = [
            {
                "post_id": "a1", "status": "replied",
                "query_candidates": ["interactive prototype builder"],
                "use_cases": ["Usability testing"],
                "competitor_pains": ["Competitor export is hard to edit"],
                "product_feedback": ["Need more editable components"],
                "outcome_metrics": {
                    "reply_interactions": 3, "natural_mentions": 0,
                    "reddit_referral_visits": 12, "signups": 2,
                    "activations": 1, "paid_customers": 0,
                },
                "response_metrics": {"score": 7, "reply_count": 3,
                                     "permalink": "/r/ExamplePM/comments/a1/question/comment123/"},
            },
            {
                "post_id": "b2", "status": "skipped",
                "outcome_metrics": {"signups": 0},
            },
        ]
        report = aggregate_weekly(runs, reviews, now=NOW)
        community = report["kpis"]["community"]
        growth = report["kpis"]["growth"]
        self.assertEqual(community["confirmed_replies"], {"value": 1, "observed_records": 2})
        self.assertEqual(community["natural_mentions"], {"value": 0, "observed_records": 1})
        self.assertEqual(growth["signups"], {"value": 2, "observed_records": 2})
        self.assertEqual(growth["paid_customers"], {"value": 0, "observed_records": 1})
        self.assertEqual(report["use_cases"][0]["use_case"], "Usability testing")
        self.assertEqual(report["competitor_pains"][0]["issue"], "Competitor export is hard to edit")
        self.assertEqual(report["product_feedback"][0]["feedback"], "Need more editable components")
        self.assertEqual(report["top_responses"][0]["score"], 7)
        self.assertEqual(report["top_responses"][0]["ranking_basis"], "comment_score")
        rendered = render_weekly_markdown(report)
        self.assertIn("Paid customers: 0 (from 1 recorded review(s))", rendered)
        self.assertIn("Need more editable components", rendered)
        self.assertIn("[View response](https://www.reddit.com/r/ExamplePM/comments/a1/question/comment123/)", rendered)

    def test_top_responses_require_actual_reply_and_measured_score_or_replies(self):
        runs = [daily(11, opportunity("a1"), opportunity("b2"))]
        reviews = [
            {"post_id": "a1", "status": "replied", "response_metrics": {"reply_count": 4}},
            {"post_id": "b2", "status": "replied", "response_metrics": {"score": -1}},
        ]
        report = aggregate_weekly(runs, reviews, now=NOW)
        self.assertEqual([row["post_id"] for row in report["top_responses"]], ["b2", "a1"])
        self.assertEqual(report["top_responses"][1]["ranking_basis"], "reply_count")
        self.assertIsNone(report["kpis"]["community"]["reply_interactions"]["value"])

    def test_rejects_unmatched_or_duplicate_reviews_and_invalid_metrics(self):
        runs = [daily(11, opportunity("a1"))]
        for reviews in (
            [{"post_id": "other", "status": "replied"}],
            [{"post_id": "a1"}, {"post_id": "a1"}],
            [{"post_id": "a1", "outcome_metrics": {"signups": -1}}],
            [{"post_id": "a1", "outcome_metrics": {"signups": True}}],
            [{"post_id": "a1", "status": "reviewed", "response_metrics": {"score": 5}}],
            [{"post_id": "a1", "status": "replied", "response_metrics": {"score": "5"}}],
        ):
            with self.subTest(reviews=reviews), self.assertRaises(ValueError):
                aggregate_weekly(runs, reviews, now=NOW)

    def test_untrusted_question_cannot_inject_markdown(self):
        attack = "# Fake heading [click](https://evil.example) <script>"
        report = aggregate_weekly([daily(11, opportunity("a1", title=attack))], now=NOW)
        rendered = render_weekly_markdown(report)
        self.assertNotIn("\n# Fake heading", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("[click](https://evil.example)", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_empty_runs_report_no_period_and_no_metrics(self):
        report = aggregate_weekly([], now=NOW)
        self.assertIsNone(report["period_start"])
        self.assertEqual(report["unique_discussions"], 0)
        self.assertIsNone(report["kpis"]["growth"]["reddit_referral_visits"]["value"])
        self.assertIn("No pain categories", render_weekly_markdown(report))

    def test_daily_digest_drops_raw_reddit_content_and_requires_human_generalization(self):
        post = opportunity("sensitive_post_id", pain="Hard to Iterate", title="How can I edit this private prototype?")
        post.update({"use_case": "Prototype", "author": "private_username",
                     "selftext": "Sensitive verbatim complaint", "permalink": "/r/ExamplePM/comments/sensitive_post_id/private/"})
        review = {
            "post_id": "sensitive_post_id", "status": "replied",
            "query_candidates": ["Sensitive verbatim complaint"],  # Legacy raw field is not retained.
            "generalized_attested": True,
            "generalized_insights": {
                "question_themes": ["Prototype editing workflow"],
                "query_candidates": ["editable prototype builder"],
                "use_cases": ["Fast iteration review"],
                "competitor_pains": ["Export editability friction"],
                "product_feedback": ["Need editable components"],
                "content_ideas": ["Guide to prototype iteration"],
            },
            "outcome_metrics": {"signups": 0},
            "response_metrics": {"score": 8, "reply_count": 2,
                                 "permalink": "/r/ExamplePM/comments/sensitive_post_id/private/comment123/"},
        }
        digest = make_daily_digest(daily(11, post), [review])
        serialized = json.dumps(digest)
        for raw in ("sensitive_post_id", "private_username", "Sensitive verbatim complaint",
                    "How can I edit this private prototype?", "reddit.com", "/r/ExamplePM"):
            self.assertNotIn(raw, serialized)
        self.assertEqual(digest["schema"], "reddit-opportunity-daily-digest/v1")
        self.assertEqual(digest["pain_point_frequency"],
                         [{"pain_point": "Hard to Iterate", "selection_count": 1}])
        self.assertEqual(digest["use_case_frequency"],
                         [{"use_case": "Prototype", "selection_count": 1}])
        self.assertEqual(digest["new_query_candidates"],
                         [{"query": "editable prototype builder", "selection_count": 1}])
        self.assertEqual(digest["top_responses"],
                         [{"score": 8, "reply_count": 2, "ranking_basis": "comment_score"}])
        self.assertEqual(digest["kpis"]["growth"]["signups"]["value"], 0)

    def test_weekly_digest_aggregates_counts_without_claiming_unique_threads(self):
        shared = opportunity("same_id", pain="Generic UI", title="How do I improve this design?")
        shared["use_case"] = "AI Design"
        first = make_daily_digest(daily(11, shared), [{
            "post_id": "same_id", "status": "replied", "generalized_attested": True,
            "generalized_insights": {"question_themes": ["AI design quality"],
                                     "query_candidates": ["improve AI design quality"]},
            "outcome_metrics": {"signups": 0}, "response_metrics": {"score": 3},
        }])
        second = make_daily_digest(daily(12, shared), [{
            "post_id": "same_id", "status": "reviewed", "generalized_attested": True,
            "generalized_insights": {"question_themes": ["AI design quality"]},
        }])
        report = aggregate_weekly_digests([first, second], now=NOW)
        self.assertEqual(report["daily_selections"], 2)
        self.assertIsNone(report["unique_discussions"])
        self.assertEqual(report["pain_point_frequency"][0]["discussion_count"], 2)
        self.assertEqual(report["question_themes"][0]["discussion_count"], 2)
        self.assertEqual(report["kpis"]["community"]["confirmed_replies"],
                         {"value": 1, "observed_records": 2})
        self.assertEqual(report["kpis"]["growth"]["signups"],
                         {"value": 0, "observed_records": 1})
        self.assertIsNone(report["kpis"]["growth"]["paid_customers"]["value"])
        rendered = render_weekly_markdown(report)
        self.assertIn("daily selections: 2 (may include repeats)", rendered)
        self.assertIn("Human-generalized question themes", rendered)
        self.assertIn("Anonymous measured response", rendered)
        self.assertNotIn("same_id", rendered)

    def test_synthetic_digest_is_labeled_and_cannot_mix_with_approved_data(self):
        sample = daily(11, opportunity("a1"))
        sample["source"] = "SYNTHETIC DEMO — no real Reddit data"
        synthetic = make_daily_digest(sample)
        self.assertEqual(synthetic["source_type"], "synthetic")
        report = aggregate_weekly_digests([synthetic], now=NOW)
        self.assertIn("SYNTHETIC DEMO", render_weekly_markdown(report))
        sample["source"] = "Reddit OAuth Data API — approved use only"
        approved = make_daily_digest(sample)
        with self.assertRaisesRegex(ValueError, "cannot mix"):
            aggregate_weekly_digests([synthetic, approved], now=NOW)

    def test_digest_rejects_raw_fields_and_unattested_or_quoted_labels(self):
        post = opportunity("a1", pain="MVP Scope")
        post["author"] = "private_author"
        digest = make_daily_digest(daily(11, post))
        contaminated = dict(digest, title="A Reddit title")
        with self.assertRaises(ValueError):
            aggregate_weekly_digests([contaminated], now=NOW)
        for insights, attested in (
            ({"query_candidates": ["keyword idea"]}, False),
            ({"query_candidates": ["https://reddit.com/r/foo"]}, True),
            ({"query_candidates": ["Visit reddit.com for details"]}, True),
            ({"query_candidates": ["Review a1 discussion"]}, True),
            ({"question_themes": ["private_author workflow"]}, True),
            ({"question_themes": ["How can I prototype faster?"]}, True),
            ({"product_feedback": ['"Verbatim quote"']}, True),
        ):
            with self.subTest(insights=insights), self.assertRaises(ValueError):
                make_daily_digest(daily(11, post), [{
                    "post_id": "a1", "generalized_attested": attested,
                    "generalized_insights": insights,
                }])


if __name__ == "__main__":
    unittest.main()
