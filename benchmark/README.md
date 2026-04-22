# Benchmark Results

This folder contains a reproducible **realistic trace-based benchmark** for seven file-oriented backends:

- `FilesystemBackend` from `deepagents`, scoped to a dedicated root directory with `virtual_mode=True`.
- `PostgresBackend` from this repository, backed by Dockerized PostgreSQL.
- `S3Backend` from this repository, backed by Dockerized MinIO.
- `AzureBlobBackend` from this repository, backed by Dockerized Azurite.
- `GCSBackend` from this repository, backed by Dockerized fake-gcs-server.
- `MongoDBBackend` from this repository, backed by Dockerized MongoDB.
- `RedisBackend` from this repository, backed by Dockerized Valkey.

## How to run

From the repository root:

```bash
uv run python benchmark/run.py --manage-services --write-readme
```

## Methodology

Each benchmark run replays a **filesystem trace**: a fixed sequence of async backend operations (`aread`, `awrite`, `aedit`, `als_info`, `aglob_info`, `agrep_raw`, `aupload_files`, `adownload_files`) on a pre-populated fixture set.

- Warmup runs per trace: `1`
- Measured runs per trace: `3`
- Fixture setup is excluded from timing; only the trace steps are measured.
- Each run uses a unique path prefix so iterations are fully isolated.
- Outcome correctness is checked per step (expected vs. actual normalized outcome).

## Environment

- Generated at: `2026-04-21T23:56:29Z`
- Python: `3.12.3`
- Platform: `Linux-6.17.0-1010-azure-x86_64-with-glibc2.39`
- Machine: `x86_64`
- Docker managed by script: `True`

## Realistic replay suite

### Median total trace latency (ms)

| Trace | Shape | Fixture | Filesystem | PostgreSQL | MinIO S3 | Azure Blob | GCS | MongoDB | Redis/Valkey | Fastest |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `T01_short_ls_read` | short·linear | repo_like_small | 1.0 | 2.6 | 64.9 | 9.9 | 2.2 | 1.5 | 1.1 | Filesystem |
| `T02_short_glob_read` | short·discovery-heavy | repo_like_small | 2.0 | 4.3 | 98.1 | 12.0 | 3.7 | 2.5 | 1.5 | Redis/Valkey |
| `T03_short_upload_download` | short·linear | binary_artifact_mix | 0.7 | 2.3 | 64.8 | 8.3 | 2.8 | 1.9 | 0.9 | Filesystem |
| `T04_short_miss_recover` | short·retry-error | repo_like_small | 1.3 | 3.9 | 100.0 | 12.2 | 4.9 | 2.1 | 1.6 | Filesystem |
| `T05_medium_discover_edit` | medium·discovery-heavy | repo_like_small | 5.3 | 8.2 | 246.2 | 38.4 | 20.4 | 5.6 | 6.0 | Filesystem |
| `T06_medium_paginated_read_write` | medium·linear | data_workspace | 4.9 | 7.5 | 233.2 | 32.7 | 16.4 | 5.3 | 4.9 | Redis/Valkey |
| `T07_medium_multi_file_inspect` | medium·linear | data_workspace | 2.5 | 6.8 | 198.5 | 24.4 | 18.0 | 4.5 | 4.2 | Filesystem |
| `T08_medium_import_validate` | medium·linear | binary_artifact_mix | 3.7 | 7.3 | 204.7 | 45.1 | 31.5 | 9.4 | 5.8 | Filesystem |
| `T09_medium_verify_heavy` | medium·verification-heavy | repo_like_small | 4.9 | 7.2 | 241.3 | 42.0 | 26.1 | 5.4 | 6.4 | Filesystem |
| `T10_medium_deep_discover` | medium·linear | repo_like_medium_deep | 4.9 | 8.1 | 242.1 | 32.8 | 40.4 | 5.5 | 8.6 | Filesystem |
| `T11_medium_wide_grep` | medium·linear | wide_flat_tree | 17.0 | 6.9 | 421.2 | 308.3 | 83.9 | 5.8 | 29.1 | MongoDB |
| `T12_medium_data_aggregate` | medium·linear | data_workspace | 2.5 | 6.1 | 220.3 | 26.6 | 28.9 | 4.8 | 7.1 | Filesystem |
| `T13_medium_edit_verify` | medium·verification-heavy | repo_like_small | 4.0 | 5.8 | 210.8 | 40.1 | 33.8 | 4.7 | 8.5 | Filesystem |
| `T14_medium_miss_then_edit` | medium·retry-error | repo_like_small | 2.8 | 8.0 | 267.1 | 33.2 | 35.4 | 6.6 | 8.4 | Filesystem |
| `T15_long_multi_touch` | long·linear | repo_like_small | 9.6 | 14.0 | 489.0 | 76.3 | 89.1 | 11.8 | 21.2 | Filesystem |
| `T16_long_paginated_scan` | long·linear | data_workspace | 8.4 | 12.7 | 438.0 | 52.6 | 71.9 | 9.2 | 16.9 | Filesystem |
| `T17_long_import_export` | long·linear | binary_artifact_mix | 7.2 | 11.9 | 381.8 | 59.4 | 64.4 | 11.4 | 15.5 | Filesystem |
| `T18_long_deep_discover` | long·discovery-heavy | repo_like_medium_deep | 8.7 | 13.9 | 444.1 | 66.3 | 135.2 | 10.1 | 29.9 | Filesystem |
| `T19_long_wide_aggregate` | long·linear | wide_flat_tree | 36.5 | 10.7 | 514.4 | 337.4 | 130.2 | 8.9 | 41.8 | MongoDB |
| `T20_vlong_full_workflow` | vlong·verification-heavy | repo_like_small | 14.1 | 25.2 | 907.7 | 119.2 | 178.2 | 20.8 | 43.7 | Filesystem |

### Per-op latency summary (p50 across all traces, ms)

| Op | Filesystem | PostgreSQL | MinIO S3 | Azure Blob | GCS | MongoDB | Redis/Valkey |
|---|---:|---:|---:|---:|---:|---:|---:|
| `adownload_files` | 0.4 | 1.2 | 33.8 | 4.9 | 1.1 | 1.0 | 0.4 |
| `aedit` | 0.5 | 1.8 | 63.5 | 7.2 | 3.1 | 1.8 | 0.8 |
| `aglob_info` | 2.6 | 1.2 | 34.6 | 6.2 | 13.1 | 0.8 | 3.1 |
| `agrep_raw` | 2.4 | 1.2 | 68.7 | 51.6 | 22.7 | 0.8 | 6.7 |
| `als_info` | 1.9 | 1.6 | 35.0 | 7.1 | 11.6 | 0.8 | 2.6 |
| `aread` | 0.4 | 0.9 | 33.1 | 3.6 | 0.7 | 0.7 | 0.3 |
| `aupload_files` | 0.5 | 1.4 | 35.2 | 6.5 | 3.6 | 2.2 | 0.9 |
| `awrite` | 0.4 | 1.8 | 68.5 | 8.0 | 3.1 | 2.0 | 0.8 |

### Correctness pass rate

| Backend | Rate |
|---|---:|
| Filesystem | 95% |
| PostgreSQL | 75% |
| MinIO S3 | 95% |
| Azure Blob | 95% |
| GCS | 95% |
| MongoDB | 95% |
| Redis/Valkey | 95% |

## Trace details

### `T01_short_ls_read`

Shape: short·linear · Fixture: `repo_like_small` · Steps: 2

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Correct |
|---|---:|---:|---:|---:|---:|
| Filesystem | 1.0 | 1.0 | 0.8 | 1.3 | 100% |
| PostgreSQL | 2.6 | 2.7 | 2.6 | 2.8 | 100% |
| MinIO S3 | 64.9 | 64.6 | 63.7 | 65.1 | 100% |
| Azure Blob | 9.9 | 10.2 | 9.9 | 10.8 | 100% |
| GCS | 2.2 | 2.1 | 1.9 | 2.3 | 100% |
| MongoDB | 1.5 | 1.5 | 1.4 | 1.5 | 100% |
| Redis/Valkey | 1.1 | 1.1 | 1.0 | 1.1 | 100% |

### `T02_short_glob_read`

Shape: short·discovery-heavy · Fixture: `repo_like_small` · Steps: 3

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Correct |
|---|---:|---:|---:|---:|---:|
| Filesystem | 2.0 | 2.0 | 2.0 | 2.1 | 100% |
| PostgreSQL | 4.3 | 4.0 | 3.1 | 4.6 | 100% |
| MinIO S3 | 98.1 | 97.1 | 94.3 | 99.0 | 100% |
| Azure Blob | 12.0 | 12.8 | 12.0 | 14.5 | 100% |
| GCS | 3.7 | 3.7 | 3.6 | 3.7 | 100% |
| MongoDB | 2.5 | 2.7 | 2.4 | 3.1 | 100% |
| Redis/Valkey | 1.5 | 1.5 | 1.5 | 1.5 | 100% |

### `T03_short_upload_download`

Shape: short·linear · Fixture: `binary_artifact_mix` · Steps: 2

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Correct |
|---|---:|---:|---:|---:|---:|
| Filesystem | 0.7 | 0.7 | 0.6 | 0.7 | 100% |
| PostgreSQL | 2.3 | 2.2 | 2.1 | 2.3 | 100% |
| MinIO S3 | 64.8 | 68.8 | 64.2 | 77.5 | 100% |
| Azure Blob | 8.3 | 8.4 | 7.7 | 9.1 | 100% |
| GCS | 2.8 | 3.0 | 2.8 | 3.3 | 100% |
| MongoDB | 1.9 | 1.9 | 1.9 | 2.0 | 100% |
| Redis/Valkey | 0.9 | 0.9 | 0.8 | 0.9 | 100% |

### `T04_short_miss_recover`

Shape: short·retry-error · Fixture: `repo_like_small` · Steps: 3

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Correct |
|---|---:|---:|---:|---:|---:|
| Filesystem | 1.3 | 1.3 | 1.3 | 1.3 | 100% |
| PostgreSQL | 3.9 | 4.0 | 3.9 | 4.3 | 100% |
| MinIO S3 | 100.0 | 99.4 | 97.7 | 100.4 | 100% |
| Azure Blob | 12.2 | 11.9 | 11.2 | 12.3 | 100% |
| GCS | 4.9 | 5.0 | 4.9 | 5.3 | 100% |
| MongoDB | 2.1 | 2.2 | 2.0 | 2.4 | 100% |
| Redis/Valkey | 1.6 | 1.6 | 1.6 | 1.7 | 100% |

### `T05_medium_discover_edit`

Shape: medium·discovery-heavy · Fixture: `repo_like_small` · Steps: 6

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Correct |
|---|---:|---:|---:|---:|---:|
| Filesystem | 5.3 | 5.4 | 5.3 | 5.4 | 100% |
| PostgreSQL | 8.2 | 8.4 | 8.1 | 8.9 | 100% |
| MinIO S3 | 246.2 | 266.4 | 231.0 | 322.0 | 100% |
| Azure Blob | 38.4 | 41.5 | 38.0 | 48.1 | 100% |
| GCS | 20.4 | 20.0 | 19.1 | 20.6 | 100% |
| MongoDB | 5.6 | 5.6 | 5.4 | 5.7 | 100% |
| Redis/Valkey | 6.0 | 6.3 | 5.9 | 7.1 | 100% |

### `T06_medium_paginated_read_write`

Shape: medium·linear · Fixture: `data_workspace` · Steps: 6

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Correct |
|---|---:|---:|---:|---:|---:|
| Filesystem | 4.9 | 4.7 | 4.3 | 5.0 | 100% |
| PostgreSQL | 7.5 | 7.5 | 7.4 | 7.7 | 100% |
| MinIO S3 | 233.2 | 233.1 | 230.8 | 235.4 | 100% |
| Azure Blob | 32.7 | 32.2 | 29.0 | 35.0 | 100% |
| GCS | 16.4 | 16.4 | 16.2 | 16.5 | 100% |
| MongoDB | 5.3 | 5.3 | 5.2 | 5.4 | 100% |
| Redis/Valkey | 4.9 | 4.9 | 4.8 | 5.1 | 100% |

### `T07_medium_multi_file_inspect`

Shape: medium·linear · Fixture: `data_workspace` · Steps: 5

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Correct |
|---|---:|---:|---:|---:|---:|
| Filesystem | 2.5 | 2.5 | 2.5 | 2.6 | 100% |
| PostgreSQL | 6.8 | 6.8 | 6.7 | 6.9 | 100% |
| MinIO S3 | 198.5 | 205.2 | 195.6 | 221.5 | 100% |
| Azure Blob | 24.4 | 25.2 | 24.1 | 27.0 | 100% |
| GCS | 18.0 | 18.7 | 17.6 | 20.5 | 100% |
| MongoDB | 4.5 | 4.6 | 4.5 | 4.8 | 100% |
| Redis/Valkey | 4.2 | 4.2 | 3.9 | 4.4 | 100% |

### `T08_medium_import_validate`

Shape: medium·linear · Fixture: `binary_artifact_mix` · Steps: 5

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Correct |
|---|---:|---:|---:|---:|---:|
| Filesystem | 3.7 | 3.9 | 3.7 | 4.2 | 100% |
| PostgreSQL | 7.3 | 7.3 | 6.9 | 7.7 | 0% |
| MinIO S3 | 204.7 | 208.4 | 201.7 | 218.7 | 100% |
| Azure Blob | 45.1 | 46.6 | 41.3 | 53.4 | 100% |
| GCS | 31.5 | 29.7 | 25.5 | 32.1 | 100% |
| MongoDB | 9.4 | 9.3 | 8.1 | 10.5 | 100% |
| Redis/Valkey | 5.8 | 5.9 | 5.8 | 6.0 | 100% |

### `T09_medium_verify_heavy`

Shape: medium·verification-heavy · Fixture: `repo_like_small` · Steps: 6

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Correct |
|---|---:|---:|---:|---:|---:|
| Filesystem | 4.9 | 5.1 | 4.4 | 5.9 | 100% |
| PostgreSQL | 7.2 | 7.1 | 6.8 | 7.4 | 100% |
| MinIO S3 | 241.3 | 240.7 | 237.5 | 243.4 | 100% |
| Azure Blob | 42.0 | 40.3 | 36.5 | 42.5 | 100% |
| GCS | 26.1 | 26.6 | 25.6 | 28.3 | 100% |
| MongoDB | 5.4 | 5.4 | 5.2 | 5.7 | 100% |
| Redis/Valkey | 6.4 | 6.3 | 6.0 | 6.5 | 100% |

### `T10_medium_deep_discover`

Shape: medium·linear · Fixture: `repo_like_medium_deep` · Steps: 6

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Correct |
|---|---:|---:|---:|---:|---:|
| Filesystem | 4.9 | 4.9 | 4.6 | 5.1 | 100% |
| PostgreSQL | 8.1 | 8.2 | 7.7 | 8.9 | 100% |
| MinIO S3 | 242.1 | 243.9 | 239.7 | 249.8 | 100% |
| Azure Blob | 32.8 | 32.7 | 31.9 | 33.6 | 100% |
| GCS | 40.4 | 40.5 | 38.6 | 42.6 | 100% |
| MongoDB | 5.5 | 5.6 | 5.4 | 6.0 | 100% |
| Redis/Valkey | 8.6 | 8.5 | 8.4 | 8.7 | 100% |

### `T11_medium_wide_grep`

Shape: medium·linear · Fixture: `wide_flat_tree` · Steps: 5

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Correct |
|---|---:|---:|---:|---:|---:|
| Filesystem | 17.0 | 17.0 | 16.7 | 17.2 | 100% |
| PostgreSQL | 6.9 | 6.9 | 6.9 | 7.0 | 100% |
| MinIO S3 | 421.2 | 458.6 | 387.8 | 566.7 | 100% |
| Azure Blob | 308.3 | 317.0 | 306.4 | 336.2 | 100% |
| GCS | 83.9 | 82.8 | 80.6 | 84.0 | 100% |
| MongoDB | 5.8 | 5.9 | 5.6 | 6.1 | 100% |
| Redis/Valkey | 29.1 | 28.9 | 28.6 | 29.1 | 100% |

### `T12_medium_data_aggregate`

Shape: medium·linear · Fixture: `data_workspace` · Steps: 5

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Correct |
|---|---:|---:|---:|---:|---:|
| Filesystem | 2.5 | 2.5 | 2.4 | 2.6 | 100% |
| PostgreSQL | 6.1 | 6.1 | 5.9 | 6.2 | 100% |
| MinIO S3 | 220.3 | 218.9 | 207.6 | 228.8 | 100% |
| Azure Blob | 26.6 | 27.4 | 22.5 | 33.0 | 100% |
| GCS | 28.9 | 28.8 | 28.3 | 29.4 | 100% |
| MongoDB | 4.8 | 4.8 | 4.6 | 4.9 | 100% |
| Redis/Valkey | 7.1 | 7.1 | 6.9 | 7.2 | 100% |

### `T13_medium_edit_verify`

Shape: medium·verification-heavy · Fixture: `repo_like_small` · Steps: 5

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Correct |
|---|---:|---:|---:|---:|---:|
| Filesystem | 4.0 | 4.7 | 4.0 | 6.2 | 100% |
| PostgreSQL | 5.8 | 5.8 | 5.6 | 6.0 | 100% |
| MinIO S3 | 210.8 | 231.0 | 207.1 | 275.2 | 100% |
| Azure Blob | 40.1 | 43.9 | 37.2 | 54.4 | 100% |
| GCS | 33.8 | 34.7 | 33.1 | 37.1 | 100% |
| MongoDB | 4.7 | 4.7 | 4.5 | 5.0 | 100% |
| Redis/Valkey | 8.5 | 8.5 | 8.5 | 8.6 | 100% |

### `T14_medium_miss_then_edit`

Shape: medium·retry-error · Fixture: `repo_like_small` · Steps: 6

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Correct |
|---|---:|---:|---:|---:|---:|
| Filesystem | 2.8 | 2.8 | 2.8 | 2.9 | 100% |
| PostgreSQL | 8.0 | 7.9 | 7.8 | 8.0 | 100% |
| MinIO S3 | 267.1 | 267.9 | 267.0 | 269.6 | 100% |
| Azure Blob | 33.2 | 34.1 | 31.4 | 37.8 | 100% |
| GCS | 35.4 | 35.9 | 35.0 | 37.2 | 100% |
| MongoDB | 6.6 | 6.7 | 6.6 | 6.8 | 100% |
| Redis/Valkey | 8.4 | 8.4 | 8.3 | 8.5 | 100% |

### `T15_long_multi_touch`

Shape: long·linear · Fixture: `repo_like_small` · Steps: 11

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Correct |
|---|---:|---:|---:|---:|---:|
| Filesystem | 9.6 | 9.6 | 9.4 | 9.9 | 100% |
| PostgreSQL | 14.0 | 14.1 | 13.7 | 14.6 | 100% |
| MinIO S3 | 489.0 | 548.8 | 483.2 | 674.1 | 100% |
| Azure Blob | 76.3 | 76.0 | 74.9 | 76.7 | 100% |
| GCS | 89.1 | 89.8 | 87.1 | 93.3 | 100% |
| MongoDB | 11.8 | 11.7 | 11.5 | 11.8 | 100% |
| Redis/Valkey | 21.2 | 21.3 | 21.0 | 21.5 | 100% |

### `T16_long_paginated_scan`

Shape: long·linear · Fixture: `data_workspace` · Steps: 12

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Correct |
|---|---:|---:|---:|---:|---:|
| Filesystem | 8.4 | 8.2 | 7.7 | 8.4 | 0% |
| PostgreSQL | 12.7 | 12.8 | 12.7 | 13.2 | 0% |
| MinIO S3 | 438.0 | 451.3 | 437.9 | 478.1 | 0% |
| Azure Blob | 52.6 | 55.4 | 50.8 | 62.8 | 0% |
| GCS | 71.9 | 72.3 | 71.6 | 73.3 | 0% |
| MongoDB | 9.2 | 9.3 | 9.0 | 9.5 | 0% |
| Redis/Valkey | 16.9 | 16.9 | 16.7 | 17.2 | 0% |

### `T17_long_import_export`

Shape: long·linear · Fixture: `binary_artifact_mix` · Steps: 9

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Correct |
|---|---:|---:|---:|---:|---:|
| Filesystem | 7.2 | 7.5 | 6.9 | 8.4 | 100% |
| PostgreSQL | 11.9 | 12.6 | 11.9 | 14.0 | 0% |
| MinIO S3 | 381.8 | 383.1 | 379.2 | 388.3 | 100% |
| Azure Blob | 59.4 | 58.4 | 55.4 | 60.4 | 100% |
| GCS | 64.4 | 64.3 | 63.6 | 65.0 | 100% |
| MongoDB | 11.4 | 11.4 | 11.3 | 11.6 | 100% |
| Redis/Valkey | 15.5 | 15.6 | 15.4 | 16.0 | 100% |

### `T18_long_deep_discover`

Shape: long·discovery-heavy · Fixture: `repo_like_medium_deep` · Steps: 11

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Correct |
|---|---:|---:|---:|---:|---:|
| Filesystem | 8.7 | 8.6 | 8.4 | 8.8 | 100% |
| PostgreSQL | 13.9 | 13.7 | 13.1 | 14.0 | 100% |
| MinIO S3 | 444.1 | 443.9 | 442.4 | 445.2 | 100% |
| Azure Blob | 66.3 | 70.4 | 61.6 | 83.3 | 100% |
| GCS | 135.2 | 135.3 | 134.5 | 136.3 | 100% |
| MongoDB | 10.1 | 11.9 | 10.1 | 15.5 | 100% |
| Redis/Valkey | 29.9 | 30.6 | 28.6 | 33.3 | 100% |

### `T19_long_wide_aggregate`

Shape: long·linear · Fixture: `wide_flat_tree` · Steps: 8

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Correct |
|---|---:|---:|---:|---:|---:|
| Filesystem | 36.5 | 36.4 | 36.0 | 36.7 | 100% |
| PostgreSQL | 10.7 | 10.7 | 10.6 | 10.9 | 0% |
| MinIO S3 | 514.4 | 522.9 | 506.9 | 547.3 | 100% |
| Azure Blob | 337.4 | 341.5 | 332.1 | 354.9 | 100% |
| GCS | 130.2 | 132.2 | 121.6 | 144.8 | 100% |
| MongoDB | 8.9 | 8.8 | 8.6 | 9.0 | 100% |
| Redis/Valkey | 41.8 | 45.4 | 38.8 | 55.8 | 100% |

### `T20_vlong_full_workflow`

Shape: vlong·verification-heavy · Fixture: `repo_like_small` · Steps: 20

| Backend | Median (ms) | Mean (ms) | Min (ms) | Max (ms) | Correct |
|---|---:|---:|---:|---:|---:|
| Filesystem | 14.1 | 14.3 | 13.6 | 15.2 | 100% |
| PostgreSQL | 25.2 | 24.8 | 24.0 | 25.3 | 0% |
| MinIO S3 | 907.7 | 905.3 | 856.7 | 951.6 | 100% |
| Azure Blob | 119.2 | 119.1 | 116.3 | 121.8 | 100% |
| GCS | 178.2 | 178.1 | 176.5 | 179.6 | 100% |
| MongoDB | 20.8 | 20.9 | 20.8 | 21.1 | 100% |
| Redis/Valkey | 43.7 | 43.9 | 43.2 | 44.7 | 100% |

## Notes

- These numbers come from the benchmark VM and should be treated as comparative, not absolute throughput guarantees.
- The built-in filesystem backend is the local baseline; the remote backends trade latency for different persistence semantics.
- Raw machine-readable results live in `benchmark/results/latest.json`.
- The interactive dashboard source lives in `benchmark/dashboard/` and is compiled into `benchmark/web/` for static publishing.
