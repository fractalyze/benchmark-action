#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""Push benchmark results to the dashboard repo via GitHub Contents API.

Reads benchmark_results.json, builds a dashboard commit entry, and pushes
it directly to ``data/{impl}/history.json`` and ``data/manifest.json`` in the
dashboard repository.  Uses only stdlib (urllib, json, base64) so no pip
dependencies are needed in CI.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
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
IMPLEMENTATION = os.environ["IMPLEMENTATION"]
RESULTS_FILE = os.environ.get("RESULTS_FILE", "benchmark_results.json")
GITHUB_SHA = os.environ.get("GITHUB_SHA", "")

# Source repo name for commit links (e.g., "zkx" instead of "zkx-poseidon2-gpu")
_source_repo = os.environ.get("SOURCE_REPO", "")
if not _source_repo:
    # Fallback: derive from GITHUB_REPOSITORY (owner/repo → repo)
    gh_repo = os.environ.get("GITHUB_REPOSITORY", "")
    _source_repo = gh_repo.split("/")[-1] if gh_repo else IMPLEMENTATION
SOURCE_REPO = _source_repo

# Tags for the implementation (e.g., "gpu,cuda" → ["gpu", "cuda"])
_raw_tags = os.environ.get("TAGS", "")
TAGS: list[str] = [t.strip() for t in _raw_tags.split(",") if t.strip()] if _raw_tags else []

# Run URL for linking to the GitHub Actions run
_server_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
_gh_repository = os.environ.get("GITHUB_REPOSITORY", "")
_run_id = os.environ.get("GITHUB_RUN_ID", "")
RUN_URL = f"{_server_url}/{_gh_repository}/actions/runs/{_run_id}" if _gh_repository and _run_id else ""

MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


# ---------------------------------------------------------------------------
# GitHub Contents API helpers
# ---------------------------------------------------------------------------


def _api_headers() -> dict[str, str]:
    return {
        "Authorization": f"token {DASHBOARD_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }


def _api_url(path: str) -> str:
    return f"https://api.github.com/repos/{DASHBOARD_REPO}/contents/{path}"


def get_file(path: str) -> tuple[dict | None, str | None]:
    """GET a file from the dashboard repo.

    Returns ``(parsed_json, file_sha)`` or ``(None, None)`` on 404.
    """
    req = urllib.request.Request(_api_url(path), headers=_api_headers())
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            content = base64.b64decode(data["content"]).decode()
            return json.loads(content), data["sha"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, None
        raise


def put_file(
    path: str,
    content: dict,
    file_sha: str | None,
    message: str,
) -> None:
    """PUT (create or update) a JSON file in the dashboard repo.

    Retries up to ``MAX_RETRIES`` times on 409 Conflict.
    """
    body = {
        "message": message,
        "content": base64.b64encode(
            json.dumps(content, indent=2).encode()
        ).decode(),
    }
    if file_sha:
        body["sha"] = file_sha

    for attempt in range(1, MAX_RETRIES + 1):
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            _api_url(path),
            data=data,
            headers=_api_headers(),
            method="PUT",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                resp.read()
            return
        except urllib.error.HTTPError as e:
            if e.code == 409 and attempt < MAX_RETRIES:
                print(f"  409 Conflict on {path}, retrying ({attempt}/{MAX_RETRIES})...")
                time.sleep(RETRY_DELAY)
                # Re-fetch to get the latest SHA
                _, file_sha = get_file(path)
                body["sha"] = file_sha
                continue
            raise


# ---------------------------------------------------------------------------
# Platform / benchmark normalization (matches collect_data.py)
# ---------------------------------------------------------------------------


def normalize_platform(platform: dict) -> dict:
    """Rename cpu_vendor → cpu, gpu_vendor → gpu; drop arch/cpu_count."""
    normalized: dict[str, str] = {}
    if "os" in platform:
        normalized["os"] = platform["os"]
    if cpu := platform.get("cpu") or platform.get("cpu_vendor"):
        normalized["cpu"] = cpu
    if gpu := platform.get("gpu") or platform.get("gpu_vendor"):
        normalized["gpu"] = gpu
    return normalized


def normalize_benchmarks(benchmarks: dict) -> dict:
    """Keep only latency, throughput, memory (each with value + unit)."""
    result: dict[str, dict] = {}
    for name, bench in benchmarks.items():
        entry: dict[str, dict[str, object]] = {}
        for metric in ("latency", "throughput", "memory"):
            if metric in bench:
                entry[metric] = {
                    "value": bench[metric]["value"],
                    "unit": bench[metric].get("unit", ""),
                }
        result[name] = entry
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    # 1. Read benchmark results
    with open(RESULTS_FILE) as f:
        results = json.load(f)

    benchmarks = normalize_benchmarks(results.get("benchmarks", {}))

    raw_platform = (
        results.get("metadata", {}).get("platform")
        or results.get("platform")
        or {}
    )
    platform = normalize_platform(raw_platform)

    # 2. Commit metadata
    commit_sha = GITHUB_SHA
    short_sha = commit_sha[:7] if commit_sha else ""
    try:
        message = subprocess.run(
            ["git", "log", "--format=%s", "-1"],
            capture_output=True,
            text=True,
        ).stdout.strip()
    except Exception:
        message = ""

    timestamp = datetime.now(timezone.utc).isoformat()

    entry = {
        "sha": commit_sha,
        "shortSha": short_sha,
        "message": message,
        "timestamp": timestamp,
        "platform": platform,
        "benchmarks": benchmarks,
    }
    if RUN_URL:
        entry["runUrl"] = RUN_URL

    # 3. Update history.json
    history_path = f"data/{IMPLEMENTATION}/history.json"
    history, history_sha = get_file(history_path)

    if history is None:
        history = {
            "implementation": IMPLEMENTATION,
            "type": "tracked",
            "commits": [],
        }

    # Deduplicate by SHA
    existing_shas = {c["sha"] for c in history["commits"]}
    if commit_sha not in existing_shas:
        history["commits"].insert(0, entry)
    else:
        print(f"  Commit {short_sha} already exists, updating entry")
        history["commits"] = [
            entry if c["sha"] == commit_sha else c
            for c in history["commits"]
        ]

    put_file(
        history_path,
        history,
        history_sha,
        f"chore: update {IMPLEMENTATION} benchmark data ({short_sha})",
    )
    print(f"Pushed {IMPLEMENTATION} history ({len(history['commits'])} commits)")

    # 4. Update manifest.json — only touch the matching impl entry
    manifest_path = "data/manifest.json"
    manifest, manifest_sha = get_file(manifest_path)

    if manifest is None:
        manifest = {"implementations": [], "lastUpdated": timestamp}

    found = False
    for impl in manifest.get("implementations", []):
        if impl["name"] == IMPLEMENTATION:
            impl["commitCount"] = len(history["commits"])
            impl["latestCommit"] = short_sha
            found = True
            break

    # Ensure repo and tags are set on the matching entry
    for impl in manifest.get("implementations", []):
        if impl["name"] == IMPLEMENTATION:
            if SOURCE_REPO and SOURCE_REPO != IMPLEMENTATION:
                impl["repo"] = SOURCE_REPO
            if TAGS:
                impl["tags"] = TAGS
            break

    if not found:
        new_entry: dict[str, object] = {
            "name": IMPLEMENTATION,
            "type": "tracked",
            "commitCount": len(history["commits"]),
            "latestCommit": short_sha,
        }
        if SOURCE_REPO and SOURCE_REPO != IMPLEMENTATION:
            new_entry["repo"] = SOURCE_REPO
        if TAGS:
            new_entry["tags"] = TAGS
        manifest["implementations"].append(new_entry)

    manifest["lastUpdated"] = timestamp

    put_file(
        manifest_path,
        manifest,
        manifest_sha,
        f"chore: update manifest for {IMPLEMENTATION}",
    )
    print("Updated manifest.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())
