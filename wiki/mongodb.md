# MongoDB Backend

`MongoDBBackend` stores files as MongoDB documents.

## Config

Use `MongoDBConfig` with:

- `connection_uri`
- `database`
- `collection`
- `prefix`
- `server_selection_timeout_ms`

## Local development

- Service: MongoDB
- Port: `27017`

## Lifecycle

```python
backend = MongoDBBackend(config)
await backend.initialize()
...
await backend.close()
```

## Notes

- Each document stores `path`, `content`, `created_at`, and `modified_at`.
- `initialize()` creates indexes on `path` and `modified_at`.
- `upload_files()` stores decoded text content.
- Sync wrappers recreate loop-safe clients when needed.
