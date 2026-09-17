"""Human-reviewable exports for Reddit opportunities.

Reddit titles, bodies and URLs are untrusted input.  These renderers do not
publish comments or turn an unverified URL into a clickable report link.
"""

from __future__ import annotations

import csv
import html
import io
import re
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote, urlsplit


_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+.!|>~-])")
_REDDIT_POST = re.compile(
    r"/r/[A-Za-z0-9_]+/comments/[A-Za-z0-9]+(?:/[^?#]*)?/?\Z"
)
_REDDIT_SHORT = re.compile(r"/[A-Za-z0-9]+/?\Z")
_COLUMNS = (
    "generated_at", "window_start", "window_end", "source", "id",
    "priority", "subreddit", "title", "permalink", "created_at",
    "score", "icp", "pain_point", "fit_reason", "promotion_risk",
    "product_mention_allowed", "action", "summary", "core_question",
    "reply_angle", "comment_draft", "evidence", "flags", "qa_summary",
    "limitations", "posting_status",
)
_LIMITATIONS = (
    "Scores and promotion-risk assessments are recommendations, not verified permissions. "
    "Open the live thread, check current subreddit rules and product claims, "
    "then edit and approve any reply manually."
)


def _plain(value: object) -> str:
    """Keep one Reddit-supplied value on one report line."""
    return " ".join(str(value if value is not None else "").split())


def _md(value: object) -> str:
    # HTML escaping prevents raw tags; Markdown escaping prevents headings,
    # tables, inline links, images and formatting from forged post text.
    return _MARKDOWN_SPECIAL.sub(r"\\\1", html.escape(_plain(value), quote=True))


def _reddit_url(value: object) -> str:
    """Return only a normalized HTTPS Reddit post URL, or no URL."""
    raw = str(value if value is not None else "").strip()
    try:
        parts = urlsplit(raw)
        if parts.scheme:
            if parts.scheme.lower() != "https" or parts.username or parts.password:
                return ""
            host = (parts.hostname or "").lower()
            if host not in {"reddit.com", "www.reddit.com", "old.reddit.com", "redd.it"}:
                return ""
        elif raw.startswith("/r/"):
            host = "www.reddit.com"
        else:
            return ""

        # Discard queries/fragments, which Reddit permalinks do not need and
        # which could contain tracking or misleading Markdown punctuation.
        path = unquote(parts.path)
        if host == "redd.it":
            if not _REDDIT_SHORT.fullmatch(path):
                return ""
            return "https://redd.it" + quote(path, safe="/-._~")
        if not _REDDIT_POST.fullmatch(path):
            return ""
        return "https://www.reddit.com" + quote(path, safe="/-._~")
    except (ValueError, UnicodeError):
        return ""


def _safe_priority(value: object) -> str:
    return value if isinstance(value, str) and value in {"P0", "P1", "P2"} else "Unclassified"


def _score(value: object) -> str:
    return str(value) if isinstance(value, int) and not isinstance(value, bool) else "—"


def _items(value: object) -> list[str]:
    return [str(item) for item in value if item is not None] if isinstance(value, list) else []


def _opportunities(run: dict) -> list[dict]:
    items = run.get("opportunities", [])
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError("opportunities must be a list of objects")
    return items


def render_markdown(run: dict) -> str:
    """Render a daily opportunity list for human review, never for auto-posting."""
    opportunities = _opportunities(run)
    counts = Counter(_safe_priority(item.get("priority")) for item in opportunities)
    flagged = sum(bool(_items(item.get("flags"))) for item in opportunities)
    lines = [
        "# Reddit Opportunity List",
        "",
        f"Generated: {_md(run.get('generated_at'))}  ",
        f"Window: {_md(run.get('window_start'))} to {_md(run.get('window_end'))}  ",
        f"Source: {_md(run.get('source'))}",
        "",
        "**Drafts only — no comment has been posted automatically.**",
        "",
        "## QA and limitations",
        "",
        (f"{len(opportunities)} opportunities: P0 {counts['P0']}, P1 {counts['P1']}, "
         f"P2 {counts['P2']}; {flagged} with review flags."),
        _LIMITATIONS,
        "",
        "| Priority | Thread | ICP | Score | Product mention | Action |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]

    for item in opportunities:
        url = _reddit_url(item.get("permalink"))
        title = _md(item.get("title")) or "Untitled thread"
        thread = f"[{title}]({url})" if url else title
        mention = "Potentially, verify rules" if item.get("product_mention_allowed") is True else "No / unknown"
        lines.append(
            f"| {_safe_priority(item.get('priority'))} | {thread} | {_md(item.get('icp'))} "
            f"| {_score(item.get('score'))} | {mention} | {_md(item.get('action'))} |"
        )

    if not opportunities:
        lines.extend(["", "No opportunities matched this run's filters."])

    for index, item in enumerate(opportunities, start=1):
        title = _md(item.get("title")) or "Untitled thread"
        url = _reddit_url(item.get("permalink"))
        lines.extend([
            "",
            f"## {index}. {_safe_priority(item.get('priority'))} — {title}",
            "",
            f"Thread: {url if url else 'URL omitted (not a valid Reddit post URL)'}  ",
            f"Reddit ID: {_md(item.get('id'))}  ",
            f"Subreddit: {_md(item.get('subreddit'))}  ",
            f"Posted: {_md(item.get('created_at'))}  ",
            f"Score: {_score(item.get('score'))}  ",
            f"ICP: {_md(item.get('persona', item.get('icp')))}  ",
            f"Use case: {_md(item.get('use_case'))}  ",
            f"Pain point: {_md(item.get('pain_point'))}  ",
            f"Competitor: {_md(item.get('competitor'))}  ",
            f"Intent: {_md(item.get('intent'))}  ",
            f"OJO fit: {_md(item.get('fit_reason'))}  ",
            f"Promotion risk: {_md(item.get('promotion_risk'))}  ",
            f"Product mention: {'Potentially, verify rules' if item.get('product_mention_allowed') is True else 'No / unknown'}  ",
            f"Action: {_md(item.get('action'))}",
            "",
            f"Summary: {_md(item.get('summary'))}",
            "",
            f"Core question: {_md(item.get('core_question'))}",
            "",
            f"Reply angle: {_md(item.get('reply_angle'))}",
            "",
            "**Comment draft — review and edit before any manual posting:**",
            "",
            _md(item.get("comment_draft")) or "(No draft)",
        ])
        evidence = _items(item.get("evidence"))
        flags = _items(item.get("flags"))
        if evidence:
            lines.extend(["", "Evidence:", *[f"- {_md(value)}" for value in evidence]])
        if flags:
            lines.extend(["", "Review flags:", *[f"- {_md(value)}" for value in flags]])

    return "\n".join(lines).rstrip() + "\n"


def _csv_safe(value: object) -> str:
    """Neutralize spreadsheet formulas while preserving CSV's normal quoting."""
    text = str(value if value is not None else "")
    position = 0
    while position < len(text) and (
        text[position].isspace() or unicodedata.category(text[position]) in {"Cc", "Cf"}
    ):
        position += 1
    if position < len(text) and text[position] in "=+-@":
        return "'" + text
    return text


def render_csv(run: dict) -> str:
    """Render a spreadsheet-safe CSV of the same human-review candidates."""
    opportunities = _opportunities(run)
    counts = Counter(_safe_priority(item.get("priority")) for item in opportunities)
    flagged = sum(bool(_items(item.get("flags"))) for item in opportunities)
    qa_summary = (
        f"{len(opportunities)} opportunities: P0 {counts['P0']}, P1 {counts['P1']}, "
        f"P2 {counts['P2']}; {flagged} with review flags."
    )
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=_COLUMNS, lineterminator="\n", quoting=csv.QUOTE_ALL)
    writer.writeheader()
    for item in opportunities:
        row = {key: run.get(key, "") for key in ("generated_at", "window_start", "window_end", "source")}
        row.update({key: item.get(key, "") for key in _COLUMNS if key not in row})
        row["priority"] = _safe_priority(item.get("priority"))
        row["permalink"] = _reddit_url(item.get("permalink"))
        row["score"] = _score(item.get("score"))
        row["product_mention_allowed"] = "Yes, verify rules" if item.get("product_mention_allowed") is True else "No / unknown"
        row["evidence"] = " | ".join(_items(item.get("evidence")))
        row["flags"] = " | ".join(_items(item.get("flags")))
        row["qa_summary"] = qa_summary
        row["limitations"] = _LIMITATIONS
        row["posting_status"] = "Draft only; not posted"
        writer.writerow({key: _csv_safe(row.get(key, "")) for key in _COLUMNS})
    return output.getvalue()


_FEISHU_COLUMNS = (
    "Run Date UTC", "Priority", "Thread ID", "Thread", "Subreddit", "Thread URL",
    "Persona", "Use Case", "Pain Point", "Opportunity Score", "Recommended Action",
    "Review Status", "Original Thread Read", "Rules Checked", "Product Claims Checked",
    "Affiliation Disclosed", "Manual Reply URL", "Reply Interactions", "Generalized Attested",
    "Query Candidate", "Question Theme", "Use Case Insight", "Competitor Pain",
    "Product Feedback", "Content Idea", "Reviewer Notes", "Competitor", "Intent",
    "ICP Score", "Problem Score", "Discussion Score", "Promotion Score", "Promotion Risk",
    "Product Mention", "Summary", "User Question", "OJO Fit", "Reply Angle",
    "Comment Draft", "Community Rule Evidence", "Review Flags", "Delete By UTC",
)


def render_feishu_csv(run: dict) -> str:
    """Feishu-importable review sheet. No upload or remote API call occurs here.

    Raw post-derived columns are intentionally marked for deletion after 24h.
    The user owns the destination sheet and must honor their approved retention.
    """
    opportunities = _opportunities(run)
    generated = run.get("generated_at", "")
    try:
        timestamp = datetime.fromisoformat(str(generated).replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        delete_by = (timestamp.astimezone(timezone.utc) + timedelta(hours=24)).isoformat()
    except (TypeError, ValueError):
        delete_by = "Review and delete within 24h"
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=_FEISHU_COLUMNS, lineterminator="\n", quoting=csv.QUOTE_ALL)
    writer.writeheader()
    for item in opportunities:
        scores = item.get("score_breakdown", {})
        if not isinstance(scores, dict):
            scores = {}
        competitor = item.get("competitor", "")
        if isinstance(competitor, list):
            competitor = ", ".join(str(value) for value in competitor)
        evidence = " | ".join(_items(item.get("evidence")))
        row = {
            "Run Date UTC": generated, "Priority": _safe_priority(item.get("priority")),
            "Thread ID": item.get("id", ""), "Thread": item.get("title", ""),
            "Subreddit": item.get("subreddit", ""), "Thread URL": _reddit_url(item.get("permalink")),
            "Persona": item.get("persona", item.get("icp", "")),
            "Use Case": item.get("use_case", item.get("pain_point", "")),
            "Pain Point": item.get("pain_point", ""), "Competitor": competitor,
            "Intent": item.get("intent", ""), "Opportunity Score": _score(item.get("score")),
            "ICP Score": _score(scores.get("icp")), "Problem Score": _score(scores.get("pain")),
            "Discussion Score": _score(scores.get("discussion")),
            "Promotion Score": _score(scores.get("promotion")),
            "Promotion Risk": item.get("promotion_risk_level", item.get("promotion_risk", "unknown")),
            "Product Mention": "Potentially, verify rules" if item.get("product_mention_allowed") is True else "No / unknown",
            "Recommended Action": item.get("action", "research_only"),
            "Summary": item.get("summary", ""), "User Question": item.get("core_question", ""),
            "OJO Fit": item.get("fit_reason", ""), "Reply Angle": item.get("reply_angle", ""),
            "Comment Draft": item.get("comment_draft", ""), "Community Rule Evidence": evidence,
            "Review Flags": " | ".join(_items(item.get("flags"))),
            "Review Status": "待审核", "Original Thread Read": "No", "Rules Checked": "No",
            "Product Claims Checked": "No", "Affiliation Disclosed": "No", "Manual Reply URL": "",
            "Reply Interactions": "", "Query Candidate": "", "Product Feedback": "",
            "Question Theme": "", "Use Case Insight": "", "Competitor Pain": "",
            "Content Idea": "", "Generalized Attested": "No",
            "Reviewer Notes": "", "Delete By UTC": delete_by,
        }
        writer.writerow({name: _csv_safe(row.get(name, "")) for name in _FEISHU_COLUMNS})
    return output.getvalue()


_RULE_COLUMNS = (
    "Subreddit", "Self Promotion", "Product Link", "Account Age", "Karma",
    "Survey", "Product Feedback", "Weekly Promotion Thread", "Rules URL",
    "Checked At UTC", "Reviewed By", "Product Mention Decision", "Notes",
)


def render_community_rules_csv(config: dict) -> str:
    """A human-checkable Feishu sheet template, never a claim of permission."""
    if not isinstance(config, dict) or not isinstance(config.get("target_subreddits"), list):
        raise ValueError("target_subreddits must be a list")
    policies = config.get("promotion_policies", {})
    if not isinstance(policies, dict):
        raise ValueError("promotion_policies must be an object")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=_RULE_COLUMNS, lineterminator="\n", quoting=csv.QUOTE_ALL)
    writer.writeheader()
    for name in config["target_subreddits"]:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]{1,21}", name):
            raise ValueError("Invalid subreddit in rule template")
        policy = policies.get(name, {})
        if not isinstance(policy, dict):
            policy = {}
        row = {
            "Subreddit": name,
            "Self Promotion": policy.get("self_promo", "unknown"),
            "Product Link": policy.get("product_link", "unknown"),
            "Account Age": policy.get("account_age", "unknown"),
            "Karma": policy.get("karma", "unknown"),
            "Survey": policy.get("survey", "unknown"),
            "Product Feedback": policy.get("product_feedback", "unknown"),
            "Weekly Promotion Thread": policy.get("weekly_promo_thread", "unknown"),
            "Rules URL": f"https://www.reddit.com/r/{name}/about/rules",
            "Checked At UTC": policy.get("checked_at", ""),
            "Reviewed By": "", "Product Mention Decision": "unknown", "Notes": "",
        }
        writer.writerow({key: _csv_safe(row.get(key, "")) for key in _RULE_COLUMNS})
    return output.getvalue()
