"""
core/anomaly.py
Detects bugs from raw session data — no LLM needed here.
Three detectors:
  1. Screenshot diff  — pixel-level change between consecutive screens
  2. JS error monitor — captures uncaught exceptions
  3. Load time check  — flags pages that take > SLOW_THRESHOLD_MS
"""
import base64
import io
from PIL import Image, ImageChops
from typing import Optional


SLOW_THRESHOLD_MS   = 3_000   # flag if page takes > 3s
DIFF_THRESHOLD_PCT  = 0.02    # flag if < 2% of pixels changed (possible blank/frozen page)
DIFF_HUGE_PCT       = 0.80    # flag if > 80% changed (possible full crash/redirect)


class AnomalyDetector:

    @staticmethod
    def check_load_time(action_entry: dict) -> Optional[dict]:
        """Flag slow navigations."""
        if action_entry.get("action") != "navigate":
            return None
        ms = action_entry.get("duration_ms", 0)
        if ms > SLOW_THRESHOLD_MS:
            return {
                "type":     "slow_load",
                "severity": "medium",
                "step":     action_entry["step"],
                "detail":   f"Page took {ms}ms to load (threshold {SLOW_THRESHOLD_MS}ms)",
                "url":      action_entry["params"].get("url", ""),
            }
        return None

    @staticmethod
    def check_js_errors(js_errors: list, step: int) -> list[dict]:
        """Return anomaly records for any JS errors captured."""
        findings = []
        for err in js_errors:
            findings.append({
                "type":     "js_error",
                "severity": "high",
                "step":     step,
                "detail":   err["message"],
            })
        return findings

    @staticmethod
    def check_action_failure(action_entry: dict) -> Optional[dict]:
        """Flag any action that explicitly failed (selector not found, timeout, etc)."""
        if not action_entry.get("success", True):
            err = action_entry["params"].get("error", "unknown error")
            return {
                "type":     "action_failure",
                "severity": "high",
                "step":     action_entry["step"],
                "action":   action_entry["action"],
                "detail":   err,
            }
        return None

    @staticmethod
    def diff_screenshots(b64_a: str, b64_b: str, step: int) -> Optional[dict]:
        """
        Compare two base64 screenshots pixel-by-pixel.
        Flags if almost nothing changed (frozen/blank page)
        or if everything changed (unexpected full redirect/crash).
        """
        try:
            img_a = Image.open(io.BytesIO(base64.b64decode(b64_a))).convert("RGB")
            img_b = Image.open(io.BytesIO(base64.b64decode(b64_b))).convert("RGB")

            if img_a.size != img_b.size:
                img_b = img_b.resize(img_a.size)

            diff  = ImageChops.difference(img_a, img_b)
            total = img_a.width * img_a.height
            # count pixels where any channel differs by > 10
            changed = sum(
                1 for px in diff.getdata()
                if max(px) > 10
            )
            pct = changed / total

            if pct < DIFF_THRESHOLD_PCT:
                return {
                    "type":     "page_frozen",
                    "severity": "medium",
                    "step":     step,
                    "detail":   f"Only {pct*100:.1f}% of pixels changed after action — page may be frozen or blank",
                    "diff_pct": round(pct, 4),
                }
            if pct > DIFF_HUGE_PCT:
                return {
                    "type":     "unexpected_redirect",
                    "severity": "medium",
                    "step":     step,
                    "detail":   f"{pct*100:.1f}% of pixels changed — possible unexpected redirect or crash",
                    "diff_pct": round(pct, 4),
                }
        except Exception as e:
            print(f"[diff warning] {e}")
        return None

    @staticmethod
    def check_blank_page(page_info: dict, step: int) -> Optional[dict]:
        """Flag pages with almost no visible text."""
        text = page_info.get("visible_text", "")
        if len(text.strip()) < 30:
            return {
                "type":     "blank_page",
                "severity": "high",
                "step":     step,
                "detail":   f"Page has only {len(text.strip())} chars of visible text — may be blank or broken",
                "url":      page_info.get("url", ""),
            }
        return None

    @classmethod
    def run_all(cls, action_entry: dict, prev_b64: Optional[str],
                curr_b64: Optional[str], js_errors: list,
                page_info: Optional[dict] = None) -> list[dict]:
        """Run all detectors for a single step. Returns list of anomalies found."""
        findings = []

        a = cls.check_action_failure(action_entry)
        if a: findings.append(a)

        b = cls.check_load_time(action_entry)
        if b: findings.append(b)

        findings += cls.check_js_errors(js_errors, action_entry["step"])

        if prev_b64 and curr_b64:
            d = cls.diff_screenshots(prev_b64, curr_b64, action_entry["step"])
            if d: findings.append(d)

        if page_info:
            bp = cls.check_blank_page(page_info, action_entry["step"])
            if bp: findings.append(bp)

        return findings
