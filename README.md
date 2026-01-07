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
from deepagents import create_deep_agent
from deepagents_backends import S3Backend, S3Config

# Configure S3 (or MinIO for local development)
config = S3Config(
    bucket="my-agent-bucket",
    prefix="agent-workspace",
    endpoint_url="http://localhost:9000",  # Remove for AWS S3
    access_key_id="minioadmin",
    secret_access_key="minioadmin",
    use_ssl=False,
)

# Create agent with S3 backend
agent = create_deep_agent(
    backend=S3Backend(config),
    system_prompt="You are a helpful assistant. Files persist in S3.",
)

# Run the agent - all file operations use S3
result = agent.invoke({
    "messages": [{"role": "user", "content": "Create a Python calculator module in /src/"}]
})
```

### PostgreSQL Backend

Store agent files in PostgreSQL with connection pooling for high-performance scenarios:

```python
import asyncio
from deepagents import create_deep_agent
from deepagents_backends import PostgresBackend, PostgresConfig

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
    await backend.initialize()  # Creates table + indexes

    try:
        agent = create_deep_agent(
            backend=backend,
            system_prompt="You are a data analyst. Files persist in PostgreSQL.",
        )

        result = await agent.ainvoke({
            "messages": [{"role": "user", "content": "Create a data analysis project in /analysis/"}]
        })
    finally:
        await backend.close()  # Always close the connection pool

asyncio.run(main())
```

## 🔀 Composite Backend (Hybrid Storage)

Route different paths to different backends for optimal storage:

```python
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend
from deepagents_backends import S3Backend, S3Config, PostgresBackend, PostgresConfig

# S3 for large files, PostgreSQL for structured data
s3_backend = S3Backend(S3Config(bucket="assets", ...))
pg_backend = PostgresBackend(PostgresConfig(...))
await pg_backend.initialize()

agent = create_deep_agent(
    backend=CompositeBackend(
        default=StateBackend(),  # Ephemeral working files
        routes={
            "/assets/": s3_backend,    # Large files → S3
            "/data/": pg_backend,      # Structured data → PostgreSQL
            "/memories/": pg_backend,  # Long-term memory → PostgreSQL
        },
    ),
)
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
python examples/s3_deep_agent.py
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
    min_pool_size=2,                 # Minimum connections in pool
    max_pool_size=10,                # Maximum connections in pool
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
