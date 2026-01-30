#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""Send Slack alert for benchmark regression."""
from __future__ import annotations

import json
import os
import sys
import urllib.request


def main() -> int:
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("SLACK_WEBHOOK_URL not set, skipping")
        return 0

    results_file = os.environ.get("RESULTS_FILE", "benchmark_results.json")
    with open(results_file) as f:
        data = json.load(f)

    commit = data["metadata"]["commit_sha"]
    impl = data["metadata"]["implementation"]

    server_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_url = f"{server_url}/{repository}/actions/runs/{run_id}"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Warning: Benchmark Regression Detected"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Implementation:*\n{impl}"},
                {"type": "mrkdwn", "text": f"*Commit:*\n`{commit}`"},
            ],
        },
    ]

    for name, bench in data.get("benchmarks", {}).items():
        lat = bench.get("latency", {}).get("value", "N/A")
        lat_str = f"{lat:.2f} ns" if isinstance(lat, (int, float)) else str(lat)
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{name}*: {lat_str}"}}
        )

    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View Run"},
                    "url": run_url,
                }
            ],
        }
    )

    payload = {"blocks": blocks}
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )

    try:
        urllib.request.urlopen(req)
        print("Slack alert sent")
    except urllib.error.URLError as e:
        print(f"Failed to send Slack alert: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
