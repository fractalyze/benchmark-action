#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""AI-powered performance analysis using Claude."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path


def get_git_diff() -> str:
    """Get git diff of recent changes."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD~1", "--stat", "--", "*.py", "*.rs", "*.cpp", "*.c", "*.h"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        stat = result.stdout.strip()

        result = subprocess.run(
            ["git", "diff", "HEAD~1", "--", "*.py", "*.rs", "*.cpp", "*.c", "*.h"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        diff = result.stdout.strip()

        # Limit diff size
        if len(diff) > 8000:
            diff = diff[:8000] + "\n... (truncated)"

        return f"Diff summary:\n{stat}\n\nDiff:\n{diff}"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "Git diff not available"


def detect_significant_changes(
    current: dict, baseline: dict, threshold: float
) -> list[dict]:
    """Detect benchmarks with significant performance changes."""
    changes = []

    for name, curr_bench in current.get("benchmarks", {}).items():
        if name not in baseline.get("benchmarks", {}):
            continue

        base_bench = baseline["benchmarks"][name]
        curr_lat = curr_bench.get("latency", {}).get("value", 0)
        base_lat = base_bench.get("latency", {}).get("value", 0)

        if base_lat > 0:
            change_pct = (curr_lat - base_lat) / base_lat * 100
            if abs(change_pct) > threshold * 100:
                changes.append({
                    "name": name,
                    "baseline_latency": base_lat,
                    "current_latency": curr_lat,
                    "change_percent": change_pct,
                    "is_regression": change_pct > 0,
                })

    return changes


def call_claude_api(api_key: str, model: str, prompt: str) -> str:
    """Call Claude API for analysis."""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }

    data = {
        "model": model,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode(),
        headers=headers,
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode())
            return result["content"][0]["text"]
    except urllib.error.URLError as e:
        return f"API call failed: {e}"


def main() -> int:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return 0

    model = os.environ.get("AI_MODEL", "claude-opus-4-5-20251101")
    threshold = float(os.environ.get("REGRESSION_THRESHOLD", "0.10"))
    results_file = os.environ.get("RESULTS_FILE", "benchmark_results.json")
    baseline_path = Path(os.environ.get("BASELINE_PATH", "benchmark_data/baseline.json"))
    analysis_output = os.environ.get("AI_ANALYSIS_OUTPUT", "ai_analysis.md")

    with open(results_file) as f:
        current = json.load(f)

    if not baseline_path.exists():
        return 0

    with open(baseline_path) as f:
        baseline = json.load(f)

    changes = detect_significant_changes(current, baseline, threshold)

    if not changes:
        return 0

    git_diff = get_git_diff()

    changes_text = "\n".join(
        f"- {c['name']}: {c['baseline_latency']:.2f}ns → {c['current_latency']:.2f}ns "
        f"({c['change_percent']:+.1f}%)"
        for c in changes
    )

    prompt = f"""Analyze this benchmark performance change and identify likely causes.

## Performance Changes
{changes_text}

## Recent Code Changes
{git_diff}

## Instructions
1. Identify the most likely cause of the performance change based on the code diff
2. Be concise (2-3 sentences)
3. If the diff doesn't explain the change, mention possible external factors
4. Format as markdown

Provide your analysis:"""

    analysis = call_claude_api(api_key, model, prompt)

    output = f"""## AI Performance Analysis

### Significant Changes
{changes_text}

### Analysis
{analysis}
"""

    print(output)

    Path(analysis_output).write_text(output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
