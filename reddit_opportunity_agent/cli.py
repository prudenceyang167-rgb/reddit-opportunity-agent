"""Offline/demo and approved-only daily Reddit opportunity runs."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .report import render_csv, render_feishu_csv, render_markdown
from .scoring import evaluate_posts


def _approval() -> None:
    if os.environ.get("REDDIT_APPROVAL_CONFIRMED") != "true" or not os.environ.get("REDDIT_APPROVAL_REFERENCE", "").strip():
        raise ValueError(
            "Real Reddit data is disabled. Obtain Reddit's explicit Data API and commercial-use approval, "
            "then set REDDIT_APPROVAL_CONFIRMED=true and REDDIT_APPROVAL_REFERENCE."
        )


def _read_json(path: Path):
    if not path.is_file() or path.stat().st_size > 2_000_000:
        raise ValueError("Input must be an existing JSON file smaller than 2 MB.")
    return json.loads(path.read_text(encoding="utf-8"))


def _configuration(path: Path) -> dict:
    config = _read_json(path)
    if not isinstance(config, dict):
        raise ValueError("Config must be a JSON object.")
    if os.environ.get("REDDIT_TARGET_SUBREDDITS", "").strip():
        config["target_subreddits"] = [name.strip().removeprefix("r/") for name in os.environ["REDDIT_TARGET_SUBREDDITS"].split(",") if name.strip()]
    if os.environ.get("OJO_VERIFIED_FACTS_JSON", "").strip():
        facts = json.loads(os.environ["OJO_VERIFIED_FACTS_JSON"])
        if not isinstance(facts, list) or not all(isinstance(item, str) for item in facts):
            raise ValueError("OJO_VERIFIED_FACTS_JSON must be a JSON string array.")
        config["verified_product_facts"] = facts
    if os.environ.get("REDDIT_PROMOTION_POLICIES_JSON", "").strip():
        policies = json.loads(os.environ["REDDIT_PROMOTION_POLICIES_JSON"])
        if not isinstance(policies, dict):
            raise ValueError("REDDIT_PROMOTION_POLICIES_JSON must be an object.")
        config["promotion_policies"] = policies
    targets = config.get("target_subreddits", [])
    if not isinstance(targets, list) or not targets or len(targets) > 20:
        raise ValueError("Configure 1–20 target_subreddits before a real run.")
    if any(not isinstance(name, str) or not name or len(name) > 21 or not name.replace("_", "").isalnum() for name in targets):
        raise ValueError("Each subreddit must be a valid short community name.")
    return config


def _demo(now: datetime) -> tuple[list[dict], dict]:
    def post(pid, sub, title, body, hours, comments, votes):
        return {"id": pid, "subreddit": sub, "title": title, "selftext": body,
                "created_utc": (now - timedelta(hours=hours)).timestamp(), "num_comments": comments,
                "score": votes, "permalink": f"/r/{sub}/comments/{pid}/synthetic_example/"}

    posts = [
        post("demo1", "SyntheticPM", "Best AI tool for prototyping?", "As a product manager I need an editable prototype from a PRD. My current UI is hard to edit. Any tools you recommend?", 2, 6, 8),
        post("demo2", "SyntheticFounders", "How do you build landing pages fast?", "I'm a founder with an MVP and no designer; looking for a landing page workflow. What worked for you?", 5, 3, 4),
        post("demo3", "SyntheticDesign", "AI design workflow reflections", "I'm a designer exploring an AI design workflow and Figma alternatives. The outputs often look generic; no request for recommendations.", 18, 0, 1),
    ]
    # Synthetic rules are test data only, never a claim about a real subreddit.
    config = {"brand": "OJO", "target_subreddits": ["SyntheticPM", "SyntheticFounders", "SyntheticDesign"],
              "max_opportunities": 3, "verified_product_facts": ["Synthetic example: produces editable interface drafts from written requirements."],
              "promotion_policies": {"SyntheticPM": {"status": "may_mention", "checked_at": now.isoformat(),
                                                   "evidence_url": "https://www.reddit.com/r/SyntheticPM/about/rules"}}}
    return posts, config


def _write(run: dict, out: Path) -> None:
    from .weekly import make_daily_digest

    out.mkdir(parents=True, exist_ok=False)
    files = {
        "opportunities.md": render_markdown(run),
        "opportunities.csv": render_csv(run),
        "feishu_review.csv": render_feishu_csv(run),
        "opportunities.json": json.dumps(run, ensure_ascii=False, indent=2) + "\n",
        "daily_digest.json": json.dumps(make_daily_digest(run), ensure_ascii=False, indent=2) + "\n",
    }
    for name, content in files.items():
        path = out / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Reddit opportunity screening; never posts comments.")
    parser.add_argument("mode", choices=["demo", "import", "live", "sync-feishu", "purge-feishu", "digest", "weekly"])
    parser.add_argument("--config", type=Path, default=Path("config.example.json"))
    parser.add_argument("--input", type=Path, help="Import JSON, Feishu CSV, or directory of daily digests, depending on mode")
    parser.add_argument("--reviews", type=Path, help="Reviewed Feishu ordinary-sheet CSV export; digest mode only")
    parser.add_argument("--out", type=Path, help="New output directory; default .runs/<timestamp>")
    parser.add_argument("--limit-per-sub", type=int, default=300)
    parser.add_argument("--ai", action="store_true", help="Optional DeepSeek wording; requires separate Reddit AI-processing approval")
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    try:
        if args.mode == "purge-feishu":
            from .feishu_sheets import cleanup_expired_feishu_rows

            result = cleanup_expired_feishu_rows(
                app_id=os.environ.get("FEISHU_APP_ID", ""),
                app_secret=os.environ.get("FEISHU_APP_SECRET", ""),
                spreadsheet_token=os.environ.get("FEISHU_SPREADSHEET_TOKEN", ""),
                sheet_id=os.environ.get("FEISHU_SHEET_ID", ""),
                now=now,
            )
            print(f"Feishu queue retention: {result['expired']} expired rows cleared, "
                  f"{result['retained']} retained; no Reddit API access")
            return 0
        if args.mode == "sync-feishu":
            from .feishu_sheets import sync_feishu_sheet

            if not args.input or not args.input.is_file() or args.input.stat().st_size > 2_000_000:
                raise ValueError("--input must be an existing Feishu review CSV smaller than 2 MB.")
            result = sync_feishu_sheet(
                args.input.read_text(encoding="utf-8"),
                reddit_approved=os.environ.get("REDDIT_APPROVAL_CONFIRMED") == "true"
                and bool(os.environ.get("REDDIT_APPROVAL_REFERENCE", "").strip()),
                feishu_sharing_approved=os.environ.get("REDDIT_FEISHU_SHARING_APPROVED") == "true",
                approval_ref=os.environ.get("REDDIT_FEISHU_APPROVAL_REFERENCE", ""),
                app_id=os.environ.get("FEISHU_APP_ID", ""),
                app_secret=os.environ.get("FEISHU_APP_SECRET", ""),
                spreadsheet_token=os.environ.get("FEISHU_SPREADSHEET_TOKEN", ""),
                sheet_id=os.environ.get("FEISHU_SHEET_ID", ""),
                now=now,
            )
            print(f"Feishu queue synced: {result['added']} added, {result['retained']} retained, "
                  f"{result['expired']} expired; no Reddit write actions")
            return 0
        if args.mode == "digest":
            from .review_import import parse_feishu_review_csv
            from .weekly import make_daily_digest

            _approval()
            if not args.input or not args.reviews or not args.reviews.is_file() or args.reviews.stat().st_size > 2_000_000:
                raise ValueError("--input approved opportunities JSON and --reviews Feishu CSV (<2 MB) are required.")
            run = _read_json(args.input)
            if not isinstance(run, dict):
                raise ValueError("--input must contain a daily run object.")
            generated = datetime.fromisoformat(str(run.get("generated_at", "")).replace("Z", "+00:00"))
            if generated.tzinfo is None or generated.utcoffset() is None or not timedelta(0) <= now - generated <= timedelta(hours=48):
                raise ValueError("Daily run must be within its 48-hour raw-data retention window.")
            reviews = parse_feishu_review_csv(args.reviews.read_text(encoding="utf-8-sig"), run)
            digest = make_daily_digest(run, reviews)
            out = args.out or Path(".runs") / now.strftime("review-digest-%Y%m%dT%H%M%SZ")
            out.mkdir(parents=True, exist_ok=False)
            path = out / "daily_digest.json"
            path.write_text(json.dumps(digest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            path.chmod(0o600)
            print(f"Reviewed daily digest ready: {path.resolve()} ({len(reviews)} reviewed row(s); no raw thread content copied)")
            return 0
        if args.mode == "weekly":
            from .weekly import aggregate_weekly_digests, render_weekly_markdown

            if not args.input or not args.input.is_dir():
                raise ValueError("--input must be a directory of retention-safe daily digest JSON files.")
            paths = sorted(args.input.glob("*.json"))
            if not paths or len(paths) > 31:
                raise ValueError("Provide 1–31 daily digest JSON files in --input.")
            report = aggregate_weekly_digests([_read_json(path) for path in paths], now=now)
            out = args.out or Path(".runs") / now.strftime("weekly-%Y%m%dT%H%M%SZ")
            out.mkdir(parents=True, exist_ok=False)
            for name, content in {
                "weekly.md": render_weekly_markdown(report),
                "weekly.json": json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            }.items():
                path = out / name
                path.write_text(content, encoding="utf-8")
                path.chmod(0o600)
            print(f"Weekly digest ready: {out.resolve()} ({report['run_count']} daily digest(s))")
            return 0
        if args.mode == "demo":
            if args.ai:
                raise ValueError("--ai is only available for approved real-data runs, not the synthetic demo.")
            posts, config = _demo(now)
            source = "SYNTHETIC DEMO — no real Reddit data"
        else:
            _approval()
            if args.ai and (os.environ.get("REDDIT_AI_PROCESSING_APPROVED") != "true"
                            or not os.environ.get("REDDIT_AI_APPROVAL_REFERENCE", "").strip()
                            or not os.environ.get("DEEPSEEK_API_KEY", "").strip()):
                raise ValueError("--ai requires REDDIT_AI_PROCESSING_APPROVED=true, REDDIT_AI_APPROVAL_REFERENCE, and DEEPSEEK_API_KEY; Reddit approval must cover third-party processing.")
            config = _configuration(args.config)
            if args.mode == "import":
                if not args.input:
                    raise ValueError("--input is required for import mode.")
                posts = _read_json(args.input)
                source = "User-supplied export under Reddit-approved use case"
            else:
                from .reddit_client import fetch_new_posts
                posts = fetch_new_posts(
                    config["target_subreddits"], client_id=os.environ.get("REDDIT_CLIENT_ID", ""),
                    client_secret=os.environ.get("REDDIT_CLIENT_SECRET", ""),
                    user_agent=os.environ.get("REDDIT_USER_AGENT", ""),
                    approval_confirmed=True, now=now, limit_per_sub=args.limit_per_sub,
                )
                source = "Reddit OAuth Data API — approved use only"
        if not isinstance(posts, list):
            raise ValueError("Input JSON must be an array of post objects.")
        run = evaluate_posts(posts, config, now=now, source=source)
        if args.ai:
            from .ai import enrich_selected
            enrich_selected(
                run, posts, config,
                reddit_approved=True,
                ai_processing_approved=os.environ.get("REDDIT_AI_PROCESSING_APPROVED") == "true",
                ai_approval_reference=os.environ.get("REDDIT_AI_APPROVAL_REFERENCE", ""),
                api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            )
        if args.mode == "demo":
            run["limitations"].insert(0, "Everything in this report is synthetic; community names, rules, posts and product facts are not real.")
        out = args.out or Path(".runs") / now.strftime("%Y%m%dT%H%M%SZ")
        _write(run, out)
        print(f"Report ready: {out.resolve()} ({run['counts']['selected']} opportunities; no Reddit write actions)")
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"Run stopped: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        from .feishu_sheets import FeishuSyncError
        from .reddit_client import RedditAccessError
        if isinstance(exc, FeishuSyncError):
            print(f"Feishu sync stopped: {exc}", file=sys.stderr)
            return 4
        if isinstance(exc, RedditAccessError):
            print(f"Reddit read stopped: {exc}", file=sys.stderr)
            return 3
        raise


if __name__ == "__main__":
    raise SystemExit(main())
