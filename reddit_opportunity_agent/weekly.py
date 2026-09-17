"""Aggregate approved daily screens and optional human review into a weekly brief.

This module reads already-produced data only.  A screened thread is not a
posted reply, a Reddit comment score is not a conversion, and absent outcome
measurements are never represented as zero.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import re
from typing import Any
import unicodedata

from .report import _md, _reddit_url
from .scoring import PAIN_POINTS, USE_CASES


_OUTCOME_METRICS = (
    "reply_interactions", "natural_mentions", "reddit_referral_visits",
    "signups", "activations", "paid_customers",
)
_STATUSES = {"reviewed", "approved", "replied", "skipped"}
_DIGEST_SCHEMA = "reddit-opportunity-daily-digest/v1"
_APPROVED_SOURCES = {
    "Reddit OAuth Data API — approved use only",
    "User-supplied export under Reddit-approved use case",
}
_GENERALIZED_FIELDS = {
    "question_themes": "theme",
    "query_candidates": "query",
    "use_cases": "use_case",
    "competitor_pains": "issue",
    "product_feedback": "feedback",
    "content_ideas": "working_topic",
}
_REDDIT_REFERENCE = re.compile(
    r"(?:https?://|www\.|\b[a-z0-9-]+\.[a-z]{2,}\b|\b(?:u|r)/|@|[`\[\]{}<>\"“”‘’])",
    re.IGNORECASE,
)


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be a timezone-aware ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware ISO timestamp")
    return parsed.astimezone(timezone.utc)


def _string(value: Any, field: str, *, limit: int = 240) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return " ".join(value.split())[:limit]


def _strings(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list of strings")
    items = [_string(item, field) for item in value]
    if any(not item for item in items):
        raise ValueError(f"{field} cannot contain empty strings")
    return items


def _count(value: Any, field: str, *, allow_negative: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or (value < 0 and not allow_negative):
        raise ValueError(f"{field} must be {'an integer' if allow_negative else 'a nonnegative integer'}")
    return value


def _bucket_add(buckets: dict[str, dict], label: str, post_id: str) -> None:
    key = label.casefold()
    if key not in buckets:
        buckets[key] = {"label": label, "post_ids": set()}
    buckets[key]["post_ids"].add(post_id)


def _bucket_rows(buckets: dict[str, dict], label_field: str) -> list[dict]:
    rows = [
        {label_field: item["label"], "discussion_count": len(item["post_ids"]),
         "post_ids": sorted(item["post_ids"])}
        for item in buckets.values()
    ]
    return sorted(rows, key=lambda row: (-row["discussion_count"], row[label_field].casefold()))


def _observed_total(reviews: list[dict], field: str) -> dict:
    values = [review["outcome_metrics"][field] for review in reviews if field in review["outcome_metrics"]]
    return {"value": sum(values) if values else None, "observed_records": len(values)}


def aggregate_weekly(
    runs: list[dict], reviews: list[dict] | None = None, *, now: datetime | None = None,
) -> dict:
    """Summarize daily ``evaluate_posts`` results and optional human outcomes.

    ``reviews`` contains at most one record per screened ``post_id``.  A record
    may include ``status`` (reviewed/approved/replied/skipped), lists named
    ``query_candidates``, ``use_cases``, ``competitor_pains``, and
    ``product_feedback``, plus ``outcome_metrics`` with any of
    reply_interactions, natural_mentions, reddit_referral_visits, signups,
    activations, or paid_customers.  Only a ``replied`` record may include
    ``response_metrics`` (score and/or reply_count, and an optional permalink).
    Outcome values must be human-supplied observed counts; no analytics or
    social platform calls are made here.
    """
    if not isinstance(runs, list) or any(not isinstance(run, dict) for run in runs):
        raise ValueError("runs must be a list of daily run objects")
    if reviews is None:
        reviews = []
    if not isinstance(reviews, list) or any(not isinstance(review, dict) for review in reviews):
        raise ValueError("reviews must be a list of objects")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    dated_runs = []
    for index, run in enumerate(runs):
        start = _timestamp(run.get("window_start"), f"runs[{index}].window_start")
        end = _timestamp(run.get("window_end"), f"runs[{index}].window_end")
        if end <= start:
            raise ValueError("each run window_end must follow window_start")
        opportunities = run.get("opportunities")
        if not isinstance(opportunities, list) or any(not isinstance(item, dict) for item in opportunities):
            raise ValueError("each run opportunities must be a list of objects")
        dated_runs.append((start, end, opportunities))
    dated_runs.sort(key=lambda item: (item[0], item[1]))

    threads: dict[str, dict] = {}
    duplicate_selections = 0
    for _, _, opportunities in dated_runs:
        for item in opportunities:
            post_id = _string(item.get("id"), "opportunity id", limit=80)
            if not post_id:
                raise ValueError("opportunity id cannot be empty")
            priority = item.get("priority")
            if priority not in {"P0", "P1", "P2"}:
                raise ValueError("opportunity priority must be P0, P1, or P2")
            if post_id in threads:
                duplicate_selections += 1
                # A thread may recur in daily screens; count it only once and
                # retain its highest screening priority for the weekly total.
                if {"P0": 0, "P1": 1, "P2": 2}[priority] < {"P0": 0, "P1": 1, "P2": 2}[threads[post_id]["priority"]]:
                    threads[post_id]["priority"] = priority
                continue
            pain = _string(item.get("pain_point", ""), "pain_point")
            use_case = _string(item.get("use_case", ""), "use_case")
            title = _string(item.get("title", ""), "title")
            question = _string(item.get("core_question", ""), "core_question")
            threads[post_id] = {
                "id": post_id, "priority": priority, "pain_point": pain, "use_case": use_case,
                "question": question if question and question.casefold() == title.casefold() else "",
                "permalink": _reddit_url(item.get("permalink", "")),
            }

    clean_reviews = []
    reviewed_ids = set()
    query_buckets: dict[str, dict] = {}
    query_origins: dict[str, set[str]] = defaultdict(set)
    use_case_buckets: dict[str, dict] = {}
    competitor_buckets: dict[str, dict] = {}
    feedback_buckets: dict[str, dict] = {}
    top_responses = []
    for index, review in enumerate(reviews):
        post_id = _string(review.get("post_id"), f"reviews[{index}].post_id", limit=80)
        if post_id not in threads:
            raise ValueError(f"review post_id {post_id!r} is not in the daily runs")
        if post_id in reviewed_ids:
            raise ValueError(f"duplicate review for post_id {post_id!r}")
        reviewed_ids.add(post_id)
        status = review.get("status")
        if status is not None and status not in _STATUSES:
            raise ValueError("review status must be reviewed, approved, replied, or skipped")
        for field, buckets in (
            ("query_candidates", query_buckets), ("use_cases", use_case_buckets),
            ("competitor_pains", competitor_buckets), ("product_feedback", feedback_buckets),
        ):
            for label in _strings(review.get(field), field):
                _bucket_add(buckets, label, post_id)
                if field == "query_candidates":
                    query_origins[label.casefold()].add("human_review")
        outcome = review.get("outcome_metrics", {})
        if not isinstance(outcome, dict) or set(outcome) - set(_OUTCOME_METRICS):
            raise ValueError("outcome_metrics contains unsupported fields")
        outcome = {field: _count(value, field) for field, value in outcome.items()}
        response = review.get("response_metrics")
        if response is not None:
            if status != "replied" or not isinstance(response, dict):
                raise ValueError("response_metrics requires status='replied' and an object")
            if set(response) - {"score", "reply_count", "permalink"}:
                raise ValueError("response_metrics contains unsupported fields")
            score = _count(response["score"], "response score", allow_negative=True) if "score" in response else None
            reply_count = _count(response["reply_count"], "response reply_count") if "reply_count" in response else None
            if score is not None or reply_count is not None:
                top_responses.append({
                    "post_id": post_id, "thread_permalink": threads[post_id]["permalink"],
                    "response_permalink": _reddit_url(response.get("permalink", "")),
                    "score": score, "reply_count": reply_count,
                    "ranking_basis": "comment_score" if score is not None else "reply_count",
                })
        clean_reviews.append({"post_id": post_id, "status": status, "outcome_metrics": outcome})

    pain_buckets: dict[str, dict] = {}
    use_case_frequency_buckets: dict[str, dict] = {}
    question_buckets: dict[str, dict] = {}
    for item in threads.values():
        if item["pain_point"]:
            _bucket_add(pain_buckets, item["pain_point"], item["id"])
        if item["use_case"]:
            _bucket_add(use_case_frequency_buckets, item["use_case"], item["id"])
        if item["question"]:
            _bucket_add(question_buckets, item["question"], item["id"])
            # A Reddit question is a keyword-research candidate, not evidence
            # of search demand or novelty against an existing query bank.
            _bucket_add(query_buckets, item["question"], item["id"])
            query_origins[item["question"].casefold()].add("screened_thread_question")

    pains = _bucket_rows(pain_buckets, "pain_point")
    use_case_frequency = _bucket_rows(use_case_frequency_buckets, "use_case")
    questions = _bucket_rows(question_buckets, "question")
    queries = _bucket_rows(query_buckets, "query")
    for row in queries:
        row["validation_status"] = "unvalidated_candidate"
        row["origins"] = sorted(query_origins[row["query"].casefold()])
    use_cases = _bucket_rows(use_case_buckets, "use_case")
    competitor_pains = _bucket_rows(competitor_buckets, "issue")
    product_feedback = _bucket_rows(feedback_buckets, "feedback")
    top_responses.sort(key=lambda row: (
        row["score"] is None, -(row["score"] if row["score"] is not None else row["reply_count"]), row["post_id"]
    ))
    content_ideas = [
        {"working_topic": row["question"], "basis": "screened_question",
         "discussion_count": row["discussion_count"], "post_ids": row["post_ids"]}
        for row in questions[:3]
    ]
    if not content_ideas:
        content_ideas = [
            {"working_topic": f"Guide to {row['pain_point']}", "basis": "screened_pain_category",
             "discussion_count": row["discussion_count"], "post_ids": row["post_ids"]}
            for row in pains[:3]
        ]

    known_statuses = [review for review in clean_reviews if review["status"] is not None]
    confirmed_replies = {
        "value": sum(review["status"] == "replied" for review in known_statuses) if known_statuses else None,
        "observed_records": len(known_statuses),
    }
    metrics = {field: _observed_total(clean_reviews, field) for field in _OUTCOME_METRICS}
    return {
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "period_start": min((run[0] for run in dated_runs), default=None).isoformat() if dated_runs else None,
        "period_end": max((run[1] for run in dated_runs), default=None).isoformat() if dated_runs else None,
        "run_count": len(runs), "screened_days": len({run[1].date() for run in dated_runs}),
        "unique_discussions": len(threads), "duplicate_selections": duplicate_selections,
        "kpis": {
            "community": {
                "screened_high_value_discussions": sum(item["priority"] in {"P0", "P1"} for item in threads.values()),
                "confirmed_replies": confirmed_replies,
                "reply_interactions": metrics["reply_interactions"],
                "natural_mentions": metrics["natural_mentions"],
            },
            "growth": {field: metrics[field] for field in (
                "reddit_referral_visits", "signups", "activations", "paid_customers"
            )},
            "business": {
                "query_candidates": len(queries), "use_cases": len(use_cases),
                "use_case_categories": len(use_case_frequency),
                "pain_points": len(pains), "competitor_issues": len(competitor_pains),
            },
        },
        "pain_point_frequency": pains,
        "use_case_frequency": use_case_frequency,
        "frequent_user_questions": questions,
        "new_query_candidates": queries,
        "use_cases": use_cases,
        "competitor_pains": competitor_pains,
        "product_feedback": product_feedback,
        "top_responses": top_responses,
        "content_ideas": content_ideas,
        "limitations": [
            "P0/P1 are screened candidates, not confirmed high-value conversations or replies.",
            "Question-derived queries, use cases, and content topics are candidates; novelty, search demand, and outcomes are not inferred.",
            "Competitor issues, use cases, product feedback, replies, mentions, referrals, and conversions require explicit human review or measurement.",
            "Metric totals sum only supplied observations; missing measurements are not zero, and partial coverage is not a whole-week total.",
            "The report covers only supplied daily runs; screened-day count does not prove complete weekly coverage.",
            "This raw-content report is ephemeral; retain only make_daily_digest outputs for longer weekly trend analysis.",
            "This brief makes no posts or API calls. Keep approved Reddit-derived data private and follow the applicable retention/deletion rules.",
        ],
    }


def _generalized_label(
    value: Any, field: str, source_text: set[str] | None = None,
    forbidden_tokens: set[str] | None = None,
) -> str:
    """Accept a short human-created category, not a copied Reddit excerpt."""
    if (not isinstance(value, str) or len(value) > 80
            or any(unicodedata.category(char) in {"Cc", "Cf"} for char in value)):
        raise ValueError(f"{field} must be a short, single-line generalized label")
    label = " ".join(value.split())
    if not label or _REDDIT_REFERENCE.search(label) or (source_text and label.casefold() in source_text):
        raise ValueError(f"{field} looks like source text or contains a Reddit reference")
    if forbidden_tokens and any(
        token and re.search(rf"(?<!\w){re.escape(token)}(?!\w)", label, re.IGNORECASE)
        for token in forbidden_tokens
    ):
        raise ValueError(f"{field} contains a source identifier")
    return label


def _count_rows(rows: list[dict], field: str, *, count_field: str = "selection_count") -> list[dict]:
    totals: dict[str, dict] = {}
    for row in rows:
        label = row[field]
        key = label.casefold()
        if key not in totals:
            totals[key] = {field: label, count_field: 0}
        totals[key][count_field] += row[count_field]
    return sorted(totals.values(), key=lambda row: (-row[count_field], row[field].casefold()))


def make_daily_digest(run: dict, reviews: list[dict] | None = None) -> dict:
    """Return a retention-safe digest from one daily run.

    No post identifiers, URLs, titles, excerpts, drafts, usernames, or raw
    questions are copied into the result.  Textual insights are retained only
    from ``review.generalized_insights`` when the reviewer sets
    ``generalized_attested=True``.  For example, a human may add
    ``{"question_themes": ["Prototype iteration workflow"],
      "query_candidates": ["interactive prototype builder"]}``.
    This is an attestation, not an automatic paraphraser; operators must not
    paste source wording into generalized fields.
    """
    if not isinstance(run, dict):
        raise ValueError("run must be a daily run object")
    if reviews is None:
        reviews = []
    if not isinstance(reviews, list) or any(not isinstance(review, dict) for review in reviews):
        raise ValueError("reviews must be a list of objects")

    # The existing aggregation validates post IDs, review association, status,
    # and metrics.  Its raw-text result stays in memory and is never returned.
    stripped_reviews = [
        {key: review[key] for key in ("post_id", "status", "outcome_metrics", "response_metrics") if key in review}
        for review in reviews
    ]
    interim = aggregate_weekly([run], stripped_reviews)
    opportunities = run["opportunities"]
    source_by_id = {item["id"]: item for item in opportunities}
    generalized_rows: dict[str, list[dict]] = {field: [] for field in _GENERALIZED_FIELDS}
    for review in reviews:
        insights = review.get("generalized_insights")
        if insights is None:
            continue
        if review.get("generalized_attested") is not True or not isinstance(insights, dict):
            raise ValueError("generalized_insights requires a human generalized_attested=True")
        if set(insights) - set(_GENERALIZED_FIELDS):
            raise ValueError("generalized_insights contains unsupported fields")
        source = source_by_id[review["post_id"]]
        raw_text = {
            " ".join(source.get(field, "").split()).casefold()
            for field in ("title", "core_question") if isinstance(source.get(field), str)
        }
        forbidden_tokens = {str(source["id"])}
        if isinstance(source.get("author"), str) and source["author"]:
            forbidden_tokens.add(source["author"])
        for field, label_field in _GENERALIZED_FIELDS.items():
            labels = insights.get(field, [])
            if not isinstance(labels, list):
                raise ValueError(f"generalized_insights.{field} must be a list")
            for label in {_generalized_label(value, field, raw_text, forbidden_tokens) for value in labels}:
                generalized_rows[field].append({label_field: label, "selection_count": 1})

    # Only controlled, code-owned taxonomy labels survive the raw run. Unknown
    # labels are represented as a fixed category, never copied verbatim.
    selected: dict[str, dict] = {}
    for item in opportunities:
        post_id = item["id"]
        if post_id not in selected:
            selected[post_id] = item
    pains = []
    use_cases = []
    for item in selected.values():
        pain = item.get("pain_point")
        use_case = item.get("use_case")
        pains.append({"pain_point": pain if pain in PAIN_POINTS else "Other / unclassified", "selection_count": 1})
        if use_case in USE_CASES:
            use_cases.append({"use_case": use_case, "selection_count": 1})

    return {
        "schema": _DIGEST_SCHEMA,
        "source_type": ("synthetic" if str(run.get("source", "")).startswith("SYNTHETIC DEMO")
                        else "approved" if run.get("source") in _APPROVED_SOURCES else "unverified"),
        "window_start": interim["period_start"], "window_end": interim["period_end"],
        "screened_selections": interim["unique_discussions"],
        "screened_high_value_selections": interim["kpis"]["community"]["screened_high_value_discussions"],
        "pain_point_frequency": _count_rows(pains, "pain_point"),
        "use_case_frequency": _count_rows(use_cases, "use_case"),
        "question_themes": _count_rows(generalized_rows["question_themes"], "theme"),
        "new_query_candidates": _count_rows(generalized_rows["query_candidates"], "query"),
        "use_cases": _count_rows(generalized_rows["use_cases"], "use_case"),
        "competitor_pains": _count_rows(generalized_rows["competitor_pains"], "issue"),
        "product_feedback": _count_rows(generalized_rows["product_feedback"], "feedback"),
        "content_ideas": _count_rows(generalized_rows["content_ideas"], "working_topic"),
        "kpis": {
            "community": {field: interim["kpis"]["community"][field] for field in
                          ("confirmed_replies", "reply_interactions", "natural_mentions")},
            "growth": interim["kpis"]["growth"],
        },
        "top_responses": [
            {field: row[field] for field in ("score", "reply_count", "ranking_basis")}
            for row in interim["top_responses"]
        ],
    }


def _validated_digest(digest: dict) -> dict:
    """Rebuild from an exact schema so callers cannot smuggle raw text in."""
    expected = {
        "schema", "source_type", "window_start", "window_end", "screened_selections", "screened_high_value_selections",
        "pain_point_frequency", "use_case_frequency", "question_themes", "new_query_candidates",
        "use_cases", "competitor_pains", "product_feedback", "content_ideas", "kpis", "top_responses",
    }
    if not isinstance(digest, dict) or set(digest) != expected or digest.get("schema") != _DIGEST_SCHEMA:
        raise ValueError("digest must match the retention-safe daily schema exactly")
    if digest["source_type"] not in {"synthetic", "approved", "unverified"}:
        raise ValueError("digest source_type is invalid")
    start = _timestamp(digest["window_start"], "digest.window_start")
    end = _timestamp(digest["window_end"], "digest.window_end")
    if end <= start:
        raise ValueError("digest window_end must follow window_start")
    screened = _count(digest["screened_selections"], "screened_selections")
    high_value = _count(digest["screened_high_value_selections"], "screened_high_value_selections")
    if high_value > screened:
        raise ValueError("high-value selections cannot exceed all selections")
    clean = {"start": start, "end": end, "screened": screened, "high_value": high_value,
             "source_type": digest["source_type"]}
    row_fields = {
        "pain_point_frequency": "pain_point", "use_case_frequency": "use_case",
        "question_themes": "theme", "new_query_candidates": "query", "use_cases": "use_case",
        "competitor_pains": "issue", "product_feedback": "feedback", "content_ideas": "working_topic",
    }
    for name, field in row_fields.items():
        rows = digest[name]
        if not isinstance(rows, list):
            raise ValueError(f"digest.{name} must be a list")
        clean[name] = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {field, "selection_count"}:
                raise ValueError(f"digest.{name} row has unsupported fields")
            label = row[field]
            if name == "pain_point_frequency":
                if label not in set(PAIN_POINTS) | {"Other / unclassified"}:
                    raise ValueError("digest pain category is not controlled")
            elif name == "use_case_frequency":
                if label not in USE_CASES:
                    raise ValueError("digest use-case category is not controlled")
            else:
                label = _generalized_label(label, name)
            count = _count(row["selection_count"], "selection_count")
            if count == 0:
                raise ValueError("digest category counts must be positive")
            clean[name].append({field: label, "selection_count": count})
    if sum(row["selection_count"] for row in clean["pain_point_frequency"]) != screened:
        raise ValueError("digest pain category counts must equal screened selections")
    if sum(row["selection_count"] for row in clean["use_case_frequency"]) > screened:
        raise ValueError("digest use-case category counts exceed screened selections")
    kpis = digest["kpis"]
    if not isinstance(kpis, dict) or set(kpis) != {"community", "growth"}:
        raise ValueError("digest.kpis must contain community and growth")
    clean["kpis"] = {}
    for group, names in (
        ("community", ("confirmed_replies", "reply_interactions", "natural_mentions")),
        ("growth", ("reddit_referral_visits", "signups", "activations", "paid_customers")),
    ):
        data = kpis[group]
        if not isinstance(data, dict) or set(data) != set(names):
            raise ValueError(f"digest.kpis.{group} has unsupported fields")
        clean["kpis"][group] = {}
        for name in names:
            metric = data[name]
            if not isinstance(metric, dict) or set(metric) != {"value", "observed_records"}:
                raise ValueError(f"digest metric {name} must have value and observed_records")
            records = _count(metric["observed_records"], f"{name}.observed_records")
            if records > screened:
                raise ValueError(f"digest metric {name} has more records than selections")
            value = metric["value"]
            if (records == 0) != (value is None):
                raise ValueError(f"digest metric {name} has inconsistent coverage")
            clean["kpis"][group][name] = {
                "value": _count(value, name) if value is not None else None,
                "observed_records": records,
            }
    responses = digest["top_responses"]
    if not isinstance(responses, list):
        raise ValueError("digest.top_responses must be a list")
    clean["top_responses"] = []
    for row in responses:
        if not isinstance(row, dict) or set(row) != {"score", "reply_count", "ranking_basis"}:
            raise ValueError("digest response metric has unsupported fields")
        score = _count(row["score"], "response score", allow_negative=True) if row["score"] is not None else None
        replies = _count(row["reply_count"], "response reply_count") if row["reply_count"] is not None else None
        basis = "comment_score" if score is not None else "reply_count"
        if (score is None and replies is None) or row["ranking_basis"] != basis:
            raise ValueError("digest response metric has inconsistent ranking basis")
        clean["top_responses"].append({"score": score, "reply_count": replies, "ranking_basis": basis})
    return clean


def aggregate_weekly_digests(digests: list[dict], *, now: datetime | None = None) -> dict:
    """Build a weekly trend report without retaining the daily Reddit content."""
    if not isinstance(digests, list):
        raise ValueError("digests must be a list")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    clean = [_validated_digest(digest) for digest in digests]
    source_types = {item["source_type"] for item in clean}
    if len(source_types) > 1:
        raise ValueError("Weekly digests cannot mix synthetic, approved, and unverified sources")
    source_type = next(iter(source_types), "unverified")
    metrics = {}
    for group, names in (
        ("community", ("confirmed_replies", "reply_interactions", "natural_mentions")),
        ("growth", ("reddit_referral_visits", "signups", "activations", "paid_customers")),
    ):
        metrics[group] = {}
        for name in names:
            rows = [item["kpis"][group][name] for item in clean]
            records = sum(row["observed_records"] for row in rows)
            metrics[group][name] = {
                "value": sum(row["value"] for row in rows if row["value"] is not None) if records else None,
                "observed_records": records,
            }
    merged = {}
    for name, field in (
        ("pain_point_frequency", "pain_point"), ("use_case_frequency", "use_case"),
        ("question_themes", "theme"), ("new_query_candidates", "query"),
        ("use_cases", "use_case"), ("competitor_pains", "issue"),
        ("product_feedback", "feedback"), ("content_ideas", "working_topic"),
    ):
        rows = [row for item in clean for row in item[name]]
        merged[name] = [
            {field: row[field], "discussion_count": row["selection_count"]}
            for row in _count_rows(rows, field)
        ]
    for row in merged["new_query_candidates"]:
        row["origins"] = ["human_generalized"]
        row["validation_status"] = "unvalidated_candidate"
    for row in merged["content_ideas"]:
        row["basis"] = "human_generalized"
    responses = [row.copy() for item in clean for row in item["top_responses"]]
    responses.sort(key=lambda row: (
        row["score"] is None, -(row["score"] if row["score"] is not None else row["reply_count"])
    ))
    pains = merged["pain_point_frequency"]
    queries = merged["new_query_candidates"]
    use_cases = merged["use_cases"]
    competitors = merged["competitor_pains"]
    metrics["community"]["screened_high_value_selections"] = sum(item["high_value"] for item in clean)
    metrics["business"] = {
        "query_candidates": len(queries), "use_cases": len(use_cases),
        "use_case_categories": len(merged["use_case_frequency"]),
        "pain_points": len(pains), "competitor_issues": len(competitors),
    }
    return {
        "report_mode": "retention_safe_digest",
        "source_type": source_type,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "period_start": min((item["start"] for item in clean), default=None).isoformat() if clean else None,
        "period_end": max((item["end"] for item in clean), default=None).isoformat() if clean else None,
        "run_count": len(clean), "screened_days": len({item["end"].date() for item in clean}),
        "daily_selections": sum(item["screened"] for item in clean),
        "unique_discussions": None, "duplicate_selections": None,
        "kpis": metrics,
        "pain_point_frequency": pains, "use_case_frequency": merged["use_case_frequency"],
        "question_themes": merged["question_themes"], "frequent_user_questions": [],
        "new_query_candidates": queries, "use_cases": use_cases,
        "competitor_pains": competitors, "product_feedback": merged["product_feedback"],
        "top_responses": responses[:5], "content_ideas": merged["content_ideas"],
        "limitations": [
            *( ["This entire report contains synthetic examples, not real Reddit activity."] if source_type == "synthetic"
               else ["Source is unverified; this report is not evidence of approved Reddit monitoring."] if source_type == "unverified"
               else [] ),
            "This report uses only content-free daily digests; it has no post IDs, URLs, titles, quotes, or usernames.",
            "Daily selections may include the same discussion on multiple days; unique weekly discussions cannot be recovered from digests.",
            "Pain and use-case categories are screening signals. Textual themes and ideas require human generalization and are not verified as new or in-demand.",
            "Only explicitly supplied outcome measurements are summed. Missing coverage is not zero; observations may overlap across days, so sums are not deduplicated weekly totals.",
            "Response metrics are anonymous and may repeat across days; score and reply count are not comparable ranking measures.",
        ],
    }


def render_weekly_markdown(report: dict) -> str:
    """Render a compact, escaped weekly brief for private human review."""
    if not isinstance(report, dict) or not isinstance(report.get("kpis"), dict):
        raise ValueError("report must be an aggregate_weekly result")

    def metric(value: dict) -> str:
        return "Not measured" if value["value"] is None else f"{value['value']} (from {value['observed_records']} recorded review(s))"

    community = report["kpis"]["community"]
    growth = report["kpis"]["growth"]
    business = report["kpis"]["business"]
    digest_mode = report.get("report_mode") == "retention_safe_digest"
    volume = (f"daily selections: {report['daily_selections']} (may include repeats)" if digest_mode
              else f"unique screened discussions: {report['unique_discussions']}")
    high_value = (community["screened_high_value_selections"] if digest_mode
                  else community["screened_high_value_discussions"])
    lines = [
        ("# Weekly Community Insights — SYNTHETIC DEMO" if report.get("source_type") == "synthetic"
         else "# Weekly Community Insights — UNVERIFIED INPUT" if report.get("source_type") == "unverified"
         else "# Weekly Reddit Community Insights"), "",
        f"Period: {_md(report.get('period_start') or 'Not available')} to {_md(report.get('period_end') or 'Not available')}",
        f"Daily runs: {report['run_count']} across {report['screened_days']} day(s); {volume}",
        "", "## KPIs", "", "Community (screening and measured activity):",
        f"- P0/P1 screened {'daily selections' if digest_mode else 'discussion candidates'}: {high_value}",
        f"- Human-confirmed replies: {metric(community['confirmed_replies'])}",
        f"- Reply interactions: {metric(community['reply_interactions'])}",
        f"- Natural mentions: {metric(community['natural_mentions'])}",
        "", "Growth (measured, attributed outcomes only):",
        f"- Reddit referral visits: {metric(growth['reddit_referral_visits'])}",
        f"- Signups: {metric(growth['signups'])}",
        f"- Activations: {metric(growth['activations'])}",
        f"- Paid customers: {metric(growth['paid_customers'])}",
        "", "Business insight candidates:",
        f"- Query candidates: {business['query_candidates']}; human-noted use-case candidates: {business['use_cases']}; "
        f"screened use-case categories: {business.get('use_case_categories', 0)}; "
        f"pain categories: {business['pain_points']}; competitor issues: {business['competitor_issues']}",
    ]

    def section(title: str, rows: list[dict], field: str, empty: str) -> None:
        lines.extend(["", f"## {title}", ""])
        if not rows:
            lines.append(empty)
            return
        for row in rows:
            unit = "daily selection(s)" if digest_mode else "screened discussion(s)"
            lines.append(f"- {_md(row[field])} — {row['discussion_count']} {unit}")

    if digest_mode:
        section("Human-generalized question themes", report["question_themes"], "theme", "No generalized question themes recorded.")
    else:
        section("Frequent user questions", report["frequent_user_questions"], "question", "No explicit thread questions in the supplied screens.")
    section("Pain-point frequency", report["pain_point_frequency"], "pain_point", "No pain categories in the supplied screens.")
    section("Use-case frequency", report.get("use_case_frequency", []), "use_case", "No use-case categories in the supplied screens.")
    section("Human-generalized query candidates" if digest_mode else "New query candidates", report["new_query_candidates"], "query", "No query candidates recorded. Newness and demand have not been checked.")
    section("New use cases", report["use_cases"], "use_case", "Not recorded in human review.")
    section("Competitor pain points", report["competitor_pains"], "issue", "Not recorded in human review.")
    section("Product feedback", report["product_feedback"], "feedback", "Not recorded in human review.")
    lines.extend(["", "## Best-performing measured responses", ""])
    if not report["top_responses"]:
        lines.append("Not measured; no response engagement observations were supplied.")
    for row in report["top_responses"]:
        score = "Not measured" if row["score"] is None else str(row["score"])
        replies = "Not measured" if row["reply_count"] is None else str(row["reply_count"])
        if digest_mode:
            lines.append(f"- Anonymous measured response: comment score {score}; replies {replies} "
                         f"(ranked by {_md(row['ranking_basis'])}).")
        else:
            link = f" [View response]({row['response_permalink']})" if row["response_permalink"] else ""
            lines.append(f"- Thread {_md(row['post_id'])}: comment score {score}; replies {replies} "
                         f"(ranked by {_md(row['ranking_basis'])}).{link}")
    if report["top_responses"]:
        lines.append("Scores and reply counts are separate measures; entries without a score are ranked by reply count only.")
    section("Content worth making (editorial candidates)", report["content_ideas"], "working_topic", "No content candidates from supplied screens.")
    lines.extend(["", "## Measurement and safety notes", ""])
    lines.extend(f"- {_md(note)}" for note in report["limitations"])
    return "\n".join(lines).rstrip() + "\n"
