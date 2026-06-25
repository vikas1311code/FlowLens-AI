"""
agents/impact_scorer.py
Week 4 — Business Impact Scorer.
Estimates revenue risk and user impact for each validated bug.
No LLM needed — pure heuristic scoring based on:
  - Where in the funnel is the bug? (checkout > products > homepage)
  - How severe is it? (critical > high > medium > low)
  - How many personas hit it? (from vision analyses)
  - Is it a PRD violation?
"""
from typing import Optional

# funnel position weights (higher = more revenue impact)
FUNNEL_WEIGHTS = {
    "/checkout":        10,
    "/order-confirmed": 9,
    "/cart":            8,
    "/products":        6,
    "/":                4,
    "/about":           2,
    "/login":           7,
    "/signup":          7,
}

SEVERITY_WEIGHTS = {
    "critical": 10,
    "high":     7,
    "medium":   4,
    "low":      1,
}

PRD_VIOLATION_BONUS = 3


def _funnel_score(url: str) -> int:
    """Score based on where in the funnel the bug appears."""
    url_lower = url.lower()
    for path, weight in FUNNEL_WEIGHTS.items():
        if path in url_lower:
            return weight
    return 3  # default for unknown pages


def score_bug(bug: dict, is_prd_violation: bool = False) -> dict:
    """
    Score a single bug for business impact.
    Returns the bug dict enriched with impact fields.
    """
    sev          = bug.get("final_severity", bug.get("severity", "medium"))
    url          = bug.get("url", "")
    confidence   = float(bug.get("confidence", 0.8))

    sev_score    = SEVERITY_WEIGHTS.get(sev, 4)
    funnel_score = _funnel_score(url)
    prd_bonus    = PRD_VIOLATION_BONUS if is_prd_violation else 0

    # raw score 0–100
    raw = (sev_score * 0.45 + funnel_score * 0.35 + prd_bonus * 0.20) * confidence * 10
    impact_score = min(100, round(raw))

    # business impact label
    if impact_score >= 75:
        impact_label   = "Revenue Blocker"
        estimated_loss = "High — directly prevents conversions"
    elif impact_score >= 50:
        impact_label   = "Significant Risk"
        estimated_loss = "Medium — degrades conversion rate"
    elif impact_score >= 25:
        impact_label   = "Moderate Impact"
        estimated_loss = "Low — affects user experience"
    else:
        impact_label   = "Low Impact"
        estimated_loss = "Minimal — cosmetic or edge case"

    return {
        **bug,
        "impact_score":    impact_score,
        "impact_label":    impact_label,
        "estimated_loss":  estimated_loss,
        "funnel_position": funnel_score,
    }


def score_all(bugs: list, pm_reviewed: list) -> list:
    """Score all bugs and return sorted by impact score (highest first)."""
    # build PRD violation lookup
    prd_violations = {
        r["id"] for r in pm_reviewed
        if r.get("prd_classification") == "PRD_VIOLATION"
    }

    scored = []
    for bug in bugs:
        is_violation = bug.get("id", "") in prd_violations
        scored.append(score_bug(bug, is_prd_violation=is_violation))

    # sort by impact score descending
    scored.sort(key=lambda b: b.get("impact_score", 0), reverse=True)

    print(f"\n  [ImpactScorer] Business impact ranking:")
    for b in scored:
        print(f"    [{b['impact_score']:3d}/100] {b['impact_label']}  "
              f"{b.get('id','?')}: {b.get('title','')[:50]}")

    return scored