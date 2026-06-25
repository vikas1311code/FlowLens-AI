"""Tests for core/accessibility.py's pure-Python summary logic (the actual
axe-core scan needs a real browser page, so that part isn't unit-tested
here — this covers the rollup math that feeds the dashboard's A11y tab
and stats grid)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import accessibility


def test_summarize_empty_results():
    summary = accessibility.summarize([])
    assert summary["total"] == 0
    assert summary["pages_scanned"] == 0
    assert summary["pages_with_issues"] == 0


def test_summarize_counts_by_impact():
    results = [
        {"url": "/", "violations": [{"impact": "critical"}, {"impact": "minor"}]},
        {"url": "/about", "violations": []},
        {"url": "/contact", "violations": [{"impact": "serious"}]},
    ]
    summary = accessibility.summarize(results)
    assert summary["total"] == 3
    assert summary["by_impact"]["critical"] == 1
    assert summary["by_impact"]["minor"] == 1
    assert summary["by_impact"]["serious"] == 1
    assert summary["pages_with_issues"] == 2
    assert summary["pages_scanned"] == 3


def test_summarize_handles_missing_violations_key():
    results = [{"url": "/", "error": "could not load axe-core"}]
    summary = accessibility.summarize(results)
    assert summary["total"] == 0
    assert summary["pages_scanned"] == 1