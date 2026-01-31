#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""Generate GitHub Actions step summary for benchmark results."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def print_system_load_info() -> None:
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

    cpu_icon = "::warning::" if cpu_warning else ""
    mem_icon = "::warning::" if mem_warning else ""

    print("## System Load\n")
    print("| Metric | Value | Status |")
    print("|--------|-------|--------|")
    print(f"| CPU Load | {cpu_load:.1%} | {cpu_icon + 'High' if cpu_warning else 'OK'} |")
    print(f"| Memory | {mem_usage:.1%} | {mem_icon + 'High' if mem_warning else 'OK'} |")
    print()


def main() -> int:
    results_file = os.environ.get("RESULTS_FILE", "benchmark_results.json")

    with open(results_file) as f:
        data = json.load(f)

    # Print system load info first
    print_system_load_info()

    print("## Benchmark Results\n")
    print("| Benchmark | Latency (ns) | Throughput (ops/s) | Memory (MB) | Verified |")
    print("|-----------|--------------|--------------------:|------------:|---------:|")

    for name, bench in data.get("benchmarks", {}).items():
        lat = bench.get("latency", {}).get("value", "N/A")
        thr = bench.get("throughput", {}).get("value", "N/A")
        mem = bench.get("memory", {}).get("value", "N/A")
        tv = bench.get("test_vectors", {})
        ver = tv.get("verified", False) if tv else False

        lat_str = f"{lat:.2f}" if isinstance(lat, (int, float)) else lat
        thr_str = f"{thr:.0f}" if isinstance(thr, (int, float)) else thr
        mem_str = f"{mem:.1f}" if isinstance(mem, (int, float)) else mem
        ver_str = "Yes" if ver else "No"

        print(f"| {name} | {lat_str} | {thr_str} | {mem_str} | {ver_str} |")

    return 0


if __name__ == "__main__":
    sys.exit(main())
