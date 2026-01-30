#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""Verify test vectors in benchmark results."""
from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify benchmark test vectors")
    parser.add_argument(
        "--results",
        required=True,
        help="Path to benchmark results JSON",
    )
    args = parser.parse_args()

    with open(args.results) as f:
        data = json.load(f)

    failed = []
    for name, bench in data.get("benchmarks", {}).items():
        tv = bench.get("test_vectors", {})
        if not tv.get("verified", False):
            failed.append(name)

    if failed:
        print(f"ERROR: Test vector verification failed for: {', '.join(failed)}")
        return 1

    print("All test vectors verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
