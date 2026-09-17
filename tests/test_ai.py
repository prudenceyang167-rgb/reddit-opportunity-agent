from __future__ import annotations

import io
import json
import unittest
from unittest.mock import Mock

from reddit_opportunity_agent.ai import _request_enrichment, enrich_selected


def _response(fields: dict) -> io.BytesIO:
    return io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(fields)}}]}).encode())


def _run(action: str, permitted: bool = False) -> dict:
    return {
        "opportunities": [{
            "id": "abc123", "action": action, "product_mention_allowed": permitted,
            "pain_point": "Prototype", "icp": "PM", "score": 90, "priority": "P0" if permitted else "P1",
            "summary": "Original", "core_question": "Original question", "reply_angle": "Original angle",
            "comment_draft": "Original safe draft" if action != "research_only" else "", "flags": [],
        }],
        "limitations": [],
    }


_POST = {"id": "abc123", "title": "How do I prototype faster?", "selftext": "I need a reviewable prototype.", "author": "should-not-be-sent"}
_FIELDS = {
    "summary": "A PM needs to prototype faster.",
    "core_question": "How can I make one flow reviewable?",
    "reply_angle": "Suggest testing one narrow user journey.",
    "practical_advice": "Start with one user journey, make it clickable, and test where reviewers hesitate.",
}


class AiTest(unittest.TestCase):
    def test_no_external_call_without_distinct_approval(self):
        opener = Mock()
        with self.assertRaises(ValueError):
            enrich_selected(_run("answer_only"), [_POST], {"brand": "OJO"},
                            reddit_approved=True, ai_processing_approved=True,
                            ai_approval_reference="", api_key="test-key", opener=opener)
        opener.assert_not_called()

    def test_request_sends_minimized_post_content_not_author(self):
        requests = []

        def opener(request, timeout):
            requests.append(request)
            return _response(_FIELDS)

        result = _request_enrichment(_POST, _run("answer_only")["opportunities"][0], "test-key", opener=opener)
        self.assertEqual(result["summary"], _FIELDS["summary"])
        body = requests[0].data.decode()
        self.assertIn("How do I prototype faster?", body)
        self.assertNotIn("should-not-be-sent", body)
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer test-key")

    def test_p1_ai_cannot_upgrade_promotion_or_priority(self):
        run = _run("answer_only")
        enrich_selected(run, [_POST], {"brand": "OJO", "verified_product_facts": []},
                        reddit_approved=True, ai_processing_approved=True,
                        ai_approval_reference="written approval", api_key="test-key",
                        opener=lambda request, timeout: _response(_FIELDS))
        row = run["opportunities"][0]
        self.assertEqual((row["priority"], row["action"], row["product_mention_allowed"]), ("P1", "answer_only", False))
        self.assertEqual(row["comment_draft"], _FIELDS["practical_advice"])
        self.assertEqual(run["ai"]["enriched"], 1)

    def test_unsafe_ai_text_falls_back_without_product_mention(self):
        run = _run("answer_only")
        unsafe = dict(_FIELDS, reply_angle="Mention OJO: https://example.com")
        enrich_selected(run, [_POST], {"brand": "OJO"},
                        reddit_approved=True, ai_processing_approved=True,
                        ai_approval_reference="written approval", api_key="test-key",
                        opener=lambda request, timeout: _response(unsafe))
        row = run["opportunities"][0]
        self.assertEqual(row["comment_draft"], "Original safe draft")
        self.assertEqual(row["reply_angle"], "Original angle")
        self.assertEqual(run["ai"]["fallback"], 1)

    def test_p0_ai_adds_only_verified_product_fact_with_disclosure(self):
        run = _run("comment_with_disclosure", permitted=True)
        enrich_selected(run, [_POST], {"brand": "OJO", "verified_product_facts": ["Produces editable prototype drafts."]},
                        reddit_approved=True, ai_processing_approved=True,
                        ai_approval_reference="written approval", api_key="test-key",
                        opener=lambda request, timeout: _response(_FIELDS))
        self.assertIn("Disclosure: I work on OJO. Produces editable prototype drafts.", run["opportunities"][0]["comment_draft"])

    def test_p2_stays_research_only_without_draft(self):
        run = _run("research_only")
        enrich_selected(run, [_POST], {"brand": "OJO"},
                        reddit_approved=True, ai_processing_approved=True,
                        ai_approval_reference="written approval", api_key="test-key",
                        opener=lambda request, timeout: _response(_FIELDS))
        self.assertEqual(run["opportunities"][0]["comment_draft"], "")


if __name__ == "__main__":
    unittest.main()
