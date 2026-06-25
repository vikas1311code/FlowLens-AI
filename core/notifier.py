"""
core/notifier.py
Sends a notification when a run finishes — works with Slack's "Incoming
Webhooks" out of the box, and with any other service that accepts a plain
POST of JSON (Discord, Microsoft Teams via a connector, your own endpoint).

Failure here must never break a validation run, so every call is wrapped
and just logs a warning on error.
"""
import json
import urllib.request
import urllib.error


def _post(url: str, payload: dict, timeout: int = 8) -> bool:
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, Exception) as e:
        print(f"[notifier] Could not send notification: {e}")
        return False


def build_slack_message(run: dict, dashboard_url: str | None = None) -> dict:
    """Builds a Slack-compatible payload (also readable by most other
    webhook-based chat tools, since it has a plain `text` fallback)."""
    stats = run.get("stats", {}) or {}
    url = run.get("url", "")
    status = run.get("status", "unknown")

    if status == "error":
        headline = f":x: Validation run failed for {url}"
        lines = [f"Error: {run.get('error', 'unknown error')}"]
    else:
        critical, high = stats.get("critical", 0), stats.get("high", 0)
        total = stats.get("total_bugs", 0)
        headline = (
            f":white_check_mark: Validation complete for {url} — all clear"
            if not (critical or high) else
            f":rotating_light: Validation complete for {url} — {critical} critical, {high} high"
        )
        lines = [
            f"Total bugs: {total}  ·  Critical: {critical}  ·  High: {high}",
            f"PRD coverage: {stats.get('prd_coverage', 0)}%  ·  "
            f"Accessibility issues: {stats.get('a11y_issues', 0)}  ·  "
            f"Pages crawled: {stats.get('pages_crawled', 0)}",
        ]

    if dashboard_url:
        lines.append(f"<{dashboard_url}|Open in dashboard>")

    text = headline + "\n" + "\n".join(lines)
    return {
        "text": text,
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{headline}*"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
        ],
    }


def notify_run_complete(webhook_url: str, run: dict, dashboard_url: str | None = None) -> bool:
    if not webhook_url:
        return False
    payload = build_slack_message(run, dashboard_url)
    return _post(webhook_url, payload)