#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for push_to_dashboard.py."""
from __future__ import annotations

import json
import os
import unittest
import urllib.error
from unittest.mock import patch

# The module reads its config from the environment at import time.
os.environ.setdefault("DASHBOARD_TOKEN", "test-token")
os.environ.setdefault("DASHBOARD_REPO", "fractalyze/benchmark-dashboard")
os.environ.setdefault("DEVICE", "cpu")
os.environ.setdefault("GITHUB_REPOSITORY", "fractalyze/src")
os.environ.setdefault("GITHUB_SHA", "abc1234")

import push_to_dashboard as p2d  # noqa: E402


class _FakeResp:
    """Minimal context-manager stand-in for an urlopen response."""

    def __init__(self, payload: dict) -> None:
        self._bytes = json.dumps(payload).encode()

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._bytes


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.github.com", code, f"status {code}", hdrs=None, fp=None
    )


class TestOpenRetry(unittest.TestCase):
    """_open() bounds each request and retries only transient failures."""

    def test_retries_on_timeout_then_succeeds(self) -> None:
        attempts = [TimeoutError(), TimeoutError(), _FakeResp({"ok": True})]
        with patch.object(
            p2d.urllib.request, "urlopen", side_effect=attempts
        ) as mock_open, patch.object(p2d.time, "sleep"):
            result = p2d._open(p2d.urllib.request.Request("https://api.github.com"))
        self.assertEqual(result, {"ok": True})
        self.assertEqual(mock_open.call_count, 3)

    def test_retries_on_connection_reset_then_succeeds(self) -> None:
        # A reset mid-read surfaces as a bare ConnectionError, not URLError.
        attempts = [ConnectionResetError(), _FakeResp({"ok": True})]
        with patch.object(
            p2d.urllib.request, "urlopen", side_effect=attempts
        ) as mock_open, patch.object(p2d.time, "sleep"):
            result = p2d._open(p2d.urllib.request.Request("https://api.github.com"))
        self.assertEqual(result, {"ok": True})
        self.assertEqual(mock_open.call_count, 2)

    def test_passes_timeout_to_urlopen(self) -> None:
        with patch.object(
            p2d.urllib.request, "urlopen", return_value=_FakeResp({"ok": True})
        ) as mock_open:
            p2d._open(p2d.urllib.request.Request("https://api.github.com"))
        _, kwargs = mock_open.call_args
        self.assertEqual(kwargs.get("timeout"), p2d._API_TIMEOUT_S)

    def test_non_retryable_http_error_propagates_without_retry(self) -> None:
        with patch.object(
            p2d.urllib.request, "urlopen", side_effect=_http_error(404)
        ) as mock_open, patch.object(p2d.time, "sleep"):
            with self.assertRaises(urllib.error.HTTPError):
                p2d._open(p2d.urllib.request.Request("https://api.github.com"))
        self.assertEqual(mock_open.call_count, 1)

    def test_gives_up_after_max_retries(self) -> None:
        with patch.object(
            p2d.urllib.request, "urlopen", side_effect=TimeoutError()
        ) as mock_open, patch.object(p2d.time, "sleep"):
            with self.assertRaises(TimeoutError):
                p2d._open(p2d.urllib.request.Request("https://api.github.com"))
        self.assertEqual(mock_open.call_count, p2d._MAX_REQUEST_RETRIES)


class TestPushRefRace(unittest.TestCase):
    """push_results() rebuilds on a 422 and never clobbers a concurrent writer."""

    def test_422_rebuild_preserves_concurrent_results(self) -> None:
        data_path = "data-v2/src-bn254-0-op-cpu.json"
        results = {
            "benchmarks": {
                "op": {
                    "metadata": {"field": "bn254", "degree": "0"},
                    "latency": {"value": 1.0, "unit": "ms"},
                }
            }
        }

        # Simulated live dashboard state.
        remote: dict[str, dict] = {}
        patch_calls = {"n": 0}

        def fake_get_file_content(path: str):
            cur = remote.get(path)
            # Deep-copy so the caller's in-place edits don't leak into "remote".
            return (json.loads(json.dumps(cur)) if cur is not None else None, "sha")

        def fake_push_atomic_commit(files: dict[str, dict], message: str) -> None:
            patch_calls["n"] += 1
            if patch_calls["n"] == 1:
                # A concurrent writer commits their result first; our ref update
                # then loses the race and GitHub rejects it with a 422.
                remote[data_path] = {
                    "repo": "src",
                    "results": [{"commit": "concurrent", "metrics": {}}],
                }
                raise _http_error(422)
            remote.update(files)  # second attempt fast-forwards cleanly

        with patch.object(
            p2d, "get_file_content", side_effect=fake_get_file_content
        ), patch.object(
            p2d, "push_atomic_commit", side_effect=fake_push_atomic_commit
        ), patch.object(p2d.time, "sleep"):
            num_files, keys = p2d.push_results(results, "2026-06-30T00:00:00Z", "msg")

        self.assertEqual(patch_calls["n"], 2)  # raced once, then succeeded
        commits = [r["commit"] for r in remote[data_path]["results"]]
        self.assertIn("concurrent", commits)  # concurrent writer preserved
        self.assertIn("abc1234", commits)  # our result present
        self.assertEqual(num_files, 1)
        self.assertEqual(keys, ["src-bn254-0-op-cpu"])

    def test_persistent_422_raises_runtime_error_chaining_http_error(self) -> None:
        results = {
            "benchmarks": {
                "op": {
                    "metadata": {"field": "bn254", "degree": "0"},
                    "latency": {"value": 1.0, "unit": "ms"},
                }
            }
        }
        http_422 = _http_error(422)

        def always_422(files: dict[str, dict], message: str) -> None:
            raise http_422

        with patch.object(
            p2d, "get_file_content", return_value=(None, "sha")
        ), patch.object(
            p2d, "push_atomic_commit", side_effect=always_422
        ), patch.object(p2d.time, "sleep"):
            with self.assertRaises(RuntimeError) as ctx:
                p2d.push_results(results, "2026-06-30T00:00:00Z", "msg")
        self.assertIs(ctx.exception.__cause__, http_422)

    def test_non_422_http_error_propagates_immediately(self) -> None:
        results = {
            "benchmarks": {
                "op": {
                    "metadata": {"field": "bn254", "degree": "0"},
                    "latency": {"value": 1.0, "unit": "ms"},
                }
            }
        }
        calls = {"n": 0}

        def fail_500(files: dict[str, dict], message: str) -> None:
            calls["n"] += 1
            raise _http_error(500)

        with patch.object(
            p2d, "get_file_content", return_value=(None, "sha")
        ), patch.object(
            p2d, "push_atomic_commit", side_effect=fail_500
        ), patch.object(p2d.time, "sleep"):
            with self.assertRaises(urllib.error.HTTPError):
                p2d.push_results(results, "2026-06-30T00:00:00Z", "msg")
        self.assertEqual(calls["n"], 1)  # not retried as a ref race


if __name__ == "__main__":
    unittest.main()
