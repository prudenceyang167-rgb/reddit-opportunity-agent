"""Approval-gated sync for a dedicated Feishu *ordinary spreadsheet* queue.

Only ``A1:AP10`` in the named worksheet is managed. The CSV must come from
``report.render_feishu_csv``; existing reviewer cells are carried forward
unchanged for retained threads. This module never creates a spreadsheet,
changes permissions, posts to Reddit, or touches Bitable.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .report import _FEISHU_COLUMNS, _csv_safe


_BASE_URL = "https://open.feishu.cn/open-apis"
_TOKEN_URL = _BASE_URL + "/auth/v3/tenant_access_token/internal"
_ID = re.compile(r"[A-Za-z0-9_-]+\Z")
_AUTH_TOKEN = re.compile(r"[A-Za-z0-9._-]+\Z")
_WIDTH = len(_FEISHU_COLUMNS)
_HEIGHT = 10
_MAX_NEW = 3
_RUN_DATE = _FEISHU_COLUMNS.index("Run Date UTC")
_THREAD_ID = _FEISHU_COLUMNS.index("Thread ID")
_DELETE_BY = _FEISHU_COLUMNS.index("Delete By UTC")
_SCORES = tuple(_FEISHU_COLUMNS.index(name) for name in (
    "Opportunity Score", "ICP Score", "Problem Score", "Discussion Score", "Promotion Score",
))


class FeishuSyncError(RuntimeError):
    """A sync was refused or failed without exposing credentials or sheet data."""


def _require_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise FeishuSyncError(f"A valid {label} is required for Feishu sync.")
    return value


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise FeishuSyncError("A queue row has no valid Delete By UTC timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise FeishuSyncError("A queue row has no valid Delete By UTC timestamp.") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FeishuSyncError("A queue row has no valid Delete By UTC timestamp.")
    return parsed.astimezone(timezone.utc)


def _read_csv(csv_text: str) -> list[list[object]]:
    if not isinstance(csv_text, str):
        raise FeishuSyncError("Feishu CSV input must be text.")
    try:
        rows = list(csv.reader(io.StringIO(csv_text, newline=""), strict=True))
    except csv.Error:
        raise FeishuSyncError("Feishu CSV input is malformed.") from None
    if not rows or tuple(rows[0]) != _FEISHU_COLUMNS:
        raise FeishuSyncError("Feishu CSV header does not match the review queue template.")
    candidates: list[list[object]] = []
    seen: set[str] = set()
    for row in rows[1:]:
        if len(row) != _WIDTH or not row[_THREAD_ID].strip():
            raise FeishuSyncError("Feishu CSV contains an invalid review row.")
        # The renderer can emit a human-readable fallback when generated_at is
        # invalid. Such a row cannot be safely retained or expired by a sync.
        if _timestamp(row[_DELETE_BY]) != _timestamp(row[_RUN_DATE]) + timedelta(hours=24):
            raise FeishuSyncError("Feishu CSV retention deadline must be 24 hours after the run date.")
        safe_row = [_csv_safe(cell) for cell in row]
        for index in _SCORES:
            if safe_row[index].isdecimal():
                safe_row[index] = int(safe_row[index])
        thread_id = safe_row[_THREAD_ID]
        if thread_id not in seen:
            candidates.append(safe_row)
            seen.add(thread_id)
    return candidates


def _request_json(request: Request, *, opener, stage: str) -> dict:
    try:
        with opener(request, timeout=20) as response:
            raw = response.read(10_000_001)
        if len(raw) > 10_000_000:
            raise FeishuSyncError(f"Feishu {stage} response exceeded the size limit.")
        payload = json.loads(raw)
    except (HTTPError, URLError, OSError, TimeoutError, ValueError, TypeError, UnicodeError):
        # Exception messages can contain a URL (including spreadsheet token),
        # a request body, or Feishu's echoed credential fields.
        raise FeishuSyncError(f"Feishu {stage} request failed.") from None
    if not isinstance(payload, dict) or type(payload.get("code")) is not int or payload["code"] != 0:
        raise FeishuSyncError(f"Feishu {stage} was not accepted.")
    return payload


def _existing_rows(payload: dict, range_name: str, now: datetime) -> tuple[list[list[object]], int, bool]:
    data = payload.get("data")
    value_range = data.get("valueRange") if isinstance(data, dict) else None
    if not isinstance(value_range, dict):
        raise FeishuSyncError("Feishu returned an invalid review queue range.")
    if value_range.get("range", range_name) != range_name or value_range.get("majorDimension", "ROWS") != "ROWS":
        raise FeishuSyncError("Feishu returned an unexpected review queue range.")
    values = value_range.get("values", [])
    if not isinstance(values, list) or len(values) > _HEIGHT or any(
        not isinstance(row, list) or len(row) > _WIDTH for row in values
    ):
        raise FeishuSyncError("Feishu returned an invalid review queue matrix.")
    normalized = [row + [""] * (_WIDTH - len(row)) for row in values]
    normalized.extend([[""] * _WIDTH for _ in range(_HEIGHT - len(normalized))])
    header = normalized[0]
    empty = all(cell is None or cell == "" for row in normalized for cell in row)
    if not empty and tuple(header) != _FEISHU_COLUMNS:
        raise FeishuSyncError("Feishu worksheet has an unknown header; no data was written.")

    retained: list[list[object]] = []
    expired = 0
    seen: set[str] = set()
    for row in normalized[1:]:
        if all(cell is None or cell == "" for cell in row):
            continue
        thread_id = row[_THREAD_ID]
        if not isinstance(thread_id, str) or not thread_id.strip() or thread_id in seen:
            raise FeishuSyncError("Feishu queue has an ambiguous Thread ID; no data was written.")
        seen.add(thread_id)
        # A reviewer may accidentally extend Delete By. Never retain source
        # material beyond 24 hours from its original run timestamp.
        effective_deadline = min(_timestamp(row[_DELETE_BY]), _timestamp(row[_RUN_DATE]) + timedelta(hours=24))
        if effective_deadline <= now:
            expired += 1
        else:
            retained.append(row)
    return retained, expired, empty


def _sync_time(now: datetime | None) -> datetime:
    now = datetime.now(timezone.utc) if now is None else now
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise FeishuSyncError("Feishu sync time must be timezone-aware.")
    return now.astimezone(timezone.utc)


def _queue_connection(
    *, app_id: str, app_secret: str, spreadsheet_token: str, sheet_id: str, opener
) -> tuple[str, str, dict[str, str]]:
    if not isinstance(app_id, str) or not app_id.strip() or not isinstance(app_secret, str) or not app_secret.strip():
        raise FeishuSyncError("Feishu app credentials are required.")
    spreadsheet_token = _require_id(spreadsheet_token, "spreadsheet token")
    sheet_id = _require_id(sheet_id, "sheet ID")
    token_request = Request(
        _TOKEN_URL,
        data=json.dumps({"app_id": app_id, "app_secret": app_secret}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    token_payload = _request_json(token_request, opener=opener, stage="token")
    token = token_payload.get("tenant_access_token")
    if not isinstance(token, str) or not _AUTH_TOKEN.fullmatch(token):
        raise FeishuSyncError("Feishu did not return a tenant access token.")
    range_name = f"{sheet_id}!A1:AP10"
    url = f"{_BASE_URL}/sheets/v2/spreadsheets/{quote(spreadsheet_token, safe='')}/values"
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    return url, range_name, headers


def _read_queue(*, url: str, range_name: str, headers: dict[str, str], now: datetime, opener) -> tuple[list[list[object]], int, bool]:
    read_request = Request(url + "/" + quote(range_name, safe="!:"), headers=headers, method="GET")
    read_payload = _request_json(read_request, opener=opener, stage="read")
    return _existing_rows(read_payload, range_name, now)


def _write_queue(*, url: str, range_name: str, headers: dict[str, str], retained: list[list[object]], opener) -> None:
    matrix: list[list[object]] = [list(_FEISHU_COLUMNS), *retained]
    matrix.extend([[""] * _WIDTH for _ in range(_HEIGHT - len(matrix))])
    write_request = Request(
        url,
        data=json.dumps({"valueRange": {"range": range_name, "values": matrix}}, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="PUT",
    )
    _request_json(write_request, opener=opener, stage="write")


def cleanup_expired_feishu_rows(
    *,
    app_id: str,
    app_secret: str,
    spreadsheet_token: str,
    sheet_id: str,
    now: datetime | None = None,
    opener=urlopen,
) -> dict[str, int | bool]:
    """Clear only expired rows in the managed ordinary spreadsheet queue.

    No Reddit data or CSV is accepted, and no Reddit API/sharing approval is
    needed: this is a Feishu-only retention task. It never appends rows. All
    surviving reviewer edits remain unchanged, and unknown/ambiguous layouts
    abort before any write.
    """
    now = _sync_time(now)
    url, range_name, headers = _queue_connection(
        app_id=app_id, app_secret=app_secret, spreadsheet_token=spreadsheet_token,
        sheet_id=sheet_id, opener=opener,
    )
    retained, expired, _ = _read_queue(
        url=url, range_name=range_name, headers=headers, now=now, opener=opener,
    )
    if expired:
        _write_queue(url=url, range_name=range_name, headers=headers, retained=retained, opener=opener)
    return {"expired": expired, "retained": len(retained), "written": expired > 0}


def sync_feishu_sheet(
    csv_text: str,
    *,
    reddit_approved: bool,
    feishu_sharing_approved: bool,
    approval_ref: str,
    app_id: str,
    app_secret: str,
    spreadsheet_token: str,
    sheet_id: str,
    now: datetime | None = None,
    opener=urlopen,
) -> dict[str, int | bool]:
    """Merge one rendered CSV into a nine-row Feishu review queue.

    Both explicit approvals and their nonempty written reference are required
    *before* token acquisition or any other network request. Up to three new,
    unexpired Thread IDs are appended; existing unexpired rows retain every
    reviewer-edited cell. Expired rows are cleared by writing blank cells.
    """
    if reddit_approved is not True or feishu_sharing_approved is not True or not isinstance(approval_ref, str) or not approval_ref.strip():
        raise FeishuSyncError("Reddit and Feishu third-party sharing approvals with a written reference are required.")
    now = _sync_time(now)
    candidates = _read_csv(csv_text)
    url, range_name, headers = _queue_connection(
        app_id=app_id, app_secret=app_secret, spreadsheet_token=spreadsheet_token,
        sheet_id=sheet_id, opener=opener,
    )
    retained, expired, empty = _read_queue(
        url=url, range_name=range_name, headers=headers, now=now, opener=opener,
    )

    seen = {row[_THREAD_ID] for row in retained}
    # Expired Thread IDs may reappear in a new run only if the new row has a
    # fresh Delete By UTC. They do not block a replacement of stale content.
    added = 0
    for row in candidates:
        thread_id = row[_THREAD_ID]
        if thread_id in seen or _timestamp(row[_DELETE_BY]) <= now:
            continue
        if added >= _MAX_NEW:
            break
        if len(retained) >= _HEIGHT - 1:
            raise FeishuSyncError("Feishu review queue is full; new opportunities remain in the encrypted report.")
        seen.add(thread_id)
        added += 1
        retained.append(row)

    changed = empty or expired > 0 or added > 0
    if changed:
        _write_queue(
            url=url, range_name=range_name, headers=headers, retained=retained, opener=opener,
        )
    return {"added": added, "retained": len(retained) - added, "expired": expired, "written": changed}
