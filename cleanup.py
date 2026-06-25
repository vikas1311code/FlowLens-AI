#!/usr/bin/env python3
"""
cleanup.py
Deletes old screenshots and videos — the actual disk-space hogs in
outputs/ — for runs older than a cutoff, while leaving the run records
themselves in SQLite alone, so Trends/regression history survives even
after the heavy files are gone.

Usage:
  python3 cleanup.py --older-than 30            # dry-run preview (default)
  python3 cleanup.py --older-than 30 --apply    # actually delete
  python3 cleanup.py --keep-latest 20 --apply   # always keep N most recent runs' files
"""
import argparse
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core.db as db

BASE_DIR        = Path(__file__).resolve().parent
SCREENSHOTS_DIR = BASE_DIR / "outputs" / "screenshots"
VIDEOS_DIR      = BASE_DIR / "outputs" / "videos"
WORKER_LOGS_DIR = BASE_DIR / "outputs" / "worker_logs"


def human_size(n: float) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def main():
    p = argparse.ArgumentParser(description="Clean up old screenshots/videos from outputs/")
    p.add_argument("--older-than", type=int, default=30,
                   help="Delete files for runs older than this many days (default: 30)")
    p.add_argument("--keep-latest", type=int, default=0,
                   help="Always keep files for the N most recent runs, regardless of age")
    p.add_argument("--apply", action="store_true",
                   help="Actually delete. Without this flag, it's a dry-run preview only.")
    args = p.parse_args()

    db.init_db()
    runs = list(db.load_all_runs().values())
    runs.sort(key=lambda r: r.get("created_at", 0), reverse=True)  # newest first

    cutoff = time.time() - args.older_than * 86400
    keep_ids = {r["run_id"] for r in runs[:args.keep_latest]} if args.keep_latest else set()

    to_clean = [r for r in runs
                if r.get("run_id") not in keep_ids and (r.get("created_at") or 0) < cutoff]

    if not to_clean:
        print(f"Nothing to clean — no runs older than {args.older_than} day(s) "
              f"(beyond the {args.keep_latest} most recent, which are always kept).")
        return

    print(f"{'Would clean' if not args.apply else 'Cleaning'} "
          f"{len(to_clean)} run(s) older than {args.older_than} day(s):\n")

    total_bytes = 0
    total_files = 0
    for run in to_clean:
        session_id = run.get("session_id")
        if not session_id:
            continue

        shots = [f for f in SCREENSHOTS_DIR.glob(f"{session_id}_*.png") if f.is_file()]
        video_dir = VIDEOS_DIR / session_id
        videos = [f for f in video_dir.glob("*") if f.is_file()] if video_dir.exists() else []
        worker_log = WORKER_LOGS_DIR / f"{run['run_id']}.log"

        run_bytes = sum(f.stat().st_size for f in shots)
        run_bytes += sum(f.stat().st_size for f in videos)
        run_bytes += worker_log.stat().st_size if worker_log.exists() else 0
        total_bytes += run_bytes
        total_files += len(shots) + len(videos) + (1 if worker_log.exists() else 0)

        age_days = (time.time() - (run.get("created_at") or 0)) / 86400
        url_display = (run.get("url") or "")[:48]
        print(f"  {run['run_id']:<14} {url_display:<48} {age_days:>4.0f}d old  "
              f"{len(shots):>3} screenshots, {len(videos)} video(s)  ({human_size(run_bytes)})")

        if args.apply:
            for f in shots:
                f.unlink(missing_ok=True)
            if video_dir.exists():
                shutil.rmtree(video_dir, ignore_errors=True)
            worker_log.unlink(missing_ok=True)

    verb = "Deleted" if args.apply else "Would delete"
    print(f"\n{verb} {total_files} file(s) totaling {human_size(total_bytes)} "
          f"across {len(to_clean)} run(s).")
    if not args.apply:
        print("This was a dry run — nothing was deleted. Re-run with --apply to actually delete.")


if __name__ == "__main__":
    main()