#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""Detect performance regression against baseline.

Checks latency (increase = regression), throughput (decrease = regression),
and memory (increase = regression).  Emits both ``has_regression`` and
``has_significant_change`` (includes improvements) to ``$GITHUB_OUTPUT``.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


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

    has_regression = False
    has_significant_change = False

    for name, curr_bench in current.get("benchmarks", {}).items():
        if name not in baseline.get("benchmarks", {}):
            continue

        base_bench = baseline["benchmarks"][name]

        # Latency: increase = regression
        curr_lat = curr_bench.get("latency", {}).get("value", 0)
        base_lat = base_bench.get("latency", {}).get("value", 0)

        if base_lat > 0 and curr_lat > 0:
            change = (curr_lat - base_lat) / base_lat
            if change > threshold:
                print(f"::warning::Regression in {name} latency: {change * 100:.1f}% slower")
                has_regression = True
                has_significant_change = True
            elif change < -threshold:
                print(f"::notice::Improvement in {name} latency: {abs(change) * 100:.1f}% faster")
                has_significant_change = True

        # Throughput: decrease = regression
        curr_tp = curr_bench.get("throughput", {}).get("value", 0)
        base_tp = base_bench.get("throughput", {}).get("value", 0)

        if base_tp > 0 and curr_tp > 0:
            change = (curr_tp - base_tp) / base_tp
            if change < -threshold:
                print(f"::warning::Regression in {name} throughput: {abs(change) * 100:.1f}% lower")
                has_regression = True
                has_significant_change = True
            elif change > threshold:
                print(f"::notice::Improvement in {name} throughput: {change * 100:.1f}% higher")
                has_significant_change = True

        # Memory: increase = regression
        curr_mem = curr_bench.get("memory", {}).get("value", 0)
        base_mem = base_bench.get("memory", {}).get("value", 0)

        if base_mem > 0 and curr_mem > 0:
            change = (curr_mem - base_mem) / base_mem
            if change > threshold:
                print(f"::warning::Regression in {name} memory: {change * 100:.1f}% more")
                has_regression = True
                has_significant_change = True
            elif change < -threshold:
                print(f"::notice::Improvement in {name} memory: {abs(change) * 100:.1f}% less")
                has_significant_change = True

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            if has_regression:
                f.write("has_regression=true\n")
            if has_significant_change:
                f.write("has_significant_change=true\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
