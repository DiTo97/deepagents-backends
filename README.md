# 🗄️ Deep Agents Remote Backends

**deepagents-backends** provides production-ready implementations of the [LangChain Deep Agents](https://github.com/langchain-ai/deepagents)' `BackendProtocol` for remote file storage, allowing your agents to maintain state across restarts and share files in distributed environments.

Store agent files in **S3**, **PostgreSQL**, **Azure Blob**, **GCS**, **MongoDB**, or **Redis/Valkey** instead of ephemeral state, enabling persistent storage, distributed execution, and multi-agent file sharing.

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
| S3Backend | Object storage, blobs, shared assets | [wiki/s3.md](https://github.com/DiTo97/deepagents-backends/blob/main/wiki/s3.md) |
| PostgresBackend | Relational persistence with pooling | [wiki/postgresql.md](https://github.com/DiTo97/deepagents-backends/blob/main/wiki/postgresql.md) |
| AzureBlobBackend | Azure-native blob storage | [wiki/azure-blob.md](https://github.com/DiTo97/deepagents-backends/blob/main/wiki/azure-blob.md) |
| GCSBackend | Google Cloud Storage-compatible object storage | [wiki/gcs.md](https://github.com/DiTo97/deepagents-backends/blob/main/wiki/gcs.md) |
| MongoDBBackend | Document-oriented persistence | [wiki/mongodb.md](https://github.com/DiTo97/deepagents-backends/blob/main/wiki/mongodb.md) |
| RedisBackend | Fast key-value persistence / Valkey | [wiki/redis-valkey.md](https://github.com/DiTo97/deepagents-backends/blob/main/wiki/redis-valkey.md) |

## ⚡ Quickstart

### S3 / MinIO

Store agent files in AWS S3 or any S3-compatible storage (MinIO, DigitalOcean Spaces, etc.):

```python
import asyncio

from deepagents import create_deep_agent
from deepagents_backends import S3Backend, S3Config
from langchain_anthropic import ChatAnthropic


def create_model() -> ChatAnthropic:
    return ChatAnthropic(
        model_name="claude-sonnet-4-5-20250929",
        max_tokens=20000,
        betas=["prompt-caching-2024-07-31"],
    )


async def main():
    config = S3Config(
        bucket="my-agent-bucket",
        prefix="agent-workspace",
        endpoint_url="http://localhost:9000",  # remove for AWS S3
        access_key_id="minioadmin",
        secret_access_key="minioadmin",
        use_ssl=False,
    )

    agent = create_deep_agent(
        model=create_model(),
        backend=S3Backend(config),
        system_prompt="You are a helpful assistant. Files persist in S3.",
    )

    result = await agent.ainvoke({
        "messages": [{"role": "user", "content": "Create a Python calculator module in /src/"}]
    })
    print(result)


asyncio.run(main())
```

### PostgreSQL

Store agent files in PostgreSQL with connection pooling for high-performance scenarios:

```python
import asyncio
import sys

from deepagents import create_deep_agent
from deepagents_backends import PostgresBackend, PostgresConfig
from langchain_anthropic import ChatAnthropic

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def create_model() -> ChatAnthropic:
    return ChatAnthropic(
        model_name="claude-sonnet-4-5-20250929",
        max_tokens=20000,
        betas=["prompt-caching-2024-07-31"],
    )


async def main():
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
        agent = create_deep_agent(
            model=create_model(),
            backend=backend,
            system_prompt="You are a data analyst. Files persist in PostgreSQL.",
        )

        result = await agent.ainvoke({
            "messages": [{"role": "user", "content": "Create a data analysis project in /analysis/"}]
        })
        print(result)
    finally:
        await backend.close()


asyncio.run(main())
```

### Azure Blob Storage

```python
import asyncio

from deepagents import create_deep_agent
from deepagents_backends import AzureBlobBackend, AzureBlobConfig
from langchain_anthropic import ChatAnthropic


def create_model() -> ChatAnthropic:
    return ChatAnthropic(
        model_name="claude-sonnet-4-5-20250929",
        max_tokens=20000,
        betas=["prompt-caching-2024-07-31"],
    )


async def main():
    backend = AzureBlobBackend(
        AzureBlobConfig(
            container="agent-files",
            prefix="agent-workspace",
            connection_string="DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;",
        )
    )
    await backend.ensure_container()

    try:
        agent = create_deep_agent(
            model=create_model(),
            backend=backend,
            system_prompt="You are a helpful assistant. Files persist in Azure Blob.",
        )

        result = await agent.ainvoke({
            "messages": [{"role": "user", "content": "Set up a project scaffold in /src/"}]
        })
        print(result)
    finally:
        await backend.close()


asyncio.run(main())
```

### Google Cloud Storage

```python
import asyncio

from deepagents import create_deep_agent
from deepagents_backends import GCSBackend, GCSConfig
from langchain_anthropic import ChatAnthropic


def create_model() -> ChatAnthropic:
    return ChatAnthropic(
        model_name="claude-sonnet-4-5-20250929",
        max_tokens=20000,
        betas=["prompt-caching-2024-07-31"],
    )


async def main():
    backend = GCSBackend(
        GCSConfig(
            bucket="my-agent-bucket",
            prefix="agent-workspace",
            service_file="/path/to/service-account.json",  # omit to use ADC
        )
    )

    try:
        agent = create_deep_agent(
            model=create_model(),
            backend=backend,
            system_prompt="You are a helpful assistant. Files persist in GCS.",
        )

        result = await agent.ainvoke({
            "messages": [{"role": "user", "content": "Create a Python calculator module in /src/"}]
        })
        print(result)
    finally:
        await backend.close()


asyncio.run(main())
```

### MongoDB

```python
import asyncio

from deepagents import create_deep_agent
from deepagents_backends import MongoDBBackend, MongoDBConfig
from langchain_anthropic import ChatAnthropic


def create_model() -> ChatAnthropic:
    return ChatAnthropic(
        model_name="claude-sonnet-4-5-20250929",
        max_tokens=20000,
        betas=["prompt-caching-2024-07-31"],
    )


async def main():
    backend = MongoDBBackend(
        MongoDBConfig(
            connection_uri="mongodb://localhost:27017",
            database="deepagents",
            collection="agent_files",
        )
    )
    await backend.initialize()

    try:
        agent = create_deep_agent(
            model=create_model(),
            backend=backend,
            system_prompt="You are a helpful assistant. Files persist in MongoDB.",
        )

        result = await agent.ainvoke({
            "messages": [{"role": "user", "content": "Create a project structure in /src/"}]
        })
        print(result)
    finally:
        await backend.close()


asyncio.run(main())
```

### Redis / Valkey

```python
import asyncio

from deepagents import create_deep_agent
from deepagents_backends import RedisBackend, RedisConfig
from langchain_anthropic import ChatAnthropic


def create_model() -> ChatAnthropic:
    return ChatAnthropic(
        model_name="claude-sonnet-4-5-20250929",
        max_tokens=20000,
        betas=["prompt-caching-2024-07-31"],
    )


async def main():
    backend = RedisBackend(
        RedisConfig(
            url="redis://localhost:6379/0",
            namespace="deepagents",
            prefix="agent-workspace",
        )
    )

    try:
        agent = create_deep_agent(
            model=create_model(),
            backend=backend,
            system_prompt="You are a helpful assistant. Files persist in Redis.",
        )

        result = await agent.ainvoke({
            "messages": [{"role": "user", "content": "Create a Python calculator module in /src/"}]
        })
        print(result)
    finally:
        await backend.close()


asyncio.run(main())
```

## 🔀 Composite Backend (Hybrid Storage)

Route different paths to different backends for optimal storage:

```python
import asyncio
import sys

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend
from deepagents_backends import PostgresBackend, PostgresConfig, S3Backend, S3Config
from langchain_anthropic import ChatAnthropic

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def create_model() -> ChatAnthropic:
    return ChatAnthropic(
        model_name="claude-sonnet-4-5-20250929",
        max_tokens=20000,
        betas=["prompt-caching-2024-07-31"],
    )


async def main():
    s3_backend = S3Backend(
        S3Config(
            bucket="my-asset-bucket",
            prefix="agent-assets",
            region="us-east-1",
        )
    )
    pg_backend = PostgresBackend(
        PostgresConfig(
            host="localhost",
            port=5432,
            database="deepagents",
            user="postgres",
            password="postgres",
            table="agent_files",
        )
    )
    await pg_backend.initialize()

    try:
        agent = create_deep_agent(
            model=create_model(),
            backend=lambda runtime: CompositeBackend(
                default=StateBackend(runtime),
                routes={
                    "/assets/": s3_backend,
                    "/data/": pg_backend,
                    "/memories/": pg_backend,
                },
            ),
        )

        await agent.ainvoke({
            "messages": [{"role": "user", "content": "Set up a hybrid workspace under /assets and /data."}]
        })
    finally:
        await pg_backend.close()


asyncio.run(main())
```

## 🔧 Backend protocol coverage

All backends implement the full `BackendProtocol` with sync and async methods:

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

Text-oriented files are stored as JSON with line arrays for efficient line-based operations:

```json
{
  "content": ["line 1", "line 2", "line 3"],
  "created_at": "2025-01-07T12:00:00Z",
  "modified_at": "2025-01-07T12:30:00Z"
}
```

## 📚 Examples

See the [examples/](https://github.com/DiTo97/deepagents-backends/blob/main/examples/) directory for complete, runnable examples:

| Example | Description |
|---|---|
| [examples/s3_deep_agent.py](https://github.com/DiTo97/deepagents-backends/blob/main/examples/s3_deep_agent.py) | Full S3 backend with streaming and custom tools |
| [examples/postgres_deep_agent.py](https://github.com/DiTo97/deepagents-backends/blob/main/examples/postgres_deep_agent.py) | PostgreSQL with multi-agent and sub-agent workflows |
| [examples/composite_backend.py](https://github.com/DiTo97/deepagents-backends/blob/main/examples/composite_backend.py) | Hybrid S3 + PostgreSQL storage with routing |
| [examples/basic_usage.py](https://github.com/DiTo97/deepagents-backends/blob/main/examples/basic_usage.py) | Low-level backend API operations |

### Running examples locally

```bash
# Start all local services
docker-compose up -d

# Run an example
uv run examples/s3_deep_agent.py
```

## 📊 Benchmarks

Latency benchmarks across all backends (filesystem baseline vs. remote backends) live in [`benchmark/`](https://github.com/DiTo97/deepagents-backends/blob/main/benchmark/README.md). Results are regenerated by running:

```bash
uv run python benchmark/run.py --manage-services --write-readme
```

## 🧪 Development

```bash
# Install dependencies
uv sync

# Unit tests (mocked, no Docker)
uv run pytest -m unit

# Integration tests (Docker services started automatically)
uv run pytest -m integration

# Backend-specific integration subsets
uv run pytest -m "integration and azure"
uv run pytest -m "integration and gcs"
uv run pytest -m "integration and mongodb"
uv run pytest -m "integration and redis"

# Lint
uv run ruff check .
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
- `PostgresBackend`, `MongoDBBackend`, and `RedisBackend` hold open connections; always call `close()` when done.

## 📄 License

MIT License — see [LICENSE](https://github.com/DiTo97/deepagents-backends/blob/main/LICENSE).
