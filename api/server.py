"""
api/server.py
FastAPI backend for ProductValidation OS.

Endpoints:
  POST /run                       — start a validation run (requires X-API-Key if DASHBOARD_API_KEY is set)
  GET  /stream/{run_id}           — SSE stream of live logs
  GET  /status/{run_id}           — full run state (bugs, stats, coverage...) — updates progressively while running
  GET  /runs                      — list all past runs (persisted in SQLite, survives restarts)
  GET  /urls                      — distinct target URLs that have been run, for the Trends view
  GET  /trends?url=...             — bug-count / coverage / a11y trend across past runs for one URL
  GET  /runs/{run_id}/regression  — new / resolved / still-open bugs vs the previous run for the same URL
  GET  /report/{run_id}           — final markdown report
  GET  /tests/{filename}          — generated Playwright test source
  GET  /screenshots/{filename}    — a single screenshot
  GET  /screenshots/list/{sid}    — ordered screenshot filenames for a session
  GET  /videos/{session}/{file}   — a bug repro video
  GET  /health                    — health check (+ whether an API key is required)
  GET  /                          — serves the dashboard (so one process = one port)
"""
import asyncio
import hmac
import ipaddress
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

# start.sh launches uvicorn from inside this api/ directory (so the
# `--reload` watcher only has to track this app, not the whole venv/outputs
# tree). That means the project root isn't on sys.path by default, which
# would break every `core.*` / `graph` / `agents.*` import below — so we
# add it ourselves, before anything else, regardless of where this process
# was actually launched from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form, Header, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

import core.db as db
from core import gemini_client

DASHBOARD_API_KEY = (os.environ.get("DASHBOARD_API_KEY") or "").strip() or None

# When an API key is configured, treat this as "meant to be exposed" and
# stop publishing the interactive API docs / OpenAPI schema — they're a
# convenience for local development, not something a public deployment
# needs to hand out for free.
app = FastAPI(
    title="ProductValidation OS", version="3.0.0",
    docs_url=None if DASHBOARD_API_KEY else "/docs",
    redoc_url=None if DASHBOARD_API_KEY else "/redoc",
    openapi_url=None if DASHBOARD_API_KEY else "/openapi.json",
)

# CORS is closed by default: the dashboard is served from this same process
# (same origin), so it never needs CORS at all. An open "*" CORS policy here
# would let *any* website's JS read your run history/bugs/screenshots if a
# visitor had this dashboard's tab open elsewhere — only opt into specific
# origins if you're deliberately calling this API from a separate frontend.
_cors_origins = [o.strip() for o in (os.environ.get("CORS_ALLOWED_ORIGINS") or "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=_cors_origins, allow_methods=["*"], allow_headers=["*"])

BASE_DIR        = Path(__file__).parent.parent
DASHBOARD_INDEX = BASE_DIR / "dashboard" / "index.html"
REPORTS_DIR     = BASE_DIR / "outputs" / "reports"
VIDEOS_DIR      = BASE_DIR / "outputs" / "videos"
TESTS_DIR       = BASE_DIR / "outputs" / "tests"
SCREENSHOTS_DIR = BASE_DIR / "outputs" / "screenshots"
PRDS_DIR        = BASE_DIR / "outputs" / "prds"
for d in [REPORTS_DIR, VIDEOS_DIR, TESTS_DIR, SCREENSHOTS_DIR, PRDS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

BLOCK_PRIVATE_TARGETS = (os.environ.get("BLOCK_PRIVATE_TARGETS", "false").lower() in ("1", "true", "yes"))
NOTIFY_WEBHOOK_URL   = (os.environ.get("NOTIFY_WEBHOOK_URL") or "").strip() or None
PUBLIC_DASHBOARD_URL = (os.environ.get("PUBLIC_DASHBOARD_URL") or "").strip() or None
MAX_CONCURRENT_RUNS  = int(os.environ.get("MAX_CONCURRENT_RUNS", "2"))
MAX_PRD_BYTES        = int(os.environ.get("MAX_PRD_BYTES", str(2 * 1024 * 1024)))  # 2MB default

if not DASHBOARD_API_KEY:
    print("[server] DASHBOARD_API_KEY is not set — /run is open to anyone who can reach this "
          "server. Fine for localhost-only use; set one in .env before exposing this via ngrok.")

WORKER_PATH     = BASE_DIR / "worker_run.py"
WORKER_LOGS_DIR = BASE_DIR / "outputs" / "worker_logs"
WORKER_LOGS_DIR.mkdir(parents=True, exist_ok=True)

# run_id -> subprocess.Popen — tracked only so /runs/{id}/cancel can signal
# the right process. The actual run state lives in SQLite, written by the
# worker subprocess itself, since that's the only thing both this API
# process and that separate process can both see.
active_processes: dict = {}


@app.on_event("startup")
async def _on_startup():
    db.init_db()
    n = len(db.load_all_runs())
    print(f"[server] {n} run(s) on file in outputs/db/runs.sqlite3")


# ── security: API key gate + basic SSRF guard ──────────────────────────────

async def require_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    if DASHBOARD_API_KEY and not hmac.compare_digest(x_api_key or "", DASHBOARD_API_KEY):
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header")


def _resolves_to_private(hostname: str) -> bool:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return True  # can't resolve — treat as unsafe
    for info in infos:
        ip = info[4][0]
        try:
            ipobj = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if (ipobj.is_private or ipobj.is_loopback or ipobj.is_link_local
                or ipobj.is_reserved or ipobj.is_multicast or ipobj.is_unspecified):
            return True
    return False


def validate_target_url(url: str, field: str = "url"):
    if not url:
        return
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail=f"{field} must be http or https")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail=f"{field} has no hostname")
    if BLOCK_PRIVATE_TARGETS and _resolves_to_private(parsed.hostname):
        raise HTTPException(
            status_code=400,
            detail=f"{field} resolves to a private/internal address, blocked because "
                   f"BLOCK_PRIVATE_TARGETS=true. Set it to false in .env to test local apps."
        )


_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _is_safe_name(name: str) -> bool:
    """Whitelist check for anything that becomes part of a filesystem path:
    letters, digits, dot, dash, underscore only — no slashes, no '..', no
    null bytes. This is checked in addition to (not instead of) _safe_join's
    containment check below, since defense-in-depth shouldn't rely on a
    single layer."""
    return bool(name) and bool(_SAFE_NAME_RE.match(name)) and ".." not in name


def _safe_join(base_dir: Path, *parts: str):
    """Joins `parts` onto base_dir and guarantees the result is still inside
    base_dir, regardless of '..', symlinks, or absolute-path tricks in any
    of the parts. Returns None if anything looks unsafe or escapes."""
    for p in parts:
        if not _is_safe_name(p):
            return None
    try:
        base_resolved = base_dir.resolve()
        candidate = base_resolved.joinpath(*parts).resolve()
        candidate.relative_to(base_resolved)  # raises ValueError if it escaped
        return candidate
    except (ValueError, RuntimeError, OSError):
        return None


def _bug_signature(bug: dict) -> str:
    """A loose fingerprint used to match the 'same' bug across separate runs
    (bug ids like BUG-003 are re-numbered every run, so they can't be used
    directly for regression tracking)."""
    url = (bug.get("url") or "").split("?")[0].rstrip("/")
    title = " ".join((bug.get("title") or "").lower().split()[:6])
    return f"{url}|{title}"


def compute_regression(current_bugs: list, previous_bugs: list) -> dict:
    cur = {_bug_signature(b): b for b in current_bugs}
    prev = {_bug_signature(b): b for b in previous_bugs}
    new_keys = set(cur) - set(prev)
    resolved_keys = set(prev) - set(cur)
    persisting_keys = set(cur) & set(prev)
    return {
        "new": [cur[k] for k in new_keys],
        "resolved": [prev[k] for k in resolved_keys],
        "persisting": [cur[k] for k in persisting_keys],
    }


# ── running validations as subprocesses (real concurrency + cancellation) ──

def _cleanup_stale_processes():
    """Drop tracking entries for processes that have already exited, so
    active_processes doesn't grow forever."""
    for rid in list(active_processes):
        if active_processes[rid].poll() is not None:
            active_processes.pop(rid, None)


def _spawn_worker(run_id: str, url: str, steps: int, prd_path: Optional[str],
                   login_cfg: Optional[dict], gemini_api_key: Optional[str] = None,
                   gemini_model: Optional[str] = None) -> subprocess.Popen:
    """Launches worker_run.py as its own OS process (its own process group,
    on POSIX) so this validation runs independently of the API server's
    event loop and of any other run in progress — that's what makes
    MAX_CONCURRENT_RUNS > 1 actually mean something."""
    cmd = [sys.executable, str(WORKER_PATH), run_id, url, str(steps)]
    if prd_path:
        cmd += ["--prd-path", prd_path]
    if login_cfg:
        cmd += ["--has-login"]
    if gemini_api_key:
        cmd += ["--has-gemini-key"]
    if gemini_model:
        cmd += ["--gemini-model", gemini_model]

    log_file = open(WORKER_LOGS_DIR / f"{run_id}.log", "wb")
    popen_kwargs = dict(cwd=str(BASE_DIR), stdout=log_file, stderr=log_file)
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True  # own process group -> clean group-wide cancel

    if login_cfg or gemini_api_key:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, **popen_kwargs)
        # Login credentials and any per-run Gemini key go over stdin, never
        # as a CLI arg — process args are visible to any other local user
        # via `ps aux`, stdin isn't. Both share one JSON payload since stdin
        # can only be read once by the worker.
        stdin_payload = {"login": login_cfg, "gemini_api_key": gemini_api_key}
        proc.stdin.write(json.dumps(stdin_payload).encode("utf-8"))
        proc.stdin.close()
    else:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, **popen_kwargs)

    active_processes[run_id] = proc
    return proc


def _terminate_process_group(proc: subprocess.Popen):
    try:
        if sys.platform != "win32":
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
    except (ProcessLookupError, PermissionError):
        pass



# ── routes ───────────────────────────────────────────────────────────────────

@app.post("/run", dependencies=[Depends(require_api_key)])
async def start_run(url: str = Form(...), steps: int = Form(10), prd: UploadFile = File(None),
                     login_url: Optional[str] = Form(None),
                     login_username: Optional[str] = Form(None),
                     login_password: Optional[str] = Form(None),
                     login_user_selector: Optional[str] = Form(None),
                     login_pass_selector: Optional[str] = Form(None),
                     login_submit_selector: Optional[str] = Form(None),
                     gemini_api_key: Optional[str] = Form(None),
                     gemini_model: Optional[str] = Form(None)):
    validate_target_url(url, "url")

    gemini_api_key = (gemini_api_key or "").strip() or None
    gemini_model = (gemini_model or "").strip() or None
    if gemini_model and gemini_model not in gemini_client.SUPPORTED_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported gemini_model '{gemini_model}'. "
                   f"Choose one of: {', '.join(gemini_client.SUPPORTED_MODELS)}",
        )

    _cleanup_stale_processes()
    running = db.count_active_runs()
    if running >= MAX_CONCURRENT_RUNS:
        raise HTTPException(
            status_code=429,
            detail=f"{running} run(s) already in progress (limit {MAX_CONCURRENT_RUNS}). "
                   f"Wait for one to finish, cancel one, or raise MAX_CONCURRENT_RUNS in .env."
        )

    login_cfg = None
    if login_url:
        validate_target_url(login_url, "login_url")
        login_cfg = {
            "login_url": login_url,
            "username": login_username or "",
            "password": login_password or "",
            "user_selector": login_user_selector or None,
            "pass_selector": login_pass_selector or None,
            "submit_selector": login_submit_selector or None,
        }

    run_id = str(uuid.uuid4())[:12]
    prd_path = None
    if prd and prd.filename:
        # Use only the basename of the client-supplied filename (it's
        # attacker-controlled and could otherwise contain '../' sequences)
        # and reject anything that isn't a plain PRD-shaped file.
        safe_filename = Path(prd.filename).name
        if not safe_filename or Path(safe_filename).suffix.lower() not in (".md", ".txt"):
            raise HTTPException(status_code=400, detail="PRD must be a .md or .txt file")
        content = await prd.read()
        if len(content) > MAX_PRD_BYTES:
            raise HTTPException(status_code=400, detail=f"PRD file too large (max {MAX_PRD_BYTES // 1024}KB)")
        prd_path = str(PRDS_DIR / f"{run_id}_{safe_filename}")
        Path(prd_path).write_bytes(content)

    db.save_run({
        "run_id": run_id, "url": url, "steps": steps, "status": "queued",
        "created_at": time.time(), "bugs": [], "stats": {},
        "login_url": login_url or None,   # never store the password
        "gemini_model": gemini_model or None,  # not secret — fine to keep for display; the key itself is never persisted
    })

    _spawn_worker(run_id, url, steps, prd_path, login_cfg, gemini_api_key, gemini_model)
    return {"run_id": run_id, "status": "queued"}


@app.post("/runs/{run_id}/cancel", dependencies=[Depends(require_api_key)])
async def cancel_run(run_id: str):
    run = db.load_run(run_id)
    if not run:
        return JSONResponse({"error": "Run not found"}, status_code=404)
    if run.get("status") not in ("queued", "running"):
        return {"status": run.get("status"), "note": "already finished"}

    proc = active_processes.get(run_id)
    if proc and proc.poll() is None:
        _terminate_process_group(proc)

        async def _escalate_if_still_alive():
            await asyncio.sleep(5)
            if proc.poll() is None:
                try:
                    if sys.platform != "win32":
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    else:
                        proc.kill()
                except (ProcessLookupError, PermissionError):
                    pass
            active_processes.pop(run_id, None)
        asyncio.create_task(_escalate_if_still_alive())
    # else: not tracked locally (e.g. the API server restarted since this
    # run started) — we can still mark it cancelled in the DB below, we
    # just can't actually kill the process from here.

    db.mark_status(run_id, "cancelled", url=run.get("url", ""))
    db.append_log(run_id, "error", "Cancelled by user")
    db.append_log(run_id, "done", "DONE")
    return {"status": "cancelling"}


@app.get("/stream/{run_id}")
async def stream_logs(run_id: str):
    async def event_generator():
        last_id = 0
        while True:
            entries = db.load_logs_since(run_id, last_id)
            if not entries and not db.load_run(run_id):
                # unknown run entirely — nothing will ever show up
                yield f"data: {json.dumps({'level': 'done', 'msg': 'DONE'})}\n\n"
                return
            for entry in entries:
                last_id = entry["id"]
                yield f"data: {json.dumps({'level': entry['level'], 'msg': entry['msg']})}\n\n"
                if entry["msg"] == "DONE":
                    return
            await asyncio.sleep(0.3)
    return StreamingResponse(event_generator(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/status/{run_id}")
async def get_status(run_id: str):
    run = db.load_run(run_id)
    if not run:
        return JSONResponse({"error": "Run not found"}, status_code=404)
    return run


@app.get("/runs")
async def list_runs():
    return list(reversed(list(db.load_all_runs().values())))


@app.get("/urls")
async def list_urls():
    """Distinct URLs that have completed runs — feeds the Trends view's URL picker."""
    return db.distinct_urls()


@app.get("/trends")
async def get_trends(url: str):
    history = db.load_runs_for_url(url)
    points = []
    for r in history:
        stats = r.get("stats", {}) or {}
        points.append({
            "run_id": r.get("run_id"),
            "created_at": r.get("created_at"),
            "total_bugs": stats.get("total_bugs", 0),
            "critical": stats.get("critical", 0),
            "high": stats.get("high", 0),
            "prd_coverage": stats.get("prd_coverage", 0),
            "a11y_issues": stats.get("a11y_issues", 0),
        })
    return {"url": url, "points": points}


@app.get("/runs/{run_id}/regression")
async def get_regression(run_id: str):
    run = db.load_run(run_id)
    if not run:
        return JSONResponse({"error": "Run not found"}, status_code=404)
    history = db.load_runs_for_url(run.get("url", ""))
    history = [r for r in history
               if r.get("run_id") != run_id and (r.get("created_at") or 0) < (run.get("created_at") or 0)]
    if not history:
        return {"new": run.get("bugs", []), "resolved": [], "persisting": [], "compared_to": None}
    previous = history[-1]
    result = compute_regression(run.get("bugs", []), previous.get("bugs", []))
    result["compared_to"] = previous.get("run_id")
    return result


@app.get("/report/{run_id}")
async def get_report(run_id: str):
    if not _is_safe_name(run_id):
        return JSONResponse({"error": "Invalid run_id"}, status_code=400)
    run = db.load_run(run_id)
    session_id = run.get("session_id") if run else None
    candidates = []
    if session_id and _is_safe_name(session_id):
        c = _safe_join(REPORTS_DIR, f"{session_id}_final_report.md")
        if c:
            candidates.append(c)
    c = _safe_join(REPORTS_DIR, f"pvos_{run_id[:8]}_final_report.md")
    if c:
        candidates.append(c)
    for c in candidates:
        if c.exists():
            return {"report": c.read_text()}
    return JSONResponse({"error": "Report not found"}, status_code=404)


@app.get("/tests/{filename}")
async def get_test_file(filename: str):
    fpath = _safe_join(TESTS_DIR, filename)
    if not fpath or not fpath.exists():
        return JSONResponse({"error": "File not found"}, status_code=404)
    return {"filename": filename, "content": fpath.read_text()}


@app.get("/screenshots/{filename}")
async def get_screenshot(filename: str):
    fpath = _safe_join(SCREENSHOTS_DIR, filename)
    if not fpath or not fpath.exists():
        return JSONResponse({"error": "Not found"}, status_code=404)
    return FileResponse(str(fpath), media_type="image/png")


@app.get("/screenshots/list/{session_id}")
async def list_screenshots(session_id: str):
    if not _is_safe_name(session_id):
        return JSONResponse({"error": "Invalid session_id"}, status_code=400)
    shots = sorted(SCREENSHOTS_DIR.glob(f"{session_id}_*.png"))
    return {"screenshots": [s.name for s in shots]}


@app.get("/videos/{session}/{filename}")
async def get_video(session: str, filename: str):
    fpath = _safe_join(VIDEOS_DIR, session, filename)
    if not fpath or not fpath.exists():
        return JSONResponse({"error": "Not found"}, status_code=404)
    return FileResponse(str(fpath), media_type="video/webm")


@app.get("/models", dependencies=[Depends(require_api_key)])
async def list_models():
    """Supported Gemini models, for the dashboard's model-select dropdown.
    Single source of truth is gemini_client.SUPPORTED_MODELS, so the
    dropdown and the server-side validation in /run can never drift apart."""
    return {
        "models": gemini_client.SUPPORTED_MODELS,
        "default": gemini_client.DEFAULT_MODEL,
    }


@app.get("/health")
async def health():
    return {
        "status": "ok", "version": "3.0.0",
        "auth_required": DASHBOARD_API_KEY is not None,
        "notifications_configured": NOTIFY_WEBHOOK_URL is not None,
    }


# ── serve the dashboard from the same process/port ──────────────────────────
# One FastAPI server now serves both the API and the dashboard UI, so a
# single `ngrok http 8000` tunnel exposes the whole app (no second 3000 port
# to juggle).

@app.get("/")
async def dashboard():
    if not DASHBOARD_INDEX.exists():
        return JSONResponse({"error": "dashboard/index.html not found"}, status_code=404)
    return FileResponse(str(DASHBOARD_INDEX), media_type="text/html")