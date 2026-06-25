"""
core/accessibility.py
Runs an axe-core accessibility audit on the current page during the crawl.

axe-core is loaded from a CDN at scan time rather than vendored, since it's
~500KB and updates its rule set fairly often. If the page (or the sandbox
running the crawl) has no outbound internet access, the scan fails closed —
it returns an empty result with an `error` field instead of crashing the
whole validation run.
"""

AXE_CDN_URL = "https://cdn.jsdelivr.net/npm/axe-core@4.10.0/axe.min.js"

_RUN_SCRIPT = """async () => {
    try {
        const results = await axe.run(document, {
            resultTypes: ['violations'],
        });
        return { ok: true, violations: results.violations };
    } catch (e) {
        return { ok: false, error: String(e) };
    }
}"""


async def scan_page(page, url: str, step: int) -> dict:
    """Inject axe-core into `page` and run it. Returns a normalized result dict."""
    try:
        await page.add_script_tag(url=AXE_CDN_URL)
    except Exception as e:
        return {"url": url, "step": step, "violations": [], "error": f"could not load axe-core: {e}"}

    try:
        raw = await page.evaluate(_RUN_SCRIPT)
    except Exception as e:
        return {"url": url, "step": step, "violations": [], "error": f"axe.run() failed: {e}"}

    if not raw.get("ok"):
        return {"url": url, "step": step, "violations": [], "error": raw.get("error", "unknown error")}

    violations = []
    for v in raw.get("violations", []):
        violations.append({
            "id": v.get("id", ""),
            "impact": v.get("impact") or "minor",
            "description": v.get("description", ""),
            "help": v.get("help", ""),
            "help_url": v.get("helpUrl", ""),
            "node_count": len(v.get("nodes", [])),
        })
    # most severe first
    order = {"critical": 0, "serious": 1, "moderate": 2, "minor": 3}
    violations.sort(key=lambda v: order.get(v["impact"], 9))

    return {"url": url, "step": step, "violations": violations}


def summarize(a11y_results: list) -> dict:
    """Roll up per-page results into impact-level counts for the stats grid."""
    counts = {"critical": 0, "serious": 0, "moderate": 0, "minor": 0}
    pages_with_issues = 0
    for page in a11y_results:
        if page.get("violations"):
            pages_with_issues += 1
        for v in page.get("violations", []):
            counts[v.get("impact", "minor")] = counts.get(v.get("impact", "minor"), 0) + 1
    return {
        "total": sum(counts.values()),
        "by_impact": counts,
        "pages_with_issues": pages_with_issues,
        "pages_scanned": len(a11y_results),
    }