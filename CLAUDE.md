# Deep Agents Remote Backends

This repository currently supports these backends:

- S3 / MinIO
- PostgreSQL
- Azure Blob Storage / Azurite
- Google Cloud Storage / fake-gcs-server
- MongoDB
- Redis / Valkey

Backend-specific details live in `wiki/`:

- `wiki/s3.md`
- `wiki/postgresql.md`
- `wiki/azure-blob.md`
- `wiki/gcs.md`
- `wiki/mongodb.md`
- `wiki/redis-valkey.md`

Useful repository files:

- `src/deepagents_backends/__init__.py`
- `docker-compose.yml`
- `tests/`
- `benchmark/run.py`
- `benchmark/README.md`
- `benchmark/web/`
- `.github/workflows/pages.yml`

Assistant notes:

- Prefer repository-relative commands and paths in docs; do not hardcode sandbox-specific `/home/...` paths.
- The benchmark docs are generated from `benchmark/run.py`; keep `benchmark/README.md` aligned with the generator.
- The benchmark dashboard reads `benchmark/results/latest.json` from the static assets in `benchmark/web/`.
- If you update benchmark presentation or deployment behavior, review both `benchmark/web/` and `.github/workflows/pages.yml`.

Common development commands:

```bash
uv sync
uv run ruff check .
uv run pytest -m unit
uv run pytest -m integration
uv run python benchmark/run.py --manage-services --write-readme
```
