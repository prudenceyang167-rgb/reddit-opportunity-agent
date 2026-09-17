from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from reddit_opportunity_agent.scoring import evaluate_posts


NOW = datetime(2026, 9, 17, 12, tzinfo=timezone.utc)


def post(pid="a1", *, title="Best AI tool for prototyping?", body="I'm a product manager with a PRD; any tools?", hours=2, sub="ExamplePM", **extra):
    return {"id": pid, "title": title, "selftext": body, "created_utc": (NOW - timedelta(hours=hours)).timestamp(),
            "subreddit": sub, "num_comments": 4, "score": 5,
            "permalink": f"/r/{sub}/comments/{pid}/sample/", **extra}


def config(*, policy="unknown", checked=True, facts=True):
    return {"brand": "OJO", "target_subreddits": ["ExamplePM"], "max_opportunities": 5,
            "verified_product_facts": ["A verified capability."] if facts else [],
            "promotion_policies": {"ExamplePM": {"status": policy,
                                                  "checked_at": NOW.isoformat() if checked else "2020-01-01T00:00:00Z",
                                                  "evidence_url": "https://www.reddit.com/r/ExamplePM/about/rules"}}}


class ScoringTest(unittest.TestCase):
    def run_score(self, posts, conf=None):
        return evaluate_posts(posts, conf or config(), now=NOW, source="synthetic")

    def test_unknown_rules_never_authorize_product_mention(self):
        row = self.run_score([post()])["opportunities"][0]
        self.assertEqual(row["priority"], "P1")
        self.assertFalse(row["product_mention_allowed"])
        self.assertNotIn("OJO", row["comment_draft"])

    def test_human_verified_current_rule_and_fact_allow_p0_with_disclosure(self):
        row = self.run_score([post()], config(policy="may_mention"))["opportunities"][0]
        self.assertEqual(row["priority"], "P0")
        self.assertTrue(row["product_mention_allowed"])
        self.assertIn("Disclosure: I work on OJO", row["comment_draft"])

    def test_old_rule_or_missing_fact_downgrades(self):
        for conf in (config(policy="may_mention", checked=False), config(policy="may_mention", facts=False)):
            with self.subTest(conf=conf):
                row = self.run_score([post()], conf)["opportunities"][0]
                self.assertNotEqual(row["priority"], "P0")
                self.assertFalse(row["product_mention_allowed"])

    def test_invalid_fact_config_cannot_authorize_product_mention(self):
        for facts in ("unverified", None, [""], ["  "], ["Valid fact", 42]):
            with self.subTest(facts=facts):
                conf = config(policy="may_mention")
                conf["verified_product_facts"] = facts
                with self.assertRaisesRegex(ValueError, "verified_product_facts"):
                    self.run_score([post()], conf)

    def test_only_same_subreddit_rules_page_is_mention_evidence(self):
        for evidence in (
            "https://www.reddit.com/r/Other/about/rules",
            "https://www.reddit.com/r/ExamplePM/comments/abc/mod_note/",
            "https://www.reddit.com/r/ExamplePM/new/",
            "https://www.reddit.com:444/r/ExamplePM/about/rules",
        ):
            with self.subTest(evidence=evidence):
                conf = config(policy="may_mention")
                conf["promotion_policies"]["ExamplePM"]["evidence_url"] = evidence
                row = self.run_score([post()], conf)["opportunities"][0]
                self.assertFalse(row["product_mention_allowed"])
                self.assertEqual(row["promotion_risk"], "unknown")

    def test_oversized_input_fails_instead_of_silent_truncation(self):
        with self.assertRaisesRegex(ValueError, "5,000 posts"):
            self.run_score([post()] * 5001)

    def test_recent_valid_posts_only_and_deduplicate(self):
        posts = [post(), post(), post("old", hours=25), post("bad", locked=True),
                 post("outside", sub="Other"), post("unsafe", permalink="https://evil.example/x")]
        run = self.run_score(posts)
        self.assertEqual(len(run["opportunities"]), 1)
        self.assertEqual(run["counts"]["deduplicated"], 1)
        self.assertEqual(run["counts"]["outside_window"], 1)

    def test_low_fit_is_research_only_without_draft(self):
        row = self.run_score([post(title="AI design workflow notes", body="We are exploring an AI design workflow.", hours=20)])["opportunities"][0]
        self.assertEqual(row["priority"], "P2")
        self.assertEqual(row["action"], "research_only")
        self.assertFalse(row["comment_draft"])

    def test_no_target_subreddits_fails(self):
        with self.assertRaises(ValueError):
            self.run_score([post()], {"target_subreddits": []})


if __name__ == "__main__":
    unittest.main()
