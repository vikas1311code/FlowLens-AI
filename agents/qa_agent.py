"""
agents/qa_agent.py - migrated to google.genai
"""
import json
from core.gemini_client import generate

QA_PROMPT = """
You are a senior QA engineer. Consolidate these anomalies into a clean de-duplicated bug list.
Respond with ONLY valid JSON (no markdown, no backticks):
{
  "bugs": [
    {
      "id": "BUG-001",
      "title": "short bug title max 10 words",
      "severity": "critical | high | medium | low",
      "url": "which page",
      "steps_to_reproduce": ["step 1", "step 2"],
      "expected": "what should happen",
      "actual": "what actually happens",
      "confidence": 0.95
    }
  ],
  "summary": "one paragraph summary"
}
"""

class QAAgent:
    def __init__(self, api_key=None, model=None):
        self.bugs = []
        self.api_key = api_key
        self.model = model

    def analyze(self, anomalies, vision_bugs):
        print(f"  [QAAgent] Consolidating {len(anomalies)} anomalies + {len(vision_bugs)} vision bugs...")
        try:
            prompt = QA_PROMPT + "\nRule-based anomalies:\n" + json.dumps(anomalies, indent=2)
            prompt += "\nVision findings:\n" + json.dumps(vision_bugs, indent=2)
            raw = generate(prompt, api_key=self.api_key, model=self.model)
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"): raw = raw[4:]
            result    = json.loads(raw.strip())
            self.bugs = result.get("bugs", [])
            print(f"  [QAAgent] Found {len(self.bugs)} unique bugs after dedup")
            for b in self.bugs:
                sev   = b.get("severity", "?")
                emoji = {"critical":"🔴","high":"🔴","medium":"🟡","low":"🟢"}.get(sev,"⚪")
                print(f"    {emoji} {b['id']}: {b['title']} (confidence: {b.get('confidence',0):.0%})")
            return result
        except Exception as e:
            print(f"  [QAAgent] Error: {e}")
            return {"bugs": [], "summary": str(e)}