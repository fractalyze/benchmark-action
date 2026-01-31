#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""Calculate rolling average baseline from historical benchmark results."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


def load_historical_results(results_dir: Path, window: int) -> list[dict]:
    """Load the most recent N historical results."""
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


def calculate_average_baseline(results: list[dict]) -> dict:
    """Calculate average latency/throughput for each benchmark."""
    if not results:
        return {}

    benchmark_data: dict[str, dict] = {}

    for result in results:
        for name, bench in result.get("benchmarks", {}).items():
            if name not in benchmark_data:
                benchmark_data[name] = {"latencies": [], "throughputs": [], "sample": bench}

            lat = bench.get("latency", {}).get("value")
            if lat is not None:
                benchmark_data[name]["latencies"].append(lat)

            thr = bench.get("throughput", {}).get("value")
            if thr is not None:
                benchmark_data[name]["throughputs"].append(thr)

    baseline = {"benchmarks": {}}

    # Use most recent result's metadata
    if results:
        baseline["metadata"] = results[0].get("metadata", {})
        baseline["metadata"]["baseline_type"] = "rolling_average"
        baseline["metadata"]["sample_count"] = len(results)

    for name, data in benchmark_data.items():
        sample = data["sample"]
        bench_baseline = {}

        if data["latencies"]:
            avg_lat = sum(data["latencies"]) / len(data["latencies"])
            bench_baseline["latency"] = {
                "value": round(avg_lat, 2),
                "unit": sample.get("latency", {}).get("unit", "ns"),
            }

        if data["throughputs"]:
            avg_thr = sum(data["throughputs"]) / len(data["throughputs"])
            bench_baseline["throughput"] = {
                "value": round(avg_thr, 2),
                "unit": sample.get("throughput", {}).get("unit", "ops/s"),
            }

        # Copy other fields from sample
        if "test_vectors" in sample:
            bench_baseline["test_vectors"] = sample["test_vectors"]
        if "metadata" in sample:
            bench_baseline["metadata"] = sample["metadata"]

        baseline["benchmarks"][name] = bench_baseline

    return baseline


def main() -> int:
    results_dir = Path(os.environ.get("RESULTS_DIR", "benchmark_data"))
    window = int(os.environ.get("ROLLING_WINDOW", "5"))
    min_samples = 2

    if not results_dir.exists():
        print(f"Results directory not found: {results_dir}")
        return 0

    results = load_historical_results(results_dir, window)

    if len(results) < min_samples:
        print(f"Not enough historical results for rolling baseline ({len(results)} < {min_samples})")
        if results:
            # Fall back to using the most recent result as baseline
            baseline_path = results_dir / "baseline.json"
            with open(baseline_path, "w") as f:
                json.dump(results[0], f, indent=2)
            print(f"Using most recent result as baseline")
        return 0

    baseline = calculate_average_baseline(results)
    baseline_path = results_dir / "baseline.json"

    with open(baseline_path, "w") as f:
        json.dump(baseline, f, indent=2)
        f.write("\n")

    print(f"Rolling baseline calculated from {len(results)} results")
    for name in baseline.get("benchmarks", {}):
        bench = baseline["benchmarks"][name]
        lat = bench.get("latency", {}).get("value", "N/A")
        print(f"  {name}: {lat} ns (avg)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
