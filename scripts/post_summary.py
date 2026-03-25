#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""Generate GitHub Actions step summary with baseline comparison table."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from slack_chart import format_metric_value

_METRICS = [
    ("latency", "Latency", "ns", "increase"),
    ("throughput", "Throughput", "ops/s", "decrease"),
    ("memory", "Memory", "bytes", "increase"),
]


def _print_system_load_info() -> None:
    """Print system load information if available."""
    system_load_file = Path(os.environ.get("SYSTEM_LOAD_OUTPUT", "system_load.json"))
    if not system_load_file.exists():
        return

    with open(system_load_file) as f:
        data = json.load(f)

    cpu = data.get("cpu", {})
    mem = data.get("memory", {})
    cpu_load = cpu.get("normalized_load", 0)
    cpu_warning = cpu.get("warning", False)
    mem_usage = mem.get("usage_ratio", 0)
    mem_warning = mem.get("warning", False)

    print("## System Load\n")
    print("| Metric | Value | Status |")
    print("|--------|------:|--------|")
    print(f"| CPU Load | {cpu_load:.1%} | {'⚠️ High' if cpu_warning else '✅ OK'} |")
    print(f"| Memory | {mem_usage:.1%} | {'⚠️ High' if mem_warning else '✅ OK'} |")
    print()


def _load_regression_details() -> dict:
    """Load regression_details.json if available."""
    details_file = Path(os.environ.get("REGRESSION_DETAILS_FILE", "regression_details.json"))
    if not details_file.exists():
        return {}
    try:
        with open(details_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        return {}


def _load_baseline() -> dict:
    """Load baseline.json if available."""
    baseline_path = Path(os.environ.get("BASELINE_PATH", "benchmark_data/baseline.json"))
    if not baseline_path.exists():
        return {}
    try:
        with open(baseline_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        return {}


def main() -> int:
    results_file = os.environ.get("RESULTS_FILE", "benchmark_results.json")

    with open(results_file) as f:
        data = json.load(f)

    _print_system_load_info()

    details = _load_regression_details()
    baseline = _load_baseline()
    has_details = bool(details.get("benchmarks"))
    has_baseline = bool(baseline.get("benchmarks"))

    print("## Benchmark Results\n")

    if has_details or has_baseline:
        # Comparison table with baseline
        print("| Benchmark | Metric | Current | Baseline | Change | Status |")
        print("|-----------|--------|--------:|---------:|-------:|:------:|")

        for name, bench in data.get("benchmarks", {}).items():
            bench_details = details.get("benchmarks", {}).get(name, {})
            base_bench = baseline.get("benchmarks", {}).get(name, {})

            for key, label, default_unit, direction in _METRICS:
                curr_entry = bench.get(key, {})
                curr_val = curr_entry.get("value")
                if curr_val is None:
                    continue

                unit = curr_entry.get("unit", default_unit)
                curr_fmt = format_metric_value(curr_val, unit)

                # Try regression details first (has stdev info), then baseline
                detail = bench_details.get(key)
                if detail:
                    base_fmt = format_metric_value(detail["baseline_mean"], unit)
                    pct = detail["change_pct"]
                    is_regression = detail["direction"] == "regression"
                    status = "🔴" if is_regression else "🟢"
                    print(f"| {name} | {label} | {curr_fmt} | {base_fmt} | {pct:+.1f}% | {status} |")
                elif base_bench.get(key, {}).get("value"):
                    base_val = base_bench[key]["value"]
                    base_fmt = format_metric_value(base_val, unit)
                    if base_val > 0:
                        pct = (curr_val - base_val) / base_val * 100
                        # Determine if this is a regression based on direction
                        if direction == "increase":
                            is_regression = pct > 0
                        else:
                            is_regression = pct < 0
                        status = "🔴" if is_regression and abs(pct) > 5 else "🟢" if abs(pct) > 5 else "➖"
                        print(f"| {name} | {label} | {curr_fmt} | {base_fmt} | {pct:+.1f}% | {status} |")
                    else:
                        print(f"| {name} | {label} | {curr_fmt} | — | — | ➖ |")
                else:
                    print(f"| {name} | {label} | {curr_fmt} | — | — | ➖ |")

            # Test vector verification
            tv = bench.get("test_vectors", {})
            ver = tv.get("verified", False) if tv else False
            if tv:
                ver_status = "✅" if ver else "❌"
                print(f"| {name} | Vectors | {ver_status} | — | — | {'✅' if ver else '❌'} |")
    else:
        # No baseline — simple table
        print("| Benchmark | Latency | Throughput | Memory | Verified |")
        print("|-----------|--------:|-----------:|-------:|---------:|")

        for name, bench in data.get("benchmarks", {}).items():
            lat = bench.get("latency", {}).get("value")
            thr = bench.get("throughput", {}).get("value")
            mem_entry = bench.get("memory", {})
            mem = mem_entry.get("value")
            mem_unit = mem_entry.get("unit", "bytes")
            tv = bench.get("test_vectors", {})
            ver = tv.get("verified", False) if tv else False

            lat_str = format_metric_value(lat, "ns") if lat is not None else "—"
            thr_str = format_metric_value(thr, "ops/s") if thr is not None else "—"
            mem_str = format_metric_value(mem, mem_unit) if mem is not None else "—"
            ver_str = "✅" if ver else "❌"

            print(f"| {name} | {lat_str} | {thr_str} | {mem_str} | {ver_str} |")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
