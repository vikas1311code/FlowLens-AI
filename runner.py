"""
runner.py
Week 1 entry point.
Runs an autonomous crawl session on any URL:
  1. Navigate to URL
  2. Collect page info (links, buttons, text)
  3. Click through every found link/button (up to max_steps)
  4. Detect anomalies at every step
  5. Save session log + markdown bug report

Usage:
    python runner.py https://example.com
    python runner.py https://example.com --steps 30
"""
import asyncio
import argparse
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from core.browser  import BrowserSession
from core.anomaly  import AnomalyDetector
from core.reporter import generate_report, save_anomalies_json


async def run_session(target_url: str, max_steps: int = 20) -> dict:
    session_id = f"pvos_{int(time.time())}"
    print(f"\n{'='*55}")
    print(f"  ProductValidation OS — Week 1 Crawler")
    print(f"  Session : {session_id}")
    print(f"  Target  : {target_url}")
    print(f"  Max steps: {max_steps}")
    print(f"{'='*55}\n")

    session  = BrowserSession(session_id=session_id, headless=True)
    detector = AnomalyDetector()
    anomalies: list = []
    visited_urls: set = set()
    prev_b64: str | None = None

    base_domain = urlparse(target_url).netloc

    await session.start()

    try:
        # ── Step 1: land on the page ────────────────────────────────────
        entry = await session.navigate(target_url)
        visited_urls.add(session.page.url)
        curr_b64 = session.get_latest_screenshot_b64()

        page_info = await session.get_page_info()
        found = detector.run_all(entry, prev_b64, curr_b64, session.js_errors, page_info)
        anomalies.extend(found)
        if found:
            for f in found: print(f"  ⚠ ANOMALY: [{f['severity'].upper()}] {f['type']} — {f['detail'][:80]}")

        prev_b64 = curr_b64
        steps_done = 1

        # ── Step 2: autonomous exploration loop ─────────────────────────
        while steps_done < max_steps:
            page_info = await session.get_page_info()
            current_url = page_info["url"]

            # collect candidate actions (links + buttons)
            candidates = []

            for link in page_info.get("links", []):
                href = link.get("href", "")
                lurl = urlparse(href)
                # stay on same domain, skip already visited, skip anchors/mailto
                if (lurl.netloc == base_domain or lurl.netloc == "") \
                        and href not in visited_urls \
                        and not href.startswith("mailto:") \
                        and not href.startswith("tel:") \
                        and lurl.fragment == "":
                    candidates.append(("link", href, link.get("text", "")))

            for btn_text in page_info.get("buttons", []):
                if btn_text:
                    candidates.append(("button", btn_text, btn_text))

            if not candidates:
                print(f"  [crawler] No more candidates at step {steps_done}. Scrolling down.")
                entry = await session.scroll("down")
                steps_done += 1
                page_info2 = await session.get_page_info()
                if page_info2["url"] == current_url and len(page_info2.get("links",[])) == 0:
                    print("  [crawler] Nothing new after scroll. Stopping.")
                    break
                continue

            # pick the next unvisited link
            action_taken = False
            for kind, target, label in candidates:
                if steps_done >= max_steps:
                    break

                if kind == "link" and target not in visited_urls:
                    entry = await session.navigate(target)
                    visited_urls.add(session.page.url)
                    action_taken = True
                elif kind == "button" and label:
                    # try to click by button text
                    selector = f"button:has-text('{label[:40]}')"
                    entry = await session.click(selector, description=label)
                    action_taken = True

                if action_taken:
                    curr_b64 = session.get_latest_screenshot_b64()
                    pi = await session.get_page_info()
                    found = detector.run_all(
                        entry, prev_b64, curr_b64,
                        session.js_errors[-3:], pi
                    )
                    anomalies.extend(found)
                    if found:
                        for f in found:
                            print(f"  ⚠ ANOMALY [{f['severity'].upper()}] {f['type']}: {f['detail'][:80]}")
                    prev_b64 = curr_b64
                    steps_done += 1
                    break   # one action per loop iteration

            if not action_taken:
                print(f"  [crawler] No new actions available. Done at step {steps_done}.")
                break

        print(f"\n[done] {steps_done} steps completed. {len(anomalies)} anomalies found.")

    finally:
        log_path = session.save_session_log()
        anomaly_path = save_anomalies_json(session_id, anomalies)
        report = generate_report(
            session_id=session_id,
            target_url=target_url,
            actions_log=session.actions_log,
            anomalies=anomalies,
            page_info=await session.get_page_info() if session.page else None,
        )
        await session.stop()

    # ── print summary ────────────────────────────────────────────────────
    print(f"\n{'='*55}")
    print(f"  SUMMARY")
    print(f"{'='*55}")
    high   = [a for a in anomalies if a["severity"] == "high"]
    medium = [a for a in anomalies if a["severity"] == "medium"]
    print(f"  Total steps   : {steps_done}")
    print(f"  Bugs found    : {len(anomalies)}  (🔴 {len(high)} high  🟡 {len(medium)} medium)")
    print(f"  Session log   : {log_path}")
    print(f"  Anomalies JSON: {anomaly_path}")
    print(f"  Report        : outputs/reports/{session_id}_report.md")
    print(f"{'='*55}\n")

    return {
        "session_id": session_id,
        "steps": steps_done,
        "anomalies": anomalies,
        "report": report,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ProductValidation OS — autonomous crawler")
    parser.add_argument("url",   help="Target URL to crawl (e.g. https://example.com)")
    parser.add_argument("--steps", type=int, default=20, help="Max steps (default 20)")
    args = parser.parse_args()

    asyncio.run(run_session(args.url, args.steps))
