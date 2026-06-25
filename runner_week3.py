"""
runner_week3.py
Week 3 entry point — full multi-agent LangGraph pipeline.

Usage:
  python runner_week3.py http://localhost:5001 --steps 10 --prd testshop_prd.md
"""
import argparse
import time
from graph import build_graph


def main():
    parser = argparse.ArgumentParser(description="ProductValidation OS — Week 3")
    parser.add_argument("url",     help="Target URL")
    parser.add_argument("--steps", type=int,   default=10)
    parser.add_argument("--prd",   type=str,   default=None)
    args = parser.parse_args()

    session_id = f"pvos_w3_{int(time.time())}"

    print(f"\n{'='*55}")
    print(f"  ProductValidation OS — Week 3 (Multi-Agent)")
    print(f"  Session : {session_id}")
    print(f"  Target  : {args.url}")
    print(f"  Agents  : Crawler → Vision → PRD → QA → PM → Debate")
    print(f"{'='*55}")

    graph = build_graph()

    initial_state = {
        "session_id":       session_id,
        "target_url":       args.url,
        "max_steps":        args.steps,
        "prd_path":         args.prd,
        "actions_log":      [],
        "anomalies":        [],
        "vision_analyses":  [],
        "prd_requirements": {},
        "prd_coverage":     {},
        "qa_result":        {},
        "pm_result":        {},
        "debate_verdicts":  [],
        "final_bugs":       [],
        "final_report":     "",
    }

    final_state = graph.invoke(initial_state)

    # ── print final summary ───────────────────────────────────────────────
    final_bugs = final_state.get("final_bugs", [])
    coverage   = final_state.get("prd_coverage", {})

    print(f"\n{'='*55}")
    print(f"  WEEK 3 COMPLETE")
    print(f"{'='*55}")
    print(f"  Validated bugs   : {len(final_bugs)}")
    critical = [b for b in final_bugs if b.get("final_severity") == "critical"]
    high     = [b for b in final_bugs if b.get("final_severity") == "high"]
    print(f"  Critical         : {len(critical)}")
    print(f"  High             : {len(high)}")
    if coverage:
        print(f"  PRD coverage     : {coverage.get('coverage_pct', 0)}%")
    print(f"  Report           : outputs/reports/{session_id}_w3_final_report.md")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
