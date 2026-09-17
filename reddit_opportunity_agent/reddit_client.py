"""Approved, read-only Reddit Data API ingestion.

This module must not be used until Reddit has approved the specific use case,
including its commercial and AI-processing aspects. It never posts or comments.
"""

from __future__ import annotations

import base64
import json
import re
import time
from datetime import datetime
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_ORIGIN = "https://oauth.reddit.com"
_SUBREDDIT = re.compile(r"^[A-Za-z0-9_]{1,21}$")
_USER_AGENT = re.compile(
    r"^[A-Za-z][A-Za-z0-9_-]*:[A-Za-z0-9._-]+:v[0-9]+(?:\.[0-9]+)* "
    r"\(by /u/[A-Za-z0-9_-]+\)$"
)
_OUTPUT_FIELDS = (
    "id",
    "subreddit",
    "title",
    "selftext",
    "created_utc",
    "num_comments",
    "score",
    "permalink",
    "locked",
    "stickied",
    "over_18",
    "removed_by_category",
)


class RedditAccessError(RuntimeError):
    """Reddit access is unavailable or not approved; no credentials are exposed."""


class RedditRateLimitError(RedditAccessError):
    """The caller should retry a later run, after ``retry_after`` seconds."""

    def __init__(self, retry_after: float):
        self.retry_after = max(0.0, retry_after)
        super().__init__("Reddit API rate limit reached; retry a later run.")


class RedditWindowTruncatedError(RedditAccessError):
    """The scan limit was reached while more posts may exist in the 24h window."""

    def __init__(self, subreddit: str):
        self.subreddit = subreddit
        super().__init__(
            f"r/{subreddit} has more posts in the 24-hour window; increase the per-subreddit limit."
        )


def _header(headers: Any, name: str) -> str | None:
    value = headers.get(name) if headers is not None else None
    if value is not None:
        return str(value)
    if isinstance(headers, dict):
        return next((str(v) for k, v in headers.items() if k.lower() == name.lower()), None)
    return None


def _seconds(value: str | None, default: float = 0.0) -> float:
    try:
        return max(0.0, float(value)) if value is not None else default
    except (TypeError, ValueError):
        return default


def _request_json(
    request: Request,
    *,
    opener: Callable[..., Any],
    sleeper: Callable[[float], None],
) -> tuple[dict[str, Any], Any]:
    for attempt in range(3):
        try:
            with opener(request, timeout=20) as response:
                status = getattr(response, "status", None) or response.getcode()
                headers = response.headers
                if status == 429:
                    raise RedditRateLimitError(_seconds(_header(headers, "Retry-After"), 60.0))
                if not 200 <= status < 300:
                    raise RedditAccessError(f"Reddit API returned HTTP {status}.")
                # Bound remote response size before parsing it.
                raw = response.read(5_000_001)
                if len(raw) > 5_000_000:
                    raise RedditAccessError("Reddit API response exceeded the safety limit.")
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise RedditAccessError("Reddit API returned an unexpected response.")
                return data, headers
        except HTTPError as exc:
            if exc.code == 429:
                delay = _seconds(_header(exc.headers, "Retry-After"), 60.0)
                if attempt < 2 and delay <= 30:
                    sleeper(delay)
                    continue
                raise RedditRateLimitError(delay) from None
            raise RedditAccessError(f"Reddit API returned HTTP {exc.code}.") from None
        except RedditRateLimitError as exc:
            if attempt < 2 and exc.retry_after <= 30:
                sleeper(exc.retry_after)
                continue
            raise
        except (URLError, TimeoutError, ValueError, UnicodeError, json.JSONDecodeError):
            raise RedditAccessError("Reddit API connection or response failed.") from None
    raise RedditAccessError("Reddit API retry budget exhausted.")


def _validated_subreddits(subreddits: Iterable[str]) -> list[str]:
    if isinstance(subreddits, (str, bytes)):
        raise ValueError("subreddits must be a list of names")
    result: list[str] = []
    seen: set[str] = set()
    for value in subreddits:
        if not isinstance(value, str) or not _SUBREDDIT.fullmatch(value):
            raise ValueError("each subreddit must be a plain community name")
        if value.casefold() not in seen:
            result.append(value)
            seen.add(value.casefold())
    if not result or len(result) > 50:
        raise ValueError("provide between 1 and 50 subreddits")
    return result


def fetch_new_posts(
    subreddits: list[str],
    *,
    client_id: str,
    client_secret: str,
    user_agent: str,
    approval_confirmed: bool,
    now: datetime,
    limit_per_sub: int = 100,
    opener: Callable[..., Any] = urlopen,
    sleeper: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """Fetch only eligible posts created in the preceding 24 hours.

    ``approval_confirmed`` must correspond to explicit Reddit approval of this
    specific use case. ``limit_per_sub`` is a scan cap, not a Reddit page size;
    a truncated window raises instead of silently presenting incomplete data.
    ``opener`` and ``sleeper`` allow offline, deterministic tests.
    """

    if approval_confirmed is not True:
        raise RedditAccessError("Reddit approval is required before API access.")
    if not all(isinstance(v, str) and v.strip() and "\n" not in v and "\r" not in v
               for v in (client_id, client_secret, user_agent)):
        raise RedditAccessError("Approved Reddit OAuth credentials and User-Agent are required.")
    if not _USER_AGENT.fullmatch(user_agent):
        raise RedditAccessError(
            "Use a truthful descriptive User-Agent: platform:app:v1.0 (by /u/username)."
        )
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime")
    if isinstance(limit_per_sub, bool) or not isinstance(limit_per_sub, int) or not 1 <= limit_per_sub <= 1000:
        raise ValueError("limit_per_sub must be between 1 and 1000")
    names = _validated_subreddits(subreddits)
    latest = now.timestamp()
    cutoff = latest - 24 * 60 * 60

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    token_request = Request(
        TOKEN_URL,
        data=urlencode({"grant_type": "client_credentials"}).encode("ascii"),
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": user_agent,
        },
        method="POST",
    )
    token_data, _ = _request_json(token_request, opener=opener, sleeper=sleeper)
    token = token_data.get("access_token")
    token_type = token_data.get("token_type", "bearer")
    if not isinstance(token, str) or not token or not isinstance(token_type, str) or token_type.lower() != "bearer":
        raise RedditAccessError("Reddit OAuth token was unavailable.")

    posts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    last_headers: Any = None
    for subreddit in names:
        examined = 0
        after: str | None = None
        while examined < limit_per_sub:
            if last_headers is not None and _seconds(_header(last_headers, "X-Ratelimit-Remaining"), 1.0) <= 0:
                raise RedditRateLimitError(_seconds(_header(last_headers, "X-Ratelimit-Reset"), 60.0))
            page_size = min(100, limit_per_sub - examined)
            params = {"limit": page_size, "raw_json": 1}
            if after:
                params["after"] = after
            url = f"{API_ORIGIN}/r/{subreddit}/new?{urlencode(params)}"
            request = Request(
                url,
                headers={"Authorization": f"Bearer {token}", "User-Agent": user_agent},
                method="GET",
            )
            data, last_headers = _request_json(request, opener=opener, sleeper=sleeper)
            listing = data.get("data")
            if not isinstance(listing, dict) or not isinstance(listing.get("children"), list):
                raise RedditAccessError("Reddit listing had an unexpected structure.")
            children = listing["children"]
            if not children:
                break
            examined += len(children)
            reached_cutoff = False
            for child in children:
                item = child.get("data") if isinstance(child, dict) else None
                if not isinstance(item, dict):
                    continue
                try:
                    created = float(item.get("created_utc"))
                except (TypeError, ValueError):
                    continue
                if created < cutoff:
                    reached_cutoff = True
                    continue
                if created > latest + 60:
                    continue
                if any(item.get(flag) for flag in ("locked", "stickied", "over_18")):
                    continue
                if item.get("removed_by_category"):
                    continue
                if str(item.get("title", "")).strip().lower() in ("[deleted]", "[removed]"):
                    continue
                if str(item.get("selftext", "")).strip().lower() in ("[deleted]", "[removed]"):
                    continue
                post_id = item.get("id")
                permalink = item.get("permalink")
                if not isinstance(post_id, str) or not re.fullmatch(r"[A-Za-z0-9]+", post_id):
                    continue
                if not isinstance(permalink, str) or not permalink.startswith(f"/r/{subreddit}/", 0):
                    # Do not emit arbitrary links supplied in a malformed listing.
                    continue
                if post_id in seen_ids:
                    continue
                seen_ids.add(post_id)
                posts.append({field: item.get(field) for field in _OUTPUT_FIELDS})
            after = listing.get("after")
            if reached_cutoff or not isinstance(after, str) or not after:
                break
            if examined >= limit_per_sub:
                raise RedditWindowTruncatedError(subreddit)
    return posts
