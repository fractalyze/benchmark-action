#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""Detect performance regression against baseline.

Checks latency (increase = regression), throughput (decrease = regression),
and memory (increase = regression).  Emits ``has_significant_change`` and
``change_type`` (regression | improvement | mixed) to ``$GITHUB_OUTPUT``.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Metric definitions: (key, label for regression, label for improvement, direction)
# direction = "increase" means an increase is a regression.
_METRICS = [
    ("latency", "slower", "faster", "increase"),
    ("throughput", "lower", "higher", "decrease"),
    ("memory", "more", "less", "increase"),
]


def _check_metric(
    name: str,
    key: str,
    curr_bench: dict,
    base_bench: dict,
    threshold: float,
    direction: str,
    regress_label: str,
    improve_label: str,
) -> str | None:
    """Check a single metric for regression or improvement.

    Returns ``"regression"``, ``"improvement"``, or ``None``.
    """
    curr_val = curr_bench.get(key, {}).get("value", 0)
    base_val = base_bench.get(key, {}).get("value", 0)
    if base_val <= 0 or curr_val <= 0:
        return None

    change = (curr_val - base_val) / base_val
    is_regression = change > threshold if direction == "increase" else change < -threshold
    is_improvement = change < -threshold if direction == "increase" else change > threshold

    if is_regression:
        pct = abs(change) * 100
        print(f"::warning::Regression in {name} {key}: {pct:.1f}% {regress_label}")
        return "regression"
    if is_improvement:
        pct = abs(change) * 100
        print(f"::notice::Improvement in {name} {key}: {pct:.1f}% {improve_label}")
        return "improvement"
    return None


def main() -> int:
    threshold = float(os.environ.get("REGRESSION_THRESHOLD", "0.10"))
    baseline_path = Path(os.environ.get("BASELINE_PATH", "benchmark_data/baseline.json"))
    results_file = os.environ.get("RESULTS_FILE", "benchmark_results.json")

    with open(results_file) as f:
        current = json.load(f)

    if not baseline_path.exists():
        print("No baseline found, skipping regression detection")
        return 0

    with open(baseline_path) as f:
        baseline = json.load(f)

    has_any_regression = False
    has_any_improvement = False

    for name, curr_bench in current.get("benchmarks", {}).items():
        if name not in baseline.get("benchmarks", {}):
            continue

        base_bench = baseline["benchmarks"][name]

        for key, regress_label, improve_label, direction in _METRICS:
            result = _check_metric(
                name, key, curr_bench, base_bench, threshold, direction,
                regress_label, improve_label,
            )
            if result == "regression":
                has_any_regression = True
            elif result == "improvement":
                has_any_improvement = True

    has_significant_change = has_any_regression or has_any_improvement

    if has_any_regression and has_any_improvement:
        change_type = "mixed"
    elif has_any_regression:
        change_type = "regression"
    elif has_any_improvement:
        change_type = "improvement"
    else:
        change_type = ""

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
