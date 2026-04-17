# 🗄️ Deep Agents Remote Backends

**deepagents-backends** provides remote `BackendProtocol` implementations for [LangChain Deep Agents](https://github.com/langchain-ai/deepagents), so agent file state can live outside local ephemeral storage.

Supported backends:

- S3 / MinIO
- PostgreSQL
- Azure Blob Storage / Azurite
- Google Cloud Storage / fake-gcs-server
- MongoDB
- Redis / Valkey

## 🚀 Install

```bash
pip install deepagents-backends
```

For development:

```bash
uv sync
```

## ✅ Supported backends

| Backend | Best fit | Docs |
|---|---|---|
| S3Backend | Object storage, blobs, shared assets | [wiki/S3.md](https://github.com/DiTo97/deepagents-backends/blob/main/wiki/S3.md) |
| PostgresBackend | Relational persistence with pooling | [wiki/PostgreSQL.md](https://github.com/DiTo97/deepagents-backends/blob/main/wiki/PostgreSQL.md) |
| AzureBlobBackend | Azure-native blob storage | [wiki/Azure-Blob.md](https://github.com/DiTo97/deepagents-backends/blob/main/wiki/Azure-Blob.md) |
| GCSBackend | Google Cloud Storage-compatible object storage | [wiki/GCS.md](https://github.com/DiTo97/deepagents-backends/blob/main/wiki/GCS.md) |
| MongoDBBackend | Document-oriented persistence | [wiki/MongoDB.md](https://github.com/DiTo97/deepagents-backends/blob/main/wiki/MongoDB.md) |
| RedisBackend | Fast key-value persistence / Valkey | [wiki/Redis-Valkey.md](https://github.com/DiTo97/deepagents-backends/blob/main/wiki/Redis-Valkey.md) |
| All backend docs | Index page | [wiki/README.md](https://github.com/DiTo97/deepagents-backends/blob/main/wiki/README.md) |

## ⚡ Quickstart

### S3 / MinIO

```python
from deepagents_backends import S3Backend, S3Config

backend = S3Backend(
    S3Config(
        bucket="my-agent-bucket",
        prefix="agent-workspace",
        endpoint_url="http://localhost:9000",
        access_key_id="minioadmin",
        secret_access_key="minioadmin",
        use_ssl=False,
    )
)
```

### PostgreSQL

```python
from deepagents_backends import PostgresBackend, PostgresConfig

backend = PostgresBackend(
    PostgresConfig(
        host="localhost",
        port=5432,
        database="deepagents",
        user="postgres",
        password="postgres",
        table="agent_files",
    )
)

await backend.initialize()
try:
    ...
finally:
    await backend.close()
```

For Azure Blob, GCS, MongoDB, and Redis/Valkey examples and lifecycle details, use the wiki pages above.

## 🔧 Backend protocol coverage

All backends implement:

| Method | Description |
|---|---|
| `read` / `aread` | Read file content with offset/limit pagination |
| `write` / `awrite` | Create a new file and fail if it already exists |
| `edit` / `aedit` | Replace text using Deep Agents string replacement semantics |
| `ls_info` / `als_info` | List directory contents |
| `glob_info` / `aglob_info` | Find files matching a glob |
| `grep_raw` / `agrep_raw` | Search files with line-numbered results |
| `upload_files` / `aupload_files` | Upload raw bytes |
| `download_files` / `adownload_files` | Download raw bytes |

### Storage format

Text-oriented files are stored as JSON with line arrays:

```json
{
  "content": ["line 1", "line 2", "line 3"],
  "created_at": "2025-01-07T12:00:00Z",
  "modified_at": "2025-01-07T12:30:00Z"
}
```

## 📚 Repository resources

| Resource | Link |
|---|---|
| Source module | [src/deepagents_backends/__init__.py](https://github.com/DiTo97/deepagents-backends/blob/main/src/deepagents_backends/__init__.py) |
| Docker services | [docker-compose.yml](https://github.com/DiTo97/deepagents-backends/blob/main/docker-compose.yml) |
| Benchmark report | [benchmark/README.md](https://github.com/DiTo97/deepagents-backends/blob/main/benchmark/README.md) |
| Benchmark JSON results | [benchmark/results/latest.json](https://github.com/DiTo97/deepagents-backends/blob/main/benchmark/results/latest.json) |
| Contributor notes | [CLAUDE.md](https://github.com/DiTo97/deepagents-backends/blob/main/CLAUDE.md) |

## 📚 Examples

| Example | Description |
|---|---|
| [examples/s3_deep_agent.py](https://github.com/DiTo97/deepagents-backends/blob/main/examples/s3_deep_agent.py) | Full S3 backend with streaming and custom tools |
| [examples/postgres_deep_agent.py](https://github.com/DiTo97/deepagents-backends/blob/main/examples/postgres_deep_agent.py) | PostgreSQL with multi-agent workflows |
| [examples/composite_backend.py](https://github.com/DiTo97/deepagents-backends/blob/main/examples/composite_backend.py) | Hybrid S3 + PostgreSQL routing |
| [examples/basic_usage.py](https://github.com/DiTo97/deepagents-backends/blob/main/examples/basic_usage.py) | Low-level backend API operations |

## 🧪 Development

```bash
# Install dependencies
uv sync

# Unit tests
uv run pytest -m unit

# Integration tests
uv run pytest -m integration

# Backend-specific integration subsets
uv run pytest -m "integration and azure"
uv run pytest -m "integration and gcs"
uv run pytest -m "integration and mongodb"
uv run pytest -m "integration and redis"

# Lint
uv run ruff check .

# Benchmarks
uv run python benchmark/run.py --manage-services --write-readme
```

### Local Docker services

| Service | Port | Notes |
|---|---:|---|
| MinIO | 9000 | S3-compatible storage |
| MinIO Console | 9001 | MinIO UI |
| PostgreSQL | 5432 | `postgres/postgres`, DB `deepagents_test` |
| Azurite Blob | 10000 | Azure Blob emulator |
| fake-gcs-server | 4443 | GCS emulator |
| MongoDB | 27017 | Document store |
| Valkey | 6379 | Redis-compatible store |

## 🔒 Security

- Prefer environment variables, IAM roles, managed identities, or workload identity instead of hard-coded credentials.
- Use TLS in production (`use_ssl=True`, `sslmode="require"`, HTTPS endpoints).
- `PostgresBackend`, `MongoDBBackend`, and `RedisBackend` keep network clients open; close them cleanly when lifecycle methods require it.

## 📄 License

MIT License — see [LICENSE](https://github.com/DiTo97/deepagents-backends/blob/main/LICENSE).
