# PostgreSQL Backend

`PostgresBackend` stores files in a PostgreSQL table with connection pooling.

## Config

Use `PostgresConfig` with:

- `host`
- `port`
- `database`
- `user`
- `password`
- `table`
- `schema`
- `min_pool_size`
- `max_pool_size`
- `sslmode`

## Local development

- Service: PostgreSQL
- Port: `5432`
- Test database: `deepagents_test`
- Test credentials: `postgres / postgres`

## Lifecycle

```python
backend = PostgresBackend(config)
await backend.initialize()
...
await backend.close()
```

## Notes

- Files are stored as JSONB content plus timestamps.
- `initialize()` creates the table and indexes.
- `upload_files()` stores decoded text content rather than opaque binary blobs.
