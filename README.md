# ProductValidation OS

An autonomous QA agent. Point it at a URL (and optionally a PRD), and a crew
of AI agents crawls the site like a real user, screenshots and analyzes
every page it lands on, flags anomalies, debates which ones actually
matter, scores their business impact, records repro videos for the
important ones, and generates ready-to-run Playwright tests — all from a
single dashboard.

## How it works

```
 Crawl ──► Vision ──► PRD Coverage ──► QA Review ──► PM Review ──► Debate
   │          │                                                       │
   │          └─ Gemini Vision looks at every screenshot              │
   │             and flags UX issues a script-only crawler can't see  │
   ▼                                                                  ▼
Anomaly detection (JS errors, slow loads, frozen/blank pages)   Impact Score
                                                                       │
                                                          ┌────────────┴────────────┐
                                                          ▼                         ▼
                                                   Repro Video (high-sev)   Playwright Test
```

- **Crawl** (`core/browser.py`) — a real Chromium session clicks every link
  and button it finds, depth-first, staying on the target domain.
- **Vision** (`agents/vision_agent.py`) — Gemini looks at each screenshot
  and writes a short page health assessment + any visual bugs.
- **PRD Coverage** (`agents/prd_parser.py`) — if you give it a PRD, it
  extracts required pages/user stories and checks how many were actually
  visited.
- **QA Agent** (`agents/qa_agent.py`) — consolidates every anomaly +
  vision flag into a clean bug list.
- **PM Agent** (`agents/pm_agent.py`) — classifies each bug against the PRD
  (`PRD_VIOLATION` / `NICE_TO_FIX` / `OUT_OF_SCOPE`) and assigns priority.
- **Debate Agent** (`agents/debate_agent.py`) — where QA and PM disagree,
  this agent reads both sides and settles the final severity + fix
  recommendation.
- **Impact Scorer** (`agents/impact_scorer.py`) — turns severity + funnel
  position + PRD violation into a 0–100 business-impact score.
- **Video Recorder** / **Test Generator** — for the bugs that matter,
  automatically records a repro clip and writes a Playwright test.

The dashboard (`dashboard/index.html`) drives all of this through the
FastAPI backend (`api/server.py`) and streams live progress over
server-sent events.

## What's new in this version

- **Login support** — if the product is behind a signup wall, give the
  run a login URL + credentials and the crawler logs in before it starts
  (`core/browser.py: BrowserSession.login()`). The password is never
  logged, persisted, or sent back to the dashboard.
- **Security gate for `/run`** — set `DASHBOARD_API_KEY` in `.env` and
  every `POST /run` must include a matching `X-API-Key` header. Do this
  before exposing the dashboard via ngrok.
- **SSRF guard** — set `BLOCK_PRIVATE_TARGETS=true` to refuse any target
  (or login URL) that resolves to a private/loopback/link-local address.
  Off by default since testing `http://localhost:...` is the normal case.
- **Live, incremental results** — the pipeline now streams node-by-node
  (`graph.stream(..., stream_mode="updates")` instead of one blocking
  `invoke()`), so screenshots and bugs show up in the dashboard as each
  stage finishes rather than only once the whole run is done.
- **Accessibility scanning** — every crawled page gets an axe-core audit
  (`core/accessibility.py`), surfaced in a dedicated **A11y** tab with
  violations grouped by impact (critical/serious/moderate/minor).
- **Run history that survives restarts** — every run is mirrored to
  SQLite (`core/db.py`, `outputs/db/runs.sqlite3`), so `/runs` and the
  sidebar history are no longer wiped out when the server restarts.
- **Run-to-run comparison & trends** — the **Bugs** tab shows a banner
  comparing the current run to the previous run on the same URL (new /
  resolved / still-open), and the sidebar's **Trends** view charts bug
  count, PRD coverage, and accessibility issues over time for any URL
  you've tested more than once.
- **Performance (Core Web Vitals)** — every page gets real LCP / CLS /
  FCP / TTFB measurements (`core/performance.py`, via Google's `web-vitals`
  library), rated good / needs-improvement / poor using Google's own
  thresholds, in a new **Performance** tab.
- **Responsive / multi-viewport check** — after the main crawl, up to 5
  visited pages are re-screenshotted at tablet (768×1024) and mobile
  (390×844) sizes and run through the vision agent again, in a new
  **Responsive** tab — catches layout breakage a desktop-only crawl
  would miss.
- **CI/CD mode** — `ci_run.py` runs a validation from the command line
  with no server needed, and exits non-zero if a bug at or above a
  severity you choose is found, so a CI pipeline can gate a deploy on it.
  See `.github/workflows/validate.yml` for a ready-to-use GitHub Actions
  job.
- **Notifications** — set `NOTIFY_WEBHOOK_URL` to a Slack incoming
  webhook (or any endpoint that takes a JSON POST) and get a message
  whenever a run finishes or errors, from both the dashboard and CI mode.
- **Runs actually execute in parallel, and can be cancelled** — each
  validation now runs in its own OS process (`worker_run.py`), not as a
  background task sharing the API server's event loop. The crawl pipeline
  is blocking under the hood (LangGraph nodes nest a blocking event loop),
  so two runs sharing one process would just serialize behind each other
  no matter what `MAX_CONCURRENT_RUNS` said. Separate processes also mean
  a run can be cleanly killed — the dashboard's run view has a **Cancel**
  button while a run is queued/in progress.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt --break-system-packages
playwright install chromium
cp .env.example .env        # then put your GEMINI_API_KEY in .env
```

> Re-create the venv fresh rather than reusing a zipped one — zip/unzip
> across OSes (e.g. via Windows) breaks the symlinks and executable bits
> Python venvs and Playwright's bundled binaries rely on.

## Running it

```bash
./start.sh
```

This starts a single process on **http://localhost:8000** that serves both
the API and the dashboard — open that URL in your browser.

## Exposing it with ngrok

Because the dashboard and API now share one port, exposing this to the
internet (for a remote demo, or testing from another device) is one
command. With the server already running from `./start.sh`, in a second
terminal:

```bash
ngrok http 8000
```

ngrok will print a forwarding URL like `https://abcd1234.ngrok-free.app` —
open that instead of localhost, from anywhere. The dashboard detects its
own origin automatically, so no config changes are needed on either end.

If you've never used ngrok before:
1. Sign up free at ngrok.com and grab your authtoken from the dashboard.
2. `ngrok config add-authtoken <your-token>` (one-time).
3. `ngrok http 8000` whenever you want a public URL for this app.

## Running it in CI/CD

No server needed for this — `ci_run.py` runs the whole pipeline from the
command line and exits non-zero if it finds a bug at or above the
severity you specify:

```bash
# Always exits 0, just prints a summary
python3 ci_run.py https://staging.myapp.com

# Fail the build if any critical bug is found
python3 ci_run.py https://staging.myapp.com --fail-on critical --output report.md
```

`.github/workflows/validate.yml` is a ready-to-use GitHub Actions job —
copy it in, add a `GEMINI_API_KEY` repo secret, and point `STAGING_URL` at
whatever you want gated. Run `python3 ci_run.py --help` for every flag
(login support, video/test generation, etc. are all available here too).

## Notifications

Set `NOTIFY_WEBHOOK_URL` in `.env` to a Slack "Incoming Webhook" URL (or
any endpoint that accepts a JSON POST) and every run — from the dashboard
or from `ci_run.py` — posts a summary there when it finishes or errors.
`PUBLIC_DASHBOARD_URL` (e.g. your ngrok URL) gets included as a link if set.

## Running it with Docker

This sidesteps the whole venv/Playwright setup dance — Chromium comes
pre-installed in the base image:

```bash
cp .env.example .env   # fill in GEMINI_API_KEY at minimum
docker compose up --build
```

Dashboard is then at **http://localhost:8000**, same as the non-Docker
setup. `outputs/` is mounted as a volume (see `docker-compose.yml`), so
your run history survives rebuilds and restarts.

Without compose:
```bash
docker build -t productvalidation-os .
docker run -p 8000:8000 -v $(pwd)/outputs:/app/outputs --env-file .env productvalidation-os
```

## Running the test suite

```bash
pip install -r requirements-dev.txt --break-system-packages
pytest
```

These are unit tests for the parts that don't need a real browser —
SQLite persistence, path-traversal/SSRF guards, accessibility and
performance scoring, the regression matcher, PRD path normalization, and
notification formatting. They won't catch everything (nothing exercises
an actual crawl), but they'll catch a regression in any of that logic
immediately instead of you finding out mid-run.

## Cleaning up old screenshots/videos

Screenshots and bug-repro videos are the only things in `outputs/` that
grow without bound. `cleanup.py` deletes the old ones while leaving the
run records themselves in SQLite alone, so Trends/regression history
keeps working even after the heavy files are gone:

```bash
python3 cleanup.py --older-than 30              # preview only, deletes nothing
python3 cleanup.py --older-than 30 --apply      # actually delete
python3 cleanup.py --keep-latest 20 --apply     # always keep the 20 most recent runs' files
```

## Project layout

```
api/server.py         FastAPI backend — REST API, spawns workers, serves the dashboard
worker_run.py          Subprocess entry point — runs one validation, writes progress to SQLite
core/pipeline.py       The actual crawl/vision/QA/PM/debate/... orchestration logic
ci_run.py              Command-line / CI runner — no server needed, exits non-zero on severe bugs
cleanup.py             Deletes old screenshots/videos, keeps run history in SQLite
graph/__init__.py      LangGraph pipeline: crawl → responsive → PRD → QA → PM → debate
agents/                One file per agent (vision, qa, pm, debate, impact, video, tests, prd)
core/                  Browser automation, accessibility, performance, SQLite, notifications, Gemini client
dashboard/index.html   The UI — single self-contained file (no build step)
tests/                 pytest unit tests for the non-browser-dependent logic
.github/workflows/     Example GitHub Actions job for gating a deploy on validation results
Dockerfile, docker-compose.yml   Containerized setup — Chromium pre-installed, no venv needed
outputs/               Generated screenshots, videos, tests, reports, and the SQLite run history
```