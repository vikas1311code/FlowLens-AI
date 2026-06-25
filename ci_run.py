#!/usr/bin/env python3
"""
ci_run.py
Run a validation from the command line — no dashboard, no server — and
exit with a non-zero code if bugs at or above a chosen severity are found.
Built for CI pipelines (GitHub Actions, GitLab CI, Jenkins, anything that
checks an exit code).

Examples
--------
  # Just run it and see the summary, always exit 0
  python3 ci_run.py https://staging.myapp.com

  # Fail the build if any critical bug is found
  python3 ci_run.py https://staging.myapp.com --fail-on critical

  # Full run with a PRD, failing on high-or-worse, with videos + tests
  python3 ci_run.py https://staging.myapp.com --prd testshop_prd.md \\
      --fail-on high --record-videos --generate-tests --output report.md

  # Behind a login wall
  python3 ci_run.py https://staging.myapp.com --fail-on critical \\
      --login-url https://staging.myapp.com/login \\
      --login-username ci@myapp.com --login-password "$CI_TEST_PASSWORD"

GitHub Actions step:
  - name: Validate staging
    run: |
      python3 ci_run.py "$STAGING_URL" --fail-on critical --output report.md
    env:
      GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
"""
import argparse
import os
import sys
import time
from pathlib import Path

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def parse_args():
    p = argparse.ArgumentParser(description="ProductValidation OS — CI/CD runner")
    p.add_argument("url", help="Target URL to validate")
    p.add_argument("--steps", type=int, default=10, help="Max crawl steps (default 10)")
    p.add_argument("--prd", default=None, help="Path to a PRD markdown/text file")
    p.add_argument("--fail-on", choices=["critical", "high", "medium", "low", "none"],
                    default="none", help="Exit non-zero if a bug at or above this "
                                          "severity is found (default: none = always exit 0)")
    p.add_argument("--record-videos", action="store_true", help="Record repro videos for high-impact bugs")
    p.add_argument("--generate-tests", action="store_true", help="Generate Playwright tests for found bugs")
    p.add_argument("--output", default=None, help="Path to write the final markdown report")
    p.add_argument("--login-url", default=None)
    p.add_argument("--login-username", default=None)
    p.add_argument("--login-password", default=None)
    p.add_argument("--login-user-selector", default=None)
    p.add_argument("--login-pass-selector", default=None)
    p.add_argument("--login-submit-selector", default=None)
    return p.parse_args()


def main():
    args = parse_args()

    from graph import build_graph
    from agents.impact_scorer import score_all
    from core.reporter import generate_full_report
    from core import notifier

    login_cfg = None
    if args.login_url:
        login_cfg = {
            "login_url": args.login_url,
            "username": args.login_username or "",
            "password": args.login_password or "",
            "user_selector": args.login_user_selector,
            "pass_selector": args.login_pass_selector,
            "submit_selector": args.login_submit_selector,
        }

    session_id = f"ci_{int(time.time())}"
    print(f"== ProductValidation OS (CI mode) ==")
    print(f"Target : {args.url}")
    print(f"Session: {session_id}")
    print(f"Steps  : {args.steps}")
    print()

    graph = build_graph()
    initial_state = {
        "session_id": session_id, "target_url": args.url, "max_steps": args.steps,
        "prd_path": args.prd, "login": login_cfg,
        "actions_log": [], "anomalies": [], "vision_analyses": [], "a11y_results": [],
        "performance_results": [], "responsive_results": [],
        "prd_requirements": {}, "prd_coverage": {}, "qa_result": {}, "pm_result": {},
        "debate_verdicts": [], "final_bugs": [], "final_report": "",
    }
    state = graph.invoke(initial_state)

    final_bugs = state.get("final_bugs", [])
    pm_result  = state.get("pm_result", {})
    prd_cov    = state.get("prd_coverage", {})
    scored_bugs = score_all(final_bugs, pm_result.get("reviewed_bugs", []))

    videos, test_files = [], []
    if args.record_videos:
        from agents.video_recorder import VideoRecorder
        videos = VideoRecorder(base_url=args.url).record_all(scored_bugs, session_id, only_high=True)
    if args.generate_tests:
        from agents.test_generator import TestGenerator
        test_files = TestGenerator(base_url=args.url).generate_all(scored_bugs)

    report = generate_full_report(
        session_id=session_id, target_url=args.url, scored_bugs=scored_bugs,
        videos=videos, test_files=test_files, prd_coverage=prd_cov, pm_result=pm_result,
    )
    if args.output:
        Path(args.output).write_text(report)
        print(f"Report written to {args.output}")

    # also drop the summary into GitHub Actions' job summary, if running there
    gh_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh_summary:
        with open(gh_summary, "a") as f:
            f.write(report)

    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for b in scored_bugs:
        sev = b.get("final_severity") or b.get("severity") or "low"
        counts[sev] = counts.get(sev, 0) + 1

    print()
    print("== Summary ==")
    print(f"Critical: {counts['critical']}   High: {counts['high']}   "
          f"Medium: {counts['medium']}   Low: {counts['low']}")
    print(f"PRD coverage: {prd_cov.get('coverage_pct', 0)}%")

    webhook = os.environ.get("NOTIFY_WEBHOOK_URL")
    if webhook:
        notifier.notify_run_complete(webhook, {
            "url": args.url, "status": "complete",
            "stats": {**counts, "total_bugs": len(scored_bugs),
                      "prd_coverage": prd_cov.get("coverage_pct", 0)},
        })

    if args.fail_on == "none":
        sys.exit(0)

    threshold = SEVERITY_RANK[args.fail_on]
    worst_found = max([SEVERITY_RANK.get(b.get("final_severity") or b.get("severity") or "low", 0) for b in scored_bugs], default=-1)
    if worst_found >= threshold:
        print(f"\nFAIL: found a bug at or above '{args.fail_on}' severity.")
        sys.exit(1)

    print(f"\nPASS: nothing at or above '{args.fail_on}' severity.")
    sys.exit(0)


if __name__ == "__main__":
    main()