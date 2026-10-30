import nest_asyncio
nest_asyncio.apply()
"""
graph/orchestrator.py
Week 3 — LangGraph multi-agent graph.

Graph flow:
  crawl → vision_analyze → prd_parse → qa_consolidate → pm_review → debate → final_report

State is passed between nodes as a typed dict.
"""
import json
import time
import asyncio
from pathlib import Path
from typing import TypedDict, Optional
from langgraph.graph import StateGraph, END

from core.browser    import BrowserSession
from core.anomaly    import AnomalyDetector
from core            import accessibility
from core            import performance
from agents.vision_agent import VisionAgent
from agents.prd_parser   import PRDParser
from agents.qa_agent     import QAAgent
from agents.pm_agent     import PMAgent
from agents.debate_agent import DebateAgent

REPORTS_DIR = Path(__file__).resolve().parent.parent / "outputs" / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent / "outputs" / "screenshots"


# ── shared state schema ───────────────────────────────────────────────────

class AgentState(TypedDict):
    session_id:       str
    target_url:       str
    max_steps:        int
    prd_path:         Optional[str]
    login:            Optional[dict]   # {login_url, username, password, user_selector, pass_selector, submit_selector}
    gemini_api_key:   Optional[str]    # per-run override; falls back to GEMINI_API_KEY env var if None
    gemini_model:     Optional[str]    # per-run override; falls back to GEMINI_MODEL env var if None

    # populated by nodes
    actions_log:      list
    anomalies:        list
    vision_analyses:  list
    a11y_results:     list
    performance_results: list
    responsive_results:  list
    prd_requirements: dict
    prd_coverage:     dict
    qa_result:        dict
    pm_result:        dict
    debate_verdicts:  list
    final_bugs:       list
    final_report:     str


async def _safe(coro, seconds: int, fallback: dict, what: str):
    """Hard time limit so one hung page-evaluate can't freeze the whole run."""
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except Exception as e:
        print(f"  [{what}] skipped ({type(e).__name__}) - took longer than {seconds}s")
        return fallback


# ── node functions ────────────────────────────────────────────────────────

def node_crawl(state: AgentState) -> AgentState:
    """Node 1: Playwright crawler + anomaly detection + vision analysis."""
    print(f"\n{'─'*50}")
    print(f"  NODE 1: Crawl + Vision")
    print(f"{'─'*50}")

    session_id   = state["session_id"]
    target_url   = state["target_url"]
    max_steps    = state["max_steps"]

    session      = BrowserSession(session_id=session_id, headless=True)
    detector     = AnomalyDetector()
    vision_agent = VisionAgent(api_key=state.get("gemini_api_key"), model=state.get("gemini_model"))
    anomalies    = []
    a11y_results = []
    performance_results = []
    visited_urls = []
    clicked_buttons = set()
    prev_b64     = None

    from urllib.parse import urlparse
    base_domain = urlparse(target_url).netloc

    async def _crawl():
        nonlocal prev_b64
        await session.start()
        try:
            login_cfg = state.get("login")
            if login_cfg and login_cfg.get("login_url"):
                await session.login(
                    login_cfg["login_url"],
                    login_cfg.get("username", ""),
                    login_cfg.get("password", ""),
                    login_cfg.get("user_selector"),
                    login_cfg.get("pass_selector"),
                    login_cfg.get("submit_selector"),
                )

            entry = await session.navigate(target_url)
            visited_urls.append(session.page.url)
            curr_b64  = session.get_latest_screenshot_b64()
            page_info = await session.get_page_info()

            found = detector.run_all(entry, prev_b64, curr_b64,
                                     session.js_errors, page_info)
            anomalies.extend(found)

            shots = sorted(SCREENSHOTS_DIR.glob(f"{session_id}_*.png"))
            if shots:
                vision_agent.analyze_screenshot(str(shots[-1]),
                                                entry["step"], session.page.url)
            a11y = await _safe(accessibility.scan_page(session.page, session.page.url, entry["step"]), 30, {"url": session.page.url, "step": entry["step"], "violations": [], "error": "timed out"}, "a11y")
            a11y_results.append(a11y)
            perf = await _safe(performance.measure_page(session.page, session.page.url, entry["step"]), 20, {"url": session.page.url, "step": entry["step"], "error": "timed out"}, "perf")
            performance_results.append(perf)
            prev_b64   = curr_b64
            steps_done = 1

            while steps_done < max_steps:
                pi          = await session.get_page_info()
                current_url = pi["url"]
                candidates  = []

                for link in pi.get("links", []):
                    href = link.get("href", "")
                    lurl = urlparse(href)
                    if (lurl.netloc == base_domain or lurl.netloc == "") \
                            and href not in visited_urls \
                            and not href.startswith(("mailto:", "tel:")) \
                            and lurl.fragment == "":
                        candidates.append(("link", href, link.get("text", "")))

                for btn in pi.get("buttons", []):
                    if btn:
                        candidates.append(("button", btn, btn))

                if not candidates:
                    entry2 = await session.scroll("down")
                    steps_done += 1
                    pi2 = await session.get_page_info()
                    if pi2["url"] == current_url and not pi2.get("links"):
                        break
                    continue

                action_taken = False
                for kind, target, label in candidates:
                    if steps_done >= max_steps:
                        break
                    if kind == "link" and target not in visited_urls:
                        entry2 = await session.navigate(target)
                        visited_urls.append(session.page.url)
                        action_taken = True
                    elif kind == "button" and label and label not in clicked_buttons:
                        selector = f"button:has-text('{label[:40]}')"
                        entry2   = await session.click(selector, description=label)
                        clicked_buttons.add(label)
                        action_taken = True

                    if action_taken:
                        curr_b64 = session.get_latest_screenshot_b64()
                        pi3      = await session.get_page_info()
                        found    = detector.run_all(entry2, prev_b64, curr_b64,
                                                    session.js_errors[-3:], pi3)
                        anomalies.extend(found)
                        shots = sorted(SCREENSHOTS_DIR.glob(f"{session_id}_*.png"))
                        if shots:
                            vision_agent.analyze_screenshot(str(shots[-1]),
                                                            entry2["step"], session.page.url)
                        a11y = await _safe(accessibility.scan_page(session.page, session.page.url, entry2["step"]), 30, {"url": session.page.url, "step": entry2["step"], "violations": [], "error": "timed out"}, "a11y")
                        a11y_results.append(a11y)
                        perf = await _safe(performance.measure_page(session.page, session.page.url, entry2["step"]), 20, {"url": session.page.url, "step": entry2["step"], "error": "timed out"}, "perf")
                        performance_results.append(perf)
                        prev_b64   = curr_b64
                        steps_done += 1
                        break

                if not action_taken:
                    break

        finally:
            session.save_session_log()
            await session.stop()

    asyncio.run(_crawl())

    return {
        **state,
        "actions_log":     session.actions_log,
        "anomalies":       anomalies,
        "vision_analyses": vision_agent.analyses,
        "a11y_results":    a11y_results,
        "performance_results": performance_results,
    }


def node_responsive(state: AgentState) -> AgentState:
    """Node: re-check a handful of already-crawled pages at tablet + mobile
    viewport sizes. Uses its own throwaway browser session — never touches
    the main crawl session, which has already shut down by this point."""
    print(f"\n{'─'*50}")
    print(f"  NODE: Responsive Check (tablet + mobile)")
    print(f"{'─'*50}")

    seen, visited = set(), []
    for a in state.get("actions_log", []):
        u = (a.get("params") or {}).get("url")
        if u and u not in seen:
            seen.add(u)
            visited.append(u)
    pages = visited[:3] if visited else [state["target_url"]]
    viewports = [("tablet", 768, 1024), ("mobile", 390, 844)]

    async def _check():
        session = BrowserSession(session_id=f"{state['session_id']}_responsive", headless=True)
        vision_agent = VisionAgent(api_key=state.get("gemini_api_key"), model=state.get("gemini_model"))
        out = []
        try:
            await session.start()
            for url in pages:
                for label, w, h in viewports:
                    snap = await session.snapshot_at_viewport(url, w, h, label)
                    if not snap:
                        continue
                    shot_path = SCREENSHOTS_DIR / snap["screenshot"]
                    analysis = None
                    if shot_path.exists():
                        analysis = vision_agent.analyze_screenshot(str(shot_path), 0, url)
                    out.append({**snap, "vision": analysis})
        finally:
            await session.stop()
        return out

    try:
        responsive_results = asyncio.run(_check())
    except Exception as e:
        print(f"  [Responsive] Skipped due to error: {e}")
        responsive_results = []

    print(f"  [Responsive] Checked {len(pages)} page(s) across {len(viewports)} viewports")
    return {**state, "responsive_results": responsive_results}


def node_prd_parse(state: AgentState) -> AgentState:
    """Node 2: Parse PRD and check coverage."""
    print(f"\n{'─'*50}")
    print(f"  NODE 2: PRD Parse + Coverage")
    print(f"{'─'*50}")

    prd_path = state.get("prd_path")
    if not prd_path:
        print("  [PRD] No PRD provided — skipping")
        return {**state, "prd_requirements": {}, "prd_coverage": {}}

    try:
        parser = PRDParser(api_key=state.get("gemini_api_key"), model=state.get("gemini_model"))
        reqs   = parser.parse_file(prd_path)

        # build visited URL list from actions_log entries (params.url for navigate actions)
        visited = []
        for a in state["actions_log"]:
            params = a.get("params", {})
            url = params.get("url")
            if url:
                visited.append(url)
        # dedupe while preserving order
        visited = list(dict.fromkeys(visited))

        coverage = parser.check_coverage(visited, state["vision_analyses"])
        return {**state, "prd_requirements": reqs, "prd_coverage": coverage}
    except Exception as e:
        print(f"  [PRD] Node failed: {e}")
        return {**state, "prd_requirements": {}, "prd_coverage": {"error": str(e), "coverage_pct": 0}}


def node_qa_consolidate(state: AgentState) -> AgentState:
    """Node 3: QA Agent consolidates all bugs."""
    print(f"\n{'─'*50}")
    print(f"  NODE 3: QA Agent")
    print(f"{'─'*50}")

    qa     = QAAgent(api_key=state.get("gemini_api_key"), model=state.get("gemini_model"))
    vision_bugs = []
    for a in state["vision_analyses"]:
        for b in a.get("potential_bugs", []):
            vision_bugs.append({**b, "step": a["step"], "url": a["url"]})

    result = qa.analyze(state["anomalies"], vision_bugs)
    return {**state, "qa_result": result}


def node_pm_review(state: AgentState) -> AgentState:
    """Node 4: PM Agent reviews bugs against PRD."""
    print(f"\n{'─'*50}")
    print(f"  NODE 4: PM Agent")
    print(f"{'─'*50}")

    bugs = state["qa_result"].get("bugs", [])
    if not bugs:
        print("  [PMAgent] No bugs to review")
        return {**state, "pm_result": {}}

    pm     = PMAgent(api_key=state.get("gemini_api_key"), model=state.get("gemini_model"))
    result = pm.review_bugs(bugs, state.get("prd_requirements", {}))
    return {**state, "pm_result": result}


def node_debate(state: AgentState) -> AgentState:
    """Node 5: Debate Agent — final verdict on each high bug."""
    print(f"\n{'─'*50}")
    print(f"  NODE 5: Debate Layer")
    print(f"{'─'*50}")

    bugs        = state["qa_result"].get("bugs", [])
    pm_reviewed = state["pm_result"].get("reviewed_bugs", [])

    if not bugs:
        return {**state, "debate_verdicts": [], "final_bugs": []}

    debate   = DebateAgent(api_key=state.get("gemini_api_key"), model=state.get("gemini_model"))
    verdicts = debate.debate_all(bugs, pm_reviewed, only_high=True)
    final    = debate.get_final_bug_list(bugs)

    return {**state, "debate_verdicts": verdicts, "final_bugs": final}


def node_final_report(state: AgentState) -> AgentState:
    """Node 6: Generate the final markdown report."""
    print(f"\n{'─'*50}")
    print(f"  NODE 6: Final Report")
    print(f"{'─'*50}")

    final_bugs   = state["final_bugs"]
    prd_coverage = state.get("prd_coverage", {})
    pm_result    = state.get("pm_result", {})
    session_id   = state["session_id"]

    critical = [b for b in final_bugs if b.get("final_severity") == "critical"]
    high     = [b for b in final_bugs if b.get("final_severity") == "high"]
    medium   = [b for b in final_bugs if b.get("final_severity","") == "medium"]
    low      = [b for b in final_bugs if b.get("final_severity","") == "low"]

    lines = [
        "# ProductValidation OS — Full Agent Report (Week 3)",
        "",
        f"**Session**: `{session_id}`  |  **URL**: {state['target_url']}",
        "",
        "## Executive Summary",
        "",
        pm_result.get("executive_summary", "No PM summary available."),
        "",
        "## Bug Summary",
        "",
        f"| Severity | Count |",
        f"|---|---|",
        f"| 🔴 Critical | {len(critical)} |",
        f"| 🔴 High | {len(high)} |",
        f"| 🟡 Medium | {len(medium)} |",
        f"| 🟢 Low | {len(low)} |",
        f"| **Total** | **{len(final_bugs)}** |",
        "",
    ]

    if prd_coverage:
        lines += [
            "## PRD Coverage",
            "",
            f"**Coverage: {prd_coverage.get('coverage_pct', 0)}%**",
            "",
        ]
        if prd_coverage.get("uncovered_pages"):
            for p in prd_coverage["uncovered_pages"]:
                lines.append(f"- ❌ `{p['path']}` — {p['name']} not tested")
        lines.append("")

    lines += ["## Validated Bugs (Debate-Confirmed)", ""]

    for i, bug in enumerate(final_bugs, 1):
        sev   = bug.get("final_severity", bug.get("severity", "?"))
        emoji = {"critical":"🔴","high":"🔴","medium":"🟡","low":"🟢"}.get(sev,"⚪")
        lines += [
            f"### {emoji} {bug.get('id','?')}: {bug.get('title','Untitled')}",
            f"**Severity**: {sev.upper()}  |  **URL**: `{bug.get('url','')}`  |  "
            f"**Fix time**: {bug.get('estimated_fix_time','')}",
            "",
        ]
        steps = bug.get("steps_to_reproduce", [])
        if steps:
            lines.append("**Steps to reproduce:**")
            for s in steps:
                lines.append(f"1. {s}")
            lines.append("")
        if bug.get("expected"):
            lines.append(f"**Expected**: {bug['expected']}")
        if bug.get("actual"):
            lines.append(f"**Actual**: {bug['actual']}")
        if bug.get("fix_recommendation"):
            lines.append(f"**Fix**: {bug['fix_recommendation']}")
        if bug.get("reasoning"):
            lines.append(f"**Why valid**: {bug['reasoning']}")
        lines.append("")

    lines += ["---", "*Generated by ProductValidation OS — Week 3 Multi-Agent Build*"]

    report = "\n".join(lines)
    out    = REPORTS_DIR / f"{session_id}_w3_final_report.md"
    out.write_text(report)

    # also save full state as JSON for debugging
    state_out = REPORTS_DIR / f"{session_id}_w3_state.json"
    safe_state = {k: v for k, v in state.items()
                  if k not in ("actions_log",)}  # skip large fields
    state_out.write_text(json.dumps(safe_state, indent=2, default=str))

    print(f"  [Report] Saved: {out}")
    print(f"  [Report] {len(final_bugs)} validated bugs in final report")

    return {**state, "final_report": report}


# ── build the graph ───────────────────────────────────────────────────────

def build_graph():
    g = StateGraph(AgentState)

    g.add_node("crawl",        node_crawl)
    g.add_node("responsive",   node_responsive)
    g.add_node("prd_parse",    node_prd_parse)
    g.add_node("qa",           node_qa_consolidate)
    g.add_node("pm",           node_pm_review)
    g.add_node("debate",       node_debate)
    g.add_node("final_report", node_final_report)

    g.set_entry_point("crawl")
    g.add_edge("crawl",        "responsive")
    g.add_edge("responsive",   "prd_parse")
    g.add_edge("prd_parse",    "qa")
    g.add_edge("qa",           "pm")
    g.add_edge("pm",           "debate")
    g.add_edge("debate",       "final_report")
    g.add_edge("final_report", END)

    return g.compile()
