"""
core/gemini_client.py
Single shared Gemini client using new google.genai SDK.
Handles: auth, retry on 429, rate limiting.

Both the API key and model are resolvable per-call: the dashboard can let a
user supply their own key/model for a single run (passed down through
pipeline -> agents -> here) without ever touching the server's .env or
mutating any shared/global state. If a caller doesn't pass either, this
falls back to GEMINI_API_KEY / GEMINI_MODEL from the environment, same as
before.
"""
import os
import time
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Models we know are valid, multimodal (text+vision) targets for this app's
# agents. Kept as a simple allow-list so a stray/typo'd model string from a
# request body can't be used to probe arbitrary API surface — and so the
# dashboard's dropdown has a single source of truth to mirror.
SUPPORTED_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-3.1-flash",
    "gemini-3.1-pro",
    "gemini-3.5-flash",
]

# One client per distinct API key actually used, so a per-run override
# doesn't force-recreate (or leak into) the default server-wide client.
_clients: dict = {}

def get_client(api_key: str | None = None):
    key = (api_key or os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        raise Exception("No Gemini API key configured (set GEMINI_API_KEY in .env, "
                         "or supply one from the dashboard).")
    if key not in _clients:
        _clients[key] = genai.Client(api_key=key)
    return _clients[key]

def generate(prompt, image_bytes=None, max_retries=5, api_key=None, model=None):
    """
    Single entry point for all Gemini calls.
    Handles 429 retry with exponential backoff.

    api_key / model: optional per-call overrides (e.g. supplied by the
    dashboard for a single run). Falls back to GEMINI_API_KEY / GEMINI_MODEL
    env vars when not given.
    """
    client = get_client(api_key)
    model  = model or DEFAULT_MODEL
    if model not in SUPPORTED_MODELS:
        raise Exception(f"Unsupported Gemini model '{model}'. "
                         f"Choose one of: {', '.join(SUPPORTED_MODELS)}")

    contents = []
    if image_bytes:
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type="image/png"))
    contents.append(prompt)

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
            )
            return response.text
        except Exception as e:
            err = str(e)
            if ("429" in err or "quota" in err.lower() or "503" in err or "unavailable" in err.lower()) and attempt < max_retries - 1:
                wait = 60 * (attempt + 1)
                print(f"  [Gemini] Rate limit hit. Waiting {wait}s (attempt {attempt+1}/{max_retries})...")
                time.sleep(wait)
            elif "403" in err:
                raise Exception(f"API key invalid or project blocked: {err}")
            else:
                raise
    raise Exception("Max retries exceeded")