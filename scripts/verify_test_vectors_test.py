#!/usr/bin/env python3
# Copyright 2026 Fractalyze Authors.
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for verify_test_vectors.py."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from verify_test_vectors import main


class TestVerifyTestVectors(unittest.TestCase):
    """Tests for the verify_test_vectors module."""

    def _create_temp_json(self, data: dict) -> str:
        """Create a temporary JSON file with the given data."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(data, f)
            return f.name

    def test_all_verified_returns_zero(self) -> None:
        """Test that all verified benchmarks return 0."""
        data = {
            "benchmarks": {
                "bench1": {"test_vectors": {"verified": True}},
                "bench2": {"test_vectors": {"verified": True}},
            }
        }
        path = self._create_temp_json(data)
        try:
            with patch("sys.argv", ["verify_test_vectors.py", "--results", path]):
                result = main()
            self.assertEqual(result, 0)
        finally:
            Path(path).unlink()

    def test_failed_verification_returns_one(self) -> None:
        """Test that failed verification returns 1."""
        data = {
            "benchmarks": {
                "bench1": {"test_vectors": {"verified": True}},
                "bench2": {"test_vectors": {"verified": False}},
            }
        }
        path = self._create_temp_json(data)
        try:
            with patch("sys.argv", ["verify_test_vectors.py", "--results", path]):
                result = main()
            self.assertEqual(result, 1)
        finally:
            Path(path).unlink()

    def test_missing_verified_field_fails(self) -> None:
        """Test that missing verified field is treated as failure."""
        data = {
            "benchmarks": {
                "bench1": {"test_vectors": {}},
            }
        }
        path = self._create_temp_json(data)
        try:
            with patch("sys.argv", ["verify_test_vectors.py", "--results", path]):
                result = main()
            self.assertEqual(result, 1)
        finally:
            Path(path).unlink()

    def test_missing_test_vectors_field_fails(self) -> None:
        """Test that missing test_vectors field is treated as failure."""
        data = {
            "benchmarks": {
                "bench1": {},
            }
        }
        path = self._create_temp_json(data)
        try:
            with patch("sys.argv", ["verify_test_vectors.py", "--results", path]):
                result = main()
            self.assertEqual(result, 1)
        finally:
            Path(path).unlink()

    def test_empty_benchmarks_returns_zero(self) -> None:
        """Test that empty benchmarks returns 0 (nothing to fail)."""
        data = {"benchmarks": {}}
        path = self._create_temp_json(data)
        try:
            with patch("sys.argv", ["verify_test_vectors.py", "--results", path]):
                result = main()
            self.assertEqual(result, 0)
        finally:
            Path(path).unlink()

    def test_missing_benchmarks_key_returns_zero(self) -> None:
        """Test that missing benchmarks key returns 0."""
        data = {}
        path = self._create_temp_json(data)
        try:
            with patch("sys.argv", ["verify_test_vectors.py", "--results", path]):
                result = main()
            self.assertEqual(result, 0)
        finally:
            Path(path).unlink()


if __name__ == "__main__":
    unittest.main()
