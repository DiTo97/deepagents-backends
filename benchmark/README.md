# Benchmark Results

This folder contains a reproducible benchmark for seven file-oriented backends:

- `FilesystemBackend` from `deepagents`, scoped to a dedicated root directory with `virtual_mode=True`.
- `PostgresBackend` from this repository, backed by Dockerized PostgreSQL.
- `S3Backend` from this repository, backed by Dockerized MinIO.
- `AzureBlobBackend` from this repository, backed by Dockerized Azurite.
- `GCSBackend` from this repository, backed by Dockerized fake-gcs-server.
- `MongoDBBackend` from this repository, backed by Dockerized MongoDB.
- `RedisBackend` from this repository, backed by Dockerized Valkey.

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
- Azure Blob, GCS, and Redis use dedicated prefixes/namespaces per run; MongoDB uses a dedicated collection per run.

## Environment

- Generated at: `2026-04-17T07:52:07Z`
- Python: `3.12.3`
- Platform: `Linux-6.17.0-1010-azure-x86_64-with-glibc2.39`
- Machine: `x86_64`
- Docker managed by script: `True`

## Median latency by scenario

| Scenario | Filesystem (ms) | PostgreSQL (ms) | MinIO S3 (ms) | Azure Blob (ms) | GCS (ms) | MongoDB (ms) | Redis/Valkey (ms) | Fastest |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `write_small_text` | 0.266 | 2.254 | 57.611 | 10.865 | 3.039 | 5.945 | 2.234 | Filesystem |
| `read_medium_text` | 0.224 | 1.123 | 36.778 | 4.611 | 1.362 | 4.739 | 1.797 | Filesystem |
| `edit_medium_text` | 0.281 | 2.165 | 57.034 | 9.966 | 3.214 | 5.988 | 2.231 | Filesystem |
| `ls_flat_directory` | 10.098 | 2.320 | 37.323 | 43.538 | 11.194 | 6.124 | 4.455 | PostgreSQL |
| `glob_nested_python` | 12.095 | 1.744 | 37.732 | 23.299 | 17.105 | 6.236 | 6.004 | PostgreSQL |
| `grep_nested_literal` | 10.199 | 3.201 | 205.851 | 280.130 | 73.849 | 10.231 | 29.217 | PostgreSQL |
| `upload_binary_batch` | 2.848 | 9.470 | 95.780 | 70.942 | 46.315 | 38.636 | 11.984 | Filesystem |
| `download_binary_batch` | 2.113 | 7.177 | 70.131 | 57.880 | 13.377 | 17.582 | 6.338 | Filesystem |

## Scenario details

### `write_small_text`

Create a new 40-line text file in a nested directory.

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Samples (ms) |
|---|---:|---:|---:|---:|---|
| Filesystem | 0.266 | 0.268 | 0.215 | 0.332 | 0.266, 0.223, 0.215, 0.332, 0.303 |
| PostgreSQL | 2.254 | 2.402 | 1.937 | 3.080 | 3.080, 2.578, 2.254, 2.160, 1.937 |
| MinIO S3 | 57.611 | 58.950 | 56.554 | 64.292 | 56.554, 57.611, 57.284, 59.010, 64.292 |
| Azure Blob | 10.865 | 10.345 | 8.082 | 11.485 | 11.147, 10.865, 10.146, 11.485, 8.082 |
| GCS | 3.039 | 3.046 | 2.963 | 3.155 | 3.058, 3.155, 3.039, 3.018, 2.963 |
| MongoDB | 5.945 | 5.963 | 5.897 | 6.080 | 5.957, 6.080, 5.933, 5.897, 5.945 |
| Redis/Valkey | 2.234 | 2.623 | 2.165 | 3.332 | 2.234, 2.182, 3.332, 2.165, 3.205 |

### `read_medium_text`

Read a pre-populated 200-line text file.

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Samples (ms) |
|---|---:|---:|---:|---:|---|
| Filesystem | 0.224 | 0.226 | 0.216 | 0.241 | 0.223, 0.224, 0.241, 0.216, 0.227 |
| PostgreSQL | 1.123 | 1.187 | 1.091 | 1.439 | 1.169, 1.091, 1.123, 1.115, 1.439 |
| MinIO S3 | 36.778 | 33.986 | 27.724 | 39.184 | 39.184, 37.947, 27.724, 28.297, 36.778 |
| Azure Blob | 4.611 | 4.617 | 4.310 | 5.053 | 4.611, 4.764, 5.053, 4.347, 4.310 |
| GCS | 1.362 | 1.349 | 1.300 | 1.373 | 1.362, 1.343, 1.300, 1.368, 1.373 |
| MongoDB | 4.739 | 5.266 | 4.356 | 7.715 | 4.356, 4.845, 4.739, 4.677, 7.715 |
| Redis/Valkey | 1.797 | 2.059 | 1.714 | 3.186 | 3.186, 1.874, 1.797, 1.724, 1.714 |

### `edit_medium_text`

Replace one marker inside a pre-populated 200-line text file.

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Samples (ms) |
|---|---:|---:|---:|---:|---|
| Filesystem | 0.281 | 0.282 | 0.271 | 0.295 | 0.295, 0.273, 0.292, 0.271, 0.281 |
| PostgreSQL | 2.165 | 2.200 | 1.981 | 2.570 | 2.165, 2.205, 2.077, 1.981, 2.570 |
| MinIO S3 | 57.034 | 58.413 | 56.037 | 64.929 | 64.929, 57.034, 56.037, 56.978, 57.088 |
| Azure Blob | 9.966 | 10.213 | 8.933 | 11.974 | 10.459, 8.933, 9.966, 9.732, 11.974 |
| GCS | 3.214 | 3.192 | 3.065 | 3.316 | 3.214, 3.065, 3.146, 3.218, 3.316 |
| MongoDB | 5.988 | 5.987 | 5.732 | 6.144 | 5.732, 6.144, 5.961, 5.988, 6.112 |
| Redis/Valkey | 2.231 | 2.246 | 2.093 | 2.452 | 2.272, 2.181, 2.093, 2.231, 2.452 |

### `ls_flat_directory`

List a directory containing 100 direct child files.

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Samples (ms) |
|---|---:|---:|---:|---:|---|
| Filesystem | 10.098 | 10.334 | 10.074 | 11.097 | 10.303, 11.097, 10.098, 10.094, 10.074 |
| PostgreSQL | 2.320 | 2.472 | 2.294 | 2.945 | 2.320, 2.296, 2.294, 2.505, 2.945 |
| MinIO S3 | 37.323 | 38.738 | 37.043 | 43.229 | 38.915, 37.180, 37.043, 37.323, 43.229 |
| Azure Blob | 43.538 | 56.827 | 27.326 | 130.240 | 45.809, 37.222, 43.538, 27.326, 130.240 |
| GCS | 11.194 | 11.050 | 8.802 | 12.469 | 8.802, 11.194, 10.901, 11.882, 12.469 |
| MongoDB | 6.124 | 7.053 | 5.828 | 9.166 | 9.166, 5.828, 8.299, 5.847, 6.124 |
| Redis/Valkey | 4.455 | 4.469 | 4.096 | 4.974 | 4.096, 4.286, 4.455, 4.534, 4.974 |

### `glob_nested_python`

Glob for Python files inside a 5x12 nested tree plus 25 non-matches.

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Samples (ms) |
|---|---:|---:|---:|---:|---|
| Filesystem | 12.095 | 12.130 | 11.981 | 12.361 | 12.095, 12.134, 12.080, 12.361, 11.981 |
| PostgreSQL | 1.744 | 1.810 | 1.708 | 2.045 | 2.045, 1.744, 1.735, 1.708, 1.819 |
| MinIO S3 | 37.732 | 37.478 | 36.321 | 38.703 | 38.039, 37.732, 38.703, 36.321, 36.594 |
| Azure Blob | 23.299 | 24.086 | 23.030 | 26.700 | 23.030, 23.299, 24.137, 26.700, 23.264 |
| GCS | 17.105 | 17.664 | 14.857 | 20.914 | 14.857, 16.309, 20.914, 17.105, 19.137 |
| MongoDB | 6.236 | 6.077 | 5.117 | 7.641 | 7.641, 5.117, 6.248, 6.236, 5.142 |
| Redis/Valkey | 6.004 | 6.230 | 5.831 | 7.039 | 5.831, 5.851, 6.004, 6.424, 7.039 |

### `grep_nested_literal`

Search for a literal needle across 80 files with 20 matches.

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Samples (ms) |
|---|---:|---:|---:|---:|---|
| Filesystem | 10.199 | 10.377 | 10.062 | 11.131 | 10.199, 10.356, 10.137, 10.062, 11.131 |
| PostgreSQL | 3.201 | 3.543 | 3.019 | 4.701 | 4.701, 3.122, 3.019, 3.201, 3.671 |
| MinIO S3 | 205.851 | 206.135 | 204.251 | 208.327 | 205.851, 205.840, 208.327, 204.251, 206.406 |
| Azure Blob | 280.130 | 275.147 | 259.710 | 292.454 | 292.454, 282.467, 260.971, 280.130, 259.710 |
| GCS | 73.849 | 74.760 | 72.262 | 79.051 | 72.262, 73.452, 73.849, 75.184, 79.051 |
| MongoDB | 10.231 | 9.519 | 6.890 | 10.994 | 6.890, 10.994, 10.330, 9.149, 10.231 |
| Redis/Valkey | 29.217 | 29.708 | 28.667 | 31.251 | 29.217, 28.667, 29.156, 30.249, 31.251 |

### `upload_binary_batch`

Upload a batch of 20 binary files (4 KiB each).

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Samples (ms) |
|---|---:|---:|---:|---:|---|
| Filesystem | 2.848 | 2.853 | 2.826 | 2.898 | 2.898, 2.864, 2.848, 2.829, 2.826 |
| PostgreSQL | 9.470 | 10.165 | 8.932 | 13.131 | 13.131, 10.030, 9.263, 8.932, 9.470 |
| MinIO S3 | 95.780 | 94.477 | 86.616 | 104.116 | 86.694, 104.116, 99.179, 95.780, 86.616 |
| Azure Blob | 70.942 | 74.119 | 69.393 | 82.820 | 70.942, 69.393, 82.820, 77.458, 69.979 |
| GCS | 46.315 | 47.518 | 41.556 | 59.596 | 41.556, 59.596, 42.050, 46.315, 48.074 |
| MongoDB | 38.636 | 38.166 | 31.570 | 44.789 | 43.621, 44.789, 38.636, 31.570, 32.213 |
| Redis/Valkey | 11.984 | 12.513 | 11.826 | 14.765 | 11.955, 12.034, 14.765, 11.984, 11.826 |

### `download_binary_batch`

Download a batch of 20 pre-populated binary files (4 KiB each).

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Samples (ms) |
|---|---:|---:|---:|---:|---|
| Filesystem | 2.113 | 2.114 | 2.098 | 2.136 | 2.116, 2.136, 2.113, 2.108, 2.098 |
| PostgreSQL | 7.177 | 7.302 | 6.662 | 8.260 | 7.394, 8.260, 7.015, 7.177, 6.662 |
| MinIO S3 | 70.131 | 74.797 | 68.754 | 83.500 | 82.322, 83.500, 69.278, 70.131, 68.754 |
| Azure Blob | 57.880 | 58.775 | 56.348 | 63.684 | 59.609, 57.880, 56.352, 56.348, 63.684 |
| GCS | 13.377 | 14.152 | 13.350 | 16.340 | 16.340, 13.377, 13.364, 13.350, 14.327 |
| MongoDB | 17.582 | 18.229 | 17.031 | 20.858 | 17.355, 17.031, 18.321, 17.582, 20.858 |
| Redis/Valkey | 6.338 | 6.317 | 5.781 | 6.705 | 6.338, 6.471, 5.781, 6.292, 6.705 |

## Notes

- These numbers come from this sandbox VM and should be treated as comparative, not absolute throughput guarantees.
- The built-in filesystem backend remains the local baseline, while the remote backends trade latency for different persistence semantics.
- Raw machine-readable results live in `benchmark/results/latest.json`.

