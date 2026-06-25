"""
agents/pm_agent.py - migrated to google.genai
"""
import json
from core.gemini_client import generate

PM_PROMPT = """
You are a senior product manager reviewing a QA bug list against the PRD.
For each bug classify as PRD_VIOLATION | NICE_TO_FIX | OUT_OF_SCOPE and assign priority 1-10.
Respond with ONLY valid JSON (no markdown, no backticks):
{
  "reviewed_bugs": [
    {
      "id": "BUG-001",
      "prd_classification": "PRD_VIOLATION",
      "violated_requirement": "which user story or criterion",
      "priority_score": 8,
      "pm_note": "short note"
    }
  ],
  "prd_health": "good | at_risk | failing",
  "executive_summary": "2-3 sentences for non-technical stakeholder"
}
"""

class PMAgent:
    def __init__(self, api_key=None, model=None):
        self.review = {}
        self.api_key = api_key
        self.model = model

    def review_bugs(self, bugs, prd_requirements):
        print(f"  [PMAgent] Reviewing {len(bugs)} bugs against PRD...")
        try:
            prompt = PM_PROMPT + "\nPRD:\n" + json.dumps(prd_requirements, indent=2)
            prompt += "\nBugs:\n" + json.dumps(bugs, indent=2)
            raw = generate(prompt, api_key=self.api_key, model=self.model)
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"): raw = raw[4:]
            self.review = json.loads(raw.strip())
            reviewed = self.review.get("reviewed_bugs", [])
            health   = self.review.get("prd_health", "?")
            emoji    = {"good":"✅","at_risk":"⚠️","failing":"🔴"}.get(health,"❓")
            print(f"  [PMAgent] PRD Health: {emoji} {health.upper()}")
            violations = [r for r in reviewed if r.get("prd_classification") == "PRD_VIOLATION"]
            print(f"  [PMAgent] PRD Violations: {len(violations)}/{len(reviewed)}")
            for v in violations:
                print(f"    ❌ {v['id']}: {str(v.get('violated_requirement',''))[:70]}")
            return self.review
        except Exception as e:
            print(f"  [PMAgent] Error: {e}")
            return {"reviewed_bugs": [], "prd_health": "unknown", "executive_summary": str(e)}