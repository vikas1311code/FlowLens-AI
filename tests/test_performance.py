"""Tests for core/performance.py's rating thresholds and summary rollup
(the actual measurement needs a real browser page with the web-vitals
script injected, so that part isn't unit-tested here)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import performance


def test_rate_lcp_thresholds():
    assert performance._rate(2000, "lcp") == "good"
    assert performance._rate(2500, "lcp") == "good"        # boundary, inclusive
    assert performance._rate(3000, "lcp") == "needs_improvement"
    assert performance._rate(5000, "lcp") == "poor"


def test_rate_cls_thresholds():
    assert performance._rate(0.05, "cls") == "good"
    assert performance._rate(0.15, "cls") == "needs_improvement"
    assert performance._rate(0.4, "cls") == "poor"


def test_rate_handles_missing_value():
    assert performance._rate(None, "lcp") == "unknown"


def test_worst_prioritizes_poor_over_others():
    assert performance._worst(["good", "good"]) == "good"
    assert performance._worst(["good", "needs_improvement"]) == "needs_improvement"
    assert performance._worst(["good", "needs_improvement", "poor"]) == "poor"
    assert performance._worst([]) == "unknown"


def test_summarize_averages_lcp_and_counts_ratings():
    results = [
        {"lcp_ms": 2000, "overall_rating": "good"},
        {"lcp_ms": 5000, "overall_rating": "poor"},
        {"error": "skipped"},
    ]
    summary = performance.summarize(results)
    assert summary["pages_measured"] == 3
    assert summary["by_rating"]["good"] == 1
    assert summary["by_rating"]["poor"] == 1
    assert summary["avg_lcp_ms"] == 3500  # average of the two valid measurements


def test_summarize_with_no_valid_pages():
    results = [{"error": "skipped"}, {"error": "also skipped"}]
    summary = performance.summarize(results)
    assert summary["avg_lcp_ms"] is None
    assert sum(summary["by_rating"].values()) == 0