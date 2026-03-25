#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""AI-powered performance analysis using Claude.

Provides the model with statistical context (Z-score, stdev, historical trend),
system load data, and recent code diffs so the verdict is grounded.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path


def _get_git_diff() -> str:
    """Get git diff of recent changes."""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD~1", "--stat",
             "--", "*.py", "*.rs", "*.cpp", "*.c", "*.h"],
            capture_output=True, text=True, timeout=30,
        )
        stat = result.stdout.strip()

        result = subprocess.run(
            ["git", "diff", "HEAD~1",
             "--", "*.py", "*.rs", "*.cpp", "*.c", "*.h"],
            capture_output=True, text=True, timeout=30,
        )
        diff = result.stdout.strip()
        if len(diff) > 8000:
            diff = diff[:8000] + "\n... (truncated)"
        return f"Diff summary:\n{stat}\n\nDiff:\n{diff}"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "Git diff not available"


def _load_system_load(path: Path) -> str:
    """Format system load info for the prompt."""
    if not path.exists():
        return "System load data not available"
    try:
        with open(path) as f:
            data = json.load(f)
        cpu = data.get("cpu", {})
        mem = data.get("memory", {})
        cpu_load = cpu.get("normalized_load", 0)
        cpu_warning = cpu.get("warning", False)
        mem_usage = mem.get("usage_ratio", 0)
        mem_warning = mem.get("warning", False)
        lines = [f"CPU: {cpu_load:.0%}", f"Memory: {mem_usage:.0%}"]
        if cpu_warning:
            lines.append("⚠ CPU load was HIGH during this run")
        if mem_warning:
            lines.append("⚠ Memory usage was HIGH during this run")
        return "\n".join(lines)
    except (json.JSONDecodeError, KeyError):
        return "System load data not available"


def _format_regression_details(details: dict) -> str:
    """Format regression_details.json into a human-readable prompt section."""
    lines = []
    for name, metrics in details.get("benchmarks", {}).items():
        for key, d in metrics.items():
            method = d.get("detection_method", "percentage")
            stat_info = ""
            if method == "zscore":
                stat_info = f", z={d['zscore']}, σ={d['baseline_stdev']}"
            lines.append(
                f"- {name} {key}: {d['baseline_mean']:.2f} → {d['current']:.2f} "
                f"({d['change_pct']:+.1f}%, {d['direction']}{stat_info})"
            )
    return "\n".join(lines) if lines else "No significant changes detected"


def _call_claude_api(api_key: str, model: str, prompt: str) -> str:
    """Call Claude API for analysis."""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    data = {
        "model": model,
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        url, data=json.dumps(data).encode(), headers=headers,
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
    results_file = os.environ.get("RESULTS_FILE", "benchmark_results.json")
    details_file = os.environ.get("REGRESSION_DETAILS_FILE", "regression_details.json")
    system_load_path = Path(os.environ.get("SYSTEM_LOAD_OUTPUT", "system_load.json"))
    analysis_output = os.environ.get("AI_ANALYSIS_OUTPUT", "ai_analysis.md")

    # Load regression details (produced by detect_regression.py)
    details_path = Path(details_file)
    if not details_path.exists():
        return 0
    with open(details_path) as f:
        details = json.load(f)
    if not details.get("benchmarks"):
        return 0

    with open(results_file) as f:
        current = json.load(f)

    changes_text = _format_regression_details(details)
    system_load_text = _load_system_load(system_load_path)
    git_diff = _get_git_diff()

    prompt = f"""You are analyzing benchmark performance data for a compiled \
cryptographic kernel.

## Performance Changes (statistically significant)
{changes_text}

## System Load During Run
{system_load_text}

## Recent Code Changes
{git_diff}

## Instructions
Respond in EXACTLY this format:

**Verdict**: [Likely real regression | Likely noise | Inconclusive]
**Probable cause**: [1-2 sentences identifying the root cause]
**Recommendation**: [specific action — e.g. investigate X, re-run to confirm, safe to ignore]

### Detailed Analysis
[2-4 paragraphs explaining which code changes map to which benchmark \
changes. Reference specific files/functions from the diff. If system load \
was high, discuss whether that could explain the variance. Mention any \
benchmarks that changed unexpectedly (no obvious code change).]

Guidelines:
- If system load was HIGH, factor that into your verdict (high load → likely noise)
- If Z-score is extremely high (>10) AND code diff shows relevant changes, it is likely real
- If no relevant code changes in the diff, mention possible external factors"""

    analysis = _call_claude_api(api_key, model, prompt)

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
