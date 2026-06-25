"""
agents/prd_parser.py - Fixed PRD coverage matching
"""
import json
from urllib.parse import urlparse
from core.gemini_client import generate

PRD_PROMPT = """
You are a senior product manager. Read the PRD below and extract structured requirements.
Respond with ONLY valid JSON (no markdown, no backticks):
{
  "product_name": "name of the product",
  "product_description": "one sentence summary",
  "user_stories": [
    {
      "id": "US-001",
      "as_a": "type of user",
      "i_want": "what they want to do",
      "so_that": "the value / outcome",
      "acceptance_criteria": ["list of specific testable criteria"]
    }
  ],
  "required_pages": [
    {
      "name": "page name",
      "path": "/url-path",
      "must_have_elements": ["list of UI elements that must exist"]
    }
  ],
  "success_metrics": ["list of measurable success criteria"],
  "out_of_scope": ["things explicitly not in scope"]
}

PRD:
"""

class PRDParser:
    def __init__(self, api_key=None, model=None):
        self.requirements = None
        self.api_key = api_key
        self.model = model

    def parse(self, prd_text):
        print(f"  [PRDParser] Parsing PRD ({len(prd_text)} chars)...")
        try:
            raw = generate(PRD_PROMPT + prd_text, api_key=self.api_key, model=self.model)
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()
            self.requirements = json.loads(raw)
            stories = len(self.requirements.get("user_stories", []))
            pages   = len(self.requirements.get("required_pages", []))
            print(f"  [PRDParser] Found {stories} user stories, {pages} required pages")
            return self.requirements
        except Exception as e:
            print(f"  [PRDParser] Error: {e}")
            self.requirements = {"error": str(e), "required_pages": [], "user_stories": []}
            return self.requirements

    def parse_file(self, prd_path):
        return self.parse(open(prd_path).read())

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Normalize a path for comparison: lowercase, strip trailing slash, strip query/fragment."""
        if not path:
            return "/"
        # if it's a full URL, extract just the path
        if path.startswith("http"):
            path = urlparse(path).path
        path = path.split("?")[0].split("#")[0]
        path = path.rstrip("/").lower()
        return path if path else "/"

    def check_coverage(self, visited_urls, page_analyses):
        if not self.requirements or "error" in self.requirements:
            return {"error": "No PRD parsed", "coverage_pct": 0,
                    "covered_pages": [], "uncovered_pages": [], "pages_tested": len(visited_urls)}

        required_pages = self.requirements.get("required_pages", [])
        if not required_pages:
            return {"coverage_pct": 0, "covered_pages": [], "uncovered_pages": [],
                    "pages_tested": len(visited_urls), "total_stories": len(self.requirements.get("user_stories", []))}

        # normalize all visited URLs to paths once
        visited_paths = set()
        for url in visited_urls:
            visited_paths.add(self._normalize_path(url))

        print(f"  [PRDParser] Visited paths: {sorted(visited_paths)}")

        covered_pages   = []
        uncovered_pages = []

        for page in required_pages:
            required_path = self._normalize_path(page.get("path", ""))
            found = required_path in visited_paths

            # also try a loose substring match as fallback
            if not found:
                for vp in visited_paths:
                    if required_path != "/" and (required_path in vp or vp in required_path):
                        found = True
                        break

            if found:
                covered_pages.append(page["name"])
            else:
                uncovered_pages.append({"name": page["name"], "path": page.get("path", "")})

        total   = len(required_pages)
        covered = len(covered_pages)
        pct     = round((covered / total * 100) if total > 0 else 0, 1)

        print(f"  [PRDParser] Coverage: {covered}/{total} pages ({pct}%)")
        for p in covered_pages:
            print(f"    [OK] Tested: {p}")
        for p in uncovered_pages:
            print(f"    [MISS] Not tested: {p['name']} ({p['path']})")

        return {
            "coverage_pct":    pct,
            "covered_pages":   covered_pages,
            "uncovered_pages": uncovered_pages,
            "total_stories":   len(self.requirements.get("user_stories", [])),
            "pages_tested":    len(visited_urls),
        }