#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""Utilities for visual Slack alerts: sparklines, dashboard URLs, metric formatting.

Used by ``send_slack_alert.py`` to render human-readable benchmark reports.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Any

_SPARK_CHARS = "▁▂▃▄▅▆▇█"

_DASHBOARD_BASE = "https://fractalyze.github.io/benchmark-dashboard/"


def render_sparkline(values: list[float]) -> str:
    """Map *values* to a Unicode block-character sparkline.

    Returns a string like ``▁▂▁▁▁▁▇▂▄`` — one character per value.
    """
    if not values:
        return ""
    lo = min(values)
    hi = max(values)
    span = hi - lo
    if span == 0:
        return _SPARK_CHARS[0] * len(values)
    n = len(_SPARK_CHARS) - 1
    return "".join(
        _SPARK_CHARS[min(int((v - lo) / span * n), n)] for v in values
    )


def build_dashboard_url(repo: str, device: str, benchmark: str) -> str:
    """Build a deep-link URL into the benchmark dashboard."""
    return (
        f"{_DASHBOARD_BASE}"
        f"#benchmarks?repo={repo}&name={benchmark}&device={device}"
    )


def format_metric_value(value: float, unit: str) -> str:
    """Format a metric value with human-readable unit scaling.

    Mirrors the formatting logic from ``dashboard.js:formatLatency`` /
    ``dashboard.js:formatThroughput``.
    """
    if unit == "ns":
        if value >= 1e9:
            return f"{value / 1e9:.2f} s"
        if value >= 1e6:
            return f"{value / 1e6:.2f} ms"
        if value >= 1e3:
            return f"{value / 1e3:.2f} μs"
        return f"{value:.1f} ns"
    if unit == "ops/s":
        if value >= 1e9:
            return f"{value / 1e9:.2f} Gops/s"
        if value >= 1e6:
            return f"{value / 1e6:.2f} Mops/s"
        if value >= 1e3:
            return f"{value / 1e3:.2f} Kops/s"
        return f"{value:.1f} ops/s"
    if unit == "bytes":
        if value >= 1024 * 1024 * 1024:
            return f"{value / (1024 ** 3):.2f} GB"
        if value >= 1024 * 1024:
            return f"{value / (1024 ** 2):.2f} MB"
        if value >= 1024:
            return f"{value / 1024:.2f} KB"
        return f"{value:.0f} B"
    return f"{value:.2f} {unit}" if unit else f"{value:.2f}"


def load_history_from_dashboard(
    token: str,
    dashboard_repo: str,
    repo: str,
    benchmark: str,
    device: str,
    metric: str = "latency",
    limit: int = 15,
) -> tuple[list[str], list[float]]:
    """Fetch historical metric values from the dashboard data-v2 via GitHub API.

    Returns (commits, values) — both lists of length ≤ *limit*, oldest first.
    """
    file_key = f"{repo}-{benchmark}-{device}"
    url = (
        f"https://api.github.com/repos/{dashboard_repo}"
        f"/contents/data-v2/{file_key}.json"
    )
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3.raw",
    }

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data: dict[str, Any] = json.loads(resp.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError):
        return [], []

    results = data.get("results", [])
    # Sort oldest-first by timestamp
    results.sort(key=lambda r: r.get("timestamp", ""))

    commits: list[str] = []
    values: list[float] = []
    for r in results[-limit:]:
        val = (r.get("metrics", {}).get(metric, {}) or {}).get("value")
        if val is not None:
            commits.append((r.get("commit", "") or "")[:7])
            values.append(val)

    return commits, values
