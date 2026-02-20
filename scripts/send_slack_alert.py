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

    has_regression = os.environ.get("HAS_REGRESSION", "") == "true"

    if has_regression:
        header_text = "Warning: Benchmark Regression Detected"
        header_emoji = ":warning:"
    else:
        header_text = "Benchmark: Significant Performance Change"
        header_emoji = ":chart_with_upwards_trend:"

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

    for name, bench in data.get("benchmarks", {}).items():
        fields = []
        lat = bench.get("latency", {}).get("value")
        if lat is not None:
            lat_str = f"{lat:.2f} ns" if isinstance(lat, (int, float)) else str(lat)
            fields.append(f"Latency: {lat_str}")

        tp = bench.get("throughput", {}).get("value")
        if tp is not None:
            tp_str = f"{tp:,.2f} ops/s" if isinstance(tp, (int, float)) else str(tp)
            fields.append(f"Throughput: {tp_str}")

        mem = bench.get("memory", {}).get("value")
        if mem is not None:
            mem_str = f"{mem:,.0f} bytes" if isinstance(mem, (int, float)) else str(mem)
            fields.append(f"Memory: {mem_str}")

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
                    "text": {"type": "mrkdwn", "text": f"*AI Analysis:*\n{analysis_summary}"},
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
        print(f"Slack alert sent ({header_emoji} {'regression' if has_regression else 'significant change'})")
    except urllib.error.URLError as e:
        print(f"Failed to send Slack alert: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
