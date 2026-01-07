# AGENTS.md: Deep Agents Remote Backends

## Project Overview

This library provides **S3Backend** and **PostgresBackend** implementations of [LangChain Deep Agents'](https://github.com/langchain-ai/deepagents) `BackendProtocol` for remote file storage and middleware operations.

**Installation:** `uv add deepagents-backends` or `uv sync` for development.

## Architecture

### Core Module Structure
- **Single module design**: All backend code lives in [src/deepagents_backends/__init__.py](src/deepagents_backends/__init__.py)
- **Two backends**: `S3Backend` (AWS S3/MinIO) and `PostgresBackend` (with connection pooling)
- **Config dataclasses**: `S3Config` and `PostgresConfig` handle connection parameters

### File Storage Pattern
Files are stored as **JSON with line arrays**, not raw text:
```python
{"content": ["line1", "line2", ...], "created_at": "...", "modified_at": "..."}
```
This enables line-based operations (offset/limit reads, line-numbered grep results).

### BackendProtocol Methods
Each backend implements both sync and async versions:
- `read`/`aread`, `write`/`awrite`, `edit`/`aedit`
- `ls_info`/`als_info`, `glob_info`/`aglob_info`, `grep_raw`/`agrep_raw`
- `upload_files`/`aupload_files`, `download_files`/`adownload_files`

Sync methods use `run_async_safely()`.

## Build and Test Commands

```bash
# Install dev dependencies
uv sync

# Unit tests only (mocked, no Docker)
uv run pytest -m unit

# Integration tests (Docker services started automatically via pytest-docker)
uv run pytest -m integration

# Specific backend tests
uv run pytest -m s3          # S3/MinIO tests
uv run pytest -m postgres    # PostgreSQL tests

# Run all tests
uv run pytest
```

### Docker Services (managed by pytest-docker)
Services are automatically started/stopped by pytest-docker using `docker-compose.yml`:
- **MinIO** (S3-compatible): credentials `minioadmin/minioadmin`
- **PostgreSQL**: database `deepagents_test`, credentials `postgres/postgres`

For manual testing or running examples:
```bash
docker-compose up -d      # Start services
docker-compose down -v    # Stop and cleanup
```

## Code Style Guidelines

- **Python 3.12+** required
- **Type hints**: All public methods must have complete type annotations
- **Async-first**: Implement `amethod()` first, then create sync wrapper `method()` using `run_until_complete()`
- **Docstrings**: Use triple-quoted docstrings for all public classes/methods
- **Imports**: Group stdlib → third-party → local; use `from __future__ import annotations`

## Testing Instructions

### Test Structure
- **Unit tests** (`tests/unit/`): Mock external services with `AsyncMock`
- **Integration tests** (`tests/integration/`): Use real Docker services via `pytest-docker`
- Fixtures auto-apply markers based on file location (see `conftest.py:pytest_collection_modifyitems`)

### Test Conventions
- Use `pytest.mark.asyncio` implicitly (configured via `asyncio_mode = "auto"`)
- Unit test fixtures: `s3_config_unit`, `postgres_config_unit` (won't connect)
- Integration fixtures: `s3_backend`, `postgres_backend` (real connections)
- Always test both success and error paths

## Key Patterns

### Write vs Edit Semantics
- `awrite()` **fails if file exists** - prevents accidental overwrites
- `aedit()` uses string replacement via `perform_string_replacement` from deepagents

### PostgresBackend Lifecycle
```python
backend = PostgresBackend(config)
await backend.initialize()  # Creates table + indexes
# ... use backend ...
await backend.close()       # Required: closes connection pool
```

### S3Backend Path Mapping
Virtual paths like `/src/file.py` map to S3 keys: `{prefix}/src/file.py`

## Security Considerations

- **Never commit credentials**: Use environment variables or config files outside repo
- **Connection strings**: `PostgresConfig.conninfo` builds connection strings - ensure passwords are not logged
- **S3 credentials**: `S3Config` accepts `access_key_id`/`secret_access_key` - prefer IAM roles in production
- **SSL/TLS**: Set `sslmode="require"` for PostgreSQL and `use_ssl=True` for S3 in production

## Commit and PR Guidelines

- **Commit messages**: Use conventional commits format (`feat:`, `fix:`, `docs:`, `test:`, `chore:`)
- **PRs**: Include tests for new functionality; update docstrings if API changes
- **Breaking changes**: Document in commit body and PR description
