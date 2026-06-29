#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""Push benchmark results to the dashboard repo via GitHub Git Trees API.

Reads benchmark_results.json, splits each benchmark into a separate file
``data-v2/{repo}-{name}-{device}.json``, and pushes all files + manifest in a
single atomic commit.  Uses only stdlib (urllib, json, base64) so no pip
dependencies are needed in CI.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------

DASHBOARD_TOKEN = os.environ["DASHBOARD_TOKEN"]
DASHBOARD_REPO = os.environ["DASHBOARD_REPO"]
DEVICE = os.environ["DEVICE"]
RESULTS_FILE = os.environ.get("RESULTS_FILE", "benchmark_results.json")
GITHUB_SHA = os.environ.get("GITHUB_SHA", "")

# Source repo name (e.g., "zkx", "whir-zorch")
_source_repo = os.environ.get("SOURCE_REPO", "")
if not _source_repo:
    gh_repo = os.environ.get("GITHUB_REPOSITORY", "")
    _source_repo = gh_repo.split("/")[-1] if gh_repo else ""
SOURCE_REPO = _source_repo

# ---------------------------------------------------------------------------
# Networking / retry tuning
# ---------------------------------------------------------------------------

# Per-request socket timeout. A healthy GitHub API call returns in well under a
# second; this only bounds a stalled connection so one bad request can never
# wedge the job indefinitely (a timeout-less urlopen once hung a scheduled run
# for 2h+ until it was cancelled by hand).
_API_TIMEOUT_S = 120
# Retries for a transient per-request failure (stall, connection error, 429/5xx).
_MAX_REQUEST_RETRIES = 3
# Rounds of rebuild-and-retry when the ref moved under us (HTTP 422); each round
# re-reads the latest dashboard state so a concurrent writer is never clobbered.
_MAX_PUSH_RETRIES = 5
# Exponential backoff base: sleeps 2s, 4s, 8s, ... between attempts.
_BACKOFF_BASE_S = 2
# HTTP statuses worth retrying as-is (server-side / rate-limit hiccups). A 4xx
# outside this set (e.g. 404, 422) is meaningful and must reach the caller.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


# ---------------------------------------------------------------------------
# GitHub Git API helpers
# ---------------------------------------------------------------------------


def _api_headers() -> dict[str, str]:
    return {
        "Authorization": f"token {DASHBOARD_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }


def _open(req: urllib.request.Request) -> dict:
    """Send a request with a bounded timeout, retrying transient failures.

    Retries a stalled/timed-out connection, a connection-level error, and a
    retryable server status (429/5xx) with exponential backoff. An HTTP error
    outside ``_RETRYABLE_STATUS`` (e.g. 404, 422) propagates immediately so the
    caller can act on it.
    """
    last_err: Exception | None = None
    for attempt in range(_MAX_REQUEST_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=_API_TIMEOUT_S) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code not in _RETRYABLE_STATUS:
                raise
            last_err = e
        except (
            urllib.error.URLError,
            ConnectionError,
            socket.timeout,
            TimeoutError,
        ) as e:
            # Connection-level failure or a read timeout. A connect-time error
            # arrives wrapped in URLError, but a connection reset mid-read
            # (resp.read()) surfaces as a bare ConnectionError; socket.timeout
            # is an alias of TimeoutError.
            last_err = e
        if attempt < _MAX_REQUEST_RETRIES - 1:
            time.sleep(_BACKOFF_BASE_S * (2**attempt))
    assert last_err is not None
    raise last_err


def _api(method: str, endpoint: str, body: dict | None = None) -> dict:
    """Call the GitHub API and return parsed JSON response."""
    url = f"https://api.github.com/repos/{DASHBOARD_REPO}/{endpoint}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=_api_headers(), method=method)
    return _open(req)


def get_file_content(path: str) -> tuple[dict | None, str | None]:
    """GET a JSON file from the dashboard repo via Contents API.

    Returns ``(parsed_json, blob_sha)`` or ``(None, None)`` on 404.
    """
    url = f"https://api.github.com/repos/{DASHBOARD_REPO}/contents/{path}"
    req = urllib.request.Request(url, headers=_api_headers())
    try:
        data = _open(req)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, None
        raise
    content = base64.b64decode(data["content"]).decode()
    return json.loads(content), data["sha"]


# ---------------------------------------------------------------------------
# Git Trees API: atomic multi-file commit
# ---------------------------------------------------------------------------


def push_atomic_commit(files: dict[str, dict], message: str) -> None:
    """Push all files in a single atomic git commit on top of current HEAD.

    Args:
        files: mapping of ``path -> json_content`` to create/update.
        message: commit message.

    Flow: get ref → get base tree → create blobs → create tree →
          create commit → update ref.

    Raises ``urllib.error.HTTPError`` with code 422 if the ref moved under us
    between reading HEAD and updating it; the caller rebuilds and retries.
    """
    # 1. Get HEAD ref
    ref_data = _api("GET", "git/ref/heads/main")
    head_sha = ref_data["object"]["sha"]

    # 2. Get base tree
    commit_data = _api("GET", f"git/commits/{head_sha}")
    base_tree_sha = commit_data["tree"]["sha"]

    # 3. Create blobs for each file
    tree_items: list[dict] = []
    for path, content in files.items():
        blob = _api(
            "POST",
            "git/blobs",
            {
                "content": json.dumps(content, indent=2),
                "encoding": "utf-8",
            },
        )
        tree_items.append(
            {
                "path": path,
                "mode": "100644",
                "type": "blob",
                "sha": blob["sha"],
            }
        )

    # 4. Create tree
    tree = _api(
        "POST",
        "git/trees",
        {
            "base_tree": base_tree_sha,
            "tree": tree_items,
        },
    )

    # 5. Create commit
    new_commit = _api(
        "POST",
        "git/commits",
        {
            "message": message,
            "tree": tree["sha"],
            "parents": [head_sha],
        },
    )

    # 6. Update ref
    _api(
        "PATCH",
        "git/refs/heads/main",
        {
            "sha": new_commit["sha"],
        },
    )


# ---------------------------------------------------------------------------
# Platform / benchmark normalization
# ---------------------------------------------------------------------------


def normalize_platform(platform: dict) -> dict:
    """Rename cpu_vendor → cpu, gpu_vendor → gpu; drop arch/cpu_count.

    GPU info is included only when DEVICE is "gpu".
    """
    normalized: dict[str, str] = {}
    if "os" in platform:
        normalized["os"] = platform["os"]
    if cpu := platform.get("cpu") or platform.get("cpu_vendor"):
        normalized["cpu"] = cpu
    if DEVICE == "gpu":
        if gpu := platform.get("gpu") or platform.get("gpu_vendor"):
            normalized["gpu"] = gpu
    return normalized


def normalize_metrics(bench: dict) -> dict:
    """Extract latency, throughput, memory (each with value + unit)."""
    metrics: dict[str, dict[str, object]] = {}
    for metric in ("latency", "throughput", "memory"):
        if metric in bench:
            metrics[metric] = {
                "value": bench[metric]["value"],
                "unit": bench[metric].get("unit", ""),
            }
    return metrics


# ---------------------------------------------------------------------------
# Result assembly
# ---------------------------------------------------------------------------


def build_files_to_push(
    results: dict, timestamp: str
) -> tuple[dict[str, dict], list[str]]:
    """Read the current dashboard files and layer this run's results on top.

    Returns ``(files_to_push, benchmark_keys)``. This performs a fresh
    read-modify-write against the live dashboard state, so it is re-run on every
    push attempt: if a concurrent writer committed between our read and our ref
    update (HTTP 422), the next attempt sees their results and preserves them
    rather than clobbering them.
    """
    raw_benchmarks = results.get("benchmarks", {})
    raw_platform = (
        results.get("metadata", {}).get("platform") or results.get("platform") or {}
    )
    platform = normalize_platform(raw_platform)

    commit_sha = GITHUB_SHA
    new_result = {
        "commit": commit_sha,
        "timestamp": timestamp,
        "platform": platform,
    }

    files_to_push: dict[str, dict] = {}
    benchmark_keys: list[str] = []

    for bench_key, bench_data in raw_benchmarks.items():
        # bench_key may be "name/degree" (zkbench compound key) or plain "name".
        # Extract the operation name by taking the first segment.
        bench_name = bench_key.split("/")[0]
        bench_meta = bench_data.get("metadata", {})
        field = bench_meta.get("field", "unknown")
        degree = bench_meta.get("degree", "0")
        file_key = f"{SOURCE_REPO}-{field}-{degree}-{bench_name}-{DEVICE}"
        file_path = f"data-v2/{file_key}.json"
        benchmark_keys.append(file_key)

        existing, _ = get_file_content(file_path)

        if existing is None:
            existing = {
                "repo": SOURCE_REPO,
                "field": field,
                "degree": degree,
                "name": bench_name,
                "device": DEVICE,
                "results": [],
            }

        # Build result with metrics for this benchmark
        result_entry = {**new_result, "metrics": normalize_metrics(bench_data)}

        # Deduplicate by commit SHA
        existing_commits = {r["commit"] for r in existing["results"]}
        if commit_sha not in existing_commits:
            existing["results"].insert(0, result_entry)
        else:
            print(f"  Commit {commit_sha[:7]} already exists in {file_key}, updating")
            existing["results"] = [
                result_entry if r["commit"] == commit_sha else r
                for r in existing["results"]
            ]

        files_to_push[file_path] = existing

    # Update manifest
    manifest_path = "data-v2/manifest.json"
    manifest, _ = get_file_content(manifest_path)

    if manifest is None:
        manifest = {"benchmarks": [], "lastUpdated": timestamp}

    existing_benchmarks = set(manifest.get("benchmarks", []))
    existing_benchmarks.update(benchmark_keys)
    manifest["benchmarks"] = sorted(existing_benchmarks)
    manifest["lastUpdated"] = timestamp

    files_to_push[manifest_path] = manifest

    return files_to_push, benchmark_keys


def push_results(results: dict, timestamp: str, message: str) -> tuple[int, list[str]]:
    """Build and push results, rebuilding on a ref-race (HTTP 422).

    Returns ``(num_benchmark_files, benchmark_keys)`` on success. Raises if the
    ref keeps moving after ``_MAX_PUSH_RETRIES`` rounds, or on any non-422 error.
    """
    last_err: urllib.error.HTTPError | None = None
    for attempt in range(_MAX_PUSH_RETRIES):
        files_to_push, benchmark_keys = build_files_to_push(results, timestamp)
        try:
            push_atomic_commit(files_to_push, message)
        except urllib.error.HTTPError as e:
            if e.code != 422:
                raise
            # The ref moved under us — a concurrent dashboard writer won the
            # race. Back off, then rebuild against their new HEAD so we layer
            # on top of (not over) their results.
            last_err = e
            if attempt < _MAX_PUSH_RETRIES - 1:
                time.sleep(_BACKOFF_BASE_S * (2**attempt))
            continue
        return len(files_to_push) - 1, benchmark_keys
    raise RuntimeError(
        f"dashboard push failed after {_MAX_PUSH_RETRIES} ref-race retries"
    ) from last_err


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    # 1. Read benchmark results
    with open(RESULTS_FILE) as f:
        results = json.load(f)

    raw_benchmarks = results.get("benchmarks", {})
    if not raw_benchmarks:
        print("No benchmarks found in results file")
        return 1

    timestamp = datetime.now(timezone.utc).isoformat()

    # 2. Push all files in one atomic commit, rebuilding on a ref-race.
    commit_sha = GITHUB_SHA
    short_sha = commit_sha[:7] if commit_sha else "unknown"
    bench_names = ", ".join(sorted(raw_benchmarks.keys()))
    commit_msg = f"chore: update {SOURCE_REPO} benchmarks ({short_sha})\n\n{bench_names}"

    num_files, benchmark_keys = push_results(results, timestamp, commit_msg)

    print(f"Pushed {num_files} benchmark file(s) + manifest")
    for key in sorted(benchmark_keys):
        print(f"  data-v2/{key}.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())
