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
            f"ICP: {_md(item.get('icp'))}  ",
            f"Pain point: {_md(item.get('pain_point'))}  ",
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
