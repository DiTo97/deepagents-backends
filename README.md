# 🗄️ Deep Agents Remote Backends

**deepagents-backends** provides production-ready implementations of the [LangChain Deep Agents](https://github.com/langchain-ai/deepagents)' `BackendProtocol` for remote file storage, allowing your agents to maintain state across restarts and share files in distributed environments.

Store agent files in **S3** or **PostgreSQL** instead of ephemeral state, enabling persistent storage, distributed execution, and multi-agent file sharing.

## 🚀 Quickstart

```bash
pip install deepagents-backends
```

### S3 Backend

Store agent files in AWS S3 or any S3-compatible storage (MinIO, DigitalOcean Spaces, etc.):

```python
import asyncio

from deepagents import create_deep_agent
from deepagents_backends import S3Backend, S3Config
from langchain_anthropic import ChatAnthropic


def create_default_model() -> ChatAnthropic:
    return ChatAnthropic(
        model_name="claude-sonnet-4-5-20250929",
        max_tokens=20000,
        betas=["prompt-caching-2024-07-31"],
    )


async def main():
    config = S3Config(
        bucket="my-agent-bucket",
        prefix="agent-workspace",
        endpoint_url="http://localhost:9000",  # Remove for AWS S3
        access_key_id="minioadmin",
        secret_access_key="minioadmin",
        use_ssl=False,
    )

    agent = create_deep_agent(
        model=create_default_model(),
        backend=S3Backend(config),
        system_prompt="You are a helpful assistant. Files persist in S3.",
    )

    result = await agent.ainvoke({
        "messages": [{"role": "user", "content": "Create a Python calculator module in /src/"}]
    })

    print(result)


asyncio.run(main())
```

### PostgreSQL Backend

Store agent files in PostgreSQL with connection pooling for high-performance scenarios:

```python
import asyncio
import sys

from deepagents import create_deep_agent
from deepagents_backends import PostgresBackend, PostgresConfig
from langchain_anthropic import ChatAnthropic

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def create_default_model() -> ChatAnthropic:
    return ChatAnthropic(
        model_name="claude-sonnet-4-5-20250929",
        max_tokens=20000,
        betas=["prompt-caching-2024-07-31"],
    )


async def main():
    config = PostgresConfig(
        host="localhost",
        port=5432,
        database="deepagents",
        user="postgres",
        password="postgres",
        table="agent_files",
    )

    backend = PostgresBackend(config)
    await backend.initialize()

    try:
        agent = create_deep_agent(
            model=create_default_model(),
            backend=backend,
            system_prompt="You are a data analyst. Files persist in PostgreSQL.",
        )

        result = await agent.ainvoke({
            "messages": [{"role": "user", "content": "Create a data analysis project in /analysis/"}]
        })
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


def create_default_model() -> ChatAnthropic:
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
            model=create_default_model(),
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

## 📚 Examples

See the [examples/](examples/) directory for complete, runnable examples:

| Example | Description |
|---------|-------------|
| [s3_deep_agent.py](examples/s3_deep_agent.py) | Full S3 backend with streaming and custom tools |
| [postgres_deep_agent.py](examples/postgres_deep_agent.py) | PostgreSQL with multi-agent and sub-agent workflows |
| [composite_backend.py](examples/composite_backend.py) | Hybrid S3 + PostgreSQL storage with routing |
| [basic_usage.py](examples/basic_usage.py) | Low-level backend API operations |

### Running Examples Locally

```bash
# Start MinIO and PostgreSQL
docker-compose up -d

# Run an example
uv run examples/s3_deep_agent.py
```

## ⚙️ Configuration

### S3Config

```python
S3Config(
    bucket="my-bucket",              # Required: S3 bucket name
    prefix="agent-files",            # Key prefix for all files
    region="us-west-2",              # AWS region (default: us-east-1)
    endpoint_url=None,               # Custom endpoint (MinIO, etc.)
    access_key_id=None,              # AWS credentials (or use IAM role)
    secret_access_key=None,
    use_ssl=True,                    # Use HTTPS
    max_pool_connections=50,         # Connection pool size
    connect_timeout=5.0,             # Connection timeout (seconds)
    read_timeout=30.0,               # Read timeout (seconds)
    max_retries=3,                   # Retry attempts
)
```

### PostgresConfig

```python
PostgresConfig(
    host="localhost",                # PostgreSQL host
    port=5432,                       # PostgreSQL port
    database="deepagents",           # Database name
    user="postgres",                 # Username
    password="postgres",             # Password
    table="agent_files",             # Table name for file storage
    min_pool_size=5,                 # Minimum connections in pool
    max_pool_size=20,                # Maximum connections in pool
    sslmode="prefer",                # SSL mode (use "require" in production)
)
```

## 🔧 Backend Protocol

Both backends implement the full `BackendProtocol` with sync and async methods:

| Method | Description |
|--------|-------------|
| `read` / `aread` | Read file content (supports offset/limit pagination) |
| `write` / `awrite` | Create new file (fails if exists) |
| `edit` / `aedit` | Edit file with string replacement |
| `ls_info` / `als_info` | List directory contents |
| `glob_info` / `aglob_info` | Find files matching glob pattern |
| `grep_raw` / `agrep_raw` | Search files with line-numbered results |
| `upload_files` / `aupload_files` | Batch upload raw bytes |
| `download_files` / `adownload_files` | Batch download as bytes |

### File Storage Format

Files are stored as JSON with line arrays for efficient line-based operations:

```json
{
  "content": ["line 1", "line 2", "line 3"],
  "created_at": "2025-01-07T12:00:00Z",
  "modified_at": "2025-01-07T12:30:00Z"
}
```

## 🧪 Development

```bash
# Install dev dependencies
uv sync

# Unit tests (mocked, no Docker)
uv run pytest -m unit

# Integration tests (Docker services started automatically via pytest-docker)
uv run pytest -m integration

# All tests
uv run pytest
```

### Docker Services

| Service | Port | Credentials |
|---------|------|-------------|
| MinIO (S3) | 9000 | `minioadmin` / `minioadmin` |
| MinIO Console | 9001 | `minioadmin` / `minioadmin` |
| PostgreSQL | 5432 | `postgres` / `postgres` |

## 🔒 Security

- **Credentials**: Use environment variables or IAM roles, never commit secrets
- **PostgreSQL**: Use `sslmode="require"` in production
- **S3**: Use `use_ssl=True` in production
- **Connection pooling**: PostgresBackend maintains a connection pool—always call `close()`

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.
