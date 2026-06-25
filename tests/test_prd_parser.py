"""Tests for agents/prd_parser.py's path normalization — this is the exact
logic that was broken before master_fix.py was applied (it compared raw,
un-normalized URLs against PRD paths, so coverage was always 0%)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.prd_parser import PRDParser


def test_normalize_strips_trailing_slash():
    assert PRDParser._normalize_path("/products/") == "/products"


def test_normalize_strips_query_and_fragment():
    assert PRDParser._normalize_path("/products?sort=asc") == "/products"
    assert PRDParser._normalize_path("/products#reviews") == "/products"


def test_normalize_lowercases():
    assert PRDParser._normalize_path("/Products") == "/products"


def test_normalize_extracts_path_from_full_url():
    assert PRDParser._normalize_path("https://example.com/Products/?ref=x") == "/products"


def test_normalize_empty_or_missing_becomes_root():
    assert PRDParser._normalize_path("") == "/"
    assert PRDParser._normalize_path(None) == "/"


def test_normalize_root_path():
    assert PRDParser._normalize_path("/") == "/"


def test_coverage_matches_visited_url_against_required_page():
    parser = PRDParser()
    parser.requirements = {
        "required_pages": [{"name": "Checkout", "path": "/checkout"}],
        "user_stories": [],
    }
    coverage = parser.check_coverage(
        visited_urls=["https://shop.test/checkout/?step=2"],
        page_analyses=[],
    )
    assert coverage["coverage_pct"] == 100
    assert coverage["uncovered_pages"] == []