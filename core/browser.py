"""
core/browser.py
Playwright async browser wrapper.
Handles: launch, navigate, screenshot, click, type, scroll, JS errors, session log.
"""
import asyncio
import base64
import json
import time
from pathlib import Path
from playwright.async_api import async_playwright, Page, Browser, BrowserContext

SCREENSHOTS_DIR = Path(__file__).parent.parent / "outputs" / "screenshots"
REPORTS_DIR     = Path(__file__).parent.parent / "outputs" / "reports"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


class BrowserSession:
    """
    One test session = one BrowserSession.
    Tracks every action, screenshot, JS error, and network event.
    """

    def __init__(self, session_id: str, headless: bool = True):
        self.session_id   = session_id
        self.headless     = headless
        self.step         = 0
        self.js_errors    = []
        self.console_msgs = []
        self.actions_log  = []          # full structured log
        self._playwright  = None
        self._browser: Browser | None  = None
        self._context: BrowserContext | None = None
        self.page: Page | None         = None

    # ── lifecycle ────────────────────────────────────────────────────────

    async def start(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox", "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",   # /dev/shm is tiny in Docker/Render -> renderer hangs
                "--disable-gpu",
            ],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            # NOTE: no record_video_dir here. Video of the main crawl context was
            # never used (VideoRecorder makes its own context) and recording
            # makes screenshots time out on low-CPU hosts like Render free tier.
        )
        self._context.set_default_timeout(15_000)
        self.page = await self._context.new_page()

        # capture JS errors
        self.page.on("pageerror", lambda err: self.js_errors.append({
            "ts": time.time(), "message": str(err)
        }))
        # capture console
        self.page.on("console", lambda msg: self.console_msgs.append({
            "ts": time.time(), "type": msg.type, "text": msg.text
        }))
        print(f"[session:{self.session_id}] Browser started")

    async def login(self, login_url: str, username: str, password: str,
                     user_selector: str | None = None,
                     pass_selector: str | None = None,
                     submit_selector: str | None = None) -> bool:
        """Log in before crawling starts. Falls back to common selector
        patterns if specific ones aren't given. Never logs the password."""
        user_sel = user_selector or (
            "input[type=email], input[name*=email i], input[name*=user i], "
            "input[id*=email i], input[id*=user i], input[autocomplete=username]"
        )
        pass_sel = pass_selector or "input[type=password]"
        submit_sel = submit_selector or (
            "button[type=submit], input[type=submit], "
            "button:has-text('Log in'), button:has-text('Sign in'), "
            "button:has-text('Login')"
        )
        print(f"[session:{self.session_id}] Logging in via {login_url} "
              f"(user field: {user_sel[:40]}...)")
        try:
            await self.page.goto(login_url, wait_until="domcontentloaded", timeout=20_000)
            await self.page.wait_for_timeout(500)
            await self.page.locator(user_sel).first.fill(username, timeout=8_000)
            await self.page.locator(pass_sel).first.fill(password, timeout=8_000)
            await self.page.locator(submit_sel).first.click(timeout=8_000)
            try:
                await self.page.wait_for_load_state("networkidle", timeout=12_000)
            except Exception:
                await self.page.wait_for_timeout(1500)
            print(f"[session:{self.session_id}] Login submitted, now at {self.page.url}")
            return True
        except Exception as e:
            print(f"[session:{self.session_id}] Login failed ({type(e).__name__}) — "
                  f"continuing the crawl unauthenticated")
            return False

    async def snapshot_at_viewport(self, url: str, width: int, height: int, label: str) -> dict | None:
        """Loads `url` in a fresh, throwaway context at the given viewport
        size and screenshots it — used for responsive checks. Doesn't touch
        the main crawl page/context at all."""
        if not self._browser:
            return None
        ctx = None
        try:
            ctx = await self._browser.new_context(viewport={"width": width, "height": height})
            page = await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            await page.wait_for_timeout(700)
            fname = f"{self.session_id}_responsive_{label}_{self.step:03d}.png"
            self.step += 1
            fpath = SCREENSHOTS_DIR / fname
            await page.screenshot(path=str(fpath), full_page=False)
            return {
                "label": label, "width": width, "height": height,
                "url": url, "screenshot": fname,
            }
        except Exception as e:
            print(f"[session:{self.session_id}] Responsive snapshot ({label}) "
                  f"for {url} failed: {type(e).__name__}")
            return None
        finally:
            if ctx:
                await ctx.close()

    async def stop(self):
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        print(f"[session:{self.session_id}] Browser stopped")

    # ── actions ─────────────────────────────────────────────────────────

    async def navigate(self, url: str) -> dict:
        """Navigate to URL, wait for load, take screenshot."""
        t0 = time.time()
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=15_000)
            await self.page.wait_for_timeout(800)          # let JS settle
            load_ms = int((time.time() - t0) * 1000)
            shot = await self._screenshot(f"navigate_{self.step}")
            entry = self._log("navigate", {"url": url}, shot, load_ms)
            return entry
        except Exception as e:
            return self._log("navigate", {"url": url, "error": str(e)}, None, 0)

    async def click(self, selector: str, description: str = "") -> dict:
        """Click an element by CSS selector."""
        t0 = time.time()
        try:
            await self.page.click(selector, timeout=5_000)
            await self.page.wait_for_timeout(600)
            shot = await self._screenshot(f"click_{self.step}")
            return self._log("click", {"selector": selector, "desc": description},
                             shot, int((time.time()-t0)*1000))
        except Exception as e:
            shot = await self._screenshot(f"click_fail_{self.step}")
            return self._log("click", {"selector": selector, "error": str(e)},
                             shot, int((time.time()-t0)*1000))

    async def type_text(self, selector: str, text: str) -> dict:
        """Click a field and type into it."""
        t0 = time.time()
        try:
            await self.page.click(selector, timeout=5_000)
            await self.page.fill(selector, text, timeout=5_000)
            await self.page.wait_for_timeout(300)
            shot = await self._screenshot(f"type_{self.step}")
            return self._log("type", {"selector": selector, "text": text},
                             shot, int((time.time()-t0)*1000))
        except Exception as e:
            shot = await self._screenshot(f"type_fail_{self.step}")
            return self._log("type", {"selector": selector, "text": text, "error": str(e)},
                             shot, int((time.time()-t0)*1000))

    async def scroll(self, direction: str = "down", amount: int = 400) -> dict:
        """Scroll the page."""
        t0 = time.time()
        dy = amount if direction == "down" else -amount
        await self.page.evaluate(f"window.scrollBy(0, {dy})")
        await self.page.wait_for_timeout(400)
        shot = await self._screenshot(f"scroll_{self.step}")
        return self._log("scroll", {"direction": direction, "amount": amount},
                         shot, int((time.time()-t0)*1000))

    async def get_page_info(self) -> dict:
        """Return current URL, title, and visible text (truncated). Handles navigation races."""
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass

        try:
            url   = self.page.url
            title = await self.page.title()
            text  = await self.page.evaluate(
                "() => document.body ? document.body.innerText.slice(0, 2000) : ''"
            )
            links = await self.page.evaluate(
                "() => Array.from(document.querySelectorAll('a[href]'))"
                ".slice(0,20).map(a => ({text: a.innerText.trim(), href: a.href}))"
            )
            buttons = await self.page.evaluate(
                "() => Array.from(document.querySelectorAll('button, input[type=submit]'))"
                ".slice(0,15).map(b => b.innerText.trim() || b.value || b.type)"
            )
            return {
                "url": url, "title": title,
                "visible_text": text,
                "links": links,
                "buttons": buttons,
                "js_errors": self.js_errors[-5:],
            }
        except Exception as e:
            # navigation destroyed the execution context mid-read — return safe defaults
            print(f"  [browser] get_page_info recovered from: {e}")
            return {
                "url": self.page.url if self.page else "",
                "title": "",
                "visible_text": "",
                "links": [],
                "buttons": [],
                "js_errors": self.js_errors[-5:],
            }

    # ── screenshot helpers ───────────────────────────────────────────────

    async def _screenshot(self, label: str) -> dict | None:
        self.step += 1
        fname = f"{self.session_id}_step{self.step:03d}_{label}.png"
        fpath = SCREENSHOTS_DIR / fname
        # animations="disabled" stops Playwright waiting on endless CSS/JS
        # animations; short timeout + one retry instead of a 30s stall.
        for attempt, tmo in enumerate((10_000, 10_000), start=1):
            try:
                await self.page.screenshot(path=str(fpath), full_page=False,
                                           animations="disabled", caret="initial",
                                           timeout=tmo)
                b64 = base64.b64encode(fpath.read_bytes()).decode()
                return {"path": str(fpath), "filename": fname, "base64": b64}
            except Exception as e:
                print(f"[screenshot error] attempt {attempt}: {str(e)[:120]}")
                try:
                    await self.page.wait_for_timeout(1000)
                except Exception:
                    break
        # last resort: raw CDP capture, bypasses Playwright's font/animation waits
        try:
            cdp = await self._context.new_cdp_session(self.page)
            res = await asyncio.wait_for(cdp.send("Page.captureScreenshot", {"format": "png"}), 10)
            fpath.write_bytes(base64.b64decode(res["data"]))
            print("[screenshot] recovered via CDP fallback")
            return {"path": str(fpath), "filename": fname, "base64": res["data"]}
        except Exception as e:
            print(f"[screenshot error] CDP fallback failed: {str(e)[:120]}")
            return None

    def get_latest_screenshot_b64(self) -> str | None:
        """Return base64 of the most recent screenshot."""
        shots = sorted(SCREENSHOTS_DIR.glob(f"{self.session_id}_*.png"))
        if not shots:
            return None
        return base64.b64encode(shots[-1].read_bytes()).decode()

    # ── logging ──────────────────────────────────────────────────────────

    def _log(self, action_type: str, params: dict,
             screenshot: dict | None, duration_ms: int) -> dict:
        entry = {
            "step":        self.step,
            "ts":          time.time(),
            "action":      action_type,
            "params":      params,
            "screenshot":  {k: v for k, v in (screenshot or {}).items() if k != "base64"},
            "duration_ms": duration_ms,
            "success":     "error" not in params,
        }
        self.actions_log.append(entry)
        status = "OK" if entry["success"] else "FAIL"
        print(f"  [{status}] step={self.step} {action_type} {list(params.values())[0]!r} "
              f"({duration_ms}ms)")
        return entry

    def save_session_log(self) -> str:
        """Write full session log to JSON. Returns file path."""
        log = {
            "session_id": self.session_id,
            "total_steps": self.step,
            "js_errors": self.js_errors,
            "actions": self.actions_log,
        }
        out = REPORTS_DIR / f"{self.session_id}_session_log.json"
        out.write_text(json.dumps(log, indent=2))
        print(f"[session log saved] {out}")
        return str(out)
