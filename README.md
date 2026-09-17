# OJO Community Opportunity Agent

Personal project by [prudenceyang167-rgb](https://github.com/prudenceyang167-rgb). An independent, read-only Reddit opportunity screener—not an official Reddit product. It never posts, comments, votes, or sends messages. A person reads the original discussion and current community rules, edits any suggested reply, and publishes manually.

## Current operating status

The public [Vercel dashboard](https://reddit-opportunity-agent.vercel.app/) is a **synthetic demonstration**, not a live Reddit feed. It offers a [Feishu ordinary-spreadsheet review template](https://reddit-opportunity-agent.vercel.app/api?format=feishu-csv) and a [community-rule checklist](https://reddit-opportunity-agent.vercel.app/api?format=rules-csv). The scheduled run, local CLI, Feishu sync, and optional DeepSeek wording are implemented and tested with offline/mocked data. **No real Reddit scan or Feishu sync has been performed.**

The operator has not yet received Reddit's written approval for this OJO commercial use case. Until that approval is obtained and recorded, live scanning, importing real Reddit data, Feishu sharing, and sending post text to DeepSeek remain disabled. Anonymous JSON, RSS, scraping, or third-party exports are not fallback routes. See [Reddit's Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy), [commercial-use guidance](https://support.reddithelp.com/hc/en-us/articles/14945211791892-Developer-Platform-Accessing-Reddit-Data), and the [application form](https://support.reddithelp.com/hc/en-us/requests/new?tf_42139884615700=api_request_type_enterprise_clone&ticket_form_id=14868593862164).

## What the workflow does

1. Approved OAuth read of up to 20 approved subreddits' `/new` posts over the past 24 hours. Incomplete pagination fails visibly. The initial configuration lists 12 candidate communities from OJO's operating plan; inclusion is **not** permission or evidence of product-mention rules.
2. Deterministic, explainable classification of persona, use case, pain point, competitor, intent, and four score dimensions. Up to three daily opportunities are prioritized P0/P1/P2; P2 is research-only. All community rules start unknown, and a product mention needs recorded, fresh human rule evidence plus verified OJO facts. A suggested P0 is never permission to post or link.
3. Markdown/CSV/JSON exports and a dedicated 42-column Feishu ordinary-spreadsheet queue (`A1:AP10`, up to nine rows). The sync preserves reviewer edits, deduplicates threads, adds up to three new rows, and clears expired rows. A full queue fails visibly instead of dropping opportunities. It refuses unknown sheet layouts and requires separate written approval for Feishu sharing. Human-generalized insights enter weekly trends only with explicit attestation.
4. Optional DeepSeek `deepseek-flash` wording for already-selected posts, only when Reddit's written scope covers that third-party processing. It cannot change priority, product-mention permission, or posting status. Default: off.
5. A raw-free daily digest and weekly summary of screening categories and explicitly measured outcomes. Unmeasured referrals, signups, activations, or purchases stay “Not measured,” never invented as zero. Human-generalized themes require explicit attestation.

For the exact daily checklist, Feishu setup, command examples, and data-retention limits, see [Operations](docs/OPERATIONS.md). For the approval scope to request, see [Reddit access request](docs/REDDIT_ACCESS_REQUEST.md).

## Try the safe demo now

Python 3.9+; no third-party Python packages required:

```bash
python -m unittest discover -s tests -v
python -m reddit_opportunity_agent.cli demo
```

The command creates a new `.runs/<timestamp>/` folder containing `opportunities.md`, `opportunities.csv`, `opportunities.json`, `feishu_review.csv`, and `daily_digest.json`. Every post, community, rule, and product fact in this demo is fictional. `.runs/` and local credentials are excluded from Git. The Vercel deployment uses `api/index.py`; the public site has no live-data route or keys.

## Safety boundary

Reddit data access and sharing depend on the actual written scope, not on setting an environment variable. Keep real-data reports private, honor any shorter authorized retention, re-check the live post and current community rules before a manual reply, and delete raw content promptly. Feishu rows expire after 24 hours and are checked twice daily, but scheduler outages still need manual cleanup; encrypted Actions artifacts expire after one day. Do not put API keys, post data, Feishu sheet contents, or private reports in this public repository or Vercel. [Data API terms](https://redditinc.com/policies/data-api-terms) may also require Reddit's consent for the repository's existing name; the app display name has been changed to OJO Community Opportunity Agent, and the name should be included in the access request.
