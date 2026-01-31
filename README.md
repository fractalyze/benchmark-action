# ZK Benchmark Action

Reusable GitHub Action for running ZK benchmarks with regression detection.

## Features

- Run any benchmark command that outputs JSON
- Verify test vectors
- Detect performance regressions against baseline
- Store historical results
- Send Slack alerts on regression
- Generate GitHub step summary
- System load pre-check (CPU and memory)
- Rolling average baseline from historical results
- Claude AI performance analysis

## Usage

```yaml
- uses: fractalyze/benchmark-action@v1
  with:
    benchmark_cmd: |
      bazel run //benchmark:poseidon2_benchmark -- \
        --output=benchmark_results.json
    implementation: whir-zorch
    regression_threshold: "0.10"
    slack_webhook: ${{ secrets.SLACK_BENCHMARK_WEBHOOK }}
    store_results: ${{ github.ref == 'refs/heads/main' }}
```

## Inputs

| Input                  | Required | Default                        | Description                                 |
| ---------------------- | -------- | ------------------------------ | ------------------------------------------- |
| `benchmark_cmd`        | Yes      | -                              | Command to run benchmark (must output JSON) |
| `implementation`       | Yes      | -                              | Implementation name (e.g., whir-zorch)      |
| `regression_threshold` | No       | `0.10`                         | Regression threshold as decimal             |
| `baseline_path`        | No       | `benchmark_data/baseline.json` | Path to baseline JSON                       |
| `results_file`         | No       | `benchmark_results.json`       | Output results file path                    |
| `slack_webhook`        | No       | `""`                           | Slack webhook URL for alerts                |
| `store_results`        | No       | `false`                        | Store results to results_dir                |
| `results_dir`          | No       | `benchmark_data`               | Directory for historical results            |
| `cpu_load_threshold`   | No       | `0.80`                         | CPU load threshold for warning (0-1)        |
| `memory_threshold`     | No       | `0.80`                         | Memory usage threshold for warning (0-1)    |
| `rolling_window`       | No       | `5`                            | Number of historical results for baseline   |
| `anthropic_api_key`    | No       | `""`                           | Anthropic API key for Claude AI analysis    |
| `ai_model`             | No       | `claude-opus-4-5-20251101`     | Claude model to use for analysis            |

## Outputs

| Output           | Description                    |
| ---------------- | ------------------------------ |
| `has_regression` | `true` if regression detected  |
| `results_file`   | Path to benchmark results JSON |
| `cpu_load`       | Normalized CPU load (0-1)      |
| `memory_usage`   | Memory usage ratio (0-1)       |

## JSON Schema

The benchmark command must output JSON matching this schema:

```json
{
  "metadata": {
    "implementation": "whir-zorch",
    "version": "0.1.0",
    "commit_sha": "abc123...",
    "timestamp": "2026-01-30T12:00:00Z",
    "platform": {
      "os": "linux",
      "arch": "x86_64",
      "cpu_count": 32,
      "cpu_vendor": "AMD Ryzen..."
    }
  },
  "benchmarks": {
    "benchmark_name": {
      "latency": { "value": 120.5, "unit": "ns" },
      "throughput": { "value": 8300.0, "unit": "ops/s" },
      "iterations": 1000,
      "test_vectors": {
        "input_hash": "sha256...",
        "output_hash": "sha256...",
        "verified": true
      },
      "metadata": {
        "field": "BabyBear",
        "width": 16
      }
    }
  }
}
```

## Example Workflow

```yaml
name: Benchmark

on:
  push:
    branches: [main]
  schedule:
    - cron: "0 2 * * *"

jobs:
  benchmark:
    runs-on: [self-hosted, benchmark]
    steps:
      - uses: actions/checkout@v4

      - uses: fractalyze/benchmark-action@v1
        with:
          benchmark_cmd: |
            cargo run --release -p my-bench -- --output=benchmark_results.json
          implementation: my-implementation
          regression_threshold: "0.10"
          rolling_window: "5"
          cpu_load_threshold: "0.80"
          memory_threshold: "0.80"
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          slack_webhook: ${{ secrets.SLACK_BENCHMARK_WEBHOOK }}
          store_results: ${{ github.ref == 'refs/heads/main' }}

      - uses: actions/upload-artifact@v4
        with:
          name: benchmark-results
          path: benchmark_results.json
```

## Testing

Run the unit tests with pytest:

```bash
cd scripts && python -m pytest -v
```

## License

Apache-2.0
