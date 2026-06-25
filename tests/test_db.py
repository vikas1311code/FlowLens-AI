"""Tests for core/db.py — the SQLite persistence layer that worker
subprocesses and the API server both read/write."""


def test_save_and_load_run(temp_db):
    temp_db.save_run({"run_id": "r1", "url": "https://x.com", "status": "complete", "created_at": 1.0})
    run = temp_db.load_run("r1")
    assert run["run_id"] == "r1"
    assert run["status"] == "complete"


def test_load_run_returns_none_for_unknown_id(temp_db):
    assert temp_db.load_run("does-not-exist") is None


def test_save_run_strips_login_password(temp_db):
    temp_db.save_run({
        "run_id": "r1", "url": "https://x.com", "status": "queued", "created_at": 1.0,
        "login_password": "hunter2",
    })
    run = temp_db.load_run("r1")
    assert "login_password" not in run


def test_save_run_upserts(temp_db):
    temp_db.save_run({"run_id": "r1", "url": "https://x.com", "status": "queued", "created_at": 1.0})
    temp_db.save_run({"run_id": "r1", "url": "https://x.com", "status": "complete", "created_at": 1.0, "bugs": [1, 2]})
    run = temp_db.load_run("r1")
    assert run["status"] == "complete"
    assert run["bugs"] == [1, 2]
    assert len(temp_db.load_all_runs()) == 1


def test_logs_are_ordered_and_cumulative(temp_db):
    temp_db.append_log("r1", "info", "first")
    temp_db.append_log("r1", "info", "second")
    logs = temp_db.load_logs_since("r1", 0)
    assert [l["msg"] for l in logs] == ["first", "second"]


def test_load_logs_since_only_returns_new_entries(temp_db):
    temp_db.append_log("r1", "info", "a")
    first_batch = temp_db.load_logs_since("r1", 0)
    temp_db.append_log("r1", "info", "b")
    second_batch = temp_db.load_logs_since("r1", first_batch[-1]["id"])
    assert len(second_batch) == 1
    assert second_batch[0]["msg"] == "b"


def test_append_log_ignores_empty_messages(temp_db):
    temp_db.append_log("r1", "info", "")
    assert temp_db.load_logs_since("r1", 0) == []


def test_count_active_runs_only_counts_queued_and_running(temp_db):
    temp_db.save_run({"run_id": "a", "url": "https://x.com", "status": "running", "created_at": 1.0})
    temp_db.save_run({"run_id": "b", "url": "https://x.com", "status": "queued", "created_at": 1.0})
    temp_db.save_run({"run_id": "c", "url": "https://x.com", "status": "complete", "created_at": 1.0})
    temp_db.save_run({"run_id": "d", "url": "https://x.com", "status": "error", "created_at": 1.0})
    assert temp_db.count_active_runs() == 2


def test_mark_status_updates_existing_run(temp_db):
    temp_db.save_run({"run_id": "r1", "url": "https://x.com", "status": "running", "created_at": 1.0})
    temp_db.mark_status("r1", "cancelled")
    assert temp_db.load_run("r1")["status"] == "cancelled"


def test_mark_status_creates_minimal_record_if_missing(temp_db):
    temp_db.mark_status("ghost", "cancelled", url="https://y.com")
    run = temp_db.load_run("ghost")
    assert run is not None
    assert run["status"] == "cancelled"
    assert run["url"] == "https://y.com"


def test_load_runs_for_url_filters_and_orders(temp_db):
    temp_db.save_run({"run_id": "a", "url": "https://x.com", "status": "complete", "created_at": 2.0})
    temp_db.save_run({"run_id": "b", "url": "https://x.com", "status": "complete", "created_at": 1.0})
    temp_db.save_run({"run_id": "c", "url": "https://other.com", "status": "complete", "created_at": 1.5})
    history = temp_db.load_runs_for_url("https://x.com")
    assert [r["run_id"] for r in history] == ["b", "a"]  # oldest first


def test_load_runs_for_url_can_include_incomplete(temp_db):
    temp_db.save_run({"run_id": "a", "url": "https://x.com", "status": "running", "created_at": 1.0})
    assert temp_db.load_runs_for_url("https://x.com", only_complete=True) == []
    assert len(temp_db.load_runs_for_url("https://x.com", only_complete=False)) == 1


def test_distinct_urls_counts_runs_per_url(temp_db):
    temp_db.save_run({"run_id": "a", "url": "https://x.com", "status": "complete", "created_at": 1.0})
    temp_db.save_run({"run_id": "b", "url": "https://x.com", "status": "complete", "created_at": 2.0})
    temp_db.save_run({"run_id": "c", "url": "https://other.com", "status": "complete", "created_at": 1.0})
    urls = {u["url"]: u["run_count"] for u in temp_db.distinct_urls()}
    assert urls["https://x.com"] == 2
    assert urls["https://other.com"] == 1


def test_delete_run_removes_it(temp_db):
    temp_db.save_run({"run_id": "r1", "url": "https://x.com", "status": "complete", "created_at": 1.0})
    temp_db.delete_run("r1")
    assert temp_db.load_run("r1") is None