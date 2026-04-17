# GCS Backend

`GCSBackend` stores files in Google Cloud Storage-compatible object storage.

## Config

Use `GCSConfig` with:

- `bucket`
- `prefix`
- `service_file`
- `api_root`

## Local development

- Service: fake-gcs-server
- Port: `4443`
- Local tests use `api_root=http://127.0.0.1:4443`

## Notes

- The backend uses `gcloud-aio-storage`.
- Local integration tests create buckets through the JSON API.
- `upload_files()` and `download_files()` operate on raw object bytes.
- Sync wrappers lazily create loop-safe async clients.
