#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""Detect performance regression against baseline using Z-score gating.

For each metric the detector computes a Z-score against the rolling baseline
(mean ± stdev).  A change is flagged only when *both*:
  1. ``|z| ≥ zscore_threshold``  (statistically significant)
  2. ``|change_pct| ≥ min_pct_floor``  (practically meaningful)

Each metric is judged independently — a latency-only regression still triggers
an alert.

When the baseline lacks stdev data (< 3 samples), falls back to a simple
percentage threshold.

Outputs:
  - ``has_significant_change`` / ``change_type`` to ``$GITHUB_OUTPUT``
  - ``regression_details.json`` with per-benchmark per-metric details
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# (key, direction, min_pct_floor)
# direction = "increase" means an increase is a regression.
_METRICS = [
    ("latency", "increase", 5.0),
    ("throughput", "decrease", 5.0),
    ("memory", "increase", 10.0),
]


def _check_metric(
    curr_bench: dict,
    base_bench: dict,
    key: str,
    direction: str,
    min_pct_floor: float,
    zscore_threshold: float,
    pct_fallback: float,
) -> dict | None:
    """Check a single metric for regression or improvement.

    Returns a detail dict or ``None`` if there is no significant change.
    """
    curr_val = curr_bench.get(key, {}).get("value", 0)
    base_entry = base_bench.get(key, {})
    base_val = base_entry.get("value", 0)
    base_stdev = base_entry.get("stdev", 0)
    sample_count = base_entry.get("sample_count", 0)

    if base_val <= 0 or curr_val <= 0:
        return None

    change_pct = (curr_val - base_val) / base_val * 100
    abs_change_pct = abs(change_pct)

    # Determine if change is statistically + practically significant
    use_zscore = base_stdev > 0 and sample_count >= 3
    if use_zscore:
        zscore = (curr_val - base_val) / base_stdev
        is_significant = abs(zscore) >= zscore_threshold and abs_change_pct >= min_pct_floor
    else:
        zscore = 0.0
        is_significant = abs_change_pct >= pct_fallback * 100

    if not is_significant:
        return None

    # Classify direction
    if direction == "increase":
        is_regression = change_pct > 0
    else:  # "decrease" — a decrease is a regression
        is_regression = change_pct < 0

    result_dir = "regression" if is_regression else "improvement"

    detail = {
        "current": curr_val,
        "baseline_mean": base_val,
        "baseline_stdev": base_stdev,
        "sample_count": sample_count,
        "zscore": round(zscore, 2),
        "change_pct": round(change_pct, 1),
        "direction": result_dir,
        "unit": base_entry.get("unit", ""),
        "detection_method": "zscore" if use_zscore else "percentage",
    }

    emoji = "::warning::" if is_regression else "::notice::"
    label = "Regression" if is_regression else "Improvement"

    return detail, emoji, label

    return detail


def main() -> int:
    zscore_threshold = float(os.environ.get("ZSCORE_THRESHOLD", "3.0"))
    pct_fallback = float(os.environ.get("REGRESSION_THRESHOLD", "0.10"))
    baseline_path = Path(os.environ.get("BASELINE_PATH", "benchmark_data/baseline.json"))
    results_file = os.environ.get("RESULTS_FILE", "benchmark_results.json")
    details_file = os.environ.get("REGRESSION_DETAILS_FILE", "regression_details.json")

    with open(results_file) as f:
        current = json.load(f)

    if not baseline_path.exists():
        print("No baseline found, skipping regression detection")
        return 0

    with open(baseline_path) as f:
        baseline = json.load(f)

    has_any_regression = False
    has_any_improvement = False
    all_details: dict = {"benchmarks": {}}

    for name, curr_bench in current.get("benchmarks", {}).items():
        if name not in baseline.get("benchmarks", {}):
            continue

        base_bench = baseline["benchmarks"][name]
        bench_details: dict = {}

        for key, direction, min_pct_floor in _METRICS:
            result = _check_metric(
                curr_bench, base_bench, key, direction,
                min_pct_floor, zscore_threshold, pct_fallback,
            )
            if result is None:
                continue

            detail, emoji, label = result
            pct = detail["change_pct"]
            z = detail["zscore"]
            print(f"{emoji}{label} in {name} {key}: {pct:+.1f}% (z={z:.1f})")

            bench_details[key] = detail

            if detail["direction"] == "regression":
                has_any_regression = True
            else:
                has_any_improvement = True

        if bench_details:
            all_details["benchmarks"][name] = bench_details

    has_significant_change = has_any_regression or has_any_improvement

    if has_any_regression and has_any_improvement:
        change_type = "mixed"
    elif has_any_regression:
        change_type = "regression"
    elif has_any_improvement:
        change_type = "improvement"
    else:
        change_type = ""

    # Write structured details for downstream consumers (Slack, AI analysis)
    with open(details_file, "w") as f:
        json.dump(all_details, f, indent=2)
        f.write("\n")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            if has_significant_change:
                f.write("has_significant_change=true\n")
            if change_type:
                f.write(f"change_type={change_type}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
