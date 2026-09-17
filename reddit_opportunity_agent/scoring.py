"""Deterministic, explainable screening of approved Reddit data."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse


ICP_TERMS = {
    "PM": ("product manager", "product management", " pm ", "prd", "product requirement"),
    "Designer": ("designer", "ux design", "ui design", "figma", "design workflow"),
    "Founder": ("founder", "startup", "cofounder", "co-founder", "founding", "my mvp"),
}

PAINS = {
    "Prototype": ("prototype", "prototyping", "wireframe", "mockup", "interactive demo"),
    "Landing Page": ("landing page", "landing pages", "website builder", "build a website"),
    "MVP": (" mvp", "minimum viable product", "ship faster", "validate idea"),
    "Product Workflow": ("product workflow", "prd", "requirement", "ai for pm", "handoff"),
    "AI Design": ("ai design", "design agent", "figma alternative", "ui generator", "ux designer"),
}

QUESTION_TERMS = (
    "?", "how do", "how can", "what tool", "which tool", "any tools", "recommend", "alternative", "looking for", "need help", "struggling", "best ai", "anyone use"
)


def _text(value: Any, limit: int = 4000) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\x00-\x1f\x7f]+", " ", value).strip()[:limit]


def _normalized(value: str) -> str:
    return " " + re.sub(r"\s+", " ", value.casefold()) + " "


def _safe_permalink(value: str) -> str:
    value = _text(value, 500)
    if value.startswith("/") and not value.startswith("//"):
        value = "https://www.reddit.com" + value
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {"reddit.com", "www.reddit.com", "old.reddit.com"}:
        return ""
    return value


def _utc(value: Any) -> datetime | None:
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, timezone.utc)
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (OverflowError, ValueError, TypeError):
        pass
    return None


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (ValueError, TypeError):
        return 0


def _policy(subreddit: str, config: dict, now: datetime) -> tuple[str, list[str]]:
    row = (config.get("promotion_policies") or {}).get(subreddit, {})
    if not isinstance(row, dict):
        return "unknown", ["Subreddit product/link policy is unverified."]
    status = row.get("status", "unknown")
    if status == "prohibited":
        return "prohibited", ["Moderator/community policy marked promotion prohibited."]
    if status != "may_mention":
        return "unknown", ["Subreddit product/link policy is unverified."]
    checked = _utc(row.get("checked_at"))
    evidence = _safe_permalink(row.get("evidence_url", ""))
    # Rule pages often use reddit.com/r/.../about/rules; a missing/freshness gap is never an allow.
    if not checked or checked > now or now - checked > timedelta(days=30) or not evidence:
        return "unknown", ["Product-mention policy evidence is missing or older than 30 days."]
    return "may_mention", [f"Human-recorded community-rule evidence: {evidence}"]


def _draft(pain: str, question: str, action: str, brand: str, facts: list[str]) -> str:
    if pain == "Prototype":
        practical = "I would make one representative flow clickable first, then test where people hesitate before polishing the whole UI."
    elif pain == "Landing Page":
        practical = "I would start with one audience and one clear conversion goal, publish the smallest page, then test the message before adding sections."
    elif pain == "MVP":
        practical = "I would narrow the MVP to the single assumption you need to validate and build just enough of the flow to get real feedback."
    elif pain == "AI Design":
        practical = "I would compare tools on editability and how quickly a team can review a realistic flow, not only on first-pass visuals."
    else:
        practical = "I would write down the key user decision, then turn the requirements into a reviewable flow before expanding scope."
    if action == "research_only":
        return ""
    draft = f"{practical} What constraint matters most for your case—speed, editability, or collaboration?"
    if action == "comment_with_disclosure":
        draft += f" Disclosure: I work on {brand}. {facts[0]} If that sounds relevant, I can share how we approach it; no link unless the moderators allow it."
    return draft


def evaluate_posts(posts: list[dict], config: dict, *, now: datetime, source: str) -> dict:
    """Select at most `max_opportunities` fresh posts; never infer promotion permission."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(timezone.utc)
    if not isinstance(posts, list) or not isinstance(config, dict):
        raise ValueError("posts must be a list and config must be an object")
    targets = {str(x).removeprefix("r/").casefold() for x in config.get("target_subreddits", []) if isinstance(x, str)}
    if not targets:
        raise ValueError("target_subreddits is required")
    max_out = min(20, max(1, _int(config.get("max_opportunities", 8))))
    facts = [_text(x, 240) for x in config.get("verified_product_facts", []) if _text(x, 240)]
    brand = _text(config.get("brand", "OJO"), 60) or "OJO"
    seen: set[str] = set()
    candidates = []
    counters = {"input": len(posts), "outside_window": 0, "excluded": 0, "no_match": 0, "deduplicated": 0}
    for post in posts[:5000]:
        if not isinstance(post, dict):
            counters["excluded"] += 1
            continue
        subreddit = _text(post.get("subreddit"), 80).removeprefix("r/")
        created = _utc(post.get("created_utc", post.get("created_at")))
        if not created or created < now - timedelta(hours=24) or created > now + timedelta(minutes=5):
            counters["outside_window"] += 1
            continue
        if subreddit.casefold() not in targets or post.get("locked") or post.get("stickied") or post.get("over_18") or post.get("removed_by_category") or post.get("deleted"):
            counters["excluded"] += 1
            continue
        title = _text(post.get("title"), 300)
        body = _text(post.get("selftext"), 1800)
        if not title or body in {"[removed]", "[deleted]"}:
            counters["excluded"] += 1
            continue
        permalink = _safe_permalink(post.get("permalink", ""))
        pid = _text(post.get("id"), 50)
        if not pid or not permalink or not re.fullmatch(r"[A-Za-z0-9_]+", pid):
            counters["excluded"] += 1
            continue
        if pid in seen:
            counters["deduplicated"] += 1
            continue
        seen.add(pid)
        corpus = _normalized(title + " " + body)
        matches = [(pain, [term for term in terms if term in corpus]) for pain, terms in PAINS.items()]
        matches = [(pain, terms) for pain, terms in matches if terms]
        if not matches:
            counters["no_match"] += 1
            continue
        pain, pain_terms = max(matches, key=lambda item: len(item[1]))
        roles = [(role, [term for term in terms if term in corpus]) for role, terms in ICP_TERMS.items()]
        roles = [(role, terms) for role, terms in roles if terms]
        role, role_terms = max(roles, key=lambda item: len(item[1])) if roles else ("Unclear", [])
        icp_score = min(25, (17 if role_terms else 5) + min(8, 4 * max(0, len(role_terms) - 1)))
        question = any(term in corpus for term in QUESTION_TERMS)
        pain_score = min(35, 17 + 5 * min(2, len(pain_terms)) + (8 if question else 0))
        age_hours = (now - created).total_seconds() / 3600
        recency = 14 if age_hours <= 3 else 11 if age_hours <= 8 else 8 if age_hours <= 16 else 5
        comments = _int(post.get("num_comments"))
        interaction = 8 if 2 <= comments <= 30 else 4 if comments == 1 or 31 <= comments <= 80 else 1 if comments > 80 else 0
        discussion_score = min(25, recency + interaction + (3 if _int(post.get("score")) >= 2 else 0))
        policy, policy_evidence = _policy(subreddit, config, now)
        can_mention = policy == "may_mention" and bool(facts) and question and role != "Unclear"
        promotion_score = 15 if can_mention else 6 if policy == "may_mention" else 2 if policy == "unknown" else 0
        total = icp_score + pain_score + discussion_score + promotion_score
        if total >= 75 and icp_score >= 17 and pain_score >= 27 and can_mention:
            priority, action = "P0", "comment_with_disclosure"
        elif total >= 55 and pain_score >= 27:
            priority, action = "P1", "answer_only"
        else:
            priority, action = "P2", "research_only"
        flags = []
        if policy != "may_mention":
            flags.append("No product mention or link until current subreddit rules and moderator guidance are confirmed.")
        if not facts:
            flags.append("No verified OJO product facts supplied; product mention disabled.")
        if role == "Unclear":
            flags.append("ICP inferred from topic only; verify before engaging.")
        if not question:
            flags.append("Post does not clearly ask for a recommendation; avoid pitching.")
        summary = title
        core_question = title if question else f"Discussion of {pain.lower()}; confirm the actual question in the thread."
        candidates.append({
            "id": pid, "subreddit": subreddit, "title": title, "permalink": permalink,
            "created_at": created.isoformat(), "score": total, "priority": priority,
            "score_breakdown": {"icp": icp_score, "pain": pain_score, "discussion": discussion_score, "promotion": promotion_score},
            "icp": role, "pain_point": pain, "fit_reason": f"Matched {pain.lower()} terms: {', '.join(pain_terms[:3])}.",
            "promotion_risk": policy, "product_mention_allowed": can_mention, "action": action,
            "summary": summary, "core_question": core_question,
            "reply_angle": "Lead with a concrete, helpful workflow; disclose affiliation if mentioning the product." if can_mention else "Answer the specific question with practical guidance; do not mention OJO or link.",
            "comment_draft": _draft(pain, core_question, action, brand, facts),
            "evidence": [f"Post age: {age_hours:.1f}h; comments: {comments}; score: {_int(post.get('score'))}.", f"ICP signals: {', '.join(role_terms) or 'none explicit'}.", *policy_evidence],
            "flags": flags,
        })
    candidates.sort(key=lambda row: ({"P0": 0, "P1": 1, "P2": 2}[row["priority"]], -row["score"], row["created_at"]))
    selected = candidates[:max_out]
    return {
        "generated_at": now.isoformat(), "window_start": (now - timedelta(hours=24)).isoformat(), "window_end": now.isoformat(),
        "source": source, "opportunities": selected, "counts": {**counters, "matched": len(candidates), "selected": len(selected)},
        "limitations": ["Drafts are suggestions only; a human must read the full thread and current community rules before commenting.", "No comments, posts, votes, or messages are sent by this tool.", "Promotion permission is never inferred from the absence of a prohibition."],
    }
