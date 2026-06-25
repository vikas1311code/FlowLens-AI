"""
core/pipeline.py
The validation pipeline itself: crawl, vision, accessibility, performance,
responsive check, PRD coverage, QA, PM, debate, impact scoring, repro
videos, generated tests, final report.

This module knows nothing about HTTP, SQLite, or subprocesses — it reports
progress purely through two callbacks, so the same pipeline can be driven
by a worker subprocess (writing to SQLite, for the dashboard) or by
anything else that wants to run a validation:

  on_update(partial: dict)      — new/changed fields for the run's state
  on_log(level: str, msg: str)  — one log line

Running each validation in its own OS process (rather than as an asyncio
background task sharing the API server's event loop) is what makes runs
actually execute concurrently — the crawl pipeline is fundamentally
blocking under the hood (LangGraph nodes use nest_asyncio to nest a
blocking sub-loop), so two of these running inside the same process would
just serialize behind each other no matter how many were "allowed" to be
in progress at once.
"""
import builtins
import re
import sys
from pathlib import Path
from typing import Callable, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
SCREENSHOTS_DIR = BASE_DIR / "outputs" / "screenshots"

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\u2190-\u21FF\uFE0F"
    "]+",
    flags=re.UNICODE,
)


def _clean(text: str) -> str:
    text = _EMOJI_RE.sub("", text).strip()
    if text and len(set(text)) <= 2 and re.match(r"^[\W_]+$", text):
        return ""  # pure decorative separator line, e.g. "──────────"
    return text


def run_pipeline(
    run_id: str,
    url: str,
    steps: int,
    prd_path: Optional[str],
    login_cfg: Optional[dict],
    on_update: Callable[[dict], None],
    on_log: Callable[[str, str], None],
    gemini_api_key: Optional[str] = None,
    gemini_model: Optional[str] = None,
) -> dict:
    """Runs the full pipeline. Calls on_update/on_log as it goes, and
    returns the final state dict too (also already delivered via on_update)."""

    def log(msg, level="info"):
        cleaned = _clean(str(msg))
        if cleaned:
            on_log(level, cleaned)

    original_print = builtins.print

    def streaming_print(*args, **kwargs):
        log(" ".join(str(a) for a in args))
        original_print(*args, **kwargs)

    state = {}
    try:
        builtins.print = streaming_print

        for mod in list(sys.modules):
            if mod.startswith(("graph", "agents.", "core.")) and mod not in (
                "core.pipeline", "core.db",
            ):
                del sys.modules[mod]

        from graph import build_graph
        from agents.video_recorder import VideoRecorder
        from agents.test_generator import TestGenerator
        from agents.impact_scorer import score_all
        from core.reporter import generate_full_report
        from core import accessibility, performance

        session_id = f"pvos_{run_id[:8]}"
        on_update({"session_id": session_id, "status": "running"})
        log(f"Starting validation for {url}")
        log(f"Max steps: {steps}")
        if prd_path:
            log(f"PRD loaded: {Path(prd_path).name}")
        if login_cfg:
            log(f"Login configured via {login_cfg.get('login_url')}")

        log("Phase 1: Crawling + Vision + Accessibility + Performance", "phase")
        graph = build_graph()
        initial_state = {
            "session_id": session_id, "target_url": url, "max_steps": steps,
            "prd_path": prd_path, "login": login_cfg,
            "gemini_api_key": gemini_api_key, "gemini_model": gemini_model,
            "actions_log": [], "anomalies": [], "vision_analyses": [], "a11y_results": [],
            "performance_results": [], "responsive_results": [],
            "prd_requirements": {}, "prd_coverage": {}, "qa_result": {}, "pm_result": {},
            "debate_verdicts": [], "final_bugs": [], "final_report": "",
        }

        state = dict(initial_state)
        for update in graph.stream(initial_state, stream_mode="updates"):
            for node_name, partial in update.items():
                state.update(partial)

                if node_name == "crawl":
                    shots = sorted(SCREENSHOTS_DIR.glob(f"{session_id}_*.png"))
                    a11y_summary = accessibility.summarize(state.get("a11y_results", []))
                    perf_summary = performance.summarize(state.get("performance_results", []))
                    on_update({
                        "screenshots": [s.name for s in shots],
                        "vision_analyses": state.get("vision_analyses", []),
                        "a11y_results": state.get("a11y_results", []),
                        "performance_results": state.get("performance_results", []),
                        "stats": {
                            "pages_crawled": len(shots),
                            "a11y_issues": a11y_summary["total"],
                            "avg_lcp_ms": perf_summary["avg_lcp_ms"],
                            "performance_by_rating": perf_summary["by_rating"],
                        },
                    })
                    log(f"Crawl done: {len(shots)} pages, "
                        f"{len(state.get('anomalies', []))} anomalies, "
                        f"{a11y_summary['total']} accessibility issues", "success")

                elif node_name == "responsive":
                    on_update({"responsive_results": state.get("responsive_results", [])})
                    log(f"Responsive check: {len(state.get('responsive_results', []))} "
                        f"viewport snapshots taken", "success")

                elif node_name == "prd_parse":
                    cov = state.get("prd_coverage", {})
                    on_update({"prd_coverage": cov, "stats": {"prd_coverage": cov.get("coverage_pct", 0)}})

                elif node_name == "qa":
                    draft_bugs = state.get("qa_result", {}).get("bugs", [])
                    on_update({"bugs": draft_bugs, "qa_summary": state.get("qa_result", {}).get("summary", "")})
                    log(f"QA flagged {len(draft_bugs)} candidate bugs", "success")

                elif node_name == "pm":
                    on_update({"pm_result": state.get("pm_result", {})})

                elif node_name == "debate":
                    confirmed = state.get("final_bugs", [])
                    on_update({"bugs": confirmed, "debate_verdicts": state.get("debate_verdicts", [])})
                    log(f"Debate confirmed {len(confirmed)} bugs", "success")

        final_bugs          = state.get("final_bugs", [])
        pm_result            = state.get("pm_result", {})
        prd_cov              = state.get("prd_coverage", {})
        vision_analyses      = state.get("vision_analyses", [])
        a11y_results         = state.get("a11y_results", [])
        performance_results  = state.get("performance_results", [])
        responsive_results   = state.get("responsive_results", [])
        debate_verdicts      = state.get("debate_verdicts", [])
        qa_result            = state.get("qa_result", {})

        log("Phase 2: Business Impact Scoring", "phase")
        scored_bugs = score_all(final_bugs, pm_result.get("reviewed_bugs", []))
        on_update({"bugs": scored_bugs})

        log("Phase 3: Recording bug repro videos", "phase")
        recorder = VideoRecorder(base_url=url)
        videos = recorder.record_all(scored_bugs, session_id, only_high=True)
        for v in videos:
            v["url"] = f"/videos/{session_id}/{Path(v['video_path']).name}"
        on_update({"videos": videos})
        log(f"{len(videos)} videos recorded", "success")

        log("Phase 4: Generating Playwright tests", "phase")
        generator = TestGenerator(base_url=url, api_key=gemini_api_key, model=gemini_model)
        test_files = generator.generate_all(scored_bugs)
        on_update({"tests": test_files})
        log(f"{len(test_files)} test files generated", "success")

        log("Phase 5: Writing final report", "phase")
        generate_full_report(
            session_id=session_id, target_url=url, scored_bugs=scored_bugs,
            videos=videos, test_files=test_files, prd_coverage=prd_cov,
            pm_result=pm_result,
        )

        a11y_summary = accessibility.summarize(a11y_results)
        perf_summary = performance.summarize(performance_results)
        shots = sorted(SCREENSHOTS_DIR.glob(f"{session_id}_*.png"))

        final = {
            "status": "complete",
            "bugs": scored_bugs, "videos": videos, "tests": test_files,
            "prd_coverage": prd_cov, "pm_result": pm_result,
            "vision_analyses": vision_analyses, "a11y_results": a11y_results,
            "performance_results": performance_results, "responsive_results": responsive_results,
            "debate_verdicts": debate_verdicts, "qa_summary": qa_result.get("summary", ""),
            "screenshots": [s.name for s in shots],
            "stats": {
                "total_bugs": len(scored_bugs),
                "critical": len([b for b in scored_bugs if b.get("final_severity") == "critical"]),
                "high": len([b for b in scored_bugs if b.get("final_severity") == "high"]),
                "medium": len([b for b in scored_bugs if b.get("final_severity", "") == "medium"]),
                "low": len([b for b in scored_bugs if b.get("final_severity", "") == "low"]),
                "videos": len(videos), "tests": len(test_files),
                "prd_coverage": prd_cov.get("coverage_pct", 0),
                "pages_crawled": len(shots),
                "a11y_issues": a11y_summary["total"],
                "a11y_by_impact": a11y_summary["by_impact"],
                "avg_lcp_ms": perf_summary["avg_lcp_ms"],
                "performance_by_rating": perf_summary["by_rating"],
            },
        }
        on_update(final)
        log(f"Complete! {len(scored_bugs)} validated bugs.", "success")
        return final

    except Exception as e:
        import traceback
        original_print(traceback.format_exc())
        on_update({"status": "error", "error": str(e)})
        log(f"Error: {e}", "error")
        return {"status": "error", "error": str(e)}

    finally:
        builtins.print = original_print