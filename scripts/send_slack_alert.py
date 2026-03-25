#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""Send visual Slack alert for benchmark regression / improvement.

Renders a Block Kit message with:
  - Per-metric comparison (current → baseline, %, σ, z-score)
  - Unicode sparkline showing recent trend
  - Structured AI analysis verdict
  - Deep-link buttons to GitHub Actions run and benchmark dashboard
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

from slack_chart import (
    build_dashboard_url,
    format_metric_value,
    load_history_from_dashboard,
    render_sparkline,
)

_CHANGE_TYPE_HEADERS: dict[str, tuple[str, str]] = {
    "regression": ("⚠️  Benchmark Regression Detected", ":warning:"),
    "improvement": ("✅  Benchmark Improvement Detected", ":chart_with_upwards_trend:"),
    "mixed": ("📊  Benchmark: Mixed Performance Changes", ":bar_chart:"),
}

_DEFAULT_HEADER = ("❌  Benchmark Run Failed", ":x:")

_METRIC_LABELS = {
    "latency": "Latency",
    "throughput": "Throughput",
    "memory": "Memory",
}

_MAX_BENCHMARKS = 5  # Block Kit 50-block limit safeguard


def _build_metric_block(
    name: str,
    metrics: dict,
    dashboard_token: str,
    dashboard_repo: str,
    source_repo: str,
    device: str,
) -> list[dict]:
    """Build Slack blocks for one benchmark's metric changes."""
    blocks: list[dict] = []

    # Pick the "worst" metric for the header indicator
    has_regression = any(m["direction"] == "regression" for m in metrics.values())
    indicator = "🔴" if has_regression else "🟢"
    dir_label = "Regression" if has_regression else "Improvement"

    lines = [f"*{indicator} {name}* — {dir_label}"]

    for key, detail in metrics.items():
        label = _METRIC_LABELS.get(key, key)
        unit = detail.get("unit", "")
        current_fmt = format_metric_value(detail["current"], unit)
        baseline_fmt = format_metric_value(detail["baseline_mean"], unit)
        stdev_fmt = format_metric_value(detail["baseline_stdev"], unit)
        pct = detail["change_pct"]
        z = detail["zscore"]

        lines.append(f"`{label}:  {baseline_fmt}  →  {current_fmt}  ({pct:+.1f}%)`")
        lines.append(f"`Baseline: {baseline_fmt}  (σ = {stdev_fmt}, z = {z:.1f})`")

    # Sparkline from dashboard history
    if dashboard_token and dashboard_repo:
        # Use the first metric key for the sparkline
        first_metric = next(iter(metrics))
        _commits, values = load_history_from_dashboard(
            dashboard_token, dashboard_repo, source_repo, name, device,
            metric=first_metric, limit=15,
        )
        if values:
            spark = render_sparkline(values)
            lines.append(f"`Trend:    {spark}  (last {len(values)} runs)`")

    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "\n".join(lines)},
    })

    return blocks


def _build_ai_analysis_block(ai_analysis_file: Path) -> list[dict]:
    """Build Slack blocks for AI analysis section."""
    if not ai_analysis_file.exists():
        return []

    text = ai_analysis_file.read_text().strip()
    lines = text.split("\n")

    # Extract the Analysis section
    analysis_lines: list[str] = []
    in_analysis = False
    for line in lines:
        if line.startswith("### Analysis"):
            in_analysis = True
            continue
        if in_analysis and line.startswith("##"):
            break
        if in_analysis and line.strip():
            analysis_lines.append(line)

    if not analysis_lines:
        return []

    # Convert markdown **bold** to Slack mrkdwn *bold*
    analysis_lines = [line.replace("**", "*") for line in analysis_lines]
    analysis_text = "\n".join(analysis_lines[:5])
    return [
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"🤖 *AI Analysis*\n{analysis_text}",
            },
        },
    ]


def main() -> int:
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("SLACK_WEBHOOK_URL not set, skipping")
        return 0

    if not webhook_url.startswith("https://hooks.slack.com/"):
        print("Invalid Slack webhook URL")
        return 1

    results_file = os.environ.get("RESULTS_FILE", "benchmark_results.json")
    details_file = os.environ.get("REGRESSION_DETAILS_FILE", "regression_details.json")
    source_repo = os.environ.get("SOURCE_REPO", "unknown")
    device = os.environ.get("DEVICE", "unknown")
    change_type = os.environ.get("CHANGE_TYPE", "")
    dashboard_token = os.environ.get("DASHBOARD_TOKEN", "")
    dashboard_repo = os.environ.get("DASHBOARD_REPO", "fractalyze/benchmark-dashboard")
    ai_analysis_file = Path(os.environ.get("AI_ANALYSIS_OUTPUT", "ai_analysis.md"))

    server_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_url = f"{server_url}/{repository}/actions/runs/{run_id}"

    # Read commit + PR info from results or env
    try:
        with open(results_file) as f:
            data = json.load(f)
        commit = data["metadata"]["commit_sha"][:7]
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
        commit = os.environ.get("GITHUB_SHA", "unknown")[:7]

    # PR link (available when triggered by pull_request event)
    pr_number = os.environ.get("PR_NUMBER", "")
    if pr_number:
        pr_url = f"{server_url}/{repository}/pull/{pr_number}"
        ref_field = {"type": "mrkdwn", "text": f"*PR:*\n<{pr_url}|#{pr_number}>"}
    else:
        commit_url = f"{server_url}/{repository}/commit/{commit}"
        ref_field = {"type": "mrkdwn", "text": f"*Commit:*\n<{commit_url}|`{commit}`>"}

    # --- Build Block Kit payload ---
    header_text, _emoji = _CHANGE_TYPE_HEADERS.get(change_type, _DEFAULT_HEADER)

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_text, "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Repo:*\n{source_repo}"},
                {"type": "mrkdwn", "text": f"*Device:*\n{device.upper()}"},
                ref_field,
            ],
        },
        {"type": "divider"},
    ]

    # Per-benchmark metric blocks (sorted by max |z-score|, limited)
    details: dict = {}
    details_path = Path(details_file)
    if details_path.exists():
        with open(details_path) as f:
            details = json.load(f)

    benchmarks = details.get("benchmarks", {})
    # Sort by maximum absolute z-score (most significant first)
    sorted_benchmarks = sorted(
        benchmarks.items(),
        key=lambda item: max(abs(m.get("zscore", 0)) for m in item[1].values()),
        reverse=True,
    )

    for name, metrics in sorted_benchmarks[:_MAX_BENCHMARKS]:
        blocks.extend(_build_metric_block(
            name, metrics, dashboard_token, dashboard_repo, source_repo, device,
        ))

    if len(sorted_benchmarks) > _MAX_BENCHMARKS:
        remaining = len(sorted_benchmarks) - _MAX_BENCHMARKS
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"_+{remaining} more benchmarks with changes_"},
            ],
        })

    # AI analysis
    blocks.extend(_build_ai_analysis_block(ai_analysis_file))

    # Action buttons
    action_elements: list[dict] = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "View Run"},
            "url": run_url,
        },
    ]

    # Dashboard deep link (to first benchmark with changes)
    if sorted_benchmarks:
        first_name = sorted_benchmarks[0][0]
        dash_url = build_dashboard_url(source_repo, device, first_name)
        action_elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "View Dashboard"},
            "url": dash_url,
        })

    blocks.append({"type": "actions", "elements": action_elements})

    # --- Send ---
    payload = {"blocks": blocks}
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )

    try:
        urllib.request.urlopen(req)
        print(f"Slack alert sent ({change_type or 'failure'})")
    except urllib.error.URLError as e:
        print(f"Failed to send Slack alert: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
