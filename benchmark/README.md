# Benchmark Results

This folder contains a reproducible benchmark for three file-oriented backends:

- `FilesystemBackend` from `deepagents`, scoped to a dedicated root directory with `virtual_mode=True`.
- `PostgresBackend` from this repository, backed by Dockerized PostgreSQL.
- `S3Backend` from this repository, backed by Dockerized MinIO.

## How to run

```bash
export PATH="$HOME/.local/bin:$PATH"
cd /home/runner/work/deepagents-backends/deepagents-backends
uv run python benchmark/run.py --manage-services --write-readme
```

## Methodology

- Warmup runs per scenario: `1`
- Measured runs per scenario: `5`
- Timings measure only the target operation; dataset setup is excluded.
- Filesystem paths are scoped to a dedicated benchmark root, so agent-visible paths stay within that root.
- PostgreSQL uses a dedicated benchmark table per run; MinIO uses a dedicated object prefix per run.

## Environment

- Generated at: `2026-04-16T16:02:52Z`
- Python: `3.12.3`
- Platform: `Linux-6.17.0-1010-azure-x86_64-with-glibc2.39`
- Machine: `x86_64`
- Docker managed by script: `True`

## Median latency by scenario

| Scenario | Filesystem (ms) | PostgreSQL (ms) | MinIO S3 (ms) | Fastest |
|---|---:|---:|---:|---|
| `write_small_text` | 0.242 | 2.430 | 60.744 | Filesystem |
| `read_medium_text` | 0.180 | 1.185 | 29.331 | Filesystem |
| `edit_medium_text` | 0.216 | 2.218 | 60.168 | Filesystem |
| `ls_flat_directory` | 10.970 | 2.176 | 41.091 | PostgreSQL |
| `glob_nested_python` | 12.981 | 1.708 | 41.416 | PostgreSQL |
| `grep_nested_literal` | 13.540 | 3.327 | 209.520 | PostgreSQL |
| `upload_binary_batch` | 3.432 | 9.264 | 89.492 | Filesystem |
| `download_binary_batch` | 2.424 | 7.370 | 70.115 | Filesystem |

## Scenario details

### `write_small_text`

Create a new 40-line text file in a nested directory.

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Samples (ms) |
|---|---:|---:|---:|---:|---|
| Filesystem | 0.242 | 0.247 | 0.230 | 0.270 | 0.256, 0.242, 0.270, 0.235, 0.230 |
| PostgreSQL | 2.430 | 2.676 | 1.841 | 4.078 | 3.004, 2.430, 2.030, 1.841, 4.078 |
| MinIO S3 | 60.744 | 61.701 | 59.090 | 68.279 | 59.492, 60.900, 59.090, 60.744, 68.279 |

### `read_medium_text`

Read a pre-populated 200-line text file.

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Samples (ms) |
|---|---:|---:|---:|---:|---|
| Filesystem | 0.180 | 0.178 | 0.172 | 0.181 | 0.180, 0.181, 0.172, 0.181, 0.177 |
| PostgreSQL | 1.185 | 1.188 | 1.152 | 1.258 | 1.189, 1.185, 1.157, 1.152, 1.258 |
| MinIO S3 | 29.331 | 29.214 | 28.720 | 29.411 | 29.331, 29.194, 29.411, 29.411, 28.720 |

### `edit_medium_text`

Replace one marker inside a pre-populated 200-line text file.

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Samples (ms) |
|---|---:|---:|---:|---:|---|
| Filesystem | 0.216 | 0.220 | 0.212 | 0.237 | 0.222, 0.216, 0.212, 0.213, 0.237 |
| PostgreSQL | 2.218 | 2.272 | 2.190 | 2.492 | 2.218, 2.207, 2.190, 2.253, 2.492 |
| MinIO S3 | 60.168 | 60.467 | 59.232 | 62.727 | 59.232, 62.727, 60.890, 59.318, 60.168 |

### `ls_flat_directory`

List a directory containing 100 direct child files.

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Samples (ms) |
|---|---:|---:|---:|---:|---|
| Filesystem | 10.970 | 10.999 | 10.920 | 11.121 | 11.013, 10.969, 10.970, 10.920, 11.121 |
| PostgreSQL | 2.176 | 2.249 | 2.039 | 2.673 | 2.039, 2.200, 2.158, 2.176, 2.673 |
| MinIO S3 | 41.091 | 57.365 | 40.708 | 121.116 | 41.091, 121.116, 40.801, 40.708, 43.108 |

### `glob_nested_python`

Glob for Python files inside a 5x12 nested tree plus 25 non-matches.

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Samples (ms) |
|---|---:|---:|---:|---:|---|
| Filesystem | 12.981 | 12.984 | 12.959 | 13.025 | 13.025, 12.981, 12.959, 12.986, 12.967 |
| PostgreSQL | 1.708 | 1.704 | 1.632 | 1.793 | 1.632, 1.736, 1.708, 1.652, 1.793 |
| MinIO S3 | 41.416 | 59.311 | 40.574 | 120.947 | 40.955, 40.574, 52.663, 120.947, 41.416 |

### `grep_nested_literal`

Search for a literal needle across 80 files with 20 matches.

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Samples (ms) |
|---|---:|---:|---:|---:|---|
| Filesystem | 13.540 | 13.825 | 12.153 | 16.350 | 16.350, 12.153, 13.540, 13.533, 13.548 |
| PostgreSQL | 3.327 | 3.681 | 3.296 | 5.096 | 5.096, 3.327, 3.304, 3.296, 3.380 |
| MinIO S3 | 209.520 | 209.109 | 207.376 | 210.145 | 208.835, 207.376, 209.520, 210.145, 209.667 |

### `upload_binary_batch`

Upload a batch of 20 binary files (4 KiB each).

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Samples (ms) |
|---|---:|---:|---:|---:|---|
| Filesystem | 3.432 | 3.426 | 3.379 | 3.464 | 3.432, 3.464, 3.414, 3.379, 3.441 |
| PostgreSQL | 9.264 | 9.373 | 8.875 | 9.912 | 9.912, 9.818, 8.997, 9.264, 8.875 |
| MinIO S3 | 89.492 | 89.104 | 87.806 | 89.840 | 88.551, 87.806, 89.492, 89.840, 89.829 |

### `download_binary_batch`

Download a batch of 20 pre-populated binary files (4 KiB each).

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Samples (ms) |
|---|---:|---:|---:|---:|---|
| Filesystem | 2.424 | 2.425 | 2.416 | 2.441 | 2.441, 2.427, 2.419, 2.424, 2.416 |
| PostgreSQL | 7.370 | 7.542 | 7.010 | 8.082 | 8.082, 8.032, 7.370, 7.010, 7.214 |
| MinIO S3 | 70.115 | 72.755 | 69.471 | 84.312 | 70.115, 70.158, 84.312, 69.718, 69.471 |

## Notes

- These numbers come from this sandbox VM and should be treated as comparative, not absolute throughput guarantees.
- The built-in filesystem backend is fastest for local single-host access, while PostgreSQL and MinIO trade latency for remote persistence semantics.
- Raw machine-readable results live in `benchmark/results/latest.json`.

