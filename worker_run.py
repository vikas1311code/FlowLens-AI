#!/usr/bin/env python3
"""
worker_run.py
Runs ONE validation pipeline to completion, in its own OS process, writing
progress to SQLite as it goes. Spawned by api/server.py's /run endpoint —
not meant to be run manually, though nothing stops you:

  python3 worker_run.py <run_id> <url> <steps> [--prd-path PATH] [--gemini-model MODEL]

If the run needs login credentials and/or a per-run Gemini API key, pass
--has-login / --has-gemini-key and write a JSON object on stdin with the
relevant keys — never as a CLI argument, since CLI args are visible to
anyone on the machine via `ps aux` / /proc, while stdin isn't. The model
name isn't a secret, so it's a plain CLI arg.

  stdin JSON shape: {"login": {...} | null, "gemini_api_key": "..." | null}

Why a whole subprocess instead of just an asyncio background task: the
crawl pipeline is blocking under the hood (LangGraph nodes nest a blocking
event loop via nest_asyncio), so two of these sharing one process's event
loop would just serialize behind each other. Separate processes give real
parallelism, and SIGTERM cleanly cancels one without touching the others
or the API server itself.
"""
import argparse
import json
import os
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import core.db as db
from core.pipeline import run_pipeline


def _install_sigterm_handler(run_id: str):
    def handle(signum, frame):
        try:
            db.mark_status(run_id, "cancelled")
            db.append_log(run_id, "error", "Cancelled by user")
            db.append_log(run_id, "done", "DONE")
        except Exception:
            pass
        sys.exit(1)
    signal.signal(signal.SIGTERM, handle)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("run_id")
    p.add_argument("url")
    p.add_argument("steps", type=int)
    p.add_argument("--prd-path", default=None)
    p.add_argument("--has-login", action="store_true")
    p.add_argument("--has-gemini-key", action="store_true",
                    help="If set, a per-run Gemini API key is included in the stdin JSON payload "
                         "(under 'gemini_api_key'), overriding GEMINI_API_KEY from .env for this run only.")
    p.add_argument("--gemini-model", default=None,
                    help="Per-run Gemini model override (not secret, safe as a CLI arg). "
                         "Falls back to GEMINI_MODEL env var / core/gemini_client.py default if omitted.")
    args = p.parse_args()

    # Put this process (and anything it spawns, like the Playwright/Chromium
    # subprocess) in its own process group on POSIX, so a cancel request can
    # signal the whole group at once instead of leaking an orphaned browser.
    if sys.platform != "win32":
        try:
            os.setpgrp()
        except Exception:
            pass

    db.init_db()
    _install_sigterm_handler(args.run_id)

    login_cfg = None
    gemini_api_key = None
    if args.has_login or args.has_gemini_key:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        login_cfg = payload.get("login") if args.has_login else None
        gemini_api_key = payload.get("gemini_api_key") if args.has_gemini_key else None

    def on_update(partial: dict):
        run = db.load_run(args.run_id) or {"run_id": args.run_id, "url": args.url}
        for k, v in partial.items():
            if k == "stats" and isinstance(v, dict) and isinstance(run.get("stats"), dict):
                run["stats"].update(v)
            else:
                run[k] = v
        db.save_run(run)

    def on_log(level: str, msg: str):
        db.append_log(args.run_id, level, msg)

    final = run_pipeline(
        run_id=args.run_id, url=args.url, steps=args.steps,
        prd_path=args.prd_path, login_cfg=login_cfg,
        on_update=on_update, on_log=on_log,
        gemini_api_key=gemini_api_key, gemini_model=args.gemini_model,
    )

    # notify, if configured — best effort, never fails the run
    try:
        from dotenv import load_dotenv
        load_dotenv()
        webhook = os.environ.get("NOTIFY_WEBHOOK_URL")
        if webhook:
            from core import notifier
            run = db.load_run(args.run_id) or {}
            notifier.notify_run_complete(webhook, run, os.environ.get("PUBLIC_DASHBOARD_URL"))
    except Exception as e:
        print(f"[worker] notification failed: {e}")

    db.append_log(args.run_id, "done", "DONE")
    sys.exit(0 if final.get("status") == "complete" else 1)


if __name__ == "__main__":
    main()