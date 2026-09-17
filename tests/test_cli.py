from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from reddit_opportunity_agent.cli import main
from reddit_opportunity_agent.report import render_feishu_csv


class CliTest(unittest.TestCase):
    def test_demo_runs_without_credentials_and_marks_synthetic(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "report"
            with patch.dict(os.environ, {"REDDIT_APPROVAL_CONFIRMED": "", "REDDIT_APPROVAL_REFERENCE": ""}):
                self.assertEqual(main(["demo", "--out", str(out)]), 0)
            result = json.loads((out / "opportunities.json").read_text())
            self.assertIn("SYNTHETIC", result["source"])
            self.assertTrue({"P0", "P1", "P2"}.issubset({item["priority"] for item in result["opportunities"]}))
            self.assertIn("no comment has been posted", (out / "opportunities.md").read_text())

    def test_real_import_blocked_without_reddit_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "input.json").write_text("[]")
            (root / "config.json").write_text('{"target_subreddits":["ExamplePM"]}')
            with patch.dict(os.environ, {"REDDIT_APPROVAL_CONFIRMED": "", "REDDIT_APPROVAL_REFERENCE": ""}):
                self.assertEqual(main(["import", "--config", str(root / "config.json"), "--input", str(root / "input.json"), "--out", str(root / "report")]), 2)
            self.assertFalse((root / "report").exists())

    def test_deepseek_blocked_without_separate_processing_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "input.json").write_text("[]")
            (root / "config.json").write_text('{"target_subreddits":["ExamplePM"]}')
            with patch.dict(os.environ, {
                "REDDIT_APPROVAL_CONFIRMED": "true", "REDDIT_APPROVAL_REFERENCE": "written-api-approval",
                "REDDIT_AI_PROCESSING_APPROVED": "", "REDDIT_AI_APPROVAL_REFERENCE": "",
                "DEEPSEEK_API_KEY": "test-key",
            }):
                self.assertEqual(main(["import", "--ai", "--config", str(root / "config.json"),
                                       "--input", str(root / "input.json"), "--out", str(root / "report")]), 2)
            self.assertFalse((root / "report").exists())

    def test_synthetic_demo_cannot_call_ai(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "report"
            self.assertEqual(main(["demo", "--ai", "--out", str(out)]), 2)
            self.assertFalse(out.exists())

    def test_duplicate_output_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "report"
            out.mkdir()
            sentinel = out / "important.txt"
            sentinel.write_text("keep me")
            self.assertEqual(main(["demo", "--out", str(out)]), 2)
            self.assertEqual(sentinel.read_text(), "keep me")

    def test_sync_feishu_refuses_missing_approval_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.csv"
            path.write_text(render_feishu_csv({"generated_at": datetime.now(timezone.utc).isoformat(),
                                               "opportunities": [{"id": "synthetic1", "priority": "P2"}]}))
            with patch.dict(os.environ, {"REDDIT_APPROVAL_CONFIRMED": "", "REDDIT_FEISHU_SHARING_APPROVED": ""}), \
                 patch("reddit_opportunity_agent.feishu_sheets.urlopen") as network:
                self.assertEqual(main(["sync-feishu", "--input", str(path)]), 4)
                network.assert_not_called()

    def test_purge_feishu_only_calls_cleanup_connector(self):
        with patch("reddit_opportunity_agent.feishu_sheets.cleanup_expired_feishu_rows",
                   return_value={"expired": 2, "retained": 1, "written": True}) as cleanup:
            self.assertEqual(main(["purge-feishu"]), 0)
            cleanup.assert_called_once()

    def test_weekly_uses_only_daily_digest_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            demo = root / "demo"
            with patch.dict(os.environ, {"REDDIT_APPROVAL_CONFIRMED": "", "REDDIT_APPROVAL_REFERENCE": ""}):
                self.assertEqual(main(["demo", "--out", str(demo)]), 0)
                digests = root / "digests"
                digests.mkdir()
                (digests / "day1.json").write_bytes((demo / "daily_digest.json").read_bytes())
                out = root / "weekly"
                self.assertEqual(main(["weekly", "--input", str(digests), "--out", str(out)]), 0)
            result = json.loads((out / "weekly.json").read_text())
            self.assertEqual(result["report_mode"], "retention_safe_digest")
            self.assertEqual(result["source_type"], "synthetic")
            self.assertEqual(result["run_count"], 1)
            self.assertIn("SYNTHETIC DEMO", (out / "weekly.md").read_text())
            self.assertNotIn("demo1", (out / "weekly.md").read_text())

    def test_digest_refuses_unapproved_run_before_reading_it(self):
        with patch.dict(os.environ, {"REDDIT_APPROVAL_CONFIRMED": "", "REDDIT_APPROVAL_REFERENCE": ""}), \
             patch("reddit_opportunity_agent.cli._read_json") as reader:
            self.assertEqual(main(["digest", "--input", "any.json", "--reviews", "any.csv"]), 2)
            reader.assert_not_called()

    def test_digest_imports_reviewed_feishu_outcome_without_raw_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            now = datetime.now(timezone.utc)
            run = {
                "generated_at": now.isoformat(),
                "window_start": (now - timedelta(hours=24)).isoformat(),
                "window_end": now.isoformat(),
                "source": "Reddit OAuth Data API — approved use only",
                "opportunities": [{"id": "a1", "priority": "P1", "title": "Private raw title",
                                   "use_case": "Prototype", "pain_point": "Hard to Iterate",
                                   "core_question": "Private raw question"}],
            }
            run_path = root / "opportunities.json"
            run_path.write_text(json.dumps(run))
            rows = list(csv.DictReader(io.StringIO(render_feishu_csv(run))))
            rows[0].update({"Review Status": "已回复", "Original Thread Read": "Yes",
                            "Rules Checked": "Yes", "Reply Interactions": "2",
                            "Query Candidate": "editable prototype workflow",
                            "Generalized Attested": "Yes",
                            "Manual Reply URL": "https://www.reddit.com/r/ExamplePM/comments/a1/test/c1/"})
            exported = io.StringIO(newline="")
            writer = csv.DictWriter(exported, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            reviews_path = root / "review.csv"
            reviews_path.write_text(exported.getvalue())
            out = root / "digest"
            with patch.dict(os.environ, {"REDDIT_APPROVAL_CONFIRMED": "true",
                                      "REDDIT_APPROVAL_REFERENCE": "test-written-approval"}):
                self.assertEqual(main(["digest", "--input", str(run_path), "--reviews", str(reviews_path),
                                       "--out", str(out)]), 0)
            text = (out / "daily_digest.json").read_text()
            digest = json.loads(text)
            self.assertEqual(digest["source_type"], "approved")
            self.assertEqual(digest["kpis"]["community"]["confirmed_replies"]["value"], 1)
            self.assertEqual(digest["kpis"]["community"]["reply_interactions"]["value"], 2)
            self.assertEqual(digest["new_query_candidates"][0]["query"], "editable prototype workflow")
            self.assertNotIn("Private raw", text)


if __name__ == "__main__":
    unittest.main()
