"""
agents/debate_agent.py - migrated to google.genai
"""
import json
from core.gemini_client import generate

DEBATE_PROMPT = """
You are a neutral engineering judge in a bug triage meeting.
Give a FINAL VERDICT on this bug.
Respond with ONLY valid JSON (no markdown, no backticks):
{
  "bug_id": "BUG-001",
  "verdict": "VALID | WONTFIX | NEEDS_RETEST",
  "final_severity": "critical | high | medium | low",
  "reasoning": "2-3 sentences explaining the verdict",
  "fix_recommendation": "specific suggestion for the developer",
  "estimated_fix_time": "15min | 1hr | half-day | full-day"
}
"""

class DebateAgent:
    def __init__(self, api_key=None, model=None):
        self.verdicts = []
        self.api_key = api_key
        self.model = model

    def debate_bug(self, bug, pm_review_item):
        prompt = DEBATE_PROMPT + "\nBug:\n" + json.dumps(bug, indent=2)
        prompt += "\nPM Review:\n" + json.dumps(pm_review_item, indent=2)
        try:
            raw = generate(prompt, api_key=self.api_key, model=self.model)
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"): raw = raw[4:]
            verdict = json.loads(raw.strip())
            self.verdicts.append(verdict)
            v     = verdict.get("verdict", "?")
            sev   = verdict.get("final_severity", "?")
            emoji = {"VALID":"✅","WONTFIX":"🚫","NEEDS_RETEST":"🔄"}.get(v,"❓")
            sev_e = {"critical":"🔴","high":"🔴","medium":"🟡","low":"🟢"}.get(sev,"⚪")
            print(f"    {emoji} {verdict.get('bug_id','?')} → {v} {sev_e} [{sev}] (fix: {verdict.get('estimated_fix_time','?')})")
            return verdict
        except Exception as e:
            print(f"    [DebateAgent] Error: {e}")
            return {"bug_id": bug.get("id","?"), "verdict": "NEEDS_RETEST",
                   "final_severity": bug.get("severity","medium"),
                   "reasoning": str(e), "fix_recommendation": "Manual review", "estimated_fix_time": "1hr"}

    def debate_all(self, bugs, pm_reviewed, only_high=True):
        pm_lookup  = {r["id"]: r for r in pm_reviewed}
        to_debate  = [b for b in bugs if b.get("severity") in ("critical","high")] if only_high else bugs
        print(f"  [DebateAgent] Debating {len(to_debate)} high/critical bugs...")
        for bug in to_debate:
            self.debate_bug(bug, pm_lookup.get(bug.get("id",""), {}))
        valid   = [v for v in self.verdicts if v["verdict"] == "VALID"]
        wontfix = [v for v in self.verdicts if v["verdict"] == "WONTFIX"]
        retest  = [v for v in self.verdicts if v["verdict"] == "NEEDS_RETEST"]
        print(f"  [DebateAgent] ✅ {len(valid)} VALID  🚫 {len(wontfix)} WONTFIX  🔄 {len(retest)} NEEDS_RETEST")
        return self.verdicts

    def get_final_bug_list(self, all_bugs):
        """Only WONTFIX bugs are dropped — those are debate-confirmed false
        positives. NEEDS_RETEST (almost always the fallback from a failed/
        malformed debate API call, see debate_bug's except-block) must NOT
        be dropped: that would silently delete a real high/critical bug from
        the report just because one Gemini call hiccuped. It's kept with its
        verdict visible so the dashboard/report can flag it as unconfirmed
        rather than pretending it never existed."""
        verdict_map = {v["bug_id"]: v for v in self.verdicts}
        final = []
        for bug in all_bugs:
            bid = bug.get("id","?")
            if bid in verdict_map:
                v = verdict_map[bid]
                if v["verdict"] == "WONTFIX":
                    continue  # debate-confirmed not a real bug — drop it
                final.append({**bug, "final_severity": v.get("final_severity", bug.get("severity","medium")),
                             "verdict": v["verdict"], "reasoning": v.get("reasoning",""),
                             "fix_recommendation": v.get("fix_recommendation",""),
                             "estimated_fix_time": v.get("estimated_fix_time","")})
            else:
                final.append({**bug, "final_severity": bug.get("severity","medium"),
                             "verdict": "VALID", "fix_recommendation": ""})
        return final