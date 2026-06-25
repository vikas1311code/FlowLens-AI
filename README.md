# FlowLens-AI

**An autonomous QA agent that crawls your product like a real user, finds
real bugs, and tells you which ones actually matter.**

Point it at a URL (and optionally a PRD). A crew of AI agents takes it
from there: crawls the site click-by-click, screenshots and visually
analyzes every page it lands on, runs an accessibility + performance audit,
flags anomalies, debates which ones are real bugs versus noise, scores
business impact, records a repro video for the important ones, and writes
a ready-to-run Playwright test — all visible live from one dashboard.

[![Python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/orchestration-LangGraph-1C3C3C)](https://www.langchain.com/langgraph)
[![Playwright](https://img.shields.io/badge/browser-Playwright-2EAD33)](https://playwright.dev/)
[![Gemini](https://img.shields.io/badge/vision-Gemini-8E75B2)](https://ai.google.dev/)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

---

## How it works

```
 Crawl ──► Vision ──► PRD Coverage ──► QA Review ──► PM Review ──► Debate
   │          │                                                       │
   │          └─ Gemini Vision looks at every screenshot               │
   │             and flags UX issues a script-only crawler can't see   │
   ▼                                                                  ▼
Anomaly detection (JS errors, slow loads, frozen/blank pages)   Impact Score
                                                                       │
                                                          ┌────────────┴────────────┐
                                                          ▼                         ▼
                                                   Repro Video (high-sev)   Playwright Test
```

| Stage | File | What it does |
|---|---|---|
| **Crawl** | `core/browser.py` | A real Chromium session clicks every link/button it finds, depth-first, staying on the target domain. |
| **Vision** | `agents/vision_agent.py` | Gemini looks at each screenshot and writes a short page-health assessment plus any visual bugs a script can't see. |
| **PRD Coverage** | `agents/prd_parser.py` | If you give it a PRD, it extracts required pages/user stories and checks how many were actually visited. |
| **QA Agent** | `agents/qa_agent.py` | Consolidates every rule-based anomaly + vision flag into one clean bug list. |
| **PM Agent** | `agents/pm_agent.py` | Classifies each bug against the PRD (`PRD_VIOLATION` / `NICE_TO_FIX` / `OUT_OF_SCOPE`) and assigns priority. |
| **Debate Agent** | `agents/debate_agent.py` | Where QA and PM disagree, this agent reads both sides and settles the final severity + fix recommendation. |
| **Impact Scorer** | `agents/impact_scorer.py` | Turns severity + funnel position + PRD violation into a 0–100 business-impact score. |
| **Video Recorder / Test Generator** | `agents/video_recorder.py`, `agents/test_generator.py` | For bugs that matter, automatically records a repro clip and writes a Playwright test. |

The dashboard (`dashboard/index.html`) drives all of this through the
FastAPI backend (`api/server.py`) and streams live progress as each stage
finishes — you watch bugs show up in real time, not after a 10-minute wait.

## Why this exists

Most QA automation needs you to already know what to test. This doesn't —
it explores the way a real, slightly impatient user would, notices what
breaks visually (not just what throws an exception), and uses two separate
LLM passes (QA, then PM) plus a tie-breaking debate pass so a single
model's hallucinated "bug" doesn't make it into your report unchallenged.

## Features

- **Bring your own Gemini key/model** — the dashboard's API Key panel lets
  you supply your own `GEMINI_API_KEY` and pick a model (`gemini-2.5-flash`,
  `gemini-2.5-pro`, `gemini-3.1-flash`, `gemini-3.1-pro`, `gemini-3.5-flash`,
  etc.) per run, stored only in your browser. Leave it blank to use the
  server's own key from `.env`. Useful for working around per-key rate
  limits, or for letting teammates run validations against your server
  without sharing credentials.
- **Login support** — give a run a login URL + credentials and the
  crawler logs in before it starts. The password is never logged,
  persisted, or echoed back to the dashboard.
- **Security gate for `/run`** — set `DASHBOARD_API_KEY` in `.env` and
  every request must include a matching `X-API-Key` header. Do this
  *before* exposing the dashboard publicly.
- **SSRF guard** — set `BLOCK_PRIVATE_TARGETS=true` to refuse any target
  (or login URL) that resolves to a private/loopback/link-local address.
  Off by default since testing `http://localhost:...` is the normal case
  locally; turn it on once this is reachable from the internet.
- **Live, incremental results** — the pipeline streams node-by-node, so
  screenshots and bugs appear as each stage finishes.
- **Accessibility scanning** — every crawled page gets a full axe-core
  audit, grouped by impact (critical/serious/moderate/minor) in its own tab.
- **Performance (Core Web Vitals)** — real LCP / CLS / FCP / TTFB per page,
  rated against Google's own good/needs-improvement/poor thresholds.
- **Responsive / multi-viewport check** — key pages are re-screenshotted
  at tablet and mobile sizes and re-analyzed, catching layout breakage a
  desktop-only crawl would miss.
- **Run history + trends** — every run persists to SQLite, so history
  survives restarts. The Bugs tab compares the current run to the
  previous run on the same URL; the Trends view charts bug count, PRD
  coverage, and a11y issues over time.
- **CI/CD mode** — `ci_run.py` runs the whole pipeline with no server and
  no browser session left open, exiting non-zero if a bug at or above a
  severity you choose is found — gate a deploy on it. See
  `.github/workflows/validate.yml` for a ready GitHub Actions job.
- **Notifications** — set `NOTIFY_WEBHOOK_URL` to a Slack incoming webhook
  (or anything that accepts a JSON POST) for a message whenever a run
  finishes or errors, from the dashboard or from CI.
- **True parallelism, with cancellation** — each validation runs in its
  own OS process, not a background task sharing the API server's event
  loop, so `MAX_CONCURRENT_RUNS` actually means something, and any run can
  be cleanly killed mid-flight from the dashboard.

## Setup

```bash
git clone https://github.com/<your-username>/FlowLens-AI.git
cd FlowLens-AI
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt --break-system-packages
playwright install chromium
cp .env.example .env        # then put your GEMINI_API_KEY in .env
```

> Get a free Gemini API key at [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey).
> Re-create the venv fresh on each machine rather than copying one over —
> zip/unzip or copying across OSes breaks the symlinks and executable bits
> Python venvs and Playwright's bundled binaries rely on.

## Running it

```bash
./start.sh
```

This starts a single process on **http://localhost:8000** serving both the
API and the dashboard — open that URL in your browser.

> **Just changed `.env`?** Stop the server (`Ctrl+C`) and run `./start.sh`
> again. `--reload` only watches `.py` files — it will not pick up a new
> API key or any other `.env` change without a full restart.

## Exposing it with ngrok

With the server already running, in a second terminal:

```bash
ngrok http 8000
```

ngrok prints a forwarding URL like `https://abcd1234.ngrok-free.app` — open
that instead of localhost, from anywhere. The dashboard detects its own
origin automatically, no config changes needed on either end.

First time using ngrok:
1. Sign up free at [ngrok.com](https://ngrok.com) and grab your authtoken.
2. `ngrok config add-authtoken <your-token>` (one-time).
3. `ngrok http 8000` whenever you want a public URL.

**Set `DASHBOARD_API_KEY` in `.env` before doing this** — without it,
anyone with the ngrok link can make your machine launch a real browser
against any site they choose.

## Deploying to Render

This repo includes a `render.yaml` Blueprint, so deploying is mostly
point-and-click:

1. Push this repo to GitHub (see below).
2. On [render.com](https://render.com), **New → Blueprint**, point it at
   your fork/repo. Render reads `render.yaml` and provisions the service
   from the existing `Dockerfile` (which already bundles Chromium).
3. In the service's **Environment** tab, set the secrets `render.yaml`
   deliberately leaves blank: `GEMINI_API_KEY` and `DASHBOARD_API_KEY`.
   **Set both before your first deploy finishes** — without
   `DASHBOARD_API_KEY`, your public Render URL has no authentication at all.
4. Deploy. Render gives you a `https://flowlens-ai.onrender.com`-style URL.

Two things worth knowing before you rely on it:

- **`render.yaml` is set to the Free plan by default**, so SQLite history
  and `outputs/` (screenshots, videos, reports) are wiped on every redeploy
  and most restarts — Render's free-tier web services don't support
  attached disks. The app still works fine, it just won't remember past
  runs. To keep history across restarts, change `plan: free` to
  `plan: starter` (or upgrade in the dashboard) and add back a `disk:`
  block — the commented-out template for it is right there in
  `render.yaml`.
- **Free-tier services sleep.** No traffic for ~15 minutes → the next
  request takes 30-60s to wake it back up. Fine for a personal tool or a
  demo link, not for something you're hitting constantly.

Prefer to wire it up manually instead of the Blueprint? Same idea: new Web
Service → connect the repo → Render auto-detects the `Dockerfile` → set
the same env vars from `.env.example` in the dashboard → deploy.

## Running it in CI/CD

No server needed — `ci_run.py` runs the whole pipeline from the command
line and exits non-zero if it finds a bug at or above the severity you pick:

```bash
# Always exits 0, just prints a summary
python3 ci_run.py https://staging.myapp.com

# Fail the build if any critical bug is found
python3 ci_run.py https://staging.myapp.com --fail-on critical --output report.md
```

`.github/workflows/validate.yml` is ready to use — copy it in, add a
`GEMINI_API_KEY` repo secret, point `STAGING_URL` at whatever you want
gated. `python3 ci_run.py --help` lists every flag (login support,
video/test generation, custom Gemini model, etc. are all available here too).

## Notifications

Set `NOTIFY_WEBHOOK_URL` in `.env` to a Slack "Incoming Webhook" URL (or
any endpoint that accepts a JSON POST) and every run — dashboard or CI —
posts a summary there on finish or error. `PUBLIC_DASHBOARD_URL` (your
ngrok or Render URL) gets included as a clickable link if set.

## Running it with Docker

Sidesteps the whole venv/Playwright setup dance — Chromium is already in
the base image:

```bash
cp .env.example .env   # fill in GEMINI_API_KEY at minimum
docker compose up --build
```

Dashboard is at **http://localhost:8000**, same as the non-Docker setup.
`outputs/` is mounted as a volume, so run history survives rebuilds.

Without compose:
```bash
docker build -t flowlens-ai .
docker run -p 8000:8000 -v $(pwd)/outputs:/app/outputs --env-file .env flowlens-ai
```

## Running the test suite

```bash
pip install -r requirements-dev.txt --break-system-packages
pytest
```

Unit tests for everything that doesn't need a real browser: SQLite
persistence, path-traversal/SSRF guards, accessibility and performance
scoring, the regression matcher, PRD path normalization, and notification
formatting. They won't catch everything (nothing here drives an actual
crawl), but they catch a regression in that logic immediately instead of
you finding out mid-run.

## Cleaning up old screenshots/videos

These are the only things in `outputs/` that grow without bound.
`cleanup.py` deletes the old ones while leaving run records in SQLite
alone, so Trends/regression history keeps working after the heavy files
are gone:

```bash
python3 cleanup.py --older-than 30              # preview only, deletes nothing
python3 cleanup.py --older-than 30 --apply      # actually delete
python3 cleanup.py --keep-latest 20 --apply     # always keep the 20 most recent runs' files
```

## Project layout

```
api/server.py           FastAPI backend — REST API, spawns workers, serves the dashboard
worker_run.py           Subprocess entry point — runs one validation, writes progress to SQLite
core/pipeline.py        Crawl/vision/QA/PM/debate/... orchestration logic
core/gemini_client.py   Shared Gemini client — handles auth, retries, per-run key/model overrides
ci_run.py               Command-line / CI runner — no server needed, exits non-zero on severe bugs
cleanup.py              Deletes old screenshots/videos, keeps run history in SQLite
graph/__init__.py       LangGraph pipeline: crawl → responsive → PRD → QA → PM → debate
agents/                 One file per agent (vision, qa, pm, debate, impact, video, tests, prd)
core/                   Browser automation, accessibility, performance, SQLite, notifications, Gemini client
dashboard/index.html    The UI — single self-contained file, no build step
tests/                  pytest unit tests for the non-browser-dependent logic
.github/workflows/      Ready-to-use GitHub Actions job for gating a deploy on validation results
Dockerfile, docker-compose.yml, render.yaml   Containerized setup + Render deploy blueprint
outputs/                Generated screenshots, videos, tests, reports, and the SQLite run history (gitignored)
```

## Security notes for a public deployment

- **Never commit `.env`.** It's gitignored already — keep it that way.
  `.env.example` shows the shape with no real values.
- Set `DASHBOARD_API_KEY` to a long random string (not a personal
  password) before exposing this past localhost — generate one with
  `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
- Turn on `BLOCK_PRIVATE_TARGETS=true` once this is reachable from the
  open internet, so it can't be tricked into crawling your own internal
  network.
- A per-run Gemini key entered in the dashboard's API Key panel is stored
  in that browser's `localStorage` only — it's sent with that run's
  request and never written to this server's `.env` or database.

## License

MIT — see [LICENSE](LICENSE).