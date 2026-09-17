"""Public, synthetic-only dashboard for Vercel.

Real Reddit reports are intentionally never loaded by this module. Approved
daily runs stay in the private/encrypted GitHub Actions artifact workflow.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone

from .cli import _demo
from .scoring import evaluate_posts


def demo_run(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    posts, config = _demo(now)
    run = evaluate_posts(posts, config, now=now, source="SYNTHETIC DEMO — no real Reddit data")
    run["limitations"].insert(0, "All posts, community names, rules, and product facts here are fictional examples.")
    return run


def _e(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def render_dashboard(run: dict) -> str:
    """Render only a synthetic run; reject accidental real-data publication."""
    if not str(run.get("source", "")).startswith("SYNTHETIC DEMO"):
        raise ValueError("The public dashboard only accepts synthetic data.")
    rows = run.get("opportunities", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Invalid demo opportunity data.")
    priority_counts = {name: sum(row.get("priority") == name for row in rows) for name in ("P0", "P1", "P2")}
    cards = []
    for row in rows:
        priority = row.get("priority") if row.get("priority") in {"P0", "P1", "P2"} else "P2"
        scores = row.get("score_breakdown", {})
        if not isinstance(scores, dict):
            scores = {}
        components = "".join(
            f'<div class="score-part"><span>{_e(label)}</span><strong>{_e(scores.get(key, 0))}/{maximum}</strong></div>'
            for label, key, maximum in (("ICP", "icp", 25), ("Problem", "pain", 35),
                                        ("Discussion", "discussion", 25), ("Promotion", "promotion", 15))
        )
        draft = row.get("comment_draft") or "No comment suggested. Keep this for research and content ideas."
        cards.append(f'''
        <article class="opportunity">
          <div class="card-top"><span class="priority {priority.lower()}">{_e(priority)}</span>
            <span class="community">r/{_e(row.get("subreddit"))} · synthetic</span>
            <span class="total">{_e(row.get("score"))}<small>/100</small></span></div>
          <h3>{_e(row.get("title"))}</h3>
          <div class="tags"><span>{_e(row.get("icp"))}</span><span>{_e(row.get("pain_point"))}</span>
            <span>{_e(row.get("action", "research_only")).replace("_", " ")}</span></div>
          <p class="summary">{_e(row.get("summary"))}</p>
          <div class="question"><span>Core question</span><p>{_e(row.get("core_question"))}</p></div>
          <div class="score-grid">{components}</div>
          <div class="angle"><span>Reply angle</span><p>{_e(row.get("reply_angle"))}</p></div>
          <details><summary>Review suggested comment draft</summary><p class="draft">{_e(draft)}</p>
            <p class="review-note">Draft only. Read the full real thread, check current community rules and product claims, then edit and post manually.</p></details>
        </article>''')
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Reddit Opportunity Agent · Synthetic Demo</title>
<style>
:root{{--ink:#192528;--muted:#657276;--paper:#f5f4ef;--card:#fff;--line:#dce2df;--teal:#0d6b62;--orange:#e8683d}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;line-height:1.55}}
a{{color:inherit}}.shell{{max-width:1120px;margin:auto;padding:0 28px}}header{{border-bottom:1px solid var(--line);background:#fff}}
.nav{{display:flex;align-items:center;justify-content:space-between;min-height:72px;gap:18px}}.brand{{font-weight:800;letter-spacing:-.04em;font-size:19px}}
.nav a{{font-size:13px;text-decoration:none;color:var(--teal);font-weight:700}}.hero{{padding:70px 0 48px}}
.eyebrow{{font-size:11px;letter-spacing:.14em;text-transform:uppercase;font-weight:800;color:var(--teal)}}h1{{font-size:clamp(36px,6vw,68px);line-height:1.02;letter-spacing:-.065em;max-width:800px;margin:16px 0 20px}}
.lede{{color:var(--muted);font-size:18px;max-width:680px;margin:0}}.notice{{margin-top:30px;padding:16px 18px;border:1px solid #e8cda9;border-radius:12px;background:#fff4e4;color:#68422d;font-size:14px}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:32px 0 50px}}.metric{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:18px 20px}}
.metric strong{{display:block;font-size:29px;line-height:1.15;letter-spacing:-.05em}}.metric span{{display:block;color:var(--muted);font-size:12px;margin-top:7px}}
.section-head{{display:flex;justify-content:space-between;align-items:end;gap:20px;margin-bottom:20px}}h2{{font-size:27px;letter-spacing:-.04em;margin:0}}.section-head p{{color:var(--muted);font-size:13px;margin:0}}
.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;padding-bottom:70px}}.opportunity{{background:#fff;border:1px solid var(--line);border-radius:18px;padding:24px;box-shadow:0 8px 30px rgba(30,53,47,.03)}}
.card-top{{display:flex;align-items:center;gap:10px}}.priority{{font-size:11px;font-weight:900;letter-spacing:.08em;border-radius:5px;padding:4px 8px;background:#e4efed;color:#07544c}}
.priority.p0{{background:#fbe9e0;color:#ad3d19}}.priority.p2{{background:#edf0ef;color:#536260}}.community{{font-size:12px;color:var(--muted)}}.total{{margin-left:auto;font-weight:850;font-size:25px;letter-spacing:-.05em}}
.total small{{font-size:12px;color:var(--muted);font-weight:500}}h3{{font-size:22px;letter-spacing:-.035em;line-height:1.25;margin:18px 0 12px}}.tags{{display:flex;flex-wrap:wrap;gap:6px}}.tags span{{font-size:11px;background:#f0f4f2;border-radius:99px;padding:4px 9px;color:#4b615c}}
.summary{{color:#4c595d;font-size:14px;margin:20px 0}}.question,.angle{{border-top:1px solid var(--line);padding-top:14px;margin-top:14px}}.question span,.angle span{{font-size:11px;letter-spacing:.1em;text-transform:uppercase;font-weight:800;color:var(--teal)}}
.question p,.angle p{{font-size:14px;margin:6px 0 0}}.score-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:20px}}.score-part{{background:#f4f6f4;border-radius:8px;padding:9px 8px;text-align:center}}
.score-part span{{display:block;font-size:10px;color:var(--muted)}}.score-part strong{{display:block;font-size:13px;margin-top:2px}}details{{margin-top:18px;background:#f6f8f6;border-radius:9px;padding:12px 14px}}
summary{{cursor:pointer;font-size:13px;font-weight:700;color:var(--teal)}}.draft{{font-size:13px;white-space:pre-wrap}}.review-note{{font-size:11px;color:var(--muted);margin-bottom:0}}footer{{border-top:1px solid var(--line);padding:25px 0 40px;color:var(--muted);font-size:12px}}
@media(max-width:760px){{.hero{{padding:48px 0 28px}}.metrics{{grid-template-columns:repeat(2,1fr);margin:28px 0 38px}}.grid{{grid-template-columns:1fr}}.section-head{{display:block}}.section-head p{{margin-top:4px}}}}
@media(max-width:420px){{.shell{{padding:0 16px}}.nav{{min-height:62px}}.brand{{font-size:16px}}.metric{{padding:14px}}.opportunity{{padding:18px}}.score-grid{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body>
<header><div class="shell nav"><div class="brand">OJO / Reddit Opportunity Agent</div><a href="https://github.com/prudenceyang167-rgb/reddit-opportunity-agent" rel="noopener noreferrer">View GitHub ↗</a></div></header>
<main class="shell"><section class="hero"><div class="eyebrow">Human-reviewed opportunity intelligence</div>
<h1>Find the right conversations before they peak.</h1>
<p class="lede">每天筛出少量值得参与的讨论，解释用户匹配、问题匹配、讨论价值和推广风险。最终回复始终由人审核和发布。</p>
<div class="notice"><strong>模拟演示 · 非实时 Reddit 数据。</strong> 真实扫描仍需 Reddit 对商业用途的书面授权；本页面不会抓取、展示或发布真实 Reddit 内容。</div></section>
<section class="metrics" aria-label="Demo summary"><div class="metric"><strong>24h</strong><span>Screening window</span></div>
<div class="metric"><strong>{len(rows)}</strong><span>Synthetic opportunities</span></div>
<div class="metric"><strong>{priority_counts['P0']}/{priority_counts['P1']}/{priority_counts['P2']}</strong><span>P0 / P1 / P2</span></div>
<div class="metric"><strong>0</strong><span>Automated posts</span></div></section>
<section><div class="section-head"><h2>Opportunity list</h2><p>Scored examples · generated {_e(run.get('generated_at'))}</p></div>
<div class="grid">{''.join(cards)}</div></section></main>
<footer><div class="shell">Independent personal project by prudenceyang167-rgb. Not an official Reddit product. All examples are fictional; no comment has been posted.</div></footer>
</body></html>'''
