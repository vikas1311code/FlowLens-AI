"""Tests for the security-critical helpers in api/server.py: path-traversal
guards, SSRF target validation, and the bug-regression matcher."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import api.server as server


# ── _is_safe_name / _safe_join (path traversal) ─────────────────────────────

@pytest.mark.parametrize("name", [
    "report.md", "BUG-001_test.py", "pvos_abc123_step007.png", "a-b.c.d",
])
def test_is_safe_name_accepts_normal_filenames(name):
    assert server._is_safe_name(name)


@pytest.mark.parametrize("name", [
    "../../etc/passwd", "a/b.png", "..", "", "/etc/passwd",
    "file..name.txt", "..%2f..%2fetc",
])
def test_is_safe_name_rejects_traversal_and_weird_input(name):
    assert not server._is_safe_name(name)


def test_safe_join_returns_path_for_legit_filename(tmp_path):
    base = tmp_path / "sandbox"
    base.mkdir()
    result = server._safe_join(base, "ok.txt")
    assert result == (base / "ok.txt").resolve()


def test_safe_join_blocks_relative_traversal(tmp_path):
    base = tmp_path / "sandbox"
    base.mkdir()
    assert server._safe_join(base, "../../../../etc/passwd") is None


def test_safe_join_blocks_absolute_path_injection(tmp_path):
    base = tmp_path / "sandbox"
    base.mkdir()
    assert server._safe_join(base, "/etc/passwd") is None


def test_safe_join_blocks_multi_arg_traversal(tmp_path):
    base = tmp_path / "sandbox"
    base.mkdir()
    assert server._safe_join(base, "../../etc", "passwd") is None


# ── validate_target_url (SSRF guard) ────────────────────────────────────────

def test_validate_target_url_accepts_https():
    server.validate_target_url("https://example.com")  # should not raise


def test_validate_target_url_accepts_http():
    server.validate_target_url("http://example.com")  # should not raise


def test_validate_target_url_rejects_non_http_scheme():
    with pytest.raises(Exception):
        server.validate_target_url("ftp://example.com")


def test_validate_target_url_rejects_javascript_scheme():
    with pytest.raises(Exception):
        server.validate_target_url("javascript:alert(1)")


def test_validate_target_url_rejects_missing_hostname():
    with pytest.raises(Exception):
        server.validate_target_url("https://")


def test_validate_target_url_allows_empty_string():
    server.validate_target_url("")  # login_url is optional — empty is fine


def test_resolves_to_private_flags_loopback():
    assert server._resolves_to_private("localhost")
    assert server._resolves_to_private("127.0.0.1")


def test_resolves_to_private_flags_unresolvable_host():
    assert server._resolves_to_private("this-domain-should-not-exist-xyz123.invalid")


# ── compute_regression / _bug_signature ─────────────────────────────────────

def test_bug_signature_ignores_query_string_and_trailing_slash():
    a = server._bug_signature({"url": "https://x.com/page/?ref=abc", "title": "Checkout button does nothing when clicked today"})
    b = server._bug_signature({"url": "https://x.com/page", "title": "Checkout button does nothing when clicked yesterday"})
    assert a == b  # same path once query/trailing-slash stripped, same first 6 words


def test_compute_regression_identifies_new_resolved_persisting():
    previous = [
        {"id": "BUG-001", "url": "/checkout", "title": "Checkout button does nothing on click"},
        {"id": "BUG-002", "url": "/", "title": "Logo image broken on homepage"},
    ]
    current = [
        {"id": "BUG-001", "url": "/", "title": "Logo image broken on homepage"},
        {"id": "BUG-002", "url": "/search", "title": "Search bar overlaps nav on mobile"},
    ]
    result = server.compute_regression(current, previous)
    assert len(result["new"]) == 1
    assert result["new"][0]["url"] == "/search"
    assert len(result["resolved"]) == 1
    assert result["resolved"][0]["url"] == "/checkout"
    assert len(result["persisting"]) == 1
    assert result["persisting"][0]["url"] == "/"


def test_compute_regression_empty_previous_means_everything_is_new():
    current = [{"id": "BUG-001", "url": "/", "title": "Something broke"}]
    result = server.compute_regression(current, [])
    assert len(result["new"]) == 1
    assert result["resolved"] == []
    assert result["persisting"] == []