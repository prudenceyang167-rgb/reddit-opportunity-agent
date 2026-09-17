"""Deterministic, explainable screening of approved Reddit data."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse


ICP_TERMS = {
    "PM": ("product manager", "product management", "pm"),
    "Designer": ("designer", "ux researcher"),
    "Founder": ("founder", "startup founder", "cofounder", "co-founder", "founding", "solo founder"),
}

# Use cases describe the job to be done; pain points describe what is going wrong.
# Both are drawn from the first-stage strategy, and neither implies product fit
# or permission to mention OJO without a human reviewing the whole thread.
USE_CASES = {
    "Prototype": ("prototype", "prototyping", "wireframe", "mockup", "interactive demo"),
    "Landing Page": ("landing page", "landing pages", "website builder", "build a website"),
    "MVP": ("mvp", "minimum viable product", "validate idea", "product validation"),
    "Product Workflow": ("product workflow", "prd", "product requirement", "handoff", "ai for pm"),
    "Design Review": ("design review", "design critique", "landing page review", "ui hierarchy", "visual hierarchy"),
    "Website Redesign": ("website redesign", "redesign my website", "redesign our website"),
    "AI Design": ("ai design", "design agent", "figma alternative", "ui generator", "ai-generated ui"),
}

# Kept for integrations that imported the former topic taxonomy by name.
PAINS = USE_CASES

PAIN_POINTS = {
    "Generic UI": ("generic ui", "generic design", "looks generic", "feel generic", "all look the same", "samey", "cookie cutter"),
    "Hard to Iterate": ("hard to edit", "difficult to edit", "can't edit", "cannot edit", "hard to change", "difficult to change", "keep modifying", "hard to iterate"),
    "Unstable Design Quality": ("inconsistent design", "inconsistent quality", "poor design quality", "bad design quality", "ugly design", "looks bad"),
    "Missing Product Context": ("lacks context", "missing context", "product context", "doesn't understand the product", "doesn't understand my product"),
    "No Design Resources": ("no designer", "without a designer", "can't design", "not a designer", "no design team"),
    "MVP Scope": ("too many screens", "feature creep", "scope the mvp", "what to build first", "minimum scope"),
    "Conversion Clarity": ("value proposition", "weak cta", "unclear cta", "information hierarchy", "not converting", "low conversion"),
}

COMPETITORS = {
    "Figma Make": r"\bfigma\s+make\b",
    "Lovable": r"\blovable\b",
    "Stitch": r"\bstitch\b",
    "v0": r"\bv0\b",
    "Replit": r"\breplit\b",
}

TOOL_INTENT = ("what tool", "which tool", "any tools", "best tool", "best ai tool", "recommend a tool", "recommend tools", "tool recommendation", "alternative to", "alternatives to", "looking for a tool", "should i use")
WORKFLOW_INTENT = ("how do", "how can", "how to", "what workflow", "which workflow", "steps to")
SOLUTION_INTENT = ("need help", "struggling with", "how to fix", "how can i fix", "what would you do", "solution for", "looking for a solution")
FEEDBACK_INTENT = ("feedback on", "review my", "critique my", "what's wrong with", "what is wrong with")


def _text(value: Any, limit: int = 4000) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\x00-\x1f\x7f]+", " ", value).strip()[:limit]


def _normalized(value: str) -> str:
    return " " + re.sub(r"\s+", " ", value.casefold().replace("’", "'")) + " "


def _safe_permalink(value: str) -> str:
    value = _text(value, 500)
    if value.startswith("/") and not value.startswith("//"):
        value = "https://www.reddit.com" + value
    try:
        parsed = urlparse(value)
        safe_host = parsed.hostname in {"reddit.com", "www.reddit.com", "old.reddit.com"}
    except ValueError:
        return ""
    if parsed.scheme != "https" or not safe_host:
        return ""
    return value


def _rules_evidence_url(value: Any, subreddit: str) -> str:
    """Accept only the target community’s moderator-controlled rules page."""
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return ""
    if parsed.scheme != "https" or parsed.netloc.lower() not in {"reddit.com", "www.reddit.com", "old.reddit.com"}:
        return ""
    match = re.fullmatch(r"/r/([A-Za-z0-9_]{1,21})/about/rules/?", parsed.path, re.IGNORECASE)
    if not match or match.group(1).casefold() != subreddit.casefold():
        return ""
    return f"https://www.reddit.com/r/{match.group(1)}/about/rules"


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


def _matches(corpus: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if
            (re.search(rf"\b{re.escape(term)}\b", corpus) if term in {"mvp", "pm", "prd"}
             else term in corpus)]


def _primary_match(corpus: str, taxonomy: dict[str, tuple[str, ...]], fallback: str) -> tuple[str, list[str]]:
    matches = [(label, _matches(corpus, terms)) for label, terms in taxonomy.items()]
    matches = [(label, terms) for label, terms in matches if terms]
    return max(matches, key=lambda item: len(item[1])) if matches else (fallback, [])


def _intent(corpus: str) -> str:
    # A question mark alone is not a request for a tool or an invitation to pitch.
    if _matches(corpus, TOOL_INTENT):
        return "tool_selection"
    if _matches(corpus, WORKFLOW_INTENT):
        return "workflow_help"
    if _matches(corpus, SOLUTION_INTENT):
        return "solution_request"
    if _matches(corpus, FEEDBACK_INTENT):
        return "feedback_request"
    return "general_discussion"


def _competitors(corpus: str, subreddit: str) -> list[str]:
    names = [name for name, pattern in COMPETITORS.items() if re.search(pattern, corpus)]
    if subreddit.casefold() == "lovable" and "Lovable" not in names:
        names.insert(0, "Lovable")
    return names


def _explicit_persona(corpus: str, role: str) -> bool:
    names = {"PM": r"(?:product manager|pm)", "Designer": r"(?:product|ux|ui)?\s*designer",
             "Founder": r"(?:solo\s+)?(?:co-?)?founder"}
    name = names.get(role)
    return bool(name and re.search(
        rf"\b(?:i(?:'m| am)|as an?|we(?:'re| are)|i work as an?)\s+(?:an?\s+)?{name}\b", corpus
    ))


def _policy_row(subreddit: str, config: dict) -> dict:
    policies = config.get("promotion_policies") or {}
    if not isinstance(policies, dict):
        return {}
    matching = [value for key, value in policies.items()
                if isinstance(key, str) and key.casefold() == subreddit.casefold()]
    # Case-variant duplicate records are ambiguous; neither may authorize promotion.
    row = matching[0] if len(matching) == 1 else {}
    return row if isinstance(row, dict) else {}


def _policy(subreddit: str, config: dict, now: datetime) -> tuple[str, list[str]]:
    row = _policy_row(subreddit, config)
    if not row:
        return "unknown", ["Subreddit product/link policy is unverified."]
    if row.get("self_promo") == "prohibited" or row.get("self_promo") == "not_allowed" or row.get("self_promo") is False:
        return "prohibited", ["Recorded community self-promotion rule prohibits product mentions."]
    status = row.get("status", "unknown")
    if status == "prohibited":
        return "prohibited", ["Moderator/community policy marked promotion prohibited."]
    if status != "may_mention":
        return "unknown", ["Subreddit product/link policy is unverified."]
    # Legacy configs can explicitly record a human-reviewed status. A new
    # checklist cannot authorize a mention while promotion or account
    # eligibility is ambiguous. Thresholds need separate operator verification;
    # only an explicit "not_required" can clear them here.
    unresolved = []
    if "self_promo" in row and row["self_promo"] not in ("allowed", "conditional"):
        unresolved.append("self_promo")
    for name in ("account_age", "karma"):
        if name in row and row[name] != "not_required":
            unresolved.append(name)
    if unresolved:
        return "unknown", ["Community rule checklist is unresolved: " + ", ".join(unresolved) + "."]
    checked = _utc(row.get("checked_at"))
    evidence = _rules_evidence_url(row.get("evidence_url", ""), subreddit)
    # A different community or an arbitrary Reddit post cannot establish the local rules.
    if not checked or checked > now or now - checked > timedelta(days=30) or not evidence:
        return "unknown", ["Product-mention policy evidence is missing, mismatched, or older than 30 days."]
    return "may_mention", [f"Human-recorded community-rule evidence: {evidence}"]


def _draft(use_case: str, action: str, brand: str, facts: list[str]) -> str:
    if use_case == "Prototype":
        practical = "I would make one representative flow clickable first, then test where people hesitate before polishing the whole UI."
    elif use_case == "Landing Page":
        practical = "I would start with one audience and one clear conversion goal, publish the smallest page, then test the message before adding sections."
    elif use_case == "MVP":
        practical = "I would narrow the MVP to the single assumption you need to validate and build just enough of the flow to get real feedback."
    elif use_case in {"Design Review", "Website Redesign"}:
        practical = "I would check the value proposition, visual hierarchy and CTA first, then revise the weakest section instead of regenerating the entire page."
    elif use_case == "AI Design":
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
    if len(posts) > 5000:
        raise ValueError("Input has more than 5,000 posts; split the approved export rather than silently truncating it.")
    targets = {str(x).removeprefix("r/").casefold() for x in config.get("target_subreddits", []) if isinstance(x, str)}
    if not targets:
        raise ValueError("target_subreddits is required")
    max_out = min(20, max(1, _int(config.get("max_opportunities", 8))))
    raw_facts = config.get("verified_product_facts", [])
    if not isinstance(raw_facts, list) or any(not isinstance(fact, str) or not _text(fact, 240) for fact in raw_facts):
        raise ValueError("verified_product_facts must be a list of nonempty strings.")
    facts = [_text(fact, 240) for fact in raw_facts]
    brand = _text(config.get("brand", "OJO"), 60) or "OJO"
    seen: set[str] = set()
    candidates = []
    counters = {"input": len(posts), "outside_window": 0, "excluded": 0, "no_match": 0, "deduplicated": 0}
    for post in posts:
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
        use_case, use_terms = _primary_match(corpus, USE_CASES, "Unclear")
        pain, pain_terms = _primary_match(corpus, PAIN_POINTS, "Not stated")
        competitor_names = _competitors(corpus, subreddit)
        if use_case == "Unclear" and competitor_names and pain_terms:
            use_case, use_terms = "AI Design", competitor_names[:1]
        if use_case == "Unclear":
            counters["no_match"] += 1
            continue
        explicit_roles = [name for name in ICP_TERMS if _explicit_persona(corpus, name)]
        if len(explicit_roles) == 1:
            role = explicit_roles[0]
            role_terms = _matches(corpus, ICP_TERMS[role])
            persona_explicit = True
        else:
            role, role_terms = _primary_match(corpus, ICP_TERMS, "Unclear")
            persona_explicit = len(explicit_roles) > 1 and role in explicit_roles
        intent = _intent(corpus)
        icp_score = min(25, (17 if role_terms else 5) + min(8, 4 * max(0, len(role_terms) - 1)))
        actionable = intent in {"tool_selection", "workflow_help", "solution_request"}
        pain_score = min(35, 17 + 5 * min(2, len(use_terms)) + (8 if actionable else 0)
                         + (3 if pain_terms else 0))
        age_hours = (now - created).total_seconds() / 3600
        recency = 14 if age_hours <= 3 else 11 if age_hours <= 8 else 8 if age_hours <= 16 else 5
        comments = _int(post.get("num_comments"))
        interaction = 8 if 2 <= comments <= 30 else 4 if comments == 1 or 31 <= comments <= 80 else 1 if comments > 80 else 0
        discussion_score = min(25, recency + interaction + (3 if _int(post.get("score")) >= 2 else 0))
        policy, policy_evidence = _policy(subreddit, config, now)
        can_mention = policy == "may_mention" and bool(facts) and actionable and persona_explicit
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
        elif not persona_explicit:
            flags.append("Persona is topic-inferred rather than self-identified; verify before mentioning a product.")
        if not actionable:
            flags.append("Post does not clearly ask for a tool, workflow, or solution; avoid pitching.")
        if pain == "Not stated":
            flags.append("Specific pain point is not explicit; confirm it in the full thread.")
        policy_row = _policy_row(subreddit, config)
        link_allowed = bool(can_mention and policy_row.get("product_link") == "allowed"
                            and intent == "tool_selection")
        summary = title
        core_question = title if actionable or "?" in corpus else f"Discussion of {use_case.lower()}; confirm the actual question in the thread."
        candidates.append({
            "id": pid, "subreddit": subreddit, "title": title, "permalink": permalink,
            "created_at": created.isoformat(), "score": total, "priority": priority,
            "score_breakdown": {"icp": icp_score, "pain": pain_score, "discussion": discussion_score, "promotion": promotion_score},
            "icp": role, "persona": role,
            "persona_confidence": "explicit" if persona_explicit else "inferred" if role != "Unclear" else "unclear",
            "use_case": use_case, "pain_point": pain,
            "competitor": competitor_names[0] if competitor_names else None,
            "competitors": competitor_names, "intent": intent,
            "fit_reason": f"Matched {use_case.lower()} terms: {', '.join(use_terms[:3])}."
                          + (f" Specific pain signal: {', '.join(pain_terms[:2])}." if pain_terms else ""),
            "promotion_risk": policy,
            "promotion_risk_level": "conditional" if policy == "may_mention" else "high" if policy == "prohibited" else "unknown",
            "product_mention_allowed": can_mention, "product_link_allowed": link_allowed, "action": action,
            "summary": summary, "core_question": core_question,
            "reply_angle": "Lead with a concrete, helpful workflow; disclose affiliation if mentioning the product." if can_mention else "Answer the specific question with practical guidance; do not mention OJO or link.",
            "comment_draft": _draft(use_case, action, brand, facts),
            "evidence": [f"Post age: {age_hours:.1f}h; comments: {comments}; score: {_int(post.get('score'))}.",
                         f"Persona signals: {', '.join(role_terms) or 'none explicit'}.",
                         f"Use-case signals: {', '.join(use_terms)}.",
                         f"Pain signals: {', '.join(pain_terms) or 'none explicit'}.",
                         f"Competitor signals: {', '.join(competitor_names) or 'none explicit'}.",
                         f"Intent: {intent}.", *policy_evidence],
            "flags": flags,
        })
    candidates.sort(key=lambda row: ({"P0": 0, "P1": 1, "P2": 2}[row["priority"]], -row["score"], row["created_at"]))
    selected = candidates[:max_out]
    return {
        "generated_at": now.isoformat(), "window_start": (now - timedelta(hours=24)).isoformat(), "window_end": now.isoformat(),
        "source": source, "opportunities": selected, "counts": {**counters, "matched": len(candidates), "selected": len(selected)},
        "limitations": ["Drafts are suggestions only; a human must read the full thread and current community rules before commenting.", "No comments, posts, votes, or messages are sent by this tool.", "Promotion permission is never inferred from the absence of a prohibition."],
    }
