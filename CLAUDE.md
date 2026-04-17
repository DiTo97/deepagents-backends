# Deep Agents Remote Backends

This repository currently supports these backends:

- S3 / MinIO
- PostgreSQL
- Azure Blob Storage / Azurite
- Google Cloud Storage / fake-gcs-server
- MongoDB
- Redis / Valkey

Backend-specific details live in `wiki/`:

- `wiki/S3.md`
- `wiki/PostgreSQL.md`
- `wiki/Azure-Blob.md`
- `wiki/GCS.md`
- `wiki/MongoDB.md`
- `wiki/Redis-Valkey.md`

Useful repository files:

- `src/deepagents_backends/__init__.py`
- `docker-compose.yml`
- `tests/`
- `benchmark/run.py`
- `benchmark/README.md`

Common development commands:

```bash
uv sync
uv run ruff check .
uv run pytest -m unit
uv run pytest -m integration
uv run python benchmark/run.py --manage-services --write-readme
```
