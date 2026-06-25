"""Tests for core/notifier.py's message formatting (the actual HTTP POST
isn't tested here — that's a thin, already-reviewed urllib call)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import notifier


def test_message_for_clean_run():
    run = {
        "url": "https://shop.test", "status": "complete",
        "stats": {"critical": 0, "high": 0, "total_bugs": 0, "prd_coverage": 100,
                   "a11y_issues": 0, "pages_crawled": 3},
    }
    msg = notifier.build_slack_message(run)
    assert "all clear" in msg["text"]
    assert "shop.test" in msg["text"]


def test_message_for_run_with_critical_bugs():
    run = {
        "url": "https://shop.test", "status": "complete",
        "stats": {"critical": 2, "high": 1, "total_bugs": 5, "prd_coverage": 80,
                   "a11y_issues": 3, "pages_crawled": 6},
    }
    msg = notifier.build_slack_message(run)
    assert "2 critical" in msg["text"]
    assert "1 high" in msg["text"]


def test_message_for_errored_run():
    run = {"url": "https://shop.test", "status": "error", "error": "boom went the dynamite"}
    msg = notifier.build_slack_message(run)
    assert "failed" in msg["text"]
    assert "boom went the dynamite" in msg["text"]


def test_message_includes_dashboard_link_when_given():
    run = {"url": "https://shop.test", "status": "complete", "stats": {}}
    msg = notifier.build_slack_message(run, dashboard_url="https://my.ngrok.app")
    assert "https://my.ngrok.app" in msg["text"]


def test_message_has_slack_blocks_shape():
    run = {"url": "https://shop.test", "status": "complete", "stats": {}}
    msg = notifier.build_slack_message(run)
    assert "blocks" in msg
    assert isinstance(msg["blocks"], list)
    assert all("type" in b for b in msg["blocks"])