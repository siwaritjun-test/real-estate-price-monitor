"""Post the latest alerts to a Slack or Discord incoming webhook.

Does nothing unless ALERT_WEBHOOK_URL is set, so the workflow can call it
unconditionally. Slack expects {"text": ...}; Discord expects {"content": ...}.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

MAX_CHARS = 3500  # keep well under both services' body limits


def main() -> int:
    url = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
    if not url:
        print("ALERT_WEBHOOK_URL not set; skipping webhook")
        return 0

    path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/latest_alerts.md")
    body = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    if not body or body == "No new alerts.":
        print("nothing to send")
        return 0

    if len(body) > MAX_CHARS:
        body = body[:MAX_CHARS] + "\n…truncated, see the dashboard for the rest."

    text = f"🏢 Condo price monitor\n\n{body}"
    field = "content" if "discord.com" in url else "text"
    payload = json.dumps({field: text}).encode("utf-8")

    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            print(f"webhook responded {response.status}")
    except Exception as exc:  # a failed notification must not fail the run
        print(f"webhook failed: {exc}", file=sys.stderr)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
