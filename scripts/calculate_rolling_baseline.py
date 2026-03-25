#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""Calculate rolling average baseline from historical benchmark results.

Computes per-metric mean, stdev, and sample count after IQR-based outlier
filtering.  The enriched baseline is consumed by ``detect_regression.py``
for Z-score-based regression detection.
"""
from __future__ import annotations

import json
import os
import re
import statistics
import sys
from pathlib import Path

_METRICS = ("latency", "throughput", "memory")


def load_historical_results(results_dir: Path, window: int) -> list[dict]:
    """Load the most recent *window* historical results."""
    pattern = re.compile(r"^\d{8}T\d{6}\.json$")
    result_files = sorted(
        [f for f in results_dir.iterdir() if f.is_file() and pattern.match(f.name)],
        key=lambda f: f.name,
        reverse=True,
    )

    results = []
    for f in result_files[:window]:
        with open(f) as fp:
            results.append(json.load(fp))

    return results


def _filter_outliers_iqr(values: list[float]) -> list[float]:
    """Remove outliers outside [Q1 - 1.5*IQR, Q3 + 1.5*IQR]."""
    if len(values) < 4:
        return values

    s = sorted(values)
    n = len(s)
    q1 = s[n // 4]
    q3 = s[(3 * n) // 4]
    iqr = q3 - q1
    lo = q1 - 1.5 * iqr
    hi = q3 + 1.5 * iqr
    return [v for v in values if lo <= v <= hi]


def _compute_metric_baseline(
    values: list[float], unit: str,
) -> dict:
    """Return baseline dict with mean, stdev, sample_count for a metric."""
    filtered = _filter_outliers_iqr(values)
    if not filtered:
        filtered = values

    mean = statistics.mean(filtered)
    stdev = statistics.stdev(filtered) if len(filtered) >= 3 else 0.0
    return {
        "value": round(mean, 2),
        "stdev": round(stdev, 2),
        "sample_count": len(filtered),
        "unit": unit,
    }


def calculate_average_baseline(results: list[dict]) -> dict:
    """Calculate per-metric mean/stdev for each benchmark with outlier filtering."""
    if not results:
        return {}

    benchmark_data: dict[str, dict] = {}

    for result in results:
        for name, bench in result.get("benchmarks", {}).items():
            if name not in benchmark_data:
                benchmark_data[name] = {
                    m: [] for m in _METRICS
                } | {"sample": bench}

            for metric in _METRICS:
                val = bench.get(metric, {}).get("value")
                if val is not None:
                    benchmark_data[name][metric].append(val)

    baseline: dict = {"benchmarks": {}}

    # Use most recent result's metadata
    if results:
        baseline["metadata"] = results[0].get("metadata", {})
        baseline["metadata"]["baseline_type"] = "rolling_average"
        baseline["metadata"]["sample_count"] = len(results)

    for name, data in benchmark_data.items():
        sample = data["sample"]
        bench_baseline: dict = {}

        for metric in _METRICS:
            values = data[metric]
            if values:
                unit = sample.get(metric, {}).get("unit", "")
                bench_baseline[metric] = _compute_metric_baseline(values, unit)

        # Copy other fields from sample
        if "test_vectors" in sample:
            bench_baseline["test_vectors"] = sample["test_vectors"]
        if "metadata" in sample:
            bench_baseline["metadata"] = sample["metadata"]

        baseline["benchmarks"][name] = bench_baseline

    return baseline


def main() -> int:
    results_dir = Path(os.environ.get("RESULTS_DIR", "benchmark_data"))
    window = int(os.environ.get("ROLLING_WINDOW", "10"))
    min_samples = 2

    if not results_dir.exists():
        print(f"Results directory not found: {results_dir}")
        return 0

    results = load_historical_results(results_dir, window)

    if len(results) < min_samples:
        print(
            f"Not enough historical results for rolling baseline "
            f"({len(results)} < {min_samples})"
        )
        if results:
            # Fall back to using the most recent result as baseline
            baseline_path = results_dir / "baseline.json"
            with open(baseline_path, "w") as f:
                json.dump(results[0], f, indent=2)
            print("Using most recent result as baseline")
        return 0

    baseline = calculate_average_baseline(results)
    baseline_path = results_dir / "baseline.json"

    with open(baseline_path, "w") as f:
        json.dump(baseline, f, indent=2)
        f.write("\n")

    print(f"Rolling baseline calculated from {len(results)} results")
    for name in baseline.get("benchmarks", {}):
        bench = baseline["benchmarks"][name]
        lat = bench.get("latency", {})
        val = lat.get("value", "N/A")
        stdev = lat.get("stdev", 0)
        count = lat.get("sample_count", 0)
        print(f"  {name}: {val} ns (avg, σ={stdev}, n={count})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
