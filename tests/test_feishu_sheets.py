"""Offline safety tests for the ordinary Feishu Sheets v2 queue sync."""

from __future__ import annotations

import csv
import io
import json
import unittest
from datetime import datetime, timezone
from urllib.error import URLError
from unittest.mock import Mock

from reddit_opportunity_agent.feishu_sheets import (
    FeishuSyncError,
    cleanup_expired_feishu_rows,
    sync_feishu_sheet,
)
from reddit_opportunity_agent.report import _FEISHU_COLUMNS, render_feishu_csv


NOW = datetime(2026, 9, 17, 9, tzinfo=timezone.utc)


def _col(name: str) -> int:
    return _FEISHU_COLUMNS.index(name)


def _csv(*ids: str) -> str:
    return render_feishu_csv({
        "generated_at": "2026-09-17T08:00:00Z",
        "opportunities": [
            {"id": thread_id, "title": "Question " + thread_id, "priority": "P1"}
            for thread_id in ids
        ],
    })


def _rows(*ids: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(_csv(*ids))))


def _as_csv(rows: list[list[str]]) -> str:
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(rows)
    return output.getvalue()


def _response(value: dict) -> io.BytesIO:
    return io.BytesIO(json.dumps(value).encode("utf-8"))


def _opener(existing: list[list[object]], *, response_code: int = 0):
    calls = []

    def open_request(request, timeout):
        calls.append(request)
        if request.get_method() == "POST":
            return _response({"code": response_code, "tenant_access_token": "private-token"})
        if request.get_method() == "GET":
            return _response({"code": 0, "data": {"valueRange": {
                "range": "sheet123!A1:AP10", "majorDimension": "ROWS", "values": existing,
            }}})
        return _response({"code": 0, "data": {"updatedRange": "sheet123!A1:AP10"}})

    return open_request, calls


def _sync(csv_text: str, opener, **overrides):
    options = {
        "reddit_approved": True,
        "feishu_sharing_approved": True,
        "approval_ref": "written-sharing-approval",
        "app_id": "cli_test",
        "app_secret": "very-secret",
        "spreadsheet_token": "sht_test",
        "sheet_id": "sheet123",
        "now": NOW,
        "opener": opener,
    }
    options.update(overrides)
    return sync_feishu_sheet(csv_text, **options)


def _cleanup(opener, **overrides):
    options = {
        "app_id": "cli_test",
        "app_secret": "very-secret",
        "spreadsheet_token": "sht_test",
        "sheet_id": "sheet123",
        "now": NOW,
        "opener": opener,
    }
    options.update(overrides)
    return cleanup_expired_feishu_rows(**options)


class FeishuSheetsTests(unittest.TestCase):
    def test_cleanup_needs_only_feishu_credentials_and_removes_expired_rows(self):
        existing = _rows("keep", "expired", "keep2")
        existing[1][_col("Reviewer Notes")] = "Private reviewer note"
        existing[1][_col("Question Theme")] = "Prototype workflow"
        existing[1][_col("Generalized Attested")] = "Yes"
        existing[2][_col("Delete By UTC")] = "2026-09-17T08:00:00Z"
        existing[3][_col("Manual Reply URL")] = [{"text": "edited", "type": "text"}]
        opener, calls = _opener(existing)
        result = _cleanup(opener)
        self.assertEqual(result, {"expired": 1, "retained": 2, "written": True})
        self.assertEqual([request.get_method() for request in calls], ["POST", "GET", "PUT"])
        self.assertTrue(all(request.full_url.startswith("https://open.feishu.cn/") for request in calls))
        matrix = json.loads(calls[2].data)["valueRange"]["values"]
        self.assertEqual([row[2] for row in matrix[1:]], ["keep", "keep2", *([""] * 7)])
        self.assertEqual(matrix[1][_col("Reviewer Notes")], "Private reviewer note")
        self.assertEqual(matrix[1][_col("Question Theme")], "Prototype workflow")
        self.assertEqual(matrix[1][_col("Generalized Attested")], "Yes")
        self.assertEqual(matrix[2][_col("Manual Reply URL")], [{"text": "edited", "type": "text"}])
        self.assertTrue(all(cell == "" for row in matrix[3:] for cell in row))

    def test_cleanup_does_not_write_or_initialize_when_nothing_expired(self):
        for existing, expected in (([], 0), (_rows("keep"), 1)):
            with self.subTest(existing=existing):
                opener, calls = _opener(existing)
                self.assertEqual(_cleanup(opener), {"expired": 0, "retained": expected, "written": False})
                self.assertEqual([request.get_method() for request in calls], ["POST", "GET"])

    def test_cleanup_fails_closed_for_unknown_header_and_ambiguous_rows(self):
        unknown = ["Somebody else's worksheet"]
        duplicate = _rows("dup", "dup")
        missing_expiration = _rows("keep")
        missing_expiration[1][_col("Delete By UTC")] = "not a date"
        for existing in (unknown, duplicate, missing_expiration):
            with self.subTest(existing=existing):
                opener, calls = _opener(existing)
                with self.assertRaises(FeishuSyncError):
                    _cleanup(opener)
                self.assertEqual([request.get_method() for request in calls], ["POST", "GET"])

    def test_cleanup_invalid_configuration_makes_no_network_requests(self):
        for overrides in (
            {"app_id": ""},
            {"app_secret": ""},
            {"spreadsheet_token": "../invalid"},
            {"sheet_id": "sheet!A1:B7"},
            {"now": datetime(2026, 9, 17, 9)},
        ):
            with self.subTest(overrides=overrides):
                opener = Mock()
                with self.assertRaises(FeishuSyncError):
                    _cleanup(opener, **overrides)
                opener.assert_not_called()

    def test_cleanup_network_errors_do_not_echo_secret_or_sheet_identifier(self):
        def failing_opener(request, timeout):
            raise URLError("very-secret sht_test private-token")

        with self.assertRaises(FeishuSyncError) as captured:
            _cleanup(failing_opener)
        for secret in ("very-secret", "sht_test", "private-token"):
            self.assertNotIn(secret, str(captured.exception))

    def test_each_missing_approval_gate_blocks_all_network(self):
        for override in (
            {"reddit_approved": False},
            {"reddit_approved": "true"},
            {"feishu_sharing_approved": False},
            {"feishu_sharing_approved": "true"},
            {"approval_ref": "  "},
        ):
            with self.subTest(override=override):
                opener = Mock()
                with self.assertRaisesRegex(FeishuSyncError, "approvals"):
                    _sync(_csv("new"), opener, **override)
                opener.assert_not_called()

    def test_empty_sheet_initializes_only_dedicated_queue_range(self):
        opener, calls = _opener([])
        result = _sync(_csv("one"), opener)
        self.assertEqual(result, {"added": 1, "retained": 0, "expired": 0, "written": True})
        self.assertEqual([request.get_method() for request in calls], ["POST", "GET", "PUT"])
        self.assertEqual(calls[0].full_url, "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal")
        self.assertEqual(json.loads(calls[0].data), {"app_id": "cli_test", "app_secret": "very-secret"})
        self.assertEqual(calls[1].full_url, "https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/sht_test/values/sheet123!A1:AP10")
        self.assertEqual(calls[1].get_header("Authorization"), "Bearer private-token")
        self.assertEqual(calls[2].full_url, "https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/sht_test/values")
        body = json.loads(calls[2].data)
        self.assertEqual(body["valueRange"]["range"], "sheet123!A1:AP10")
        matrix = body["valueRange"]["values"]
        self.assertEqual(len(matrix), 10)
        self.assertTrue(all(len(row) == 42 for row in matrix))
        self.assertEqual(matrix[1][2], "one")
        self.assertTrue(all(cell == "" for row in matrix[2:] for cell in row))

    def test_duplicate_input_ids_are_written_only_once(self):
        opener, calls = _opener([])
        result = _sync(_csv("same", "same"), opener)
        self.assertEqual(result["added"], 1)
        matrix = json.loads(calls[2].data)["valueRange"]["values"]
        self.assertEqual([row[2] for row in matrix[1:]], ["same", *([""] * 8)])

    def test_opportunity_scores_are_numeric_cells_in_api_write(self):
        rows = _rows("one")
        for name, score in (("Opportunity Score", "78"), ("ICP Score", "21"),
                            ("Problem Score", "22"), ("Discussion Score", "23"),
                            ("Promotion Score", "12")):
            rows[1][_col(name)] = score
        opener, calls = _opener([])
        _sync(_as_csv(rows), opener)
        written = json.loads(calls[2].data)["valueRange"]["values"][1]
        self.assertEqual([written[_col(name)] for name in (
            "Opportunity Score", "ICP Score", "Problem Score", "Discussion Score",
            "Promotion Score",
        )], [78, 21, 22, 23, 12])

    def test_preserves_reviewer_edits_compacts_expired_and_limits_new_rows(self):
        existing = _rows("keep", "expired")
        existing[1][_col("Review Status")] = "已审核"
        existing[1][_col("Reviewer Notes")] = "Reviewer edited this"
        existing[2][_col("Delete By UTC")] = "2026-09-17T08:00:00Z"
        opener, calls = _opener(existing)
        result = _sync(_csv("keep", "new1", "new2", "new3", "new4"), opener)
        self.assertEqual(result, {"added": 3, "retained": 1, "expired": 1, "written": True})
        matrix = json.loads(calls[2].data)["valueRange"]["values"]
        self.assertEqual([row[2] for row in matrix[1:]], ["keep", "new1", "new2", "new3", *([""] * 5)])
        self.assertEqual(matrix[1][_col("Review Status")], "已审核")
        self.assertEqual(matrix[1][_col("Reviewer Notes")], "Reviewer edited this")
        self.assertNotIn("expired", [row[2] for row in matrix])

    def test_deduped_run_does_not_overwrite_existing_review(self):
        existing = _rows("same")
        existing[1][_col("Reviewer Notes")] = "Keep reviewer note"
        opener, calls = _opener(existing)
        result = _sync(_csv("same", "same"), opener)
        self.assertEqual(result, {"added": 0, "retained": 1, "expired": 0, "written": False})
        self.assertEqual([request.get_method() for request in calls], ["POST", "GET"])

    def test_full_queue_fails_visibly_without_overwriting_another_candidate(self):
        existing = _rows("one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
        opener, calls = _opener(existing)
        with self.assertRaisesRegex(FeishuSyncError, "queue is full"):
            _sync(_csv("ten"), opener)
        self.assertEqual([request.get_method() for request in calls], ["POST", "GET"])

    def test_six_retained_rows_still_leave_room_for_three_new_opportunities(self):
        existing = _rows("one", "two", "three", "four", "five", "six")
        opener, calls = _opener(existing)
        result = _sync(_csv("seven", "eight", "nine"), opener)
        self.assertEqual(result["added"], 3)
        matrix = json.loads(calls[2].data)["valueRange"]["values"]
        self.assertEqual([row[2] for row in matrix[1:]], ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"])

    def test_existing_link_cell_is_preserved_when_queue_changes(self):
        existing = _rows("keep")
        rich_link = [{"link": "https://example.com/manual", "text": "Manual reply", "type": "url"}]
        existing[1][_col("Manual Reply URL")] = rich_link
        opener, calls = _opener(existing)
        _sync(_csv("new"), opener)
        matrix = json.loads(calls[2].data)["valueRange"]["values"]
        self.assertEqual(matrix[1][_col("Manual Reply URL")], rich_link)

    def test_unknown_or_partial_layout_is_never_overwritten(self):
        for existing in (["Different header"], [[], ["orphan"]]):
            with self.subTest(existing=existing):
                opener, calls = _opener(existing)
                with self.assertRaises(FeishuSyncError):
                    _sync(_csv("new"), opener)
                self.assertEqual([request.get_method() for request in calls], ["POST", "GET"])

    def test_ambiguous_existing_row_is_never_overwritten(self):
        existing = _rows("same", "same")
        opener, calls = _opener(existing)
        with self.assertRaisesRegex(FeishuSyncError, "ambiguous Thread ID"):
            _sync(_csv("new"), opener)
        self.assertEqual([request.get_method() for request in calls], ["POST", "GET"])

    def test_existing_row_without_parseable_delete_date_is_not_overwritten(self):
        existing = _rows("keep")
        existing[1][_col("Delete By UTC")] = "someday"
        opener, calls = _opener(existing)
        with self.assertRaisesRegex(FeishuSyncError, "Delete By UTC"):
            _sync(_csv("new"), opener)
        self.assertEqual([request.get_method() for request in calls], ["POST", "GET"])

    def test_manually_extended_existing_deadline_cannot_extend_24_hour_cap(self):
        existing = _rows("old")
        existing[1][0] = "2026-09-15T08:00:00Z"
        existing[1][_col("Delete By UTC")] = "2026-10-19T08:00:00Z"
        opener, calls = _opener(existing)
        result = _sync(_csv("new"), opener)
        self.assertEqual(result["expired"], 1)
        matrix = json.loads(calls[2].data)["valueRange"]["values"]
        self.assertNotIn("old", [row[2] for row in matrix[1:]])

    def test_invalid_expiration_or_csv_header_blocks_write(self):
        opener = Mock()
        bad_csv = _csv("new").replace("2026-09-18T08:00:00+00:00", "Review and delete within 24h")
        with self.assertRaises(FeishuSyncError):
            _sync(bad_csv, opener)
        opener.assert_not_called()
        with self.assertRaisesRegex(FeishuSyncError, "header"):
            _sync("not,the,review,template\n", opener)
        opener.assert_not_called()

    def test_forged_extended_retention_is_rejected_before_network(self):
        rows = _rows("new")
        rows[1][_col("Delete By UTC")] = "2026-10-19T08:00:00+00:00"
        opener = Mock()
        with self.assertRaisesRegex(FeishuSyncError, "24 hours"):
            _sync(_as_csv(rows), opener)
        opener.assert_not_called()

    def test_forged_csv_formula_cells_are_neutralized(self):
        rows = _rows("new")
        rows[1][3] = '=HYPERLINK("https://evil.example","click")'
        rows[1][23] = "\ufeff\t@SUM(1,1)"
        opener, calls = _opener([])
        _sync(_as_csv(rows), opener)
        matrix = json.loads(calls[2].data)["valueRange"]["values"]
        self.assertTrue(matrix[1][3].startswith("'=HYPERLINK"))
        self.assertTrue(matrix[1][23].startswith("'\ufeff\t@SUM"))

    def test_api_failures_do_not_echo_credentials_or_sheet_tokens(self):
        def failing_opener(request, timeout):
            raise URLError("very-secret sht_test private-token")

        with self.assertRaises(FeishuSyncError) as captured:
            _sync(_csv("one"), failing_opener)
        for secret in ("very-secret", "sht_test", "private-token"):
            self.assertNotIn(secret, str(captured.exception))

        opener, calls = _opener([], response_code=999)
        with self.assertRaises(FeishuSyncError):
            _sync(_csv("one"), opener)
        self.assertEqual([request.get_method() for request in calls], ["POST"])


if __name__ == "__main__":
    unittest.main()
