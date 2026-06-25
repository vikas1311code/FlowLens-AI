"""
agents/test_generator.py - migrated to google.genai
"""
import json
from pathlib import Path
from core.gemini_client import generate

TESTS_DIR = Path(__file__).resolve().parent.parent / "outputs" / "tests"
TESTS_DIR.mkdir(parents=True, exist_ok=True)

CODEGEN_PROMPT = """
You are a senior QA automation engineer.
Write a Playwright TypeScript test for this bug.
Rules:
- Use @playwright/test imports
- Use async/await  
- Test FAILS when bug exists (proving the bug)
- Clean readable production-quality code
- Add comments explaining the bug

Respond with ONLY TypeScript code (no markdown, no backticks):
"""

class TestGenerator:
    def __init__(self, base_url, api_key=None, model=None):
        self.base_url   = base_url
        self.test_files = []
        self.api_key = api_key
        self.model = model

    def generate_for_bug(self, bug):
        bug_id = bug.get("id", "unknown")
        print(f"  [TestGenerator] Generating test for {bug_id}: {str(bug.get('title',''))[:50]}")
        try:
            prompt = CODEGEN_PROMPT + f"\nBase URL: {self.base_url}\nBug:\n" + json.dumps(bug, indent=2)
            code   = generate(prompt, api_key=self.api_key, model=self.model)
            if code.startswith("```"):
                code = code.split("```")[1]
                if code.startswith(("typescript","ts")): code = code.split("\n",1)[1]
            code  = code.strip()
            fname = f"{bug_id.lower().replace('-','_')}.spec.ts"
            fpath = TESTS_DIR / fname
            fpath.write_text(code)
            self.test_files.append({"bug_id": bug_id, "file": str(fpath), "filename": fname})
            print(f"    ✅ {fname} ({len(code.splitlines())} lines)")
            return str(fpath)
        except Exception as e:
            print(f"    [TestGenerator] Error: {e}")
            return None

    def generate_all(self, validated_bugs):
        print(f"  [TestGenerator] Generating {len(validated_bugs)} test files...")
        for bug in validated_bugs:
            self.generate_for_bug(bug)
        print(f"  [TestGenerator] {len(self.test_files)} test files created")
        return self.test_files