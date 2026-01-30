#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""Generate GitHub Actions step summary for benchmark results."""
from __future__ import annotations

import json
import os
import sys


def main() -> int:
    results_file = os.environ.get("RESULTS_FILE", "benchmark_results.json")

    with open(results_file) as f:
        data = json.load(f)

    print("## Benchmark Results\n")
    print("| Benchmark | Latency (ns) | Throughput (ops/s) | Verified |")
    print("|-----------|--------------|--------------------|---------:|")

    for name, bench in data.get("benchmarks", {}).items():
        lat = bench.get("latency", {}).get("value", "N/A")
        thr = bench.get("throughput", {}).get("value", "N/A")
        tv = bench.get("test_vectors", {})
        ver = tv.get("verified", False) if tv else False

        lat_str = f"{lat:.2f}" if isinstance(lat, (int, float)) else lat
        thr_str = f"{thr:.0f}" if isinstance(thr, (int, float)) else thr
        ver_str = "Yes" if ver else "No"

        print(f"| {name} | {lat_str} | {thr_str} | {ver_str} |")

    return 0


if __name__ == "__main__":
    sys.exit(main())
