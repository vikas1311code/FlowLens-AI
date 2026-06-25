"""
core/performance.py
Measures real Core Web Vitals (LCP, CLS, FCP, TTFB) for the current page
using Google's own `web-vitals` library, injected from a CDN — the same
pattern as core/accessibility.py's axe-core injection.

This is a meaningfully better signal than a single navigation-time
threshold: LCP/CLS are the actual metrics Google uses to judge whether a
page *feels* fast, and they're what something like PageSpeed Insights
reports. It's not a full Lighthouse audit (no Lighthouse process is
spawned here) — just the field metrics, measured live during the crawl.

Requires outbound internet to fetch the CDN script. If that's unavailable,
measurement degrades to an `error` field rather than crashing the run.
"""

WEB_VITALS_CDN = "https://cdn.jsdelivr.net/npm/web-vitals@4/dist/web-vitals.iife.js"

# Google's published Core Web Vitals thresholds (ms for LCP/FCP/TTFB, unitless for CLS)
_THRESHOLDS = {
    "lcp":  (2500, 4000),
    "cls":  (0.1, 0.25),
    "fcp":  (1800, 3000),
    "ttfb": (800, 1800),
}

_COLLECT_SCRIPT = """async () => {
    return new Promise((resolve) => {
        const metrics = {};
        const mark = (key) => (m) => { metrics[key] = m.value; };
        try {
            webVitals.onLCP(mark('lcp'));
            webVitals.onCLS(mark('cls'));
            webVitals.onFCP(mark('fcp'));
            webVitals.onTTFB(mark('ttfb'));
        } catch (e) {
            resolve({ __error: String(e) });
            return;
        }
        // Some metrics (LCP, CLS) only finalize on page hide/unload, which
        // won't happen while we're sitting on the page — so we give the
        // observers a window to report what they already have rather than
        // waiting for an event that, in a one-shot crawl visit, may never come.
        setTimeout(() => resolve(metrics), 2500);
    });
}"""


def _rate(value, key) -> str:
    if value is None:
        return "unknown"
    good, poor = _THRESHOLDS[key]
    if value <= good:
        return "good"
    if value <= poor:
        return "needs_improvement"
    return "poor"


def _worst(ratings: list) -> str:
    order = ["poor", "needs_improvement", "good", "unknown"]
    for r in order:
        if r in ratings:
            return r
    return "unknown"


async def measure_page(page, url: str, step: int) -> dict:
    try:
        await page.add_script_tag(url=WEB_VITALS_CDN)
    except Exception as e:
        return {"url": url, "step": step, "error": f"could not load web-vitals: {e}"}

    try:
        raw = await page.evaluate(_COLLECT_SCRIPT)
    except Exception as e:
        return {"url": url, "step": step, "error": f"measurement failed: {e}"}

    if raw.get("__error"):
        return {"url": url, "step": step, "error": raw["__error"]}

    lcp, cls, fcp, ttfb = raw.get("lcp"), raw.get("cls"), raw.get("fcp"), raw.get("ttfb")
    ratings = {
        "lcp": _rate(lcp, "lcp"), "cls": _rate(cls, "cls"),
        "fcp": _rate(fcp, "fcp"), "ttfb": _rate(ttfb, "ttfb"),
    }
    return {
        "url": url, "step": step,
        "lcp_ms": round(lcp) if lcp is not None else None,
        "cls": round(cls, 3) if cls is not None else None,
        "fcp_ms": round(fcp) if fcp is not None else None,
        "ttfb_ms": round(ttfb) if ttfb is not None else None,
        "ratings": ratings,
        "overall_rating": _worst(ratings.values()),
    }


def summarize(results: list) -> dict:
    valid = [r for r in results if not r.get("error")]
    counts = {"good": 0, "needs_improvement": 0, "poor": 0, "unknown": 0}
    for r in valid:
        counts[r.get("overall_rating", "unknown")] += 1
    lcps = [r["lcp_ms"] for r in valid if r.get("lcp_ms") is not None]
    return {
        "pages_measured": len(results),
        "by_rating": counts,
        "avg_lcp_ms": round(sum(lcps) / len(lcps)) if lcps else None,
    }