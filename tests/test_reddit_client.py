"""Offline contract tests: these tests never contact Reddit."""

import io
import json
import unittest
from datetime import datetime, timezone
from urllib.error import HTTPError

from reddit_opportunity_agent.reddit_client import (
    RedditAccessError,
    RedditRateLimitError,
    RedditWindowTruncatedError,
    fetch_new_posts,
)


NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
UA = "web:prudence.reddit-opportunities:v1.0 (by /u/prudenceyang167)"


def post(post_id, *, hours_ago=1, **overrides):
    value = {
        "id": post_id,
        "subreddit": "UXDesign",
        "title": "How can I prototype faster?",
        "selftext": "Looking for a realistic workflow",
        "created_utc": NOW.timestamp() - hours_ago * 3600,
        "num_comments": 4,
        "score": 5,
        "permalink": f"/r/UXDesign/comments/{post_id}/question/",
        "locked": False,
        "stickied": False,
        "over_18": False,
        "removed_by_category": None,
    }
    value.update(overrides)
    return {"kind": "t3", "data": value}


class FakeResponse:
    def __init__(self, payload, *, status=200, headers=None):
        self.status = status
        self.headers = headers or {}
        self._body = io.BytesIO(json.dumps(payload).encode())

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, count=-1):
        return self._body.read(count)


class QueueOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, *, timeout):
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("Unexpected network request")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def fetch(opener, **overrides):
    kwargs = {
        "client_id": "test-client",
        "client_secret": "test-secret",
        "user_agent": UA,
        "approval_confirmed": True,
        "now": NOW,
        "opener": opener,
        "sleeper": lambda _: None,
    }
    kwargs.update(overrides)
    return fetch_new_posts(["UXDesign"], **kwargs)


class RedditClientTests(unittest.TestCase):
    def test_requires_explicit_approval_before_network(self):
        opener = QueueOpener([])
        with self.assertRaisesRegex(RedditAccessError, "approval"):
            fetch(opener, approval_confirmed=False)
        self.assertEqual(opener.requests, [])

    def test_requires_credentials_and_descriptive_user_agent(self):
        opener = QueueOpener([])
        for bad in ({"client_secret": ""}, {"user_agent": "Python/urllib"}):
            with self.assertRaises(RedditAccessError):
                fetch(opener, **bad)
        self.assertEqual(opener.requests, [])

    def test_only_oauth_token_and_read_only_listing_requests(self):
        opener = QueueOpener([
            FakeResponse({"access_token": "fake-token", "token_type": "bearer"}),
            FakeResponse({"data": {"children": [post("abc"), post("old", hours_ago=25)], "after": None}}),
        ])
        results = fetch(opener)
        self.assertEqual([item["id"] for item in results], ["abc"])
        self.assertEqual(opener.requests[0].get_method(), "POST")
        self.assertEqual(opener.requests[0].full_url, "https://www.reddit.com/api/v1/access_token")
        self.assertEqual(opener.requests[0].data, b"grant_type=client_credentials")
        self.assertTrue(opener.requests[0].get_header("Authorization").startswith("Basic "))
        self.assertEqual(opener.requests[1].get_method(), "GET")
        self.assertIn("https://oauth.reddit.com/r/UXDesign/new?", opener.requests[1].full_url)
        self.assertIn("limit=100", opener.requests[1].full_url)
        self.assertEqual(opener.requests[1].get_header("Authorization"), "Bearer fake-token")

    def test_filters_deleted_removed_locked_stickied_and_nsfw(self):
        children = [
            post("keep"),
            post("locked", locked=True),
            post("sticky", stickied=True),
            post("nsfw", over_18=True),
            post("removed", removed_by_category="moderator"),
            post("deleted", selftext="[deleted]"),
            post("old", hours_ago=24.01),
            post("future", hours_ago=-3),
            post("unsafe", permalink="https://evil.example/"),
        ]
        opener = QueueOpener([
            FakeResponse({"access_token": "token"}),
            FakeResponse({"data": {"children": children, "after": None}}),
        ])
        self.assertEqual([x["id"] for x in fetch(opener)], ["keep"])

    def test_paginates_until_cutoff_and_never_requests_more_than_100(self):
        opener = QueueOpener([
            FakeResponse({"access_token": "token"}),
            FakeResponse({"data": {"children": [post("p1")], "after": "t3_p1"}}),
            FakeResponse({"data": {"children": [post("p2"), post("old", hours_ago=25)], "after": "t3_old"}}),
        ])
        ids = [item["id"] for item in fetch(opener, limit_per_sub=150)]
        self.assertEqual(ids, ["p1", "p2"])
        self.assertIn("after=t3_p1", opener.requests[2].full_url)
        self.assertIn("limit=100", opener.requests[1].full_url)

    def test_truncated_window_fails_closed(self):
        opener = QueueOpener([
            FakeResponse({"access_token": "token"}),
            FakeResponse({"data": {"children": [post("p1")], "after": "t3_p1"}}),
        ])
        with self.assertRaises(RedditWindowTruncatedError):
            fetch(opener, limit_per_sub=1)

    def test_rate_limit_headers_fail_before_next_request(self):
        opener = QueueOpener([
            FakeResponse({"access_token": "token"}),
            FakeResponse(
                {"data": {"children": [post("p1")], "after": "t3_p1"}},
                headers={"X-Ratelimit-Remaining": "0", "X-Ratelimit-Reset": "45"},
            ),
        ])
        with self.assertRaises(RedditRateLimitError) as context:
            fetch(opener, limit_per_sub=150)
        self.assertEqual(context.exception.retry_after, 45)
        self.assertEqual(len(opener.requests), 2)

    def test_http_429_backs_off_then_succeeds(self):
        sleeps = []
        opener = QueueOpener([
            FakeResponse({"access_token": "token"}),
            HTTPError("https://oauth.reddit.com/r/UXDesign/new", 429, "Too Many", {"Retry-After": "2"}, None),
            FakeResponse({"data": {"children": [post("p1")], "after": None}}),
        ])
        self.assertEqual([x["id"] for x in fetch(opener, sleeper=sleeps.append)], ["p1"])
        self.assertEqual(sleeps, [2])

    def test_http_403_is_clear_safe_failure(self):
        opener = QueueOpener([
            HTTPError("https://www.reddit.com/api/v1/access_token", 403, "Forbidden", {}, None),
        ])
        with self.assertRaisesRegex(RedditAccessError, "HTTP 403") as context:
            fetch(opener)
        self.assertNotIn("test-secret", str(context.exception))

    def test_subreddit_path_is_validated_before_network(self):
        opener = QueueOpener([])
        with self.assertRaises(ValueError):
            fetch_new_posts(["../api/comment"], client_id="x", client_secret="y", user_agent=UA,
                            approval_confirmed=True, now=NOW, opener=opener)
        self.assertEqual(opener.requests, [])


if __name__ == "__main__":
    unittest.main()
