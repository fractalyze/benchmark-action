#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""Check system load before running benchmarks."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def get_cpu_info() -> tuple[float, int]:
    """Return (1-min load average, cpu count)."""
    load_avg = os.getloadavg()[0]
    cpu_count = os.cpu_count() or 1
    return load_avg, cpu_count


def get_memory_info() -> tuple[float, int, int]:
    """Return (usage ratio, used MB, total MB) from /proc/meminfo."""
    meminfo: dict[str, int] = {}
    with open("/proc/meminfo") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0].rstrip(":")
                meminfo[key] = int(parts[1])

    total_kb = meminfo.get("MemTotal", 0)
    available_kb = meminfo.get("MemAvailable", 0)

    if total_kb == 0:
        return 0.0, 0, 0

    used_kb = total_kb - available_kb
    usage_ratio = used_kb / total_kb
    used_mb = used_kb // 1024
    total_mb = total_kb // 1024

    return usage_ratio, used_mb, total_mb


def main() -> int:
    cpu_threshold = float(os.environ.get("CPU_LOAD_THRESHOLD", "0.80"))
    memory_threshold = float(os.environ.get("MEMORY_THRESHOLD", "0.80"))
    output_file = os.environ.get("SYSTEM_LOAD_OUTPUT", "system_load.json")

    load_avg, cpu_count = get_cpu_info()
    normalized_load = load_avg / cpu_count

    mem_usage, mem_used_mb, mem_total_mb = get_memory_info()

    result = {
        "cpu": {
            "load_avg_1m": round(load_avg, 2),
            "cpu_count": cpu_count,
            "normalized_load": round(normalized_load, 3),
            "threshold": cpu_threshold,
            "warning": normalized_load > cpu_threshold,
        },
        "memory": {
            "usage_ratio": round(mem_usage, 3),
            "used_mb": mem_used_mb,
            "total_mb": mem_total_mb,
            "threshold": memory_threshold,
            "warning": mem_usage > memory_threshold,
        },
    }

    Path(output_file).write_text(json.dumps(result, indent=2) + "\n")

    if result["cpu"]["warning"]:
        print(
            f"::warning::High CPU load detected: {normalized_load:.1%} "
            f"(threshold: {cpu_threshold:.0%})"
        )

    if result["memory"]["warning"]:
        print(
            f"::warning::High memory usage detected: {mem_usage:.1%} "
            f"(threshold: {memory_threshold:.0%})"
        )

    print(f"CPU load: {normalized_load:.1%} ({load_avg:.2f} / {cpu_count} cores)")
    print(f"Memory: {mem_usage:.1%} ({mem_used_mb} / {mem_total_mb} MB)")

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"cpu_load={normalized_load:.3f}\n")
            f.write(f"memory_usage={mem_usage:.3f}\n")
            f.write(f"cpu_warning={'true' if result['cpu']['warning'] else 'false'}\n")
            f.write(f"memory_warning={'true' if result['memory']['warning'] else 'false'}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
