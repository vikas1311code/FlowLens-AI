"""
runner_week2.py
Week 2 entry point.
Combines:
  - Week 1: Playwright autonomous crawler
  - Week 2: Gemini Vision analysis of every screenshot
  - Week 2: PRD Parser (optional --prd flag)

Usage:
  python runner_week2.py http://localhost:5001 --steps 15
  python runner_week2.py http://localhost:5001 --steps 15 --prd my_prd.md
"""
import asyncio
import argparse
import time
import json
from pathlib import Path

from core.browser   import BrowserSession
from core.anomaly   import AnomalyDetector
from core.reporter  import generate_report, save_anomalies_json
from agents.vision_agent import VisionAgent
from agents.prd_parser   import PRDParser

REPORTS_DIR = Path("outputs/reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def save_vision_report(session_id: str, vision_agent: VisionAgent,
                       prd_coverage: dict | None) -> str:
    """Save a combined vision + PRD markdown report."""

    summary  = vision_agent.get_summary()
    all_bugs = vision_agent.get_all_bugs()
    analyses = vision_agent.analyses

    lines = [
        "# ProductValidation OS — Vision Analysis Report",
        "",
        "## Session Summary",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Pages analyzed | {summary['pages_analyzed']} |",
        f"| Critical pages | 🔴 {summary['critical_pages']} |",
        f"| Warning pages  | 🟡 {summary['warning_pages']} |",
        f"| Good pages     | ✅ {summary['good_pages']} |",
        f"| Total bugs (AI-detected) | {summary['total_bugs']} |",
        f"| High severity bugs | {summary['high_bugs']} |",
        "",
    ]

    if prd_coverage:
        lines += [
            "## PRD Coverage",
            "",
            f"| Metric | Value |",
            f"|---|---|",
            f"| Coverage | **{prd_coverage['coverage_pct']}%** |",
            f"| Pages tested | {prd_coverage['pages_tested']} |",
            f"| User stories | {prd_coverage['total_stories']} |",
            "",
        ]
        if prd_coverage.get("uncovered_pages"):
            lines.append("**Untested pages:**")
            for p in prd_coverage["uncovered_pages"]:
                lines.append(f"- ❌ `{p['path']}` — {p['name']}")
            lines.append("")

    if all_bugs:
        lines += ["## 🐛 AI-Detected Bugs", ""]
        for i, b in enumerate(all_bugs, 1):
            sev   = b.get("severity", "?")
            emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(sev, "⚪")
            lines += [
                f"### Bug {i}: {emoji} {b.get('type', 'Unknown')}",
                f"- **Severity**: {sev.upper()}",
                f"- **URL**: {b.get('url', '')}",
                f"- **Step**: {b.get('step', '?')}",
                f"- **Description**: {b.get('description', '')}",
                "",
            ]

    lines += ["## 📄 Page-by-Page Analysis", ""]
    for a in analyses:
        health = a.get("overall_health", "?")
        emoji  = {"good": "✅", "warning": "⚠️", "critical": "🔴"}.get(health, "❓")
        lines += [
            f"### Step {a['step']}: {emoji} {a.get('page_description', 'Unknown page')}",
            f"**URL**: `{a.get('url', '')}`  |  **Health**: {health}",
            "",
        ]
        if a.get("ux_issues"):
            lines.append("**UX Issues:**")
            for issue in a["ux_issues"]:
                lines.append(f"- {issue}")
            lines.append("")
        if a.get("summary"):
            lines += [f"**AI Summary**: {a['summary']}", ""]

    report = "\n".join(lines)
    out    = REPORTS_DIR / f"{session_id}_vision_report.md"
    out.write_text(report)
    print(f"[vision report saved] {out}")
    return report


async def run_week2(target_url: str, max_steps: int = 15,
                    prd_path: str | None = None) -> dict:

    session_id   = f"pvos_w2_{int(time.time())}"
    session      = BrowserSession(session_id=session_id, headless=True)
    detector     = AnomalyDetector()
    vision_agent = VisionAgent()
    prd_parser   = PRDParser() if prd_path else None

    anomalies:    list = []
    visited_urls: list = []
    prev_b64:     str | None = None

    print(f"\n{'='*55}")
    print(f"  ProductValidation OS — Week 2")
    print(f"  Session : {session_id}")
    print(f"  Target  : {target_url}")
    print(f"  Max steps: {max_steps}")
    print(f"  Vision  : Gemini 2.5 Flash ✅")
    print(f"  PRD     : {prd_path or 'None (use --prd to add)'}")
    print(f"{'='*55}\n")

    # parse PRD if provided
    if prd_parser and prd_path:
        prd_parser.parse_file(prd_path)

    from urllib.parse import urlparse
    base_domain = urlparse(target_url).netloc

    await session.start()

    try:
        # ── initial navigation ───────────────────────────────────────────
        entry = await session.navigate(target_url)
        visited_urls.append(session.page.url)
        curr_b64  = session.get_latest_screenshot_b64()
        page_info = await session.get_page_info()

        # run anomaly detectors
        found = detector.run_all(entry, prev_b64, curr_b64, session.js_errors, page_info)
        anomalies.extend(found)

        # run vision analysis on first screenshot
        shot_files = sorted(Path("outputs/screenshots").glob(f"{session_id}_*.png"))
        if shot_files:
            vision_agent.analyze_screenshot(str(shot_files[-1]), entry["step"], session.page.url)

        prev_b64   = curr_b64
        steps_done = 1

        # ── exploration loop ─────────────────────────────────────────────
        while steps_done < max_steps:
            page_info   = await session.get_page_info()
            current_url = page_info["url"]

            candidates = []
            for link in page_info.get("links", []):
                href = link.get("href", "")
                lurl = urlparse(href)
                if (lurl.netloc == base_domain or lurl.netloc == "") \
                        and href not in visited_urls \
                        and not href.startswith(("mailto:", "tel:")) \
                        and lurl.fragment == "":
                    candidates.append(("link", href, link.get("text", "")))

            for btn in page_info.get("buttons", []):
                if btn:
                    candidates.append(("button", btn, btn))

            if not candidates:
                entry = await session.scroll("down")
                steps_done += 1
                pi2 = await session.get_page_info()
                if pi2["url"] == current_url and not pi2.get("links"):
                    break
                continue

            action_taken = False
            for kind, target, label in candidates:
                if steps_done >= max_steps:
                    break

                if kind == "link" and target not in visited_urls:
                    entry = await session.navigate(target)
                    visited_urls.append(session.page.url)
                    action_taken = True
                elif kind == "button" and label:
                    selector = f"button:has-text('{label[:40]}')"
                    entry = await session.click(selector, description=label)
                    action_taken = True

                if action_taken:
                    curr_b64 = session.get_latest_screenshot_b64()
                    pi       = await session.get_page_info()

                    # anomaly detection
                    found = detector.run_all(
                        entry, prev_b64, curr_b64,
                        session.js_errors[-3:], pi
                    )
                    anomalies.extend(found)
                    if found:
                        for f in found:
                            print(f"  ⚠ [{f['severity'].upper()}] {f['type']}: {f['detail'][:70]}")

                    # vision analysis on every step
                    shot_files = sorted(Path("outputs/screenshots").glob(f"{session_id}_*.png"))
                    if shot_files:
                        vision_agent.analyze_screenshot(
                            str(shot_files[-1]), entry["step"], session.page.url
                        )

                    prev_b64   = curr_b64
                    steps_done += 1
                    break

            if not action_taken:
                break

        print(f"\n[done] {steps_done} steps. "
              f"{len(anomalies)} rule-based anomalies + "
              f"{len(vision_agent.get_all_bugs())} AI-detected bugs.")

    finally:
        # PRD coverage check
        prd_coverage = None
        if prd_parser and prd_parser.requirements:
            prd_coverage = prd_parser.check_coverage(
                visited_urls, vision_agent.analyses
            )

        # save all reports
        session.save_session_log()
        save_anomalies_json(session_id, anomalies)

        # combined anomalies: rule-based + AI vision bugs
        all_bugs = anomalies + vision_agent.get_all_bugs()
        generate_report(
            session_id=session_id,
            target_url=target_url,
            actions_log=session.actions_log,
            anomalies=all_bugs,
        )
        save_vision_report(session_id, vision_agent, prd_coverage)

        # save vision analyses as JSON too
        vision_json = REPORTS_DIR / f"{session_id}_vision_analyses.json"
        vision_json.write_text(json.dumps(vision_agent.analyses, indent=2))

        await session.stop()

    # final summary
    v_summary = vision_agent.get_summary()
    print(f"\n{'='*55}")
    print(f"  WEEK 2 SUMMARY")
    print(f"{'='*55}")
    print(f"  Steps run           : {steps_done}")
    print(f"  Pages analyzed (AI) : {v_summary['pages_analyzed']}")
    print(f"  Rule-based bugs     : {len(anomalies)}")
    print(f"  AI-detected bugs    : {v_summary['total_bugs']} ({v_summary['high_bugs']} high)")
    if prd_coverage:
        print(f"  PRD coverage        : {prd_coverage['coverage_pct']}%")
    print(f"  Reports saved in    : outputs/reports/")
    print(f"{'='*55}\n")

    return {
        "session_id":   session_id,
        "steps":        steps_done,
        "anomalies":    len(anomalies),
        "ai_bugs":      v_summary["total_bugs"],
        "prd_coverage": prd_coverage,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ProductValidation OS — Week 2")
    parser.add_argument("url",     help="Target URL")
    parser.add_argument("--steps", type=int, default=15, help="Max steps (default 15)")
    parser.add_argument("--prd",   type=str, default=None, help="Path to PRD markdown file")
    args = parser.parse_args()

    asyncio.run(run_week2(args.url, args.steps, args.prd))
