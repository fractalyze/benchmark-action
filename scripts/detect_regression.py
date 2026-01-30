#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""Detect performance regression against baseline."""
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
    for name, curr_bench in current.get("benchmarks", {}).items():
        if name not in baseline.get("benchmarks", {}):
            continue

        base_bench = baseline["benchmarks"][name]
        curr_lat = curr_bench.get("latency", {}).get("value", 0)
        base_lat = base_bench.get("latency", {}).get("value", 0)

        if base_lat > 0:
            change = (curr_lat - base_lat) / base_lat
            if change > threshold:
                print(f"::warning::Regression in {name}: {change * 100:.1f}% slower")
                has_regression = True

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output and has_regression:
        with open(github_output, "a") as f:
            f.write("has_regression=true\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
