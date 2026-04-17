# Azure Blob Backend

`AzureBlobBackend` stores files in Azure Blob Storage or Azurite.

## Config

Use `AzureBlobConfig` with:

- `container`
- `prefix`
- `connection_string` or `account_url`
- optional `credential`

## Local development

- Service: Azurite
- Port: `10000`
- The repository runs Azurite with `--skipApiVersionCheck` for current SDK compatibility.

## Lifecycle

Create the container before use when needed:

```python
backend = AzureBlobBackend(config)
await backend.ensure_container()
...
await backend.close()
```

## Notes

- Virtual paths map to blob names under `{prefix}/...`.
- `upload_files()` and `download_files()` operate on raw blob bytes.
- Sync wrappers recreate async clients safely across event loops.
