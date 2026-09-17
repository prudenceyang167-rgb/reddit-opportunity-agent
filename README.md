# Reddit Opportunity Agent

Personal project by [prudenceyang167-rgb](https://github.com/prudenceyang167-rgb). This is an independent, read-only opportunity screener for OJO—not an official Reddit product. It **never posts, comments, votes, or sends messages**. A human must review the full thread, the current community rules, the product claim, and the proposed reply before publishing anything manually.

## What works now

- Scores a **synthetic demo** with a 24-hour window, ICP fit, problem fit, discussion timing/engagement, and promotion risk.
- Produces a short P0/P1/P2 opportunity list in Markdown, CSV, and JSON. Each selected thread has a summary, core question, evidence, action, reply angle, and draft (P2 has no reply draft because participation is not recommended).
- Provides an approved-only OAuth Data API adapter for `/r/{sub}/new`, capped and paginated. Incomplete 24-hour coverage fails visibly; it does not silently claim to have seen everything.
- Optionally uses DeepSeek to improve summaries and draft wording **only when a separate written approval covers sending Reddit post text to an external AI provider**. The AI cannot change score, priority, or permission gates. The default is off.
- Runs offline tests in GitHub Actions. The daily 09:17 China-time workflow is installed but **skips live scans until the Reddit approval and credentials are configured**. A manual synthetic demo can be run in Actions today.

## Why live Reddit scanning is disabled

Reddit's [Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy) requires explicit approval before API access. [Commercial-use guidance](https://support.reddithelp.com/hc/en-us/articles/14945211791892-Developer-Platform-Accessing-Reddit-Data) says business/on-behalf-of-business use needs Reddit permission and a contract. OJO opportunity monitoring is a commercial use case. The [Data API Wiki](https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki) also requires OAuth, a truthful User-Agent, rate-limit compliance and prompt deletion of removed user content. Anonymous `.json`, RSS, third-party scraping, or manual bulk export are **not** used as workarounds.

Before a real run, obtain written approval for this precise monitoring purpose, its target communities, retention, report sharing, and any external AI processing. DeepSeek is disabled unless an additional approval reference specifically covers sending post title/body to that provider. Check the name “Reddit Opportunity Agent” in the access request as Reddit's [Data API Terms](https://redditinc.com/policies/data-api-terms) restrict use of its marks in app names. No real data or credentials have been accessed or embedded in this repository.

## Run the synthetic demo

Requires Python 3.9+; no third-party packages are needed.

```bash
python -m unittest discover -s tests -v
python -m reddit_opportunity_agent.cli demo
```

The command prints a new `.runs/<timestamp>/` path. Open `opportunities.md`, `opportunities.csv`, or `opportunities.json`. Everything in this demo—including subreddit names, rule evidence, posts, and the product capability—is fictional. The report is a UI/process demonstration, not an OJO recommendation or a real Reddit opportunity.

## After Reddit grants approval

1. Copy `config.example.json` to `config.local.json`. Fill in approved target subreddits (maximum 20), verified OJO product facts, and per-subreddit promotion policies. Never interpret “rules do not mention promotion” as permission. `may_mention` requires a human-recorded evidence URL and a check within the past 30 days; stale/missing evidence downgrades to unknown. Product mentions also require a relevant user question and explicit ICP match.
2. Register the approved OAuth app and set `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, and a truthful `REDDIT_USER_AGENT` (`platform:app:v1.0 (by /u/your_reddit_username)`). Set `REDDIT_APPROVAL_CONFIRMED=true` and a specific `REDDIT_APPROVAL_REFERENCE` describing the written permission. These are configuration attestations, not a substitute for permission.
3. Run `python -m reddit_opportunity_agent.cli live --config config.local.json`. For approved exports, use `import --input approved-posts.json --config config.local.json` instead. A real-data import also requires the approval gate; it is **not** a licensing workaround.
4. Inspect the full live thread and current subreddit rules. P0 means potentially mention OJO *with affiliation disclosure*, not automatic permission. P1 contributes a useful answer without mentioning OJO. P2 is research only. Never paste a draft without editing it.

Optional DeepSeek wording: only if the Reddit permission **explicitly covers third-party AI processing**, set `REDDIT_AI_PROCESSING_APPROVED=true`, `REDDIT_AI_APPROVAL_REFERENCE` (the written permission reference), and `DEEPSEEK_API_KEY`, then add `--ai` to the approved `live` or `import` command. The [DeepSeek JSON Output API](https://api-docs.deepseek.com/guides/json_mode/) is used for concise summaries, questions, reply angles, and advice. Only selected post titles and up to 1,200 characters of body are transmitted; no usernames or Reddit author IDs are sent. Failed/unsafe AI responses fall back to the deterministic draft. It cannot upgrade a P1/P2 to P0, authorize product mentions, or publish. Without this separate permission, leave these settings unset.

The scheduled GitHub Action additionally needs repository variable `REDDIT_APPROVAL_CONFIRMED=true`; variable `REDDIT_TARGET_SUBREDDITS` as comma-separated approved communities; secrets `REDDIT_APPROVAL_REFERENCE`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`, and `REPORT_ENCRYPTION_KEY` (a long random passphrase). Optional secrets: `OJO_VERIFIED_FACTS_JSON` (JSON array) and `REDDIT_PROMOTION_POLICIES_JSON` (JSON object). For optional DeepSeek, set variable `REDDIT_AI_PROCESSING_APPROVED=true` plus secrets `REDDIT_AI_APPROVAL_REFERENCE` and `DEEPSEEK_API_KEY`. Missing promotion evidence or product facts means **no product mention**. No live report is published in a public Issue or comment. The Action uploads only an encrypted report artifact, retained for one day. Download it from the run and decrypt locally:

```bash
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
  -in opportunities.tar.gz.enc -out opportunities.tar.gz \
  -pass env:REPORT_ENCRYPTION_KEY
tar -xzf opportunities.tar.gz
```

Store the decryption key only as a GitHub Actions secret and in your own secure password manager—not in repository files, terminal history, screenshots, or chat. GitHub's schedule can be delayed and public-repository schedules may be disabled after inactivity; check the run's status each morning. This project does not guarantee a daily delivery without active approved access and working credentials.

## Scoring and safety

Opportunity Score is an explainable 0–100 heuristic: ICP (0–25), pain/problem fit (0–35), discussion value (0–25), and promotion eligibility (0–15). P0 requires score ≥75, a strong ICP and problem match, a user asking a relevant question, verified product facts, and fresh human-recorded community-rule evidence. P1 requires score ≥55 and good problem fit; otherwise P2. These are not predictions of conversion or statements of moderator permission. The top eight are returned by default; duplicates, old posts, locked/stickied/NSFW/removed posts, and unrelated communities are excluded.

Real Reddit content can be deleted at any time. Do not commit reports, inputs, user names, or tokens. `.runs/` is ignored by Git; delete local reports promptly (Reddit recommends retention under 48 hours) and re-check a post's live status before use. GitHub encrypted artifacts expire after one day. The code never stores Reddit authors or profile details. Rendering neutralizes Markdown/HTML injection and CSV formula injection; links are restricted to Reddit post URLs.

The draft is a starting point, not an accurate claim by default. It uses general advice and only inserts a product fact supplied as verified input. No social posting endpoints exist in this codebase. DeepSeek text remains untrusted and human review is mandatory.
