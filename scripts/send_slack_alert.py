#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""Send Slack alert for benchmark regression or significant improvement."""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path


_METRICS_TO_REPORT = [
    ("Latency", "latency", "{:.2f} ns"),
    ("Throughput", "throughput", "{:,.2f} ops/s"),
    ("Memory", "memory", "{:,.0f} bytes"),
]

_CHANGE_TYPE_HEADERS = {
    "regression": ("Warning: Benchmark Regression Detected", ":warning:"),
    "improvement": ("Benchmark Improvement Detected", ":chart_with_upwards_trend:"),
    "mixed": ("Benchmark: Mixed Performance Changes", ":bar_chart:"),
}

_DEFAULT_HEADER = ("Benchmark Run Failed", ":x:")


def main() -> int:
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("SLACK_WEBHOOK_URL not set, skipping")
        return 0

    results_file = os.environ.get("RESULTS_FILE", "benchmark_results.json")
    try:
        with open(results_file) as f:
            data = json.load(f)
        commit = data["metadata"]["commit_sha"]
        impl = data["metadata"]["implementation"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        data = None
        commit = os.environ.get("GITHUB_SHA", "unknown")[:7]
        impl = os.environ.get("IMPLEMENTATION", "unknown")

    server_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_url = f"{server_url}/{repository}/actions/runs/{run_id}"

    change_type = os.environ.get("CHANGE_TYPE", "")
    header_text, header_emoji = _CHANGE_TYPE_HEADERS.get(change_type, _DEFAULT_HEADER)

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_text, "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Implementation:*\n{impl}"},
                {"type": "mrkdwn", "text": f"*Commit:*\n`{commit}`"},
            ],
        },
    ]

    if data:
        for name, bench in data.get("benchmarks", {}).items():
            fields = []
            for label, key, fmt in _METRICS_TO_REPORT:
                val = bench.get(key, {}).get("value")
                if val is not None:
                    val_str = fmt.format(val) if isinstance(val, (int, float)) else str(val)
                    fields.append(f"{label}: {val_str}")

            summary = " | ".join(fields) if fields else "N/A"
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*{name}*: {summary}"}}
            )

        # Include AI analysis if available
        ai_analysis_file = Path(os.environ.get("AI_ANALYSIS_OUTPUT", "ai_analysis.md"))
        if ai_analysis_file.exists():
            analysis_text = ai_analysis_file.read_text().strip()
            # Extract just the analysis section (skip markdown headers for Slack)
            lines = analysis_text.split("\n")
            analysis_lines = []
            in_analysis = False
            for line in lines:
                if line.startswith("### Analysis"):
                    in_analysis = True
                    continue
                if in_analysis and line.startswith("##"):
                    break
                if in_analysis and line.strip():
                    analysis_lines.append(line)

            if analysis_lines:
                analysis_summary = "\n".join(analysis_lines[:5])  # Limit to 5 lines
                blocks.append(
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*AI Analysis:*\n{analysis_summary}",
                        },
                    }
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
        print(f"Slack alert sent ({header_emoji} {change_type or 'failure'})")
    except urllib.error.URLError as e:
        print(f"Failed to send Slack alert: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
