"""Tests for core/pipeline.py's _clean() — strips emoji and decorative
separator lines before they reach the dashboard's live log feed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pipeline import _clean


def test_clean_strips_emoji():
    assert _clean("Crawl complete \U0001F680") == "Crawl complete"


def test_clean_strips_decorative_separator_line():
    assert _clean("─" * 50) == ""
    assert _clean("=" * 30) == ""


def test_clean_keeps_normal_text_with_punctuation():
    assert _clean("NODE 1: Crawl + Vision") == "NODE 1: Crawl + Vision"


def test_clean_keeps_text_that_happens_to_repeat_one_letter():
    # not a separator line just because it's short/uniform-ish — must
    # actually be pure punctuation to get dropped
    assert _clean("ok") == "ok"


def test_clean_handles_empty_string():
    assert _clean("") == ""