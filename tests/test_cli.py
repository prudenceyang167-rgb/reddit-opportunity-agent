from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reddit_opportunity_agent.cli import main


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


if __name__ == "__main__":
    unittest.main()
