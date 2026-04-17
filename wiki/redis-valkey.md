# Redis / Valkey Backend

`RedisBackend` stores files in Redis-compatible key-value storage such as Redis or Valkey.

## Config

Use `RedisConfig` with:

- `url`
- `prefix`
- `namespace`

## Local development

- Service: Valkey
- Port: `6379`

## Notes

- File payloads are stored as JSON values.
- A Redis set index tracks known storage paths for listing, globbing, and grep.
- `upload_files()` stores decoded text content.
- Sync wrappers recreate loop-safe clients when needed.
