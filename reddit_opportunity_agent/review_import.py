"""Read human review outcomes from the ordinary Feishu spreadsheet CSV.

The exported sheet also contains short-lived Reddit material.  This module
returns status, observed interaction counts, and expressly attested human
generalizations for a matching approved daily run. Titles, links, drafts, and
arbitrary reviewer notes never leave the parser. It does not contact Feishu
or Reddit.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import re
from urllib.parse import urlsplit

from .report import _FEISHU_COLUMNS
from .weekly import make_daily_digest


_APPROVED_SOURCES = {
    "Reddit OAuth Data API — approved use only",
    "User-supplied export under Reddit-approved use case",
}
_STATUSES = {
    "reviewed": "reviewed", "已审核": "reviewed", "已审阅": "reviewed",
    "approved": "approved", "已批准": "approved",
    "replied": "replied", "已回复": "replied",
    "skipped": "skipped", "已跳过": "skipped", "跳过": "skipped",
}
_PENDING = {"", "待审核", "pending"}
_YES = {"yes", "true", "是", "已确认"}
_NO = {"", "no", "false", "否", "未确认"}
_INSIGHT_FIELDS = {
    "Question Theme": "question_themes",
    "Query Candidate": "query_candidates",
    "Use Case Insight": "use_cases",
    "Competitor Pain": "competitor_pains",
    "Product Feedback": "product_feedback",
    "Content Idea": "content_ideas",
}
_COMMENT_PATH = re.compile(r"^/r/[A-Za-z0-9_]+/comments/([A-Za-z0-9]+)/[^/]+/([A-Za-z0-9]+)/?$", re.IGNORECASE)


def _utc_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{field} must be a timezone-aware ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware ISO timestamp")
    return parsed.astimezone(timezone.utc)


def _valid_reply_url(value: str, post_id: str) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.hostname not in {"reddit.com", "www.reddit.com"}:
        return False
    if parsed.username or parsed.password or port is not None:
        return False
    match = _COMMENT_PATH.fullmatch(parsed.path)
    if not match:
        return False
    expected = post_id.removeprefix("t3_")
    return match.group(1).casefold() == expected.casefold() and match.group(2).casefold() != expected.casefold()


def parse_feishu_review_csv(csv_text: str, run: dict) -> list[dict]:
    """Return reviews compatible with ``weekly.make_daily_digest``.

    Rows are paired with the daily run by UTC run timestamp and thread ID.  A
    rolling Feishu queue may contain rows from other days; those are ignored.
    Pending rows are ignored unless they contain human insights, in which case
    import fails so those edits cannot silently disappear. "Reply Interactions"
    is observed only when a reviewer marked the row replied and supplied a
    plausible same-thread Reddit comment URL. The URL is checked structurally
    but not fetched. Generalized insights require explicit attestation and are
    validated by ``make_daily_digest`` before returning any reviews.
    """
    if not isinstance(csv_text, str) or len(csv_text) > 2_000_000:
        raise ValueError("Feishu review CSV must be text smaller than 2 MB")
    if not isinstance(run, dict) or run.get("source") not in _APPROVED_SOURCES:
        raise ValueError("Review import requires an approved, non-synthetic daily run")
    run_at = _utc_timestamp(run.get("generated_at"), "run.generated_at")
    opportunities = run.get("opportunities")
    if not isinstance(opportunities, list) or any(not isinstance(item, dict) for item in opportunities):
        raise ValueError("run.opportunities must be a list of objects")
    post_ids = [item.get("id") for item in opportunities]
    if any(not isinstance(pid, str) or not pid for pid in post_ids) or len(set(post_ids)) != len(post_ids):
        raise ValueError("run.opportunities must have distinct nonempty thread IDs")
    ids = set(post_ids)

    try:
        reader = csv.reader(io.StringIO(csv_text.removeprefix("\ufeff"), newline=""), strict=True)
        header = next(reader, None)
        if header != list(_FEISHU_COLUMNS):
            raise ValueError("Feishu review CSV header does not match the current ordinary-sheet template")
        reviews: list[dict] = []
        seen: set[str] = set()
        has_insights = False
        for number, values in enumerate(reader, start=2):
            if number > 501:
                raise ValueError("Feishu review CSV has more than 500 data rows")
            if not any(value.strip() for value in values):
                continue
            if len(values) != len(_FEISHU_COLUMNS):
                raise ValueError(f"Feishu review CSV row {number} has the wrong number of columns")
            row = dict(zip(_FEISHU_COLUMNS, values))
            row_at = _utc_timestamp(row["Run Date UTC"], f"row {number} Run Date UTC")
            if row_at != run_at:
                continue
            post_id = row["Thread ID"].strip()
            if post_id not in ids:
                raise ValueError(f"row {number} Thread ID is not in the daily run")
            if post_id in seen:
                raise ValueError(f"row {number} repeats a Thread ID for the daily run")
            seen.add(post_id)

            status_text = row["Review Status"].strip()
            normalized = status_text.casefold()
            reply_url = row["Manual Reply URL"].strip()
            interactions = row["Reply Interactions"].strip()
            insight_cells = {
                digest_field: row[sheet_field].strip()
                for sheet_field, digest_field in _INSIGHT_FIELDS.items()
                if row[sheet_field].strip()
            }
            if any(label.startswith(("=", "+", "-", "@", "'")) for label in insight_cells.values()):
                raise ValueError(f"row {number} has a formula-like generalized insight")
            attested = row["Generalized Attested"].strip().casefold()
            if attested not in _YES | _NO:
                raise ValueError(f"row {number} has an unrecognized Generalized Attested value")
            if normalized in _PENDING:
                if reply_url or interactions:
                    raise ValueError(f"row {number} is pending but contains reply evidence")
                if insight_cells or attested in _YES:
                    raise ValueError(f"row {number} is pending but contains generalized insights")
                continue
            status = _STATUSES.get(normalized)
            if status is None:
                raise ValueError(f"row {number} has an unrecognized Review Status")
            if insight_cells and attested not in _YES:
                raise ValueError(f"row {number} needs Generalized Attested=Yes for insight fields")
            if status != "replied" and (reply_url or interactions):
                raise ValueError(f"row {number} has reply evidence without replied status")
            outcome: dict[str, int] = {}
            if status == "replied":
                if not _valid_reply_url(reply_url, post_id):
                    raise ValueError(f"row {number} needs a same-thread HTTPS Reddit comment URL")
                if (row["Original Thread Read"].strip().casefold() not in _YES
                        or row["Rules Checked"].strip().casefold() not in _YES):
                    raise ValueError(f"row {number} needs original-thread and community-rule review")
                if interactions:
                    if not re.fullmatch(r"[0-9]+", interactions):
                        raise ValueError(f"row {number} Reply Interactions must be a nonnegative whole number")
                    outcome["reply_interactions"] = int(interactions)
            review = {"post_id": post_id, "status": status, "outcome_metrics": outcome}
            if insight_cells:
                review["generalized_insights"] = {
                    field: [label] for field, label in insight_cells.items()
                }
                review["generalized_attested"] = True
                has_insights = True
            reviews.append(review)
        if has_insights:
            # Reject source quotations, URLs, handles, oversized labels and
            # hidden identifiers before any caller can persist the reviews.
            make_daily_digest(run, reviews)
        return reviews
    except csv.Error as exc:
        raise ValueError("Feishu review CSV is malformed") from exc
