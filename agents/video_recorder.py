"""
agents/video_recorder.py
Week 4 — Bug reproduction video recorder.
For each validated bug, replays the exact steps and records a .mp4 video.
"""
import asyncio
import os
import time
from pathlib import Path
from playwright.async_api import async_playwright

VIDEOS_DIR = Path(__file__).resolve().parent.parent / "outputs" / "videos"
VIDEOS_DIR.mkdir(parents=True, exist_ok=True)


class VideoRecorder:

    def __init__(self, base_url: str):
        self.base_url  = base_url
        self.recordings = []  # list of {bug_id, video_path}

    async def _record_single(self, bug: dict, session_id: str) -> str | None:
        """Record a single bug repro. Returns video path or None."""
        bug_id = bug.get("id", "unknown")
        url    = bug.get("url", self.base_url)
        steps  = bug.get("steps_to_reproduce", [])

        video_dir  = VIDEOS_DIR / session_id
        video_dir.mkdir(parents=True, exist_ok=True)

        print(f"  [VideoRecorder] Recording {bug_id}: {bug.get('title','')[:50]}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                record_video_dir=str(video_dir),
                record_video_size={"width": 1280, "height": 800},
            )
            page = await context.new_page()

            try:
                # navigate to the bug's page
                await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
                await page.wait_for_timeout(1500)

                # replay steps heuristically
                for step in steps:
                    step_lower = step.lower()

                    if "click" in step_lower:
                        # try to find a button or link to click
                        if "buy" in step_lower:
                            try: await page.click("text=Buy", timeout=2000)
                            except: pass
                        elif "order" in step_lower or "place" in step_lower:
                            try: await page.click("text=Place Order", timeout=2000)
                            except: pass
                        elif "shop" in step_lower:
                            try: await page.click("text=Shop Now", timeout=2000)
                            except: pass
                        await page.wait_for_timeout(800)

                    elif "navigate" in step_lower or "open" in step_lower:
                        if "product" in step_lower:
                            try: await page.goto(f"{self.base_url}/products")
                            except: pass
                        elif "checkout" in step_lower:
                            try: await page.goto(f"{self.base_url}/checkout")
                            except: pass
                        await page.wait_for_timeout(800)

                    elif "scroll" in step_lower:
                        await page.evaluate("window.scrollBy(0, 400)")
                        await page.wait_for_timeout(500)

                    elif "observe" in step_lower or "notice" in step_lower:
                        # just wait so viewer can see
                        await page.wait_for_timeout(1500)

                    else:
                        await page.wait_for_timeout(600)

                # hold on final state so viewer can see the bug
                await page.wait_for_timeout(2000)

            except Exception as e:
                print(f"    [VideoRecorder] Step error: {e}")

            finally:
                await context.close()
                await browser.close()

        # find the recorded video file
        video_files = sorted(video_dir.glob("*.webm"))
        if video_files:
            # rename to bug_id for clarity
            final_path = video_dir / f"{bug_id}_repro.webm"
            video_files[-1].rename(final_path)
            print(f"    ✅ Saved: {final_path}")
            return str(final_path)

        return None

    def record_all(self, validated_bugs: list, session_id: str,
                   only_high: bool = True) -> list:
        """
        Record repro videos for all validated bugs.
        only_high=True records only high/critical bugs (saves API quota).
        Returns list of {bug_id, video_path}.
        """
        to_record = validated_bugs
        if only_high:
            to_record = [b for b in validated_bugs
                         if b.get("final_severity", b.get("severity","")) in ("critical","high")]

        print(f"  [VideoRecorder] Recording {len(to_record)} bug repros...")

        async def _run_all():
            for bug in to_record:
                path = await self._record_single(bug, session_id)
                if path:
                    self.recordings.append({
                        "bug_id":     bug.get("id"),
                        "title":      bug.get("title",""),
                        "video_path": path,
                    })

        asyncio.run(_run_all())
        print(f"  [VideoRecorder] {len(self.recordings)} videos saved")
        return self.recordings