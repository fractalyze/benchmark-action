# ZK Benchmark Action

Reusable GitHub Action for running ZK benchmarks with regression detection.

## Features

- Run any benchmark command that outputs JSON
- Verify test vectors
- Detect performance regressions against baseline
- Store historical results
- Push per-benchmark results to dashboard repo via Git Trees API (atomic commit)
- Send Slack alerts on regression
- Generate GitHub step summary
- System load pre-check (CPU and memory)
- Rolling average baseline from historical results
- Claude AI performance analysis

## Usage

```yaml
- uses: fractalyze/benchmark-action@v2
  with:
    benchmark_cmd: |
      bazel run //benchmark:poseidon2_benchmark -- \
        --output=benchmark_results.json
    repo: whir-zorch
    device: cpu
    regression_threshold: "0.10"
    slack_webhook: ${{ secrets.SLACK_BENCHMARK_WEBHOOK }}
    dashboard_token: ${{ secrets.DASHBOARD_TOKEN }}
    store_results: ${{ github.ref == 'refs/heads/main' }}
```

## Inputs

| Input                  | Required | Default                          | Description                                 |
| ---------------------- | -------- | -------------------------------- | ------------------------------------------- |
| `benchmark_cmd`        | Yes      | -                                | Command to run benchmark (must output JSON) |
| `device`               | Yes      | -                                | Device type (`cpu` or `gpu`)                |
| `repo`                 | No       | GITHUB_REPOSITORY tail           | Source repository name (e.g., `zkx`)        |
| `regression_threshold` | No       | `0.10`                           | Regression threshold as decimal             |
| `baseline_path`        | No       | `benchmark_data/baseline.json`   | Path to baseline JSON                       |
| `results_file`         | No       | `benchmark_results.json`         | Output results file path                    |
| `slack_webhook`        | No       | `""`                             | Slack webhook URL for alerts                |
| `store_results`        | No       | `false`                          | Store results to results_dir                |
| `results_dir`          | No       | `benchmark_data`                 | Directory for historical results            |
| `cpu_load_threshold`   | No       | `0.80`                           | CPU load threshold for warning (0-1)        |
| `memory_threshold`     | No       | `0.80`                           | Memory usage threshold for warning (0-1)    |
| `rolling_window`       | No       | `5`                              | Number of historical results for baseline   |
| `anthropic_api_key`    | No       | `""`                             | Anthropic API key for Claude AI analysis    |
| `ai_model`             | No       | `claude-opus-4-5-20251101`       | Claude model to use for analysis            |
| `dashboard_token`      | No       | `""`                             | GitHub token for dashboard repo updates     |
| `dashboard_repo`       | No       | `fractalyze/benchmark-dashboard` | Dashboard repository (owner/repo)           |

## Outputs

| Output                   | Description                                    |
| ------------------------ | ---------------------------------------------- |
| `has_significant_change` | `true` if regression or improvement detected   |
| `change_type`            | `regression`, `improvement`, `mixed`, or empty |
| `results_file`           | Path to benchmark results JSON                 |
| `cpu_load`               | Normalized CPU load (0-1)                      |
| `memory_usage`           | Memory usage ratio (0-1)                       |

## JSON Schema

The benchmark command must output JSON matching this schema:

```json
{
  "metadata": {
    "platform": {
      "os": "linux",
      "cpu_vendor": "AMD Ryzen...",
      "gpu_vendor": "NVIDIA RTX 5090"
    }
  },
  "benchmarks": {
    "poseidon2": {
      "latency": { "value": 86880, "unit": "ns" },
      "throughput": { "value": 11510, "unit": "ops/s" },
      "metadata": { "field": "koalabear", "degree": "20" }
    },
    "fft": {
      "latency": { "value": 143200, "unit": "ns" },
      "metadata": { "field": "koalabear", "degree": "16" }
    }
  }
}
```

Each benchmark in the `benchmarks` dict is split into a separate file
`data-v2/{repo}-{field}-{degree}-{name}-{device}.json` in the dashboard repo:

```json
{
  "repo": "whir-zorch",
  "field": "koalabear",
  "degree": "20",
  "name": "poseidon2",
  "device": "gpu",
  "results": [
    {
      "commit": "55364efd6d995f4ff3e3a45cb817dc7698133c57",
      "timestamp": "2026-02-25T10:30:00Z",
      "platform": { "os": "linux", "gpu": "NVIDIA RTX 5090" },
      "metrics": {
        "latency": { "value": 86880, "unit": "ns" },
        "throughput": { "value": 11510, "unit": "ops/s" }
      }
    }
  ]
}
```

## Example Workflow

```yaml
name: Benchmark

on:
  push:
    branches: [main]

jobs:
  benchmark:
    runs-on: [self-hosted, benchmark]
    steps:
      - uses: actions/checkout@v4

      - uses: fractalyze/benchmark-action@v2
        with:
          benchmark_cmd: |
            cargo run --release -p my-bench -- --output=benchmark_results.json
          repo: my-repo
          device: cpu
          regression_threshold: "0.10"
          rolling_window: "5"
          cpu_load_threshold: "0.80"
          memory_threshold: "0.80"
          anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
          dashboard_token: ${{ secrets.DASHBOARD_TOKEN }}
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
