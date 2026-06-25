"""
agents/vision_agent.py - migrated to google.genai
"""
import json
from pathlib import Path
from core.gemini_client import generate

VISION_PROMPT = """
You are a senior QA engineer and UX expert analyzing a screenshot of a web page.
Respond with ONLY valid JSON (no markdown, no backticks):
{
  "page_description": "one sentence describing what this page is",
  "page_type": "homepage | product | checkout | form | error | blank | other",
  "visible_elements": ["list of key UI elements you can see"],
  "potential_bugs": [
    {
      "type": "bug type",
      "severity": "high | medium | low",
      "description": "clear description of the issue"
    }
  ],
  "ux_issues": ["list of UX problems even if not bugs"],
  "overall_health": "good | warning | critical",
  "summary": "2-3 sentence overall assessment for a developer"
}
Be specific. If the page looks blank or broken, say so clearly.
"""

class VisionAgent:
    def __init__(self, api_key=None, model=None):
        self.analyses = []
        self.api_key = api_key
        self.model = model

    def analyze_screenshot(self, screenshot_path, step, url):
        print(f"  [VisionAgent] Analyzing step {step} — {url}")
        try:
            img_bytes = Path(screenshot_path).read_bytes()
            raw = generate(VISION_PROMPT, image_bytes=img_bytes, api_key=self.api_key, model=self.model)
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"): raw = raw[4:]
            raw = raw.strip()
            analysis = json.loads(raw)
            analysis["step"] = step
            analysis["url"]  = url
            health = analysis.get("overall_health", "?")
            emoji  = {"good": "✅", "warning": "⚠️", "critical": "🔴"}.get(health, "❓")
            print(f"  {emoji} Health: {health.upper()} — {str(analysis.get('page_description', ''))[:60]}")
            for b in analysis.get("potential_bugs", []):
                sev_emoji = {"high":"🔴","medium":"🟡","low":"🟢"}.get(b.get("severity",""),"⚪")
                print(f"     {sev_emoji} [{b.get('severity','?').upper()}] {str(b.get('description',''))[:70]}")
            self.analyses.append(analysis)
            return analysis
        except Exception as e:
            print(f"  [VisionAgent] Error: {e}")
            fallback = {"step": step, "url": url, "page_description": "Analysis failed",
                       "overall_health": "warning", "potential_bugs": [], "ux_issues": [], "error": str(e)}
            self.analyses.append(fallback)
            return fallback

    def get_all_bugs(self):
        bugs = []
        for a in self.analyses:
            for b in a.get("potential_bugs", []):
                bugs.append({**b, "step": a["step"], "url": a["url"], "source": "vision_agent"})
        return bugs

    def get_summary(self):
        all_bugs = self.get_all_bugs()
        return {
            "pages_analyzed": len(self.analyses),
            "critical_pages": sum(1 for a in self.analyses if a.get("overall_health") == "critical"),
            "warning_pages":  sum(1 for a in self.analyses if a.get("overall_health") == "warning"),
            "good_pages":     sum(1 for a in self.analyses if a.get("overall_health") == "good"),
            "total_bugs":     len(all_bugs),
            "high_bugs":      len([b for b in all_bugs if b.get("severity") == "high"]),
        }